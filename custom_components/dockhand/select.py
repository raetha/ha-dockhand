"""Select platform for Dockhand's in-place restart-policy control.

Same scope and rationale as number.py (see docs/update-runtime-design.md and
number.py's module docstring): stack-less containers only, gated behind
CONF_ENABLE_RUNTIME_CONTROLS, optimistic state update. Restart policy has no
OOM-kill-style failure mode the way lowering Memory does, so there's no
auto-revert safety check here — only the shared warnings-to-repair-issue
handling.
"""

from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import CONF_ENABLE_RUNTIME_CONTROLS, DOMAIN
from .coordinator import DockhandFastCoordinator, DockhandSlowCoordinator
from .entity_defaults import enabling_chosen
from .env_settings import (
    IMAGE_PRUNE,
    SCANNER,
    DockhandEnvSettingEntity,
    EnvSettingDescription,
    build_setting_entities,
)
from .helpers import (
    _all_envs,
    _compose_project,
    _coordinator_env,
    _device_id_container,
    _device_id_instance,
    _find_container,
    already_registered,
    async_dockhand_action,
    create_issue,
)

PARALLEL_UPDATES = 0

_RESTART_POLICY_OPTIONS = ["no", "always", "unless-stopped", "on-failure"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities = enabling_chosen(
        entry.entry_id, entry.options, async_add_entities
    )
    data = entry.runtime_data

    def _add_settings() -> None:
        if new := build_setting_entities(
            hass, entry, "select", ENV_SETTING_SELECTS, DockhandEnvSettingSelect
        ):
            async_add_entities(new)

    _add_settings()
    entry.async_on_unload(data.fast_coordinator.async_add_listener(_add_settings))
    entry.async_on_unload(data.slow_coordinator.async_add_listener(_add_settings))

    # Dockhand's default scanner, once it can be read.
    default_added: list[bool] = []

    def _add_default() -> None:
        slow = data.slow_coordinator
        if default_added or (slow.data or {}).get("scanner_default") is None:
            return
        default_added.append(True)
        async_add_entities(
            [DockhandDefaultScannerSelect(slow, data.client, entry.entry_id)]
        )

    _add_default()
    entry.async_on_unload(data.slow_coordinator.async_add_listener(_add_default))

    # How Dockhand collects Docker's events, once it can be read.
    collection_added: list[bool] = []

    def _add_event_collection() -> None:
        slow = data.slow_coordinator
        if collection_added or not (slow.data or {}).get("event_collection"):
            return
        collection_added.append(True)
        async_add_entities(
            [
                DockhandEventCollectionSelect(slow, data.client, entry.entry_id),
                DockhandEventPollIntervalSelect(slow, data.client, entry.entry_id),
            ]
        )

    _add_event_collection()
    entry.async_on_unload(
        data.slow_coordinator.async_add_listener(_add_event_collection)
    )

    def _opt(key: str, default: Any) -> Any:
        return entry.options.get(key, default)

    if not _opt(CONF_ENABLE_RUNTIME_CONTROLS, False):
        return

    fast = data.fast_coordinator
    slow = data.slow_coordinator

    known_ids = entry.runtime_data.known_entity_ids
    pending_readd_ids = entry.runtime_data.pending_readd_entity_ids

    def _build_entities() -> list[SelectEntity]:
        new: list[SelectEntity] = []
        for env_id, env_data in _all_envs(fast.data).items():
            for container in env_data.get("containers") or []:
                if _compose_project(container):
                    continue
                if container.get("systemContainer"):
                    continue  # Dockhand itself, or a Hawser agent — same
                    # protection as switch.py/button.py/number.py;
                    # changing restart policy on Dockhand's own
                    # infrastructure could prevent it recovering from a
                    # crash.
                name = container.get("name", "")
                if not name:
                    continue
                entity = DockhandContainerRestartPolicySelect(
                    fast, slow, entry.entry_id, env_id, name
                )
                if already_registered(
                    hass,
                    known_ids,
                    "select",
                    entity.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    continue
                new.append(entity)
        return new

    async_add_entities(_build_entities())
    entry.async_on_unload(
        fast.async_add_listener(lambda: async_add_entities(_build_entities()))
    )


class DockhandContainerRestartPolicySelect(
    CoordinatorEntity[DockhandSlowCoordinator], SelectEntity
):
    """Restart policy for a stack-less container. Primary coordinator is the
    slow one (carries runtime_config); the fast coordinator is consulted
    directly for container existence/id — same dual-coordinator pattern as
    number.py and ContainerUpdateEntity (update.py)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "container_restart_policy"
    _attr_options = _RESTART_POLICY_OPTIONS

    def __init__(
        self,
        fast_coordinator: DockhandFastCoordinator,
        slow_coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        container_name: str,
    ) -> None:
        super().__init__(slow_coordinator)
        self._fast_coordinator = fast_coordinator
        self._entry_id = entry_id
        self._env_id = env_id
        self._container_name = container_name
        self._optimistic_value: str | None = None
        self._attr_unique_id = (
            f"{entry_id}_{env_id}_container_{container_name}_restart_policy"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, _device_id_container(entry_id, env_id, container_name))
            },
        )

    def _container(self) -> dict | None:
        return _find_container(
            self._fast_coordinator.data, self._env_id, self._container_name
        )

    def _runtime_config(self) -> dict:
        slow_data = self.coordinator.data or {}
        env = _coordinator_env(slow_data, self._env_id)
        return (env.get("runtime_config") or {}).get(self._container_name) or {}

    @property
    @override
    def available(self) -> bool:
        if self._container() is None or not super().available:
            return False
        env = _coordinator_env(self.coordinator.data, self._env_id)
        return "runtime_config" not in (env.get("fetch_failures") or set())

    @override
    def _handle_coordinator_update(self) -> None:
        self._optimistic_value = None
        super()._handle_coordinator_update()

    @property
    @override
    def current_option(self) -> str | None:
        if self._optimistic_value is not None:
            return self._optimistic_value
        value = self._runtime_config().get("restart_policy")
        return value if value in _RESTART_POLICY_OPTIONS else None

    @override
    async def async_select_option(self, option: str) -> None:
        c = self._container()
        if not c:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="container_not_found",
            )
        response = await async_dockhand_action(
            self._fast_coordinator.client.async_update_container_runtime(
                self._env_id, c["id"], {"RestartPolicy": {"Name": option}}
            )
        )

        warnings = response.get("warnings") or []
        if warnings:
            create_issue(
                self.hass,
                self._entry_id,
                f"runtime_update_warning_{self._entry_id}_{self._env_id}_"
                f"{self._container_name}_RestartPolicy",
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="runtime_update_warning",
                translation_placeholders={
                    "container": self._container_name,
                    "field": "RestartPolicy",
                    "warnings": "; ".join(str(w) for w in warnings),
                },
            )

        self._optimistic_value = option
        self.async_write_ha_state()


SCANNERS = ["none", "grype", "trivy", "both"]


@dataclass(frozen=True, kw_only=True)
class EnvSettingSelectDescription(EnvSettingDescription):
    options: list[str]


ENV_SETTING_SELECTS = (
    EnvSettingSelectDescription(
        key="vulnerability_scanner",
        read=SCANNER,
        unique_suffix="vulnerability_scanner",
        options=SCANNERS,
    ),
    EnvSettingSelectDescription(
        key="image_prune_mode",
        read=IMAGE_PRUNE,
        field="pruneMode",
        unique_suffix="prune_mode",
        options=["dangling", "all"],
    ),
)


class DockhandEnvSettingSelect(DockhandEnvSettingEntity, SelectEntity):
    """An environment setting with a few choices (env_settings.py)."""

    _setting: EnvSettingSelectDescription

    @property
    @override
    def options(self) -> list[str]:
        return self._setting.options

    @property
    @override
    def current_option(self) -> str | None:
        value = self._value
        return value if value in self._setting.options else None

    @override
    async def async_select_option(self, option: str) -> None:
        await self._save(option)


class DockhandDefaultScannerSelect(
    CoordinatorEntity[DockhandSlowCoordinator], SelectEntity
):
    """Dockhand's default vulnerability scanner, on the Dockhand device:
    the one every environment without its own uses."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "default_vulnerability_scanner"
    _attr_options = SCANNERS

    def __init__(
        self, coordinator: DockhandSlowCoordinator, client: Any, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{entry_id}_instance_vulnerability_scanner"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, _device_id_instance(entry_id))}
        )

    @property
    def _value(self) -> str | None:
        return (self.coordinator.data or {}).get("scanner_default")

    @property
    @override
    def available(self) -> bool:
        return super().available and self._value is not None

    @property
    @override
    def current_option(self) -> str | None:
        value = self._value
        return value if value in SCANNERS else None

    @override
    async def async_select_option(self, option: str) -> None:
        await async_dockhand_action(self._client.async_set_scanner(None, option))
        await self.coordinator.async_refresh_scanner_default()


EVENT_COLLECTION_MODES = ["stream", "poll"]


class DockhandEventCollectionSelect(
    CoordinatorEntity[DockhandSlowCoordinator], SelectEntity
):
    """How Dockhand collects Docker's events, on the Dockhand device: Stream
    as they happen, or Poll at an interval. Live updates and the Docker
    event entities depend on it (docs/data-updates.md)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "event_collection_mode"
    _attr_options = EVENT_COLLECTION_MODES

    def __init__(
        self, coordinator: DockhandSlowCoordinator, client: Any, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{entry_id}_instance_event_collection_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, _device_id_instance(entry_id))}
        )

    @property
    def _collection(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("event_collection") or {}

    @property
    @override
    def available(self) -> bool:
        return super().available and bool(self._collection)

    @property
    @override
    def current_option(self) -> str | None:
        mode = self._collection.get("mode")
        return mode if mode in EVENT_COLLECTION_MODES else None

    @override
    async def async_select_option(self, option: str) -> None:
        await async_dockhand_action(
            self._client.async_set_event_collection_mode(option)
        )
        await self.coordinator.async_refresh_event_collection()


# The poll intervals Dockhand offers, in seconds.
EVENT_POLL_INTERVALS = ["30", "60", "120", "300"]


class DockhandEventPollIntervalSelect(DockhandEventCollectionSelect):
    """How often Dockhand polls for events in Poll mode. Like Dockhand's
    own setting, only available while it polls."""

    _attr_translation_key = "event_poll_interval"
    _attr_options = EVENT_POLL_INTERVALS

    def __init__(
        self, coordinator: DockhandSlowCoordinator, client: Any, entry_id: str
    ) -> None:
        super().__init__(coordinator, client, entry_id)
        self._attr_unique_id = f"{entry_id}_instance_event_poll_interval"

    @property
    @override
    def available(self) -> bool:
        return super().available and self._collection.get("mode") == "poll"

    @property
    @override
    def current_option(self) -> str | None:
        interval = str(self._collection.get("interval"))
        return interval if interval in EVENT_POLL_INTERVALS else None

    @override
    async def async_select_option(self, option: str) -> None:
        await async_dockhand_action(
            self._client.async_set_event_poll_interval(int(option))
        )
        await self.coordinator.async_refresh_event_collection()
