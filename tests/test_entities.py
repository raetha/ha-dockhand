"""
Tests for entity classes across all platforms.

Covers: native_value, extra_state_attributes, is_on, entity metadata
(unique_id, category, enabled-by-default, has_entity_name), device_info
parentage, action method calls, and HomeAssistantError propagation.

Entities are instantiated directly with mock coordinators — no full HA
platform setup required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

DOMAIN = "dockhand"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ENV_ID = 1
ENV_NAME = "MyHost"
BASE_URL = "http://dh.test:3000"
ENTRY_ID = "test_entry_id"

STATS = {
    "name": "MyHost",
    "online": True,
    "connectionType": "socket",
    "metrics": {
        "memoryPercent": 45.2,
        "memoryUsed": 4724464640,
        "memoryTotal": 8589934592,
        "cpuPercent": 23.5,
    },
    "containers": {
        "total": 4,
        "running": 3,
        "stopped": 1,
        "paused": 0,
        "restarting": 0,
        "unhealthy": 0,
        "pendingUpdates": 1,
    },
    "stacks": {"total": 2, "running": 2, "partial": 0, "stopped": 0},
    "images": {"total": 5, "totalSize": 2147483648},
    "volumes": {"total": 2, "totalSize": 1073741824},
    "networks": {"total": 3},
    "containersSize": 524288000,
    "buildCacheSize": 104857600,
    "activityEvents": 10,
    "hawserVersion": None,
    "collectActivity": True,
    "collectMetrics": True,
    "scannerEnabled": False,
    "updateCheckEnabled": True,
    "autoUpdate": False,
    "imagePrune": True,
}

CONTAINER = {
    "id": "abc123",
    "name": "nginx",
    "state": "running",
    "image": "nginx:latest",
    "labels": {},
    "health": "healthy",
}

COMPOSE_CONTAINER = {
    "id": "def456",
    "name": "web",
    "state": "running",
    "image": "python:3.11",
    "labels": {"com.docker.compose.project": "myapp"},
    "health": None,
}

STACK = {"name": "myapp", "status": "running", "containers": ["c1", "c2", "c3"]}

IMAGE = {
    "id": "sha256:deadbeef1234",
    "size": 104857600,
    "repoTags": ["nginx:latest"],
    "repoDigests": [],
    "containers": 2,
    "created": 1700000000,
    "labels": {},
}

NETWORK = {
    "id": "net123",
    "name": "bridge",
    "driver": "bridge",
    "scope": "local",
    "internal": False,
    "ipam": {"config": [{"subnet": "172.17.0.0/16"}]},
    "containers": {"c1": {"name": "nginx", "ipv4Address": "172.17.0.2"}},
}

VOLUME = {
    "name": "mydata",
    "driver": "local",
    "mountpoint": "/var/lib/docker/volumes/mydata/_data",
    "scope": "local",
    "created": "2026-03-01T22:12:16-05:00",
    "labels": {},
    "usedBy": ["container_abc123"],
}

VOLUME_UNUSED = {**VOLUME, "usedBy": []}

SCHEDULE = {
    "id": "sched1",
    "name": "nightly-backup",
    "type": "system",
    "cronExpression": "0 2 * * *",
    "enabled": True,
    "environmentName": "Heimdall",
    "nextRun": 1700100000,
    "lastExecution": {
        "status": "success",
        "triggeredBy": "schedule",
        "triggeredAt": "2023-11-15T20:00:00Z",
        "duration": 42000,
        "errorMessage": None,
    },
}

SCHEDULE_FAILED = {
    **SCHEDULE,
    "nextRun": 1700200000,
    "lastExecution": {
        "status": "failed",
        "triggeredBy": "schedule",
        "triggeredAt": "2023-11-16T02:00:00Z",
        "duration": 1200,
        "errorMessage": "Connection timeout",
    },
}


# ---------------------------------------------------------------------------
# Coordinator factories
# ---------------------------------------------------------------------------


def _fast_coord(env_data=None):
    coord = MagicMock()
    coord.data = {
        "environments": {
            ENV_ID: env_data
            or {
                "stats": STATS,
                "containers": [CONTAINER],
                "stacks": [STACK],
                "container_stats": {},
                "pending_update_container_ids": {CONTAINER["id"]},
            }
        }
    }
    coord.last_update_success = True
    coord.async_refresh = AsyncMock()
    return coord


def _slow_coord(env_data=None, schedules=None):
    coord = MagicMock()
    coord.data = {
        "environments": {
            ENV_ID: env_data
            or {
                "env": {"name": ENV_NAME},
                "images": [IMAGE],
                "networks": [NETWORK],
                "volumes": [VOLUME],
            }
        },
        "schedules": schedules if schedules is not None else [SCHEDULE],
    }
    coord.last_update_success = True
    coord.async_refresh = AsyncMock()
    return coord


# ---------------------------------------------------------------------------
# Lazy imports (avoid HA import ordering issues at module level)
# ---------------------------------------------------------------------------


def _sensor_classes():
    from custom_components.dockhand.sensor import (
        DockhandContainerBlockReadSensor,
        DockhandContainerBlockWriteSensor,
        DockhandContainerCpuSensor,
        DockhandContainerHealthSensor,
        DockhandContainerMemoryLimitSensor,
        DockhandContainerMemoryPercentSensor,
        DockhandContainerMemoryUsageSensor,
        DockhandContainerNetworkRxSensor,
        DockhandContainerNetworkTxSensor,
        DockhandContainerStateSensor,
        DockhandEnvActivityEventsSensor,
        DockhandEnvConnectionTypeSensor,
        DockhandEnvContainerCountSensor,
        DockhandEnvCpuSensor,
        DockhandEnvDiskUsageSensor,
        DockhandEnvHawserVersionSensor,
        DockhandEnvImagesSensor,
        DockhandEnvMemPercentSensor,
        DockhandEnvNetworksSensor,
        DockhandEnvStacksSensor,
        DockhandEnvVolumesSensor,
        DockhandImageSensor,
        DockhandNetworkSensor,
        DockhandScheduleLastStatusSensor,
        DockhandScheduleNextRunSensor,
        DockhandStackContainerCountSensor,
        DockhandStackStatusSensor,
        DockhandVolumeSensor,
    )

    return locals()


def _bs_classes():
    from custom_components.dockhand.binary_sensor import (
        DockhandEnvAutoUpdateSensor,
        DockhandEnvCollectActivitySensor,
        DockhandEnvCollectMetricsSensor,
        DockhandEnvOnlineSensor,
        DockhandEnvScannerEnabledSensor,
        DockhandEnvUpdateCheckSensor,
        DockhandStackUpdatesAvailableBinarySensor,
    )

    return locals()


def _switch_classes():
    from custom_components.dockhand.switch import (
        DockhandContainerRunningSwitch,
        DockhandStackRunningSwitch,
    )

    return locals()


def _button_classes():
    from custom_components.dockhand.button import (
        DockhandContainerRestartButton,
        DockhandStackDeployButton,
        DockhandStackRestartButton,
    )

    return locals()


# ===========================================================================
# Environment sensors
# ===========================================================================


@pytest.fixture
def env_sensors():
    sc = _sensor_classes()
    coord = _fast_coord()
    slow_coord = _slow_coord()
    return {
        "cpu": sc["DockhandEnvCpuSensor"](
            coord, slow_coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        "mem": sc["DockhandEnvMemPercentSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        "containers": sc["DockhandEnvContainerCountSensor"](
            coord, None, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        "stacks": sc["DockhandEnvStacksSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        "images": sc["DockhandEnvImagesSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        "volumes": sc["DockhandEnvVolumesSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        "networks": sc["DockhandEnvNetworksSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        "disk_usage": sc["DockhandEnvDiskUsageSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        "connection_type": sc["DockhandEnvConnectionTypeSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
    }


def test_cpu_value(env_sensors):
    assert abs(env_sensors["cpu"].native_value - 23.5) < 1e-9


def test_cpu_count_attribute_from_slow_coordinator_host_data():
    from custom_components.dockhand.sensor import DockhandEnvCpuSensor

    fast_coord = _fast_coord()
    slow_coord = _slow_coord(env_data={"host": {"cpus": 8}})
    sensor = DockhandEnvCpuSensor(
        fast_coord, slow_coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    assert sensor.extra_state_attributes == {"cpu_count": 8, "top_containers": []}


def test_cpu_count_attribute_empty_when_absent():
    from custom_components.dockhand.sensor import DockhandEnvCpuSensor

    fast_coord = _fast_coord()
    slow_coord = _slow_coord(env_data={"host": {}})
    sensor = DockhandEnvCpuSensor(
        fast_coord, slow_coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    assert sensor.extra_state_attributes == {"top_containers": []}


def test_top_containers_ranked_by_cpu_no_extra_api_call():
    """top_containers is computed from container_stats, which
    async_get_container_stats() already fetches unconditionally every
    fast poll for every environment — no new API call, and no dependency
    on "Enable container stats" being on."""
    from custom_components.dockhand.sensor import DockhandEnvCpuSensor

    fast_coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": [],
            "stacks": [],
            "container_stats": {
                "web": {"name": "web", "cpuPercent": 12.3, "memoryPercent": 40.0},
                "db": {"name": "db", "cpuPercent": 55.1, "memoryPercent": 70.2},
                "cache": {"name": "cache", "cpuPercent": 2.0, "memoryPercent": 10.0},
            },
        }
    )
    slow_coord = _slow_coord()
    sensor = DockhandEnvCpuSensor(
        fast_coord, slow_coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    top = sensor.extra_state_attributes["top_containers"]
    assert [c["name"] for c in top] == ["db", "web", "cache"]
    assert top[0] == {"name": "db", "cpu_percent": 55.1, "memory_percent": 70.2}


def test_top_containers_capped_at_five():
    from custom_components.dockhand.sensor import DockhandEnvCpuSensor

    fast_coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": [],
            "stacks": [],
            "container_stats": {
                f"c{i}": {"name": f"c{i}", "cpuPercent": float(i), "memoryPercent": 1.0}
                for i in range(10)
            },
        }
    )
    slow_coord = _slow_coord()
    sensor = DockhandEnvCpuSensor(
        fast_coord, slow_coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    top = sensor.extra_state_attributes["top_containers"]
    assert len(top) == 5
    assert [c["name"] for c in top] == ["c9", "c8", "c7", "c6", "c5"]


def test_mem_percent_value(env_sensors):
    assert abs(env_sensors["mem"].native_value - 45.2) < 1e-9


def test_mem_attributes_raw_bytes(env_sensors):
    attrs = env_sensors["mem"].extra_state_attributes
    assert attrs["memory_used_bytes"] == 4724464640
    assert attrs["memory_total_bytes"] == 8589934592
    assert "memory_used_mib" not in attrs


def test_env_cpu_and_mem_value_none_when_metrics_explicitly_null():
    """End-to-end regression test for the actual reported crash
    (github.com/raetha/ha-dockhand/issues/20, and a live crash this
    session): Dockhand can send "metrics": null on an environment's stats
    blob rather than omitting the key. native_value must return None
    (making the entity unavailable), not raise AttributeError."""
    sc = _sensor_classes()
    coord = _fast_coord(
        env_data={
            "stats": {**STATS, "metrics": None},
            "containers": [CONTAINER],
            "stacks": [STACK],
            "container_stats": {},
        }
    )
    cpu_sensor = sc["DockhandEnvCpuSensor"](
        coord, _slow_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    mem_sensor = sc["DockhandEnvMemPercentSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    assert cpu_sensor.native_value is None
    assert mem_sensor.native_value is None
    assert mem_sensor.extra_state_attributes == {
        "memory_used_bytes": None,
        "memory_total_bytes": None,
    }


def test_container_count_total(env_sensors):
    assert env_sensors["containers"].native_value == 4


def test_container_count_attributes(env_sensors):
    attrs = env_sensors["containers"].extra_state_attributes
    assert attrs["running"] == 3
    assert attrs["stopped"] == 1
    # Sourced from pending_update_container_ids (Tier 1), not Dockhand's
    # own stats.containers.pendingUpdates — see the sensor's own comment
    # for why. This fixture's env_data sets pending_update_container_ids
    # to one container id, matching the pre-existing expectation here.
    assert attrs["pending_updates"] == 1


def test_container_count_pending_updates_excludes_system_containers():
    """pending_updates is the actionable/bulk-eligible count -- must
    exclude a system container's own pending update, matching
    _actionable_pending_update_container_ids()'s own exclusion (the same
    function the bulk-update button uses to decide what it will actually
    send to Dockhand's batch-update API). This container's update should
    still be visible somewhere, though -- see pending_system_updates and
    pending_updates_total below, which is the whole reason this became
    three attributes instead of one: a single count can't correctly
    answer both "how many things need attention" (should include this)
    and "how many things can I safely bulk-update" (should not) at once."""
    sc = _sensor_classes()
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": [
                CONTAINER,
                {
                    **CONTAINER,
                    "id": "sys-1",
                    "name": "watchtower",
                    "systemContainer": "watchtower",
                },
            ],
            "stacks": [STACK],
            "container_stats": {},
            "pending_update_container_ids": {"sys-1"},
        }
    )
    sensor = sc["DockhandEnvContainerCountSensor"](
        coord, None, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    attrs = sensor.extra_state_attributes
    assert attrs["pending_updates"] == 0
    assert attrs["pending_system_updates"] == 1
    assert attrs["pending_updates_total"] == 1


def test_container_count_pending_updates_mixed_system_and_normal():
    """Both a normal and a system container pending at once -- confirms
    the three attributes stay correctly separated rather than one
    leaking into another (e.g. a bug that summed both into
    pending_updates, or double-counted the normal one into
    pending_system_updates)."""
    sc = _sensor_classes()
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": [
                CONTAINER,
                {
                    **CONTAINER,
                    "id": "sys-1",
                    "name": "watchtower",
                    "systemContainer": "watchtower",
                },
            ],
            "stacks": [STACK],
            "container_stats": {},
            "pending_update_container_ids": {CONTAINER["id"], "sys-1"},
        }
    )
    sensor = sc["DockhandEnvContainerCountSensor"](
        coord, None, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    attrs = sensor.extra_state_attributes
    assert attrs["pending_updates"] == 1
    assert attrs["pending_system_updates"] == 1
    assert attrs["pending_updates_total"] == 2


def test_container_count_pending_updates_includes_tier_2_only_containers():
    """Regression test, same class of bug as the system-container case
    above but a different specific cause: an earlier version of this fix
    counted only pending_update_container_ids (Tier 1), reasoning that
    this sensor platform had no access to update_coordinator (Tier 2) at
    all. True, but the wrong thing to stop at — Tier 2, when configured,
    can flag a container's update before Tier 1's own cache catches up,
    and each container's own update entity (update.py's latest_version)
    already reflects that Tier-1-or-Tier-2 check. A Tier-1-only count
    here could still disagree with what that container's own entity (and
    this environment's Updates card rows) shows. This container is
    absent from pending_update_container_ids entirely — only Tier 2 (via
    update_coordinator) flags it — and must still be counted."""
    sc = _sensor_classes()
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": [{**CONTAINER, "id": "tier2-only"}],
            "stacks": [STACK],
            "container_stats": {},
            "pending_update_container_ids": set(),
        }
    )
    update_coord = MagicMock()
    update_coord.data = {"environments": {ENV_ID: {"tier2-only": {"hasUpdate": True}}}}
    sensor = sc["DockhandEnvContainerCountSensor"](
        coord, update_coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    assert sensor.extra_state_attributes["pending_updates"] == 1


def test_container_count_pending_updates_none_when_update_coordinator_absent():
    """update_coordinator is optional (Tier 2 is opt-in) — must not crash
    or misbehave when it's None, same as _container_has_pending_update's
    own contract for its update_env_data parameter."""
    sc = _sensor_classes()
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": [CONTAINER],
            "stacks": [STACK],
            "container_stats": {},
            "pending_update_container_ids": set(),
        }
    )
    sensor = sc["DockhandEnvContainerCountSensor"](
        coord, None, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )
    assert sensor.extra_state_attributes["pending_updates"] == 0


def test_stacks_value(env_sensors):
    assert env_sensors["stacks"].native_value == 2


def test_images_count(env_sensors):
    assert env_sensors["images"].native_value == 5


def test_images_attribute_raw_bytes(env_sensors):
    attrs = env_sensors["images"].extra_state_attributes
    assert attrs["total_size_bytes"] == 2147483648
    assert "total_size_mib" not in attrs


def test_volumes_count(env_sensors):
    assert env_sensors["volumes"].native_value == 2


def test_volumes_attribute_raw_bytes(env_sensors):
    attrs = env_sensors["volumes"].extra_state_attributes
    assert "total_size_bytes" in attrs
    assert "total_size_mib" not in attrs


def test_networks_count(env_sensors):
    assert env_sensors["networks"].native_value == 3


def test_disk_usage_total_bytes(env_sensors):
    # images.totalSize + volumes.totalSize + containersSize + buildCacheSize
    assert (
        env_sensors["disk_usage"].native_value
        == 2147483648 + 1073741824 + 524288000 + 104857600
    )


def test_disk_usage_attributes(env_sensors):
    attrs = env_sensors["disk_usage"].extra_state_attributes
    assert attrs == {
        "images_size_bytes": 2147483648,
        "volumes_size_bytes": 1073741824,
        "containers_size_bytes": 524288000,
        "build_cache_size_bytes": 104857600,
    }


def test_disk_usage_disabled_by_default(env_sensors):
    assert not env_sensors["disk_usage"]._attr_entity_registry_enabled_default


def test_connection_type_value(env_sensors):
    assert env_sensors["connection_type"].native_value == "socket"


def test_connection_type_enabled_by_default(env_sensors):
    assert env_sensors["connection_type"]._attr_entity_registry_enabled_default is True


def test_env_sensor_unique_ids_are_unique(env_sensors):
    uids = [s._attr_unique_id for s in env_sensors.values()]
    assert len(uids) == len(set(uids))


def test_env_sensor_entity_category_diagnostic(env_sensors):
    for key in [
        "containers",
        "stacks",
        "images",
        "volumes",
        "networks",
        "disk_usage",
        "connection_type",
    ]:
        assert env_sensors[key]._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_env_sensor_has_entity_name_true(env_sensors):
    for _name, sensor in env_sensors.items():
        assert sensor._attr_has_entity_name, (
            f"{type(sensor).__name__} must have _attr_has_entity_name=True"
        )


# ===========================================================================
# Environment activity sensor
# ===========================================================================


def _make_activity(events=None, recent_events=None):
    from custom_components.dockhand.sensor import DockhandEnvActivityEventsSensor

    coord = _fast_coord(
        env_data={
            "stats": {**STATS, "events": events or {"total": 42, "today": 7}},
            "containers": [],
            "stacks": [],
        }
    )
    slow_coord = _slow_coord(
        env_data={"recent_events": recent_events if recent_events is not None else []}
    )
    return DockhandEnvActivityEventsSensor(
        coord, slow_coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
    )


def test_activity_total_event_count():
    assert _make_activity().native_value == 42


def test_activity_today_attribute():
    assert _make_activity().extra_state_attributes["today"] == 7


def test_activity_disabled_by_default():
    assert not _make_activity()._attr_entity_registry_enabled_default


def test_activity_recent_events_attribute():
    events = [
        {"containerName": "web", "action": "start", "timestamp": "2026-07-13T00:00:00Z"}
    ]
    attrs = _make_activity(recent_events=events).extra_state_attributes
    assert attrs["recent_events"] == [
        {
            "container_name": "web",
            "action": "start",
            "timestamp": "2026-07-13T00:00:00Z",
        }
    ]


def test_activity_recent_events_empty_when_not_collecting():
    assert _make_activity().extra_state_attributes["recent_events"] == []


def test_activity_state_class_is_measurement():
    from homeassistant.components.sensor import SensorStateClass

    assert _make_activity()._attr_state_class == SensorStateClass.MEASUREMENT


# ===========================================================================
# Hawser version sensor
# ===========================================================================


def _make_hawser(host_environment=None):
    from custom_components.dockhand.sensor import DockhandEnvHawserVersionSensor

    coord = _slow_coord(
        env_data={
            "host": {"environment": host_environment}
            if host_environment is not None
            else {},
            "images": [],
            "networks": [],
            "volumes": [],
        }
    )
    return DockhandEnvHawserVersionSensor(coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL)


def test_hawser_version_string():
    sensor = _make_hawser(host_environment={"hawserVersion": "1.4.2"})
    assert sensor.native_value == "1.4.2"


def test_hawser_none_when_absent():
    assert _make_hawser().native_value is None


def test_hawser_disabled_by_default():
    assert not _make_hawser()._attr_entity_registry_enabled_default


def test_hawser_has_no_attributes():
    """agent_name/agent_id/last_seen were dropped along with the
    /api/environments call entirely — /api/host doesn't have them (it
    only forwards hawserVersion from its internal agent-info call), and
    the only other source is a side-effecting manual-action endpoint we
    shouldn't poll. Rather than gate them, they're just gone — a low-use
    edge-mode-only detail wasn't worth keeping a whole extra API call
    around for (see coordinator.py for the /api/environments removal
    rationale: it also returns tlsKey/hawserToken fully decrypted with no
    redaction on Dockhand's side)."""
    sensor = _make_hawser(host_environment={"hawserVersion": "1.4.2"})
    assert sensor.extra_state_attributes is None


# ===========================================================================
# Host info sensors (platform/arch/cpu count/docker version/last boot)
# ===========================================================================


def _make_host_sensor(cls_name, host=None):
    from custom_components.dockhand import sensor as sensor_module

    cls = getattr(sensor_module, cls_name)
    coord = _slow_coord(
        env_data={
            "host": host if host is not None else {},
            "images": [],
            "networks": [],
            "volumes": [],
        }
    )
    return cls(coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL)


def test_host_platform_sensor():
    sensor = _make_host_sensor("DockhandEnvPlatformSensor", {"platform": "linux"})
    assert sensor.native_value == "linux"


def test_host_platform_sensor_none_when_absent():
    assert _make_host_sensor("DockhandEnvPlatformSensor").native_value is None


def test_host_platform_sensor_architecture_attribute():
    sensor = _make_host_sensor(
        "DockhandEnvPlatformSensor", {"platform": "linux", "arch": "x64"}
    )
    assert sensor.extra_state_attributes == {"architecture": "x64"}


def test_host_platform_sensor_architecture_attribute_absent_when_missing():
    sensor = _make_host_sensor("DockhandEnvPlatformSensor", {"platform": "linux"})
    assert sensor.extra_state_attributes == {}


def test_host_docker_version_sensor():
    sensor = _make_host_sensor(
        "DockhandEnvDockerVersionSensor", {"dockerVersion": "27.3.1"}
    )
    assert sensor.native_value == "27.3.1"


def test_host_docker_version_sensor_treats_unknown_string_as_none():
    """Dockhand reports the literal string "unknown" for some connection
    types it can't determine this for — treat that as absent, not as a
    real version string."""
    sensor = _make_host_sensor(
        "DockhandEnvDockerVersionSensor", {"dockerVersion": "unknown"}
    )
    assert sensor.native_value is None


def test_host_last_boot_sensor_computed_from_uptime():
    import homeassistant.util.dt as dt_util

    sensor = _make_host_sensor("DockhandEnvLastBootSensor", {"uptime": 3600})
    result = sensor.native_value
    assert result is not None
    # Roughly one hour before "now" — generous tolerance since the test
    # itself takes nonzero time to run.
    expected = dt_util.utcnow() - __import__("datetime").timedelta(seconds=3600)
    assert abs((result - expected).total_seconds()) < 5


def test_host_last_boot_sensor_none_when_uptime_absent():
    assert _make_host_sensor("DockhandEnvLastBootSensor").native_value is None


def test_host_last_boot_sensor_none_when_uptime_negative():
    sensor = _make_host_sensor("DockhandEnvLastBootSensor", {"uptime": -1})
    assert sensor.native_value is None


def test_host_sensors_disabled_by_default():
    for cls_name in [
        "DockhandEnvPlatformSensor",
        "DockhandEnvDockerVersionSensor",
        "DockhandEnvLastBootSensor",
    ]:
        sensor = _make_host_sensor(cls_name)
        assert not sensor._attr_entity_registry_enabled_default, cls_name


# ===========================================================================
# Container sensors
# ===========================================================================


@pytest.fixture
def container_sensors():
    sc = _sensor_classes()
    coord = _fast_coord()
    return {
        "state": sc["DockhandContainerStateSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        ),
        "health": sc["DockhandContainerHealthSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        ),
    }


def test_container_state_value(container_sensors):
    assert container_sensors["state"].native_value == "running"


def test_container_state_image_attribute(container_sensors):
    assert container_sensors["state"].extra_state_attributes["image"] == "nginx:latest"


def test_container_health_value(container_sensors):
    assert container_sensors["health"].native_value == "healthy"


def test_container_health_enabled_by_default(container_sensors):
    """Health sensor is enabled by default; only created when a healthcheck exists."""
    assert container_sensors["health"].entity_registry_enabled_default


def test_container_state_none_when_container_gone():
    coord = MagicMock()
    coord.data = {
        "environments": {
            ENV_ID: {
                "stats": STATS,
                "containers": [],
                "stacks": [],
                "container_stats": {},
            }
        }
    }
    sc = _sensor_classes()
    state = sc["DockhandContainerStateSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
    )
    assert state.native_value is None


def test_container_has_entity_name_true(container_sensors):
    for s in container_sensors.values():
        assert s._attr_has_entity_name


def test_container_unique_ids_include_container_name(container_sensors):
    name = CONTAINER["name"]
    assert name in container_sensors["state"]._attr_unique_id
    assert name in container_sensors["health"]._attr_unique_id


def test_container_unique_ids_differ(container_sensors):
    assert (
        container_sensors["state"]._attr_unique_id
        != container_sensors["health"]._attr_unique_id
    )


# ===========================================================================
# Container stats sensors
# ===========================================================================

CONTAINER_STATS = {
    "name": "nginx",
    "cpuPercent": 12.34,
    "memoryUsage": 157286400,
    "memoryRaw": 178257920,
    "memoryCache": 20971520,
    "memoryLimit": 16764731392,
    "memoryPercent": 0.94,
    "networkRx": 83886080,
    "networkTx": 104857600,
    "blockRead": 52428800,
    "blockWrite": 31457280,
}


def _stats_coord(stats=None, running=True):
    coord = MagicMock()
    coord.data = {
        "environments": {
            ENV_ID: {
                "stats": STATS,
                "containers": [CONTAINER] if running else [],
                "stacks": [],
                "container_stats": {"nginx": stats or CONTAINER_STATS}
                if running
                else {},
            }
        }
    }
    coord.last_update_success = True
    coord.async_refresh = AsyncMock()
    return coord


@pytest.fixture
def stats_sensors():
    sc = _sensor_classes()
    coord = _stats_coord()
    args = (coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER, True)
    sensors = {
        "cpu": sc["DockhandContainerCpuSensor"](*args),
        "mem_usage": sc["DockhandContainerMemoryUsageSensor"](*args),
        "mem_pct": sc["DockhandContainerMemoryPercentSensor"](*args),
        "mem_limit": sc["DockhandContainerMemoryLimitSensor"](*args),
        "net_rx": sc["DockhandContainerNetworkRxSensor"](*args),
        "net_tx": sc["DockhandContainerNetworkTxSensor"](*args),
        "blk_read": sc["DockhandContainerBlockReadSensor"](*args),
        "blk_write": sc["DockhandContainerBlockWriteSensor"](*args),
    }
    sensors["all"] = list(sensors.values())
    return sensors


def test_stats_cpu_value(stats_sensors):
    assert stats_sensors["cpu"].native_value == 12.34


def test_stats_memory_usage_value_raw_bytes(stats_sensors):
    assert stats_sensors["mem_usage"].native_value == 157_286_400


def test_stats_memory_percent_value(stats_sensors):
    assert stats_sensors["mem_pct"].native_value == 0.94


def test_stats_memory_limit_value_raw_bytes(stats_sensors):
    assert stats_sensors["mem_limit"].native_value == 16_764_731_392


def test_stats_network_rx_value_raw_bytes(stats_sensors):
    assert stats_sensors["net_rx"].native_value == 83_886_080


def test_stats_network_tx_value_raw_bytes(stats_sensors):
    assert stats_sensors["net_tx"].native_value == 104_857_600


def test_stats_block_read_value_raw_bytes(stats_sensors):
    assert stats_sensors["blk_read"].native_value == 52_428_800


def test_stats_block_write_value_raw_bytes(stats_sensors):
    assert stats_sensors["blk_write"].native_value == 31_457_280


def test_stats_memory_usage_cache_attribute(stats_sensors):
    attrs = stats_sensors["mem_usage"].extra_state_attributes
    assert "memory_cache_bytes" in attrs
    assert attrs["memory_cache_bytes"] == 20_971_520


def test_stats_available_when_running(stats_sensors):
    for s in stats_sensors["all"]:
        assert s.available, (
            f"{type(s).__name__} should be available when the container has stats"
        )


def test_stats_all_sensors_none_when_container_stopped():
    coord = _stats_coord(running=False)
    sc = _sensor_classes()
    args = (coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER, True)
    sensors = [
        sc["DockhandContainerCpuSensor"](*args),
        sc["DockhandContainerMemoryUsageSensor"](*args),
        sc["DockhandContainerMemoryPercentSensor"](*args),
        sc["DockhandContainerMemoryLimitSensor"](*args),
        sc["DockhandContainerNetworkRxSensor"](*args),
        sc["DockhandContainerNetworkTxSensor"](*args),
        sc["DockhandContainerBlockReadSensor"](*args),
        sc["DockhandContainerBlockWriteSensor"](*args),
    ]
    for s in sensors:
        assert s.native_value is None, f"{type(s).__name__} should be None when stopped"
        assert not s.available, (
            f"{type(s).__name__} should report unavailable (not just None), when stopped"
        )


def test_stats_enabled_default_follows_config_option(stats_sensors):
    """Enabled-by-default now follows the "Enable container stats" option
    (passed in at construction) rather than being hardcoded False —
    stats_sensors fixture constructs with stats_enabled=True."""
    for s in stats_sensors["all"]:
        assert s._attr_entity_registry_enabled_default, (
            f"{type(s).__name__} should follow the stats_enabled flag it was constructed with"
        )


def test_stats_disabled_by_default_when_option_off():
    sc = _sensor_classes()
    coord = _stats_coord()
    sensor = sc["DockhandContainerCpuSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER, False
    )
    assert not sensor._attr_entity_registry_enabled_default


def test_stats_all_diagnostic_category(stats_sensors):
    for s in stats_sensors["all"]:
        assert s._attr_entity_category == EntityCategory.DIAGNOSTIC, (
            f"{type(s).__name__} should be DIAGNOSTIC"
        )


def test_stats_all_have_entity_name(stats_sensors):
    for s in stats_sensors["all"]:
        assert s._attr_has_entity_name


def test_stats_unique_ids_all_distinct(stats_sensors):
    uids = [s._attr_unique_id for s in stats_sensors["all"]]
    assert len(uids) == len(set(uids)), "All unique_ids must be distinct"


def test_stats_unique_ids_contain_container_name(stats_sensors):
    for s in stats_sensors["all"]:
        assert CONTAINER["name"] in s._attr_unique_id, (
            f"{type(s).__name__} unique_id missing container name"
        )


# ===========================================================================
# Stack sensors
# ===========================================================================


@pytest.fixture
def stack_sensors():
    sc = _sensor_classes()
    coord = _fast_coord()
    return {
        "status": sc["DockhandStackStatusSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
        ),
        "count": sc["DockhandStackContainerCountSensor"](
            coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
        ),
    }


def test_stack_status_value(stack_sensors):
    assert stack_sensors["status"].native_value == "running"


def test_stack_container_count(stack_sensors):
    assert stack_sensors["count"].native_value == 3


def test_stack_container_count_names_attribute():
    """The container count entity is the one the card links to for
    more-info, so this is where the container list is most useful to
    see at a glance — added alongside the same attribute on the status
    entity, not instead of it."""
    sc = _sensor_classes()
    stack = {"name": "myapp", "status": "running", "containers": ["abc123", "def456"]}
    containers = [
        {"id": "abc123", "name": "web", "state": "running"},
        {"id": "def456", "name": "worker", "state": "running"},
    ]
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": containers,
            "stacks": [stack],
            "container_stats": {},
        }
    )
    sensor = sc["DockhandStackContainerCountSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, stack
    )
    assert sensor.extra_state_attributes == {"container_names": ["web", "worker"]}


def test_stack_status_container_count_attribute(stack_sensors):
    assert "container_count" in stack_sensors["status"].extra_state_attributes


def test_stack_status_container_names_resolved_from_ids():
    """Dockhand's own stack.containers field is a list of raw container
    IDs (verified against Dockhand's source, src/lib/server/stacks.ts),
    not names — this attribute must resolve them against the
    environment's actual container list, not just echo the IDs back."""
    sc = _sensor_classes()
    stack = {"name": "myapp", "status": "running", "containers": ["abc123", "def456"]}
    containers = [
        {"id": "abc123", "name": "web", "state": "running"},
        {"id": "def456", "name": "worker", "state": "running"},
    ]
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": containers,
            "stacks": [stack],
            "container_stats": {},
        }
    )
    sensor = sc["DockhandStackStatusSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, stack
    )
    assert sensor.extra_state_attributes["container_names"] == ["web", "worker"]


