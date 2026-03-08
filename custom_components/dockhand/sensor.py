from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from . import DockhandConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_VOLUMES,
)
from .coordinator import DockhandFastCoordinator, DockhandSlowCoordinator
from .helpers import (
    _container_url, _stack_url, _network_url, _volume_url, _image_url,
    _env_url, _schedules_url,
    _env_device,
    _network_group_device, _volume_group_device,
    _container_device, _stack_device,
    _image_group_device, _image_display_name,
    _container_has_healthcheck,
)

_LOGGER = logging.getLogger(__name__)


def _sched_key(sched: dict) -> str:
    return f"{sched['id']}_{sched['type']}"


def _parse_dt(value: str | int | float | None) -> datetime | None:
    """Parse a timestamp value to a timezone-aware datetime.

    Accepts ISO 8601 strings or Unix epoch integers/floats (Dockhand uses
    epoch integers for nextRun on schedule objects).
    """
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            # Use stdlib directly — avoids HA utility dependency for simple epoch conversion
            from datetime import timezone
            return datetime.utcfromtimestamp(float(value)).replace(tzinfo=timezone.utc)
        parsed = dt_util.parse_datetime(str(value))
        if parsed is not None and parsed.tzinfo is None:
            parsed = dt_util.as_utc(parsed)
        return parsed
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #

