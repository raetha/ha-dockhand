"""
Tests for git stack entities (sensor/binary_sensor/button/switch) and the
container and git-stack auto-update switches.

Covers:
- Git stack sync status/last sync sensors and sync-error binary sensor
- Git stack Deploy/Sync from Git button: correct git_stack_id used,
  git_stack_not_found and action_failed error handling, and its
  translated name and icon, which follow the stack's state as in Dockhand
- Git stack auto-update switch: optimistic update, PUT body shape
- Container auto-update switch: on/off state derived from map membership
  (not an explicit boolean field), optimistic update, enable/disable body shape
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import UNDEFINED

from custom_components.dockhand.binary_sensor import (
    DockhandGitStackSyncErrorBinarySensor,
)
from custom_components.dockhand.button import (
    DockhandGitStackDeployButton,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
)
from custom_components.dockhand.sensor import (
    DockhandGitStackLastSyncSensor,
    DockhandGitStackSyncStatusSensor,
)
from custom_components.dockhand.switch import (
    DockhandContainerAutoUpdateSwitch,
    DockhandGitStackAutoUpdateSwitch,
)

from .conftest import fast_coordinator, slow_coordinator, stack

ENV_ID = 1
ENTRY_ID = "test_entry_id_git"
ENV_NAME = "myenv"
BASE_URL = "http://dh.test:3000"

GIT_STACK = {
    "id": 42,
    "stackName": "myapp",
    "syncStatus": "synced",
    "lastSync": "2026-07-01T12:00:00Z",
    "lastCommit": "abc123",
    "syncError": None,
    "autoUpdate": False,
    "webhookEnabled": True,
}


def _make_slow_coord(git_stacks=None) -> MagicMock:
    return slow_coordinator(
        {ENV_ID: {"git_stacks": git_stacks if git_stacks is not None else [GIT_STACK]}}
    )


def _make_fast_coord(containers=None) -> MagicMock:
    return fast_coordinator(
        {ENV_ID: {"containers": containers if containers is not None else []}}
    )


# ---------------------------------------------------------------------------
# Git stack sensors
# ---------------------------------------------------------------------------


def test_sync_status_sensor_value_and_attrs():
    slow = _make_slow_coord()
    sensor = DockhandGitStackSyncStatusSensor(
        slow, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert sensor.native_value == "synced"
    attrs = sensor.extra_state_attributes
    assert attrs["last_commit"] == "abc123"
    assert attrs["webhook_enabled"] is True


def test_sync_status_sensor_none_when_stack_gone():
    slow = _make_slow_coord(git_stacks=[])
    sensor = DockhandGitStackSyncStatusSensor(
        slow, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_last_sync_sensor_parses_timestamp():
    slow = _make_slow_coord()
    sensor = DockhandGitStackLastSyncSensor(
        slow, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert sensor.native_value is not None
    assert sensor.native_value.year == 2026


# ---------------------------------------------------------------------------
# Git stack sync-error binary sensor
# ---------------------------------------------------------------------------


def test_sync_error_binary_sensor_off_when_synced():
    slow = _make_slow_coord()
    sensor = DockhandGitStackSyncErrorBinarySensor(
        slow, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert sensor.is_on is False


def test_sync_error_binary_sensor_on_when_error():
    errored = {**GIT_STACK, "syncStatus": "error", "syncError": "auth failed"}
    slow = _make_slow_coord(git_stacks=[errored])
    sensor = DockhandGitStackSyncErrorBinarySensor(
        slow, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, errored
    )
    assert sensor.is_on is True
    assert sensor.extra_state_attributes["sync_error"] == "auth failed"


# ---------------------------------------------------------------------------
# Git stack sync/deploy buttons
# ---------------------------------------------------------------------------


async def test_deploy_button_uses_git_stack_id():
    fast = _make_fast_coord()
    slow = _make_slow_coord()
    client = MagicMock()
    client.async_deploy_git_stack = AsyncMock(return_value={"success": True})
    button = DockhandGitStackDeployButton(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    await button.async_press()
    client.async_deploy_git_stack.assert_called_once_with(42)


def _make_fast_coord_with_stack_status(status: str | None) -> MagicMock:
    stacks = [stack("myapp", status=status)] if status is not None else []
    return fast_coordinator({ENV_ID: {"containers": [], "stacks": stacks}})


def _translations(language: str) -> dict[str, str]:
    """The integration's button names in a language, keyed as Home
    Assistant's platform translations are."""
    path = (
        Path(__file__).parent.parent
        / "custom_components/dockhand/translations"
        / f"{language}.json"
    )
    buttons = json.loads(path.read_text(encoding="utf-8"))["entity"]["button"]
    return {
        f"component.dockhand.entity.button.{key}.name": value["name"]
        for key, value in buttons.items()
    }