def test_stack_status_container_names_sorted_alphabetically():
    """Real, reported usability issue: an unsorted list is hard to skim
    for a stack with many containers. Deliberately feeds IDs in an order
    that would NOT already happen to look sorted, to actually exercise
    the sort rather than coincidentally pass."""
    sc = _sensor_classes()
    stack = {
        "name": "myapp",
        "status": "running",
        "containers": ["id-zebra", "id-alpha", "id-mike"],
    }
    containers = [
        {"id": "id-zebra", "name": "zebra", "state": "running"},
        {"id": "id-alpha", "name": "alpha", "state": "running"},
        {"id": "id-mike", "name": "Mike", "state": "running"},
    ]
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": containers,
            "stacks": [stack],
            "container_stats": {},
        }
    )
    sensor = sc["DockhandStackStatusSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, stack
    )
    # Case-insensitive: "Mike" sorts between "alpha" and "zebra", not
    # before both of them due to capitalization.
    assert sensor.extra_state_attributes["container_names"] == [
        "alpha",
        "Mike",
        "zebra",
    ]


def test_stack_status_container_names_falls_back_to_id_when_unresolved():
    """A container ID that isn't in the environment's current container
    list (e.g. removed since the stack's own list last refreshed) should
    still show up as its raw ID, not silently vanish from the list."""
    sc = _sensor_classes()
    stack = {"name": "myapp", "status": "running", "containers": ["abc123", "gone999"]}
    containers = [{"id": "abc123", "name": "web", "state": "running"}]
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": containers,
            "stacks": [stack],
            "container_stats": {},
        }
    )
    sensor = sc["DockhandStackStatusSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, stack
    )
    assert sensor.extra_state_attributes["container_names"] == ["gone999", "web"]


