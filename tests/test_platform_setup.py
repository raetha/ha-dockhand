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

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.const import DOMAIN

ENV_ID = 1
STATS = {
    "name": "local",
    "online": True,
    "connectionType": "socket",
    "updateCheckEnabled": True,
    "collectActivity": True,
    "collectMetrics": False,
    "metrics": {"cpuPercent": 5.0, "memoryPercent": 40.0},
    "containers": {"total": 5, "running": 4},
}
FREE = {"id": "c1", "name": "my-app", "state": "running", "image": "nginx:1.27"}
COMPOSE = {
    "id": "c2",
    "name": "web",
    "state": "running",
    "image": "nginx:1.27",
    "labels": {"com.docker.compose.project": "mystack"},
}
SYSTEM = {
    "id": "c3",
    "name": "dockhand",
    "state": "running",
    "image": "fnsys/dockhand:latest",
    "systemContainer": True,
}
UNNAMED = {"id": "c4", "name": "", "state": "running", "image": "busybox"}
STACKS = [
    {
        "name": "mystack",
        "status": "running",
        "sourceType": "internal",
        "containers": ["c2"],
        "updatesAvailable": 1,
    },
    {"name": "gitapp", "status": "running", "sourceType": "git", "containers": []},
    {
        "name": "infra",
        "status": "running",
        "sourceType": "external",
        "containers": ["c3"],
    },
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
            "auto_update_settings": {},
            "env_meta": {},
            "settings": {
                "update_check": {"enabled": True, "autoUpdate": False},
                "image_prune": {"enabled": True, "pruneMode": "all"},
                "disk_warning": {
                    "enabled": False,
                    "mode": "percentage",
                    "threshold": 85,
                    "thresholdGb": 20,
                },
                "scanner": "trivy",
            },
            "fetch_failures": set(),
        }
    },
    "schedules": [SCHEDULE, SCHEDULE_NO_ID, PRUNE_SCHEDULE, REPORT_SCHEDULE],
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
    ("number", "disk_warning_threshold"),
    ("binary_sensor", "stack_gitapp_git_sync_error"),
    ("switch", "stack_gitapp_git_auto_deploy"),
)


def _coordinator(data: dict, listeners: list[Callable[[], None]]) -> MagicMock:
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = True
    coord.async_config_entry_first_refresh = AsyncMock()

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
    fast = _coordinator(FAST_DATA, listeners)
    slow = _coordinator(SLOW_DATA, listeners)
    update = _coordinator(UPDATE_DATA, listeners)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"api_url": "http://dh.test:3000", "api_token": "dh_x"},
        options=OPTIONS,
        version=2,
        minor_version=2,
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)
    # Disabled by default; registered enabled up front so they get states.
    ent_reg = er.async_get(hass)
    for domain, suffix in ENABLED_UP_FRONT:
        ent_reg.async_get_or_create(
            domain, DOMAIN, f"{entry.entry_id}_{ENV_ID}_{suffix}", config_entry=entry
        )
    with (
        patch("custom_components.dockhand.async_get_clientsession"),
        patch("custom_components.dockhand.DockhandClient"),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
        patch(
            "custom_components.dockhand.DockhandUpdateCoordinator", return_value=update
        ),
    ):
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
        f"{p}_volume_mydata",
        f"{p}_container_my-app_memory_limit",
        f"{p}_container_my-app_restart_policy",
        f"{p}_container_my-app_running",
        f"{p}_stack_mystack_running",
        f"{p}_image_prune_enabled",
        f"{p}_collect_activity",
        f"{p}_collect_metrics",
        f"{p}_update_check_enabled",
        f"{p}_auto_update",
        f"{p}_disk_warning_enabled",
        f"{p}_vulnerability_scanner",
        f"{p}_prune_mode",
        f"{p}_disk_warning_mode",
        f"{p}_disk_warning_threshold",
        f"{p}_disk_warning_threshold_gb",
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
    assert {f"{p}_container_my-app_pause", f"{p}_container_my-app_resume"} <= uids
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
    assert state("switch", "disk_warning_enabled") == "off"
    assert state("select", "vulnerability_scanner") == "trivy"
    assert state("select", "prune_mode") == "all"
    assert state("select", "disk_warning_mode") == "percentage"
    assert state("number", "disk_warning_threshold") == "85.0"
    assert state("number", "disk_warning_threshold_gb") == "20.0"
    assert state("binary_sensor", "stack_gitapp_git_sync_error") == "off"
    assert state("switch", "stack_gitapp_git_auto_deploy") == "off"