# Coordinator centralises all updates — no per-entity polling.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: DockhandConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    fast: DockhandFastCoordinator = entry.runtime_data.fast_coordinator
    slow: DockhandSlowCoordinator = entry.runtime_data.slow_coordinator
    base_url: str = entry.data.get(CONF_API_URL, "")

    def _opt(key: str, default: Any) -> Any:
        return entry.options.get(key, entry.data.get(key, default))

    enable_schedules = _opt(CONF_ENABLE_SCHEDULES, False)
    enable_images = _opt(CONF_ENABLE_IMAGES, False)
    enable_networks = _opt(CONF_ENABLE_NETWORKS, False)
    enable_volumes = _opt(CONF_ENABLE_VOLUMES, False)

    # Track unique_ids already registered so the coordinator listener can
    # add entities for containers/stacks/images created after initial setup
    # without duplicating existing ones.
    known_container_ids: set[str] = set()
    known_stack_ids: set[str] = set()
    known_env_ids: set[int] = set()
    known_slow_env_ids: set[int] = set()
    known_image_ids: set[str] = set()
    known_network_ids: set[str] = set()
    known_volume_ids: set[str] = set()
    known_sched_ids: set[str] = set()

    def _build_fast_entities() -> list[SensorEntity]:
        """Return new fast-coordinator entities not yet registered."""
        _ensure_fast_group_devices()
        new: list[SensorEntity] = []

        for env_id, env_data in (fast.data or {}).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")

            # Per-env sensors — created once per environment
            if env_id not in known_env_ids:
                known_env_ids.add(env_id)
                new += [
                    DockhandEnvCpuSensor(fast, env_id, env_name, base_url),
                    DockhandEnvMemPercentSensor(fast, env_id, env_name, base_url),
                    DockhandEnvContainerCountSensor(fast, env_id, env_name, base_url),
                    DockhandEnvStacksSensor(fast, env_id, env_name, base_url),
                    DockhandEnvImagesSensor(fast, env_id, env_name, base_url),
                    DockhandEnvVolumesSensor(fast, env_id, env_name, base_url),
                    DockhandEnvNetworksSensor(fast, env_id, env_name, base_url),
                    DockhandEnvContainersDiskSensor(fast, env_id, env_name, base_url),
                    DockhandEnvBuildCacheSensor(fast, env_id, env_name, base_url),
                    DockhandEnvActivityEventsSensor(fast, env_id, env_name, base_url),
                ]

            # Per-container sensors
            for container in env_data.get("containers") or []:
                cid = container["id"]
                if cid not in known_container_ids:
                    known_container_ids.add(cid)
                    new += [
                        DockhandContainerStateSensor(fast, env_id, env_name, base_url, container),
                        DockhandContainerImageSensor(fast, env_id, env_name, base_url, container),
                    ]
                    if _container_has_healthcheck(container):
                        new.append(
                            DockhandContainerHealthSensor(fast, env_id, env_name, base_url, container)
                        )

            # Per-stack sensors
            for stack in env_data.get("stacks") or []:
                sid = f"{env_id}_{stack['name']}"
                if sid not in known_stack_ids:
                    known_stack_ids.add(sid)
                    new += [
                        DockhandStackStatusSensor(fast, env_id, env_name, base_url, stack),
                        DockhandStackContainerCountSensor(fast, env_id, env_name, base_url, stack),
                    ]

        return new

    def _ensure_fast_group_devices() -> None:
        """Ensure env hub, group, and individual stack devices exist for each live env.

        Called on every fast coordinator update so that these devices are created
        the moment an environment or its containers/stacks first appear — including
        on a brand-new Docker host that was empty at integration setup time.
        async_get_or_create is idempotent: calling it when the device already
        exists is a no-op.

        Individual stack devices are registered here (not just the Stacks group)
        because compose-managed container entities reference them as via_device.
        HA logs a warning if via_device points to a non-existent device, so we
        must ensure every stack device is registered before any container entity
        that uses it as a parent is added.
        """
        registry = dr.async_get(hass)

        for env_id, env_data in (fast.data or {}).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")

            # Environment hub — always ensure it exists
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"env_{env_id}")},
                name=env_name,
                manufacturer="Dockhand",
                model="Environment",
                configuration_url=_env_url(base_url),
                entry_type=DeviceEntryType.SERVICE,
            )

            # Containers group — only when freestanding (non-Compose) containers exist
            freestanding = [
                c for c in (env_data.get("containers") or [])
                if not (c.get("labels") or {}).get("com.docker.compose.project")
            ]
            if freestanding:
                registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, f"env_{env_id}_Containers")},
                    name=f"{env_name} – Containers",
                    manufacturer="Dockhand",
                    model="Environment",
                    configuration_url=_container_url(base_url),
                    via_device=(DOMAIN, f"env_{env_id}"),
                    entry_type=DeviceEntryType.SERVICE,
                )

            # Stacks group and individual stack devices — must be registered before
            # any compose-managed container entity (which uses the stack device as
            # via_device) is passed to async_add_entities.
            stacks = env_data.get("stacks") or []
            if stacks:
                registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, f"env_{env_id}_Stacks")},
                    name=f"{env_name} – Stacks",
                    manufacturer="Dockhand",
                    model="Environment",
                    configuration_url=_stack_url(base_url),
                    via_device=(DOMAIN, f"env_{env_id}"),
                    entry_type=DeviceEntryType.SERVICE,
                )
                for stack in stacks:
                    stack_name = stack.get("name", "")
                    if stack_name:
                        registry.async_get_or_create(
                            config_entry_id=entry.entry_id,
                            identifiers={(DOMAIN, f"stack_{env_id}_{stack_name}")},
                            name=f"{env_name} – {stack_name}",
                            manufacturer="Dockhand",
                            model="Stack",
                            configuration_url=_stack_url(base_url),
                            via_device=(DOMAIN, f"env_{env_id}_Stacks"),
                            entry_type=DeviceEntryType.SERVICE,
                        )

    def _ensure_slow_group_devices() -> None:
        """Ensure Networks/Images/Volumes group devices exist for each env that has them.

        Called on every slow coordinator update so that group devices are created
        the first time resources appear (e.g. first volume added after setup) and
        remain correct as the inventory changes. async_get_or_create is idempotent.
        """
        registry = dr.async_get(hass)
        slow_envs = (slow.data or {}).get("environments", {})
        fast_data = fast.data or {}

        for env_id, env_data in slow_envs.items():
            # Prefer the name from fast stats (more reliable); fall back to slow env obj
            fast_stats = fast_data.get(env_id, {}).get("stats") or {}
            slow_env_obj = (env_data.get("env") or {})
            env_name = fast_stats.get("name") or slow_env_obj.get("name", f"Environment {env_id}")

            if enable_networks and env_data.get("networks"):
                registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, f"env_{env_id}_Networks")},
                    name=f"{env_name} – Networks",
                    manufacturer="Dockhand",
                    model="Environment",
                    configuration_url=_network_url(base_url),
                    via_device=(DOMAIN, f"env_{env_id}"),
                    entry_type=DeviceEntryType.SERVICE,
                )
            if enable_images and env_data.get("images"):
                registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, f"env_{env_id}_Images")},
                    name=f"{env_name} – Images",
                    manufacturer="Dockhand",
                    model="Environment",
                    configuration_url=_image_url(base_url),
                    via_device=(DOMAIN, f"env_{env_id}"),
                    entry_type=DeviceEntryType.SERVICE,
                )
            if enable_volumes and env_data.get("volumes"):
                registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, f"env_{env_id}_Volumes")},
                    name=f"{env_name} – Volumes",
                    manufacturer="Dockhand",
                    model="Environment",
                    configuration_url=_volume_url(base_url),
                    via_device=(DOMAIN, f"env_{env_id}"),
                    entry_type=DeviceEntryType.SERVICE,
                )

    def _build_slow_entities() -> list[SensorEntity]:
        """Return new slow-coordinator entities not yet registered."""
        _ensure_slow_group_devices()
        new: list[SensorEntity] = []
        slow_envs = (slow.data or {}).get("environments", {})

        for env_id, env_data in slow_envs.items():
            env_name = (env_data.get("env") or {}).get("name", f"Environment {env_id}")

            if env_id not in known_slow_env_ids:
                known_slow_env_ids.add(env_id)
                new.append(DockhandEnvHawserVersionSensor(slow, env_id, env_name, base_url))

            if enable_images:
                for image in env_data.get("images") or []:
                    raw_id = image.get("id") or ""
                    iid = f"{env_id}_{raw_id.split(':')[-1]}"
                    if iid not in known_image_ids:
                        known_image_ids.add(iid)
                        new.append(DockhandImageSensor(slow, env_id, env_name, base_url, image))

            if enable_networks:
                for network in env_data.get("networks") or []:
                    nid = network.get("id", "")
                    if nid not in known_network_ids:
                        known_network_ids.add(nid)
                        new.append(DockhandNetworkSensor(slow, env_id, env_name, base_url, network))

            if enable_volumes:
                for volume in env_data.get("volumes") or []:
                    vid = f"{env_id}_{volume.get('name') or volume.get('Name', '')}"
                    if vid not in known_volume_ids:
                        known_volume_ids.add(vid)
                        new.append(DockhandVolumeSensor(slow, env_id, env_name, base_url, volume))

        if enable_schedules:
            for sched in (slow.data or {}).get("schedules") or []:
                skid = _sched_key(sched)
                if skid not in known_sched_ids:
                    known_sched_ids.add(skid)
                    new += [
                        DockhandScheduleNextRunSensor(slow, sched, base_url),
                        DockhandScheduleLastStatusSensor(slow, sched, base_url),
                    ]

        return new

    # Initial registration
    async_add_entities(_build_fast_entities())
    async_add_entities(_build_slow_entities())

    # Dynamic registration: add entities for new objects discovered after setup
    entry.async_on_unload(
        fast.async_add_listener(
            lambda: async_add_entities(_build_fast_entities())
        )
    )
    entry.async_on_unload(
        slow.async_add_listener(
            lambda: async_add_entities(_build_slow_entities())
        )
    )


