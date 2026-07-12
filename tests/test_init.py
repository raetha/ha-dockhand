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
    async_migrate_entry,
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
    slow = _make_slow_coordinator(slow_data or {"environments": {}, "schedules": []})
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
    env_dev = next((d for d in devs if ("dockhand", "env_1") in d.identifiers), None)
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
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
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
        fast_data={
            1: {
                "containers": [{"id": "c1", "name": "nginx", "labels": {}}],
                "stacks": [],
            }
        },
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
    compose = {
        "name": "web",
        "id": "abc",
        "state": "running",
        "labels": {"com.docker.compose.project": "mystack"},
    }
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [compose],
                "stacks": [{"name": "mystack"}],
                "stats": {"online": True},
            }
        },
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
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
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
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_image_deadbeef")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_live_image_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={
            "environments": {
                1: {
                    "images": [{"id": "sha256:deadbeef"}],
                    "networks": [],
                    "volumes": [],
                }
            },
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_image_deadbeef")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stale_network_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_network_netXYZ")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_removes_stale_volume_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_volume_mydata")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_stale_and_live_in_same_env(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={
            "environments": {
                1: {
                    "images": [{"id": "sha256:aabbccdd"}],
                    "networks": [],
                    "volumes": [],
                }
            },
            "schedules": [],
        },
    )
    live = _add_entity(hass, entry, f"{entry.entry_id}_1_image_aabbccdd")
    stale = _add_entity(hass, entry, f"{entry.entry_id}_1_image_deadbeef")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, live.entity_id)
    assert not _entity_exists(hass, stale.entity_id)


def test_removes_stale_update_entity(hass: HomeAssistant):
    """Container confirmed gone from an online, updateCheckEnabled
    environment — its Tier 1 update entity is stale and removed."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {
                    "name": "myenv",
                    "online": True,
                    "updateCheckEnabled": True,
                },
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_nginx")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_live_update_entity(hass: HomeAssistant):
    """Tier 1 is entirely fast-data-derived — live whenever the
    environment has updateCheckEnabled=True and the container is present,
    regardless of whether update_coordinator (Tier 2) has any data at all."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "nginx", "id": "abc", "state": "running", "labels": {}}
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True, "updateCheckEnabled": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_nginx")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_update_entity_when_update_check_disabled(hass: HomeAssistant):
    """The whole point of the fix: turning off update-check for an
    environment removes its Tier 1 update entities even though the
    container itself (and its device) still exists — unlike every other
    entity type in this integration, which only ever goes unavailable."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "nginx", "id": "abc", "state": "running", "labels": {}}
                ],
                "stacks": [],
                "stats": {
                    "name": "myenv",
                    "online": True,
                    "updateCheckEnabled": False,
                },
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_nginx")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_update_entity_when_container_missing_but_env_offline(
    hass: HomeAssistant,
):
    """An offline environment's container list is empty but that's not
    ground truth — preserved until confirmed online, same guard as every
    other entity type."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {
                    "name": "myenv",
                    "online": False,
                    "updateCheckEnabled": True,
                },
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_nginx")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


# ---------------------------------------------------------------------------
# Runtime control entity cleanup (number/select: memory/cpu/pids/restart-policy)
# ---------------------------------------------------------------------------