def test_stack_status_model_untracked_when_no_source_record(stack_sensors):
    """STACK fixture has no sourceType — Dockhand has no DB record for it
    at all (e.g. a plain compose stack it only ever saw via running
    containers). Confirmed from Dockhand's own frontend source that it
    treats this exact case as sourceType 'external' by default (not
    "unknown"), displayed there as "Untracked" — we match that instead of
    falling back to a generic, uninformative "Stack"."""
    assert stack_sensors["status"].device_info["model"] == "Untracked Stack"


def test_stack_status_model_reflects_git_source_type():
    sc = _sensor_classes()
    coord = _fast_coord(
        {
            "stats": STATS,
            "containers": [CONTAINER],
            "stacks": [{**STACK, "sourceType": "git"}],
            "container_stats": {},
        }
    )
    sensor = sc["DockhandStackStatusSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
    )
    assert sensor.device_info["model"] == "Git Stack"


def test_stack_status_model_reflects_internal_source_type():
    sc = _sensor_classes()
    coord = _fast_coord(
        {
            "stats": STATS,
            "containers": [CONTAINER],
            "stacks": [{**STACK, "sourceType": "internal"}],
            "container_stats": {},
        }
    )
    sensor = sc["DockhandStackStatusSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
    )
    assert sensor.device_info["model"] == "Internal Stack"