def _git_deploy_button(status: str | None, language: str = "en"):
    button = DockhandGitStackDeployButton(
        _make_fast_coord_with_stack_status(status),
        _make_slow_coord(),
        MagicMock(),
        ENTRY_ID,
        ENV_ID,
        ENV_NAME,
        BASE_URL,
        GIT_STACK,
    )
    button.platform_data = MagicMock(
        platform_name="dockhand",
        domain="button",
        platform_translations=_translations(language),
        object_id_platform_translations=_translations("en"),
    )
    return button


@pytest.mark.parametrize("status", ["not deployed", "created"])
def test_deploy_button_name_is_deploy_when_stack_down(status):
    assert _git_deploy_button(status).name == "Deploy"


def test_deploy_button_name_is_sync_from_git_when_running():
    assert _git_deploy_button("running").name == "Sync from Git"


def test_deploy_button_name_is_sync_from_git_when_stack_status_unknown():
    """Not in the fast data at all (a poll gap): Dockhand only says
    "Deploy" for the two down states."""
    assert _git_deploy_button(None).name == "Sync from Git"


def test_deploy_button_names_are_translated():
    assert _git_deploy_button("running", "de").name == "Aus Git synchronisieren"
    assert _git_deploy_button("created", "de").name == "Bereitstellen"


def test_deploy_button_entity_id_comes_from_english_deploy_in_any_state():
    assert _git_deploy_button("running", "de").suggested_object_id == "Deploy"
    assert _git_deploy_button("created").suggested_object_id == "Deploy"


def test_deploy_button_has_no_name_before_it_is_added():
    button = _git_deploy_button("running")
    button.platform_data = None
    assert button.name is UNDEFINED


