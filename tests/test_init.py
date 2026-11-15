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

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
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

from .conftest import (
    config_entry,
    container,
    fast_coordinator,
    patch_setup,
    stack,
    slow_coordinator,
    update_coordinator,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

ENV1_STATS = {"name": "MyHost"}
CONTAINER_FREE = container("nginx", id="c1")
CONTAINER_COMPOSE = container("web", stack="myapp", id="c2")
STACK1 = stack("myapp", CONTAINER_COMPOSE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(hass: HomeAssistant, data=None, options=None) -> MockConfigEntry:
    """An entry with the optional platforms off. Settings in `data` are
    filed under entry.options, where they really live: `data` only keeps
    the connection details."""
    from custom_components.dockhand.const import OPTION_KEYS

    d = {"api_url": "http://dh.test:3000", "api_token": "dh_test_token"}
    opts = {
        "enable_schedules": False,
        "enable_images": False,
        "enable_volumes": False,
        "enable_networks": False,
    }
    for key, value in (data or {}).items():
        (opts if key in OPTION_KEYS else d)[key] = value
    opts.update(options or {})
    return config_entry(hass, data=d, options=opts)


def _make_runtime_data(fast_data, slow_data, update_data=None) -> MagicMock:
    """Runtime data whose fast coordinator holds these environments
    (`fast_data`, by ID), and whose slow coordinator holds `slow_data` (a
    first poll that failed when empty)."""
    rd = MagicMock()
    rd.fast_coordinator = fast_coordinator(fast_data)
    rd.slow_coordinator = slow_coordinator(
        attrs={"last_update_success": bool(slow_data)}
    )
    rd.slow_coordinator.data = slow_data
    rd.update_coordinator = None
    if update_data is not None:
        rd.update_coordinator = update_coordinator()
        rd.update_coordinator.data = update_data
    return rd


def _run_register(hass, fast_data, slow_data=None, config_overrides=None):
    entry = _make_entry(hass, data=config_overrides)
    fast = fast_coordinator(fast_data)
    slow = slow_coordinator(**(slow_data or {}))
    _register_devices(
        hass, entry, fast, slow, dict(entry.options), "http://dh.test:3000"
    )
    return entry


def _identifiers(hass, entry):
    devs = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return {next(iter(d.identifiers))[1] for d in devs}


def _add_device(hass, entry, identifier) -> dr.DeviceEntry:
    reg = dr.async_get(hass)
    return reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("dockhand", identifier)},
        name=identifier,
    )


def _add_entity(hass, entry, unique_id, domain="sensor") -> er.RegistryEntry:
    reg = er.async_get(hass)
    return reg.async_get_or_create(
        domain=domain,
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
    assert f"{entry.entry_id}_env_1" in _identifiers(hass, entry)


def test_env_hub_uses_stats_name(hass: HomeAssistant):
    entry = _run_register(
        hass, {1: {"stats": {"name": "MyHost"}, "containers": [], "stacks": []}}
    )
    devs = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    env_dev = next(
        (d for d in devs if ("dockhand", f"{entry.entry_id}_env_1") in d.identifiers),
        None,
    )
    assert env_dev is not None
    assert env_dev.name == "MyHost"


def test_containers_group_created_for_freestanding(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [CONTAINER_FREE], "stacks": []}},
    )
    assert f"{entry.entry_id}_env_1_Containers" in _identifiers(hass, entry)


def test_containers_group_not_created_compose_only(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [CONTAINER_COMPOSE], "stacks": []}},
    )
    assert f"{entry.entry_id}_env_1_Containers" not in _identifiers(hass, entry)


def test_stacks_group_created_when_stacks_exist(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": [STACK1]}},
    )
    assert f"{entry.entry_id}_env_1_Stacks" in _identifiers(hass, entry)


def test_stacks_group_not_created_when_empty(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
    )
    assert f"{entry.entry_id}_env_1_Stacks" not in _identifiers(hass, entry)


def test_networks_group_when_enabled_and_data(hass: HomeAssistant):
    slow = {
        "environments": {1: {"networks": [{"id": "n1"}], "images": [], "volumes": []}},
        "schedules": [],
    }
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data=slow,
        config_overrides={"enable_networks": True},
    )
    assert f"{entry.entry_id}_env_1_Networks" in _identifiers(hass, entry)


def test_networks_group_not_created_when_disabled(hass: HomeAssistant):
    slow = {
        "environments": {1: {"networks": [{"id": "n1"}], "images": [], "volumes": []}},
        "schedules": [],
    }
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data=slow,
        config_overrides={"enable_networks": False},
    )
    assert f"{entry.entry_id}_env_1_Networks" not in _identifiers(hass, entry)


def test_schedules_hub_created_when_enabled(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        config_overrides={"enable_schedules": True},
    )
    assert f"{entry.entry_id}_schedules_hub" in _identifiers(hass, entry)


def test_schedules_hub_not_created_when_disabled(hass: HomeAssistant):
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        config_overrides={"enable_schedules": False},
    )
    assert f"{entry.entry_id}_schedules_hub" not in _identifiers(hass, entry)


def test_env_scoped_schedule_creates_env_group(hass: HomeAssistant):
    """A schedule with environmentId set gets its own env's Schedules group,
    not just the flat hub — see helpers.py's _schedule_group_device."""
    slow = {
        "environments": {1: {"networks": [], "images": [], "volumes": []}},
        "schedules": [
            {
                "id": 5,
                "type": "container_update",
                "name": "Update nginx",
                "environmentId": 1,
            }
        ],
    }
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data=slow,
        config_overrides={"enable_schedules": True},
    )
    ids = _identifiers(hass, entry)
    assert f"{entry.entry_id}_env_1_Schedules" in ids
    assert f"{entry.entry_id}_schedule_5_container_update" in ids


def test_env_scoped_schedule_device_parented_to_env_group(hass: HomeAssistant):
    slow = {
        "environments": {1: {"networks": [], "images": [], "volumes": []}},
        "schedules": [
            {
                "id": 5,
                "type": "container_update",
                "name": "Update nginx",
                "environmentId": 1,
            }
        ],
    }
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data=slow,
        config_overrides={"enable_schedules": True},
    )
    devs = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    sched_dev = next(
        d
        for d in devs
        if ("dockhand", f"{entry.entry_id}_schedule_5_container_update")
        in d.identifiers
    )
    group_dev = next(
        d
        for d in devs
        if ("dockhand", f"{entry.entry_id}_env_1_Schedules") in d.identifiers
    )
    assert sched_dev.via_device_id == group_dev.id