def test_preserves_live_runtime_control_entity(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_runtime_controls": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "nginx", "id": "abc", "state": "running", "labels": {}}
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_runtime_control_entity_when_feature_disabled(hass: HomeAssistant):
    """Turning off 'Enable runtime controls' removes the number/select
    entities even though the container (and its device) still exists —
    same pattern as update entities disappearing when updateCheckEnabled
    turns off."""
    entry = _make_entry(hass, options={"enable_runtime_controls": False})
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "nginx", "id": "abc", "state": "running", "labels": {}}
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_removes_runtime_control_entity_when_container_becomes_compose_managed(
    hass: HomeAssistant,
):
    """Runtime controls are stack-less-only — if the same container name
    starts showing a Compose project label (adopted into a stack), its
    runtime control entities are no longer valid even though the feature
    is still enabled and the container itself is still present."""
    entry = _make_entry(hass, options={"enable_runtime_controls": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "nginx",
                        "id": "abc",
                        "state": "running",
                        "labels": {"com.docker.compose.project": "myapp"},
                    }
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_runtime_control_entity_when_env_offline(hass: HomeAssistant):
    """Offline environment — container list is empty but that's not
    ground truth, so runtime control entities are preserved, same guard
    as every other fast-data-derived entity type."""
    entry = _make_entry(hass, options={"enable_runtime_controls": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"name": "myenv", "online": False},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


# ---------------------------------------------------------------------------
# Container/stack action entity cleanup (running switch + restart button,
# suppressed for system containers/stacks containing one)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Health sensor cleanup (live only for containers with a healthcheck)
# ---------------------------------------------------------------------------


def test_preserves_health_entity_when_container_has_healthcheck(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "web", "id": "abc", "labels": {}, "health": "healthy"}
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_health")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_health_entity_when_healthcheck_removed(hass: HomeAssistant):
    """An image update can drop the HEALTHCHECK instruction — the
    container device persists, but the Health sensor should disappear
    since there's nothing for it to report anymore."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "web", "id": "abc", "labels": {}, "health": "none"}
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_health")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_health_entity_when_env_offline(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"name": "myenv", "online": False},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_health")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


# ---------------------------------------------------------------------------
# Runtime control cleanup for system containers (memory/cpu/pids/restart-policy
# suppressed for system containers, same as the action entities above)
# ---------------------------------------------------------------------------


def test_preserves_runtime_control_entities_for_normal_stackless_container(
    hass: HomeAssistant,
):
    entry = _make_entry(hass, options={"enable_runtime_controls": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "web",
                        "id": "abc",
                        "labels": {},
                        "systemContainer": None,
                    }
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_memory_limit")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_runtime_control_entities_when_container_is_system(
    hass: HomeAssistant,
):
    """Runtime controls (memory/CPU/PID limits, restart policy) carry the
    same risk as the running switch/restart button on Dockhand's own
    infrastructure — an over-tight memory limit could OOM-kill Dockhand
    itself. Suppressed for system containers the same way."""
    entry = _make_entry(hass, options={"enable_runtime_controls": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "web",
                        "id": "abc",
                        "labels": {},
                        "systemContainer": "dockhand",
                    }
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_memory_limit")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_container_action_entities_for_normal_container(
    hass: HomeAssistant,
):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "web",
                        "id": "abc",
                        "state": "running",
                        "labels": {},
                        "systemContainer": None,
                    }
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    running = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_running")
    restart = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_restart")
    auto_update = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_web_auto_update"
    )
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, running.entity_id)
    assert _entity_exists(hass, restart.entity_id)
    assert _entity_exists(hass, auto_update.entity_id)


def test_removes_container_action_entities_when_container_is_system(
    hass: HomeAssistant,
):
    """A container that's now classified as a system container (image
    changed under the same name — an unusual but possible edge case)
    loses its running switch, restart button, and auto-update switch
    even though the container device itself stays."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "web",
                        "id": "abc",
                        "state": "running",
                        "labels": {},
                        "systemContainer": "dockhand",
                    }
                ],
                "stacks": [],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    running = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_running")
    restart = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_restart")
    auto_update = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_web_auto_update"
    )
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, running.entity_id)
    assert not _entity_exists(hass, restart.entity_id)
    assert not _entity_exists(hass, auto_update.entity_id)


def test_preserves_container_action_entities_when_env_offline(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"name": "myenv", "online": False},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    running = _add_entity(hass, entry, f"{entry.entry_id}_1_container_web_running")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, running.entity_id)


# ---------------------------------------------------------------------------
# Deploy button cleanup (internal stacks only, no system container)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bulk update button cleanup (conditionally present on pending updates)
# ---------------------------------------------------------------------------


