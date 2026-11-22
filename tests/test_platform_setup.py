"""Full integration setup with every optional feature on.

Runs the real async_setup_entry, so every platform builds its entities from
one environment that has a bit of everything — a stand-alone, a Compose and
a system container, an internal, a git and an untracked stack, volumes,
schedules, pending updates — and then re-runs each coordinator listener the
way a poll does, which must find everything already registered and add
nothing twice. Covers the creation paths platform-level unit tests
construct entities around rather than through.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import async_get_platforms
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.const import DOMAIN

from .conftest import (
    config_entry,
    container,
    fast_coordinator,
    patch_setup,
    slow_coordinator,
    stack,
    update_coordinator,
)

ENV_ID = 1
STATS = {
    "name": "local",
    "online": True,
    "connectionType": "socket",
    "updateCheckEnabled": True,
    "collectActivity": True,
    "collectMetrics": False,
    "updateCheckAutoUpdate": False,
    "metrics": {"cpuPercent": 5.0, "memoryPercent": 40.0},
    "containers": {"total": 5, "running": 4},
}
FREE = container("my-app", id="c1", image="nginx:1.27")
COMPOSE = container("web", stack="mystack", id="c2", image="nginx:1.27")
SYSTEM = container(
    "dockhand",
    stack="infra",
    id="c3",
    image="fnsys/dockhand:latest",
    systemContainer="dockhand",
)
UNNAMED = container("", id="c4", image="busybox")
STACKS = [
    stack("mystack", COMPOSE, updatesAvailable=True, updateCount=1),
    stack("gitapp", status="running", sourceType="git"),
    stack("infra", SYSTEM, sourceType="external"),
]
GIT_STACK = {
    "id": 42,
    "stackName": "gitapp",
    "syncStatus": "synced",
    "lastSync": "2026-07-01T12:00:00Z",
    "autoUpdate": False,
}
VOLUME = {"name": "mydata", "driver": "local", "usedBy": []}
SCHEDULE = {
    "id": 7,
    "type": "system",
    "name": "cleanup",
    "environmentId": ENV_ID,
    "nextRun": 1700100000,
    "lastExecution": {"status": "success"},
}
SCHEDULE_NO_ID = {**SCHEDULE, "id": None}
PRUNE_SCHEDULE = {**SCHEDULE, "id": 8, "type": "image_prune", "enabled": True}
REPORT_SCHEDULE = {**SCHEDULE, "id": 9, "type": "env_report", "enabled": True}

FAST_DATA = {
    "environments": {
        ENV_ID: {
            "stats": STATS,
            "containers": [FREE, COMPOSE, SYSTEM, UNNAMED],
            "stacks": STACKS,
            "container_stats": {},
            "stack_stats": {},
            "pending_update_container_ids": {"c1"},
            "pending_update_details": {},
            "fetch_failures": set(),
        }
    }
}
SLOW_DATA = {
    "environments": {
        ENV_ID: {
            "host": {"cpus": 4},
            "images": [],
            "networks": [],
            "volumes": [VOLUME],
            "runtime_config": {"my-app": {"memory": 0, "restart_policy": "no"}},
            "git_stacks": [GIT_STACK],
            # web's image never scanned: listed by Dockhand without it.
            "container_vulnerabilities": {
                "my-app": {"total": 9, "critical": 2, "high": 5, "medium": 2, "low": 0}
            },
            "auto_update_settings": {},
            "env_meta": {},
            "settings": {
                "image_prune": {"enabled": True, "pruneMode": "all"},
                "scanner": "trivy",
            },
            "fetch_failures": set(),
        }
    },
    "schedules": [SCHEDULE, SCHEDULE_NO_ID, PRUNE_SCHEDULE, REPORT_SCHEDULE],
    "scanner_default": "grype",
    "fetch_failures": set(),
}
UPDATE_DATA = {"environments": {ENV_ID: {}}}

OPTIONS = {
    "enable_schedules": True,
    "enable_images": True,
    "enable_volumes": True,
    "enable_networks": True,
    "enable_update_entities": True,
    "enable_precise_updates": True,
    "enable_runtime_controls": True,
    "enable_resource_stats": True,
}


ENABLED_UP_FRONT = (
    ("switch", "image_prune_enabled"),
    ("switch", "collect_activity"),
    ("select", "vulnerability_scanner"),
    ("binary_sensor", "stack_gitapp_git_sync_error"),
    ("switch", "stack_gitapp_git_auto_deploy"),
    ("sensor", "container_my-app_vulnerabilities_critical"),
    ("sensor", "container_my-app_vulnerabilities_low"),
    ("sensor", "container_web_vulnerabilities_high"),
)


def _listened(coord: MagicMock, listeners: list[Callable[[], None]]) -> MagicMock:
    """Keep the listeners the integration adds, so a test can run them as a
    poll would."""

    def _add_listener(callback, context=None):
        listeners.append(callback)
        return lambda: None

    coord.async_add_listener = _add_listener
    return coord


@pytest.fixture
def listeners() -> list[Callable[[], None]]:
    return []


@pytest.fixture
async def loaded_entry(hass: HomeAssistant, listeners) -> MockConfigEntry:
    fast = _listened(fast_coordinator(FAST_DATA["environments"]), listeners)
    slow = _listened(slow_coordinator(**SLOW_DATA), listeners)
    update = _listened(update_coordinator(UPDATE_DATA["environments"]), listeners)
    entry = config_entry(hass, options=OPTIONS)
    # Disabled by default; registered enabled up front so they get states.
    ent_reg = er.async_get(hass)
    for domain, suffix in ENABLED_UP_FRONT:
        ent_reg.async_get_or_create(
            domain, DOMAIN, f"{entry.entry_id}_{ENV_ID}_{suffix}", config_entry=entry
        )
    with patch_setup(fast, slow, update):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _unique_ids(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    return {
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_every_optional_entity_is_created(hass: HomeAssistant, loaded_entry):
    uids = _unique_ids(hass, loaded_entry)
    p = f"{loaded_entry.entry_id}_{ENV_ID}"
    expected = {
        f"{p}_stack_mystack_updates_available",
        f"{p}_stack_gitapp_git_sync_error",
        f"{p}_stack_gitapp_git_deploy",
        f"{p}_stack_gitapp_git_auto_deploy",
        f"{p}_stack_gitapp_git_sync_status",
        f"{p}_stack_gitapp_git_last_sync",
        f"{p}_volume_mydata_container_count",
        f"{p}_volume_mydata_size",
        f"{p}_container_my-app_memory_limit",
        f"{p}_container_my-app_restart_policy",
        f"{p}_container_my-app_running",
        f"{p}_stack_mystack_running",
        f"{p}_image_prune_enabled",
        f"{p}_collect_activity",
        f"{p}_collect_metrics",
        f"{p}_update_check_enabled",
        f"{p}_auto_update",
        f"{p}_vulnerability_scanner",
        f"{p}_prune_mode",
        f"{loaded_entry.entry_id}_instance_vulnerability_scanner",
        f"{p}_container_my-app_vulnerabilities",
        f"{p}_container_my-app_vulnerabilities_critical",
        f"{p}_container_my-app_vulnerabilities_high",
        f"{p}_container_my-app_vulnerabilities_medium",
        f"{p}_container_my-app_vulnerabilities_low",
        f"{p}_container_web_vulnerabilities_critical",
        f"{p}_container_dockhand_vulnerabilities_high",
    }
    missing = expected - uids
    assert not missing, missing
    # Compose-managed, system and unnamed containers get no runtime controls,
    # and a stack containing a system container no switch or restart button.
    ent_reg = er.async_get(hass)
    for domain, uid in (
        ("number", f"{p}_container_web_memory_limit"),
        ("number", f"{p}_container_dockhand_memory_limit"),
        ("select", f"{p}_container_dockhand_restart_policy"),
        ("switch", f"{p}_stack_infra_running"),
    ):
        assert ent_reg.async_get_entity_id(domain, DOMAIN, uid) is None, uid
    # An unnamed container (malformed data) gets no runtime controls or
    # update entity, which are keyed by name.
    for domain, uid in (
        ("number", f"{p}_container__memory_limit"),
        ("select", f"{p}_container__restart_policy"),
        ("sensor", f"{p}_container__vulnerabilities_critical"),
    ):
        assert ent_reg.async_get_entity_id(domain, DOMAIN, uid) is None, uid
    updates = [
        e
        for e in er.async_entries_for_config_entry(ent_reg, loaded_entry.entry_id)
        if e.domain == "update" and "_instance_" not in e.unique_id
    ]
    assert len(updates) == 3  # my-app, web, dockhand — not the unnamed one
    assert f"{loaded_entry.entry_id}_sched_7_system_next_run" in uids
    sched = f"{loaded_entry.entry_id}_sched"
    assert {f"{sched}_7_system_run", f"{sched}_8_image_prune_run"} <= uids
    assert f"{sched}_8_image_prune_enabled" in uids
    assert f"{sched}_7_system_enabled" not in uids  # can't be paused
    assert f"{sched}_9_env_report_run" not in uids  # can't be run on demand
    assert f"{sched}_None_system_run" not in uids
    assert f"{p}_container_my-app_pause" in uids
    assert f"{p}_container_my-app_resume" not in uids
    assert f"{p}_container_dockhand_pause" not in uids


async def test_listeners_add_nothing_twice(
    hass: HomeAssistant, loaded_entry, listeners
):
    """A poll re-runs every listener; everything is already registered."""
    before = _unique_ids(hass, loaded_entry)
    for listener in listeners:
        listener()
    await hass.async_block_till_done()
    assert _unique_ids(hass, loaded_entry) == before


async def test_git_stack_and_env_meta_entities_have_states(
    hass: HomeAssistant, loaded_entry
):
    ent_reg = er.async_get(hass)
    p = f"{loaded_entry.entry_id}_{ENV_ID}"

    def state(domain: str, suffix: str) -> str:
        entity_id = ent_reg.async_get_entity_id(domain, DOMAIN, f"{p}_{suffix}")
        return hass.states.get(entity_id).state

    assert state("switch", "image_prune_enabled") == "on"
    assert state("switch", "update_check_enabled") == "on"
    assert state("switch", "auto_update") == "off"
    assert state("select", "vulnerability_scanner") == "trivy"
    assert state("select", "prune_mode") == "all"
    assert state("binary_sensor", "stack_gitapp_git_sync_error") == "off"
    assert state("switch", "stack_gitapp_git_auto_deploy") == "off"
    assert state("sensor", "container_my-app_vulnerabilities_critical") == "2"
    assert state("sensor", "container_my-app_vulnerabilities_low") == "0"
    # Its image not scanned yet.
    assert state("sensor", "container_web_vulnerabilities_high") == "unknown"


async def test_a_1x_volume_entity_moves_to_its_volume_device(hass: HomeAssistant):
    """Upgrading from 1.x: the volume's one entity becomes its Containers
    sensor on the volume's own device, keeping its entity ID."""
    entry = config_entry(hass, options=OPTIONS)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_{ENV_ID}_volume_mydata",
        config_entry=entry,
        original_name="mydata",
        suggested_object_id="local_volumes_mydata",
    )
    with patch_setup(
        fast_coordinator(FAST_DATA["environments"]),
        slow_coordinator(**SLOW_DATA),
        update_coordinator(UPDATE_DATA["environments"]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    moved = ent_reg.async_get(old.entity_id)
    assert moved is not None
    assert moved.unique_id == f"{entry.entry_id}_{ENV_ID}_volume_mydata_container_count"
    assert moved.translation_key == "volume_containers"
    device = dr.async_get(hass).async_get(moved.device_id)
    assert device is not None
    assert (DOMAIN, f"{entry.entry_id}_volume_{ENV_ID}_mydata") in device.identifiers
    assert device.model == "Local Volume"
    assert hass.states.get(old.entity_id).state == "0"


async def test_uptime_keeps_its_state_through_clock_wobble(hass: HomeAssistant):
    """The boot time is worked out from uptime and the clock, read at
    slightly different moments, so it wobbles each poll; the state must
    change only on a reboot, or every poll writes a row to the database."""
    slow_data = copy.deepcopy(SLOW_DATA)
    host = slow_data["environments"][ENV_ID]["host"]
    host["uptime"] = 3600
    entry = config_entry(hass, options=OPTIONS)
    uid = f"{entry.entry_id}_{ENV_ID}_host_last_boot"
    # Disabled by default: registered beforehand as turned on.
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, uid, config_entry=entry, disabled_by=None
    )
    with patch_setup(
        fast_coordinator(FAST_DATA["environments"]),
        slow_coordinator(**slow_data),
        update_coordinator(UPDATE_DATA["environments"]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, uid)
    assert entity_id is not None
    entity = next(
        e
        for platform in async_get_platforms(hass, DOMAIN)
        for e in platform.entities.values()
        if e.entity_id == entity_id
    )
    first = hass.states.get(entity_id).state
    host["uptime"] = 3610.5
    entity.async_write_ha_state()
    assert hass.states.get(entity_id).state == first
    host["uptime"] = 60
    entity.async_write_ha_state()
    assert hass.states.get(entity_id).state != first


async def test_setup_clears_the_retired_poll_repair(hass: HomeAssistant):
    """Releases up to 2.1.0 raised one while Dockhand polled for events;
    one the user ignored would otherwise stay."""
    from homeassistant.helpers import issue_registry as ir

    entry = config_entry(hass, options=OPTIONS)
    issue_id = f"{entry.entry_id}_event_collection_poll"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="event_collection_poll",
    )
    ir.async_ignore_issue(hass, DOMAIN, issue_id, True)
    with patch_setup(
        fast_coordinator(FAST_DATA["environments"]),
        slow_coordinator(**SLOW_DATA),
        update_coordinator(UPDATE_DATA["environments"]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