def test_stack_unique_ids_differ(stack_sensors):
    assert (
        stack_sensors["status"]._attr_unique_id
        != stack_sensors["count"]._attr_unique_id
    )


# ===========================================================================
# Image sensors
# ===========================================================================


def _make_image(image=None):
    sc = _sensor_classes()
    return sc["DockhandImageSensor"](
        _slow_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, image or IMAGE
    )


def test_image_native_value_is_tag():
    assert _make_image().native_value == "latest"


def test_image_name_is_repo_only():
    sensor = _make_image()
    assert sensor.name == "nginx"
    assert ":" not in sensor.name


def test_image_has_entity_name_true():
    assert _make_image()._attr_has_entity_name


def test_image_name_recomputes_live_when_tag_is_lost():
    """Regression test: name used to be fixed at construction (_attr_name
    set once in __init__). Since this entity object is reused
    indefinitely for the same image hash (see the known_image_ids dedup
    pattern in async_setup_entry), a static name meant that once this
    image's tag moved to a different (newly pulled) image — the normal
    outcome of a container upgrade — this entity would keep showing the
    old repo:tag forever, permanently occupying the entity_id slot the
    new image's entity actually deserved and forcing it into an
    auto-suffixed "_2" id that never self-heals. name is now a live
    property so it correctly falls back to the short hash the moment
    Dockhand's own data shows this image as untagged, freeing that slot
    naturally within a poll cycle or two."""
    coord = _slow_coord()
    sc = _sensor_classes()
    sensor = sc["DockhandImageSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, IMAGE
    )
    assert sensor.name == "nginx"

    # Simulate the next poll: Dockhand's data now shows this exact image
    # (same id) as untagged — a new image has taken over "nginx:latest".
    untagged_image = {**IMAGE, "repoTags": []}
    coord.data["environments"][ENV_ID]["images"] = [untagged_image]
    assert sensor.name == "deadbeef1234"


def test_image_name_falls_back_when_image_gone_entirely():
    """If the image disappears from the environment entirely (e.g.
    pruned) while this entity object still exists momentarily, name
    falls back to whatever it was last known as, rather than crashing
    or going blank."""
    coord = _slow_coord()
    sc = _sensor_classes()
    sensor = sc["DockhandImageSensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, IMAGE
    )
    coord.data["environments"][ENV_ID]["images"] = []
    assert sensor.name == "nginx"


def test_image_size_bytes_attribute():
    attrs = _make_image().extra_state_attributes
    assert attrs["size_bytes"] == 104857600
    assert "size_mib" not in attrs


def test_image_tags_attribute():
    assert _make_image().extra_state_attributes["tags"] == ["nginx:latest"]


def test_image_containers_using_attribute():
    assert _make_image().extra_state_attributes["containers_using"] == 2


def test_image_device_is_images_group():
    idents = _make_image().device_info.get("identifiers", set())
    assert (DOMAIN, f"env_{ENV_ID}_Images") in idents


# ===========================================================================
# Network sensors
# ===========================================================================


def _make_network(coord=None):
    sc = _sensor_classes()
    return sc["DockhandNetworkSensor"](
        coord or _slow_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, NETWORK
    )


def test_network_container_count():
    assert _make_network().native_value == 1


def test_network_attributes():
    attrs = _make_network().extra_state_attributes
    assert attrs["driver"] == "bridge"
    assert attrs["subnet"] == "172.17.0.0/16"
    assert "nginx" in attrs["connected_containers"]


def test_network_none_when_not_found():
    coord = _slow_coord(
        env_data={"env": {}, "images": [], "networks": [], "volumes": []}
    )
    assert _make_network(coord).native_value is None


def test_network_unique_id_includes_env_id():
    assert str(ENV_ID) in _make_network()._attr_unique_id


def test_network_name_is_network_name():
    sensor = _make_network()
    assert sensor._attr_name == NETWORK["name"]
    assert sensor._attr_has_entity_name


def test_network_device_is_networks_group():
    idents = _make_network().device_info.get("identifiers", set())
    assert (DOMAIN, f"env_{ENV_ID}_Networks") in idents
    assert (DOMAIN, f"network_{NETWORK['id']}") not in idents


# ===========================================================================
# Volume sensors
# ===========================================================================


def _make_volume(volume=None, coord=None):
    sc = _sensor_classes()
    return sc["DockhandVolumeSensor"](
        coord or _slow_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, volume or VOLUME
    )


def test_volume_container_count_when_used():
    assert _make_volume().native_value == 1


def test_volume_container_count_zero_when_unused():
    coord = _slow_coord(
        env_data={"env": {}, "images": [], "networks": [], "volumes": [VOLUME_UNUSED]}
    )
    assert _make_volume(VOLUME_UNUSED, coord).native_value == 0


def test_volume_in_use_attribute():
    assert _make_volume().extra_state_attributes["in_use"]


def test_volume_containers_attribute():
    assert _make_volume().extra_state_attributes["containers"] == ["container_abc123"]


def test_volume_driver_scope_mountpoint_created():
    attrs = _make_volume().extra_state_attributes
    assert attrs["driver"] == "local"
    assert attrs["scope"] == "local"
    assert "mountpoint" in attrs
    assert "created" in attrs


def test_volume_none_when_not_found():
    coord = _slow_coord(
        env_data={"env": {}, "images": [], "networks": [], "volumes": []}
    )
    assert _make_volume(coord=coord).native_value is None


def test_volume_name_is_volume_name():
    sensor = _make_volume()
    assert sensor._attr_name == VOLUME["name"]
    assert sensor._attr_has_entity_name


def test_volume_device_is_volumes_group():
    idents = _make_volume().device_info.get("identifiers", set())
    assert (DOMAIN, f"env_{ENV_ID}_Volumes") in idents


# ===========================================================================
# Schedule sensors
# ===========================================================================


def _make_next_run(sched=None):
    sc = _sensor_classes()
    s = sched or SCHEDULE
    return sc["DockhandScheduleNextRunSensor"](
        _slow_coord(schedules=[s]), ENTRY_ID, s, BASE_URL
    )