# --------------------------------------------------------------------------- #
# Fast coordinator — environment sensors
# --------------------------------------------------------------------------- #

class BaseFastEnvSensor(CoordinatorEntity[DockhandFastCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator)
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url

    def _stats(self) -> dict:
        return (self.coordinator.data or {}).get(self._env_id, {}).get("stats") or {}

    @property
    def device_info(self) -> DeviceInfo:
        return _env_device(self._env_id, self._env_name, self._base_url, self._stats())


class BaseFastContainerSensor(CoordinatorEntity[DockhandFastCoordinator], SensorEntity):
    """Base for per-container fast-coordinator sensors."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str, container: dict) -> None:
        super().__init__(coordinator)
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._container_id = container.get("id", "")
        self._container_name = container.get("name", "")

    def _container(self) -> dict | None:
        for c in (self.coordinator.data or {}).get(self._env_id, {}).get("containers") or []:
            if c.get("id") == self._container_id:
                return c
        return None

    @property
    def device_info(self) -> DeviceInfo:
        c = self._container()
        stack_name = (c.get("labels") or {}).get("com.docker.compose.project") if c else None
        return _container_device(self._container_id, self._container_name,
                                  self._env_id, self._env_name, self._base_url, stack_name)


class BaseFastStackSensor(CoordinatorEntity[DockhandFastCoordinator], SensorEntity):
    """Base for per-stack fast-coordinator sensors."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str, stack: dict) -> None:
        super().__init__(coordinator)
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._stack_name = stack.get("name", "")

    def _stack(self) -> dict | None:
        for s in (self.coordinator.data or {}).get(self._env_id, {}).get("stacks") or []:
            if s.get("name") == self._stack_name:
                return s
        return None

    @property
    def device_info(self) -> DeviceInfo:
        return _stack_device(self._stack_name, self._env_id, self._env_name, self._base_url)


class DockhandEnvCpuSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "CPU usage"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_cpu"

    @property
    def native_value(self) -> float | None:
        cpu = self._stats().get("metrics", {}).get("cpuPercent")
        return round(cpu * 100, 2) if cpu is not None else None


class DockhandEnvMemPercentSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Memory usage"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_mem_percent"

    @property
    def native_value(self) -> float | None:
        mem = self._stats().get("metrics", {}).get("memoryPercent")
        return round(mem, 2) if mem is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        m = self._stats().get("metrics") or {}
        used, total = m.get("memoryUsed"), m.get("memoryTotal")
        return {
            "memory_used_bytes": used,
            "memory_total_bytes": total,
        }


class DockhandEnvContainerCountSensor(BaseFastEnvSensor):
    """Containers sensor — state is total count, all sub-states as attributes.

    unique_id kept as containers_running for backwards compatibility with
    any existing automations referencing the old entity.
    """
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Containers"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_containers_running"

    @property
    def native_value(self) -> int | None:
        return self._stats().get("containers", {}).get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._stats().get("containers") or {}
        return {
            "running": c.get("running"),
            "stopped": c.get("stopped"),
            "paused": c.get("paused"),
            "restarting": c.get("restarting"),
            "unhealthy": c.get("unhealthy"),
            "pending_updates": c.get("pendingUpdates"),
        }


class DockhandEnvStacksSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Stacks"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_stacks_total"

    @property
    def native_value(self) -> int | None:
        return self._stats().get("stacks", {}).get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._stats().get("stacks") or {}
        return {
            "running": s.get("running"),
            "partial": s.get("partial"),
            "stopped": s.get("stopped"),
        }


class DockhandEnvImagesSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Image count"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_images_total"

    @property
    def native_value(self) -> int | None:
        return self._stats().get("images", {}).get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        size = self._stats().get("images", {}).get("totalSize")
        return {
            "total_size_bytes": size,
        }


class DockhandEnvVolumesSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Volume count"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_volumes_total"

    @property
    def native_value(self) -> int | None:
        return self._stats().get("volumes", {}).get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        size = self._stats().get("volumes", {}).get("totalSize")
        return {
            "total_size_bytes": size,
        }


class DockhandEnvNetworksSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Network count"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_networks_total"

    @property
    def native_value(self) -> int | None:
        return self._stats().get("networks", {}).get("total")


class DockhandEnvContainersDiskSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "MiB"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Containers disk usage"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_containers_size"

    @property
    def native_value(self) -> float | None:
        v = self._stats().get("containersSize")
        return round(v / 1_048_576, 3) if isinstance(v, int) else None


class DockhandEnvBuildCacheSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "MiB"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Build cache size"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_build_cache_size"

    @property
    def native_value(self) -> float | None:
        v = self._stats().get("buildCacheSize")
        return round(v / 1_048_576, 3) if isinstance(v, int) else None


class DockhandEnvActivityEventsSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_name = "Activity events"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_events_total"

    @property
    def native_value(self) -> int | None:
        return self._stats().get("events", {}).get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        e = self._stats().get("events") or {}
        return {"today": e.get("today")}


# --------------------------------------------------------------------------- #
# Fast coordinator — container sensors
# model = "Container" mirrors Portainer naming convention
# --------------------------------------------------------------------------- #

class DockhandContainerStateSensor(BaseFastContainerSensor):
    """Container state sensor — aligned with Portainer's sensor.container_state."""
    _attr_name = "State"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str, container: dict) -> None:
        super().__init__(coordinator, env_id, env_name, base_url, container)
        self._attr_unique_id = f"dockhand_container_{self._container_id}_state"

    @property
    def native_value(self) -> str | None:
        c = self._container()
        return c.get("state") if c else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._container()
        if not c:
            return {}
        return {
            "status": c.get("status"),
            "image": c.get("image"),
            "restart_count": c.get("restartCount"),
            "networks": {n: i.get("ipAddress") for n, i in (c.get("networks") or {}).items()},
        }


