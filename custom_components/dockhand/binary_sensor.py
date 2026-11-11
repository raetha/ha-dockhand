from typing import Any, override

# Home Assistant 2026.10 moved the class to binary_sensor.const, which the
# minimum supported version doesn't have; the package still re-exports it.
from homeassistant.components.binary_sensor import (  # type: ignore[attr-defined, unused-ignore]
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import CONF_API_URL, DOMAIN
from .coordinator import DockhandFastCoordinator, DockhandSlowCoordinator
from .entity_defaults import enabling_chosen
from .events import DockhandEventStream
from .helpers import (
    _all_envs,
    _coordinator_env,
    _device_id_instance,
    _env_device,
    _find_git_stack,
    _find_stack,
    _stack_device,
    already_registered,
)

# Coordinator-based read-only platform.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities = enabling_chosen(
        entry.entry_id, entry.options, async_add_entities
    )
    fast: DockhandFastCoordinator = entry.runtime_data.fast_coordinator
    slow: DockhandSlowCoordinator = entry.runtime_data.slow_coordinator
    base_url: str = entry.data.get(CONF_API_URL, "")

    known_ids = entry.runtime_data.known_entity_ids
    pending_readd_ids = entry.runtime_data.pending_readd_entity_ids

    def _build_fast_entities() -> list[BinarySensorEntity]:
        new: list[BinarySensorEntity] = []
        for env_id, env_data in _all_envs(fast.data).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")
            online_sensor = DockhandEnvOnlineSensor(
                fast, slow, entry.entry_id, env_id, base_url
            )
            if not already_registered(
                hass,
                known_ids,
                "binary_sensor",
                online_sensor.unique_id,
                pending_readd_ids=pending_readd_ids,
            ):
                # Activity logging, metrics, update checks, auto-update and
                # image pruning are switches (env_settings.py); scanning stays
                # a sensor, since its control picks a scanner, not on/off.
                new += [
                    online_sensor,
                    DockhandEnvScannerEnabledSensor(
                        fast, entry.entry_id, env_id, base_url
                    ),
                ]
            for stack in env_data.get("stacks") or []:
                if "updatesAvailable" not in stack:
                    continue
                stack_sensor = DockhandStackUpdatesAvailableBinarySensor(
                    fast, entry.entry_id, env_id, env_name, base_url, stack
                )
                if not already_registered(
                    hass,
                    known_ids,
                    "binary_sensor",
                    stack_sensor.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    new.append(stack_sensor)
        return new

    def _build_slow_entities() -> list[BinarySensorEntity]:
        new: list[BinarySensorEntity] = []
        slow_envs = _all_envs(slow.data)
        fast_data = _all_envs(fast.data)
        for env_id, env_data in slow_envs.items():
            fast_stats = (fast_data.get(env_id) or {}).get("stats") or {}
            env_name = fast_stats.get("name", f"Environment {env_id}")

            for git_stack in env_data.get("git_stacks") or []:
                git_sensor = DockhandGitStackSyncErrorBinarySensor(
                    slow,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                    git_stack,
                )
                if not already_registered(
                    hass,
                    known_ids,
                    "binary_sensor",
                    git_sensor.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    new.append(git_sensor)
        return new

    async_add_entities(
        [
            DockhandLiveUpdatesBinarySensor(
                entry.runtime_data.event_stream, entry.entry_id
            )
        ]
    )
    async_add_entities(_build_fast_entities())
    async_add_entities(_build_slow_entities())
    entry.async_on_unload(
        fast.async_add_listener(lambda: async_add_entities(_build_fast_entities()))
    )
    entry.async_on_unload(
        slow.async_add_listener(lambda: async_add_entities(_build_slow_entities()))
    )


class DockhandLiveUpdatesBinarySensor(BinarySensorEntity):
    """Whether Dockhand's activity feed is open, on the Dockhand device.
    Off also while no environment sends events, when there's nothing to
    receive (in_use says which)."""

    _attr_has_entity_name = True
    _attr_translation_key = "live_updates"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, stream: DockhandEventStream, entry_id: str) -> None:
        self._stream = stream
        self._attr_unique_id = f"{entry_id}_instance_live_updates"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, _device_id_instance(entry_id))}
        )

    @override
    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._stream.async_add_listener(self.async_write_ha_state))

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        # Nothing is keyed on entity_id: rename in place (HA 2026.11+), as
        # event.py explains.
        super().async_entity_id_changed(old_entity_id)  # type: ignore[misc, unused-ignore]

    @property
    @override
    def is_on(self) -> bool:
        return self._stream.connected

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"in_use": self._stream.running}


class BaseEnvBinarySensor(
    CoordinatorEntity[DockhandFastCoordinator], BinarySensorEntity
):
    """Base for all environment-level binary sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        base_url: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._env_id = env_id
        self._base_url = base_url

    def _stats(self) -> dict:
        return _coordinator_env(self.coordinator.data, self._env_id).get("stats") or {}

    @property
    @override
    def device_info(self) -> DeviceInfo:
        stats = self._stats()
        env_name = stats.get("name", f"Environment {self._env_id}")
        return _env_device(
            self._entry_id, self._env_id, env_name, self._base_url, stats
        )


class DockhandEnvOnlineSensor(BaseEnvBinarySensor):
    """Environment connectivity — also carries a few identifying
    attributes (name, Docker connection host/port, user-assigned labels)
    for dashboard cards that want them without cross-referencing the
    device registry."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "online"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        slow_coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, base_url)
        self._slow_coordinator = slow_coordinator
        self._attr_unique_id = f"{entry_id}_{env_id}_online"

    @property
    @override
    def is_on(self) -> bool:
        return bool(self._stats().get("online", False))

    def _env_meta(self) -> dict:
        slow_data = self._slow_coordinator.data or {}
        env = _coordinator_env(slow_data, self._env_id)
        return env.get("env_meta") or {}

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        meta = self._env_meta()
        labels = self._stats().get("labels")
        return {
            "connection_host": meta.get("connectionHost"),
            "connection_port": meta.get("connectionPort"),
            "labels": labels if isinstance(labels, list) else [],
        }