def _make_last_status(sched=None):
    sc = _sensor_classes()
    s = sched or SCHEDULE
    return sc["DockhandScheduleLastStatusSensor"](
        _slow_coord(schedules=[s]), ENTRY_ID, s, BASE_URL
    )


def test_schedule_next_run_returns_datetime():
    assert _make_next_run().native_value is not None


def test_schedule_next_run_none_when_schedule_gone():
    sc = _sensor_classes()
    sensor = sc["DockhandScheduleNextRunSensor"](
        _slow_coord(schedules=[]), ENTRY_ID, SCHEDULE, BASE_URL
    )
    assert sensor.native_value is None


def test_schedule_next_run_attributes():
    attrs = _make_next_run().extra_state_attributes
    assert attrs["cron_expression"] == "0 2 * * *"
    assert attrs["enabled"]
    assert attrs["schedule_type"] == "system"


def test_schedule_last_status_success():
    assert _make_last_status().native_value == "success"


def test_schedule_last_status_failed():
    assert _make_last_status(SCHEDULE_FAILED).native_value == "failed"


def test_schedule_last_status_attributes_on_failure():
    attrs = _make_last_status(SCHEDULE_FAILED).extra_state_attributes
    assert attrs["error_message"] == "Connection timeout"
    assert "triggered_at" in attrs
    assert "duration_ms" in attrs


def test_schedule_last_status_none_when_no_execution():
    sched = {**SCHEDULE, "lastExecution": None}
    sc = _sensor_classes()
    sensor = sc["DockhandScheduleLastStatusSensor"](
        _slow_coord(schedules=[sched]), ENTRY_ID, sched, BASE_URL
    )
    assert sensor.native_value is None


def test_schedule_both_sensors_share_device():
    nr = _make_next_run()
    ls = _make_last_status()
    assert nr.device_info.get("identifiers") == ls.device_info.get("identifiers")


def test_schedule_device_is_child_of_hub():
    via = _make_next_run().device_info.get("via_device")
    assert via == ("dockhand", "schedules_hub")


def test_schedule_last_status_is_diagnostic():
    assert _make_last_status()._attr_entity_category == EntityCategory.DIAGNOSTIC


# ===========================================================================
# Binary sensors
# ===========================================================================


def _make_binary(cls_name, stats_override=None):
    bs = _bs_classes()
    coord = _fast_coord(
        {
            "stats": {**STATS, **(stats_override or {})},
            "containers": [],
            "stacks": [],
        }
    )
    if cls_name == "DockhandEnvOnlineSensor":
        return bs[cls_name](coord, _slow_coord(), ENTRY_ID, ENV_ID, BASE_URL)
    return bs[cls_name](coord, ENTRY_ID, ENV_ID, BASE_URL)


def test_binary_online_is_on():
    assert _make_binary("DockhandEnvOnlineSensor").is_on


def test_binary_online_carries_name_and_connection_attributes():
    from custom_components.dockhand.binary_sensor import DockhandEnvOnlineSensor

    fast_coord = _fast_coord(
        {"stats": {**STATS, "name": "prod"}, "containers": [], "stacks": []}
    )
    slow_coord = _slow_coord(
        env_data={"env_meta": {"connectionHost": "192.168.1.5", "connectionPort": 2375}}
    )
    sensor = DockhandEnvOnlineSensor(fast_coord, slow_coord, ENTRY_ID, ENV_ID, BASE_URL)
    assert sensor.extra_state_attributes == {
        "name": "prod",
        "connection_host": "192.168.1.5",
        "connection_port": 2375,
        "labels": [],
    }


def test_binary_online_attributes_none_when_env_meta_absent():
    from custom_components.dockhand.binary_sensor import DockhandEnvOnlineSensor

    fast_coord = _fast_coord(
        {"stats": {**STATS, "name": "prod"}, "containers": [], "stacks": []}
    )
    slow_coord = _slow_coord(env_data={})
    sensor = DockhandEnvOnlineSensor(fast_coord, slow_coord, ENTRY_ID, ENV_ID, BASE_URL)
    assert sensor.extra_state_attributes == {
        "name": "prod",
        "connection_host": None,
        "connection_port": None,
        "labels": [],
    }


def test_binary_online_labels_attribute():
    from custom_components.dockhand.binary_sensor import DockhandEnvOnlineSensor

    fast_coord = _fast_coord(
        {
            "stats": {**STATS, "labels": ["prod", "critical"]},
            "containers": [],
            "stacks": [],
        }
    )
    sensor = DockhandEnvOnlineSensor(
        fast_coord, _slow_coord(), ENTRY_ID, ENV_ID, BASE_URL
    )
    assert sensor.extra_state_attributes["labels"] == ["prod", "critical"]


# ---------------------------------------------------------------------------
# Stack updates-available binary sensor (feature-detected, Dockhand 1.0.37+)
# ---------------------------------------------------------------------------


def _make_stack_updates_sensor(stack):
    bs = _bs_classes()
    coord = _fast_coord({"stats": STATS, "containers": [], "stacks": [stack]})
    return bs["DockhandStackUpdatesAvailableBinarySensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, stack
    )


def test_stack_updates_available_true():
    stack = {**STACK, "updatesAvailable": True, "updateCount": 2}
    sensor = _make_stack_updates_sensor(stack)
    assert sensor.is_on is True
    assert sensor.extra_state_attributes == {
        "update_count": 2,
        "pending_container_names": [],
    }


def test_stack_updates_available_false():
    stack = {**STACK, "updatesAvailable": False, "updateCount": 0}
    sensor = _make_stack_updates_sensor(stack)
    assert sensor.is_on is False
    assert sensor.extra_state_attributes == {
        "update_count": 0,
        "pending_container_names": [],
    }


def test_stack_updates_available_has_no_device_class():
    """Regression guard: PROBLEM made a routine available update look
    like something was wrong (a real, reported issue). UPDATE was
    considered and rejected too — HA's own developer docs discourage it
    in favor of a real update-domain entity, a bigger change than this."""
    stack = {**STACK, "updatesAvailable": True, "updateCount": 1}
    sensor = _make_stack_updates_sensor(stack)
    assert sensor.device_class is None


def test_stack_updates_available_pending_container_names_resolved():
    """Dockhand's stack object only gives the container ID list and the
    aggregate count, never which containers specifically — resolved here
    by cross-referencing the environment's pending_update_container_ids
    against the stack's own container IDs, then to names."""
    bs = _bs_classes()
    stack = {
        "name": "myapp",
        "status": "running",
        "containers": ["abc123", "def456", "ghi789"],
        "updatesAvailable": True,
        "updateCount": 2,
    }
    coord = _fast_coord(
        env_data={
            "stats": STATS,
            "containers": [
                {"id": "abc123", "name": "web"},
                {"id": "def456", "name": "worker"},
                {"id": "ghi789", "name": "cache"},
            ],
            "stacks": [stack],
            "pending_update_container_ids": {"abc123", "ghi789"},
        }
    )
    sensor = bs["DockhandStackUpdatesAvailableBinarySensor"](
        coord, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, stack
    )
    assert sensor.extra_state_attributes["pending_container_names"] == ["cache", "web"]


def test_stack_updates_available_none_when_field_absent():
    """Feature detection: an older Dockhand version's stack data simply
    doesn't have this key at all — reads as None (unknown), not False,
    since those mean different things (we don't know vs. confirmed no
    updates)."""
    stack = dict(STACK)
    assert "updatesAvailable" not in stack
    sensor = _make_stack_updates_sensor(stack)
    assert sensor.is_on is None
    assert sensor.extra_state_attributes is None


def test_stack_updates_available_none_when_stack_gone():
    stack = {**STACK, "updatesAvailable": True, "updateCount": 1}
    sensor = _make_stack_updates_sensor(stack)
    # Simulate the stack disappearing from live data entirely.
    sensor.coordinator.data["environments"][ENV_ID]["stacks"] = []
    assert sensor.is_on is None


def test_stack_updates_available_device_reflects_source_type():
    stack = {**STACK, "updatesAvailable": True, "updateCount": 1, "sourceType": "git"}
    sensor = _make_stack_updates_sensor(stack)
    assert sensor.device_info["model"] == "Git Stack"


def test_binary_collect_activity_true():
    assert _make_binary("DockhandEnvCollectActivitySensor").is_on


def test_binary_collect_metrics_true():
    assert _make_binary("DockhandEnvCollectMetricsSensor").is_on


def test_binary_scanner_disabled():
    assert not _make_binary("DockhandEnvScannerEnabledSensor").is_on


def test_binary_update_checks_enabled():
    assert _make_binary("DockhandEnvUpdateCheckSensor").is_on


def test_binary_auto_update_disabled():
    assert not _make_binary("DockhandEnvAutoUpdateSensor").is_on


def test_binary_config_sensors_disabled_by_default():
    bs = _bs_classes()
    coord = _fast_coord()
    for cls_name in [
        "DockhandEnvCollectActivitySensor",
        "DockhandEnvCollectMetricsSensor",
        "DockhandEnvScannerEnabledSensor",
        "DockhandEnvUpdateCheckSensor",
        "DockhandEnvAutoUpdateSensor",
    ]:
        s = bs[cls_name](coord, ENTRY_ID, ENV_ID, BASE_URL)
        assert not s._attr_entity_registry_enabled_default, (
            f"{cls_name} should be disabled by default"
        )


def test_binary_online_sensor_enabled_by_default():
    bs = _bs_classes()
    s = bs["DockhandEnvOnlineSensor"](
        _fast_coord(), _slow_coord(), ENTRY_ID, ENV_ID, BASE_URL
    )
    assert s.entity_registry_enabled_default


# ===========================================================================
# Switches
# ===========================================================================


