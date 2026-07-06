"""
Tests for async_setup_entry, _register_devices, _cleanup_stale_registry (__init__.py).

Covers:
- async_setup_entry: success path, legacy entry handling, auth failure raises
  ConfigEntryAuthFailed, fast coordinator failure raises ConfigEntryNotReady
- _register_devices: env hub always created, Containers/Stacks groups, optional groups
- _cleanup_stale_registry: containers, stacks, env/group devices, schedule devices,
  standalone image/network/volume/update entities
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand import (
    DockhandData,
    _cleanup_stale_registry,
    _register_devices,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

ENV1_STATS = {"name": "MyHost"}
CONTAINER_FREE = {"id": "c1", "name": "nginx", "labels": {}}
CONTAINER_COMPOSE = {
    "id": "c2",
    "name": "web",
    "labels": {"com.docker.compose.project": "myapp"},
}
STACK1 = {"name": "myapp", "status": "running"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(hass: HomeAssistant, data=None, options=None) -> MockConfigEntry:
    """Create a MockConfigEntry registered with hass."""
    d = {
        "api_url": "http://dh.test:3000",
        "api_token": "dh_test_token",
        "enable_schedules": False,
        "enable_images": False,
        "enable_volumes": False,
        "enable_networks": False,
    }
    if data:
        d.update(data)
    entry = MockConfigEntry(
        domain="dockhand",
        data=d,
        options=options or {},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)
    return entry


def _make_fast_coordinator(data) -> MagicMock:
    coord = MagicMock(spec=DockhandFastCoordinator)
    coord.data = data
    coord.async_config_entry_first_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_slow_coordinator(data) -> MagicMock:
    coord = MagicMock(spec=DockhandSlowCoordinator)
    coord.data = data
    coord.last_update_success = True
    coord.async_config_entry_first_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_runtime_data(fast_data, slow_data, update_data=None) -> MagicMock:
    rd = MagicMock()
    rd.fast_coordinator.data = fast_data
    rd.fast_coordinator.last_update_success = True
    rd.slow_coordinator.data = slow_data
    rd.slow_coordinator.last_update_success = bool(slow_data)
    if update_data is not None:
        rd.update_coordinator = MagicMock()
        rd.update_coordinator.data = update_data
        rd.update_coordinator.last_update_success = True
    else:
        rd.update_coordinator = None
    return rd


def _run_register(hass, fast_data, slow_data=None, config_overrides=None):
    entry = _make_entry(hass, data=config_overrides)
    fast = _make_fast_coordinator(fast_data)
    slow = _make_slow_coordinator(
        slow_data or {"environments": {}, "schedules": []}
    )
    _register_devices(hass, entry, fast, slow, dict(entry.data), "http://dh.test:3000")
    return entry


def _identifiers(hass, entry):
    reg = dr.async_get(hass)
    devs = reg.devices.get_devices_for_config_entry_id(entry.entry_id)
    return {next(iter(d.identifiers))[1] for d in devs}


def _add_device(hass, entry, identifier) -> dr.DeviceEntry:
    reg = dr.async_get(hass)
    return reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("dockhand", identifier)},
        name=identifier,
    )


def _add_entity(hass, entry, unique_id) -> er.RegistryEntry:
    reg = er.async_get(hass)
    return reg.async_get_or_create(
        domain="sensor",
        platform="dockhand",
        unique_id=unique_id,
        config_entry=entry,
    )


def _device_exists(hass, device_id: str) -> bool:
    return dr.async_get(hass).async_get(device_id) is not None


def _entity_exists(hass, entity_id: str) -> bool:
    return er.async_get(hass).async_get(entity_id) is not None


# ---------------------------------------------------------------------------
# _register_devices
# ---------------------------------------------------------------------------


def test_env_hub_always_created(hass: HomeAssistant):
    entry = _run_register(
        hass, {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    assert "env_1" in _identifiers(hass, entry)


def test_env_hub_uses_stats_name(hass: HomeAssistant):
    entry = _run_register(
        hass, {1: {"stats": {"name": "MyHost"}, "containers": [], "stacks": []}}
    )
    reg = dr.async_get(hass)
    devs = reg.devices.get_devices_for_config_entry_id(entry.entry_id)
    env_dev = next(
        (d for d in devs if ("dockhand", "env_1") in d.identifiers), None
    )
    assert env_dev is not None
    assert env_dev.name == "MyHost"


def test_containers_group_created_for_freestanding(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [CONTAINER_FREE], "stacks": []}},
    )
    assert "env_1_Containers" in _identifiers(hass, entry)


def test_containers_group_not_created_compose_only(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [CONTAINER_COMPOSE], "stacks": []}},
    )
    assert "env_1_Containers" not in _identifiers(hass, entry)


def test_stacks_group_created_when_stacks_exist(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": [STACK1]}},
    )
    assert "env_1_Stacks" in _identifiers(hass, entry)


def test_stacks_group_not_created_when_empty(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
    )
    assert "env_1_Stacks" not in _identifiers(hass, entry)


def test_networks_group_when_enabled_and_data(hass: HomeAssistant):
    slow = {
        "environments": {
            1: {"env": {}, "networks": [{"id": "n1"}], "images": [], "volumes": []}
        },
        "schedules": [],
    }
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data=slow,
        config_overrides={"enable_networks": True},
    )
    assert "env_1_Networks" in _identifiers(hass, entry)


def test_networks_group_not_created_when_disabled(hass: HomeAssistant):
    slow = {
        "environments": {
            1: {"env": {}, "networks": [{"id": "n1"}], "images": [], "volumes": []}
        },
        "schedules": [],
    }
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data=slow,
        config_overrides={"enable_networks": False},
    )
    assert "env_1_Networks" not in _identifiers(hass, entry)


def test_schedules_hub_created_when_enabled(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        config_overrides={"enable_schedules": True},
    )
    assert "schedules_hub" in _identifiers(hass, entry)


def test_schedules_hub_not_created_when_disabled(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        config_overrides={"enable_schedules": False},
    )
    assert "schedules_hub" not in _identifiers(hass, entry)


def test_empty_fast_data_creates_no_devices(hass: HomeAssistant):
    entry = _run_register(hass, {})
    env_ids = {i for i in _identifiers(hass, entry) if i.startswith("env_")}
    assert env_ids == set()


def test_idempotent_second_call(hass: HomeAssistant):
    entry = _make_entry(hass)
    fast = _make_fast_coordinator(
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})
    _register_devices(hass, entry, fast, slow, dict(entry.data), "http://dh.test:3000")
    _register_devices(hass, entry, fast, slow, dict(entry.data), "http://dh.test:3000")
    reg = dr.async_get(hass)
    devs = reg.devices.get_devices_for_config_entry_id(entry.entry_id)
    ids = [next(iter(d.identifiers))[1] for d in devs]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Stack device pre-registration
# ---------------------------------------------------------------------------


def test_individual_stack_device_registered(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {
            1: {
                "stats": ENV1_STATS,
                "containers": [CONTAINER_COMPOSE],
                "stacks": [STACK1, {"name": "second", "status": "running"}],
            }
        },
    )
    ids = _identifiers(hass, entry)
    assert "stack_1_myapp" in ids
    assert "stack_1_second" in ids


def test_no_stack_devices_when_no_stacks(hass: HomeAssistant):
    entry = _run_register(
        hass, {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    stack_devs = {i for i in _identifiers(hass, entry) if i.startswith("stack_")}
    assert stack_devs == set()


# ---------------------------------------------------------------------------
# _cleanup_stale_registry — device cleanup
# ---------------------------------------------------------------------------


def test_guard_empty_fast_data_skips_all_cleanup(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={},
        slow_data={"environments": {1: {"images": [], "networks": [], "volumes": []}}, "schedules": []},
    )
    dev = _add_device(hass, entry, "container_1_oldhash")
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_image_deadbeef")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stale_container(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "container_1_oldhash")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_live_container(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [{"id": "c1", "name": "nginx", "labels": {}}], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_stale_stack(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "stack_1_oldapp")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_live_stack(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [{"name": "myapp"}]}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "stack_1_myapp")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_preserves_container_when_env_offline(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": False}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "container_1_oldhash")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_stale_container_when_env_online(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "container_1_oldhash")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_removes_container_when_env_deleted(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={2: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_removes_env_device_when_env_gone(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={2: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "env_1")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_env_device_when_env_present(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "env_1")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_containers_group_when_no_freestanding(hass: HomeAssistant):
    entry = _make_entry(hass)
    compose = {"name": "web", "id": "abc", "state": "running",
               "labels": {"com.docker.compose.project": "mystack"}}
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [compose], "stacks": [{"name": "mystack"}], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "env_1_Containers")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_removes_stale_schedule_device(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_schedules": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, "schedule_99")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_live_schedule_device(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_schedules": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": [{"id": 5, "type": "maintenance"}]},
    )
    dev = _add_device(hass, entry, "schedule_5_maintenance")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


# ---------------------------------------------------------------------------
# _cleanup_stale_registry — entity cleanup
# ---------------------------------------------------------------------------


def test_guard_slow_invalid_skips_entity_cleanup(hass: HomeAssistant):
    entry = _make_entry(hass)
    rd = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {1: {"images": [], "networks": [], "volumes": []}}, "schedules": []},
    )
    rd.slow_coordinator.last_update_success = False
    entry.runtime_data = rd
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_image_deadbeef")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stale_image_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {1: {"images": [], "networks": [], "volumes": []}}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_image_deadbeef")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_live_image_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {1: {"images": [{"id": "sha256:deadbeef"}], "networks": [], "volumes": []}}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_image_deadbeef")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stale_network_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {1: {"images": [], "networks": [], "volumes": []}}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_network_netXYZ")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_removes_stale_volume_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {1: {"images": [], "networks": [], "volumes": []}}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_volume_mydata")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_stale_and_live_in_same_env(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {1: {"images": [{"id": "sha256:aabbccdd"}], "networks": [], "volumes": []}}, "schedules": []},
    )
    live = _add_entity(hass, entry, f"{entry.entry_id}_1_image_aabbccdd")
    stale = _add_entity(hass, entry, f"{entry.entry_id}_1_image_deadbeef")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, live.entity_id)
    assert not _entity_exists(hass, stale.entity_id)



def test_removes_stale_update_entity(hass: HomeAssistant):
    # update_data must be non-empty for update_valid=True; env must be online.
    # nginx is absent from update_data so it should be removed.
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"name": "myenv", "online": True}}},
        slow_data={"environments": {}, "schedules": []},
        update_data={1: {}},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_nginx")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_live_update_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [{"name": "nginx", "id": "abc", "state": "running", "labels": {}}], "stacks": [], "stats": {"name": "myenv", "online": True}}},
        slow_data={"environments": {}, "schedules": []},
        update_data={1: {"abc": {"containerName": "nginx", "currentDigest": "d1", "latestDigest": "d1"}}},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_nginx")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_uid_too_short_is_skipped_in_entity_cleanup(hass: HomeAssistant):
    """UIDs with fewer than 3 underscore-separated parts are skipped without error."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {1: {"images": [], "networks": [], "volumes": []}}, "schedules": []},
    )
    # Only 2 parts after split — guard must not raise
    ent = _add_entity(hass, entry, f"{entry.entry_id}_odduid")
    _cleanup_stale_registry(hass, entry)
    # Entity is not removed (guard skipped it)
    assert _entity_exists(hass, ent.entity_id)