def test_global_schedule_has_no_env_group_and_stays_under_hub(hass: HomeAssistant):
    """environmentId: None (system_cleanup, repo_prune/check/verify) parents
    to schedules_hub, and no per-env Schedules group is created for it."""
    slow = {
        "environments": {1: {"networks": [], "images": [], "volumes": []}},
        "schedules": [
            {
                "id": 1,
                "type": "system_cleanup",
                "name": "Schedule execution cleanup",
                "environmentId": None,
            }
        ],
    }
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data=slow,
        config_overrides={"enable_schedules": True},
    )
    ids = _identifiers(hass, entry)
    assert f"{entry.entry_id}_env_1_Schedules" not in ids
    assert f"{entry.entry_id}_schedules_hub" in ids
    assert f"{entry.entry_id}_schedule_1_system_cleanup" in ids
    devs = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    sched_dev = next(
        d
        for d in devs
        if ("dockhand", f"{entry.entry_id}_schedule_1_system_cleanup") in d.identifiers
    )
    hub_dev = next(
        d
        for d in devs
        if ("dockhand", f"{entry.entry_id}_schedules_hub") in d.identifiers
    )
    assert sched_dev.via_device_id == hub_dev.id


def test_schedule_device_via_device_consistent_across_repeated_calls(
    hass: HomeAssistant,
):
    """_ensure_hub_devices() builds a schedule's device with the same
    _sched_device() factory as the entity (architecture.md §0), so a
    later call can't move an environment's schedule back under the
    schedules hub."""
    slow = {
        "environments": {1: {"networks": [], "images": [], "volumes": []}},
        "schedules": [
            {
                "id": 5,
                "type": "container_update",
                "name": "Update nginx",
                "environmentId": 1,
            }
        ],
    }
    entry = _run_register(
        hass,
        {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data=slow,
        config_overrides={"enable_schedules": True},
    )
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow_coord = slow_coordinator(**slow)
    _register_devices(
        hass, entry, fast, slow_coord, dict(entry.data), "http://dh.test:3000"
    )
    devs = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    sched_dev = next(
        d
        for d in devs
        if ("dockhand", f"{entry.entry_id}_schedule_5_container_update")
        in d.identifiers
    )
    group_dev = next(
        d
        for d in devs
        if ("dockhand", f"{entry.entry_id}_env_1_Schedules") in d.identifiers
    )
    assert sched_dev.via_device_id == group_dev.id


def test_empty_fast_data_creates_no_devices(hass: HomeAssistant):
    entry = _run_register(hass, {})
    prefix = f"{entry.entry_id}_env_"
    env_ids = {i for i in _identifiers(hass, entry) if i.startswith(prefix)}
    assert env_ids == set()


def test_idempotent_second_call(hass: HomeAssistant):
    entry = _make_entry(hass)
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = slow_coordinator()
    _register_devices(
        hass, entry, fast, slow, dict(entry.options), "http://dh.test:3000"
    )
    _register_devices(
        hass, entry, fast, slow, dict(entry.options), "http://dh.test:3000"
    )
    devs = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
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
    assert f"{entry.entry_id}_stack_1_myapp" in ids
    assert f"{entry.entry_id}_stack_1_second" in ids


def test_no_stack_devices_when_no_stacks(hass: HomeAssistant):
    entry = _run_register(
        hass, {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
    )
    prefix = f"{entry.entry_id}_stack_"
    stack_devs = {i for i in _identifiers(hass, entry) if i.startswith(prefix)}
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
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_oldhash")
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
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_oldhash")
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
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_stale_stack(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_stack_1_oldapp")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_live_stack(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [{"name": "myapp"}]}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_stack_1_myapp")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_preserves_container_when_env_offline(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": False}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_oldhash")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_stale_container_when_env_online(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_oldhash")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_container_when_containers_fetch_specifically_failed(
    hass: HomeAssistant,
):
    """No containers with the environment online looks like every
    container was removed, unless fetch_failures says the fetch failed
    (coordinator.py's DockhandFastCoordinator._fetch, architecture.md
    §9): then nothing is removed."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"online": True},
                "fetch_failures": {"containers"},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_preserves_stack_when_stacks_fetch_specifically_failed(hass: HomeAssistant):
    """Same mechanism as the containers case above, for stacks."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"online": True},
                "fetch_failures": {"stacks"},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_stack_1_myapp")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_container_when_env_deleted(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={2: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_removes_env_device_when_env_gone(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={2: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_env_device_when_env_present(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1")
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
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Containers")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_removes_stacks_group_when_no_stacks(hass: HomeAssistant):
    """The Stacks group device goes once an environment's last stack is
    removed, rather than staying empty."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Stacks")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_stacks_group_when_stacks_exist(hass: HomeAssistant):
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
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Stacks")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_preserves_stacks_group_when_stacks_fetch_specifically_failed(
    hass: HomeAssistant,
):
    """Same mechanism as the individual stack device version of this test
    above — the group device needs the identical stacks_fetch_ok_env_ids
    gating, not just the individual stack devices/entities."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"online": True},
                "fetch_failures": {"stacks"},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Stacks")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_stale_schedule_device(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_schedules": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_schedule_99")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_live_schedule_device(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_schedules": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": [{"id": 5, "type": "maintenance"}]},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_schedule_5_maintenance")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_preserves_schedule_device_when_schedules_fetch_specifically_failed(
    hass: HomeAssistant,
):
    """No schedules looks like every schedule was deleted, unless
    fetch_failures says the fetch failed. The same data as
    test_removes_stale_schedule_device, except for that record: here the
    device stays."""
    entry = _make_entry(hass, data={"enable_schedules": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={
            "environments": {},
            "schedules": [],
            "fetch_failures": {"schedules"},
        },
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_schedule_99")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_preserves_image_entities_when_images_fetch_specifically_failed(
    hass: HomeAssistant,
):
    """Same mechanism as the schedules case above, for the per-environment
    resources (images/networks/volumes/git_stacks) — a specific
    environment's images fetch failing must not wipe that environment's
    existing image entities, even though the poll as a whole succeeds and
    other environments' data (or this same environment's other
    resources) may be perfectly fine."""
    entry = _make_entry(hass, data={"enable_images": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={
            "environments": {
                1: {"images": [], "fetch_failures": {"images"}},
            },
            "schedules": [],
        },
    )
    ent_registry = er.async_get(hass)
    entity_entry = ent_registry.async_get_or_create(
        "sensor",
        "dockhand",
        f"{entry.entry_id}_1_image_abc123",
        config_entry=entry,
    )
    _cleanup_stale_registry(hass, entry)
    assert ent_registry.async_get(entity_entry.entity_id) is not None


def test_disabling_schedules_removes_hub_env_group_and_child_device(
    hass: HomeAssistant,
):
    """Turning schedules off removes the hub, each environment's
    Schedules group and every schedule device: Home Assistant clears
    via_device_id on removal rather than removing children."""
    entry = _make_entry(hass, data={"enable_schedules": False})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={"environments": {1: {}}, "schedules": []},
    )
    hub = _add_device(hass, entry, f"{entry.entry_id}_schedules_hub")
    group = _add_device(hass, entry, f"{entry.entry_id}_env_1_Schedules")
    sched = _add_device(hass, entry, f"{entry.entry_id}_schedule_5_container_update")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, hub.id)
    assert not _device_exists(hass, group.id)
    assert not _device_exists(hass, sched.id)