def test_preserves_bulk_update_when_pending_updates_exist(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "web", "id": "id-web", "systemContainer": None}
                ],
                "stacks": [],
                "stats": {"online": True},
                "pending_update_container_ids": {"id-web"},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_bulk_update")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_bulk_update_when_no_pending_updates(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"online": True},
                "pending_update_container_ids": set(),
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_bulk_update")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_removes_bulk_update_when_only_system_containers_pending(
    hass: HomeAssistant,
):
    """Matches Dockhand's own behavior: its "Update all" button doesn't
    count system containers, so if the only pending update is Dockhand's
    own container, there's effectively nothing to bulk-update."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "dockhand",
                        "id": "id-dockhand",
                        "systemContainer": "dockhand",
                    }
                ],
                "stacks": [],
                "stats": {"online": True},
                "pending_update_container_ids": {"id-dockhand"},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_bulk_update")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_bulk_update_when_env_offline(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"online": False},
                "pending_update_container_ids": set(),
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_bulk_update")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_preserves_stack_deploy_for_internal_stack_no_system(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "web", "id": "id-web", "systemContainer": None}
                ],
                "stacks": [
                    {
                        "name": "myapp",
                        "containers": ["id-web"],
                        "sourceType": "internal",
                    }
                ],
                "stats": {"online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_deploy")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stack_deploy_when_stack_gains_system_container(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "dockhand",
                        "id": "id-dockhand",
                        "systemContainer": "dockhand",
                    }
                ],
                "stacks": [
                    {
                        "name": "myapp",
                        "containers": ["id-dockhand"],
                        "sourceType": "internal",
                    }
                ],
                "stats": {"online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_deploy")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_removes_stack_deploy_when_stack_becomes_git_tracked(hass: HomeAssistant):
    """A stack switching from internal to git-tracked (adopted into a
    git stack in Dockhand) should lose the plain Deploy button, since
    it now has its own git-specific Deploy button instead."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {"name": "web", "id": "id-web", "systemContainer": None}
                ],
                "stacks": [
                    {"name": "myapp", "containers": ["id-web"], "sourceType": "git"}
                ],
                "stats": {"online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_deploy")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_stack_deploy_cleanup_does_not_affect_git_deploy_button(hass: HomeAssistant):
    """Confirms a live git stack's Deploy button ("..._git_deploy") is
    preserved by the _GIT_STACK_SUFFIXES branch, not incorrectly caught
    by the newer stack-deploy branch below it.

    Note on what this test does and doesn't prove: Python's elif stops
    at the first matching branch, and _GIT_STACK_SUFFIXES is checked
    earlier in the chain than the stack-deploy branch — so ordering
    alone already guarantees "..._git_deploy" never reaches the
    stack-deploy branch, regardless of whether that branch's own
    "not uid.endswith('_git_deploy')" exclusion is present. That
    exclusion is still kept for defensiveness against a future reorder
    of these branches (an exact match shouldn't depend on file order to
    be correct), but this particular test can't force it to be the
    thing that matters — it was verified by temporarily removing the
    exclusion and confirming this test still passed either way, which
    is why the exclusion's value here is about not relying on order,
    not about this test catching its absence.
    """
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [{"name": "myapp"}],
                "stats": {"online": True},
            }
        },
        slow_data={
            "environments": {1: {"git_stacks": [{"id": 5, "stackName": "myapp"}]}},
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_git_deploy")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_preserves_stack_action_entities_for_normal_stack(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "web",
                        "id": "id-web",
                        "systemContainer": None,
                        "labels": {},
                    }
                ],
                "stacks": [{"name": "myapp", "containers": ["id-web"]}],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    running = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_running")
    restart = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_restart")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, running.entity_id)
    assert _entity_exists(hass, restart.entity_id)