def test_non_digit_env_id_is_skipped_in_entity_cleanup(hass: HomeAssistant):
    """UIDs whose second token is not a digit are skipped without error."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {1: {"images": [], "networks": [], "volumes": []}}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_notanint_image_abc")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_success_stores_runtime_data(hass: HomeAssistant):
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = _make_fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState
    assert entry.state == ConfigEntryState.LOADED
    assert entry.runtime_data is not None
    assert entry.runtime_data.fast_coordinator is fast
    assert entry.runtime_data.slow_coordinator is slow



async def test_setup_with_healthy_container_creates_health_sensor(hass: HomeAssistant):
    """Health sensor is created when a container has a healthcheck.

    Regression test for a bug where DockhandContainerHealthSensor was called
    without entry.entry_id, causing a TypeError at setup time.
    """
    from tests.conftest import MOCK_CONTAINER_HEALTHY

    entry = _make_entry(hass)
    fast = _make_fast_coordinator({
        1: {
            "stats": ENV1_STATS,
            "containers": [MOCK_CONTAINER_HEALTHY],
            "stacks": [],
        }
    })
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState
    assert entry.state == ConfigEntryState.LOADED

    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(reg, entry.entry_id)
    entity_ids = {e.entity_id for e in entities}
    # Health sensor must be present — its entity_id contains the container name
    assert any("healthy_app" in eid and "health" in eid for eid in entity_ids), (
        f"Health sensor not found in: {entity_ids}"
    )


async def test_container_gaining_healthcheck_adds_health_sensor(hass: HomeAssistant):
    """A container that gains a healthcheck after setup gets its Health sensor.

    Regression test: health sensor creation was gated behind the same
    known-key set as the other per-container sensors, so a container whose
    image update added a HEALTHCHECK never got a Health sensor until restart.
    """
    entry = _make_entry(hass)
    container = {
        "id": "c1",
        "name": "nginx",
        "state": "running",
        "labels": {},
        "health": None,
    }
    fast = _make_fast_coordinator({
        1: {"stats": {"name": "MyHost", "online": True},
            "containers": [container], "stacks": []}
    })
    # Capture listener callbacks so the coordinator-update path can be driven.
    listeners: list = []

    def _add_listener(cb):
        listeners.append(cb)
        return lambda: None

    fast.async_add_listener = MagicMock(side_effect=_add_listener)
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        reg = er.async_get(hass)
        uids = {e.unique_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
        health_uid = f"{entry.entry_id}_1_container_nginx_health"
        assert health_uid not in uids, "Health sensor must not exist without a healthcheck"

        # Container is recreated from an image that adds a HEALTHCHECK.
        fast.data = {
            1: {"stats": {"name": "MyHost", "online": True},
                "containers": [{**container, "health": "healthy"}], "stacks": []}
        }
        for cb in listeners:
            cb()
        await hass.async_block_till_done()

        uids = {e.unique_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
        assert health_uid in uids, f"Health sensor not created after healthcheck appeared: {uids}"


async def test_same_network_id_in_two_envs_creates_both_entities(hass: HomeAssistant):
    """Identical network IDs across environments each get an entity.

    Regression test: the network known-set was keyed on the bare Docker
    network ID, so two environments pointing at the same Docker host (which
    report identical network IDs) only got an entity for the first env seen.
    """
    entry = _make_entry(hass, data={"enable_networks": True})
    network = {"id": "netabc123", "name": "bridge", "driver": "bridge", "containers": {}}
    fast = _make_fast_coordinator({
        1: {"stats": {"name": "HostDirect", "online": True}, "containers": [], "stacks": []},
        2: {"stats": {"name": "HostHawser", "online": True}, "containers": [], "stacks": []},
    })
    slow = _make_slow_coordinator({
        "environments": {
            1: {"env": {"id": 1, "name": "HostDirect"}, "images": [],
                "networks": [network], "volumes": []},
            2: {"env": {"id": 2, "name": "HostHawser"}, "images": [],
                "networks": [network], "volumes": []},
        },
        "schedules": [],
    })

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    reg = er.async_get(hass)
    uids = {e.unique_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    assert f"{entry.entry_id}_1_network_netabc123" in uids, uids
    assert f"{entry.entry_id}_2_network_netabc123" in uids, uids


async def test_fast_coordinator_failure_raises_not_ready(hass: HomeAssistant):
    """Fast coordinator failure puts entry in SETUP_RETRY state."""
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = _make_fast_coordinator({})
    fast.async_config_entry_first_refresh = AsyncMock(
        side_effect=ConfigEntryNotReady("timeout")
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState
    assert entry.state == ConfigEntryState.SETUP_RETRY


async def test_legacy_entry_without_token_raises_auth_failed(hass: HomeAssistant):
    """Legacy entry without api_token raises ConfigEntryAuthFailed → SETUP_ERROR."""
    entry = MockConfigEntry(
        domain="dockhand",
        data={
            "api_url": "http://dh.test:3000",
            "username": "admin",
            "password": "pass",
            "session_cookie": "old_cookie",
            "enable_schedules": False,
            "enable_images": False,
            "enable_volumes": False,
            "enable_networks": False,
        },
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState
    assert entry.state == ConfigEntryState.SETUP_ERROR


async def test_legacy_entry_with_token_strips_legacy_keys(hass: HomeAssistant):
    """After reauth, legacy keys are stripped and setup proceeds normally."""
    entry = _make_entry(hass, {
        "username": "admin", "password": "pass",
        "session_cookie": "old", "api_token": "dh_new_token",
    })
    fast = _make_fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert "username" not in entry.data
    assert "session_cookie" not in entry.data
    assert entry.data.get("api_token") == "dh_new_token"


async def test_slow_coordinator_failure_is_non_fatal(hass: HomeAssistant):
    """Slow coordinator failure at startup is non-fatal; entry reaches LOADED."""
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = _make_fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})
    slow.async_config_entry_first_refresh = AsyncMock(
        side_effect=UpdateFailed("slow timeout")
    )

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState
    assert entry.state == ConfigEntryState.LOADED
    assert entry.runtime_data is not None


# ---------------------------------------------------------------------------
# async_unload_entry
# ---------------------------------------------------------------------------


async def test_unload_returns_true_on_success(hass: HomeAssistant):
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = _make_fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.async_unload(entry.entry_id)
    assert result is True


async def test_unload_returns_false_when_platform_fails(hass: HomeAssistant):
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = _make_fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    with patch.object(
        hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=False)
    ):
        result = await hass.config_entries.async_unload(entry.entry_id)
    assert result is False


async def test_unload_calls_correct_platforms(hass: HomeAssistant):
    from custom_components.dockhand.const import PLATFORMS

    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = _make_fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    called_with = []

    async def _capture(e, platforms):
        called_with.extend(platforms)
        return True

    with patch.object(hass.config_entries, "async_unload_platforms", new=_capture):
        await hass.config_entries.async_unload(entry.entry_id)

    assert sorted(called_with) == sorted(PLATFORMS)
    assert "diagnostics" not in called_with
