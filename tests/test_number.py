"""
Tests for runtime-control number entities (number.py).

Covers:
- async_setup_entry: gated behind CONF_ENABLE_RUNTIME_CONTROLS, only creates
  entities for stack-less containers
- native_value: reads from slow coordinator's runtime_config, unknown when
  the container hasn't been inspected yet
- Optimistic update: displayed value updates immediately on
  async_set_native_value, reset to None (defer to coordinator data) on the
  next _handle_coordinator_update
- Memory safety check: schedules a delayed revert-check only on a decrease,
  not on an increase or a set to 0 (unlimited); reverts and raises a repair
  issue if the container stopped running; does nothing if still running
- CPU limit: CPUs <-> NanoCpus conversion at the API boundary
- Pids limit: -1 passed straight through as Docker's "unlimited" sentinel
- Repair issue raised when Dockhand returns non-empty "warnings"
- container_not_found / action_failed error handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.dockhand.number import (
    DockhandContainerCpuLimitNumber,
    DockhandContainerMemoryLimitNumber,
    DockhandContainerPidsLimitNumber,
    async_setup_entry,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
)

ENV_ID = 1
ENTRY_ID = "test_entry_id_number"
ENV_NAME = "myenv"
BASE_URL = "http://dh.test:3000"
CONTAINER_NAME = "nginx"
CONTAINER_ID = "abc123"

CONTAINER_STANDALONE = {
    "id": CONTAINER_ID,
    "name": CONTAINER_NAME,
    "state": "running",
    "labels": {},
}
CONTAINER_COMPOSE = {
    "id": "def456",
    "name": "compose-web",
    "state": "running",
    "labels": {"com.docker.compose.project": "myapp"},
}


def _make_fast_coord(containers=None) -> MagicMock:
    coord = MagicMock(spec=DockhandFastCoordinator)
    coord.data = {
        ENV_ID: {
            "stats": {"name": ENV_NAME},
            "containers": containers
            if containers is not None
            else [CONTAINER_STANDALONE],
        }
    }
    coord.client = MagicMock()
    coord.client.async_update_container_runtime = AsyncMock(
        return_value={"success": True, "warnings": []}
    )
    coord.last_update_success = True
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_slow_coord(runtime_config=None) -> MagicMock:
    coord = MagicMock(spec=DockhandSlowCoordinator)
    coord.data = {
        "environments": {
            ENV_ID: {"runtime_config": runtime_config or {}},
        }
    }
    coord.last_update_success = True
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_memory_entity(runtime_config=None, containers=None):
    fast = _make_fast_coord(containers)
    slow = _make_slow_coord(runtime_config)
    entity = DockhandContainerMemoryLimitNumber(
        fast, slow, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER_NAME
    )
    entity.hass = MagicMock()
    return entity


def _make_cpu_entity(runtime_config=None, host_cpus=None):
    fast = _make_fast_coord()
    slow = _make_slow_coord(runtime_config)
    entity = DockhandContainerCpuLimitNumber(
        fast,
        slow,
        ENTRY_ID,
        ENV_ID,
        ENV_NAME,
        BASE_URL,
        CONTAINER_NAME,
        host_cpus=host_cpus,
    )
    entity.hass = MagicMock()
    return entity


def _make_pids_entity(runtime_config=None):
    fast = _make_fast_coord()
    slow = _make_slow_coord(runtime_config)
    entity = DockhandContainerPidsLimitNumber(
        fast, slow, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, CONTAINER_NAME
    )
    entity.hass = MagicMock()
    return entity


# ---------------------------------------------------------------------------
# async_setup_entry gating
# ---------------------------------------------------------------------------


async def test_setup_entry_skips_when_runtime_controls_disabled():
    entry = MagicMock()
    entry.options = {}
    entry.data = {"enable_runtime_controls": False}
    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)
    add_entities.assert_not_called()


async def test_setup_entry_creates_entities_only_for_stackless_containers():
    entry = MagicMock()
    entry.options = {"enable_runtime_controls": True}
    entry.data = {}
    entry.entry_id = ENTRY_ID
    entry.runtime_data.fast_coordinator = _make_fast_coord(
        [CONTAINER_STANDALONE, CONTAINER_COMPOSE]
    )
    entry.runtime_data.slow_coordinator = _make_slow_coord()
    entry.async_on_unload = MagicMock()
    add_entities = MagicMock()

    await async_setup_entry(MagicMock(), entry, add_entities)

    add_entities.assert_called_once()
    created = add_entities.call_args.args[0]
    device_ids = {list(e._attr_device_info["identifiers"])[0][1] for e in created}
    assert f"container_{ENV_ID}_{CONTAINER_NAME}" in device_ids
    assert f"container_{ENV_ID}_compose-web" not in device_ids
    # 3 number entities per stack-less container (memory, cpu, pids)
    assert len(created) == 3


# ---------------------------------------------------------------------------
# native_value
# ---------------------------------------------------------------------------


def test_memory_native_value_from_runtime_config():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 268435456}})
    assert entity.native_value == 268435456


def test_memory_native_value_unknown_when_not_yet_inspected():
    entity = _make_memory_entity({})
    assert entity.native_value is None


def test_cpu_native_value_converts_nano_cpus():
    entity = _make_cpu_entity({CONTAINER_NAME: {"nano_cpus": 1_500_000_000}})
    assert entity.native_value == 1.5


def test_cpu_native_max_uses_host_cpu_count():
    entity = _make_cpu_entity(host_cpus=8)
    assert entity._attr_native_max_value == 8.0


def test_cpu_native_max_falls_back_when_host_cpus_unknown():
    entity = _make_cpu_entity(host_cpus=None)
    assert entity._attr_native_max_value == 64.0


def test_pids_native_value_unlimited_sentinel():
    entity = _make_pids_entity({CONTAINER_NAME: {"pids_limit": -1}})
    assert entity.native_value == -1


# ---------------------------------------------------------------------------
# Optimistic update
# ---------------------------------------------------------------------------


async def test_memory_set_native_value_optimistic_update():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 268435456}})
    with patch.object(entity, "async_write_ha_state"):
        await entity.async_set_native_value(536870912)
    assert entity.native_value == 536870912
    entity._fast_coordinator.client.async_update_container_runtime.assert_called_once_with(
        ENV_ID, CONTAINER_ID, {"Memory": 536870912}
    )


def test_optimistic_value_cleared_on_coordinator_update():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 268435456}})
    entity._optimistic_value = 999
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()
    assert entity._optimistic_value is None
    assert entity.native_value == 268435456


async def test_cpu_set_native_value_converts_to_nano_cpus():
    entity = _make_cpu_entity({CONTAINER_NAME: {"nano_cpus": 0}})
    with patch.object(entity, "async_write_ha_state"):
        await entity.async_set_native_value(2.0)
    entity._fast_coordinator.client.async_update_container_runtime.assert_called_once_with(
        ENV_ID, CONTAINER_ID, {"NanoCpus": 2_000_000_000}
    )


async def test_pids_set_native_value_passes_through():
    entity = _make_pids_entity({CONTAINER_NAME: {"pids_limit": 100}})
    with patch.object(entity, "async_write_ha_state"):
        await entity.async_set_native_value(-1)
    entity._fast_coordinator.client.async_update_container_runtime.assert_called_once_with(
        ENV_ID, CONTAINER_ID, {"PidsLimit": -1}
    )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_set_native_value_raises_container_not_found():
    entity = _make_memory_entity({}, containers=[])
    with pytest.raises(HomeAssistantError) as exc_info:
        with patch.object(entity, "async_write_ha_state"):
            await entity.async_set_native_value(1024)
    assert exc_info.value.translation_key == "container_not_found"


async def test_set_native_value_raises_action_failed_on_api_error():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 0}})
    entity._fast_coordinator.client.async_update_container_runtime = AsyncMock(
        side_effect=Exception("connection refused")
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        with patch.object(entity, "async_write_ha_state"):
            await entity.async_set_native_value(1024)
    assert exc_info.value.translation_key == "action_failed"


# ---------------------------------------------------------------------------
# Memory safety check / auto-revert
# ---------------------------------------------------------------------------


async def test_memory_decrease_schedules_safety_check():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 536870912}})
    with (
        patch.object(entity, "async_write_ha_state"),
        patch("custom_components.dockhand.number.async_call_later") as mock_later,
    ):
        await entity.async_set_native_value(268435456)  # decrease
    mock_later.assert_called_once()
    assert mock_later.call_args.args[1] == 15  # _MEMORY_SAFETY_CHECK_DELAY_SECONDS


async def test_memory_increase_does_not_schedule_safety_check():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 268435456}})
    with (
        patch.object(entity, "async_write_ha_state"),
        patch("custom_components.dockhand.number.async_call_later") as mock_later,
    ):
        await entity.async_set_native_value(536870912)  # increase
    mock_later.assert_not_called()


async def test_memory_set_to_unlimited_does_not_schedule_safety_check():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 268435456}})
    with (
        patch.object(entity, "async_write_ha_state"),
        patch("custom_components.dockhand.number.async_call_later") as mock_later,
    ):
        await entity.async_set_native_value(0)  # unlimited
    mock_later.assert_not_called()


async def test_memory_safety_check_reverts_when_container_stopped():
    """If the container is no longer running when the delayed check fires,
    revert to the previous memory value and raise a repair issue."""
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 536870912}})
    # Simulate the container having stopped by the time the check runs.
    entity._container = MagicMock(
        return_value={**CONTAINER_STANDALONE, "state": "exited"}
    )
    check_fn = entity._async_check_and_revert(536870912)

    with patch.object(entity, "async_write_ha_state"):
        await check_fn(None)

    entity._fast_coordinator.client.async_update_container_runtime.assert_called_once_with(
        ENV_ID, CONTAINER_ID, {"Memory": 536870912}
    )
    assert entity._optimistic_value == 536870912


async def test_memory_safety_check_does_nothing_when_still_running():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 268435456}})
    check_fn = entity._async_check_and_revert(536870912)

    with patch.object(entity, "async_write_ha_state"):
        await check_fn(None)

    entity._fast_coordinator.client.async_update_container_runtime.assert_not_called()


async def test_memory_safety_check_does_nothing_when_container_gone():
    entity = _make_memory_entity({}, containers=[])
    check_fn = entity._async_check_and_revert(536870912)

    with patch.object(entity, "async_write_ha_state"):
        await check_fn(None)

    entity._fast_coordinator.client.async_update_container_runtime.assert_not_called()


async def test_will_remove_from_hass_cancels_pending_safety_check():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 536870912}})
    cancel = MagicMock()
    entity._cancel_safety_check = cancel
    await entity.async_will_remove_from_hass()
    cancel.assert_called_once()
    assert entity._cancel_safety_check is None


# ---------------------------------------------------------------------------
# Repair issue on warnings
# ---------------------------------------------------------------------------


async def test_warnings_create_repair_issue():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 0}})
    entity._fast_coordinator.client.async_update_container_runtime = AsyncMock(
        return_value={"success": True, "warnings": ["swap limit not supported"]}
    )
    with (
        patch.object(entity, "async_write_ha_state"),
        patch("custom_components.dockhand.number.ir.async_create_issue") as mock_issue,
    ):
        await entity.async_set_native_value(268435456)
    mock_issue.assert_called_once()
    assert mock_issue.call_args.kwargs["translation_key"] == "runtime_update_warning"


async def test_no_warnings_no_repair_issue():
    entity = _make_memory_entity({CONTAINER_NAME: {"memory": 0}})
    with (
        patch.object(entity, "async_write_ha_state"),
        patch("custom_components.dockhand.number.ir.async_create_issue") as mock_issue,
    ):
        await entity.async_set_native_value(268435456)
    mock_issue.assert_not_called()


# ---------------------------------------------------------------------------
# Entity metadata
# ---------------------------------------------------------------------------


def test_entities_disabled_by_default():
    assert not _make_memory_entity()._attr_entity_registry_enabled_default
    assert not _make_cpu_entity()._attr_entity_registry_enabled_default
    assert not _make_pids_entity()._attr_entity_registry_enabled_default


def test_unique_id_format():
    entity = _make_memory_entity()
    assert (
        entity._attr_unique_id
        == f"{ENTRY_ID}_{ENV_ID}_container_{CONTAINER_NAME}_memory_limit"
    )