def test_removes_empty_env_schedules_group_when_enabled(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_schedules": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={"environments": {1: {}}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Schedules")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_populated_env_schedules_group(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_schedules": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {}},
            "schedules": [
                {
                    "id": 5,
                    "type": "container_update",
                    "name": "Update nginx",
                    "environmentId": 1,
                }
            ],
        },
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Schedules")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_images_group_when_disabled(hass: HomeAssistant):
    """The Images group device goes with the option, not only its
    entities (Networks and Volumes below likewise)."""
    entry = _make_entry(hass, data={"enable_images": False})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Images")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_removes_empty_images_group_when_enabled(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_images": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Images")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_populated_images_group_when_enabled(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_images": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {
                1: {"images": [{"id": "sha256:abc"}], "networks": [], "volumes": []}
            },
            "schedules": [],
        },
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Images")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


def test_removes_networks_group_when_disabled(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_networks": False})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Networks")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_removes_volumes_group_when_disabled(hass: HomeAssistant):
    entry = _make_entry(hass, data={"enable_volumes": False})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Volumes")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, dev.id)


def test_preserves_images_group_during_slow_poll_failure(hass: HomeAssistant):
    """Two-case safety rule: a failed slow poll must never be mistaken for
    "confirmed empty" — the group device must survive."""
    entry = _make_entry(hass, data={"enable_images": True})
    rd = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    rd.slow_coordinator.last_update_success = False
    entry.runtime_data = rd
    dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Images")
    _cleanup_stale_registry(hass, entry)
    assert _device_exists(hass, dev.id)


# ---------------------------------------------------------------------------
# _cleanup_stale_registry — entity cleanup
# ---------------------------------------------------------------------------


def test_removing_images_group_device_cascades_entity_removal(hass: HomeAssistant):
    """Confirms the redundancy called out in architecture.md §2 is real and
    safe: removing a group device (here, Images, because the toggle is off)
    cascades away entities living on it synchronously, so the entity-registry
    pass below never even sees them — not "attempts and no-ops", genuinely
    already gone."""
    entry = _make_entry(hass, data={"enable_images": False})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    group_dev = _add_device(hass, entry, f"{entry.entry_id}_env_1_Images")
    image_entity = _add_entity(
        hass, entry, f"{entry.entry_id}_1_image_deadbeef", domain="sensor"
    )
    er.async_get(hass).async_update_entity(
        image_entity.entity_id, device_id=group_dev.id
    )
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, group_dev.id)
    assert not _entity_exists(hass, image_entity.entity_id)


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
    """Container confirmed gone from an online environment — its Tier 1
    update entity is stale and removed."""
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
    """Tier 1 is entirely fast-data-derived — live whenever the container
    is present, regardless of whether update_coordinator (Tier 2) has any data at all."""
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


def test_preserves_update_entity_when_scheduled_check_disabled(hass: HomeAssistant):
    """github.com/raetha/ha-dockhand/issues/42: an environment's update
    entities stay when Dockhand's scheduled update check is off for it;
    only the integration's update-entities option removes them."""
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
    assert _entity_exists(hass, ent.entity_id)


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


def test_preserves_update_entity_when_containers_fetch_specifically_failed(
    hass: HomeAssistant,
):
    """Same mechanism as
    test_preserves_container_when_containers_fetch_specifically_failed
    in this file's device-registry tests, but for the entity-registry
    pass instead — a genuinely separate code path (this uid never reaches
    device-cascade removal, since update entities live on the container's
    own device but are tracked independently). Both had to be fixed;
    this confirms the entity-level half actually is."""
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
                "fetch_failures": {"containers"},
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
    ent = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit", domain="number"
    )
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_runtime_control_entity_when_feature_disabled(hass: HomeAssistant):
    """Turning off 'Enable runtime controls' removes the number/select
    entities even though the container (and its device) still exists —
    same pattern as update entities disappearing when the update-entities
    option turns off."""
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
    ent = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit", domain="number"
    )
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
    ent = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit", domain="number"
    )
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
    ent = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit", domain="number"
    )
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
    ent = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_web_memory_limit", domain="number"
    )
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
    ent = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_web_memory_limit", domain="number"
    )
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


# ---------------------------------------------------------------------------
# Container stats entity cleanup
# ---------------------------------------------------------------------------


def test_preserves_container_stats_entity_when_option_on(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": True})
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
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_cpu_percent")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_container_stats_entity_when_option_off(hass: HomeAssistant):
    """The actual bug report: these entities weren't being cleaned up at
    all when the option was turned off — the config option only ever
    controlled future creation, cleanup had no tracking for them."""
    entry = _make_entry(hass, options={"enable_resource_stats": False})
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
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_cpu_percent")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_removes_container_stats_entity_when_container_gone(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_network_rx")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_container_stats_entity_when_env_offline(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": False}}},
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_block_write")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def _stack_stats_runtime(stacks, stack_stats=None, failures=None):
    return _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": stacks,
                "stack_stats": {} if stack_stats is None else stack_stats,
                "fetch_failures": failures or set(),
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )


def test_preserves_stack_stats_entity_when_option_on(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": True})
    entry.runtime_data = _stack_stats_runtime([{"name": "myapp", "containers": []}])
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_cpu_percent")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stack_stats_entity_when_option_off(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": False})
    entry.runtime_data = _stack_stats_runtime([{"name": "myapp", "containers": []}])
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_memory_usage")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_stack_stats_entity_when_env_offline(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": False}}},
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_block_write")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stack_stats_entity_when_dockhand_lacks_the_endpoint(
    hass: HomeAssistant,
):
    """Dockhand older than 1.0.52 (or downgraded): stack_stats is None."""
    entry = _make_entry(hass, options={"enable_resource_stats": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [{"name": "myapp", "containers": []}],
                "stack_stats": None,
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_cpu_percent")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_stack_stats_entity_when_the_fetch_failed(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": True})
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [{"name": "myapp", "containers": []}],
                "stack_stats": None,
                "fetch_failures": {"stack_stats"},
                "stats": {"name": "myenv", "online": True},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_cpu_percent")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_stack_stats_entity_when_stack_gone(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": True})
    entry.runtime_data = _stack_stats_runtime([])
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_myapp_network_rx")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_container_stats_memory_limit_collision_disambiguated_by_domain(
    hass: HomeAssistant,
):
    """The container stats memory_limit sensor and the runtime control
    memory_limit number share a unique ID suffix by design
    (_CONTAINER_STATS_SUFFIXES): the domain decides which branch handles
    each. With both options off, each is removed by its own branch."""
    entry = _make_entry(
        hass,
        options={"enable_runtime_controls": False, "enable_resource_stats": False},
    )
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
    stats_ent = _add_entity(
        hass, entry, f"{entry.entry_id}_1_container_nginx_memory_limit"
    )
    control_ent = _add_entity(
        hass,
        entry,
        f"{entry.entry_id}_1_container_nginx_memory_limit",
        domain="number",
    )
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, stats_ent.entity_id)
    assert not _entity_exists(hass, control_ent.entity_id)


