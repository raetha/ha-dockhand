"""
Tests for system-container protection: the running switch, restart
button, auto-update switch, and runtime controls (memory/CPU/pids limit,
restart policy) must not be created for Dockhand's own infrastructure
containers (itself, or a Hawser agent), or — for the running switch and
restart button — for any stack containing one. Confirmed from Dockhand's
own source that its API has no server-side guard against restarting/
stopping these directly, or changing their resource limits (only its own
frontend UI hides the option for start/stop/restart specifically), so
this integration must enforce it itself rather than relying on
Dockhand's API to refuse.

Covers async_setup_entry's creation-skip logic in switch.py, button.py,
number.py, and select.py. Cleanup of these same entities if a
container/stack transitions into "system" status while already
registered is covered in test_init.py (container_action_uids/
stack_action_uids/runtime_control_uids).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.dockhand.button import async_setup_entry as button_setup
from custom_components.dockhand.number import async_setup_entry as number_setup
from custom_components.dockhand.select import async_setup_entry as select_setup
from custom_components.dockhand.switch import async_setup_entry as switch_setup

ENV_ID = 1
ENTRY_ID = "test_entry_id_system"
ENV_NAME = "myenv"
BASE_URL = "http://dh.test:3000"

CONTAINER_NORMAL = {"name": "web", "id": "abc", "systemContainer": None}
CONTAINER_SYSTEM = {"name": "dockhand", "id": "def", "systemContainer": "dockhand"}

# NOTE: stack["containers"] is a list of container IDs, not names —
# confirmed from Dockhand's own source. Must match CONTAINER_NORMAL/
# CONTAINER_SYSTEM's "id" fields above, not their "name" fields.
STACK_NORMAL = {"name": "myapp", "containers": ["abc"], "status": "running"}
STACK_WITH_SYSTEM = {
    "name": "infra",
    "containers": ["abc", "def"],
    "status": "running",
}


def _make_entry(containers, stacks) -> MagicMock:
    fast = MagicMock()
    fast.data = {
        ENV_ID: {
            "stats": {"name": ENV_NAME},
            "containers": containers,
            "stacks": stacks,
        }
    }
    fast.async_add_listener = MagicMock(return_value=lambda: None)

    slow = MagicMock()
    slow.data = {}
    slow.async_add_listener = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"api_url": BASE_URL}
    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.runtime_data.client = MagicMock()
    entry.async_on_unload = MagicMock()
    return entry


def _all_created(add_entities: MagicMock) -> list:
    """Both switch.py and button.py call async_add_entities() multiple
    times in one setup pass (containers, stacks, git stacks, etc.) — need
    every call's entities, not just the last one."""
    created = []
    for call in add_entities.call_args_list:
        created.extend(call.args[0])
    return created


async def test_switch_skips_running_switch_for_system_container():
    entry = _make_entry([CONTAINER_SYSTEM], [])
    add_entities = MagicMock()
    await switch_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandContainerRunningSwitch" not in names


async def test_switch_creates_running_switch_for_normal_container():
    entry = _make_entry([CONTAINER_NORMAL], [])
    add_entities = MagicMock()
    await switch_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandContainerRunningSwitch" in names


async def test_switch_skips_stack_running_switch_when_stack_has_system_container():
    entry = _make_entry([CONTAINER_NORMAL, CONTAINER_SYSTEM], [STACK_WITH_SYSTEM])
    add_entities = MagicMock()
    await switch_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandStackRunningSwitch" not in names


async def test_switch_creates_stack_running_switch_for_normal_stack():
    entry = _make_entry([CONTAINER_NORMAL], [STACK_NORMAL])
    add_entities = MagicMock()
    await switch_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandStackRunningSwitch" in names


async def test_switch_skips_auto_update_switch_for_system_container():
    entry = _make_entry([CONTAINER_SYSTEM], [])
    add_entities = MagicMock()
    await switch_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandContainerAutoUpdateSwitch" not in names


async def test_switch_creates_auto_update_switch_for_normal_container():
    entry = _make_entry([CONTAINER_NORMAL], [])
    add_entities = MagicMock()
    await switch_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandContainerAutoUpdateSwitch" in names


async def test_button_skips_restart_button_for_system_container():
    entry = _make_entry([CONTAINER_SYSTEM], [])
    add_entities = MagicMock()
    await button_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandContainerRestartButton" not in names


async def test_button_creates_restart_button_for_normal_container():
    entry = _make_entry([CONTAINER_NORMAL], [])
    add_entities = MagicMock()
    await button_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandContainerRestartButton" in names


async def test_button_skips_stack_restart_button_when_stack_has_system_container():
    entry = _make_entry([CONTAINER_NORMAL, CONTAINER_SYSTEM], [STACK_WITH_SYSTEM])
    add_entities = MagicMock()
    await button_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandStackRestartButton" not in names


