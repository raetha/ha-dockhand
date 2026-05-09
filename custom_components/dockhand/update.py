"""Update platform for Dockhand container image updates.

Each container gets an UpdateEntity that reflects whether a newer image
digest is available. The "Install" button triggers a pull-and-recreate
via POST /api/containers/batch-update. Note: this API endpoint does not
apply vulnerability scanning or criteria evaluation — that workflow is
only available through the Dockhand UI. A warning is shown in the entity's
release summary when scanning is enabled on the environment.

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

# Updates trigger pull-and-recreate via the API — serialise to avoid concurrent
# pulls on the same host. 0 = coordinator manages updates, no HA-level limit.
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
                container_name = item.get("containerName", "")
                if not container_name:
                    continue
                # Key on env_id + container_name, not container_id.
                # Container IDs change every time a container is recreated
                # (e.g. after an image update), but the name is stable.
                uid = f"dockhand_update_{env_id}_{container_name}"
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
                        container_name=container_name,
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
    """Update entity for a single container's image update status.

    Identity is keyed on (env_id, container_name) rather than container_id.
    Container IDs (Docker hashes) change every time a container is recreated —
    which happens during every image update — so using the ID would cause the
    entity to be destroyed and recreated on each update. Container names are
    stable across updates and are the correct identity key here.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        fast_coordinator: DockhandFastCoordinator,
        update_coordinator: DockhandUpdateCoordinator,
        env_id: int,
        env_name: str,
        container_id: str,
        container_name: str,
        item: dict,
    ) -> None:
        super().__init__(update_coordinator)
        self._fast_coordinator = fast_coordinator
        self._env_id = env_id
        self._container_name = container_name

        # Unique ID is stable across container recreation — name-based not ID-based.
        self._attr_unique_id = f"dockhand_update_{env_id}_{container_name}"
        self._attr_translation_key = "image_update"

        # Device attachment: use the current container_id from the item to find
        # the container device. This is updated on each coordinator refresh via
        # _handle_coordinator_update calling _update_device_info(), so that after
        # an image update the entity re-attaches to the new container device.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"container_{item.get('containerId', '')}")},
        )

        self._update_supported_features()

    def _item(self) -> dict:
        """Return the current update payload for this container.

        Looks up by container name across the current coordinator data for this
        environment, since the container_id changes after every image update.
        Returns empty dict if the container is not currently present.
        """
        update_data = self.coordinator.data or {}
        env_data = update_data.get(self._env_id, {})
        # env_data is indexed by container_id — scan for matching name.
        for item in env_data.values():
            if item.get("containerName") == self._container_name:
                return item
        return {}

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

    def _scanner_enabled(self) -> bool:
        """Return True if vulnerability scanning is enabled on this environment."""
        fast_data = self._fast_coordinator.data or {}
        stats = fast_data.get(self._env_id, {}).get("stats") or {}
        return bool(stats.get("scannerEnabled", False))

    @property
    def release_summary(self) -> str | None:
        item = self._item()
        if not item:
            return None
        parts = []
        # Scanning warning always appears first so it's visible without scrolling.
        if self._scanner_enabled():
            parts.append(
                "⚠ Vulnerability scanning is enabled on this environment but is "
                "not applied when updating via Home Assistant. Verify the update "
                "in Dockhand after applying."
            )
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
        # Check by name in fast data — name is stable across container recreation.
        fast_data = self._fast_coordinator.data or {}
        env_containers = fast_data.get(self._env_id, {}).get("containers") or []
        container_exists = any(
            c.get("name") == self._container_name for c in env_containers
        )
        return container_exists and super().available

    def _update_device_info(self) -> None:
        """Re-attach to the current container device after a container recreation."""
        item = self._item()
        container_id = item.get("containerId", "")
        if container_id:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"container_{container_id}")},
            )

    def _handle_coordinator_update(self) -> None:
        self._update_supported_features()
        self._update_device_info()
        super()._handle_coordinator_update()

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        """Trigger a pull-and-recreate update for this container via Dockhand."""
        # Find the current container_id by name — it may have changed since init.
        item = self._item()
        container_id = item.get("containerId", "")
        if not container_id:
            _LOGGER.warning(
                "Dockhand: cannot update %s — container not found in update data",
                self._container_name,
            )
            return
        await self.coordinator.client.async_batch_update_container(
            self._env_id, container_id
        )
        # Request a refresh so the entity state reflects the result.
        await self.coordinator.async_request_refresh()