class TestSwitches:
    def _container_switch(self, container=None, coord=None):
        sw = _switch_classes()
        c = container or CONTAINER
        return sw["DockhandContainerRunningSwitch"](
            coord or _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, c
        )

    def _stack_switch(self, stack=None, coord=None):
        sw = _switch_classes()
        s = stack or STACK
        return sw["DockhandStackRunningSwitch"](
            coord or _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, s
        )

    def test_container_on_when_running(self):
        assert self._container_switch().is_on

    def test_container_off_when_stopped(self):
        stopped = {**CONTAINER, "state": "stopped"}
        coord = _fast_coord({"stats": STATS, "containers": [stopped], "stacks": []})
        assert not self._container_switch(stopped, coord).is_on

    def test_stack_on_when_running(self):
        assert self._stack_switch().is_on

    def test_stack_off_when_stopped(self):
        stopped = {**STACK, "status": "stopped"}
        coord = _fast_coord({"stats": STATS, "containers": [], "stacks": [stopped]})
        assert not self._stack_switch(stopped, coord).is_on

    async def test_container_turn_on_calls_start(self):
        switch = self._container_switch()
        switch._client = MagicMock()
        switch._client.async_start_container = AsyncMock()
        await switch.async_turn_on()
        switch._client.async_start_container.assert_called_once_with(
            ENV_ID, CONTAINER["id"]
        )

    async def test_container_turn_off_calls_stop(self):
        switch = self._container_switch()
        switch._client = MagicMock()
        switch._client.async_stop_container = AsyncMock()
        await switch.async_turn_off()
        switch._client.async_stop_container.assert_called_once_with(
            ENV_ID, CONTAINER["id"]
        )

    async def test_container_turn_on_raises_ha_error_on_api_failure(self):
        switch = self._container_switch()
        switch._client = MagicMock()
        switch._client.async_start_container = AsyncMock(
            side_effect=Exception("network error")
        )
        with pytest.raises(HomeAssistantError) as exc_info:
            await switch.async_turn_on()
        assert exc_info.value.translation_key == "action_failed"

    async def test_container_turn_off_raises_ha_error_on_api_failure(self):
        switch = self._container_switch()
        switch._client = MagicMock()
        switch._client.async_stop_container = AsyncMock(
            side_effect=Exception("timeout")
        )
        with pytest.raises(HomeAssistantError) as exc_info:
            await switch.async_turn_off()
        assert exc_info.value.translation_key == "action_failed"

    async def test_container_turn_on_raises_not_found_when_container_missing(self):
        coord = _fast_coord({"stats": STATS, "containers": [], "stacks": []})
        switch = self._container_switch(coord=coord)
        switch._client = MagicMock()
        with pytest.raises(HomeAssistantError) as exc_info:
            await switch.async_turn_on()
        assert exc_info.value.translation_key == "container_not_found"

    async def test_stack_turn_on_calls_start(self):
        switch = self._stack_switch()
        switch._client = MagicMock()
        switch._client.async_start_stack = AsyncMock()
        await switch.async_turn_on()
        switch._client.async_start_stack.assert_called_once_with(ENV_ID, STACK["name"])

    async def test_stack_turn_on_raises_ha_error_on_api_failure(self):
        switch = self._stack_switch()
        switch._client = MagicMock()
        switch._client.async_start_stack = AsyncMock(side_effect=Exception("down"))
        with pytest.raises(HomeAssistantError) as exc_info:
            await switch.async_turn_on()
        assert exc_info.value.translation_key == "action_failed"

    async def test_stack_turn_off_calls_stop(self):
        switch = self._stack_switch()
        switch._client = MagicMock()
        switch._client.async_stop_stack = AsyncMock()
        await switch.async_turn_off()
        switch._client.async_stop_stack.assert_called_once_with(ENV_ID, STACK["name"])

    async def test_stack_turn_off_raises_ha_error_on_api_failure(self):
        switch = self._stack_switch()
        switch._client = MagicMock()
        switch._client.async_stop_stack = AsyncMock(side_effect=Exception("down"))
        with pytest.raises(HomeAssistantError) as exc_info:
            await switch.async_turn_off()
        assert exc_info.value.translation_key == "action_failed"


# ===========================================================================
# Buttons
# ===========================================================================


