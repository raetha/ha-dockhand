"""
Tests for entity classes across all platforms.

Covers: native_value, extra_state_attributes, is_on, entity metadata
(unique_id, category, enabled-by-default, has_entity_name), device_info
parentage, action method calls, and HomeAssistantError propagation.

Entities are instantiated directly with mock coordinators — no full HA
platform setup required. All HA classes come from ha_stubs.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

import ha_stubs as stubs

stubs.install()
from ha_stubs import EntityCategory, HomeAssistantError

DOMAIN = "dockhand"
run = asyncio.run

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
        DockhandContainerHealthSensor,
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


class TestEnvSensors(unittest.TestCase):
    def setUp(self):
        sc = _sensor_classes()
        coord = _fast_coord()
        self.cpu = sc["DockhandEnvCpuSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)
        self.mem = sc["DockhandEnvMemPercentSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)
        self.containers = sc["DockhandEnvContainerCountSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)
        self.stacks = sc["DockhandEnvStacksSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)
        self.images = sc["DockhandEnvImagesSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)
        self.volumes = sc["DockhandEnvVolumesSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)
        self.networks = sc["DockhandEnvNetworksSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)
        self.disk = sc["DockhandEnvContainersDiskSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)
        self.cache = sc["DockhandEnvBuildCacheSensor"](coord, ENV_ID, ENV_NAME, BASE_URL)

    def test_cpu_value(self):
        self.assertAlmostEqual(self.cpu.native_value, 23.5)

    def test_mem_percent_value(self):
        self.assertAlmostEqual(self.mem.native_value, 45.2)

    def test_mem_attributes_raw_bytes(self):
        attrs = self.mem.extra_state_attributes
        self.assertEqual(attrs["memory_used_bytes"], 4724464640)
        self.assertEqual(attrs["memory_total_bytes"], 8589934592)
        self.assertNotIn("memory_used_mib", attrs)

    def test_container_count_total(self):
        self.assertEqual(self.containers.native_value, 4)

    def test_container_count_attributes(self):
        attrs = self.containers.extra_state_attributes
        self.assertEqual(attrs["running"], 3)
        self.assertEqual(attrs["stopped"], 1)
        self.assertEqual(attrs["pending_updates"], 1)

    def test_stacks_value(self):
        self.assertEqual(self.stacks.native_value, 2)

    def test_images_count(self):
        self.assertEqual(self.images.native_value, 5)

    def test_images_attribute_raw_bytes(self):
        attrs = self.images.extra_state_attributes
        self.assertEqual(attrs["total_size_bytes"], 2147483648)
        self.assertNotIn("total_size_mib", attrs)

    def test_volumes_count(self):
        self.assertEqual(self.volumes.native_value, 2)

    def test_volumes_attribute_raw_bytes(self):
        attrs = self.volumes.extra_state_attributes
        self.assertIn("total_size_bytes", attrs)
        self.assertNotIn("total_size_mib", attrs)

    def test_networks_count(self):
        self.assertEqual(self.networks.native_value, 3)

    def test_disk_value_bytes(self):
        self.assertEqual(self.disk.native_value, 524288000)

    def test_disk_disabled_by_default(self):
        self.assertFalse(self.disk._attr_entity_registry_enabled_default)

    def test_cache_value_bytes(self):
        self.assertEqual(self.cache.native_value, 104857600)

    def test_cache_disabled_by_default(self):
        self.assertFalse(self.cache._attr_entity_registry_enabled_default)

    def test_unique_ids_are_unique(self):
        sensors = [
            self.cpu, self.mem, self.containers, self.stacks,
            self.images, self.volumes, self.networks, self.disk, self.cache,
        ]
        uids = [s._attr_unique_id for s in sensors]
        self.assertEqual(len(uids), len(set(uids)))

    def test_entity_category_diagnostic(self):
        for sensor in [
            self.containers, self.stacks, self.images,
            self.volumes, self.networks, self.disk, self.cache,
        ]:
            self.assertEqual(sensor._attr_entity_category, EntityCategory.DIAGNOSTIC)

    def test_has_entity_name_true(self):
        for sensor in [
            self.cpu, self.mem, self.containers, self.stacks,
            self.images, self.volumes, self.networks, self.disk, self.cache,
        ]:
            self.assertTrue(
                sensor._attr_has_entity_name,
                f"{type(sensor).__name__} must have _attr_has_entity_name=True",
            )


class TestEnvActivitySensor(unittest.TestCase):
    def _make(self, events=None):
        from custom_components.dockhand.sensor import DockhandEnvActivityEventsSensor
        coord = _fast_coord(env_data={
            "stats": {**STATS, "events": events or {"total": 42, "today": 7}},
            "containers": [],
            "stacks": [],
        })
        return DockhandEnvActivityEventsSensor(coord, ENV_ID, ENV_NAME, BASE_URL)

    def test_total_event_count(self):
        self.assertEqual(self._make().native_value, 42)

    def test_today_attribute(self):
        self.assertEqual(self._make().extra_state_attributes["today"], 7)

    def test_disabled_by_default(self):
        self.assertFalse(self._make()._attr_entity_registry_enabled_default)

    def test_state_class_is_measurement(self):
        from ha_stubs import SensorStateClass
        sensor = self._make()
        self.assertEqual(sensor._attr_state_class, SensorStateClass.MEASUREMENT)


class TestEnvHawserSensor(unittest.TestCase):
    def _make(self, env_obj=None):
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

    def test_version_string(self):
        self.assertEqual(self._make().native_value, "1.4.2")

    def test_agent_name_attribute(self):
        self.assertEqual(self._make().extra_state_attributes["agent_name"], "agent-1")

    def test_last_seen_attribute_present(self):
        self.assertIn("last_seen", self._make().extra_state_attributes)

    def test_none_when_absent(self):
        sensor = self._make(env_obj={"name": ENV_NAME})
        self.assertIsNone(sensor.native_value)

    def test_disabled_by_default(self):
        self.assertFalse(self._make()._attr_entity_registry_enabled_default)


# ===========================================================================
# Container sensors
# ===========================================================================


class TestContainerSensors(unittest.TestCase):
    def setUp(self):
        sc = _sensor_classes()
        coord = _fast_coord()
        self.state = sc["DockhandContainerStateSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        self.health = sc["DockhandContainerHealthSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )

    def test_state_value(self):
        self.assertEqual(self.state.native_value, "running")

    def test_state_image_attribute(self):
        self.assertEqual(self.state.extra_state_attributes["image"], "nginx:latest")

    def test_health_value(self):
        self.assertEqual(self.health.native_value, "healthy")

    def test_health_enabled_by_default(self):
        """Health sensor is enabled by default; only created when a healthcheck exists."""
        self.assertTrue(self.health._attr_entity_registry_enabled_default)

    def test_state_none_when_container_gone(self):
        coord = MagicMock()
        coord.data = {ENV_ID: {"stats": STATS, "containers": [], "stacks": []}}
        sc = _sensor_classes()
        state = sc["DockhandContainerStateSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        self.assertIsNone(state.native_value)

    def test_has_entity_name_true(self):
        for s in [self.state, self.health]:
            self.assertTrue(s._attr_has_entity_name)

    def test_unique_ids_include_container_name(self):
        name = CONTAINER["name"]
        self.assertIn(name, self.state._attr_unique_id)
        self.assertIn(name, self.health._attr_unique_id)

    def test_unique_ids_differ(self):
        self.assertNotEqual(self.state._attr_unique_id, self.health._attr_unique_id)


# ===========================================================================
# Stack sensors
# ===========================================================================


class TestStackSensors(unittest.TestCase):
    def setUp(self):
        sc = _sensor_classes()
        coord = _fast_coord()
        self.status = sc["DockhandStackStatusSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        self.count = sc["DockhandStackContainerCountSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, STACK
        )

    def test_status_value(self):
        self.assertEqual(self.status.native_value, "running")

    def test_container_count(self):
        self.assertEqual(self.count.native_value, 3)

    def test_status_container_count_attribute(self):
        self.assertIn("container_count", self.status.extra_state_attributes)

    def test_unique_ids_differ(self):
        self.assertNotEqual(self.status._attr_unique_id, self.count._attr_unique_id)


# ===========================================================================
# Image sensors
# ===========================================================================


class TestImageSensor(unittest.TestCase):
    def _make(self, image=None):
        sc = _sensor_classes()
        return sc["DockhandImageSensor"](
            _slow_coord(), ENV_ID, ENV_NAME, BASE_URL, image or IMAGE
        )

    def test_native_value_is_tag(self):
        self.assertEqual(self._make().native_value, "latest")

    def test_name_is_repo_only(self):
        sensor = self._make()
        self.assertEqual(sensor._attr_name, "nginx")
        self.assertNotIn(":", sensor._attr_name)

    def test_has_entity_name_true(self):
        """Images use has_entity_name=True so device name prefixes entity_id."""
        self.assertTrue(self._make()._attr_has_entity_name)

    def test_size_bytes_attribute(self):
        attrs = self._make().extra_state_attributes
        self.assertEqual(attrs["size_bytes"], 104857600)
        self.assertNotIn("size_mib", attrs)

    def test_tags_attribute(self):
        self.assertEqual(self._make().extra_state_attributes["tags"], ["nginx:latest"])

    def test_containers_using_attribute(self):
        self.assertEqual(self._make().extra_state_attributes["containers_using"], 2)

    def test_device_is_images_group(self):
        idents = self._make().device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Images"), idents)


# ===========================================================================
# Network sensors
# ===========================================================================


class TestNetworkSensor(unittest.TestCase):
    def _make(self, coord=None):
        sc = _sensor_classes()
        return sc["DockhandNetworkSensor"](
            coord or _slow_coord(), ENV_ID, ENV_NAME, BASE_URL, NETWORK
        )

    def test_container_count(self):
        self.assertEqual(self._make().native_value, 1)

    def test_attributes(self):
        attrs = self._make().extra_state_attributes
        self.assertEqual(attrs["driver"], "bridge")
        self.assertEqual(attrs["subnet"], "172.17.0.0/16")
        self.assertIn("nginx", attrs["connected_containers"])

    def test_none_when_not_found(self):
        coord = _slow_coord(
            env_data={"env": {}, "images": [], "networks": [], "volumes": []}
        )
        self.assertIsNone(self._make(coord).native_value)

    def test_unique_id_includes_env_id(self):
        self.assertIn(str(ENV_ID), self._make()._attr_unique_id)

    def test_name_is_network_name(self):
        """_attr_name is the network name (device name provides env+type prefix)."""
        sensor = self._make()
        self.assertEqual(sensor._attr_name, NETWORK["name"])
        self.assertTrue(sensor._attr_has_entity_name)

    def test_device_is_networks_group(self):
        idents = self._make().device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Networks"), idents)
        self.assertNotIn((DOMAIN, f"network_{NETWORK['id']}"), idents)


# ===========================================================================
# Volume sensors
# ===========================================================================


class TestVolumeSensor(unittest.TestCase):
    def _make(self, volume=None, coord=None):
        sc = _sensor_classes()
        vol = volume or VOLUME
        return sc["DockhandVolumeSensor"](
            coord or _slow_coord(), ENV_ID, ENV_NAME, BASE_URL, vol
        )

    def test_container_count_when_used(self):
        self.assertEqual(self._make().native_value, 1)

    def test_container_count_zero_when_unused(self):
        coord = _slow_coord(
            env_data={"env": {}, "images": [], "networks": [], "volumes": [VOLUME_UNUSED]}
        )
        self.assertEqual(self._make(VOLUME_UNUSED, coord).native_value, 0)

    def test_in_use_attribute(self):
        self.assertTrue(self._make().extra_state_attributes["in_use"])

    def test_containers_attribute(self):
        self.assertEqual(
            self._make().extra_state_attributes["containers"], ["container_abc123"]
        )

    def test_driver_scope_mountpoint_created(self):
        attrs = self._make().extra_state_attributes
        self.assertEqual(attrs["driver"], "local")
        self.assertEqual(attrs["scope"], "local")
        self.assertIn("mountpoint", attrs)
        self.assertIn("created", attrs)

    def test_none_when_not_found(self):
        coord = _slow_coord(
            env_data={"env": {}, "images": [], "networks": [], "volumes": []}
        )
        self.assertIsNone(self._make(coord=coord).native_value)

    def test_name_is_volume_name(self):
        """_attr_name is the volume name (device name provides env+type prefix)."""
        sensor = self._make()
        self.assertEqual(sensor._attr_name, VOLUME["name"])
        self.assertTrue(sensor._attr_has_entity_name)

    def test_device_is_volumes_group(self):
        idents = self._make().device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Volumes"), idents)


# ===========================================================================
# Schedule sensors
# ===========================================================================


class TestScheduleSensors(unittest.TestCase):
    def _next_run(self, sched=None):
        sc = _sensor_classes()
        s = sched or SCHEDULE
        return sc["DockhandScheduleNextRunSensor"](
            _slow_coord(schedules=[s]), s, BASE_URL
        )

    def _last_status(self, sched=None):
        sc = _sensor_classes()
        s = sched or SCHEDULE
        return sc["DockhandScheduleLastStatusSensor"](
            _slow_coord(schedules=[s]), s, BASE_URL
        )

    def test_next_run_returns_datetime(self):
        self.assertIsNotNone(self._next_run().native_value)

    def test_next_run_none_when_schedule_gone(self):
        sc = _sensor_classes()
        sensor = sc["DockhandScheduleNextRunSensor"](
            _slow_coord(schedules=[]), SCHEDULE, BASE_URL
        )
        self.assertIsNone(sensor.native_value)

    def test_next_run_attributes(self):
        attrs = self._next_run().extra_state_attributes
        self.assertEqual(attrs["cron_expression"], "0 2 * * *")
        self.assertTrue(attrs["enabled"])
        self.assertEqual(attrs["schedule_type"], "system")

    def test_last_status_success(self):
        self.assertEqual(self._last_status().native_value, "success")

    def test_last_status_failed(self):
        self.assertEqual(self._last_status(SCHEDULE_FAILED).native_value, "failed")

    def test_last_status_attributes_on_failure(self):
        attrs = self._last_status(SCHEDULE_FAILED).extra_state_attributes
        self.assertEqual(attrs["error_message"], "Connection timeout")
        self.assertIn("triggered_at", attrs)
        self.assertIn("duration_ms", attrs)

    def test_last_status_none_when_no_execution(self):
        sched = {**SCHEDULE, "lastExecution": None}
        sc = _sensor_classes()
        sensor = sc["DockhandScheduleLastStatusSensor"](
            _slow_coord(schedules=[sched]), sched, BASE_URL
        )
        self.assertIsNone(sensor.native_value)

    def test_both_sensors_share_device(self):
        nr = self._next_run()
        ls = self._last_status()
        self.assertEqual(
            nr.device_info.get("identifiers"), ls.device_info.get("identifiers")
        )

    def test_device_is_child_of_hub(self):
        via = self._next_run().device_info.get("via_device")
        self.assertEqual(via, ("dockhand", "schedules_hub"))

    def test_last_status_is_diagnostic(self):
        self.assertEqual(
            self._last_status()._attr_entity_category, EntityCategory.DIAGNOSTIC
        )


# ===========================================================================
# Binary sensors
# ===========================================================================


class TestBinarySensors(unittest.TestCase):
    def _make(self, cls_name, stats_override=None):
        bs = _bs_classes()
        coord = _fast_coord({
            "stats": {**STATS, **(stats_override or {})},
            "containers": [],
            "stacks": [],
        })
        return bs[cls_name](coord, ENV_ID, BASE_URL)

    def test_online_is_on(self):
        self.assertTrue(self._make("DockhandEnvOnlineSensor").is_on)

    def test_collect_activity_true(self):
        self.assertTrue(self._make("DockhandEnvCollectActivitySensor").is_on)

    def test_collect_metrics_true(self):
        self.assertTrue(self._make("DockhandEnvCollectMetricsSensor").is_on)

    def test_scanner_disabled(self):
        self.assertFalse(self._make("DockhandEnvScannerEnabledSensor").is_on)

    def test_update_checks_enabled(self):
        self.assertTrue(self._make("DockhandEnvUpdateCheckSensor").is_on)

    def test_auto_update_disabled(self):
        self.assertFalse(self._make("DockhandEnvAutoUpdateSensor").is_on)

    def test_image_prune_enabled(self):
        bs = _bs_classes()
        coord = _slow_coord(env_data={
            "env": {"name": ENV_NAME, "imagePruneEnabled": True},
            "images": [], "networks": [], "volumes": [],
        })
        self.assertTrue(bs["DockhandEnvImagePruneBinarySensor"](coord, ENV_ID, BASE_URL).is_on)

    def test_config_sensors_disabled_by_default(self):
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
            self.assertFalse(
                s._attr_entity_registry_enabled_default,
                f"{cls_name} should be disabled by default",
            )

    def test_online_sensor_enabled_by_default(self):
        bs = _bs_classes()
        s = bs["DockhandEnvOnlineSensor"](_fast_coord(), ENV_ID, BASE_URL)
        self.assertTrue(s._attr_entity_registry_enabled_default)


# ===========================================================================
# Switches
# ===========================================================================


class TestSwitches(unittest.TestCase):
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
        self.assertTrue(self._container_switch().is_on)

    def test_container_off_when_stopped(self):
        stopped = {**CONTAINER, "state": "stopped"}
        coord = _fast_coord({"stats": STATS, "containers": [stopped], "stacks": []})
        self.assertFalse(self._container_switch(stopped, coord).is_on)

    def test_stack_on_when_running(self):
        self.assertTrue(self._stack_switch().is_on)

    def test_stack_off_when_stopped(self):
        stopped = {**STACK, "status": "stopped"}
        coord = _fast_coord({"stats": STATS, "containers": [], "stacks": [stopped]})
        self.assertFalse(self._stack_switch(stopped, coord).is_on)

    def test_container_turn_on_calls_start(self):
        switch = self._container_switch()
        switch._client = MagicMock()
        switch._client.async_start_container = AsyncMock()
        run(switch.async_turn_on())
        switch._client.async_start_container.assert_called_once_with(
            ENV_ID, CONTAINER["id"]
        )

    def test_container_turn_off_calls_stop(self):
        switch = self._container_switch()
        switch._client = MagicMock()
        switch._client.async_stop_container = AsyncMock()
        run(switch.async_turn_off())
        switch._client.async_stop_container.assert_called_once_with(
            ENV_ID, CONTAINER["id"]
        )

    def test_container_turn_on_raises_ha_error_on_api_failure(self):
        switch = self._container_switch()
        switch._client = MagicMock()
        switch._client.async_start_container = AsyncMock(
            side_effect=Exception("network error")
        )
        with self.assertRaises(HomeAssistantError) as ctx:
            run(switch.async_turn_on())
        self.assertEqual(ctx.exception.translation_key, "action_failed")

    def test_container_turn_off_raises_ha_error_on_api_failure(self):
        switch = self._container_switch()
        switch._client = MagicMock()
        switch._client.async_stop_container = AsyncMock(
            side_effect=Exception("timeout")
        )
        with self.assertRaises(HomeAssistantError) as ctx:
            run(switch.async_turn_off())
        self.assertEqual(ctx.exception.translation_key, "action_failed")

    def test_container_turn_on_raises_not_found_when_container_missing(self):
        """If the container is no longer in coordinator data, container_not_found is raised."""
        coord = _fast_coord({"stats": STATS, "containers": [], "stacks": []})
        switch = self._container_switch(coord=coord)
        switch._client = MagicMock()
        with self.assertRaises(HomeAssistantError) as ctx:
            run(switch.async_turn_on())
        self.assertEqual(ctx.exception.translation_key, "container_not_found")

    def test_stack_turn_on_calls_start(self):
        switch = self._stack_switch()
        switch._client = MagicMock()
        switch._client.async_start_stack = AsyncMock()
        run(switch.async_turn_on())
        switch._client.async_start_stack.assert_called_once_with(
            ENV_ID, STACK["name"]
        )

    def test_stack_turn_on_raises_ha_error_on_api_failure(self):
        switch = self._stack_switch()
        switch._client = MagicMock()
        switch._client.async_start_stack = AsyncMock(side_effect=Exception("down"))
        with self.assertRaises(HomeAssistantError) as ctx:
            run(switch.async_turn_on())
        self.assertEqual(ctx.exception.translation_key, "action_failed")


# ===========================================================================
# Buttons
# ===========================================================================


class TestButtons(unittest.TestCase):
    def _container_btn(self, coord=None):
        btn = _button_classes()
        b = btn["DockhandContainerRestartButton"](
            coord or _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        return b

    def _stack_btn(self):
        btn = _button_classes()
        return btn["DockhandStackRestartButton"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK
        )

    def test_container_restart_calls_api(self):
        b = self._container_btn()
        b._client = MagicMock()
        b._client.async_restart_container = AsyncMock()
        run(b.async_press())
        b._client.async_restart_container.assert_called_once_with(
            ENV_ID, CONTAINER["id"]
        )

    def test_stack_restart_calls_api(self):
        b = self._stack_btn()
        b._client = MagicMock()
        b._client.async_restart_stack = AsyncMock()
        run(b.async_press())
        b._client.async_restart_stack.assert_called_once_with(ENV_ID, STACK["name"])

    def test_container_restart_raises_ha_error_on_api_failure(self):
        b = self._container_btn()
        b._client = MagicMock()
        b._client.async_restart_container = AsyncMock(
            side_effect=Exception("connection refused")
        )
        with self.assertRaises(HomeAssistantError) as ctx:
            run(b.async_press())
        self.assertEqual(ctx.exception.translation_key, "action_failed")

    def test_container_restart_raises_not_found_when_container_missing(self):
        coord = _fast_coord({"stats": STATS, "containers": [], "stacks": []})
        b = self._container_btn(coord=coord)
        b._client = MagicMock()
        with self.assertRaises(HomeAssistantError) as ctx:
            run(b.async_press())
        self.assertEqual(ctx.exception.translation_key, "container_not_found")

    def test_stack_restart_raises_ha_error_on_api_failure(self):
        b = self._stack_btn()
        b._client = MagicMock()
        b._client.async_restart_stack = AsyncMock(side_effect=Exception("refused"))
        with self.assertRaises(HomeAssistantError) as ctx:
            run(b.async_press())
        self.assertEqual(ctx.exception.translation_key, "action_failed")

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
        self.assertEqual(c_btn._attr_entity_category, EntityCategory.CONFIG)
        self.assertEqual(s_btn._attr_entity_category, EntityCategory.CONFIG)

    def test_restart_buttons_both_use_restart_translation_key(self):
        """Both use the same 'restart' key — no collision because device names now differ.

        Container device: 'Forseti - Containers - nginx'
        Stack device:     'Forseti - Stacks - nginx'
        → entity_ids: button.forseti_containers_nginx_restart vs button.forseti_stacks_nginx_restart
        """
        coord = _fast_coord()
        client = MagicMock()
        btn = _button_classes()
        c_btn = btn["DockhandContainerRestartButton"](
            coord, client, ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        s_btn = btn["DockhandStackRestartButton"](
            coord, client, ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        self.assertEqual(c_btn._attr_translation_key, "restart")
        self.assertEqual(s_btn._attr_translation_key, "restart")

    def test_container_device_name_includes_containers_segment(self):
        """Container device names include 'Containers' type segment."""
        btn = _button_classes()
        b = btn["DockhandContainerRestartButton"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        self.assertIn("Containers", b.device_info["name"])
        self.assertIn(CONTAINER["name"], b.device_info["name"])

    def test_stack_device_name_includes_stacks_segment(self):
        """Stack device names include 'Stacks' type segment."""
        btn = _button_classes()
        b = btn["DockhandStackRestartButton"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        self.assertIn("Stacks", b.device_info["name"])
        self.assertIn(STACK["name"], b.device_info["name"])


# ===========================================================================
# Device naming and parentage
# ===========================================================================


class TestDeviceInfo(unittest.TestCase):
    """Verify env-prefixed names and correct group device parentage."""

    def test_container_device_name_format(self):
        """Container device name must be '{env} – Containers – {name}'."""
        sc = _sensor_classes()
        sensor = sc["DockhandContainerStateSensor"](
            _fast_coord(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        name = sensor.device_info["name"]
        self.assertEqual(name, f"{ENV_NAME} \u2013 Containers \u2013 {CONTAINER['name']}")

    def test_stack_device_name_format(self):
        """Stack device name must be '{env} – Stacks – {name}'."""
        sc = _sensor_classes()
        sensor = sc["DockhandStackStatusSensor"](
            _fast_coord(), ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        name = sensor.device_info["name"]
        self.assertEqual(name, f"{ENV_NAME} \u2013 Stacks \u2013 {STACK['name']}")

    def test_container_switch_device_name_format(self):
        sw = _switch_classes()
        switch = sw["DockhandContainerRunningSwitch"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        self.assertIn("Containers", switch.device_info["name"])
        self.assertIn(CONTAINER["name"], switch.device_info["name"])

    def test_stack_switch_device_name_format(self):
        sw = _switch_classes()
        switch = sw["DockhandStackRunningSwitch"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        self.assertIn("Stacks", switch.device_info["name"])
        self.assertIn(STACK["name"], switch.device_info["name"])

    def test_container_button_device_name_format(self):
        btn = _button_classes()
        b = btn["DockhandContainerRestartButton"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER
        )
        self.assertIn("Containers", b.device_info["name"])

    def test_stack_button_device_name_format(self):
        btn = _button_classes()
        b = btn["DockhandStackRestartButton"](
            _fast_coord(), MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK
        )
        self.assertIn("Stacks", b.device_info["name"])

    def test_stack_device_helper_name_format(self):
        """_stack_device() must produce '{env} – Stacks – {name}' (regression guard)."""
        from custom_components.dockhand.helpers import _stack_device
        info = _stack_device(STACK["name"], ENV_ID, ENV_NAME, BASE_URL)
        name = info["name"]
        self.assertEqual(name, f"{ENV_NAME} \u2013 Stacks \u2013 {STACK['name']}")

    def test_network_entity_under_group_device(self):
        sc = _sensor_classes()
        sensor = sc["DockhandNetworkSensor"](
            _slow_coord(), ENV_ID, ENV_NAME, BASE_URL, NETWORK
        )
        idents = sensor.device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Networks"), idents)
        self.assertNotIn((DOMAIN, f"network_{NETWORK['id']}"), idents)

    def test_volume_entity_under_group_device(self):
        sc = _sensor_classes()
        sensor = sc["DockhandVolumeSensor"](
            _slow_coord(), ENV_ID, ENV_NAME, BASE_URL, VOLUME
        )
        idents = sensor.device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Volumes"), idents)

    def test_image_entity_under_group_device(self):
        sc = _sensor_classes()
        sensor = sc["DockhandImageSensor"](
            _slow_coord(), ENV_ID, ENV_NAME, BASE_URL, IMAGE
        )
        idents = sensor.device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Images"), idents)


# ===========================================================================
# helpers.py unit tests
# ===========================================================================


class TestComposeProjectHelper(unittest.TestCase):
    """Tests for the _compose_project() helper in helpers.py."""

    def setUp(self):
        from custom_components.dockhand.helpers import _compose_project
        self._fn = _compose_project

    def test_returns_project_name_for_compose_container(self):
        self.assertEqual(self._fn(COMPOSE_CONTAINER), "myapp")

    def test_returns_none_for_freestanding_container(self):
        self.assertIsNone(self._fn(CONTAINER))

    def test_returns_none_for_empty_labels(self):
        self.assertIsNone(self._fn({"labels": {}}))

    def test_returns_none_for_none_labels(self):
        self.assertIsNone(self._fn({"labels": None}))

    def test_returns_none_for_none_input(self):
        self.assertIsNone(self._fn(None))

    def test_returns_none_for_empty_dict(self):
        self.assertIsNone(self._fn({}))


class TestContainerHasHealthcheck(unittest.TestCase):
    """Tests for the _container_has_healthcheck() helper."""

    def setUp(self):
        from custom_components.dockhand.helpers import _container_has_healthcheck
        self._fn = _container_has_healthcheck

    def test_true_for_healthy(self):
        self.assertTrue(self._fn({"health": "healthy"}))

    def test_true_for_unhealthy(self):
        self.assertTrue(self._fn({"health": "unhealthy"}))

    def test_true_for_starting(self):
        self.assertTrue(self._fn({"health": "starting"}))

    def test_false_for_none_string(self):
        self.assertFalse(self._fn({"health": "none"}))

    def test_false_for_none_value(self):
        self.assertFalse(self._fn({"health": None}))

    def test_false_for_missing_key(self):
        self.assertFalse(self._fn({}))

    def test_false_for_unknown(self):
        self.assertFalse(self._fn({"health": "unknown"}))


if __name__ == "__main__":
    unittest.main()
