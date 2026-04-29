"""
Tests for entity sensor/binary_sensor/switch/button native values, attributes,
entity metadata (unique_id, category, disabled-by-default), and action calls.

Entities are tested by directly instantiating the class with a mock coordinator
and calling native_value / extra_state_attributes / is_on / async_press.
This avoids needing a full platform setup while covering the business logic.
"""
import asyncio, sys, os, unittest
from unittest.mock import AsyncMock, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT); sys.path.insert(0, TESTS)

import ha_stubs as stubs; stubs.install()
from ha_stubs import EntityCategory
DOMAIN = "dockhand"

run = asyncio.run

# Data fixtures
ENV_ID = 1
ENV_NAME = "MyHost"
BASE_URL = "http://dh.test:3000"

STATS = {
    "name": "MyHost",
    "online": True,
    "metrics": {"memoryPercent": 45.2, "memoryUsed": 4724464640, "memoryTotal": 8589934592,
                "cpuPercent": 0.235},  # sensor multiplies by 100 → 23.5
    "containers": {"total": 4, "running": 3, "stopped": 1, "paused": 0, "restarting": 0,
                   "unhealthy": 0, "pendingUpdates": 1},
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
    "containers": {
        "c1": {"name": "nginx", "ipv4Address": "172.17.0.2"},
    },
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
VOLUME_UNUSED = {
    "name": "mydata",
    "driver": "local",
    "mountpoint": "/var/lib/docker/volumes/mydata/_data",
    "scope": "local",
    "created": "2026-03-01T22:12:16-05:00",
    "labels": {},
    "usedBy": [],
}

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
    "id": "sched1",
    "name": "nightly-backup",
    "type": "system",
    "cronExpression": "0 2 * * *",
    "enabled": True,
    "environmentName": "Heimdall",
    "nextRun": 1700200000,
    "lastExecution": {
        "status": "failed",
        "triggeredBy": "schedule",
        "triggeredAt": "2023-11-16T02:00:00Z",
        "duration": 1200,
        "errorMessage": "Connection timeout",
    },
}


def _fast_coord(env_data=None):
    coord = MagicMock()
    coord.data = {ENV_ID: env_data or {
        "stats": STATS,
        "containers": [CONTAINER],
        "stacks": [STACK],
    }}
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
    return coord


def _slow_coord(env_data=None, schedules=None):
    coord = MagicMock()
    coord.data = {
        "environments": {ENV_ID: env_data or {
            "env": {"name": ENV_NAME},
            "images": [IMAGE],
            "networks": [NETWORK],
            "volumes": [VOLUME],
        }},
        "schedules": schedules if schedules is not None else [SCHEDULE],
    }
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
    return coord


# Lazy import to avoid issues with import ordering
def _sensor_classes():
    from custom_components.dockhand.sensor import (
        DockhandEnvCpuSensor,
        DockhandEnvMemPercentSensor,
        DockhandEnvContainerCountSensor,
        DockhandEnvStacksSensor,
        DockhandEnvImagesSensor,
        DockhandEnvVolumesSensor,
        DockhandEnvNetworksSensor,
        DockhandEnvContainersDiskSensor,
        DockhandEnvBuildCacheSensor,
        DockhandContainerStateSensor,
        DockhandContainerImageSensor,
        DockhandContainerHealthSensor,
        DockhandStackStatusSensor,
        DockhandStackContainerCountSensor,
        DockhandImageSensor,
        DockhandNetworkSensor,
        DockhandVolumeSensor,
        DockhandScheduleNextRunSensor,
        DockhandScheduleLastStatusSensor,
    )
    return locals()