def test_removes_container_stats_entity_predating_the_option(hass: HomeAssistant):
    """An entry without the stats option at all counts as off
    (DEFAULT_ENABLE_RESOURCE_STATS), so its stats entities are removed."""
    entry = _make_entry(hass)  # no options at all — key genuinely absent
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
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_memory_usage")
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


def test_keeps_bulk_update_when_nothing_is_pending(hass: HomeAssistant):
    """It stays, unavailable, rather than coming and going with updates."""
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
    assert _entity_exists(hass, ent.entity_id)


def test_removes_bulk_update_with_its_environment(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={2: {"containers": [], "stacks": [], "stats": {"online": True}}},
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


def test_removes_update_entity_when_update_entities_option_disabled(
    hass: HomeAssistant,
):
    """CONF_ENABLE_UPDATE_ENTITIES=False removes Tier 1 update entities
    even though the container still exists — the new integration-level platform gate
    added for github.com/raetha/ha-dockhand/issues/23."""
    entry = _make_entry(hass, options={"enable_update_entities": False})
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
    assert not _entity_exists(hass, ent.entity_id)


def test_preserves_update_entity_when_update_entities_option_explicitly_enabled(
    hass: HomeAssistant,
):
    entry = _make_entry(hass, options={"enable_update_entities": True})
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


def test_removes_bulk_update_when_update_entities_option_disabled(hass: HomeAssistant):
    """Tier 1's own pending-updates fetch isn't gated on this option (see
    _build_live_sets), so pending_update_container_ids can still be
    non-empty here — the bulk button's own removal must check the option
    explicitly rather than relying on that data being absent, or it would
    keep reappearing for a user who disabled update entities entirely."""
    entry = _make_entry(hass, options={"enable_update_entities": False})
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
    assert not _entity_exists(hass, ent.entity_id)


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
    """A live git stack's Deploy button ("..._git_deploy") is kept by the
    _GIT_STACK_SUFFIXES branch, not caught by the stack deploy branch.
    That branch is checked later, so this passes with or without its own
    "_git_deploy" exclusion; the exclusion is there so the result doesn't
    depend on branch order."""
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
    """stack['containers'] lists container IDs, not names, so a system
    container in it is found by ID."""
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
    action, health, or container-stats suffix (e.g. the container State
    sensor) is left alone by these cleanup paths — it relies on
    device-removal cascade instead, tested elsewhere."""
    entry = _make_entry(hass, options={"enable_runtime_controls": False})
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": [], "stats": {"online": True}}},
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_container_nginx_state")
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
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = slow_coordinator()

    with patch_setup(fast, slow):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state == ConfigEntryState.LOADED
    assert entry.runtime_data is not None
    assert entry.runtime_data.fast_coordinator is fast
    assert entry.runtime_data.slow_coordinator is slow


async def test_setup_with_healthy_container_creates_health_sensor(hass: HomeAssistant):
    """A container with a healthcheck gets a Health sensor at setup."""
    entry = _make_entry(hass)
    fast = fast_coordinator(
        {
            1: {
                "stats": ENV1_STATS,
                "containers": [
                    container(
                        "healthy-app", health="healthy", status="Up 3 hours (healthy)"
                    )
                ],
                "stacks": [],
            }
        }
    )
    slow = slow_coordinator()

    with patch_setup(fast, slow):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state == ConfigEntryState.LOADED

    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(reg, entry.entry_id)
    entity_ids = {e.entity_id for e in entities}
    # Health sensor must be present — its entity_id contains the container name
    assert any(
        "healthy_app" in entity_id and "health" in entity_id for entity_id in entity_ids
    ), f"Health sensor not found in: {entity_ids}"


async def test_container_gaining_healthcheck_adds_health_sensor(hass: HomeAssistant):
    """A container that gains a healthcheck after setup (an image update
    adding HEALTHCHECK) gets its Health sensor without a restart."""
    entry = _make_entry(hass)
    container = {
        "id": "c1",
        "name": "nginx",
        "state": "running",
        "labels": {},
        "health": None,
    }
    fast = fast_coordinator(
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
    slow = slow_coordinator()

    with patch_setup(fast, slow):
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
            "environments": {
                1: {
                    "stats": {"name": "MyHost", "online": True},
                    "containers": [{**container, "health": "healthy"}],
                    "stacks": [],
                }
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
    """Two environments on the same Docker host report the same network
    IDs, and each gets its own entity."""
    entry = _make_entry(hass, data={"enable_networks": True})
    network = {
        "id": "netabc123",
        "name": "bridge",
        "driver": "bridge",
        "containers": {},
    }
    fast = fast_coordinator(
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
    slow = slow_coordinator(
        **{
            "environments": {
                1: {
                    "images": [],
                    "networks": [network],
                    "volumes": [],
                },
                2: {
                    "images": [],
                    "networks": [network],
                    "volumes": [],
                },
            },
            "schedules": [],
        }
    )

    with patch_setup(fast, slow):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    reg = er.async_get(hass)
    uids = {e.unique_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    assert f"{entry.entry_id}_1_network_netabc123" in uids, uids
    assert f"{entry.entry_id}_2_network_netabc123" in uids, uids


async def test_fast_coordinator_failure_raises_not_ready(hass: HomeAssistant):
    """Fast coordinator failure puts entry in SETUP_RETRY state."""
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = fast_coordinator({})
    fast.async_config_entry_first_refresh = AsyncMock(
        side_effect=ConfigEntryNotReady("timeout")
    )
    slow = slow_coordinator()

    with patch_setup(fast, slow):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state == ConfigEntryState.SETUP_RETRY


async def test_legacy_entry_without_token_raises_auth_failed(hass: HomeAssistant):
    """Legacy entry without api_token raises ConfigEntryAuthFailed → SETUP_ERROR."""
    entry = config_entry(
        hass,
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
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = slow_coordinator()

    with patch_setup(fast, slow):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert "username" not in entry.data
    assert "session_cookie" not in entry.data
    assert entry.data.get("api_token") == "dh_new_token"


async def test_slow_coordinator_failure_is_non_fatal(hass: HomeAssistant):
    """Slow coordinator failure at startup is non-fatal; entry reaches LOADED."""
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = slow_coordinator()
    slow.async_config_entry_first_refresh = AsyncMock(
        side_effect=UpdateFailed("slow timeout")
    )

    with patch_setup(fast, slow):
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
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = slow_coordinator()

    with patch_setup(fast, slow):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.async_unload(entry.entry_id)
    assert result is True


async def test_unload_returns_false_when_platform_fails(hass: HomeAssistant):
    entry = _make_entry(hass, {"api_token": "dh_test_token"})
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = slow_coordinator()

    with patch_setup(fast, slow):
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
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = slow_coordinator()

    with patch_setup(fast, slow):
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
# Config entry schema: async_migrate_entry and _normalized_entry_config
# ---------------------------------------------------------------------------

CONNECTION = {"api_url": "http://dh.test:3000", "api_token": "dh_test_token"}

# Every setting a release on schema 2.2 (1.11.x) saved: current names, the
# old-name copies it kept for 1.10.x, and the polling intervals 2.0.0
# removed.
SAVED_BY_1_11 = {
    "enable_resource_stats": True,
    "enable_container_stats": True,
    "poll_interval_fast": 45,
    "poll_interval": 45,
    "poll_interval_slow": 900,
    "poll_interval_precise_updates": 3600,
    "poll_interval_updates": 3600,
    "enable_images": True,
}


def _entry(hass, version, minor_version, data, options):
    entry = config_entry(
        hass,
        version=version,
        minor_version=minor_version,
        data=data,
        options=options,
    )
    return entry


async def test_migrate_1_8_era_entry_renames_and_moves_everything(hass: HomeAssistant):
    """A 1.7.x-era entry: version 1, settings saved with the connection
    details, every option under its oldest name."""
    entry = _entry(
        hass,
        1,
        1,
        {
            **CONNECTION,
            "verify_ssl": False,
            "poll_interval": 30,
            "enable_images": True,
        },
        {"enable_updates": True, "poll_interval_updates": 3600},
    )
    assert await async_migrate_entry(hass, entry) is True
    assert (entry.version, entry.minor_version) == (2, 3)
    assert entry.data == {**CONNECTION, "verify_ssl": False}
    assert entry.options == {
        "poll_interval_fast": 30,
        "enable_images": True,
        "enable_precise_updates": True,
        "poll_interval_precise_updates": 3600,
    }


@pytest.mark.parametrize("value", [True, False])
async def test_migrate_2_1_carries_renamed_values_over(
    hass: HomeAssistant, value: bool
):
    """Both values, since an explicit False must stay a stored choice."""
    entry = _entry(
        hass,
        2,
        1,
        dict(CONNECTION),
        {
            "enable_container_stats": value,
            "poll_interval": 45,
            "poll_interval_slow": 900,
        },
    )
    assert await async_migrate_entry(hass, entry) is True
    assert (entry.version, entry.minor_version) == (2, 3)
    assert entry.options == {
        "enable_resource_stats": value,
        "poll_interval_fast": 45,
        "poll_interval_slow": 900,
    }


async def test_migrate_2_2_keeps_intervals_and_drops_old_name_copies(
    hass: HomeAssistant,
):
    """The intervals aren't read any more, but a downgrade to 1.11.x still
    reads them; the old-name copies were only for 1.10.x, which can't
    reliably load a 2.3 entry anyway."""
    entry = _entry(hass, 2, 2, dict(CONNECTION), dict(SAVED_BY_1_11))
    assert await async_migrate_entry(hass, entry) is True
    assert (entry.version, entry.minor_version) == (2, 3)
    assert entry.options == {
        "enable_resource_stats": True,
        "poll_interval_fast": 45,
        "poll_interval_slow": 900,
        "poll_interval_precise_updates": 3600,
        "enable_images": True,
    }


async def test_migrate_moves_settings_out_of_data_but_options_win(hass: HomeAssistant):
    """Settings left in entry.data by the pre-1.7.1 setup form move to
    options, except where options already has a value — options always won
    every read, so that's the value in effect."""
    entry = _entry(
        hass,
        2,
        1,
        {**CONNECTION, "enable_images": True, "enable_volumes": True},
        {"enable_images": False},
    )
    await async_migrate_entry(hass, entry)
    assert entry.data == CONNECTION
    assert entry.options == {"enable_images": False, "enable_volumes": True}


async def test_migrate_keeps_legacy_auth_keys_in_data(hass: HomeAssistant):
    """Pre-1.2.0 session keys are handled by async_setup_entry, not here."""
    entry = _entry(hass, 2, 1, {**CONNECTION, "session_cookie": "x"}, {})
    await async_migrate_entry(hass, entry)
    assert entry.data == {**CONNECTION, "session_cookie": "x"}


async def test_migrate_accepts_the_next_minor_version_unchanged(hass: HomeAssistant):
    """Downgrading from the release that bumped the schema to the next
    minor version: Home Assistant still calls this, and it must load the
    entry as-is (unknown settings just aren't read)."""
    options = {"enable_images": True, "some_future_option": True}
    entry = _entry(hass, 2, 4, dict(CONNECTION), dict(options))
    assert await async_migrate_entry(hass, entry) is True
    assert (entry.version, entry.minor_version) == (2, 4)
    assert entry.options == options


async def test_migrate_refuses_an_entry_two_minor_versions_newer(hass: HomeAssistant):
    """The release that wrote it no longer keeps the old names this one
    reads, so loading it would quietly reset those settings."""
    options = {"enable_images": True, "some_future_option": True}
    entry = _entry(hass, 2, 5, dict(CONNECTION), dict(options))
    assert await async_migrate_entry(hass, entry) is False
    assert (entry.version, entry.minor_version) == (2, 5)
    assert entry.options == options


async def test_migrate_current_entry_is_a_no_op(hass: HomeAssistant):
    options = {"enable_resource_stats": True, "enable_images": True}
    entry = _entry(hass, 2, 3, dict(CONNECTION), dict(options))
    assert await async_migrate_entry(hass, entry) is True
    assert entry.options == options


def test_normalize_prefers_an_old_name_written_after_a_downgrade():
    """After a downgrade, an older release writes the old name; on the next
    upgrade that's the newer choice, so it replaces the current name."""
    from custom_components.dockhand import _normalized_entry_config

    data, options = _normalized_entry_config(
        CONNECTION, {"enable_resource_stats": True, "enable_container_stats": False}
    )
    assert data == CONNECTION
    assert options == {"enable_resource_stats": False}


def test_normalize_leaves_a_current_entry_untouched():
    from custom_components.dockhand import _normalized_entry_config

    options = {"enable_resource_stats": True, "enable_images": True}
    assert _normalized_entry_config(CONNECTION, options) == (CONNECTION, options)


def test_normalize_moves_a_removed_setting_out_of_data_while_kept():
    """Releases before 1.7.1 saved the polling interval with the connection
    details."""
    from custom_components.dockhand import _normalized_entry_config

    data, options = _normalized_entry_config(
        {**CONNECTION, "poll_interval": 20}, {"poll_interval_slow": 900}
    )
    assert data == CONNECTION
    assert options == {"poll_interval_fast": 20, "poll_interval_slow": 900}


@pytest.mark.parametrize("schema", [(2, 4), (3, 1)])
def test_the_next_schema_version_drops_removed_settings(schema):
    from custom_components.dockhand import _normalized_entry_config

    data, options = _normalized_entry_config(
        {**CONNECTION, "poll_interval": 20},
        {"poll_interval_slow": 900, "enable_images": True},
        schema=schema,
    )
    assert data == CONNECTION
    assert options == {"enable_images": True}


def test_normalize_is_idempotent():
    from custom_components.dockhand import _normalized_entry_config

    once = _normalized_entry_config(
        {**CONNECTION, "poll_interval": 20},
        {"enable_container_stats": True, "enable_updates": False},
    )
    assert _normalized_entry_config(*once) == once


def test_renames_point_at_real_settings():
    from custom_components.dockhand.const import OPTION_KEYS, RENAMED_OPTIONS

    from custom_components.dockhand.const import REMOVED_OPTIONS

    current = set(OPTION_KEYS) | {r.name for r in REMOVED_OPTIONS}
    assert {r.new for r in RENAMED_OPTIONS} <= current
    assert not {r.old for r in RENAMED_OPTIONS} & set(OPTION_KEYS)


def test_removed_settings_are_not_settings():
    from custom_components.dockhand.const import (
        OPTION_KEYS,
        REMOVED_OPTIONS,
        removed_to_drop,
        removed_to_keep,
    )

    names = {r.name for r in REMOVED_OPTIONS}
    assert not names & set(OPTION_KEYS)
    assert removed_to_keep() == names
    assert removed_to_drop() == frozenset()
    assert removed_to_keep((2, 4)) == frozenset()
    assert removed_to_drop((2, 4)) == names


def test_no_retired_renames_left_in_the_code():
    """A rename more than one schema major old can never be used again
    (async_migrate_entry refuses such entries) — delete it from
    RENAMED_OPTIONS when this fails."""
    from custom_components.dockhand.const import RENAMED_OPTIONS, SCHEMA_VERSION

    dead = [r.old for r in RENAMED_OPTIONS if r.major < SCHEMA_VERSION - 1]
    assert dead == []


def test_rename_lifecycle_today():
    """1.11.0's rename isn't mirrored any more: schema 2.2's releases read
    the new name, and 2.1's can't load a 2.3 entry."""
    from custom_components.dockhand.const import (
        renames_to_mirror,
        renames_to_translate,
    )

    assert renames_to_translate() == {
        "enable_updates": "enable_precise_updates",
        "enable_container_stats": "enable_resource_stats",
        "poll_interval": "poll_interval_fast",
        "poll_interval_updates": "poll_interval_precise_updates",
    }
    assert renames_to_mirror() == {}


def test_rename_lifecycle_after_future_schema_versions():
    """Renames are still translated for entries upgrading from older
    releases until two majors later."""
    from custom_components.dockhand.const import (
        renames_to_mirror,
        renames_to_translate,
    )

    assert renames_to_mirror((2, 4)) == {}
    assert renames_to_mirror((3, 1)) == {}
    assert "enable_container_stats" in renames_to_translate((2, 4))
    assert "enable_container_stats" in renames_to_translate((3, 1))
    assert renames_to_translate((4, 1)) == {}


def test_a_rename_is_mirrored_only_at_its_own_schema_version():
    from custom_components.dockhand import const

    future = const.RenamedOption("enable_images", "enable_image_sensors", 2, 4)
    with patch.object(const, "RENAMED_OPTIONS", (*const.RENAMED_OPTIONS, future)):
        assert const.renames_to_mirror((2, 4)) == {
            "enable_images": "enable_image_sensors"
        }
        assert const.renames_to_mirror((2, 5)) == {}
        # A rename shipped with a new major's first minor is never mirrored:
        # no release of the previous major can load that entry.
        first = const.RenamedOption("a", "b", 3, 1)
        with patch.object(const, "RENAMED_OPTIONS", (first,)):
            assert const.renames_to_mirror((3, 1)) == {}


def test_a_mirrored_rename_is_saved_under_both_names():
    from custom_components.dockhand import _normalized_entry_config, const

    future = const.RenamedOption("enable_images", "enable_image_sensors", 2, 4)
    with (
        patch.object(const, "RENAMED_OPTIONS", (future,)),
        patch.object(const, "OPTION_KEYS", (*const.OPTION_KEYS, future.new)),
    ):
        _, options = _normalized_entry_config(
            CONNECTION, {"enable_images": True}, schema=(2, 4)
        )
    assert options == {"enable_image_sensors": True, "enable_images": True}


async def test_migrate_refuses_an_entry_more_than_one_schema_major_old(
    hass: HomeAssistant,
):
    from custom_components.dockhand import const

    entry = _entry(hass, 1, 1, dict(CONNECTION), {"enable_updates": True})
    with (
        patch.object(const, "SCHEMA_VERSION", 3),
        patch("custom_components.dockhand.SCHEMA_VERSION", 3),
    ):
        assert await async_migrate_entry(hass, entry) is False
    assert entry.version == 1
    assert entry.options == {"enable_updates": True}


async def test_setup_normalizes_an_entry_left_behind_by_a_downgrade(
    hass: HomeAssistant,
):
    """Downgrade to 1.11.x, change a setting there (it writes the old name
    too, and its intervals), upgrade again: the entry is already 2.3, so no
    migration step runs — async_setup_entry's own normalization has to pick
    the change up."""
    from custom_components.dockhand import async_setup_entry

    entry = _entry(
        hass,
        2,
        3,
        {**CONNECTION, "poll_interval": 20},
        {
            "enable_container_stats": True,
            "enable_resource_stats": False,
            "poll_interval_fast": 30,
        },
    )
    with patch(
        "custom_components.dockhand.DockhandFastCoordinator",
        side_effect=RuntimeError("stop after normalizing"),
    ):
        with pytest.raises(RuntimeError, match="stop after normalizing"):
            await async_setup_entry(hass, entry)
    assert entry.data == CONNECTION
    assert entry.options == {"enable_resource_stats": True, "poll_interval_fast": 30}


def test_config_flow_schema_version():
    """Schema changes bump the minor version only — see config_flow.py."""
    from custom_components.dockhand.config_flow import DockhandConfigFlow

    assert (DockhandConfigFlow.VERSION, DockhandConfigFlow.MINOR_VERSION) == (2, 3)


# ---------------------------------------------------------------------------
# Type-prefix collision regression: entities whose full unique_id starts
# with a reserved type word ("update"/"image") but aren't actually that
# type of tracked entity must never be swept up by the type dispatch.
# ---------------------------------------------------------------------------


def test_update_check_enabled_sensor_survives_cleanup_when_env_online(
    hass: HomeAssistant,
):
    """{entry_id}_{env_id}_update_check_enabled has "update" where a
    container update entity's unique ID does, but isn't one: cleanup
    keeps it while the environment is online."""
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
        identifiers={("dockhand", f"{entry.entry_id}_env_1")},
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


# ---------------------------------------------------------------------------
# Stats cross-validation: Hawser-online / Docker-daemon-down (issue #34)
# ---------------------------------------------------------------------------


def test_preserves_container_when_stats_total_nonzero_but_list_empty(
    hass: HomeAssistant,
):
    """Root cause of issue #34: Hawser is up and reports stats.containers.total > 0,
    but the containers API returns [] with HTTP 200 — Docker daemon temporarily
    unreachable. The coordinator sees no fetch exception, so without the cross-
    validation, env is added to containers_fetch_ok_env_ids and cleanup removes all
    container devices. 60 s later Docker recovers; entities try to re-add, producing
    'unique ID already registered' errors. Fix: skip cleanup when list is empty but
    stats.containers.total > 0."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],  # HTTP 200 empty — Docker daemon unreachable via Hawser
                "stacks": [],
                "stats": {
                    "online": True,
                    "containers": {  # Hawser stats say 3 exist
                        "total": 3,
                        "running": 2,
                    },
                },
                "unconfirmed": {"containers"},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    # Container device must survive — the empty list is not ground truth
    assert _device_exists(hass, dev.id)


def test_preserves_container_entity_when_stats_total_nonzero_but_list_empty(
    hass: HomeAssistant,
):
    """Same scenario as the device test above, but covering the entity-registry
    pass — update entities live on the container device but are tracked via
    containers_fetch_ok_env_ids independently (they're swept by entity uid set,
    not by device cascade). Both the device and any entities on it must survive."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {
                    "online": True,
                    "updateCheckEnabled": True,
                    "containers": {"total": 3, "running": 2},
                },
                "unconfirmed": {"containers"},
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_update_nginx")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_removes_container_when_stats_total_zero_and_list_empty(hass: HomeAssistant):
    """Genuine empty: stats.containers.total == 0 AND containers list is empty.
    This is a real 'no containers' environment — cleanup should proceed normally."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {
                    "online": True,
                    "containers": {"total": 0, "running": 0},
                },
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    # Stats confirm zero containers — empty list is ground truth, stale device removed
    assert not _device_exists(hass, dev.id)


def test_removes_container_when_stats_has_no_containers_key_and_list_empty(
    hass: HomeAssistant,
):
    """Stats payload without a 'containers' key — no cross-validation possible;
    fall back to the list as ground truth (same behaviour as before fix)."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [],
                "stacks": [],
                "stats": {"online": True},  # no 'containers' sub-object in stats
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    dev = _add_device(hass, entry, f"{entry.entry_id}_container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    # No stats cross-validation data available — treat list as ground truth
    assert not _device_exists(hass, dev.id)


def test_removes_container_when_list_nonempty_despite_stats_mismatch(
    hass: HomeAssistant,
):
    """If containers were actually returned (non-empty list), we trust the list
    regardless of what stats says — the list is primary. A stale container not in
    the returned list should be removed."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={
            1: {
                "containers": [{"id": "c1", "name": "nginx", "labels": {}}],
                "stacks": [],
                "stats": {
                    "online": True,
                    "containers": {
                        "total": 5
                    },  # stats says 5, but we got 1 — trust the list
                },
            }
        },
        slow_data={"environments": {}, "schedules": []},
    )
    stale = _add_device(hass, entry, f"{entry.entry_id}_container_1_oldapp")
    live = _add_device(hass, entry, f"{entry.entry_id}_container_1_nginx")
    _cleanup_stale_registry(hass, entry)
    # List was returned — trust it; stale container removed, live container kept
    assert not _device_exists(hass, stale.id)
    assert _device_exists(hass, live.id)


# ---------------------------------------------------------------------------
# async_remove_config_entry_device — deleting a device by hand
# ---------------------------------------------------------------------------


def _removal_entry(state: ConfigEntryState = ConfigEntryState.LOADED) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.state = state
    return entry


def _device(identifier: str) -> MagicMock:
    device = MagicMock()
    device.identifiers = {("dockhand", identifier)}
    return device


_LIVE = {
    "env_ids": {1},
    "containers": {"e1_container_1_web"},
    "stacks": {"e1_stack_1_media"},
    "schedules": {"e1_schedule_5_system"},
    "schedules_feature_enabled": True,
}


@pytest.mark.parametrize(
    ("identifier", "removable"),
    [
        ("e1_container_1_web", False),  # Dockhand still reports it
        ("e1_container_1_gone", True),  # not reported (offline env, failed fetch)
        ("e1_stack_1_media", False),
        ("e1_stack_1_gone", True),
        ("e1_schedule_5_system", False),
        ("e1_schedule_9_system", True),
        ("e1_schedules_hub", False),
        ("e1_env_1", False),  # a live environment and its group devices
        ("e1_env_1_Containers", False),
        ("e1_env_10", True),  # environment 10 is gone; only 1 is live
        ("e1_env_2_Stacks", True),
    ],
)
async def test_remove_config_entry_device(hass: HomeAssistant, identifier, removable):
    from custom_components.dockhand import async_remove_config_entry_device

    with patch("custom_components.dockhand._build_live_sets", return_value=_LIVE):
        result = await async_remove_config_entry_device(
            hass, _removal_entry(), _device(identifier)
        )
    assert result is removable


async def test_remove_config_entry_device_hub_once_schedules_are_off(
    hass: HomeAssistant,
):
    from custom_components.dockhand import async_remove_config_entry_device

    live = {**_LIVE, "schedules_feature_enabled": False}
    with patch("custom_components.dockhand._build_live_sets", return_value=live):
        assert await async_remove_config_entry_device(
            hass, _removal_entry(), _device("e1_schedules_hub")
        )


async def test_remove_config_entry_device_while_not_loaded(hass: HomeAssistant):
    """Nothing to compare against, and nothing would recreate it."""
    from custom_components.dockhand import async_remove_config_entry_device

    entry = _removal_entry(ConfigEntryState.NOT_LOADED)
    assert await async_remove_config_entry_device(hass, entry, _device("e1_env_1"))


# ---------------------------------------------------------------------------
# Setup: a rejected token, and the optional update coordinator
# ---------------------------------------------------------------------------


async def test_setup_with_a_rejected_token_starts_reauth(hass: HomeAssistant):
    entry = _make_entry(hass)
    fast = fast_coordinator({})
    fast.async_config_entry_first_refresh = AsyncMock(
        side_effect=ConfigEntryAuthFailed("revoked")
    )
    slow = slow_coordinator()
    with patch_setup(fast, slow):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_setup_survives_a_failed_first_precise_update_check(
    hass: HomeAssistant,
):
    """Precise update versions on, and the first registry check fails: the
    integration still loads and retries on the next interval."""
    entry = _make_entry(hass, options={"enable_precise_updates": True})
    fast = fast_coordinator({1: {"stats": ENV1_STATS, "containers": [], "stacks": []}})
    slow = slow_coordinator()
    update = update_coordinator(last_update_success=False)
    update.async_config_entry_first_refresh.side_effect = UpdateFailed(
        "registry unreachable"
    )
    with patch_setup(fast, slow, update):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.update_coordinator is update
    # The cleanup listener is attached to it too.
    update.async_add_listener.assert_called()


# ---------------------------------------------------------------------------
# _build_live_sets / _cleanup_stale_registry: unusual and deleted cases
# ---------------------------------------------------------------------------


def test_git_stack_without_a_name_is_ignored(hass: HomeAssistant):
    from custom_components.dockhand import _build_live_sets

    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"git_stacks": [{"id": 3, "stackName": ""}]}},
            "schedules": [],
        },
    )
    assert _build_live_sets(entry)["git_stack_uids"] == set()


def test_cleanup_leaves_devices_it_cannot_parse_alone(hass: HomeAssistant):
    """Identifiers from another integration or entry, or without a numeric
    environment, are never touched."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    reg = dr.async_get(hass)
    other_domain = reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("other", f"{entry.entry_id}_container_9_x")},
    )
    keep = [
        other_domain,
        _add_device(hass, entry, "someone-else_container_9_x"),
        _add_device(hass, entry, f"{entry.entry_id}_container_abc_x"),
        _add_device(hass, entry, f"{entry.entry_id}_stack_abc_x"),
        _add_device(hass, entry, f"{entry.entry_id}_env_abc"),
    ]
    _cleanup_stale_registry(hass, entry)
    for device in keep:
        assert _device_exists(hass, device.id)


