"""Update platform for Dockhand container image updates.

Each container gets an UpdateEntity that reflects whether a newer image
digest is available. The "Install" button triggers Dockhand's safe-pull
workflow (POST /api/containers/batch-update), which includes vulnerability
scanning if configured in Dockhand — no extra HA-side coordination needed.

Version string strategy:
  installed_version — first 12 hex chars of the sha256 from currentDigest.
                      currentDigest format: "image@sha256:<hex>"
  latest_version    — same as installed_version when up to date.
                      When hasUpdate=True, first 12 hex chars of newDigest.
                      newDigest format: "sha256:<hex>" (no image prefix).

Both digest fields are present in the API response. newDigest only appears
when hasUpdate=True; it is absent (not null) when no update is available.

Install is suppressed for:
  - updateDisabled=True  (dockhand.update=false label on the container)
  - systemContainer!=None (Dockhand infrastructure containers like hawser
                           that cannot be updated through the batch-update API)
"""

import logging

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import DOMAIN
from .coordinator import DockhandFastCoordinator, DockhandUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Updates trigger safe-pull via the API — serialise to avoid concurrent pulls
# on the same host. 0 = coordinator manages updates, no HA-level parallelism limit.
PARALLEL_UPDATES = 0


def _short_digest(digest: str) -> str:
    """Return a short human-readable version string from a digest reference.

    Handles both formats returned by the API:
      currentDigest: "ghcr.io/finsys/hawser@sha256:53bb1e23fb302f..."
      newDigest:     "sha256:79f926e8d8fe31c0dfe90858f90b69bfd4cfbb..."

    Returns the first 12 hex chars of the sha256, e.g. "53bb1e23fb30".
    Falls back to the raw digest string if parsing fails.
    """
    try:
        sha_part = digest.split("sha256:")[-1]
        return sha_part[:12] if sha_part else digest
    except Exception:
        return digest


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up container update entities."""
    data = entry.runtime_data
    update_coordinator = data.update_coordinator
    fast_coordinator = data.fast_coordinator

    if update_coordinator is None:
        return

    seen: set[str] = set()

    def _add_new_entities() -> None:
        nonlocal seen
        update_data = update_coordinator.data or {}
        fast_data = fast_coordinator.data or {}
        new_entities = []

        for env_id, by_container_id in update_data.items():
            env_fast = fast_data.get(env_id, {})
            stats = env_fast.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")

            for container_id, item in by_container_id.items():
                uid = f"dockhand_update_{container_id}"
                if uid in seen:
                    continue
                seen.add(uid)
                new_entities.append(
                    ContainerUpdateEntity(
                        fast_coordinator=fast_coordinator,
                        update_coordinator=update_coordinator,
                        env_id=env_id,
                        env_name=env_name,
                        container_id=container_id,
                        item=item,
                    )
                )

        if new_entities:
            async_add_entities(new_entities)

    # Add entities for initial data
    _add_new_entities()

    # Re-run on each coordinator update to pick up new containers
    entry.async_on_unload(update_coordinator.async_add_listener(_add_new_entities))


class ContainerUpdateEntity(CoordinatorEntity[DockhandUpdateCoordinator], UpdateEntity):
    """Update entity for a single container's image update status."""

    _attr_has_entity_name = True

    def __init__(
        self,
        fast_coordinator: DockhandFastCoordinator,
        update_coordinator: DockhandUpdateCoordinator,
        env_id: int,
        env_name: str,
        container_id: str,
        item: dict,
    ) -> None:
        super().__init__(update_coordinator)
        self._fast_coordinator = fast_coordinator
        self._env_id = env_id
        self._container_id = container_id
        self._container_name = item.get("containerName", container_id)

        self._attr_unique_id = f"dockhand_update_{container_id}"
        self._attr_translation_key = "image_update"

        # Device: attach to the existing container device created by fast coordinator
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"container_{container_id}")},
        )

        # Install is supported unless updateDisabled — re-evaluated on each update
        self._update_supported_features()

    def _item(self) -> dict:
        """Return the current update payload for this container, or empty dict."""
        update_data = self.coordinator.data or {}
        env_data = update_data.get(self._env_id, {})
        return env_data.get(self._container_id, {})

    def _update_supported_features(self) -> None:
        item = self._item()
        update_disabled = item.get("updateDisabled", False)
        is_system = item.get("systemContainer") is not None
        if update_disabled or is_system:
            self._attr_supported_features = UpdateEntityFeature(0)
        else:
            self._attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def installed_version(self) -> str | None:
        item = self._item()
        digest = item.get("currentDigest", "")
        return _short_digest(digest) if digest else None

    @property
    def latest_version(self) -> str | None:
        item = self._item()
        if not item:
            return self.installed_version
        if item.get("hasUpdate"):
            new_digest = item.get("newDigest", "")
            return _short_digest(new_digest) if new_digest else self.installed_version
        return self.installed_version

    @property
    def release_summary(self) -> str | None:
        item = self._item()
        if not item:
            return None
        parts = []
        image_name = item.get("imageName")
        if image_name:
            parts.append(f"Image: {image_name}")
        if item.get("systemContainer"):
            parts.append(
                "Dockhand system container — update must be applied"
                " outside of Home Assistant."
            )
        elif item.get("updateDisabled"):
            parts.append("Updates disabled via dockhand.update=false label.")
        return "\n".join(parts) if parts else None

    @property
    def available(self) -> bool:
        # Entity is unavailable if the container no longer appears in either
        # coordinator's data. Fast data confirms the container still exists;
        # update data confirms the update coordinator has current information.
        fast_data = self._fast_coordinator.data or {}
        env_containers = fast_data.get(self._env_id, {}).get("containers") or []
        container_exists = any(
            c.get("id") == self._container_id for c in env_containers
        )
        return container_exists and super().available

    def _handle_coordinator_update(self) -> None:
        self._update_supported_features()
        super()._handle_coordinator_update()

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        """Trigger Dockhand's safe-pull update for this container."""
        await self.coordinator.client.async_batch_update_container(
            self._env_id, self._container_id
        )
        # Request an update check refresh so the entity state reflects the result
        await self.coordinator.async_request_refresh()