def test_removes_stack_action_entities_when_stack_gains_system_container(
    hass: HomeAssistant,
):
    """stack['containers'] is a list of container IDs, not names —
    confirmed from Dockhand's own source. Using names here was a real
    bug that shipped: this check silently never matched anything, for
    any stack, ever."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [
                    {
                        "name": "dockhand",
                        "id": "id-dockhand",
                        "systemContainer": "dockhand",
                        "labels": {},
                    }
                ],
                "stacks": [{"name": "myapp", "containers": ["id-dockhand"]}],
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    running = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_running")
    restart = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_restart")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, running.entity_id)
    assert not _entity_exists(hass, restart.entity_id)


def test_other_container_entities_untouched_by_action_cleanup(
    hass: HomeAssistant,
):
    """A container-scoped entity that isn't a recognized runtime-control,
    action, or health suffix (e.g. the CPU usage sensor) is left alone
    by these cleanup paths — it relies on device-removal cascade
    instead, tested elsewhere."""
    entry = _make_entry(hass, options={"enable_runtime_controls": False})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_cpu_percent")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


# ---------------------------------------------------------------------------
# Git stack entity cleanup
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stack updates-available entity cleanup (feature-detected, Dockhand 1.0.37+)
# ---------------------------------------------------------------------------


def test_preserves_stack_updates_available_when_field_present(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [
                    {"name": "myapp", "updatesAvailable": True, "updateCount": 1}
                ],
                "stats": {"online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_updates_available")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stack_updates_available_when_field_absent(hass: HomeAssistant):
    """Feature detection in reverse: if a Dockhand downgrade or a stack
    that no longer reports this field means it's genuinely gone (not
    just False), the entity is removed rather than left stuck."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [{"name": "myapp"}],
                "stats": {"online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_updates_available")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_stack_updates_available_when_env_offline(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": False}}},
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_updates_available")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_preserves_live_git_stack_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={
            "environments": {
                1: {
                    "images": [],
                    "networks": [],
                    "volumes": [],
                    "git_stacks": [{"stackName": "myapp"}],
                }
            },
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_git_sync_status")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_git_stack_entity_when_no_longer_git_tracked(hass: HomeAssistant):
    """Dockhand no longer classifies this stack as git-tracked (removed
    from git_stacks) — its entities are stale even though the stack
    itself (and its device) still exists."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={
            "environments": {
                1: {"images": [], "networks": [], "volumes": [], "git_stacks": []}
            },
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_git_sync_status")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_git_stack_entity_when_slow_poll_failed(hass: HomeAssistant):
    """A failed slow-coordinator poll must not trigger cleanup — same
    guard as images/networks/volumes."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={},  # empty -> slow_valid=False
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_git_sync_status")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_git_stack_entity_when_env_deleted(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={2: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={
            "environments": {
                1: {
                    "images": [],
                    "networks": [],
                    "volumes": [],
                    "git_stacks": [{"stackName": "myapp"}],
                }
            },
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_git_sync_status")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)

    """UIDs with fewer than 3 underscore-separated parts are skipped without error."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
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
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_notanint_image_abc")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_success_stores_runtime_data(hass: HomeAssistant):
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = _make_fast_coordinator(
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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
    fast = _make_fast_coordinator(
        {
            1: {
                "stats": ENV1_STATS,
                "containers": [MOCK_CONTAINER_HEALTHY],
                "stacks": [],
            }
        }
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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
    fast = _make_fast_coordinator(
        {
            1: {
                "stats": {"name": "MyHost", "online": True},
                "containers": [container],
                "stacks": [],
            }
        }
    )
    # Capture listener callbacks so the coordinator-update path can be driven.
    listeners: list = []

    def _add_listener(cb):
        listeners.append(cb)
        return lambda: None

    fast.async_add_listener = MagicMock(side_effect=_add_listener)
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        reg = er.async_get(hass)
        uids = {
            e.unique_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)
        }
        health_uid = f"{entry.entry_id}_1_container_nginx_health"
        assert health_uid not in uids, (
            "Health sensor must not exist without a healthcheck"
        )

        # Container is recreated from an image that adds a HEALTHCHECK.
        fast.data = {
            1: {
                "stats": {"name": "MyHost", "online": True},
                "containers": [{**container, "health": "healthy"}],
                "stacks": [],
            }
        }
        for cb in listeners:
            cb()
        await hass.async_block_till_done()

        uids = {
            e.unique_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)
        }
        assert health_uid in uids, (
            f"Health sensor not created after healthcheck appeared: {uids}"
        )


async def test_same_network_id_in_two_envs_creates_both_entities(hass: HomeAssistant):
    """Identical network IDs across environments each get an entity.

    Regression test: the network known-set was keyed on the bare Docker
    network ID, so two environments pointing at the same Docker host (which
    report identical network IDs) only got an entity for the first env seen.
    """
    entry = _make_entry(hass, data={"enable_networks": True})
    network = {
        "id": "netabc123",
        "name": "bridge",
        "driver": "bridge",
        "containers": {},
    }
    fast = _make_fast_coordinator(
        {
            1: {
                "stats": {"name": "HostDirect", "online": True},
                "containers": [],
                "stacks": [],
            },
            2: {
                "stats": {"name": "HostHawser", "online": True},
                "containers": [],
                "stacks": [],
            },
        }
    )
    slow = _make_slow_coordinator(
        {
            "environments": {
                1: {
                    "env": {"id": 1, "name": "HostDirect"},
                    "images": [],
                    "networks": [network],
                    "volumes": [],
                },
                2: {
                    "env": {"id": 2, "name": "HostHawser"},
                    "images": [],
                    "networks": [network],
                    "volumes": [],
                },
            },
            "schedules": [],
        }
    )

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state == ConfigEntryState.SETUP_ERROR


async def test_legacy_entry_with_token_strips_legacy_keys(hass: HomeAssistant):
    """After reauth, legacy keys are stripped and setup proceeds normally."""
    entry = _make_entry(
        hass,
        {
            "username": "admin",
            "password": "pass",
            "session_cookie": "old",
            "api_token": "dh_new_token",
        },
    )
    fast = _make_fast_coordinator(
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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
    fast = _make_fast_coordinator(
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})
    slow.async_config_entry_first_refresh = AsyncMock(
        side_effect=UpdateFailed("slow timeout")
    )

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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
    fast = _make_fast_coordinator(
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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
    fast = _make_fast_coordinator(
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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
    fast = _make_fast_coordinator(
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    slow = _make_slow_coordinator({"environments": {}, "schedules": []})

    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
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


# ---------------------------------------------------------------------------
# async_migrate_entry: version 1 -> 2 (enable_updates -> enable_precise_updates)
# ---------------------------------------------------------------------------


async def test_migrate_entry_renames_key_in_options(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain="dockhand",
        version=1,
        data={"api_url": "http://dh.test:3000"},
        options={"enable_updates": True, "poll_interval": 60},
    )
    entry.add_to_hass(hass)
    result = await async_migrate_entry(hass, entry)
    assert result is True
    assert entry.version == 2
    assert entry.options["enable_precise_updates"] is True
    assert "enable_updates" not in entry.options
    # Untouched keys survive.
    assert entry.options["poll_interval"] == 60


async def test_migrate_entry_renames_key_in_data(hass: HomeAssistant):
    """Belt-and-suspenders: this option has only ever been set via the
    options flow in every released version, never entry.data — but the
    migration checks data too in case that ever changes."""
    entry = MockConfigEntry(
        domain="dockhand",
        version=1,
        data={"api_url": "http://dh.test:3000", "enable_updates": True},
        options={},
    )
    entry.add_to_hass(hass)
    await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.data["enable_precise_updates"] is True
    assert "enable_updates" not in entry.data


async def test_migrate_entry_no_op_when_key_absent(hass: HomeAssistant):
    """A fresh install (or one that never touched this option) has
    nothing to rename — just bump the version, no crash."""
    entry = MockConfigEntry(
        domain="dockhand",
        version=1,
        data={"api_url": "http://dh.test:3000"},
        options={"poll_interval": 60},
    )
    entry.add_to_hass(hass)
    result = await async_migrate_entry(hass, entry)
    assert result is True
    assert entry.version == 2
    assert entry.options == {"poll_interval": 60}


async def test_migrate_entry_already_current_version_is_no_op(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain="dockhand",
        version=2,
        data={"api_url": "http://dh.test:3000"},
        options={"enable_precise_updates": True},
    )
    entry.add_to_hass(hass)
    result = await async_migrate_entry(hass, entry)
    assert result is True
    assert entry.version == 2
    assert entry.options["enable_precise_updates"] is True


# ---------------------------------------------------------------------------
# Type-prefix collision regression: entities whose full unique_id starts
# with a reserved type word ("update"/"image") but aren't actually that
# type of tracked entity must never be swept up by the type dispatch.
# ---------------------------------------------------------------------------


def test_update_check_enabled_sensor_survives_cleanup_when_env_online(
    hass: HomeAssistant,
):
    """Regression test: {entry_id}_{env_id}_update_check_enabled was being
    incorrectly matched by the "update" (Tier 1 update entity) dispatch
    branch, since position-2 of its unique_id is "update" — same as a
    real Tier 1 update entity's uid — even though it's an ordinary
    always-on binary sensor, not a container update entity at all. It
    was getting removed on every online poll, since it never appears in
    update_uids (which only contains real container names)."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"name": "myenv", "online": True, "updateCheckEnabled": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_check_enabled")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_image_prune_enabled_sensor_survives_cleanup_when_env_online(
    hass: HomeAssistant,
):
    """Same class of bug as update_check_enabled above, but for the
    "image" (Dockhand image entity) dispatch branch — {entry_id}_{env_id}_
    image_prune_enabled's position-2 token is "image", same as a real
    image entity's uid, even though it's an ordinary always-on binary
    sensor, not an image entity."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_image_prune_enabled")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_update_check_enabled_sensor_untouched_regardless_of_fast_data(
    hass: HomeAssistant,
):
    """The exclusion skips the type-dispatch entirely for this uid — it
    relies purely on device-removal cascade, like every other ordinary
    env-level sensor, so this cleanup pass should never touch it at all,
    regardless of what fast_data says (including an env_id it doesn't
    even belong to, or no matching env at all)."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={2: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_check_enabled")
    _cleanup_stale_registry(hass, entry)  # should not raise
    assert _entity_exists(hass, ent.entity_id)


