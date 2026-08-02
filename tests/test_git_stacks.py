"""
Tests for git stack entities (sensor/binary_sensor/button/switch) and the
container and git-stack auto-update switches.

Covers:
- Git stack sync status/last sync sensors and sync-error binary sensor
- Git stack Deploy/Sync from Git button: correct git_stack_id used,
  git_stack_not_found and action_failed error handling, and its live
  name/icon matching Dockhand's own state-dependent labeling (see
  DockhandGitStackDeployButton's docstring for why there's no separate
  check-only Sync button — confirmed redundant with this one, since
  Dockhand's own deployGitStack() always runs the identical sync step
  first regardless of whether a deploy follows)
- Git stack auto-update switch: optimistic update, PUT body shape
- Container auto-update switch: on/off state derived from map membership
  (not an explicit boolean field), optimistic update, enable/disable body shape
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

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
    coord = MagicMock(spec=DockhandSlowCoordinator)
    coord.data = {
        "environments": {
            ENV_ID: {
                "git_stacks": git_stacks if git_stacks is not None else [GIT_STACK],
            }
        }
    }
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
    return coord


def _make_fast_coord(containers=None) -> MagicMock:
    coord = MagicMock(spec=DockhandFastCoordinator)
    coord.data = {
        "environments": {
            ENV_ID: {"containers": containers if containers is not None else []}
        }
    }
    return coord


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
    coord = MagicMock(spec=DockhandFastCoordinator)
    stacks = [{"name": "myapp", "status": status}] if status is not None else []
    coord.data = {"environments": {ENV_ID: {"containers": [], "stacks": stacks}}}
    return coord


def test_deploy_button_name_is_deploy_when_stack_not_deployed():
    fast = _make_fast_coord_with_stack_status("not deployed")
    slow = _make_slow_coord()
    button = DockhandGitStackDeployButton(
        fast, slow, MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert button.name == "Deploy"


def test_deploy_button_name_is_deploy_when_stack_created_not_started():
    fast = _make_fast_coord_with_stack_status("created")
    slow = _make_slow_coord()
    button = DockhandGitStackDeployButton(
        fast, slow, MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert button.name == "Deploy"


def test_deploy_button_name_is_sync_from_git_when_running():
    fast = _make_fast_coord_with_stack_status("running")
    slow = _make_slow_coord()
    button = DockhandGitStackDeployButton(
        fast, slow, MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert button.name == "Sync from Git"


def test_deploy_button_name_is_sync_from_git_when_stack_status_unknown():
    """If the stack isn't found in fast data at all (e.g. a poll gap),
    default to "Sync from Git" rather than "Deploy" — matching Dockhand's
    own condition, which only shows "Deploy" for the two specific down
    states, defaulting to the "up" label otherwise."""
    fast = _make_fast_coord_with_stack_status(None)
    slow = _make_slow_coord()
    button = DockhandGitStackDeployButton(
        fast, slow, MagicMock(), ENTRY_ID, ENV_ID, ENV_NAME, BASE_URL, GIT_STACK
    )
    assert button.name == "Sync from Git"


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
    """A swallowed auto_update_settings fetch failure used to show
    whatever the last-known toggle state was — indistinguishable from a
    genuinely just-fetched one, and specifically risky here since
    absence-from-map already means "disabled": a failed fetch could look
    identical to a real, confirmed disable. Now the entity goes
    unavailable instead."""
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