class DockhandContainerHealthSensor(BaseFastContainerSensor):
    """Container health sensor — mirrors Portainer's health check attribute."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_name = "Health"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str, container: dict) -> None:
        super().__init__(coordinator, env_id, env_name, base_url, container)
        self._attr_unique_id = f"dockhand_container_{self._container_id}_health"

    @property
    def native_value(self) -> str | None:
        c = self._container()
        return c.get("health") if c else None


class DockhandContainerImageSensor(BaseFastContainerSensor):
    """Image tag sensor for a container — mirrors Portainer's image attribute sensor."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_name = "Image"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str, container: dict) -> None:
        super().__init__(coordinator, env_id, env_name, base_url, container)
        self._attr_unique_id = f"dockhand_container_{self._container_id}_image"

    @property
    def native_value(self) -> str | None:
        c = self._container()
        return c.get("image") if c else None


# --------------------------------------------------------------------------- #
# Fast coordinator — stack sensors
# model = "Stack" — distinguishes from containers in device list
# --------------------------------------------------------------------------- #

class DockhandStackStatusSensor(BaseFastStackSensor):
    _attr_name = "Status"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str, stack: dict) -> None:
        super().__init__(coordinator, env_id, env_name, base_url, stack)
        self._attr_unique_id = f"dockhand_stack_{env_id}_{self._stack_name}_status"

    @property
    def native_value(self) -> str | None:
        s = self._stack()
        return s.get("status") if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._stack()
        return {"container_count": len(s.get("containers") or [])} if s else {}