class DockhandEnvScannerEnabledSensor(BaseEnvBinarySensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "vulnerability_scanning"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, base_url)
        self._attr_unique_id = f"{entry_id}_{env_id}_scanner_enabled"

    @property
    @override
    def is_on(self) -> bool | None:
        v = self._stats().get("scannerEnabled")
        return bool(v) if v is not None else None


class DockhandStackUpdatesAvailableBinarySensor(
    CoordinatorEntity[DockhandFastCoordinator], BinarySensorEntity
):
    """Whether any container in this stack has a pending image update.

    Sourced from /api/stacks' updatesAvailable/updateCount fields — added
    in Dockhand 1.0.37, computed server-side from the same pending-update
    data our own Tier 1 update entities already use, just pre-aggregated
    per stack so we don't have to cross-reference containers ourselves
    for the count itself. Dockhand's own stack object doesn't expose
    *which* containers specifically (see pending_container_names below),
    only the count and the boolean.

    Feature-detected rather than version-gated: created only when
    "updatesAvailable" is actually present as a key in the stack's data
    (checked with "in", since False is a real, meaningful value distinct
    from "field doesn't exist on this Dockhand version") — works
    correctly against older Dockhand installs without needing to know
    or compare any specific version number, and adapts automatically if
    Dockhand changes this again later.

    Deliberately no device_class. BinarySensorDeviceClass.PROBLEM makes a
    routine available update look like something is wrong.
    BinarySensorDeviceClass.UPDATE is the semantically obvious one, but
    HA's developer docs discourage it in favor of an update entity. A
    stack-level update entity would be a materially bigger entity (one that
    installs, not a read-only summary), so this stays a plain binary sensor
    that renders as generic On/Off.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "stack_updates_available"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._stack_name = stack.get("name", "")
        self._attr_unique_id = (
            f"{entry_id}_{env_id}_stack_{self._stack_name}_updates_available"
        )

    def _stack(self) -> dict | None:
        return _find_stack(self.coordinator.data, self._env_id, self._stack_name)

    @property
    @override
    def is_on(self) -> bool | None:
        s = self._stack()
        if s is None or "updatesAvailable" not in s:
            return None
        return bool(s["updatesAvailable"])

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        s = self._stack()
        if s is None or "updateCount" not in s:
            return None
        env = _coordinator_env(self.coordinator.data, self._env_id)
        # Dockhand's stack object gives us the container ID list and the
        # aggregate update count, but not which of those containers
        # specifically have a pending update — cross-referenced here
        # against the environment's own pending_update_container_ids
        # (the same set DockhandEnvBulkUpdateButton uses), then resolved
        # to names against the environment's full container list, same
        # pattern as DockhandStackStatusSensor's container_names.
        pending_ids = env.get("pending_update_container_ids") or set()
        stack_container_ids = s.get("containers") or []
        env_containers = env.get("containers") or []
        id_to_name = {c.get("id"): c.get("name") for c in env_containers if c.get("id")}
        pending_container_names = sorted(
            (
                id_to_name.get(cid, cid)
                for cid in stack_container_ids
                if cid in pending_ids
            ),
            key=str.lower,
        )
        return {"pending_container_names": pending_container_names}

    @property
    @override
    def device_info(self) -> DeviceInfo:
        s = self._stack()
        return _stack_device(
            getattr(self, "hass", None),
            self._entry_id,
            self._stack_name,
            self._env_id,
            self._env_name,
            self._base_url,
            source_type=(s or {}).get("sourceType"),
        )


class DockhandGitStackSyncErrorBinarySensor(
    CoordinatorEntity[DockhandSlowCoordinator], BinarySensorEntity
):
    """On when a git stack's last sync/deploy attempt failed.

    Lives on the same device as the regular Stack — see
    sensor.BaseSlowGitStackSensor for why there's no separate device type.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "git_stack_sync_error"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        git_stack: dict,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._stack_name = git_stack.get("stackName", "")
        self._attr_unique_id = (
            f"{entry_id}_{env_id}_stack_{self._stack_name}_git_sync_error"
        )

    def _git_stack(self) -> dict[str, Any] | None:
        return _find_git_stack(self.coordinator.data, self._env_id, self._stack_name)

    @property
    @override
    def is_on(self) -> bool | None:
        gs = self._git_stack()
        return gs.get("syncStatus") == "error" if gs else None

    @property
    @override
    def extra_state_attributes(self) -> dict:
        gs = self._git_stack()
        return {"sync_error": gs.get("syncError")} if gs else {}

    @property
    @override
    def device_info(self) -> DeviceInfo:
        return _stack_device(
            getattr(self, "hass", None),
            self._entry_id,
            self._stack_name,
            self._env_id,
            self._env_name,
            self._base_url,
            source_type="git",
        )