class TestButtons:
    def _container_btn(self, coord=None):
        btn = _button_classes()
        return btn["DockhandContainerRestartButton"](
            coord or _fast_coord(),
            MagicMock(),
            ENTRY_ID,
            ENV_ID,
            ENV_NAME,
            BASE_URL,
            CONTAINER,
        )

    def _stack_btn(self):
        btn = _button_classes()
        return btn["DockhandStackRestartButton"](
            _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
        )

    async def test_container_restart_calls_api(self):
        b = self._container_btn()
        b._client = MagicMock()
        b._client.async_restart_container = AsyncMock()
        await b.async_press()
        b._client.async_restart_container.assert_called_once_with(
            ENV_ID, CONTAINER["id"]
        )

    async def test_stack_restart_calls_api(self):
        b = self._stack_btn()
        b._client = MagicMock()
        b._client.async_restart_stack = AsyncMock()
        await b.async_press()
        b._client.async_restart_stack.assert_called_once_with(ENV_ID, STACK["name"])

    async def test_container_restart_raises_ha_error_on_api_failure(self):
        b = self._container_btn()
        b._client = MagicMock()
        b._client.async_restart_container = AsyncMock(
            side_effect=Exception("connection refused")
        )
        with pytest.raises(HomeAssistantError) as exc_info:
            await b.async_press()
        assert exc_info.value.translation_key == "action_failed"

    async def test_container_restart_raises_not_found_when_container_missing(self):
        coord = _fast_coord({"stats": STATS, "containers": [], "stacks": []})
        b = self._container_btn(coord=coord)
        b._client = MagicMock()
        with pytest.raises(HomeAssistantError) as exc_info:
            await b.async_press()
        assert exc_info.value.translation_key == "container_not_found"

    async def test_stack_restart_raises_ha_error_on_api_failure(self):
        b = self._stack_btn()
        b._client = MagicMock()
        b._client.async_restart_stack = AsyncMock(side_effect=Exception("refused"))
        with pytest.raises(HomeAssistantError) as exc_info:
            await b.async_press()
        assert exc_info.value.translation_key == "action_failed"

    def test_restart_buttons_are_config_category(self):
        coord = _fast_coord()
        client = MagicMock()
        btn = _button_classes()
        c_btn = btn["DockhandContainerRestartButton"](
            coord, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        s_btn = btn["DockhandStackRestartButton"](
            coord, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        assert c_btn._attr_entity_category == EntityCategory.CONFIG
        assert s_btn._attr_entity_category == EntityCategory.CONFIG

    def test_restart_buttons_both_use_restart_translation_key(self):
        coord = _fast_coord()
        client = MagicMock()
        btn = _button_classes()
        c_btn = btn["DockhandContainerRestartButton"](
            coord, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        s_btn = btn["DockhandStackRestartButton"](
            coord, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        assert c_btn._attr_translation_key == "restart"
        assert s_btn._attr_translation_key == "restart"

    def test_container_device_name_includes_containers_segment(self):
        btn = _button_classes()
        b = btn["DockhandContainerRestartButton"](
            _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        assert "Containers" in b.device_info["name"]
        assert CONTAINER["name"] in b.device_info["name"]

    def test_stack_device_name_includes_stacks_segment(self):
        btn = _button_classes()
        b = btn["DockhandStackRestartButton"](
            _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        assert "Stacks" in b.device_info["name"]
        assert STACK["name"] in b.device_info["name"]

    def _stack_deploy_btn(self, coord=None):
        btn = _button_classes()
        return btn["DockhandStackDeployButton"](
            coord or _fast_coord(),
            MagicMock(),
            ENTRY_ID,
            ENV_ID,
            ENV_NAME,
            BASE_URL,
            STACK,
        )

    async def test_stack_deploy_calls_api_and_refreshes(self):
        b = self._stack_deploy_btn()
        b._client = MagicMock()
        b._client.async_deploy_stack = AsyncMock(return_value={"success": True})
        b.coordinator.async_refresh = AsyncMock()
        await b.async_press()
        b._client.async_deploy_stack.assert_called_once_with(ENV_ID, STACK["name"])
        b.coordinator.async_refresh.assert_called_once()

    async def test_stack_deploy_raises_not_found_when_stack_missing(self):
        coord = _fast_coord({"stats": STATS, "containers": [], "stacks": []})
        b = self._stack_deploy_btn(coord=coord)
        b._client = MagicMock()
        with pytest.raises(HomeAssistantError) as exc_info:
            await b.async_press()
        assert exc_info.value.translation_key == "action_failed"

    async def test_stack_deploy_raises_ha_error_on_client_exception(self):
        b = self._stack_deploy_btn()
        b._client = MagicMock()
        b._client.async_deploy_stack = AsyncMock(side_effect=Exception("refused"))
        with pytest.raises(HomeAssistantError) as exc_info:
            await b.async_press()
        assert exc_info.value.translation_key == "action_failed"

    async def test_stack_deploy_raises_on_success_false_response(self):
        """Dockhand returns HTTP 200 with {"success": false, "error": ...}
        for an expected failure mode (e.g. compose file location not
        configured) rather than an HTTP error — must be checked
        explicitly rather than relying on the client raising."""
        b = self._stack_deploy_btn()
        b._client = MagicMock()
        b._client.async_deploy_stack = AsyncMock(
            return_value={"success": False, "error": "compose file not configured"}
        )
        with pytest.raises(HomeAssistantError) as exc_info:
            await b.async_press()
        assert exc_info.value.translation_key == "action_failed"
        assert "compose file not configured" in str(
            exc_info.value.translation_placeholders["error"]
        )


# ===========================================================================
# Device naming and parentage
# ===========================================================================


def test_container_device_name_format():
    sc = _sensor_classes()
    sensor = sc["DockhandContainerStateSensor"](
        _fast_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
    )
    assert sensor.device_info["name"] == (
        f"{ENV_NAME} \u2013 Containers \u2013 {CONTAINER['name']}"
    )


def test_stack_device_name_format():
    sc = _sensor_classes()
    sensor = sc["DockhandStackStatusSensor"](
        _fast_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
    )
    assert sensor.device_info["name"] == (
        f"{ENV_NAME} \u2013 Stacks \u2013 {STACK['name']}"
    )


def test_container_switch_device_name_format():
    sw = _switch_classes()
    switch = sw["DockhandContainerRunningSwitch"](
        _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
    )
    assert "Containers" in switch.device_info["name"]
    assert CONTAINER["name"] in switch.device_info["name"]


def test_stack_switch_device_name_format():
    sw = _switch_classes()
    switch = sw["DockhandStackRunningSwitch"](
        _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
    )
    assert "Stacks" in switch.device_info["name"]
    assert STACK["name"] in switch.device_info["name"]


def test_container_button_device_name_format():
    btn = _button_classes()
    b = btn["DockhandContainerRestartButton"](
        _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
    )
    assert "Containers" in b.device_info["name"]


def test_stack_button_device_name_format():
    btn = _button_classes()
    b = btn["DockhandStackRestartButton"](
        _fast_coord(), MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, STACK
    )
    assert "Stacks" in b.device_info["name"]


def test_stack_device_helper_name_format():
    """_stack_device() must produce '{env} – Stacks – {name}' (regression guard)."""
    from custom_components.dockhand.helpers import _stack_device

    info = _stack_device(STACK["name"], ENV_ID, ENV_NAME, BASE_URL)
    assert info["name"] == f"{ENV_NAME} \u2013 Stacks \u2013 {STACK['name']}"


def test_network_entity_under_group_device():
    sc = _sensor_classes()
    sensor = sc["DockhandNetworkSensor"](
        _slow_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, NETWORK
    )
    idents = sensor.device_info.get("identifiers", set())
    assert (DOMAIN, f"env_{ENV_ID}_Networks") in idents
    assert (DOMAIN, f"network_{NETWORK['id']}") not in idents


def test_volume_entity_under_group_device():
    sc = _sensor_classes()
    sensor = sc["DockhandVolumeSensor"](
        _slow_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, VOLUME
    )
    idents = sensor.device_info.get("identifiers", set())
    assert (DOMAIN, f"env_{ENV_ID}_Volumes") in idents


def test_image_entity_under_group_device():
    sc = _sensor_classes()
    sensor = sc["DockhandImageSensor"](
        _slow_coord(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, IMAGE
    )
    idents = sensor.device_info.get("identifiers", set())
    assert (DOMAIN, f"env_{ENV_ID}_Images") in idents


# ===========================================================================
# helpers.py unit tests
# ===========================================================================


@pytest.fixture
def compose_project_fn():
    from custom_components.dockhand.helpers import _compose_project

    return _compose_project


def test_compose_project_returns_name(compose_project_fn):
    assert compose_project_fn(COMPOSE_CONTAINER) == "myapp"


def test_compose_project_none_for_freestanding(compose_project_fn):
    assert compose_project_fn(CONTAINER) is None


def test_compose_project_none_for_empty_labels(compose_project_fn):
    assert compose_project_fn({"labels": {}}) is None


def test_compose_project_none_for_none_labels(compose_project_fn):
    assert compose_project_fn({"labels": None}) is None


def test_compose_project_none_for_none_input(compose_project_fn):
    assert compose_project_fn(None) is None


def test_compose_project_none_for_empty_dict(compose_project_fn):
    assert compose_project_fn({}) is None


@pytest.fixture
def healthcheck_fn():
    from custom_components.dockhand.helpers import _container_has_healthcheck

    return _container_has_healthcheck


def test_healthcheck_true_for_healthy(healthcheck_fn):
    assert healthcheck_fn({"health": "healthy"})


def test_healthcheck_true_for_unhealthy(healthcheck_fn):
    assert healthcheck_fn({"health": "unhealthy"})


def test_healthcheck_true_for_starting(healthcheck_fn):
    assert healthcheck_fn({"health": "starting"})


def test_healthcheck_false_for_none_string(healthcheck_fn):
    assert not healthcheck_fn({"health": "none"})


def test_healthcheck_false_for_none_value(healthcheck_fn):
    assert not healthcheck_fn({"health": None})


def test_healthcheck_false_for_missing_key(healthcheck_fn):
    assert not healthcheck_fn({})


def test_healthcheck_false_for_unknown(healthcheck_fn):
    assert not healthcheck_fn({"health": "unknown"})


# ---------------------------------------------------------------------------
# Image entity tag-collision avoidance (async_setup_entry)
# ---------------------------------------------------------------------------


def _make_image_setup_entry(images):
    """Minimal entry mock exercising sensor.py's async_setup_entry with a
    given images list — everything else (containers/stacks/schedules)
    left empty so only the images path is meaningfully tested."""
    fast = MagicMock()
    fast.data = {
        "environments": {
            ENV_ID: {"stats": {"name": ENV_NAME}, "containers": [], "stacks": []}
        }
    }
    fast.async_add_listener = MagicMock(return_value=lambda: None)

    slow = MagicMock()
    slow.data = {
        "environments": {ENV_ID: {"images": images}},
        "schedules": [],
    }
    slow.async_add_listener = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"api_url": BASE_URL, "enable_images": True}
    entry.options = {}
    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.async_on_unload = MagicMock()
    return entry


async def test_setup_entry_defers_image_entities_when_tag_collides():
    """Two images momentarily reporting the same repo:tag (a container
    upgrade in progress — the old image hasn't been marked untagged in
    Dockhand's data yet) — neither gets an entity created this poll,
    avoiding the "_2" suffix collision entirely."""
    from custom_components.dockhand.sensor import async_setup_entry

    old_image = {**IMAGE, "id": "sha256:old111111111"}
    new_image = {**IMAGE, "id": "sha256:new222222222"}
    entry = _make_image_setup_entry([old_image, new_image])
    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)

    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    image_entities = [e for e in created if type(e).__name__ == "DockhandImageSensor"]
    assert image_entities == []


async def test_setup_entry_creates_image_entity_when_tag_unambiguous():
    from custom_components.dockhand.sensor import async_setup_entry

    entry = _make_image_setup_entry([IMAGE])
    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)

    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    image_entities = [e for e in created if type(e).__name__ == "DockhandImageSensor"]
    assert len(image_entities) == 1


async def test_setup_entry_creates_entity_once_collision_resolves():
    """Same scenario as the deferred case, but simulating the next poll:
    the old image has dropped out of the list (Dockhand's data caught up
    — it's now untagged and no longer shares the tag), so the new image
    can be created cleanly."""
    from custom_components.dockhand.sensor import async_setup_entry

    new_image = {**IMAGE, "id": "sha256:new222222222"}
    entry = _make_image_setup_entry([new_image])
    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)

    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    image_entities = [e for e in created if type(e).__name__ == "DockhandImageSensor"]
    assert len(image_entities) == 1
    assert image_entities[0].name == "nginx"


async def test_setup_entry_untagged_images_never_collide_with_each_other():
    """Two different untagged images each fall back to their own short
    hash as a display name — since hashes are unique, they never
    collide, regardless of how many untagged images exist at once."""
    from custom_components.dockhand.sensor import async_setup_entry

    untagged_1 = {**IMAGE, "id": "sha256:aaaa11111111", "repoTags": []}
    untagged_2 = {**IMAGE, "id": "sha256:bbbb22222222", "repoTags": []}
    entry = _make_image_setup_entry([untagged_1, untagged_2])
    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)

    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    image_entities = [e for e in created if type(e).__name__ == "DockhandImageSensor"]
    assert len(image_entities) == 2


# ---------------------------------------------------------------------------
# Bulk update button (env-level "Update all", conditionally present)
# ---------------------------------------------------------------------------


def _make_bulk_update_button(pending=None, containers=None, update_data=None):
    from custom_components.dockhand.button import DockhandEnvBulkUpdateButton

    coord = MagicMock()
    coord.data = {
        "environments": {
            ENV_ID: {
                "pending_update_container_ids": pending or set(),
                "containers": containers or [],
            }
        }
    }
    coord.async_refresh = AsyncMock()
    update_coord = None
    if update_data is not None:
        update_coord = MagicMock()
        update_coord.data = {"environments": {ENV_ID: update_data}}
    client = MagicMock()
    client.async_get_update_check_settings = AsyncMock(return_value={})
    return (
        DockhandEnvBulkUpdateButton(
            coord, update_coord, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL
        ),
        coord,
        client,
    )


def test_bulk_update_updatable_ids_excludes_system_containers():
    button, _, _ = _make_bulk_update_button(
        pending={"id-web", "id-dockhand"},
        containers=[
            {"id": "id-web", "name": "web", "systemContainer": None},
            {"id": "id-dockhand", "name": "dockhand", "systemContainer": "dockhand"},
        ],
    )
    assert button._updatable_container_ids() == ["id-web"]


def test_bulk_update_updatable_ids_includes_tier2_only_container():
    """A container Tier 1's cheap cache hasn't (yet) flagged, but Tier 2's
    precise digest check has, should still be included — Tier 2 alone is
    a valid reason for this button to exist and act."""
    button, _, _ = _make_bulk_update_button(
        pending=set(),
        containers=[{"id": "id-web", "name": "web", "systemContainer": None}],
        update_data={"id-web": {"containerName": "web", "hasUpdate": True}},
    )
    assert button._updatable_container_ids() == ["id-web"]


def test_bulk_update_updatable_ids_ignores_stale_tier2_entry():
    """A Tier 2 entry keyed under an old container id (left over from
    before the container was recreated by an update) must not resurrect
    a resolved update just because Tier 2 hasn't re-polled yet — the
    *current* container's id isn't a key in that stale snapshot, so the
    lookup should simply miss."""
    button, _, _ = _make_bulk_update_button(
        pending=set(),
        containers=[{"id": "id-web-new", "name": "web", "systemContainer": None}],
        update_data={"id-web-old": {"containerName": "web", "hasUpdate": True}},
    )
    assert button._updatable_container_ids() == []


async def test_bulk_update_press_raises_when_nothing_updatable():
    button, _, _ = _make_bulk_update_button()
    with pytest.raises(HomeAssistantError):
        await button.async_press()


async def test_bulk_update_press_success():
    button, coord, client = _make_bulk_update_button(
        pending={"id-web"},
        containers=[{"id": "id-web", "name": "web", "systemContainer": None}],
    )
    client.async_start_batch_update_stream = AsyncMock(return_value="job-1")
    client.async_get_job = AsyncMock(return_value={"status": "done", "lines": []})
    await button.async_press()
    client.async_start_batch_update_stream.assert_called_once_with(
        ENV_ID, ["id-web"], vulnerability_criteria=None
    )
    coord.async_refresh.assert_called_once()


async def test_bulk_update_press_raises_on_job_error():
    button, _, client = _make_bulk_update_button(
        pending={"id-web"},
        containers=[{"id": "id-web", "name": "web", "systemContainer": None}],
    )
    client.async_start_batch_update_stream = AsyncMock(return_value="job-1")
    client.async_get_job = AsyncMock(
        return_value={"status": "error", "result": {"error": "pull failed"}}
    )
    with pytest.raises(HomeAssistantError):
        await button.async_press()


async def test_bulk_update_press_collects_multiple_failures():
    """A partial batch failure (some containers blocked/failed, others
    fine) shouldn't hide that multiple containers failed — the summary
    error should mention all of them, not just the first."""
    button, _, client = _make_bulk_update_button(
        pending={"id-web", "id-db"},
        containers=[
            {"id": "id-web", "name": "web", "systemContainer": None},
            {"id": "id-db", "name": "db", "systemContainer": None},
        ],
    )
    client.async_start_batch_update_stream = AsyncMock(return_value="job-1")
    client.async_get_job = AsyncMock(
        return_value={
            "status": "done",
            "lines": [
                {
                    "data": {
                        "type": "blocked",
                        "containerId": "id-web",
                        "blockReason": "critical CVE",
                    }
                },
                {
                    "data": {
                        "type": "progress",
                        "step": "failed",
                        "containerId": "id-db",
                        "error": "pull timeout",
                    }
                },
            ],
        }
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await button.async_press()
    message = str(exc_info.value.translation_placeholders["error"])
    assert "id-web" in message
    assert "id-db" in message


async def test_setup_entry_creates_bulk_update_button_when_pending():
    from custom_components.dockhand.button import async_setup_entry

    fast = MagicMock()
    fast.data = {
        "environments": {
            ENV_ID: {
                "stats": {"name": ENV_NAME},
                "containers": [
                    {"id": "id-web", "name": "web", "systemContainer": None}
                ],
                "stacks": [],
                "pending_update_container_ids": {"id-web"},
            }
        }
    }
    fast.async_add_listener = MagicMock(return_value=lambda: None)
    slow = MagicMock()
    slow.data = {"environments": {}, "schedules": []}
    slow.async_add_listener = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"api_url": BASE_URL}
    entry.options = {}
    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.runtime_data.client = MagicMock()
    entry.runtime_data.update_coordinator = None
    entry.async_on_unload = MagicMock()

    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)
    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    names = [type(e).__name__ for e in created]
    assert "DockhandEnvBulkUpdateButton" in names


async def test_setup_entry_skips_bulk_update_button_when_nothing_pending():
    from custom_components.dockhand.button import async_setup_entry

    fast = MagicMock()
    fast.data = {
        "environments": {
            ENV_ID: {
                "stats": {"name": ENV_NAME},
                "containers": [],
                "stacks": [],
                "pending_update_container_ids": set(),
            }
        }
    }
    fast.async_add_listener = MagicMock(return_value=lambda: None)
    slow = MagicMock()
    slow.data = {"environments": {}, "schedules": []}
    slow.async_add_listener = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"api_url": BASE_URL}
    entry.options = {}
    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.runtime_data.client = MagicMock()
    entry.runtime_data.update_coordinator = None
    entry.async_on_unload = MagicMock()

    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)
    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    names = [type(e).__name__ for e in created]
    assert "DockhandEnvBulkUpdateButton" not in names