def test_type_collision_excluded_entities_removed_via_device_cascade(
    hass: HomeAssistant,
):
    """update_check_enabled/image_prune_enabled are skipped by the
    entity-registry pass's type dispatch (see
    _TYPE_COLLISION_EXCLUDED_SUFFIXES), but both live on the env hub
    device (env_{env_id}) like every other ordinary always-on env-level
    sensor — when the environment itself is deleted from Dockhand, the
    device-registry pass removes that device unconditionally, and HA's
    own device-removal cascade takes every entity on it, including
    these two. No separate tracking needed, and no new orphaning risk
    from excluding them from the entity-registry pass."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={2: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev_registry = dr.async_get(hass)
    device = dev_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("dockhand", "env_1")},
        name="myenv",
    )
    ent_registry = er.async_get(hass)
    update_check = ent_registry.async_get_or_create(
        "binary_sensor",
        "dockhand",
        f"{entry.entry_id}_1_update_check_enabled",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="myenv_update_checks",
    )
    image_prune = ent_registry.async_get_or_create(
        "binary_sensor",
        "dockhand",
        f"{entry.entry_id}_1_image_prune_enabled",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="myenv_image_pruning",
    )
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, update_check.entity_id)
    assert not _entity_exists(hass, image_prune.entity_id)