def test_deploy_button_icon_is_rocket_when_down():
    fast = _make_fast_coord_with_stack_status("not deployed")
    slow = _make_slow_coord()
    button = DockhandGitStackDeployButton(
        fast, slow, MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert button.icon == "mdi:rocket-launch-outline"


def test_deploy_button_icon_is_refresh_when_running():
    fast = _make_fast_coord_with_stack_status("running")
    slow = _make_slow_coord()
    button = DockhandGitStackDeployButton(
        fast, slow, MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert button.icon == "mdi:refresh"


async def test_deploy_button_raises_git_stack_not_found():
    fast = _make_fast_coord()
    slow = _make_slow_coord(git_stacks=[])
    client = MagicMock()
    button = DockhandGitStackDeployButton(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await button.async_press()
    assert exc_info.value.translation_key == "git_stack_not_found"


async def test_deploy_button_raises_action_failed_on_api_error():
    fast = _make_fast_coord()
    slow = _make_slow_coord()
    client = MagicMock()
    client.async_deploy_git_stack = AsyncMock(side_effect=Exception("timeout"))
    button = DockhandGitStackDeployButton(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await button.async_press()
    assert exc_info.value.translation_key == "action_failed"


# ---------------------------------------------------------------------------
# Git stack auto-update switch
# ---------------------------------------------------------------------------


def test_git_stack_auto_update_reads_current_state():
    slow = _make_slow_coord()
    client = MagicMock()
    switch = DockhandGitStackAutoUpdateSwitch(
        slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert switch.is_on is False


async def test_git_stack_auto_update_turn_on_sends_put():
    slow = _make_slow_coord()
    client = MagicMock()
    client.async_update_git_stack = AsyncMock(return_value={"success": True})
    switch = DockhandGitStackAutoUpdateSwitch(
        slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_on()
    client.async_update_git_stack.assert_called_once_with(42, {"autoUpdate": True})
    assert switch.is_on is True


async def test_git_stack_auto_update_optimistic_cleared_on_refresh():
    slow = _make_slow_coord()
    client = MagicMock()
    switch = DockhandGitStackAutoUpdateSwitch(
        slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    switch._optimistic_value = True
    with patch.object(switch, "async_write_ha_state"):
        switch._handle_coordinator_update()
    assert switch._optimistic_value is None
    assert switch.is_on is False  # falls back to real (unchanged) data


async def test_git_stack_auto_update_raises_not_found():
    slow = _make_slow_coord(git_stacks=[])
    client = MagicMock()
    switch = DockhandGitStackAutoUpdateSwitch(
        slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await switch.async_turn_on()
    assert exc_info.value.translation_key == "git_stack_not_found"


# ---------------------------------------------------------------------------
# Container auto-update switch
# ---------------------------------------------------------------------------


def test_container_auto_update_on_when_present_in_map():
    fast = _make_fast_coord(containers=[{"name": "web", "id": "abc"}])
    slow = _make_slow_coord()
    slow.data["environments"][ENV_ID]["auto_update_settings"] = {
        "web": {"enabled": True}
    }
    client = MagicMock()
    switch = DockhandContainerAutoUpdateSwitch(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, "web"
    )
    assert switch.is_on is True


def test_container_auto_update_off_when_absent_from_map():
    """Dockhand's batch endpoint only lists enabled containers — absence
    means disabled, not unknown."""
    fast = _make_fast_coord(containers=[{"name": "web", "id": "abc"}])
    slow = _make_slow_coord()
    slow.data["environments"][ENV_ID]["auto_update_settings"] = {}
    client = MagicMock()
    switch = DockhandContainerAutoUpdateSwitch(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, "web"
    )
    assert switch.is_on is False


def test_container_auto_update_unavailable_when_fetch_failed():
    """A failed auto_update_settings fetch makes the switch unavailable:
    a container missing from the settings means "off", so the last state,
    or an empty one, could pass for a confirmed change."""
    fast = _make_fast_coord(containers=[{"name": "web", "id": "abc"}])
    slow = _make_slow_coord()
    slow.data["environments"][ENV_ID]["auto_update_settings"] = {}
    slow.data["environments"][ENV_ID]["fetch_failures"] = {"auto_update_settings"}
    client = MagicMock()
    switch = DockhandContainerAutoUpdateSwitch(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, "web"
    )
    assert switch.available is False


async def test_container_auto_update_turn_on_sends_defaults():
    fast = _make_fast_coord(containers=[{"name": "web", "id": "abc"}])
    slow = _make_slow_coord()
    slow.data["environments"][ENV_ID]["auto_update_settings"] = {}
    client = MagicMock()
    client.async_set_container_auto_update = AsyncMock(return_value={"success": True})
    switch = DockhandContainerAutoUpdateSwitch(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, "web"
    )
    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_on()
    client.async_set_container_auto_update.assert_called_once_with(ENV_ID, "web", True)
    assert switch.is_on is True


async def test_container_auto_update_raises_not_found_when_container_gone():
    fast = _make_fast_coord(containers=[])
    slow = _make_slow_coord()
    client = MagicMock()
    switch = DockhandContainerAutoUpdateSwitch(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, "web"
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await switch.async_turn_off()
    assert exc_info.value.translation_key == "container_not_found"


def test_container_auto_update_disabled_by_default():
    fast = _make_fast_coord()
    slow = _make_slow_coord()
    client = MagicMock()
    switch = DockhandContainerAutoUpdateSwitch(
        fast, slow, client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, "web"
    )
    assert not switch._attr_entity_registry_enabled_default


# ---------------------------------------------------------------------------
# Auto update switches: errors, refreshes and availability
# ---------------------------------------------------------------------------


def _container_auto_update_switch(containers=None, client=None):
    fast = _make_fast_coord(
        containers=containers
        if containers is not None
        else [{"name": "web", "id": "a"}]
    )
    slow = _make_slow_coord()
    slow.data["environments"][ENV_ID]["auto_update_settings"] = {}
    return DockhandContainerAutoUpdateSwitch(
        fast, slow, client or MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, "web"
    )


def test_container_auto_update_unavailable_once_the_container_is_gone():
    assert _container_auto_update_switch(containers=[]).available is False


async def test_container_auto_update_api_error_is_action_failed():
    client = MagicMock()
    client.async_set_container_auto_update = AsyncMock(side_effect=Exception("500"))
    switch = _container_auto_update_switch(client=client)
    with pytest.raises(HomeAssistantError) as exc_info:
        await switch.async_turn_on()
    assert exc_info.value.translation_key == "action_failed"


def test_container_auto_update_refresh_drops_the_optimistic_value():
    switch = _container_auto_update_switch()
    switch._optimistic_value = True
    with patch.object(switch, "async_write_ha_state"):
        switch._handle_coordinator_update()
    assert switch.is_on is False


async def test_git_stack_auto_update_api_error_is_action_failed():
    client = MagicMock()
    client.async_update_git_stack = AsyncMock(side_effect=Exception("500"))
    switch = DockhandGitStackAutoUpdateSwitch(
        _make_slow_coord(), client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await switch.async_turn_off()
    assert exc_info.value.translation_key == "action_failed"


async def test_git_stack_auto_update_turn_off_sends_put():
    client = MagicMock()
    client.async_update_git_stack = AsyncMock(return_value={"success": True})
    switch = DockhandGitStackAutoUpdateSwitch(
        _make_slow_coord(), client, ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_off()
    client.async_update_git_stack.assert_called_once_with(42, {"autoUpdate": False})
    assert switch.is_on is False