class DockhandStackContainerCountSensor(BaseFastStackSensor):
    """Count of containers belonging to this stack."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Containers"

    def __init__(self, coordinator: DockhandFastCoordinator, env_id: int,
                 env_name: str, base_url: str, stack: dict) -> None:
        super().__init__(coordinator, env_id, env_name, base_url, stack)
        self._attr_unique_id = f"dockhand_stack_{env_id}_{self._stack_name}_container_count"

    @property
    def native_value(self) -> int | None:
        s = self._stack()
        return len(s.get("containers") or []) if s else None


# --------------------------------------------------------------------------- #
# Slow coordinator — optional sensors
# --------------------------------------------------------------------------- #

class BaseSlowEnvSensor(CoordinatorEntity[DockhandSlowCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DockhandSlowCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator)
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url

    def _env_data(self) -> dict:
        return (self.coordinator.data or {}).get("environments", {}).get(self._env_id) or {}

    @property
    def device_info(self) -> DeviceInfo:
        return _env_device(self._env_id, self._env_name, self._base_url)


# --------------------------------------------------------------------------- #
# Slow coordinator — environment config sensors (from /api/environments)
# --------------------------------------------------------------------------- #

class BaseSlowEnvConfigSensor(BaseSlowEnvSensor):
    """Env sensors sourced from /api/environments via the slow coordinator."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _env_obj(self) -> dict:
        return self._env_data().get("env") or {}


