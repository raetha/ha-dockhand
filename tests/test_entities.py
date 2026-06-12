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

STATS = {
    "name": "MyHost",
    "online": True,
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
        ENV_ID: env_data
        or {
            "stats": STATS,
            "containers": [CONTAINER],
            "stacks": [STACK],
            "container_stats": {},
        }
    }
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
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
    coord.async_request_refresh = AsyncMock()
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
        DockhandEnvBuildCacheSensor,
        DockhandEnvContainerCountSensor,
        DockhandEnvContainersDiskSensor,
        DockhandEnvCpuSensor,
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
        DockhandEnvImagePruneBinarySensor,
        DockhandEnvOnlineSensor,
        DockhandEnvScannerEnabledSensor,
        DockhandEnvUpdateCheckSensor,
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
    return {
        "cpu": sc["DockhandEnvCpuSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
        "mem": sc["DockhandEnvMemPercentSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
        "containers": sc["DockhandEnvContainerCountSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
        "stacks": sc["DockhandEnvStacksSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
        "images": sc["DockhandEnvImagesSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
        "volumes": sc["DockhandEnvVolumesSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
        "networks": sc["DockhandEnvNetworksSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
        "disk": sc["DockhandEnvContainersDiskSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
        "cache": sc["DockhandEnvBuildCacheSensor"](coord, ENV_ID, ENV_NAME, BASE_URL),
    }


def test_cpu_value(env_sensors):
    assert abs(env_sensors["cpu"].native_value - 23.5) < 1e-9


def test_mem_percent_value(env_sensors):
    assert abs(env_sensors["mem"].native_value - 45.2) < 1e-9


def test_mem_attributes_raw_bytes(env_sensors):
    attrs = env_sensors["mem"].extra_state_attributes
    assert attrs["memory_used_bytes"] == 4724464640
    assert attrs["memory_total_bytes"] == 8589934592
    assert "memory_used_mib" not in attrs


def test_container_count_total(env_sensors):
    assert env_sensors["containers"].native_value == 4


def test_container_count_attributes(env_sensors):
    attrs = env_sensors["containers"].extra_state_attributes
    assert attrs["running"] == 3
    assert attrs["stopped"] == 1
    assert attrs["pending_updates"] == 1


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


def test_disk_value_bytes(env_sensors):
    assert env_sensors["disk"].native_value == 524288000


def test_disk_disabled_by_default(env_sensors):
    assert not env_sensors["disk"]._attr_entity_registry_enabled_default


def test_cache_value_bytes(env_sensors):
    assert env_sensors["cache"].native_value == 104857600


def test_cache_disabled_by_default(env_sensors):
    assert not env_sensors["cache"]._attr_entity_registry_enabled_default


def test_env_sensor_unique_ids_are_unique(env_sensors):
    uids = [s._attr_unique_id for s in env_sensors.values()]
    assert len(uids) == len(set(uids))


def test_env_sensor_entity_category_diagnostic(env_sensors):
    for key in ["containers", "stacks", "images", "volumes", "networks", "disk", "cache"]:
        assert env_sensors[key]._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_env_sensor_has_entity_name_true(env_sensors):
    for name, sensor in env_sensors.items():
        assert sensor._attr_has_entity_name, (
            f"{type(sensor).__name__} must have _attr_has_entity_name=True"
        )


# ===========================================================================
# Environment activity sensor
# ===========================================================================


def _make_activity(events=None):
    from custom_components.dockhand.sensor import DockhandEnvActivityEventsSensor
    coord = _fast_coord(env_data={
        "stats": {**STATS, "events": events or {"total": 42, "today": 7}},
        "containers": [],
        "stacks": [],
    })
    return DockhandEnvActivityEventsSensor(coord, ENV_ID, ENV_NAME, BASE_URL)


def test_activity_total_event_count():
    assert _make_activity().native_value == 42


def test_activity_today_attribute():
    assert _make_activity().extra_state_attributes["today"] == 7


def test_activity_disabled_by_default():
    assert not _make_activity()._attr_entity_registry_enabled_default


def test_activity_state_class_is_measurement():
    from homeassistant.components.sensor import SensorStateClass
    assert _make_activity()._attr_state_class == SensorStateClass.MEASUREMENT


# ===========================================================================
# Hawser version sensor
# ===========================================================================


def _make_hawser(env_obj=None):
    from custom_components.dockhand.sensor import DockhandEnvHawserVersionSensor
    coord = _slow_coord(env_data={
        "env": env_obj or {
            "name": ENV_NAME,
            "hawserVersion": "1.4.2",
            "hawserAgentName": "agent-1",
            "hawserAgentId": "abc",
            "hawserLastSeen": "2024-01-01T00:00:00Z",
        },
        "images": [], "networks": [], "volumes": [],
    })
    return DockhandEnvHawserVersionSensor(coord, ENV_ID, ENV_NAME, BASE_URL)


def test_hawser_version_string():
    assert _make_hawser().native_value == "1.4.2"


def test_hawser_agent_name_attribute():
    assert _make_hawser().extra_state_attributes["agent_name"] == "agent-1"


def test_hawser_last_seen_attribute_present():
    assert "last_seen" in _make_hawser().extra_state_attributes


def test_hawser_none_when_absent():
    assert _make_hawser(env_obj={"name": ENV_NAME}).native_value is None


def test_hawser_disabled_by_default():
    assert not _make_hawser()._attr_entity_registry_enabled_default


# ===========================================================================
# Container sensors
# ===========================================================================


@pytest.fixture
def container_sensors():
    sc = _sensor_classes()
    coord = _fast_coord()
    return {
        "state": sc["DockhandContainerStateSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER),
        "health": sc["DockhandContainerHealthSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER),
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
        ENV_ID: {"stats": STATS, "containers": [], "stacks": [], "container_stats": {}}
    }
    sc = _sensor_classes()
    state = sc["DockhandContainerStateSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
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
    "memoryRaw":   178257920,
    "memoryCache":  20971520,
    "memoryLimit": 16764731392,
    "memoryPercent": 0.94,
    "networkRx":  83886080,
    "networkTx": 104857600,
    "blockRead":  52428800,
    "blockWrite":  31457280,
}


def _stats_coord(stats=None, running=True):
    coord = MagicMock()
    coord.data = {
        ENV_ID: {
            "stats": STATS,
            "containers": [CONTAINER] if running else [],
            "stacks": [],
            "container_stats": {"nginx": stats or CONTAINER_STATS} if running else {},
        }
    }
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
    return coord


@pytest.fixture
def stats_sensors():
    sc = _sensor_classes()
    coord = _stats_coord()
    args = (coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
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


def test_stats_all_sensors_none_when_container_stopped():
    coord = _stats_coord(running=False)
    sc = _sensor_classes()
    args = (coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
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


def test_stats_all_disabled_by_default(stats_sensors):
    for s in stats_sensors["all"]:
        assert not s._attr_entity_registry_enabled_default, (
            f"{type(s).__name__} should be disabled by default"
        )


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
        "status": sc["DockhandStackStatusSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, STACK),
        "count": sc["DockhandStackContainerCountSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, STACK),
    }


def test_stack_status_value(stack_sensors):
    assert stack_sensors["status"].native_value == "running"


def test_stack_container_count(stack_sensors):
    assert stack_sensors["count"].native_value == 3


def test_stack_status_container_count_attribute(stack_sensors):
    assert "container_count" in stack_sensors["status"].extra_state_attributes


def test_stack_unique_ids_differ(stack_sensors):
    assert stack_sensors["status"]._attr_unique_id != stack_sensors["count"]._attr_unique_id


# ===========================================================================
# Image sensors
# ===========================================================================


def _make_image(image=None):
    sc = _sensor_classes()
    return sc["DockhandImageSensor"](_slow_coord(), ENV_ID, ENV_NAME, BASE_URL, image or IMAGE)


def test_image_native_value_is_tag():
    assert _make_image().native_value == "latest"


def test_image_name_is_repo_only():
    sensor = _make_image()
    assert sensor._attr_name == "nginx"
    assert ":" not in sensor._attr_name


def test_image_has_entity_name_true():
    assert _make_image()._attr_has_entity_name


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
        coord or _slow_coord(), ENV_ID, ENV_NAME, BASE_URL, NETWORK
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
        coord or _slow_coord(), ENV_ID, ENV_NAME, BASE_URL, volume or VOLUME
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
    return sc["DockhandScheduleNextRunSensor"](_slow_coord(schedules=[s]), s, BASE_URL)


def _make_last_status(sched=None):
    sc = _sensor_classes()
    s = sched or SCHEDULE
    return sc["DockhandScheduleLastStatusSensor"](_slow_coord(schedules=[s]), s, BASE_URL)


def test_schedule_next_run_returns_datetime():
    assert _make_next_run().native_value is not None


def test_schedule_next_run_none_when_schedule_gone():
    sc = _sensor_classes()
    sensor = sc["DockhandScheduleNextRunSensor"](_slow_coord(schedules=[]), SCHEDULE, BASE_URL)
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
        _slow_coord(schedules=[sched]), sched, BASE_URL
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
    coord = _fast_coord({
        "stats": {**STATS, **(stats_override or {})},
        "containers": [],
        "stacks": [],
    })
    return bs[cls_name](coord, ENV_ID, BASE_URL)


def test_binary_online_is_on():
    assert _make_binary("DockhandEnvOnlineSensor").is_on


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


def test_binary_image_prune_enabled():
    bs = _bs_classes()
    coord = _slow_coord(env_data={
        "env": {"name": ENV_NAME, "imagePruneEnabled": True},
        "images": [], "networks": [], "volumes": [],
    })
    assert bs["DockhandEnvImagePruneBinarySensor"](coord, ENV_ID, BASE_URL).is_on


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
        s = bs[cls_name](coord, ENV_ID, BASE_URL)
        assert not s._attr_entity_registry_enabled_default, (
            f"{cls_name} should be disabled by default"
        )


def test_binary_online_sensor_enabled_by_default():
    bs = _bs_classes()
    s = bs["DockhandEnvOnlineSensor"](_fast_coord(), ENV_ID, BASE_URL)
    assert s.entity_registry_enabled_default


# ===========================================================================
# Switches
# ===========================================================================


class TestSwitches:
    def _container_switch(self, container=None, coord=None):
        sw = _switch_classes()
        c = container or CONTAINER
        return sw["DockhandContainerRunningSwitch"](
            coord or _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, c
        )

    def _stack_switch(self, stack=None, coord=None):
        sw = _switch_classes()
        s = stack or STACK
        return sw["DockhandStackRunningSwitch"](
            coord or _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, s
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
        switch._client.async_start_stack.assert_called_once_with(
            ENV_ID, STACK["name"]
        )

    async def test_stack_turn_on_raises_ha_error_on_api_failure(self):
        switch = self._stack_switch()
        switch._client = MagicMock()
        switch._client.async_start_stack = AsyncMock(side_effect=Exception("down"))
        with pytest.raises(HomeAssistantError) as exc_info:
            await switch.async_turn_on()
        assert exc_info.value.translation_key == "action_failed"


# ===========================================================================
# Buttons
# ===========================================================================


class TestButtons:
    def _container_btn(self, coord=None):
        btn = _button_classes()
        return btn["DockhandContainerRestartButton"](
            coord or _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )

    def _stack_btn(self):
        btn = _button_classes()
        return btn["DockhandStackRestartButton"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK
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
            coord, client, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        s_btn = btn["DockhandStackRestartButton"](
            coord, client, ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        assert c_btn._attr_entity_category == EntityCategory.CONFIG
        assert s_btn._attr_entity_category == EntityCategory.CONFIG

    def test_restart_buttons_both_use_restart_translation_key(self):
        coord = _fast_coord()
        client = MagicMock()
        btn = _button_classes()
        c_btn = btn["DockhandContainerRestartButton"](
            coord, client, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        s_btn = btn["DockhandStackRestartButton"](
            coord, client, ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        assert c_btn._attr_translation_key == "restart"
        assert s_btn._attr_translation_key == "restart"

    def test_container_device_name_includes_containers_segment(self):
        btn = _button_classes()
        b = btn["DockhandContainerRestartButton"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        assert "Containers" in b.device_info["name"]
        assert CONTAINER["name"] in b.device_info["name"]

    def test_stack_device_name_includes_stacks_segment(self):
        btn = _button_classes()
        b = btn["DockhandStackRestartButton"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        assert "Stacks" in b.device_info["name"]
        assert STACK["name"] in b.device_info["name"]


# ===========================================================================
# Device naming and parentage
# ===========================================================================


def test_container_device_name_format():
    sc = _sensor_classes()
    sensor = sc["DockhandContainerStateSensor"](
        _fast_coord(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
    )
    assert sensor.device_info["name"] == (
        f"{ENV_NAME} \u2013 Containers \u2013 {CONTAINER['name']}"
    )


def test_stack_device_name_format():
    sc = _sensor_classes()
    sensor = sc["DockhandStackStatusSensor"](
        _fast_coord(), ENV_ID, ENV_NAME, BASE_URL, STACK
    )
    assert sensor.device_info["name"] == (
        f"{ENV_NAME} \u2013 Stacks \u2013 {STACK['name']}"
    )


def test_container_switch_device_name_format():
    sw = _switch_classes()
    switch = sw["DockhandContainerRunningSwitch"](
        _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
    )
    assert "Containers" in switch.device_info["name"]
    assert CONTAINER["name"] in switch.device_info["name"]


def test_stack_switch_device_name_format():
    sw = _switch_classes()
    switch = sw["DockhandStackRunningSwitch"](
        _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK
    )
    assert "Stacks" in switch.device_info["name"]
    assert STACK["name"] in switch.device_info["name"]


def test_container_button_device_name_format():
    btn = _button_classes()
    b = btn["DockhandContainerRestartButton"](
        _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
    )
    assert "Containers" in b.device_info["name"]


def test_stack_button_device_name_format():
    btn = _button_classes()
    b = btn["DockhandStackRestartButton"](
        _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK
    )
    assert "Stacks" in b.device_info["name"]


def test_stack_device_helper_name_format():
    """_stack_device() must produce '{env} – Stacks – {name}' (regression guard)."""
    from custom_components.dockhand.helpers import _stack_device
    info = _stack_device(STACK["name"], ENV_ID, ENV_NAME, BASE_URL)
    assert info["name"] == f"{ENV_NAME} \u2013 Stacks \u2013 {STACK['name']}"


def test_network_entity_under_group_device():
    sc = _sensor_classes()
    sensor = sc["DockhandNetworkSensor"](_slow_coord(), ENV_ID, ENV_NAME, BASE_URL, NETWORK)
    idents = sensor.device_info.get("identifiers", set())
    assert (DOMAIN, f"env_{ENV_ID}_Networks") in idents
    assert (DOMAIN, f"network_{NETWORK['id']}") not in idents


def test_volume_entity_under_group_device():
    sc = _sensor_classes()
    sensor = sc["DockhandVolumeSensor"](_slow_coord(), ENV_ID, ENV_NAME, BASE_URL, VOLUME)
    idents = sensor.device_info.get("identifiers", set())
    assert (DOMAIN, f"env_{ENV_ID}_Volumes") in idents


def test_image_entity_under_group_device():
    sc = _sensor_classes()
    sensor = sc["DockhandImageSensor"](_slow_coord(), ENV_ID, ENV_NAME, BASE_URL, IMAGE)
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