async def test_button_creates_stack_restart_button_for_normal_stack():
    entry = _make_entry([CONTAINER_NORMAL], [STACK_NORMAL])
    add_entities = MagicMock()
    await button_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandStackRestartButton" in names


# ---------------------------------------------------------------------------
# Runtime controls (number.py/select.py) — stack-less, non-system containers
# only
# ---------------------------------------------------------------------------


def _make_runtime_control_entry(containers) -> MagicMock:
    fast = MagicMock()
    fast.data = {
        ENV_ID: {
            "stats": {"name": ENV_NAME},
            "containers": containers,
            "stacks": [],
        }
    }
    fast.async_add_listener = MagicMock(return_value=lambda: None)

    slow = MagicMock()
    slow.data = {"environments": {ENV_ID: {"host": {}, "runtime_config": {}}}}
    slow.async_add_listener = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {"api_url": BASE_URL}
    entry.options = {"enable_runtime_controls": True}
    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.async_on_unload = MagicMock()
    return entry


async def test_number_skips_runtime_controls_for_system_container():
    entry = _make_runtime_control_entry([CONTAINER_SYSTEM])
    add_entities = MagicMock()
    await number_setup(MagicMock(), entry, add_entities)
    created = add_entities.call_args.args[0] if add_entities.call_args else []
    assert created == []


async def test_number_creates_runtime_controls_for_normal_container():
    entry = _make_runtime_control_entry([CONTAINER_NORMAL])
    add_entities = MagicMock()
    await number_setup(MagicMock(), entry, add_entities)
    created = add_entities.call_args.args[0]
    names = {type(e).__name__ for e in created}
    assert "DockhandContainerMemoryLimitNumber" in names
    assert "DockhandContainerCpuLimitNumber" in names
    assert "DockhandContainerPidsLimitNumber" in names


async def test_select_skips_restart_policy_for_system_container():
    entry = _make_runtime_control_entry([CONTAINER_SYSTEM])
    add_entities = MagicMock()
    await select_setup(MagicMock(), entry, add_entities)
    created = add_entities.call_args.args[0] if add_entities.call_args else []
    assert created == []


async def test_select_creates_restart_policy_for_normal_container():
    entry = _make_runtime_control_entry([CONTAINER_NORMAL])
    add_entities = MagicMock()
    await select_setup(MagicMock(), entry, add_entities)
    created = add_entities.call_args.args[0]
    names = [type(e).__name__ for e in created]
    assert "DockhandContainerRestartPolicySelect" in names


# ---------------------------------------------------------------------------
# Deploy button (internal stacks only) — button.py
# ---------------------------------------------------------------------------

STACK_INTERNAL = {
    "name": "myapp",
    "containers": ["abc"],
    "status": "running",
    "sourceType": "internal",
}
STACK_GIT = {
    "name": "myapp",
    "containers": ["abc"],
    "status": "running",
    "sourceType": "git",
}
STACK_UNTRACKED = {"name": "myapp", "containers": ["abc"], "status": "running"}
STACK_INTERNAL_WITH_SYSTEM = {
    "name": "infra",
    "containers": ["abc", "def"],
    "status": "running",
    "sourceType": "internal",
}


async def test_button_creates_deploy_button_for_internal_stack():
    entry = _make_entry([CONTAINER_NORMAL], [STACK_INTERNAL])
    add_entities = MagicMock()
    await button_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandStackDeployButton" in names


async def test_button_skips_deploy_button_for_git_stack():
    """Git stacks already have their own Deploy button via a completely
    separate code path — the internal-stack Deploy button must not also
    be created for them."""
    entry = _make_entry([CONTAINER_NORMAL], [STACK_GIT])
    add_entities = MagicMock()
    await button_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandStackDeployButton" not in names


async def test_button_skips_deploy_button_for_untracked_stack():
    """Confirmed from Dockhand's own frontend: its Redeploy control is
    hidden entirely for stacks with no known compose file location
    (sourceType absent/'external')."""
    entry = _make_entry([CONTAINER_NORMAL], [STACK_UNTRACKED])
    add_entities = MagicMock()
    await button_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandStackDeployButton" not in names


async def test_button_skips_deploy_button_for_internal_stack_with_system_container():
    entry = _make_entry(
        [CONTAINER_NORMAL, CONTAINER_SYSTEM], [STACK_INTERNAL_WITH_SYSTEM]
    )
    add_entities = MagicMock()
    await button_setup(MagicMock(), entry, add_entities)
    names = [type(e).__name__ for e in _all_created(add_entities)]
    assert "DockhandStackDeployButton" not in names
