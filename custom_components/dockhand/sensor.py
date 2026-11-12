from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, override

import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry, tags
from .const import (
    CONF_API_URL,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_RESOURCE_STATS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_VOLUMES,
    DEFAULT_ENABLE_RESOURCE_STATS,
)
from .coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
    DockhandUpdateCoordinator,
)
from .entity import (
    DockhandContainerEntity,
    DockhandScheduleEntity,
    DockhandStackEntity,
)
from .entity_defaults import enabling_chosen
from .helpers import (
    _actionable_pending_update_container_ids,
    _all_envs,
    _container_has_healthcheck,
    _container_has_held_update_only,
    _container_has_pending_update,
    _container_has_pinned_digest_only,
    _container_has_version_suggestion_only,
    _coordinator_env,
    _ensure_env_devices,
    _ensure_hub_devices,
    _env_device,
    _find_git_stack,
    _image_display_name,
    _image_group_device,
    _network_group_device,
    _stack_device,
    _stack_has_system_container,
    _volume_group_device,
    already_registered,
)


def _parse_dt(value: str | int | float | None) -> datetime | None:
    """Parse a timestamp value to a timezone-aware datetime.

    Accepts ISO 8601 strings or Unix epoch integers/floats (Dockhand uses
    epoch integers for nextRun on schedule objects).
    """
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return dt_util.utc_from_timestamp(float(value))
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
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities = enabling_chosen(
        entry.entry_id, entry.options, async_add_entities
    )
    fast: DockhandFastCoordinator = entry.runtime_data.fast_coordinator
    slow: DockhandSlowCoordinator = entry.runtime_data.slow_coordinator
    update_coordinator: DockhandUpdateCoordinator | None = (
        entry.runtime_data.update_coordinator
    )
    base_url: str = entry.data.get(CONF_API_URL, "")

    def _opt(key: str, default: Any) -> Any:
        return entry.options.get(key, default)

    enable_schedules = _opt(CONF_ENABLE_SCHEDULES, False)
    enable_images = _opt(CONF_ENABLE_IMAGES, False)
    enable_networks = _opt(CONF_ENABLE_NETWORKS, False)
    enable_volumes = _opt(CONF_ENABLE_VOLUMES, False)
    enable_resource_stats = _opt(
        CONF_ENABLE_RESOURCE_STATS, DEFAULT_ENABLE_RESOURCE_STATS
    )

    known_ids = entry.runtime_data.known_entity_ids

    pending_readd_ids = entry.runtime_data.pending_readd_entity_ids

    def _already_registered(domain: str, unique_id: str | None) -> bool:
        # See helpers.py's already_registered() for the full reasoning —
        # moved there once switch.py/number.py/select.py/button.py/
        # binary_sensor.py needed the exact same check too.
        return already_registered(
            hass, known_ids, domain, unique_id, pending_readd_ids=pending_readd_ids
        )

    def _unregistered(entities: Sequence[SensorEntity]) -> list[SensorEntity]:
        return [e for e in entities if not _already_registered("sensor", e.unique_id)]

    def _build_fast_entities() -> list[SensorEntity]:
        """Return new fast-coordinator entities not yet registered."""
        _ensure_fast_group_devices()
        new: list[SensorEntity] = []

        for env_id, env_data in _all_envs(fast.data).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")

            # Every entity checked on its own, so a sensor added in a later
            # release is created for environments that already have the rest.
            new += _unregistered(
                [
                    DockhandEnvConnectionTypeSensor(
                        fast, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvCpuSensor(
                        fast, slow, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvMemPercentSensor(
                        fast, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvContainerCountSensor(
                        fast, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvStacksSensor(
                        fast, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvImagesSensor(
                        fast, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvVolumesSensor(
                        fast, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvNetworksSensor(
                        fast, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvDiskUsageSensor(
                        fast, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvActivityEventsSensor(
                        fast, slow, entry.entry_id, env_id, env_name, base_url
                    ),
                    *(
                        DockhandEnvValueSensor(
                            fast,
                            update_coordinator,
                            entry.entry_id,
                            env_id,
                            env_name,
                            base_url,
                            description,
                        )
                        for description in ENV_VALUE_SENSORS
                    ),
                ]
            )

            # Per-container sensors
            for container in env_data.get("containers") or []:
                if _container_has_healthcheck(container):
                    health_sensor = DockhandContainerHealthSensor(
                        fast,
                        entry.entry_id,
                        env_id,
                        env_name,
                        base_url,
                        container,
                    )
                    if not _already_registered("sensor", health_sensor.unique_id):
                        new.append(health_sensor)
                state_sensor = DockhandContainerStateSensor(
                    fast, entry.entry_id, env_id, env_name, base_url, container
                )
                if not _already_registered("sensor", state_sensor.unique_id):
                    new.append(state_sensor)

                # Resource stats sensors — only created at all when "Enable
                # container stats" is on, so turning the option off lets the
                # registry cleanup remove them.
                if enable_resource_stats:
                    cpu_sensor = DockhandContainerCpuSensor(
                        fast,
                        entry.entry_id,
                        env_id,
                        env_name,
                        base_url,
                        container,
                        enable_resource_stats,
                    )
                    new += _unregistered(
                        [
                            cpu_sensor,
                            DockhandContainerMemoryUsageSensor(
                                fast,
                                entry.entry_id,
                                env_id,
                                env_name,
                                base_url,
                                container,
                                enable_resource_stats,
                            ),
                            DockhandContainerMemoryCacheSensor(
                                fast,
                                entry.entry_id,
                                env_id,
                                env_name,
                                base_url,
                                container,
                                enable_resource_stats,
                            ),
                            DockhandContainerMemoryPercentSensor(
                                fast,
                                entry.entry_id,
                                env_id,
                                env_name,
                                base_url,
                                container,
                                enable_resource_stats,
                            ),
                            DockhandContainerMemoryLimitSensor(
                                fast,
                                entry.entry_id,
                                env_id,
                                env_name,
                                base_url,
                                container,
                                enable_resource_stats,
                            ),
                            DockhandContainerNetworkRxSensor(
                                fast,
                                entry.entry_id,
                                env_id,
                                env_name,
                                base_url,
                                container,
                                enable_resource_stats,
                            ),
                            DockhandContainerNetworkTxSensor(
                                fast,
                                entry.entry_id,
                                env_id,
                                env_name,
                                base_url,
                                container,
                                enable_resource_stats,
                            ),
                            DockhandContainerBlockReadSensor(
                                fast,
                                entry.entry_id,
                                env_id,
                                env_name,
                                base_url,
                                container,
                                enable_resource_stats,
                            ),
                            DockhandContainerBlockWriteSensor(
                                fast,
                                entry.entry_id,
                                env_id,
                                env_name,
                                base_url,
                                container,
                                enable_resource_stats,
                            ),
                        ]
                    )

            # Per-stack sensors
            for stack in env_data.get("stacks") or []:
                status_sensor = DockhandStackStatusSensor(
                    fast, entry.entry_id, env_id, env_name, base_url, stack
                )
                if not _already_registered("sensor", status_sensor.unique_id):
                    new += [
                        status_sensor,
                        DockhandStackContainerCountSensor(
                            fast, entry.entry_id, env_id, env_name, base_url, stack
                        ),
                    ]
                # Alongside the Updates available binary sensor (Dockhand
                # 1.0.37+).
                if "updatesAvailable" in stack:
                    new += _unregistered(
                        [
                            DockhandStackUpdateCountSensor(
                                fast, entry.entry_id, env_id, env_name, base_url, stack
                            )
                        ]
                    )
                # Same gating as the container stats sensors above, plus
                # Dockhand having the
                # stack stats endpoint at all (stack_stats is None
                # otherwise — see the fast coordinator).
                if enable_resource_stats and env_data.get("stack_stats") is not None:
                    stats_sensors = [
                        DockhandStackStatsSensor(
                            fast,
                            entry.entry_id,
                            env_id,
                            env_name,
                            base_url,
                            stack,
                            description,
                        )
                        for description in STACK_STATS_SENSORS
                    ]
                    new += _unregistered(stats_sensors)

        return new

    def _ensure_fast_group_devices() -> None:
        """Ensure env hub, group, and individual stack devices exist for each live env.

        Called on every fast coordinator update so that devices are created
        the moment an environment or its containers/stacks first appear — including
        on a brand-new Docker host that was empty at integration setup time.
        Delegates to _ensure_env_devices (helpers.py), the single source of truth
        for device names, models, entry_type, and via_device relationships.
        """
        for env_id, env_data in _all_envs(fast.data).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")
            _ensure_env_devices(
                hass,
                entry.entry_id,
                base_url,
                env_id,
                env_name,
                containers=env_data.get("containers") or [],
                stacks=env_data.get("stacks") or [],
            )

    def _ensure_slow_group_devices() -> None:
        """Ensure optional resource group devices exist for each env.

        Called on every slow coordinator update so that group devices are created
        the first time resources appear (e.g. first volume added after setup).
        Delegates to _ensure_env_devices (helpers.py), the single source of truth
        for device names, models, entry_type, and via_device relationships.
        """
        slow_envs = _all_envs(slow.data)
        fast_data = _all_envs(fast.data)
        all_schedules = (slow.data or {}).get("schedules") or []

        for env_id, env_data in slow_envs.items():
            fast_stats = (fast_data.get(env_id) or {}).get("stats") or {}
            env_name = fast_stats.get("name", f"Environment {env_id}")
            env_schedules = [
                s for s in all_schedules if s.get("environmentId") == env_id
            ]
            _ensure_env_devices(
                hass,
                entry.entry_id,
                base_url,
                env_id,
                env_name,
                networks=env_data.get("networks"),
                images=env_data.get("images"),
                volumes=env_data.get("volumes"),
                schedules=env_schedules,
                enable_networks=enable_networks,
                enable_images=enable_images,
                enable_volumes=enable_volumes,
                enable_schedules=enable_schedules,
            )

    def _build_slow_entities() -> list[SensorEntity]:
        """Return new slow-coordinator entities not yet registered."""
        _ensure_slow_group_devices()
        if enable_schedules:
            _ensure_hub_devices(
                hass,
                entry.entry_id,
                base_url,
                (slow.data or {}).get("schedules") or [],
            )
        new: list[SensorEntity] = []
        slow_envs = _all_envs(slow.data)
        fast_data = _all_envs(fast.data)

        for env_id, env_data in slow_envs.items():
            fast_stats = (fast_data.get(env_id) or {}).get("stats") or {}
            env_name = fast_stats.get("name", f"Environment {env_id}")

            hawser_version_sensor = DockhandEnvHawserVersionSensor(
                slow, entry.entry_id, env_id, env_name, base_url
            )
            if not _already_registered("sensor", hawser_version_sensor.unique_id):
                new += [
                    hawser_version_sensor,
                    DockhandEnvPlatformSensor(
                        slow, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvDockerVersionSensor(
                        slow, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvLastBootSensor(
                        slow, entry.entry_id, env_id, env_name, base_url
                    ),
                    DockhandEnvVulnerabilitiesSensor(
                        slow, entry.entry_id, env_id, env_name, base_url
                    ),
                ]
            new += _unregistered(
                [
                    DockhandEnvVulnerabilityCountSensor(
                        slow, entry.entry_id, env_id, env_name, base_url, field
                    )
                    for field in VULNERABILITY_SENSORS
                ]
            )
            if fast_stats.get("connectionType") == "hawser-edge":
                new += _unregistered(
                    [
                        DockhandEnvHawserLastSeenSensor(
                            slow, entry.entry_id, env_id, env_name, base_url
                        )
                    ]
                )

            if enable_images:
                images_list = env_data.get("images") or []
                # A container upgrade momentarily produces two images under
                # the same repo:tag — the freshly-pulled one, and the old
                # one it's replacing, which hasn't been marked untagged in
                # Dockhand's own data yet (that usually resolves by the very
                # next poll). Creating a brand-new entity for either one
                # while both still claim the same tag would collide with
                # whichever entity gets added first, forcing an ugly
                # auto-suffixed "_2" entity_id that doesn't self-heal
                # without a manual "recreate entity ids" action. Detect
                # any tag currently claimed by more than one image and
                # defer creating entities for all of them — normal,
                # unambiguous images are never affected, and a real
                # collision resolves itself within a poll cycle or two
                # once Dockhand's data catches up.
                tag_counts: dict[str, int] = {}
                for image in images_list:
                    tag = _image_display_name(image)
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
                for image in images_list:
                    image_sensor = DockhandImageSensor(
                        slow, entry.entry_id, env_id, env_name, base_url, image
                    )
                    if _already_registered("sensor", image_sensor.unique_id):
                        continue
                    if tag_counts.get(_image_display_name(image), 0) > 1:
                        continue
                    new.append(image_sensor)

            if enable_networks:
                for network in env_data.get("networks") or []:
                    network_sensor = DockhandNetworkSensor(
                        slow,
                        entry.entry_id,
                        env_id,
                        env_name,
                        base_url,
                        network,
                    )
                    if not _already_registered("sensor", network_sensor.unique_id):
                        new.append(network_sensor)

            if enable_volumes:
                for volume in env_data.get("volumes") or []:
                    volume_sensor = DockhandVolumeSensor(
                        slow, entry.entry_id, env_id, env_name, base_url, volume
                    )
                    if not _already_registered("sensor", volume_sensor.unique_id):
                        new.append(volume_sensor)

            for git_stack in env_data.get("git_stacks") or []:
                git_sync_sensor = DockhandGitStackSyncStatusSensor(
                    slow,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                    git_stack,
                )
                if not _already_registered("sensor", git_sync_sensor.unique_id):
                    new += [
                        git_sync_sensor,
                        DockhandGitStackLastSyncSensor(
                            slow,
                            entry.entry_id,
                            env_id,
                            env_name,
                            base_url,
                            git_stack,
                        ),
                    ]

        if enable_schedules:
            for sched in (slow.data or {}).get("schedules") or []:
                next_run_sensor = DockhandScheduleNextRunSensor(
                    slow, entry.entry_id, sched, base_url
                )
                if not _already_registered("sensor", next_run_sensor.unique_id):
                    new += [
                        next_run_sensor,
                        DockhandScheduleLastStatusSensor(
                            slow, entry.entry_id, sched, base_url
                        ),
                    ]

        return new

    # Initial registration
    async_add_entities(_build_fast_entities())
    async_add_entities(_build_slow_entities())

    # Dynamic registration: add entities for new objects discovered after setup
    entry.async_on_unload(
        fast.async_add_listener(lambda: async_add_entities(_build_fast_entities()))
    )
    entry.async_on_unload(
        slow.async_add_listener(lambda: async_add_entities(_build_slow_entities()))
    )


# --------------------------------------------------------------------------- #
# Fast coordinator — environment sensors
# --------------------------------------------------------------------------- #


class BaseFastEnvSensor(CoordinatorEntity[DockhandFastCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url

    def _stats(self) -> dict:
        return _coordinator_env(self.coordinator.data, self._env_id).get("stats") or {}

    @property
    @override
    def device_info(self) -> DeviceInfo:
        return _env_device(
            self._entry_id,
            self._env_id,
            self._env_name,
            self._base_url,
            self._stats(),
        )


class BaseFastContainerSensor(DockhandContainerEntity, SensorEntity):
    """Base for per-container fast-coordinator sensors."""

    def _container_stats(self) -> dict | None:
        """Return the latest stats snapshot for this container, or None.

        Returns None when the container is stopped, exited, or created —
        the stats endpoint omits non-running containers entirely.  Sensor
        native_value should return None in that case so HA marks the entity
        unavailable rather than showing a stale or zero reading.
        """
        return (
            _coordinator_env(self.coordinator.data, self._env_id).get("container_stats")
            or {}
        ).get(self._container_name)


class BaseFastContainerStatsSensor(BaseFastContainerSensor):
    """Base for the container CPU/memory/network/block-I/O sensors
    specifically (not state/health, which have their own valid data even
    for a stopped container) — only created at all when "Enable container
    stats" is on (see sensor.py's entity-creation loop), which also gates
    the underlying stats API call itself. Reports unavailable rather than
    a stale/zero reading whenever this specific container has no stats
    snapshot right now (stopped, or dropped out of the API response for
    any other reason) — distinct from state/health, which stay available
    in exactly that situation.
    """

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, container)
        self._attr_entity_registry_enabled_default = stats_enabled

    @property
    @override
    def available(self) -> bool:
        return super().available and self._container_stats() is not None


def _resolve_container_names(
    container_ids: list[str], env_data: dict[str, Any]
) -> list[str]:
    """Resolve a list of raw container IDs to their current names, against
    an environment's own full container list. Falls back to the ID itself
    if a container isn't found (e.g. removed since the list was last
    refreshed) — better than silently dropping it. Shared by
    DockhandStackStatusSensor and DockhandStackContainerCountSensor,
    which both expose a container_names attribute — Dockhand's own stack
    object only gives raw container IDs (verified against Dockhand's
    source, src/lib/server/stacks.ts), never names.

    Sorted alphabetically (case-insensitive) — Dockhand's own container
    ID order has no particular meaning to a person reading the
    attribute, and an unsorted list is harder to skim at a glance,
    especially for a stack with many containers.
    """
    env_containers = env_data.get("containers") or []
    id_to_name = {c.get("id"): c.get("name") for c in env_containers if c.get("id")}
    names = [id_to_name.get(cid, cid) for cid in container_ids]
    return sorted(names, key=str.lower)


class BaseFastStackSensor(DockhandStackEntity, SensorEntity):
    """Base for per-stack fast-coordinator sensors."""


class DockhandEnvConnectionTypeSensor(BaseFastEnvSensor):
    """How this environment connects to Docker: socket / direct / hawser-standard
    / hawser-edge — the same value already carried on the environment device's
    hw_version, now also exposed as a proper entity so dashboards (and the
    ha-dockhand-cards environment card) can show its own icon via
    ha-state-icon rather than a hardcoded lookup table keyed off the device
    attribute. Enabled by default, same reasoning as `online` — this is
    identifying info about the environment, not a diagnostic extra.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_translation_key = "connection_type"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["socket", "direct", "hawser-standard", "hawser-edge"]

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_connection_type"

    @property
    @override
    def native_value(self) -> str | None:
        v = self._stats().get("connectionType")
        return v if v in self._attr_options else None


class DockhandEnvCpuSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "cpu_usage"
    _unrecorded_attributes = frozenset({"top_containers"})

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        slow_coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._slow_coordinator = slow_coordinator
        self._attr_unique_id = f"{self._entry_id}_{env_id}_cpu"

    @property
    @override
    def native_value(self) -> float | None:
        cpu = (self._stats().get("metrics") or {}).get("cpuPercent")
        return round(cpu, 2) if cpu is not None else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        # cpu_count is host-level data from the slow coordinator (GET
        # /api/host) — consulted directly here rather than as a separate
        # entity, same reasoning as Memory usage's used/total byte
        # attributes: one more data point about the same underlying
        # metric doesn't need its own entity. Unlike memory's attributes
        # (same fast-coordinator source as the state itself), this one
        # is genuinely cross-coordinator — cpus practically never
        # changes, so only updating in step with the slow coordinator's
        # own 600s cadence rather than every fast poll is a non-issue.
        slow_data = self._slow_coordinator.data or {}
        host = _coordinator_env(slow_data, self._env_id).get("host") or {}
        cpus = host.get("cpus")
        attrs: dict[str, Any] = {"cpu_count": cpus} if isinstance(cpus, int) else {}

        # top_containers — ranked from the same container_stats data the
        # per-container sensors use (see BaseFastContainerStatsSensor).
        # Only populated when "Enable container and stack stats" is on, since that
        # option now gates the underlying API call itself, not just
        # whether the per-container entities are created — an empty list
        # here when the option is off is correct, not a bug.
        container_stats = (
            _coordinator_env(self.coordinator.data, self._env_id).get("container_stats")
            or {}
        )
        ranked = sorted(
            (s for s in container_stats.values() if isinstance(s, dict)),
            key=lambda s: s.get("cpuPercent") or 0,
            reverse=True,
        )[:5]
        attrs["top_containers"] = [
            {
                "name": s.get("name"),
                "cpu_percent": s.get("cpuPercent"),
                "memory_percent": s.get("memoryPercent"),
            }
            for s in ranked
        ]
        return attrs


class DockhandEnvMemPercentSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "memory_usage"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_mem_percent"

    @property
    @override
    def native_value(self) -> float | None:
        mem = (self._stats().get("metrics") or {}).get("memoryPercent")
        return round(mem, 2) if mem is not None else None


class DockhandEnvContainerCountSensor(BaseFastEnvSensor):
    """Every container in the environment; each state has its own sensor
    (ENV_VALUE_SENSORS). The unique ID's `containers_running` predates that
    and is kept so existing entities stay."""

    _attr_translation_key = "containers"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_containers_running"

    @property
    @override
    def native_value(self) -> int | None:
        return (self._stats().get("containers") or {}).get("total")


def _pending_update_counts(
    env_data: dict[str, Any], update_env_data: dict[str, Any] | None
) -> dict[str, int]:
    """An environment's containers with an update, by kind. `installable` is
    what the bulk update would touch (the same helper the Update all button
    uses, so system containers are never in it); `system` is system
    containers with one, shown but never bulk-updated; `version_tag`,
    `pinned_digest` and `held` are update entities that are on without an
    install to offer. `total` is every update entity that's on, the number
    the Updates card shows."""
    pending_ids = env_data.get("pending_update_container_ids") or set()
    containers = env_data.get("containers") or []
    details = env_data.get("pending_update_details") or {}
    installable = len(
        _actionable_pending_update_container_ids(
            containers, pending_ids, update_env_data, details
        )
    )

    def _count(check: Callable[..., bool], *args: Any) -> int:
        return sum(1 for c in containers if check(c, *args))

    with_update = _count(_container_has_pending_update, pending_ids, update_env_data)
    version_tag = _count(
        _container_has_version_suggestion_only,
        pending_ids,
        details,
        update_env_data,
    )
    pinned = _count(
        _container_has_pinned_digest_only, pending_ids, details, update_env_data
    )
    held = _count(
        _container_has_held_update_only, pending_ids, details, update_env_data
    )
    return {
        "installable": installable,
        "system": with_update - installable,
        "version_tag": version_tag,
        "pinned_digest": pinned,
        "held": held,
        "total": with_update + version_tag + pinned + held,
    }


@dataclass(frozen=True, kw_only=True)
class DockhandEnvValueDescription(SensorEntityDescription):
    """One number about an environment from the fast poll. `key` ends the
    unique ID; `value_fn` gets the environment's fast data and the
    precise-update data (None while that option is off)."""

    value_fn: Callable[[dict[str, Any], dict[str, Any] | None], Any]


def _stat(group: str, field: str) -> Callable[[dict, dict | None], Any]:
    return lambda env, _: ((env.get("stats") or {}).get(group) or {}).get(field)


def _updates(kind: str) -> Callable[[dict, dict | None], Any]:
    return lambda env, update_env: _pending_update_counts(env, update_env)[kind]


def _size(*path: str) -> Callable[[dict, dict | None], Any]:
    def _value(env: dict, _: dict | None) -> int | None:
        value: Any = env.get("stats") or {}
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        return value if isinstance(value, int) else None

    return _value


def _count_description(
    key: str, translation_key: str, value_fn: Callable, enabled: bool = True
) -> DockhandEnvValueDescription:
    return DockhandEnvValueDescription(
        key=key,
        translation_key=translation_key,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=enabled,
        value_fn=value_fn,
    )


def _bytes_description(
    key: str, translation_key: str, value_fn: Callable, enabled: bool = True
) -> DockhandEnvValueDescription:
    return DockhandEnvValueDescription(
        key=key,
        translation_key=translation_key,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        entity_registry_enabled_default=enabled,
        value_fn=value_fn,
    )


# Unique ID suffixes here must not start with a word the registry cleanup
# dispatches on (container, image, update, stack, …): they rely on the
# environment device's removal, like the other environment sensors.
ENV_VALUE_SENSORS: tuple[DockhandEnvValueDescription, ...] = (
    *(
        _count_description(
            f"{state}_containers", f"containers_{state}", _stat("containers", state)
        )
        for state in ("running", "stopped", "paused", "restarting", "unhealthy")
    ),
    *(
        _count_description(f"{state}_stacks", f"stacks_{state}", _stat("stacks", state))
        for state in ("running", "partial", "stopped")
    ),
    _count_description("pending_updates", "pending_updates", _updates("total")),
    _count_description(
        "installable_updates", "installable_updates", _updates("installable")
    ),
    _count_description("system_updates", "system_updates", _updates("system")),
    _count_description(
        "version_tag_updates", "version_tag_updates", _updates("version_tag")
    ),
    _count_description(
        "pinned_digest_updates",
        "pinned_digest_updates",
        _updates("pinned_digest"),
        enabled=False,
    ),
    _count_description("held_updates", "held_updates", _updates("held"), False),
    _bytes_description("memory_used", "memory_used", _size("metrics", "memoryUsed")),
    _bytes_description("memory_total", "memory_total", _size("metrics", "memoryTotal")),
    _bytes_description(
        "images_size", "disk_usage_images", _size("images", "totalSize"), False
    ),
    _bytes_description(
        "containers_size", "disk_usage_containers", _size("containersSize"), False
    ),
    _bytes_description(
        "volumes_size", "disk_usage_volumes", _size("volumes", "totalSize"), False
    ),
    _bytes_description(
        "build_cache_size", "disk_usage_build_cache", _size("buildCacheSize"), False
    ),
    _count_description(
        "events_today", "activity_events_today", _stat("events", "today"), False
    ),
)


class DockhandEnvValueSensor(BaseFastEnvSensor):
    """A count or size about the environment, from Dockhand's dashboard
    stats and container list (ENV_VALUE_SENSORS)."""

    entity_description: DockhandEnvValueDescription

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        update_coordinator: DockhandUpdateCoordinator | None,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        description: DockhandEnvValueDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        # Precise-update data is read when the fast poll updates this
        # entity, not on its own (longer) schedule.
        self._update_coordinator = update_coordinator
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{env_id}_{description.key}"

    @property
    @override
    def native_value(self) -> Any:
        env = _coordinator_env(self.coordinator.data, self._env_id)
        update_env = (
            _coordinator_env(self._update_coordinator.data, self._env_id)
            if self._update_coordinator is not None
            else None
        )
        return self.entity_description.value_fn(env, update_env)


class DockhandEnvStacksSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "stacks"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_stacks_total"

    @property
    @override
    def native_value(self) -> int | None:
        return (self._stats().get("stacks") or {}).get("total")


class DockhandEnvImagesSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "image_count"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_images_total"

    @property
    @override
    def native_value(self) -> int | None:
        return (self._stats().get("images") or {}).get("total")


class DockhandEnvVolumesSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "volume_count"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_volumes_total"

    @property
    @override
    def native_value(self) -> int | None:
        return (self._stats().get("volumes") or {}).get("total")


class DockhandEnvNetworksSensor(BaseFastEnvSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "network_count"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_networks_total"

    @property
    @override
    def native_value(self) -> int | None:
        return (self._stats().get("networks") or {}).get("total")


class DockhandEnvDiskUsageSensor(BaseFastEnvSensor):
    """Docker's disk usage for the environment: images, containers,
    volumes and build cache together, from Dockhand's dashboard stats. Each
    part has its own sensor (ENV_VALUE_SENSORS)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "disk_usage"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_disk_usage"

    def _sizes(self) -> tuple[int, int, int, int]:
        s = self._stats()
        images = s.get("images") or {}
        volumes = s.get("volumes") or {}
        images_size = images.get("totalSize")
        volumes_size = volumes.get("totalSize")
        containers_size = s.get("containersSize")
        build_cache_size = s.get("buildCacheSize")
        return (
            images_size if isinstance(images_size, int) else 0,
            volumes_size if isinstance(volumes_size, int) else 0,
            containers_size if isinstance(containers_size, int) else 0,
            build_cache_size if isinstance(build_cache_size, int) else 0,
        )

    @property
    @override
    def native_value(self) -> int:
        return sum(self._sizes())


class DockhandEnvActivityEventsSensor(BaseFastEnvSensor):
    """Activity events sensor — state is the running total (today's count
    has its own sensor), with the most recent events as an attribute.

    recent_events is sourced from the slow coordinator (GET /api/activity,
    600s cadence, gated on collectActivity — see coordinator.py) rather
    than the fast coordinator's aggregate today/total counts, which come
    from a cheaper stats endpoint. Same cross-coordinator pattern as
    DockhandEnvCpuSensor's cpu_count attribute. Marked unrecorded since a
    list-of-dicts attribute that changes most polls would otherwise bloat
    the recorder database for no benefit — the individual events aren't
    meaningful history once superseded by the next poll's list.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "activity_events"
    _unrecorded_attributes = frozenset({"recent_events"})

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        slow_coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._slow_coordinator = slow_coordinator
        self._attr_unique_id = f"{self._entry_id}_{env_id}_events_total"

    @property
    @override
    def native_value(self) -> int | None:
        return (self._stats().get("events") or {}).get("total")

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        slow_data = self._slow_coordinator.data or {}
        env = _coordinator_env(slow_data, self._env_id)
        # None (not []) when this specific fetch failed — distinguishes
        # "we don't know" from "genuinely zero recent events," same
        # reasoning as BaseSlowEnvSensor's _fetch_failure_key, just
        # applied to one attribute instead of the whole entity, since
        # native_value above is fast-data-derived and unaffected by this
        # failure — marking the whole entity unavailable would wrongly
        # hide a still-valid state along with the one stale attribute.
        if "recent_events" in (env.get("fetch_failures") or set()):
            recent_events = None
        else:
            raw_events = env.get("recent_events") or []
            recent_events = [
                {
                    "container_name": ev.get("containerName"),
                    "action": ev.get("action"),
                    "timestamp": ev.get("timestamp"),
                }
                for ev in raw_events
                if isinstance(ev, dict)
            ][:10]
        return {"recent_events": recent_events}


# --------------------------------------------------------------------------- #
# Fast coordinator — container sensors
# --------------------------------------------------------------------------- #


# Docker's container states (Engine API ContainerState.Status) and health
# statuses; anything else Dockhand ever reports reads as unknown.
CONTAINER_STATES = [
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
]
CONTAINER_HEALTH_STATES = ["healthy", "unhealthy", "starting"]
# Dockhand's stack statuses (stacks.ts, stack-status.ts).
STACK_STATES = ["running", "partial", "restarting", "stopped", "created"]
# Dockhand's ScheduleStatus (db.ts).
SCHEDULE_STATUSES = [
    "queued",
    "running",
    "success",
    "failed",
    "skipped",
    "warning",
    "error",
    "cancelled",
    "stale",
]


class DockhandContainerStateSensor(BaseFastContainerSensor):
    """Container state sensor — aligned with Portainer's sensor.container_state."""

    _attr_translation_key = "state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CONTAINER_STATES

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, container)
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_state"
        )

    @property
    @override
    def native_value(self) -> str | None:
        state = (self._container() or {}).get("state")
        return state if state in CONTAINER_STATES else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._container()
        if not c:
            return {}
        restarting = c.get("state") == "restarting"
        # Not Docker's status text ("Up 3 hours"): it changes every minute
        # on its own, and would write a new state to the database each time.
        return {
            "image": c.get("image"),
            # Dockhand only counts restarts for a container restarting now.
            "restart_count": c.get("restartCount") if restarting else None,
            "exit_code": c.get("exitCode") if c.get("state") == "exited" else None,
            "networks": {
                n: i.get("ipAddress") for n, i in (c.get("networks") or {}).items()
            },
            # Dockhand's own infrastructure: Dockhand itself or a Hawser agent.
            "system_container": bool(c.get("systemContainer")),
            **tags.attributes(
                _coordinator_env(self.coordinator.data, self._env_id)
                .get("container_tags", {})
                .get(self._container_name, [])
            ),
        }


class DockhandContainerHealthSensor(BaseFastContainerSensor):
    """Container health sensor — only created when the container has a healthcheck.

    Enabled by default: when a container exposes health data it is immediately
    actionable (automations on unhealthy, dashboards, alerts). Containers
    without a healthcheck never get this entity, so the sensor is never
    permanently-unknown for containers that don't report health.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "health"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CONTAINER_HEALTH_STATES

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, container)
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_health"
        )

    @property
    @override
    def native_value(self) -> str | None:
        health = (self._container() or {}).get("health")
        return health if health in CONTAINER_HEALTH_STATES else None


# --------------------------------------------------------------------------- #
# Fast coordinator — container stats sensors
#
# All 8 sensors are created for every container but start disabled.
# Users enable only the ones they care about — enabled/disabled state
# survives container recreation because it is keyed on unique_id, which
# is derived from env_id + container name (both stable across restarts).
#
# Sensors return None (→ unavailable) when a container is stopped or
# exited; the stats endpoint omits non-running containers entirely.
#
# networkRx/Tx and blockRead/Write are cumulative counters that reset to
# zero when the container restarts.  TOTAL_INCREASING state class lets HA
# handle these correctly in long-term statistics — a reset simply begins
# a new rising segment rather than being treated as an error.
# --------------------------------------------------------------------------- #


class DockhandContainerCpuSensor(BaseFastContainerStatsSensor):
    """Container CPU usage as a percentage of total host CPU capacity."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "container_cpu_percent"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_cpu_percent"
        )

    @property
    @override
    def native_value(self) -> float | None:
        s = self._container_stats()
        if s is None:
            return None
        cpu = s.get("cpuPercent")
        return round(cpu, 2) if cpu is not None else None


class DockhandContainerMemoryUsageSensor(BaseFastContainerStatsSensor):
    """Container effective memory usage in bytes (cache excluded)."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "container_memory_usage"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_memory_usage"
        )

    @property
    @override
    def native_value(self) -> int | None:
        s = self._container_stats()
        if s is None:
            return None
        usage = s.get("memoryUsage")
        return int(usage) if usage is not None else None


class DockhandContainerMemoryCacheSensor(BaseFastContainerStatsSensor):
    """Container page cache in bytes, left out of its memory usage."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "container_memory_cache"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_memory_cache"
        )

    @property
    @override
    def native_value(self) -> int | None:
        s = self._container_stats()
        cache = s.get("memoryCache") if s else None
        return int(cache) if cache is not None else None


class DockhandContainerMemoryPercentSensor(BaseFastContainerStatsSensor):
    """Container memory usage as a percentage of its configured limit."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "container_memory_percent"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_memory_percent"
        )

    @property
    @override
    def native_value(self) -> float | None:
        s = self._container_stats()
        if s is None:
            return None
        pct = s.get("memoryPercent")
        return round(pct, 2) if pct is not None else None


class DockhandContainerMemoryLimitSensor(BaseFastContainerStatsSensor):
    """Container memory limit in bytes.

    When no explicit limit is set, Dockhand reports the total host RAM.
    """

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "container_memory_limit"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_memory_limit"
        )

    @property
    @override
    def native_value(self) -> int | None:
        s = self._container_stats()
        if s is None:
            return None
        limit = s.get("memoryLimit")
        return int(limit) if limit is not None else None


class DockhandContainerNetworkRxSensor(BaseFastContainerStatsSensor):
    """Cumulative bytes received by the container since last restart."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "container_network_rx"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_network_rx"
        )

    @property
    @override
    def native_value(self) -> int | None:
        s = self._container_stats()
        if s is None:
            return None
        rx = s.get("networkRx")
        return int(rx) if rx is not None else None


class DockhandContainerNetworkTxSensor(BaseFastContainerStatsSensor):
    """Cumulative bytes transmitted by the container since last restart."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "container_network_tx"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_network_tx"
        )

    @property
    @override
    def native_value(self) -> int | None:
        s = self._container_stats()
        if s is None:
            return None
        tx = s.get("networkTx")
        return int(tx) if tx is not None else None


class DockhandContainerBlockReadSensor(BaseFastContainerStatsSensor):
    """Cumulative bytes read from block devices since last restart."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "container_block_read"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_block_read"
        )

    @property
    @override
    def native_value(self) -> int | None:
        s = self._container_stats()
        if s is None:
            return None
        br = s.get("blockRead")
        return int(br) if br is not None else None


class DockhandContainerBlockWriteSensor(BaseFastContainerStatsSensor):
    """Cumulative bytes written to block devices since last restart."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "container_block_write"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
        stats_enabled: bool,
    ) -> None:
        super().__init__(
            coordinator, entry_id, env_id, env_name, base_url, container, stats_enabled
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_container_{self._container_name}_block_write"
        )

    @property
    @override
    def native_value(self) -> int | None:
        s = self._container_stats()
        if s is None:
            return None
        bw = s.get("blockWrite")
        return int(bw) if bw is not None else None


# --------------------------------------------------------------------------- #
# Fast coordinator — stack sensors
# --------------------------------------------------------------------------- #


class DockhandStackStatusSensor(BaseFastStackSensor):
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STACK_STATES

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, stack)
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_stack_{self._stack_name}_status"
        )

    @property
    @override
    def native_value(self) -> str | None:
        status = (self._stack() or {}).get("status")
        return status if status in STACK_STATES else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._stack()
        if not s:
            return {}
        source_type = s.get("sourceType")
        type_map = {"internal": "Internal", "git": "Git", "external": "Untracked"}
        type_label = (
            type_map.get(source_type, "Untracked")
            if isinstance(source_type, str)
            else "Untracked"
        )
        env_data = _coordinator_env(self.coordinator.data, self._env_id)
        return {
            "type": type_label,
            "system_container": _stack_has_system_container(
                s, env_data.get("containers") or []
            ),
            **tags.attributes(env_data.get("stack_tags", {}).get(self._stack_name, [])),
        }


class DockhandStackContainerCountSensor(BaseFastStackSensor):
    """Count of containers belonging to this stack."""

    _attr_translation_key = "containers_in_stack"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, stack)
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_stack_{self._stack_name}_container_count"
        )

    @property
    @override
    def native_value(self) -> int | None:
        s = self._stack()
        return len(s.get("containers") or []) if s else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._stack()
        if not s:
            return {}
        container_ids = s.get("containers") or []
        env_data = _coordinator_env(self.coordinator.data, self._env_id)
        return {"container_names": _resolve_container_names(container_ids, env_data)}


class DockhandStackUpdateCountSensor(BaseFastStackSensor):
    """How many of the stack's containers have an update, as Dockhand
    counts them."""

    _attr_translation_key = "stack_pending_updates"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, stack)
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_stack_{self._stack_name}_update_count"
        )

    @property
    @override
    def native_value(self) -> int | None:
        count = (self._stack() or {}).get("updateCount")
        return count if isinstance(count, int) else None


# --------------------------------------------------------------------------- #
# Slow coordinator — optional sensors
# --------------------------------------------------------------------------- #


class BaseSlowEnvSensor(CoordinatorEntity[DockhandSlowCoordinator], SensorEntity):
    _attr_has_entity_name = True
    # Overridden by subclasses whose *value* (existence is handled
    # entirely by cleanup — see __init__.py's _build_live_sets, not this)
    # depends on a resource fetch that can fail independently of the
    # overall slow poll succeeding — see coordinator.py's _unwrap and
    # docs/architecture.md §9. None (the default) means "not gated on any
    # single resource," which covers most subclasses; only host- and
    # vulnerabilities-derived ones need to set this.
    _fetch_failure_key: str | None = None

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url

    def _env_data(self) -> dict:
        return _coordinator_env(self.coordinator.data, self._env_id)

    @property
    @override
    def available(self) -> bool:
        if not super().available:
            return False
        if self._fetch_failure_key is None:
            return True
        failures = self._env_data().get("fetch_failures") or set()
        return self._fetch_failure_key not in failures

    @property
    @override
    def device_info(self) -> DeviceInfo:
        return _env_device(self._entry_id, self._env_id, self._env_name, self._base_url)


# --------------------------------------------------------------------------- #
# Fast coordinator — stack resource stats sensors
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class DockhandStackStatsDescription(SensorEntityDescription):
    """One of Dockhand's own stack totals — `key` is its unique_id suffix,
    the same as the matching container stats sensor's. There's no memory
    percentage: Dockhand doesn't report one for a stack."""

    value_fn: Callable[[dict[str, Any]], float | int | None]


def _round2(value: Any) -> float | None:
    return round(value, 2) if value is not None else None


def _as_int(value: Any) -> int | None:
    return int(value) if value is not None else None


STACK_STATS_SENSORS: tuple[DockhandStackStatsDescription, ...] = (
    DockhandStackStatsDescription(
        key="cpu_percent",
        translation_key="stack_cpu_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: _round2(t.get("cpuPercent")),
    ),
    DockhandStackStatsDescription(
        key="running_containers",
        translation_key="stack_running_containers",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.get("runningCount"),
    ),
    DockhandStackStatsDescription(
        key="memory_usage",
        translation_key="stack_memory_usage",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: _as_int(t.get("memoryUsage")),
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
    ),
    DockhandStackStatsDescription(
        key="memory_limit",
        translation_key="stack_memory_limit",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: _as_int(t.get("memoryLimit")),
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
    ),
    DockhandStackStatsDescription(
        key="network_rx",
        translation_key="stack_network_rx",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda t: _as_int(t.get("networkRx")),
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
    ),
    DockhandStackStatsDescription(
        key="network_tx",
        translation_key="stack_network_tx",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda t: _as_int(t.get("networkTx")),
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
    ),
    DockhandStackStatsDescription(
        key="block_read",
        translation_key="stack_block_read",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda t: _as_int(t.get("blockRead")),
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
    ),
    DockhandStackStatsDescription(
        key="block_write",
        translation_key="stack_block_write",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda t: _as_int(t.get("blockWrite")),
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
    ),
)


class DockhandStackStatsSensor(BaseFastStackSensor):
    """A stack's CPU/memory/network/block-I/O total, exactly as Dockhand
    reports it (GET /api/stack-stats, 1.0.52+) — the stack-level
    counterpart of the container stats sensors, created and removed with
    the same "Enable container and stack stats" option, and only where Dockhand has
    the endpoint. Unavailable while none of the stack's containers is
    running (Dockhand leaves such a stack out), like a stopped container's
    own stats sensors."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: DockhandStackStatsDescription

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict,
        description: DockhandStackStatsDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, stack)
        self.entity_description = description
        self._attr_unique_id = (
            f"{entry_id}_{env_id}_stack_{self._stack_name}_{description.key}"
        )

    def _totals(self) -> dict[str, Any] | None:
        stack_stats = _coordinator_env(self.coordinator.data, self._env_id).get(
            "stack_stats"
        )
        return (stack_stats or {}).get(self._stack_name)

    @property
    @override
    def available(self) -> bool:
        return super().available and self._totals() is not None

    @property
    @override
    def native_value(self) -> float | int | None:
        totals = self._totals()
        return self.entity_description.value_fn(totals) if totals else None


# --------------------------------------------------------------------------- #
# Slow coordinator — environment config sensors (from /api/environments)
# --------------------------------------------------------------------------- #


class DockhandEnvHawserVersionSensor(BaseSlowEnvSensor):
    """Hawser agent version string — None until the agent first checks in.

    Sourced entirely from /api/host: for hawser-standard (port-bind)
    connections, it live-fetches the version from the agent on every
    call; for hawser-edge it falls back to Dockhand's own persisted
    value.

    agent_name/agent_id attributes come from /api/environments' env_meta
    (see coordinator.py — only the needed fields are extracted from that
    response, never the raw one with its decrypted secrets) since
    /api/host doesn't have them. Dockhand only fills them in for Hawser
    Edge; they're None otherwise.
    """

    _attr_translation_key = "hawser_agent_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _fetch_failure_key = "host"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_hawser_version"

    def _host_env(self) -> dict:
        return (self._env_data().get("host") or {}).get("environment") or {}

    @property
    @override
    def native_value(self) -> str | None:
        return self._host_env().get("hawserVersion")

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        meta = self._env_data().get("env_meta") or {}
        return {
            "agent_name": meta.get("hawserAgentName"),
            "agent_id": meta.get("hawserAgentId"),
        }


class DockhandEnvHawserLastSeenSensor(BaseSlowEnvSensor):
    """When the environment's Hawser Edge agent last checked in, the only
    connection type Dockhand records it for. It changes on every poll, so
    it's off by default: each change is a row in the database."""

    _attr_translation_key = "hawser_last_seen"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_hawser_last_seen"

    @property
    @override
    def native_value(self) -> datetime | None:
        meta = self._env_data().get("env_meta") or {}
        return _parse_dt(meta.get("hawserLastSeen"))


class DockhandEnvVulnerabilitiesSensor(BaseSlowEnvSensor):
    """Cached vulnerability scan summary for an environment.

    Sourced from GET /api/vulnerabilities/count (gated on scannerEnabled —
    see coordinator.py), the same endpoint Dockhand's own dashboard badge
    reads from — this is Dockhand's cached aggregation, not a fresh scan
    trigger, so polling it every 600s costs nothing extra server-side.

    State is the total finding count; each severity, and how many images
    have been scanned, have their own sensors (VULNERABILITY_SENSORS).
    """

    _attr_translation_key = "vulnerabilities"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _fetch_failure_key = "vulnerabilities"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_vulnerabilities"

    def _summary(self) -> dict:
        return self._env_data().get("vulnerabilities") or {}

    @property
    @override
    def native_value(self) -> int | None:
        return self._summary().get("total")


# Dockhand's vulnerability summary field → translation key.
VULNERABILITY_SENSORS = {
    "critical": "vulnerabilities_critical",
    "high": "vulnerabilities_high",
    "medium": "vulnerabilities_medium",
    "low": "vulnerabilities_low",
    "imagesScanned": "images_scanned",
}


class DockhandEnvVulnerabilityCountSensor(DockhandEnvVulnerabilitiesSensor):
    """One count from the vulnerability summary: findings of one severity,
    or the images scanned so far."""

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        field: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._field = field
        self._attr_translation_key = VULNERABILITY_SENSORS[field]
        self._attr_unique_id = (
            f"{self._entry_id}_{env_id}_{VULNERABILITY_SENSORS[field]}"
        )

    @property
    @override
    def native_value(self) -> int | None:
        value = self._summary().get(self._field)
        return value if isinstance(value, int) else None


class BaseSlowEnvHostSensor(BaseSlowEnvSensor):
    """Env sensors sourced from the top-level fields of GET /api/host
    (hostname/platform/arch/cpus/memory/uptime/dockerVersion) — distinct
    from DockhandEnvHawserVersionSensor's nested "environment" sub-object.

    All of this comes from data the slow coordinator already fetches for
    the Hawser version sensor — no additional API call. Deliberately
    skips dockerContainers/dockerContainersRunning/dockerImages, which
    would duplicate the existing Containers-running and Images sensors
    (sourced from /api/dashboard/stats), and totalMemory/freeMemory,
    which would duplicate the existing Memory usage sensor's used/total
    byte attributes (also from dashboard/stats metrics). cpus (a raw
    count, not a percentage) has no existing equivalent, so it's kept.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _fetch_failure_key = "host"

    def _host(self) -> dict:
        return self._env_data().get("host") or {}


class DockhandEnvPlatformSensor(BaseSlowEnvHostSensor):
    """Host OS platform, e.g. 'linux', 'darwin', 'win32' (Node's os.platform())."""

    _attr_translation_key = "host_platform"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_host_platform"

    @property
    @override
    def native_value(self) -> str | None:
        return self._host().get("platform")

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        # architecture — folded in here rather than its own sensor, same
        # reasoning as cpu_count on the CPU usage sensor: one more static
        # fact about the same underlying host doesn't need its own entity.
        # Unlike architecture, Docker version and host uptime stay as
        # their own sensors: version data is commonly its own entity
        # elsewhere, and usable on a dashboard without a template.
        return {"architecture": self._host().get("arch")}


class DockhandEnvDockerVersionSensor(BaseSlowEnvHostSensor):
    """Docker Engine server version string."""

    _attr_translation_key = "host_docker_version"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_host_docker_version"

    @property
    @override
    def native_value(self) -> str | None:
        version = self._host().get("dockerVersion")
        # Reported as the literal string "unknown" for some connection
        # types Dockhand can't determine it for (see /api/host source) —
        # treat that the same as genuinely absent rather than displaying
        # the word "unknown" as if it were a real version string.
        return version if version and version != "unknown" else None


_BOOT_DRIFT = timedelta(minutes=1)


class DockhandEnvLastBootSensor(BaseSlowEnvHostSensor):
    """Host uptime, computed from Node's os.uptime() (seconds since boot)
    at the moment /api/host was called, expressed as a boot-time
    TIMESTAMP rather than a raw duration — matches the convention HA's
    own System Monitor integration uses for the same concept, and lets
    HA's own per-entity "Display as: Relative time" setting show it as
    "2 days ago" / "3 weeks ago" natively — no new device_class or
    server-side duration formatting needed, HA already does this
    conversion for any TIMESTAMP sensor when the user opts into it.

    Named/keyed as "uptime" (translation_key), matching Dockhand's own
    API field name, even though the underlying value is a timestamp —
    "Uptime" is the more intuitive label for what this represents.

    Uptime and the clock are read at slightly different moments, so the
    boot time computed from them moves by a fraction of a second every
    poll. Each move would be a new state in the database, so it only
    changes when it moves by more than a minute (a reboot).
    """

    _last_boot: datetime | None = None

    _attr_translation_key = "uptime"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._attr_unique_id = f"{self._entry_id}_{env_id}_host_last_boot"

    @property
    @override
    def native_value(self) -> datetime | None:
        uptime_seconds = self._host().get("uptime")
        if not isinstance(uptime_seconds, int | float) or uptime_seconds < 0:
            return None
        boot = dt_util.utcnow() - timedelta(seconds=uptime_seconds)
        if self._last_boot is None or abs(boot - self._last_boot) > _BOOT_DRIFT:
            self._last_boot = boot
        return self._last_boot


class DockhandImageSensor(BaseSlowEnvSensor):
    """Entity for a single Docker image, living under the Images group device.

    One entity per image — no individual image devices. The entity name is the
    repository portion of the primary tag (e.g. "cloudflare/cloudflared") and
    the state is the tag portion (e.g. "latest", "2.1.0"). For untagged images
    the name is the short hash ID and the state is None. All image metadata
    (size, digests, OCI labels, created, containers_using) is surfaced as
    extra_state_attributes.

    name is a live @property, not a value fixed at construction — see its
    docstring for why.

    API shape (confirmed from /api/images): camelCase fields, created is a
    Unix timestamp integer, containers is always an int (0 = unused).
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:package-variant-closed"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        image: dict,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        raw_id = image.get("id") or ""
        # Strip "sha256:" prefix — store just the 64-char hex for lookups
        self._image_id = raw_id.split(":")[-1] if ":" in raw_id else raw_id
        # Fallback repo name if a live lookup ever comes back empty (image
        # gone entirely — shouldn't normally happen while this entity still
        # exists, but avoids a blank name in that edge case).
        primary_tag = _image_display_name(image)  # e.g. "cloudflare/cloudflared:latest"
        self._image_repo_fallback = (
            primary_tag.rsplit(":", 1)[0] if ":" in primary_tag else primary_tag
        )
        self._attr_unique_id = f"{self._entry_id}_{env_id}_image_{self._image_id}"

    def _image(self) -> dict | None:
        for img in self._env_data().get("images") or []:
            raw_id = img.get("id") or ""
            short_id = raw_id.split(":")[-1] if ":" in raw_id else raw_id
            if short_id == self._image_id and isinstance(img, dict):
                return img
        return None

    @property
    @override
    def name(self) -> str:
        """Recomputed from live data on every access — NOT fixed at
        construction. The unique_id is hash-based and this entity object
        is reused indefinitely for the same hash (see the dedup pattern
        in async_setup_entry), so a static name would go stale the moment
        this image's tag changes: a container upgrade pulls a new image
        under the same repo:tag, the old image (this one) loses that tag
        and becomes just a hash — if the name were fixed at construction,
        this entity would keep showing the old repo:tag forever, and
        worse, would permanently occupy the entity_id slot the *new*
        image's entity actually deserves, forcing it into an auto-
        suffixed "_2" id that never self-heals without a manual
        "recreate entity ids" action. Recomputing live means this
        entity's name correctly becomes the short hash on the very next
        poll after the tag moves elsewhere, freeing the slot naturally.
        See also the tag-collision check in async_setup_entry, which
        covers the (usually one extra poll cycle) window before that
        happens, where the two images might briefly still agree on the
        same tag.
        """
        img = self._image()
        if img is None:
            return self._image_repo_fallback
        primary_tag = _image_display_name(img)
        return primary_tag.rsplit(":", 1)[0] if ":" in primary_tag else primary_tag

    @property
    @override
    def native_value(self) -> str | None:
        """The tag portion of the primary tag, e.g. 'latest' or '2.1.0'."""
        img = self._image()
        if img is None:
            return None
        tags = [t for t in (img.get("repoTags") or []) if t and t != "<none>:<none>"]
        if not tags:
            return None  # untagged image — no meaningful tag value
        primary = str(tags[0])
        return primary.rsplit(":", 1)[1] if ":" in primary else primary

    @property
    @override
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
            except OverflowError, OSError, ValueError:
                pass

        return {
            "tags": tags,
            "digests": digests,
            "size_bytes": size,
            "created": created_iso,
            "containers_using": containers_using,
            "version": oci_version,
            "vendor": oci_vendor,
            "title": oci_title,
            "source": oci_source,
        }

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """All image entities live under the per-env Images group device."""
        return _image_group_device(
            getattr(self, "hass", None),
            self._entry_id,
            self._env_id,
            self._env_name,
            self._base_url,
        )


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
    _attr_has_entity_name = True
    _attr_icon = "mdi:lan"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        network: dict,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._network_id = network.get("id", "")
        self._network_name = network.get("name", "")
        self._attr_unique_id = f"{self._entry_id}_{env_id}_network_{self._network_id}"
        self._attr_name = self._network_name

    def _network(self) -> dict | None:
        for n in self._env_data().get("networks") or []:
            if isinstance(n, dict) and n.get("id") == self._network_id:
                return n
        return None

    @property
    @override
    def native_value(self) -> int | None:
        n = self._network()
        return len(n.get("containers") or {}) if n else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        n = self._network()
        if not n:
            return {}
        ipam = (n.get("ipam") or {}).get("config") or []
        connected = {
            i.get("name"): i.get("ipv4Address")
            for i in (n.get("containers") or {}).values()
            if i.get("name")
        }
        return {
            "driver": n.get("driver"),
            "scope": n.get("scope"),
            "internal": n.get("internal"),
            "subnet": ipam[0].get("subnet") if ipam else None,
            "connected_containers": connected,
        }

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """All network entities live under the per-env Networks group device."""
        return _network_group_device(
            getattr(self, "hass", None),
            self._entry_id,
            self._env_id,
            self._env_name,
            self._base_url,
        )


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
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        volume: dict,
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url)
        self._volume_name: str = volume.get("name") or volume.get("Name") or "unknown"
        self._attr_unique_id = f"{self._entry_id}_{env_id}_volume_{self._volume_name}"
        self._attr_name = self._volume_name

    def _volume(self) -> dict | None:
        for v in self._env_data().get("volumes") or []:
            if (v.get("name") or v.get("Name")) == self._volume_name and isinstance(
                v, dict
            ):
                return v
        return None

    @property
    @override
    def native_value(self) -> int | None:
        """Container count — 0 means unused/dangling, a pruning candidate."""
        v = self._volume()
        if not v:
            return None
        used_by = v.get("usedBy") or v.get("UsedBy") or []
        return len(used_by)

    @property
    @override
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
    @override
    def device_info(self) -> DeviceInfo:
        """All volume entities live under the per-env Volumes group device."""
        return _volume_group_device(
            getattr(self, "hass", None),
            self._entry_id,
            self._env_id,
            self._env_name,
            self._base_url,
        )


# --------------------------------------------------------------------------- #
# Slow coordinator — schedule sensors
# --------------------------------------------------------------------------- #


class _BaseScheduleSensor(DockhandScheduleEntity, SensorEntity):
    """Common base for per-schedule sensors."""


class DockhandScheduleNextRunSensor(_BaseScheduleSensor):
    """Next scheduled run — TIMESTAMP sensor for time-based automations.

    Keeping this as a first-class entity (not an attribute) lets users write
    clean ``trigger: state`` automations against the timestamp directly.
    """

    _attr_translation_key = "next_run"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        sched: dict,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, sched, base_url, "next_run")

    @property
    @override
    def native_value(self) -> datetime | None:
        s = self._find()
        return _parse_dt(s.get("nextRun")) if s else None

    @property
    @override
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

    Not diagnostic — "current known status" is core, everyday-relevant
    information about a schedule, not technical/troubleshooting trivia,
    matching this codebase's own precedent (DockhandStackStatusSensor,
    DockhandGitStackSyncStatusSensor — the closest existing analogs — are
    both primary, not diagnostic). This is the primary/comprehensive entity
    for a schedule device: it carries the identity attributes
    (description, is_system; the name is the device's) alongside the
    scheduling ones already on
    Next run (cron_expression, enabled, environment, schedule_type) —
    duplicated rather than moved, since automations and templates may
    read them from Next run; duplication here is safe (both read
    fresh from the same coordinator dict every update, unlike DeviceInfo
    fields, which is why that duplication was a bug and this one isn't).
    """

    _attr_translation_key = "last_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = SCHEDULE_STATUSES

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        entry_id: str,
        sched: dict,
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, sched, base_url, "last_status")

    @property
    @override
    def native_value(self) -> str | None:
        s = self._find()
        if s:
            status = (s.get("lastExecution") or {}).get("status")
            return status if status in SCHEDULE_STATUSES else None
        return None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._find()
        if not s:
            return {}
        last = s.get("lastExecution") or {}
        return {
            "description": s.get("description"),
            "is_system": s.get("isSystem"),
            "cron_expression": s.get("cronExpression"),
            "enabled": s.get("enabled"),
            "environment": s.get("environmentName"),
            "schedule_type": s.get("type"),
            "triggered_by": last.get("triggeredBy"),
            "triggered_at": last.get("triggeredAt"),
            "duration_ms": last.get("duration"),
            "error_message": last.get("errorMessage"),
            "updates_found": (last.get("details") or {}).get("updatesFound"),
        }


# ===========================================================================
# Git stack sensors (slow coordinator, always created when a stack is
# detected as git-tracked — no config gate; it's one bulk call per
# environment, not per-stack, so there's no meaningful API cost to gate)
# ===========================================================================


class BaseSlowGitStackSensor(CoordinatorEntity[DockhandSlowCoordinator], SensorEntity):
    """Base for per-git-stack slow-coordinator sensors.

    Lives on the same device as the regular Stack (_stack_device) — a git
    stack IS a regular Compose stack, just with extra sync/deploy metadata
    Dockhand tracks separately from /api/stacks. No separate device type.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

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

    def _git_stack(self) -> dict[str, Any] | None:
        return _find_git_stack(self.coordinator.data, self._env_id, self._stack_name)

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


class DockhandGitStackSyncStatusSensor(BaseSlowGitStackSensor):
    """Current git sync status: pending / syncing / synced / error."""

    _attr_translation_key = "git_stack_sync_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["pending", "syncing", "synced", "error"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_unique_id = (
            f"{self._entry_id}_{self._env_id}_stack_{self._stack_name}_git_sync_status"
        )

    @property
    @override
    def native_value(self) -> str | None:
        gs = self._git_stack()
        return gs.get("syncStatus") if gs else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        gs = self._git_stack()
        if not gs:
            return {}
        return {
            "last_commit": gs.get("lastCommit"),
            "sync_error": gs.get("syncError"),
            "auto_update": gs.get("autoUpdate"),
            "webhook_enabled": gs.get("webhookEnabled"),
        }


class DockhandGitStackLastSyncSensor(BaseSlowGitStackSensor):
    """Timestamp of the last git sync — for time-based automations."""

    _attr_translation_key = "git_stack_last_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_unique_id = (
            f"{self._entry_id}_{self._env_id}_stack_{self._stack_name}_git_last_sync"
        )

    @property
    @override
    def native_value(self) -> datetime | None:
        gs = self._git_stack()
        return _parse_dt(gs.get("lastSync")) if gs else None