class DockhandEnvHawserVersionSensor(BaseSlowEnvConfigSensor):
    """Hawser agent version string — None until the agent first checks in."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_name = "Hawser agent version"

    def __init__(self, coordinator: DockhandSlowCoordinator, env_id: int,
                 env_name: str, base_url: str) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._attr_unique_id = f"dockhand_env_{env_id}_hawser_version"

    @property
    def native_value(self) -> str | None:
        return self._env_obj().get("hawserVersion")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        e = self._env_obj()
        return {
            "agent_name": e.get("hawserAgentName"),
            "agent_id": e.get("hawserAgentId"),
            "last_seen": e.get("hawserLastSeen"),
        }


class DockhandImageSensor(BaseSlowEnvSensor):
    """Entity for a single Docker image, living under the Images group device.

    One entity per image — no individual image devices. The entity name is the
    repository portion of the primary tag (e.g. "cloudflare/cloudflared") and
    the state is the tag portion (e.g. "latest", "2.1.0"). For untagged images
    the name is the short hash ID and the state is None. All image metadata
    (size, digests, OCI labels, created, containers_using) is surfaced as
    extra_state_attributes.

    API shape (confirmed from /api/images): camelCase fields, created is a
    Unix timestamp integer, containers is always an int (0 = unused).
    """
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = False  # standalone name — not prefixed by Images group device

    def __init__(self, coordinator: DockhandSlowCoordinator, env_id: int,
                 env_name: str, base_url: str, image: dict) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        raw_id = image.get("id") or ""
        # Strip "sha256:" prefix — store just the 64-char hex for lookups
        self._image_id = raw_id.split(":")[-1] if ":" in raw_id else raw_id
        # Name = repository portion only (e.g. "cloudflare/cloudflared")
        # Fall back to short hash for untagged/intermediate images
        primary_tag = _image_display_name(image)  # e.g. "cloudflare/cloudflared:latest"
        if ":" in primary_tag:
            self._image_repo = primary_tag.rsplit(":", 1)[0]
        else:
            self._image_repo = primary_tag  # already a short hash (no colon)
        self._attr_unique_id = f"dockhand_image_{env_id}_{self._image_id}"
        self._attr_name = self._image_repo

    def _image(self) -> dict | None:
        for img in self._env_data().get("images") or []:
            raw_id = img.get("id") or ""
            short_id = raw_id.split(":")[-1] if ":" in raw_id else raw_id
            if short_id == self._image_id:
                return img
        return None

    @property
    def native_value(self) -> str | None:
        """The tag portion of the primary tag, e.g. 'latest' or '2.1.0'."""
        img = self._image()
        if img is None:
            return None
        tags = [t for t in (img.get("repoTags") or []) if t and t != "<none>:<none>"]
        if not tags:
            return None  # untagged image — no meaningful tag value
        primary = tags[0]
        return primary.rsplit(":", 1)[1] if ":" in primary else primary

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        img = self._image()
        if not img:
            return {}

        # All tags — filter Docker placeholder for untagged layers
        tags = [t for t in (img.get("repoTags") or []) if t and t != "<none>:<none>"]

        # Digests — keep full digest string (algo:hex), trim nothing
        digests = img.get("repoDigests") or []

        size = img.get("size")
        containers_using = img.get("containers")

        # OCI standard labels contain useful metadata worth surfacing
        labels = img.get("labels") or {}
        oci_version = labels.get("org.opencontainers.image.version")
        oci_vendor = labels.get("org.opencontainers.image.vendor")
        oci_title = labels.get("org.opencontainers.image.title")
        oci_source = labels.get("org.opencontainers.image.source")

        # created is a Unix timestamp integer — convert to ISO 8601 UTC string
        created_ts = img.get("created")
        created_iso: str | None = None
        if isinstance(created_ts, int):
            try:
                created_iso = dt_util.utc_from_timestamp(created_ts).isoformat()
            except Exception:
                pass

        attrs: dict[str, Any] = {
            "tags": tags,
            "digests": digests,
            "size_bytes": size,
            "created": created_iso,
            "containers_using": containers_using,
        }
        # Only include OCI labels that are actually present
        if oci_version:
            attrs["version"] = oci_version
        if oci_vendor:
            attrs["vendor"] = oci_vendor
        if oci_title:
            attrs["title"] = oci_title
        if oci_source:
            attrs["source"] = oci_source
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        """All image entities live under the per-env Images group device."""
        return _image_group_device(self._env_id, self._env_name, self._base_url)


class DockhandNetworkSensor(BaseSlowEnvSensor):
    """Entity for a Docker network, living under the Networks group device.

    One entity per network — no individual network sub-devices. The entity name
    is the network name and the state is the count of connected containers.
    All network metadata (driver, scope, subnet, connected containers) is
    surfaced as extra_state_attributes.
    """
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "containers"
    _attr_has_entity_name = False  # standalone name — not prefixed by Networks group device

    def __init__(self, coordinator: DockhandSlowCoordinator, env_id: int,
                 env_name: str, base_url: str, network: dict) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._network_id = network.get("id", "")
        self._network_name = network.get("name", "")
        self._attr_unique_id = f"dockhand_network_{env_id}_{self._network_id}"
        self._attr_name = self._network_name

    def _network(self) -> dict | None:
        for n in self._env_data().get("networks") or []:
            if n.get("id") == self._network_id:
                return n
        return None

    @property
    def native_value(self) -> int | None:
        n = self._network()
        return len(n.get("containers") or {}) if n else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        n = self._network()
        if not n:
            return {}
        ipam = (n.get("ipam") or {}).get("config") or []
        connected = {
            i.get("name"): i.get("ipv4Address")
            for i in (n.get("containers") or {}).values() if i.get("name")
        }
        return {
            "driver": n.get("driver"),
            "scope": n.get("scope"),
            "internal": n.get("internal"),
            "subnet": ipam[0].get("subnet") if ipam else None,
            "connected_containers": connected,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """All network entities live under the per-env Networks group device."""
        return _network_group_device(self._env_id, self._env_name, self._base_url)


class DockhandVolumeSensor(BaseSlowEnvSensor):
    """Entity for a Docker volume, living under the Volumes group device.

    One entity per volume — no individual volume sub-devices. The state is the
    container count (most actionable: 0 = unused/dangling candidate for pruning).
    All volume metadata (in_use bool, driver, scope, mountpoint, labels, created,
    container list) is surfaced as extra_state_attributes.
    """
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "containers"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:database"
    _attr_has_entity_name = False  # standalone name — not prefixed by Volumes group device

    def __init__(self, coordinator: DockhandSlowCoordinator, env_id: int,
                 env_name: str, base_url: str, volume: dict) -> None:
        super().__init__(coordinator, env_id, env_name, base_url)
        self._volume_name: str = volume.get("name") or volume.get("Name") or "unknown"
        self._attr_unique_id = f"dockhand_volume_{env_id}_{self._volume_name}"
        self._attr_name = self._volume_name

    def _volume(self) -> dict | None:
        for v in self._env_data().get("volumes") or []:
            if (v.get("name") or v.get("Name")) == self._volume_name:
                return v
        return None

    @property
    def native_value(self) -> int | None:
        """Container count — 0 means unused/dangling, a pruning candidate."""
        v = self._volume()
        if not v:
            return None
        used_by = v.get("usedBy") or v.get("UsedBy") or []
        return len(used_by)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v = self._volume()
        if not v:
            return {}
        used_by = v.get("usedBy") or v.get("UsedBy") or []
        # created timestamp — parse to ISO string if present
        created_iso: str | None = None
        raw_created = v.get("created") or v.get("Created")
        if raw_created:
            try:
                parsed = dt_util.parse_datetime(str(raw_created))
                created_iso = parsed.isoformat() if parsed else str(raw_created)
            except Exception:
                created_iso = str(raw_created)
        return {
            "in_use": len(used_by) > 0,
            "containers": used_by,
            "driver": v.get("driver") or v.get("Driver"),
            "scope": v.get("scope") or v.get("Scope"),
            "mountpoint": v.get("mountpoint") or v.get("Mountpoint"),
            "labels": v.get("labels") or v.get("Labels") or {},
            "created": created_iso,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """All volume entities live under the per-env Volumes group device."""
        return _volume_group_device(self._env_id, self._env_name, self._base_url)


# --------------------------------------------------------------------------- #
# Slow coordinator — schedule sensors
# --------------------------------------------------------------------------- #

class _BaseScheduleSensor(CoordinatorEntity[DockhandSlowCoordinator], SensorEntity):
    """Common base for per-schedule sensors."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: DockhandSlowCoordinator,
                 sched: dict, base_url: str) -> None:
        super().__init__(coordinator)
        self._sched_id = sched["id"]
        self._sched_type = sched["type"]
        self._sched_name = sched["name"]
        self._base_url = base_url

    def _find(self) -> dict | None:
        for s in (self.coordinator.data or {}).get("schedules") or []:
            if s["id"] == self._sched_id and s["type"] == self._sched_type:
                return s
        return None

    @property
    def device_info(self) -> DeviceInfo:
        key = _sched_key({"id": self._sched_id, "type": self._sched_type})
        return DeviceInfo(
            identifiers={(DOMAIN, f"schedule_{key}")},
            name=self._sched_name,
            manufacturer="Dockhand",
            model="Schedule",
            configuration_url=_schedules_url(self._base_url),
            via_device=(DOMAIN, "schedules_hub"),
            entry_type=DeviceEntryType.SERVICE,
        )