def test_cleanup_skips_the_registry_while_nothing_changed(hass: HomeAssistant):
    """A poll that changes neither the live items nor the entry's devices
    and entities has nothing new to remove; one that does is checked."""
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    entry.runtime_data.cleanup_seen = None
    _cleanup_stale_registry(hass, entry)
    with patch(
        "custom_components.dockhand.dr.async_entries_for_config_entry",
        wraps=dr.async_entries_for_config_entry,
    ) as listed:
        _cleanup_stale_registry(hass, entry)
    assert listed.call_count == 1  # only to see whether anything changed
    gone = _add_device(hass, entry, f"{entry.entry_id}_stack_1_media")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, gone.id)


def test_cleanup_removes_a_deleted_environments_stack_device(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    gone = _add_device(hass, entry, f"{entry.entry_id}_stack_9_media")
    _cleanup_stale_registry(hass, entry)
    assert not _device_exists(hass, gone.id)


@pytest.mark.parametrize("kind", ["image", "network", "volume"])
def test_cleanup_removes_a_deleted_environments_resource_entities(
    hass: HomeAssistant, kind
):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_9_{kind}_abc")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


async def test_remove_config_entry_device_ignores_other_integrations_identifiers(
    hass: HomeAssistant,
):
    from custom_components.dockhand import async_remove_config_entry_device

    device = MagicMock()
    device.identifiers = {("other", "e1_env_1"), ("dockhand", "e1_container_1_gone")}
    with patch("custom_components.dockhand._build_live_sets", return_value=_LIVE):
        assert await async_remove_config_entry_device(hass, _removal_entry(), device)


def test_removes_the_binary_sensors_settings_switches_replaced(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data={1: {"containers": [], "stacks": []}},
        slow_data={
            "environments": {1: {"images": [], "networks": [], "volumes": []}},
            "schedules": [],
        },
    )
    p = f"{entry.entry_id}_1"
    retired = [
        _add_entity(hass, entry, f"{p}_{s}", domain="binary_sensor")
        for s in ("collect_activity", "update_check_enabled", "image_prune_enabled")
    ]
    kept = [
        _add_entity(hass, entry, f"{p}_scanner_enabled", domain="binary_sensor"),
        _add_entity(hass, entry, f"{p}_image_prune_enabled", domain="switch"),
        _add_entity(hass, entry, f"{p}_collect_activity", domain="switch"),
    ]
    with patch("custom_components.dockhand.async_check_retired_entities") as check:
        _cleanup_stale_registry(hass, entry)
        # Removed after Home Assistant started: the repair is checked again.
        check.assert_called_once_with(hass, entry.entry_id)
        _cleanup_stale_registry(hass, entry)
        check.assert_called_once()
    assert not any(_entity_exists(hass, e.entity_id) for e in retired)
    assert all(_entity_exists(hass, e.entity_id) for e in kept)


# ---------------------------------------------------------------------------
# Entities introduced in 2.0.0 that come and go with their environment's
# connection type or Dockhand's stack data
# ---------------------------------------------------------------------------


def _env_with(connection_type, online=True, stacks=()):
    return {
        1: {
            "containers": [],
            "stacks": list(stacks),
            "stats": {
                "name": "myenv",
                "online": online,
                "connectionType": connection_type,
            },
        }
    }


def test_hawser_last_seen_kept_for_hawser_edge(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data=_env_with("hawser-edge"),
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_hawser_last_seen")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_hawser_last_seen_removed_once_the_environment_connects_otherwise(
    hass: HomeAssistant,
):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data=_env_with("hawser-standard"),
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_hawser_last_seen")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_hawser_last_seen_kept_while_the_environment_is_offline(hass: HomeAssistant):
    entry = _make_entry(hass)
    entry.runtime_data = _make_runtime_data(
        fast_data=_env_with(None, online=False),
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_hawser_last_seen")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)


def test_stack_update_count_follows_dockhands_stack_updates(hass: HomeAssistant):
    entry = _make_entry(hass)
    with_updates = {"name": "app", "containers": [], "updatesAvailable": False}
    entry.runtime_data = _make_runtime_data(
        fast_data=_env_with("socket", stacks=[with_updates]),
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_app_update_count")
    _cleanup_stale_registry(hass, entry)
    assert _entity_exists(hass, ent.entity_id)

    entry.runtime_data = _make_runtime_data(
        fast_data=_env_with("socket", stacks=[{"name": "app", "containers": []}]),
        slow_data={"environments": {}, "schedules": []},
    )
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)


def test_stack_running_containers_removed_with_the_stats_option(hass: HomeAssistant):
    entry = _make_entry(hass, options={"enable_resource_stats": False})
    entry.runtime_data = _make_runtime_data(
        fast_data=_env_with("socket", stacks=[{"name": "app", "containers": []}]),
        slow_data={"environments": {}, "schedules": []},
    )
    ent = _add_entity(hass, entry, f"{entry.entry_id}_1_stack_app_running_containers")
    _cleanup_stale_registry(hass, entry)
    assert not _entity_exists(hass, ent.entity_id)
