"""
Tests for the restart-policy select entity (select.py).

Covers: async_setup_entry gating (stack-less only, opt-in flag),
current_option from runtime_config, optimistic update + reset on
coordinator refresh, async_select_option API call shape, error handling,
and repair issue on warnings.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.dockhand.select import (
    DockhandContainerRestartPolicySelect,
    async_setup_entry,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
)

ENV_ID = 1
ENTRY_ID = "test_entry_id_select"
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
        "environments": {
            ENV_ID: {
                "containers": containers
                if containers is not None
                else [CONTAINER_STANDALONE],
            }
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
    coord.data = {"environments": {ENV_ID: {"runtime_config": runtime_config or {}}}}
    coord.last_update_success = True
    return coord


def _make_entity(runtime_config=None, containers=None):
    fast = _make_fast_coord(containers)
    slow = _make_slow_coord(runtime_config)
    entity = DockhandContainerRestartPolicySelect(
        fast, slow, ENTRY_ID, ENV_ID, CONTAINER_NAME
    )
    entity.hass = MagicMock()
    return entity


async def test_setup_entry_skips_when_disabled():
    entry = MagicMock()
    entry.options = {}
    entry.data = {"enable_runtime_controls": False}
    add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, add_entities)
    add_entities.assert_not_called()


async def test_setup_entry_creates_only_for_stackless():
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

    created = add_entities.call_args.args[0]
    assert len(created) == 1
    assert created[0]._container_name == CONTAINER_NAME


def test_current_option_from_runtime_config():
    entity = _make_entity({CONTAINER_NAME: {"restart_policy": "always"}})
    assert entity.current_option == "always"


def test_current_option_none_when_not_yet_inspected():
    entity = _make_entity({})
    assert entity.current_option is None


def test_current_option_none_for_unrecognized_value():
    """Defensive: an unexpected policy string doesn't crash the select,
    just reads as unknown rather than an invalid option."""
    entity = _make_entity({CONTAINER_NAME: {"restart_policy": "something-new"}})
    assert entity.current_option is None


async def test_select_option_optimistic_update():
    entity = _make_entity({CONTAINER_NAME: {"restart_policy": "no"}})
    with patch.object(entity, "async_write_ha_state"):
        await entity.async_select_option("always")
    assert entity.current_option == "always"
    entity._fast_coordinator.client.async_update_container_runtime.assert_called_once_with(
        ENV_ID, CONTAINER_ID, {"RestartPolicy": {"Name": "always"}}
    )


def test_optimistic_value_cleared_on_coordinator_update():
    entity = _make_entity({CONTAINER_NAME: {"restart_policy": "no"}})
    entity._optimistic_value = "always"
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()
    assert entity._optimistic_value is None
    assert entity.current_option == "no"


async def test_select_option_raises_container_not_found():
    entity = _make_entity({}, containers=[])
    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_select_option("always")
    assert exc_info.value.translation_key == "container_not_found"


async def test_select_option_raises_action_failed_on_api_error():
    entity = _make_entity({CONTAINER_NAME: {"restart_policy": "no"}})
    entity._fast_coordinator.client.async_update_container_runtime = AsyncMock(
        side_effect=Exception("connection refused")
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_select_option("always")
    assert exc_info.value.translation_key == "action_failed"


async def test_warnings_create_repair_issue():
    entity = _make_entity({CONTAINER_NAME: {"restart_policy": "no"}})
    entity._fast_coordinator.client.async_update_container_runtime = AsyncMock(
        return_value={"success": True, "warnings": ["some warning"]}
    )
    with (
        patch.object(entity, "async_write_ha_state"),
        patch("custom_components.dockhand.select.ir.async_create_issue") as mock_issue,
    ):
        await entity.async_select_option("always")
    mock_issue.assert_called_once()
    assert mock_issue.call_args.kwargs["translation_key"] == "runtime_update_warning"


def test_disabled_by_default():
    assert not _make_entity()._attr_entity_registry_enabled_default


def test_unique_id_format():
    entity = _make_entity()
    assert (
        entity._attr_unique_id
        == f"{ENTRY_ID}_{ENV_ID}_container_{CONTAINER_NAME}_restart_policy"
    )