class DockhandScheduleNextRunSensor(_BaseScheduleSensor):
    """Next scheduled run — TIMESTAMP sensor for time-based automations.

    Keeping this as a first-class entity (not an attribute) lets users write
    clean ``trigger: state`` automations against the timestamp directly.
    """
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Next run"

    def __init__(self, coordinator: DockhandSlowCoordinator,
                 sched: dict, base_url: str) -> None:
        super().__init__(coordinator, sched, base_url)
        self._attr_unique_id = f"dockhand_sched_{_sched_key(sched)}_next_run"

    @property
    def native_value(self) -> datetime | None:
        s = self._find()
        return _parse_dt(s.get("nextRun")) if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._find()
        if not s:
            return {}
        return {
            "cron_expression": s.get("cronExpression"),
            "enabled": s.get("enabled"),
            "environment": s.get("environmentName"),
            "schedule_type": s.get("type"),
        }


class DockhandScheduleLastStatusSensor(_BaseScheduleSensor):
    """Last execution status — string sensor for failure-alert automations.

    A dedicated string sensor (rather than an attribute on Next run) lets users
    write idiomatic HA automations like:
        trigger:
          - platform: state
            entity_id: sensor.auto_update_last_status
            to: "failed"
    Template triggers on attributes are fragile and hard to read.
    """
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Last status"

    def __init__(self, coordinator: DockhandSlowCoordinator,
                 sched: dict, base_url: str) -> None:
        super().__init__(coordinator, sched, base_url)
        self._attr_unique_id = f"dockhand_sched_{_sched_key(sched)}_last_status"

    @property
    def native_value(self) -> str | None:
        s = self._find()
        if s:
            last = s.get("lastExecution")
            return last.get("status") if last else None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._find()
        if not s:
            return {}
        last = s.get("lastExecution")
        if not last:
            return {}
        attrs: dict[str, Any] = {
            "triggered_by": last.get("triggeredBy"),
            "triggered_at": last.get("triggeredAt"),
            "duration_ms": last.get("duration"),
            "error_message": last.get("errorMessage"),
        }
        details = last.get("details") or {}
        if "updatesFound" in details:
            attrs["updates_found"] = details["updatesFound"]
        return attrs