def _bs_classes():
    from custom_components.dockhand.binary_sensor import (
        DockhandEnvOnlineSensor,
        DockhandEnvCollectActivitySensor,
        DockhandEnvCollectMetricsSensor,
        DockhandEnvScannerEnabledSensor,
        DockhandEnvUpdateCheckSensor,
        DockhandEnvAutoUpdateSensor,
        DockhandEnvImagePruneBinarySensor,
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


# ── Environment sensors ───────────────────────────────────────────────────────

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
        self.assertIn("memory_used_bytes", attrs)
        self.assertIn("memory_total_bytes", attrs)
        self.assertNotIn("memory_used_mib", attrs)
        self.assertEqual(attrs["memory_used_bytes"], 4724464640)
        self.assertEqual(attrs["memory_total_bytes"], 8589934592)

    def test_container_count_total(self):
        # Total = running + stopped + paused + restarting
        val = self.containers.native_value
        self.assertEqual(val, 4)  # 3+1+0+0

    def test_container_count_attributes(self):
        attrs = self.containers.extra_state_attributes
        self.assertEqual(attrs["running"], 3)
        self.assertEqual(attrs["stopped"], 1)
        self.assertEqual(attrs["pending_updates"], 1)

    def test_stacks_value(self):
        self.assertEqual(self.stacks.native_value, 2)  # running=2

    def test_images_count(self):
        self.assertEqual(self.images.native_value, 5)

    def test_images_attribute_raw_bytes(self):
        attrs = self.images.extra_state_attributes
        self.assertIn("total_size_bytes", attrs)
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

    def test_disk_value_mib(self):
        # containersSize = 524288000 bytes → 500.0 MiB
        self.assertAlmostEqual(self.disk.native_value, 500.0, places=1)

    def test_disk_disabled_by_default(self):
        self.assertFalse(self.disk._attr_entity_registry_enabled_default)

    def test_cache_value_mib(self):
        # buildCacheSize = 104857600 bytes → 100.0 MiB
        self.assertAlmostEqual(self.cache.native_value, 100.0, places=1)

    def test_cache_disabled_by_default(self):
        self.assertFalse(self.cache._attr_entity_registry_enabled_default)

    def test_unique_ids_are_unique(self):
        sensors = [self.cpu, self.mem, self.containers, self.stacks,
                   self.images, self.volumes, self.networks, self.disk, self.cache]
        uids = [s._attr_unique_id for s in sensors]
        self.assertEqual(len(uids), len(set(uids)))

    def test_entity_category_diagnostic(self):
        for sensor in [self.containers, self.stacks, self.images,
                       self.volumes, self.networks, self.disk, self.cache]:
            self.assertEqual(sensor._attr_entity_category, EntityCategory.DIAGNOSTIC)

    def test_has_entity_name_true(self):
        """All env sensors must set has_entity_name=True (HA naming convention)."""
        for sensor in [self.cpu, self.mem, self.containers, self.stacks,
                       self.images, self.volumes, self.networks,
                       self.disk, self.cache]:
            self.assertTrue(
                sensor._attr_has_entity_name,
                f"{type(sensor).__name__} must have _attr_has_entity_name = True"
            )

# ── Container sensors ─────────────────────────────────────────────────────────

class TestContainerSensors(unittest.TestCase):

    def setUp(self):
        sc = _sensor_classes()
        coord = _fast_coord()
        self.state = sc["DockhandContainerStateSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        self.image = sc["DockhandContainerImageSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        self.health = sc["DockhandContainerHealthSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)

    def test_state_value(self):
        self.assertEqual(self.state.native_value, "running")

    def test_image_value(self):
        self.assertEqual(self.image.native_value, "nginx:latest")

    def test_image_disabled_by_default(self):
        self.assertFalse(self.image._attr_entity_registry_enabled_default)

    def test_health_value(self):
        self.assertEqual(self.health.native_value, "healthy")

    def test_health_disabled_by_default(self):
        self.assertFalse(self.health._attr_entity_registry_enabled_default)

    def test_container_not_found_returns_none(self):
        # Point coordinator at different env
        coord = MagicMock()
        coord.data = {ENV_ID: {"stats": STATS, "containers": [], "stacks": []}}
        sc = _sensor_classes()
        state = sc["DockhandContainerStateSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        self.assertIsNone(state.native_value)

    def test_has_entity_name_true(self):
        """All container sensors must use base class has_entity_name=True."""
        for s in [self.state, self.image, self.health]:
            self.assertTrue(s._attr_has_entity_name,
                            f"{type(s).__name__} must have _attr_has_entity_name=True")

    def test_unique_ids_include_container_id(self):
        cid = CONTAINER["id"]
        self.assertIn(cid, self.state._attr_unique_id)
        self.assertIn(cid, self.image._attr_unique_id)
        self.assertIn(cid, self.health._attr_unique_id)


# ── Stack sensors ─────────────────────────────────────────────────────────────

class TestStackSensors(unittest.TestCase):

    def setUp(self):
        sc = _sensor_classes()
        coord = _fast_coord()
        self.status = sc["DockhandStackStatusSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, STACK)
        self.count = sc["DockhandStackContainerCountSensor"](
            coord, ENV_ID, ENV_NAME, BASE_URL, STACK)

    def test_status_value(self):
        self.assertEqual(self.status.native_value, "running")

    def test_container_count(self):
        self.assertEqual(self.count.native_value, 3)


# ── Slow coordinator sensors ──────────────────────────────────────────────────

class TestSlowSensors(unittest.TestCase):

    def test_image_native_value_is_tag_portion(self):
        """DockhandImageSensor native_value is the tag portion only (e.g. 'latest')."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandImageSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, IMAGE)
        self.assertEqual(sensor.native_value, "latest")

    def test_image_name_is_repo_portion(self):
        """Entity name is the repository portion only (e.g. 'nginx'), not the full tag.

        The name is stable across image pulls so dashboard/automation references
        remain valid. The unique_id uses the image hash so stale entities are
        cleaned up when the old image is pruned from Docker.
        """
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandImageSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, IMAGE)
        self.assertEqual(sensor._attr_name, "nginx")
        self.assertNotIn(":", sensor._attr_name)  # colon means full tag leaked into name

    def test_image_has_entity_name_false(self):
        """Image entities use standalone names (not prefixed by parent device)."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandImageSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, IMAGE)
        self.assertFalse(sensor._attr_has_entity_name)

    def test_image_attributes_raw_bytes(self):
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandImageSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, IMAGE)
        attrs = sensor.extra_state_attributes
        self.assertIn("size_bytes", attrs)
        self.assertNotIn("size_mib", attrs)
        self.assertEqual(attrs["size_bytes"], 104857600)

    def test_image_attributes_tags_and_containers(self):
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandImageSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, IMAGE)
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["tags"], ["nginx:latest"])
        self.assertEqual(attrs["containers_using"], 2)

    def test_image_device_is_images_group(self):
        """Image entity must live under the Images group device, not its own device."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandImageSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, IMAGE)
        # DeviceInfo is a TypedDict — identifiers is a set of (domain, id) tuples
        idents = sensor.device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Images"), idents)

    def test_network_container_count(self):
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandNetworkSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, NETWORK)
        self.assertEqual(sensor.native_value, 1)  # 1 container in NETWORK

    def test_network_attributes(self):
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandNetworkSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, NETWORK)
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["driver"], "bridge")
        self.assertEqual(attrs["subnet"], "172.17.0.0/16")
        self.assertIn("nginx", attrs["connected_containers"])

    def test_network_returns_none_when_not_found(self):
        """native_value is None (not 0) when the network has disappeared."""
        sc = _sensor_classes()
        coord = _slow_coord(env_data={"env": {}, "images": [], "networks": [], "volumes": []})
        sensor = sc["DockhandNetworkSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, NETWORK)
        self.assertIsNone(sensor.native_value)

    def test_network_unique_id_includes_env_id(self):
        """Network unique_id must include env_id so multi-env installs don't collide."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandNetworkSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, NETWORK)
        self.assertIn(str(ENV_ID), sensor._attr_unique_id)

    def test_network_entity_name_is_network_name(self):
        """Entity name is the network name — standalone, not prefixed by group device."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandNetworkSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, NETWORK)
        self.assertEqual(sensor._attr_name, NETWORK["name"])
        self.assertFalse(sensor._attr_has_entity_name)

    def test_network_device_is_networks_group(self):
        """Network entity must live under the Networks group device, not its own device."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandNetworkSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, NETWORK)
        idents = sensor.device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Networks"), idents)

    def test_volume_container_count(self):
        """DockhandVolumeSensor native_value is container count (length of usedBy)."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandVolumeSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, VOLUME)
        self.assertEqual(sensor.native_value, 1)

    def test_volume_container_count_zero_when_unused(self):
        sc = _sensor_classes()
        coord = _slow_coord(env_data={
            "env": {}, "images": [], "networks": [], "volumes": [VOLUME_UNUSED]})
        sensor = sc["DockhandVolumeSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, VOLUME_UNUSED)
        self.assertEqual(sensor.native_value, 0)

    def test_volume_attributes_include_in_use_and_containers(self):
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandVolumeSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, VOLUME)
        attrs = sensor.extra_state_attributes
        self.assertTrue(attrs["in_use"])
        self.assertEqual(attrs["containers"], ["container_abc123"])

    def test_volume_attributes_include_driver_scope_mountpoint(self):
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandVolumeSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, VOLUME)
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["driver"], "local")
        self.assertEqual(attrs["scope"], "local")
        self.assertIn("mountpoint", attrs)
        self.assertIn("created", attrs)

    def test_volume_not_found_returns_none(self):
        sc = _sensor_classes()
        coord = _slow_coord(env_data={"env": {}, "images": [], "networks": [], "volumes": []})
        sensor = sc["DockhandVolumeSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, VOLUME)
        self.assertIsNone(sensor.native_value)

    def test_volume_entity_name_is_volume_name(self):
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandVolumeSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, VOLUME)
        self.assertEqual(sensor._attr_name, VOLUME["name"])
        self.assertFalse(sensor._attr_has_entity_name)

    def test_volume_device_is_volumes_group(self):
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandVolumeSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, VOLUME)
        idents = sensor.device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Volumes"), idents)


    def test_restart_buttons_are_config_category(self):
        """Restart buttons must be EntityCategory.CONFIG per HA best practice."""
        btn = _button_classes()
        coord = _fast_coord()
        client = MagicMock()
        container_btn = btn["DockhandContainerRestartButton"](coord, client, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        stack_btn = btn["DockhandStackRestartButton"](coord, client, ENV_ID, ENV_NAME, BASE_URL, STACK)
        from ha_stubs import EntityCategory
        self.assertEqual(container_btn._attr_entity_category, EntityCategory.CONFIG)
        self.assertEqual(stack_btn._attr_entity_category, EntityCategory.CONFIG)


# ── Binary sensors ────────────────────────────────────────────────────────────


    # ── Schedule sensors ─────────────────────────────────────────────────

    def test_schedule_next_run_returns_datetime(self):
        """NextRun epoch is parsed into a datetime."""
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[SCHEDULE])
        sensor = sc["DockhandScheduleNextRunSensor"](coord, SCHEDULE, BASE_URL)
        val = sensor.native_value
        self.assertIsNotNone(val)

    def test_schedule_next_run_none_when_schedule_gone(self):
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[])
        sensor = sc["DockhandScheduleNextRunSensor"](coord, SCHEDULE, BASE_URL)
        self.assertIsNone(sensor.native_value)

    def test_schedule_next_run_attributes(self):
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[SCHEDULE])
        sensor = sc["DockhandScheduleNextRunSensor"](coord, SCHEDULE, BASE_URL)
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["cron_expression"], "0 2 * * *")
        self.assertTrue(attrs["enabled"])
        self.assertEqual(attrs["schedule_type"], "system")

    def test_schedule_last_status_success(self):
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[SCHEDULE])
        sensor = sc["DockhandScheduleLastStatusSensor"](coord, SCHEDULE, BASE_URL)
        self.assertEqual(sensor.native_value, "success")

    def test_schedule_last_status_failed(self):
        """Failed status is returned exactly — enables idiomatic state trigger automations."""
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[SCHEDULE_FAILED])
        sensor = sc["DockhandScheduleLastStatusSensor"](coord, SCHEDULE_FAILED, BASE_URL)
        self.assertEqual(sensor.native_value, "failed")

    def test_schedule_last_status_attributes_include_error(self):
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[SCHEDULE_FAILED])
        sensor = sc["DockhandScheduleLastStatusSensor"](coord, SCHEDULE_FAILED, BASE_URL)
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["error_message"], "Connection timeout")
        self.assertIn("triggered_at", attrs)
        self.assertIn("duration_ms", attrs)

    def test_schedule_last_status_none_when_no_last_execution(self):
        sc = _sensor_classes()
        sched_no_exec = {**SCHEDULE, "lastExecution": None}
        coord = _slow_coord(schedules=[sched_no_exec])
        sensor = sc["DockhandScheduleLastStatusSensor"](coord, sched_no_exec, BASE_URL)
        self.assertIsNone(sensor.native_value)

    def test_schedule_sensors_share_device(self):
        """Both schedule sensors must use the same device identifier."""
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[SCHEDULE])
        next_run = sc["DockhandScheduleNextRunSensor"](coord, SCHEDULE, BASE_URL)
        last_status = sc["DockhandScheduleLastStatusSensor"](coord, SCHEDULE, BASE_URL)
        self.assertEqual(
            next_run.device_info.get("identifiers"),
            last_status.device_info.get("identifiers"),
        )

    def test_schedule_device_is_child_of_hub(self):
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[SCHEDULE])
        sensor = sc["DockhandScheduleNextRunSensor"](coord, SCHEDULE, BASE_URL)
        via = sensor.device_info.get("via_device")
        self.assertEqual(via, ("dockhand", "schedules_hub"))

    def test_schedule_last_status_is_diagnostic(self):
        from ha_stubs import EntityCategory
        sc = _sensor_classes()
        coord = _slow_coord(schedules=[SCHEDULE])
        sensor = sc["DockhandScheduleLastStatusSensor"](coord, SCHEDULE, BASE_URL)
        self.assertEqual(sensor._attr_entity_category, EntityCategory.DIAGNOSTIC)


    def test_activity_events_total(self):
        """DockhandEnvActivityEventsSensor returns the total event count."""
        coord = _fast_coord(env_data={
            "stats": {**STATS, "events": {"total": 42, "today": 7}},
            "containers": [], "stacks": [],
        })
        from custom_components.dockhand.sensor import DockhandEnvActivityEventsSensor
        sensor = DockhandEnvActivityEventsSensor(coord, ENV_ID, ENV_NAME, BASE_URL)
        self.assertEqual(sensor.native_value, 42)
        self.assertEqual(sensor.extra_state_attributes["today"], 7)

    def test_activity_events_disabled_by_default(self):
        coord = _fast_coord()
        from custom_components.dockhand.sensor import DockhandEnvActivityEventsSensor
        sensor = DockhandEnvActivityEventsSensor(coord, ENV_ID, ENV_NAME, BASE_URL)
        self.assertFalse(sensor._attr_entity_registry_enabled_default)

    def test_hawser_version_returns_string(self):
        coord = _slow_coord(env_data={
            "env": {"name": ENV_NAME, "hawserVersion": "1.4.2",
                    "hawserAgentName": "agent-1", "hawserAgentId": "abc",
                    "hawserLastSeen": "2024-01-01T00:00:00Z"},
            "images": [], "networks": [], "volumes": [],
        })
        from custom_components.dockhand.sensor import DockhandEnvHawserVersionSensor
        sensor = DockhandEnvHawserVersionSensor(coord, ENV_ID, ENV_NAME, BASE_URL)
        self.assertEqual(sensor.native_value, "1.4.2")
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["agent_name"], "agent-1")
        self.assertIn("last_seen", attrs)

    def test_hawser_version_none_when_absent(self):
        coord = _slow_coord(env_data={
            "env": {"name": ENV_NAME},
            "images": [], "networks": [], "volumes": [],
        })
        from custom_components.dockhand.sensor import DockhandEnvHawserVersionSensor
        sensor = DockhandEnvHawserVersionSensor(coord, ENV_ID, ENV_NAME, BASE_URL)
        self.assertIsNone(sensor.native_value)

    def test_hawser_version_disabled_by_default(self):
        from custom_components.dockhand.sensor import DockhandEnvHawserVersionSensor
        coord = _slow_coord()
        sensor = DockhandEnvHawserVersionSensor(coord, ENV_ID, ENV_NAME, BASE_URL)
        self.assertFalse(sensor._attr_entity_registry_enabled_default)

class TestBinarySensors(unittest.TestCase):

    def _make_sensor(self, cls_name, stats_override=None):
        bs = _bs_classes()
        coord = _fast_coord({
            "stats": {**STATS, **(stats_override or {})},
            "containers": [], "stacks": [],
        })
        return bs[cls_name](coord, ENV_ID, BASE_URL)

    def test_online_is_on(self):
        sensor = self._make_sensor("DockhandEnvOnlineSensor")
        self.assertTrue(sensor.is_on)  # coordinator.last_update_success=True

    def test_collect_activity_true(self):
        s = self._make_sensor("DockhandEnvCollectActivitySensor")
        self.assertTrue(s.is_on)

    def test_collect_metrics_true(self):
        s = self._make_sensor("DockhandEnvCollectMetricsSensor")
        self.assertTrue(s.is_on)

    def test_scanner_disabled(self):
        s = self._make_sensor("DockhandEnvScannerEnabledSensor")
        self.assertFalse(s.is_on)

    def test_update_checks_enabled(self):
        s = self._make_sensor("DockhandEnvUpdateCheckSensor")
        self.assertTrue(s.is_on)

    def test_auto_update_disabled(self):
        s = self._make_sensor("DockhandEnvAutoUpdateSensor")
        self.assertFalse(s.is_on)

    def test_image_prune_enabled(self):
        bs = _bs_classes()
        coord = _slow_coord(env_data={
            "env": {"name": ENV_NAME, "imagePruneEnabled": True},
            "images": [], "networks": [], "volumes": [],
        })
        s = bs["DockhandEnvImagePruneBinarySensor"](coord, ENV_ID, BASE_URL)
        self.assertTrue(s.is_on)

    def test_config_sensors_disabled_by_default(self):
        bs = _bs_classes()
        coord = _fast_coord()
        disabled = [
            "DockhandEnvCollectActivitySensor",
            "DockhandEnvCollectMetricsSensor",
            "DockhandEnvScannerEnabledSensor",
            "DockhandEnvUpdateCheckSensor",
            "DockhandEnvAutoUpdateSensor",
        ]
        for cls_name in disabled:
            s = bs[cls_name](coord, ENV_ID, BASE_URL)
            self.assertFalse(s._attr_entity_registry_enabled_default,
                             f"{cls_name} should be disabled by default")

    def test_online_sensor_not_disabled(self):
        bs = _bs_classes()
        coord = _fast_coord()
        s = bs["DockhandEnvOnlineSensor"](coord, ENV_ID, BASE_URL)
        self.assertTrue(s._attr_entity_registry_enabled_default)


    # Volume in_use is now an attribute on DockhandVolumeSensor, not a binary_sensor.
    # Tests are in TestSlowSensors (test_volume_attributes_include_in_use_and_containers).


# ── Switches ──────────────────────────────────────────────────────────────────

class TestSwitches(unittest.TestCase):

    def test_container_switch_on_when_running(self):
        sw = _switch_classes()
        coord = _fast_coord()
        switch = sw["DockhandContainerRunningSwitch"](coord, MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        self.assertTrue(switch.is_on)

    def test_container_switch_off_when_stopped(self):
        sw = _switch_classes()
        stopped = {**CONTAINER, "state": "stopped"}
        coord = _fast_coord({
            "stats": STATS, "containers": [stopped], "stacks": []})
        switch = sw["DockhandContainerRunningSwitch"](coord, MagicMock(), ENV_ID, ENV_NAME, BASE_URL, stopped)
        self.assertFalse(switch.is_on)

    def test_stack_switch_on_when_running(self):
        sw = _switch_classes()
        coord = _fast_coord()
        switch = sw["DockhandStackRunningSwitch"](coord, MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK)
        self.assertTrue(switch.is_on)

    def test_stack_switch_off_when_stopped(self):
        sw = _switch_classes()
        stopped_stack = {**STACK, "status": "stopped"}
        coord = _fast_coord({
            "stats": STATS, "containers": [], "stacks": [stopped_stack]})
        switch = sw["DockhandStackRunningSwitch"](coord, MagicMock(), ENV_ID, ENV_NAME, BASE_URL, stopped_stack)
        self.assertFalse(switch.is_on)

    def test_container_turn_on_calls_start(self):
        sw = _switch_classes()
        coord = _fast_coord()
        coord.hass = MagicMock()
        switch = sw["DockhandContainerRunningSwitch"](coord, MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        switch._client = MagicMock()
        switch._client.async_start_container = AsyncMock()
        run(switch.async_turn_on())
        switch._client.async_start_container.assert_called_once_with(ENV_ID, CONTAINER["id"])

    def test_container_turn_off_calls_stop(self):
        sw = _switch_classes()
        coord = _fast_coord()
        switch = sw["DockhandContainerRunningSwitch"](coord, MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        switch._client = MagicMock()
        switch._client.async_stop_container = AsyncMock()
        run(switch.async_turn_off())
        switch._client.async_stop_container.assert_called_once_with(ENV_ID, CONTAINER["id"])


# ── Buttons ───────────────────────────────────────────────────────────────────

class TestButtons(unittest.TestCase):

    def test_container_restart_button_calls_api(self):
        btn = _button_classes()
        coord = _fast_coord()
        button = btn["DockhandContainerRestartButton"](coord, MagicMock(), ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        button._client = MagicMock()
        button._client.async_restart_container = AsyncMock()
        run(button.async_press())
        button._client.async_restart_container.assert_called_once_with(
            ENV_ID, CONTAINER["id"])

    def test_stack_restart_button_calls_api(self):
        btn = _button_classes()
        coord = _fast_coord()
        button = btn["DockhandStackRestartButton"](coord, MagicMock(), ENV_ID, ENV_NAME, BASE_URL, STACK)
        button._client = MagicMock()
        button._client.async_restart_stack = AsyncMock()
        run(button.async_press())
        button._client.async_restart_stack.assert_called_once_with(
            ENV_ID, STACK["name"])


if __name__ == "__main__":
    unittest.main()

# ── Environment prefix in device names ────────────────────────────────────────

class TestEnvPrefixedDeviceNames(unittest.TestCase):
    """All individual resource devices should include the environment name."""

    def test_container_device_name_includes_env(self):
        sc = _sensor_classes()
        coord = _fast_coord()
        sensor = sc["DockhandContainerStateSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        name = sensor.device_info["name"]
        self.assertTrue(name.startswith(ENV_NAME), f"Expected '{ENV_NAME}' prefix, got '{name}'")
        self.assertIn(CONTAINER["name"], name)

    def test_stack_device_name_includes_env(self):
        sc = _sensor_classes()
        coord = _fast_coord()
        sensor = sc["DockhandStackStatusSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, STACK)
        name = sensor.device_info["name"]
        self.assertTrue(name.startswith(ENV_NAME), f"Expected '{ENV_NAME}' prefix, got '{name}'")
        self.assertIn(STACK["name"], name)

    def test_network_entity_lives_under_group_device(self):
        """Network entities now roll up to the Networks group device — no sub-device."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandNetworkSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, NETWORK)
        idents = sensor.device_info.get("identifiers", set())
        # Must be the group device, not a standalone network device
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Networks"), idents)
        self.assertNotIn((DOMAIN, f"network_{NETWORK['id']}"), idents)

    def test_volume_entity_lives_under_group_device(self):
        """Volume entities now roll up to the Volumes group device — no sub-device."""
        sc = _sensor_classes()
        coord = _slow_coord()
        sensor = sc["DockhandVolumeSensor"](coord, ENV_ID, ENV_NAME, BASE_URL, VOLUME)
        idents = sensor.device_info.get("identifiers", set())
        self.assertIn((DOMAIN, f"env_{ENV_ID}_Volumes"), idents)

    def test_container_switch_device_name_includes_env(self):
        btn = _switch_classes()
        coord = _fast_coord()
        client = MagicMock()
        sw = btn["DockhandContainerRunningSwitch"](coord, client, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        name = sw.device_info["name"]
        self.assertTrue(name.startswith(ENV_NAME), f"Expected '{ENV_NAME}' prefix, got '{name}'")

    def test_stack_switch_device_name_includes_env(self):
        btn = _switch_classes()
        coord = _fast_coord()
        client = MagicMock()
        sw = btn["DockhandStackRunningSwitch"](coord, client, ENV_ID, ENV_NAME, BASE_URL, STACK)
        name = sw.device_info["name"]
        self.assertTrue(name.startswith(ENV_NAME), f"Expected '{ENV_NAME}' prefix, got '{name}'")

    def test_container_button_device_name_includes_env(self):
        btn = _button_classes()
        coord = _fast_coord()
        client = MagicMock()
        b = btn["DockhandContainerRestartButton"](coord, client, ENV_ID, ENV_NAME, BASE_URL, CONTAINER)
        name = b.device_info["name"]
        self.assertTrue(name.startswith(ENV_NAME), f"Expected '{ENV_NAME}' prefix, got '{name}'")

    def test_stack_button_device_name_includes_env(self):
        btn = _button_classes()
        coord = _fast_coord()
        client = MagicMock()
        b = btn["DockhandStackRestartButton"](coord, client, ENV_ID, ENV_NAME, BASE_URL, STACK)
        name = b.device_info["name"]
        self.assertTrue(name.startswith(ENV_NAME), f"Expected '{ENV_NAME}' prefix, got '{name}'")

    def test_stack_device_helper_name_includes_env(self):
        """Regression: _stack_device() helper must produce an env-prefixed name.

        sensor.py's _ensure_fast_group_devices pre-registers stack devices via
        registry.async_get_or_create. If the name passed is bare (no env prefix),
        entity_ids for compose-managed containers parented to that stack are
        computed without the env prefix on first registration, causing collisions
        across environments and spurious 'recreate entity IDs' suggestions.
        """
        from custom_components.dockhand.helpers import _stack_device
        info = _stack_device(STACK["name"], ENV_ID, ENV_NAME, BASE_URL)
        name = info["name"]
        self.assertTrue(
            name.startswith(ENV_NAME),
            f"_stack_device name must start with env '{ENV_NAME}', got '{name}'"
        )
        self.assertIn(STACK["name"], name)
        self.assertEqual(name, f"{ENV_NAME} \u2013 {STACK['name']}")
