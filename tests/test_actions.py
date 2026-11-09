"""Pause and resume, schedule Run now and Enabled, and the paused case of
the Container switch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.dockhand.api import DockhandPermissionError
from custom_components.dockhand.button import (
    DockhandContainerPauseButton,
    DockhandContainerResumeButton,
    DockhandScheduleRunButton,
)
from custom_components.dockhand.helpers import (
    _schedule_can_run,
    _schedule_can_toggle,
    _schedule_is_system_toggle,
)
from custom_components.dockhand.switch import (
    DockhandContainerRunningSwitch,
    DockhandScheduleEnabledSwitch,
)

ENTRY_ID = "entry"
ENV_ID = 1
BASE_URL = "http://dh.test:3000"
RUNNING = {"id": "c1", "name": "web", "state": "running", "labels": {}}
PAUSED = {**RUNNING, "state": "paused"}
SCHED = {
    "id": 7,
    "type": "image_prune",
    "name": "Prune images",
    "environmentId": ENV_ID,
    "enabled": True,
}


def _fast(container: dict | None) -> MagicMock:
    coord = MagicMock()
    coord.data = {
        "environments": {
            ENV_ID: {"stats": {}, "containers": [container] if container else []}
        }
    }
    coord.last_update_success = True
    coord.async_refresh_environment = AsyncMock()
    return coord


def _slow(schedules: list[dict]) -> MagicMock:
    coord = MagicMock()
    coord.data = {"environments": {}, "schedules": schedules}
    coord.last_update_success = True
    coord.async_refresh = AsyncMock()
    return coord


def _container_button(cls, container: dict | None, client=None):
    return cls(
        _fast(container),
        client or MagicMock(),
        ENTRY_ID,
        ENV_ID,
        "local",
        BASE_URL,
        container or RUNNING,
    )


@pytest.mark.parametrize(
    ("cls", "state", "available"),
    [
        (DockhandContainerPauseButton, "running", True),
        (DockhandContainerPauseButton, "paused", False),
        (DockhandContainerPauseButton, "exited", False),
        (DockhandContainerResumeButton, "paused", True),
        (DockhandContainerResumeButton, "running", False),
    ],
)
def test_pause_and_resume_only_in_their_state(cls, state: str, available: bool):
    button = _container_button(cls, {**RUNNING, "state": state})
    assert button.available is available


def test_pause_and_resume_are_unavailable_once_the_container_is_gone():
    button = _container_button(DockhandContainerPauseButton, None)
    assert button.available is False


def test_pause_and_resume_are_off_by_default_with_their_own_ids():
    pause = _container_button(DockhandContainerPauseButton, RUNNING)
    resume = _container_button(DockhandContainerResumeButton, PAUSED)
    assert pause.entity_registry_enabled_default is False
    assert pause.unique_id == f"{ENTRY_ID}_{ENV_ID}_container_web_pause"
    assert resume.unique_id == f"{ENTRY_ID}_{ENV_ID}_container_web_resume"


@pytest.mark.parametrize(
    ("cls", "container", "call"),
    [
        (DockhandContainerPauseButton, RUNNING, "async_pause_container"),
        (DockhandContainerResumeButton, PAUSED, "async_unpause_container"),
    ],
)
async def test_pause_and_resume_press(cls, container: dict, call: str):
    client = MagicMock()
    setattr(client, call, AsyncMock())
    button = _container_button(cls, container, client)
    await button.async_press()
    getattr(client, call).assert_awaited_once_with(ENV_ID, "c1")
    button.coordinator.async_refresh_environment.assert_awaited_once_with(ENV_ID)


async def test_pause_press_without_the_container():
    button = _container_button(DockhandContainerPauseButton, None)
    with pytest.raises(HomeAssistantError) as err:
        await button.async_press()
    assert err.value.translation_key == "container_not_found"


async def test_pause_press_reports_a_permission_refusal():
    client = MagicMock()
    client.async_pause_container = AsyncMock(side_effect=DockhandPermissionError("403"))
    button = _container_button(DockhandContainerPauseButton, RUNNING, client)
    with pytest.raises(HomeAssistantError) as err:
        await button.async_press()
    assert err.value.translation_key == "permission_denied"


async def test_container_switch_resumes_a_paused_container():
    client = MagicMock()
    client.async_unpause_container = AsyncMock()
    client.async_start_container = AsyncMock()
    switch = DockhandContainerRunningSwitch(
        _fast(PAUSED), client, ENTRY_ID, ENV_ID, "local", BASE_URL, PAUSED
    )
    assert switch.is_on is False
    await switch.async_turn_on()
    client.async_unpause_container.assert_awaited_once_with(ENV_ID, "c1")
    client.async_start_container.assert_not_called()


@pytest.mark.parametrize(
    ("sched", "can_run", "can_toggle", "system"),
    [
        (SCHED, True, True, False),
        ({"id": 1, "type": "container_update"}, True, False, False),
        ({"id": 1, "type": "git_stack_sync"}, True, False, False),
        ({"id": 100001, "type": "repo_prune"}, True, False, False),
        ({"id": 1, "type": "env_report"}, False, False, False),
        ({"id": 1, "type": "stack_deploy"}, False, False, False),
        ({"id": 3, "type": "container_start"}, True, True, False),
        ({"id": 2, "type": "system_cleanup"}, True, True, True),
        ({"id": 3, "type": "system_cleanup"}, True, False, False),
        ({"id": 6, "type": "deploy_log_reconcile"}, True, False, False),
    ],
)
def test_what_each_schedule_type_offers(
    sched: dict, can_run: bool, can_toggle: bool, system: bool
):
    assert _schedule_can_run(sched) is can_run
    assert _schedule_can_toggle(sched) is can_toggle
    assert _schedule_is_system_toggle(sched) is system


def test_schedule_entities_share_the_schedule_device_and_ids():
    button = DockhandScheduleRunButton(
        _slow([SCHED]), MagicMock(), ENTRY_ID, SCHED, BASE_URL
    )
    switch = DockhandScheduleEnabledSwitch(
        _slow([SCHED]), MagicMock(), ENTRY_ID, SCHED, BASE_URL
    )
    assert button.unique_id == f"{ENTRY_ID}_sched_7_image_prune_run"
    assert switch.unique_id == f"{ENTRY_ID}_sched_7_image_prune_enabled"
    assert button.device_info == switch.device_info


async def test_schedule_run_button():
    client = MagicMock()
    client.async_run_schedule = AsyncMock()
    button = DockhandScheduleRunButton(
        _slow([SCHED]), client, ENTRY_ID, SCHED, BASE_URL
    )
    assert button.available is True
    await button.async_press()
    client.async_run_schedule.assert_awaited_once_with("image_prune", 7)
    button.coordinator.async_refresh.assert_awaited_once()


def test_schedule_entities_unavailable_once_the_schedule_is_gone():
    slow = _slow([])
    assert (
        DockhandScheduleRunButton(
            slow, MagicMock(), ENTRY_ID, SCHED, BASE_URL
        ).available
        is False
    )
    switch = DockhandScheduleEnabledSwitch(slow, MagicMock(), ENTRY_ID, SCHED, BASE_URL)
    assert switch.available is False
    assert switch.is_on is None


@pytest.mark.parametrize(
    ("turn_on", "replies", "flips"),
    [
        # Already the wanted state elsewhere: the first flip overshoots.
        (True, [False, True], 2),
        (False, [False], 1),
        (True, [True], 1),
    ],
)
async def test_schedule_switch_flips_until_dockhand_agrees(
    turn_on: bool, replies: list[bool], flips: int
):
    client = MagicMock()
    client.async_toggle_schedule = AsyncMock(side_effect=replies)
    switch = DockhandScheduleEnabledSwitch(
        _slow([SCHED]), client, ENTRY_ID, SCHED, BASE_URL
    )
    assert switch.is_on is True
    await (switch.async_turn_on() if turn_on else switch.async_turn_off())
    assert client.async_toggle_schedule.await_count == flips
    client.async_toggle_schedule.assert_awaited_with("image_prune", 7, system=False)
    switch.coordinator.async_refresh.assert_awaited_once()


async def test_system_schedule_switch_uses_the_system_route():
    sched = {
        "id": 2,
        "type": "system_cleanup",
        "name": "Event cleanup",
        "enabled": False,
    }
    client = MagicMock()
    client.async_toggle_schedule = AsyncMock(return_value=True)
    switch = DockhandScheduleEnabledSwitch(
        _slow([sched]), client, ENTRY_ID, sched, BASE_URL
    )
    await switch.async_turn_on()
    client.async_toggle_schedule.assert_awaited_once_with(
        "system_cleanup", 2, system=True
    )