async def test_setup_entry_skips_bulk_update_button_when_update_entities_disabled():
    """CONF_ENABLE_UPDATE_ENTITIES=False must suppress the bulk button even
    when Tier 1 genuinely has a pending update — Tier 1's own fetch isn't
    gated on this option (other consumers legitimately want it), so this
    has to be an explicit check rather than relying on the data being
    absent. github.com/raetha/ha-dockhand/issues/23."""
    from custom_components.dockhand.button import async_setup_entry
    from custom_components.dockhand.const import CONF_ENABLE_UPDATE_ENTITIES

    fast = MagicMock()
    fast.data = {
        "environments": {
            ENV_ID: {
                "stats": {"name": ENV_NAME},
                "containers": [
                    {"id": "id-web", "name": "web", "systemContainer": None}
                ],
                "stacks": [],
                "pending_update_container_ids": {"id-web"},
            }
        }
    }
    fast.async_add_listener = MagicMock(return_value=lambda: None)
    slow = MagicMock()
    slow.data = {"environments": {}, "schedules": []}
    slow.async_add_listener = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"api_url": BASE_URL}
    entry.options = {CONF_ENABLE_UPDATE_ENTITIES: False}
    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.runtime_data.client = MagicMock()
    entry.runtime_data.update_coordinator = None
    entry.async_on_unload = MagicMock()

    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)
    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    names = [type(e).__name__ for e in created]
    assert "DockhandEnvBulkUpdateButton" not in names


# ---------------------------------------------------------------------------
# Check-updates button (env-level "Check for updates", conditionally present)
# ---------------------------------------------------------------------------


def _make_check_updates_button(
    env_id=ENV_ID,
    update_coordinator=None,
    update_entities_enabled=True,
    check_result=None,
):
    from custom_components.dockhand.button import DockhandCheckUpdatesButton

    fast_coord = MagicMock()
    fast_coord.data = {"environments": {env_id: {"stats": {"name": ENV_NAME}}}}
    fast_coord.async_merge_pending_updates_from_check = MagicMock()
    client = MagicMock()
    client.async_check_container_updates = AsyncMock(
        return_value=check_result if check_result is not None else []
    )
    button = DockhandCheckUpdatesButton(
        fast_coord,
        client,
        update_coordinator,
        update_entities_enabled,
        ENTRY_ID,
        env_id,
        ENV_NAME,
        BASE_URL,
    )
    return button, fast_coord, client


async def test_check_updates_press_calls_client_for_its_own_environment_only():
    """The actual design fix from the original bug report: this button
    used to call async_refresh() on the whole DockhandUpdateCoordinator,
    which always re-checked every environment in one gather -- so
    pressing environment 1's button silently also re-checked every other
    environment too. Now it calls the client directly, scoped to just
    its own environment id, regardless of what coordinators exist."""
    button, _, client = _make_check_updates_button(env_id=7)
    await button.async_press()
    client.async_check_container_updates.assert_called_once_with(7)


async def test_check_updates_press_raises_on_error():
    button, _, client = _make_check_updates_button()
    client.async_check_container_updates = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(HomeAssistantError):
        await button.async_press()


async def test_check_updates_press_feeds_tier2_when_precise_updates_enabled():
    """When update_coordinator exists (Tier 2/precise updates on), the
    already-fetched response feeds it directly via
    async_merge_check_results() -- not a second, redundant client call."""
    update_coord = MagicMock()
    update_coord.async_merge_check_results = MagicMock()
    result = [{"containerId": "id-web", "containerName": "web", "hasUpdate": True}]
    button, fast_coord, client = _make_check_updates_button(
        update_coordinator=update_coord,
        update_entities_enabled=False,
        check_result=result,
    )
    await button.async_press()
    update_coord.async_merge_check_results.assert_called_once_with(ENV_ID, result)
    client.async_check_container_updates.assert_called_once()
    fast_coord.async_merge_pending_updates_from_check.assert_not_called()


async def test_check_updates_press_feeds_tier1_when_update_entities_enabled():
    """When update_entities_enabled is on, the same response also
    refreshes Tier 1's pending set for this environment immediately,
    regardless of whether Tier 2/precise updates is configured at all."""
    result = [
        {"containerId": "id-web", "containerName": "web", "hasUpdate": True},
        {"containerId": "id-db", "containerName": "db", "hasUpdate": False},
    ]
    button, fast_coord, _ = _make_check_updates_button(
        update_coordinator=None,
        update_entities_enabled=True,
        check_result=result,
    )
    await button.async_press()
    fast_coord.async_merge_pending_updates_from_check.assert_called_once_with(
        ENV_ID, {"id-web"}
    )


async def test_check_updates_press_feeds_both_tiers_when_both_enabled():
    update_coord = MagicMock()
    update_coord.async_merge_check_results = MagicMock()
    result = [{"containerId": "id-web", "containerName": "web", "hasUpdate": True}]
    button, fast_coord, _ = _make_check_updates_button(
        update_coordinator=update_coord,
        update_entities_enabled=True,
        check_result=result,
    )
    await button.async_press()
    update_coord.async_merge_check_results.assert_called_once_with(ENV_ID, result)
    fast_coord.async_merge_pending_updates_from_check.assert_called_once_with(
        ENV_ID, {"id-web"}
    )


async def test_check_updates_press_captures_nothing_when_neither_enabled():
    """The check still runs (Dockhand's own cache still gets refreshed
    server-side) even when nothing local is configured to consume the
    response -- but nothing local should be touched in that case."""
    button, fast_coord, client = _make_check_updates_button(
        update_coordinator=None,
        update_entities_enabled=False,
        check_result=[{"containerId": "id-web", "hasUpdate": True}],
    )
    await button.async_press()
    client.async_check_container_updates.assert_called_once()
    fast_coord.async_merge_pending_updates_from_check.assert_not_called()


async def test_check_updates_button_always_created_regardless_of_options():
    """No longer gated on update_coordinator or either config option --
    it's a read-only, user-initiated action, not a way to perform
    updates, so neither option needs to block its existence."""
    from custom_components.dockhand.button import async_setup_entry

    fast = MagicMock()
    fast.data = {
        "environments": {
            ENV_ID: {
                "stats": {"name": ENV_NAME},
                "containers": [],
                "stacks": [],
                "pending_update_container_ids": set(),
            }
        }
    }
    fast.async_add_listener = MagicMock(return_value=lambda: None)
    slow = MagicMock()
    slow.data = {"environments": {}, "schedules": []}
    slow.async_add_listener = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"api_url": BASE_URL}
    entry.options = {"enable_update_entities": False}
    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.runtime_data.client = MagicMock()
    entry.runtime_data.update_coordinator = None
    entry.async_on_unload = MagicMock()

    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)
    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    names = [type(e).__name__ for e in created]
    assert "DockhandCheckUpdatesButton" in names


# ---------------------------------------------------------------------------
# Container stats sensors gated on "Enable container stats" (async_setup_entry)
# ---------------------------------------------------------------------------


def _make_container_stats_setup_entry(enable_container_stats):
    from custom_components.dockhand.sensor import async_setup_entry  # noqa: F401

    fast = MagicMock()
    fast.data = {
        "environments": {
            ENV_ID: {
                "stats": STATS,
                "containers": [CONTAINER],
                "stacks": [],
                "container_stats": {},
                "pending_update_container_ids": set(),
            }
        }
    }
    fast.async_add_listener = MagicMock(return_value=lambda: None)

    slow = MagicMock()
    slow.data = {"environments": {}, "schedules": []}
    slow.async_add_listener = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"api_url": BASE_URL, "enable_container_stats": enable_container_stats}
    entry.options = {}
    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.runtime_data.client = MagicMock()
    entry.runtime_data.update_coordinator = None
    entry.async_on_unload = MagicMock()
    return entry


async def _created_entity_names(entry):
    from custom_components.dockhand.sensor import async_setup_entry

    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)
    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    return [type(e).__name__ for e in created]


STATS_SENSOR_NAMES = {
    "DockhandContainerCpuSensor",
    "DockhandContainerMemoryUsageSensor",
    "DockhandContainerMemoryPercentSensor",
    "DockhandContainerMemoryLimitSensor",
    "DockhandContainerNetworkRxSensor",
    "DockhandContainerNetworkTxSensor",
    "DockhandContainerBlockReadSensor",
    "DockhandContainerBlockWriteSensor",
}


async def test_container_stats_entities_not_created_when_option_off():
    """Not just disabled-by-default — genuinely not instantiated at all,
    same as enable_images/enable_volumes/enable_networks, so the existing
    central cleanup system removes any that already exist from before the
    option was turned off (Raetha's report: they weren't being cleaned up
    because they were always being created regardless of the flag)."""
    entry = _make_container_stats_setup_entry(enable_container_stats=False)
    names = await _created_entity_names(entry)
    assert not (STATS_SENSOR_NAMES & set(names)), (
        f"stats sensors should not be created when the option is off, found: {STATS_SENSOR_NAMES & set(names)}"
    )
    # The container's core sensors are unaffected by the flag.
    assert "DockhandContainerStateSensor" in names


async def test_container_stats_entities_created_when_option_on():
    entry = _make_container_stats_setup_entry(enable_container_stats=True)
    names = await _created_entity_names(entry)
    assert STATS_SENSOR_NAMES.issubset(set(names))
