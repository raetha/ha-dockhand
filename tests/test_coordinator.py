"""Tests for DockhandFastCoordinator and DockhandSlowCoordinator."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand import coordinator as coordinator_module
from custom_components.dockhand.api import (
    DockhandAuthError,
    DockhandClient,
    DockhandNotFoundError,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
    DockhandUpdateCoordinator,
    _safe_list,
    _unwrap,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

ENV1 = {"id": 1, "name": "local"}
ENV2 = {"id": 2, "name": "remote"}
STATS1 = {"name": "local", "cpu": 10.5, "containers": {"running": 2, "stopped": 1}}
CONTAINER1 = {"id": "abc", "name": "web", "state": "running", "labels": {}}
STACK1 = {"name": "myapp", "status": "running", "containers": 2}
IMAGE1 = {"id": "sha256:deadbeef", "size": 104857600}
NETWORK1 = {"id": "net1", "name": "bridge", "containers": {}}
VOLUME1 = {"Name": "mydata", "UsageData": {"Size": 10485760}}


def _make_client(
    envs=None,
    stats=None,
    containers=None,
    stacks=None,
    images=None,
    networks=None,
    volumes=None,
    schedules=None,
    host_info=None,
):
    c = MagicMock(spec=DockhandClient)
    _envs = envs if envs is not None else [ENV1]
    _stats = stats or STATS1
    c.async_get_environments = AsyncMock(return_value=_envs)
    c.async_get_all_dashboard_stats = AsyncMock(
        return_value=[{**_stats, "id": e["id"]} for e in _envs]
    )
    c.async_get_containers = AsyncMock(
        return_value=containers if containers is not None else [CONTAINER1]
    )
    c.async_get_container_stats = AsyncMock(return_value=[])
    c.async_get_stack_stats = AsyncMock(return_value=[])
    c.async_get_stacks = AsyncMock(return_value=stacks or [])
    c.async_get_images = AsyncMock(return_value=images or [IMAGE1])
    c.async_get_networks = AsyncMock(return_value=networks or [NETWORK1])
    c.async_get_volumes = AsyncMock(return_value=volumes or [VOLUME1])
    c.async_get_schedules = AsyncMock(return_value=schedules or [])
    c.async_get_host_info = AsyncMock(return_value=host_info or {})
    c.async_get_container_inspect = AsyncMock(
        return_value={"HostConfig": {"Memory": 0}}
    )
    c.async_get_git_stacks = AsyncMock(return_value=[])
    c.async_get_auto_update_settings = AsyncMock(return_value={})
    c.async_get_pending_updates = AsyncMock(return_value=[])
    return c


def _fast(hass: HomeAssistant, client, config=None, entry=None):
    return DockhandFastCoordinator(hass, client, config or {}, entry=entry)


def _update_coord(hass: HomeAssistant, client, fast_coordinator=None):
    if fast_coordinator is None:
        fast_coordinator = MagicMock()
        fast_coordinator.data = {"environments": {1: {"stats": {"name": "local"}}}}
    return DockhandUpdateCoordinator(hass, client, fast_coordinator, {})


def _slow(hass: HomeAssistant, client, config=None, fast_coordinator=None):
    if fast_coordinator is None:
        fast_coordinator = MagicMock()
        # Matches ENV1 = {"id": 1, "name": "local"} used throughout this
        # file — the slow coordinator derives its environment id list
        # from fast_coordinator.data["environments"].keys(), not a
        # separate API call.
        fast_coordinator.data = {"environments": {1: {"stats": {"name": "local"}}}}
    return DockhandSlowCoordinator(
        hass,
        client,
        config
        or {
            "enable_images": True,
            "enable_networks": True,
            "enable_volumes": True,
            "enable_schedules": True,
        },
        fast_coordinator,
    )


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def test_safe_list_with_list():
    assert _safe_list([1, 2]) == [1, 2]


def test_safe_list_with_none():
    assert _safe_list(None) == []


def test_safe_list_with_dict():
    assert _safe_list({"a": 1}) == []


def test_unwrap_value():
    assert _unwrap("ok", "d", "t") == "ok"


def test_unwrap_exception():
    assert _unwrap(ValueError(), "d", "t") == "d"


# ---------------------------------------------------------------------------
# Fast coordinator — data shape
# ---------------------------------------------------------------------------


async def test_fast_basic_shape(hass: HomeAssistant):
    coord = _fast(hass, _make_client(stacks=[STACK1]))
    await coord.async_refresh()
    assert 1 in coord.data["environments"]
    stats = coord.data["environments"][1]["stats"]
    assert stats["name"] == STATS1["name"]
    assert stats["cpu"] == STATS1["cpu"]
    assert coord.data["environments"][1]["containers"] == [CONTAINER1]
    assert coord.data["environments"][1]["stacks"] == [STACK1]
    assert "container_stats" in coord.data["environments"][1]


async def test_fast_container_stats_indexed_by_name(hass: HomeAssistant):
    """container_stats dict is keyed by container name for O(1) sensor lookup,
    when "Enable container stats" is on."""
    client = _make_client()
    client.async_get_container_stats = AsyncMock(
        return_value=[
            {"name": "nginx", "cpuPercent": 1.5, "memoryUsage": 52428800},
            {"name": "redis", "cpuPercent": 0.2, "memoryUsage": 10485760},
        ]
    )
    coord = _fast(hass, client, config={"enable_resource_stats": True})
    await coord.async_refresh()
    cs = coord.data["environments"][1]["container_stats"]
    assert "nginx" in cs
    assert "redis" in cs
    assert cs["nginx"]["cpuPercent"] == 1.5


async def test_fast_container_stats_not_fetched_when_disabled(hass: HomeAssistant):
    """Zero reason to pay for this API call every 60s when nothing consumes
    the result — "Enable container stats" off (the default) means the call
    itself is skipped, not just the resulting sensors left disabled."""
    client = _make_client()
    client.async_get_container_stats = AsyncMock(
        return_value=[{"name": "nginx", "cpuPercent": 1.5}]
    )
    coord = _fast(hass, client)  # default config — enable_resource_stats off
    await coord.async_refresh()
    assert coord.data["environments"][1]["container_stats"] == {}
    client.async_get_container_stats.assert_not_called()


async def test_fast_container_stats_fetched_when_enabled(hass: HomeAssistant):
    client = _make_client()
    client.async_get_container_stats = AsyncMock(
        return_value=[{"name": "nginx", "cpuPercent": 1.5}]
    )
    coord = _fast(hass, client, config={"enable_resource_stats": True})
    await coord.async_refresh()
    client.async_get_container_stats.assert_called_once_with(1)


async def test_fast_container_stats_failure_returns_empty_dict(hass: HomeAssistant):
    """A stats API failure is non-fatal — containers and stacks still update."""
    client = _make_client()
    client.async_get_container_stats = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["container_stats"] == {}
    assert coord.data["environments"][1]["containers"] == [CONTAINER1]


async def test_fast_stack_stats_keyed_by_stack_name(hass: HomeAssistant):
    client = _make_client()
    client.async_get_stack_stats = AsyncMock(
        return_value=[{"name": "myapp", "cpuPercent": 1.4, "runningCount": 2}]
    )
    coord = _fast(hass, client, config={"enable_resource_stats": True})
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert env["stack_stats"] == {
        "myapp": {"name": "myapp", "cpuPercent": 1.4, "runningCount": 2}
    }
    assert "stack_stats" not in env["fetch_failures"]
    client.async_get_stack_stats.assert_called_once_with(1)


async def test_fast_stack_stats_not_fetched_when_container_stats_off(
    hass: HomeAssistant,
):
    client = _make_client()
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["stack_stats"] is None
    client.async_get_stack_stats.assert_not_called()


async def test_fast_stack_stats_none_without_the_endpoint(hass: HomeAssistant):
    """Dockhand before 1.0.52 answers 404 — not a failure, just unsupported."""
    client = _make_client()
    client.async_get_stack_stats = AsyncMock(
        side_effect=DockhandNotFoundError("API error 404: Not Found")
    )
    coord = _fast(hass, client, config={"enable_resource_stats": True})
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert env["stack_stats"] is None
    assert "stack_stats" not in env["fetch_failures"]


async def test_fast_stack_stats_failure_is_recorded(hass: HomeAssistant):
    client = _make_client()
    client.async_get_stack_stats = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client, config={"enable_resource_stats": True})
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert env["stack_stats"] is None
    assert "stack_stats" in env["fetch_failures"]
    assert env["containers"] == [CONTAINER1]


async def test_fast_multiple_envs(hass: HomeAssistant):
    client = _make_client(envs=[ENV1, ENV2])
    client.async_get_all_dashboard_stats = AsyncMock(
        return_value=[{"id": 1, "name": "env1"}, {"id": 2, "name": "env2"}]
    )
    client.async_get_containers = AsyncMock(return_value=[])
    client.async_get_stacks = AsyncMock(return_value=[])
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert 1 in coord.data["environments"]
    assert 2 in coord.data["environments"]


async def test_fast_containers_failure_returns_empty(hass: HomeAssistant):
    client = _make_client()
    client.async_get_containers = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["containers"] == []


@pytest.mark.parametrize("key", ["containers", "stacks"])
async def test_fast_empty_list_needs_two_polls(hass: HomeAssistant, key: str):
    """Dockhand answers HTTP 200 [] when Docker can't be reached, so an
    empty list only counts once a second poll agrees."""
    client = _make_client(
        containers=[CONTAINER1], stacks=[{"name": "web"}], stats=STATS1
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == set()

    getattr(client, f"async_get_{key}").return_value = []
    client.async_get_all_dashboard_stats.return_value = [
        {**STATS1, "id": 1, key: {"total": 0}}
    ]
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert env["unconfirmed"] == {key}
    assert key not in env["fetch_failures"]

    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == set()


async def test_fast_a_missing_container_needs_a_second_refresh(hass: HomeAssistant):
    """A container being recreated drops out of the list for a moment."""
    other = {**CONTAINER1, "id": "def", "name": "db"}
    client = _make_client(containers=[CONTAINER1, other])
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert "containers" not in coord.data["environments"][1]["unconfirmed"]

    client.async_get_containers.return_value = [other]
    await coord.async_refresh_environment(1)
    assert "containers" in coord.data["environments"][1]["unconfirmed"]

    client.async_get_containers.return_value = [CONTAINER1, other]
    await coord.async_refresh_environment(1)
    assert "containers" not in coord.data["environments"][1]["unconfirmed"]

    client.async_get_containers.return_value = [other]
    await coord.async_refresh()
    await coord.async_refresh()
    assert "containers" not in coord.data["environments"][1]["unconfirmed"]


async def test_fast_a_different_disappearance_restarts_the_wait(hass: HomeAssistant):
    a, b, c = ({**CONTAINER1, "id": n, "name": n} for n in ("a", "b", "c"))
    client = _make_client(containers=[a, b, c])
    coord = _fast(hass, client)
    await coord.async_refresh()
    client.async_get_containers.return_value = [a, b]
    await coord.async_refresh()
    client.async_get_containers.return_value = [a]
    await coord.async_refresh()
    assert "containers" in coord.data["environments"][1]["unconfirmed"]
    await coord.async_refresh()
    assert "containers" not in coord.data["environments"][1]["unconfirmed"]


async def test_fast_empty_list_never_confirmed_while_dockhand_counts_some(
    hass: HomeAssistant,
):
    client = _make_client(containers=[], stats={**STATS1, "containers": {"total": 3}})
    coord = _fast(hass, client)
    for _ in range(3):
        await coord.async_refresh()
        assert "containers" in coord.data["environments"][1]["unconfirmed"]


async def test_fast_empty_list_unconfirmed_on_first_poll(hass: HomeAssistant):
    """Nothing to compare against at startup, so even an environment that
    really has no stacks waits one poll before its stacks count as empty."""
    client = _make_client(stacks=[])
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == {"stacks"}
    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == set()


async def test_fast_empty_list_guard_resets_when_items_return(hass: HomeAssistant):
    client = _make_client(stacks=[])
    coord = _fast(hass, client)
    await coord.async_refresh()
    client.async_get_stacks.return_value = [{"name": "web"}]
    await coord.async_refresh()
    client.async_get_stacks.return_value = []
    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == {"stacks"}


async def test_fast_failed_fetch_is_not_also_unconfirmed(hass: HomeAssistant):
    client = _make_client()
    client.async_get_stacks = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client)
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert "stacks" in env["fetch_failures"]
    assert "stacks" not in env["unconfirmed"]


async def test_slow_empty_images_need_two_polls(hass: HomeAssistant):
    client = _make_client()
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == set()
    client.async_get_images.return_value = []
    client.async_get_images.side_effect = None
    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == {"images"}
    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == set()


async def test_slow_empty_images_unconfirmed_while_dockhand_counts_some(
    hass: HomeAssistant,
):
    fast = MagicMock()
    fast.data = {
        "environments": {1: {"stats": {"name": "local", "images": {"total": 4}}}}
    }
    client = _make_client()
    client.async_get_images = AsyncMock(return_value=[])
    coord = _slow(hass, client, fast_coordinator=fast)
    await coord.async_refresh()
    await coord.async_refresh()
    assert coord.data["environments"][1]["unconfirmed"] == {"images"}


async def test_refresh_environment_updates_only_that_environment(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1, {"id": 2, "name": "remote"}])
    coord = _fast(hass, client)
    await coord.async_refresh()
    before_other = coord.data["environments"][2]
    stats_before = coord.data["environments"][1]["stats"]
    listener = MagicMock()
    coord.async_add_listener(listener)
    client.async_get_all_dashboard_stats.reset_mock()

    stopped = {**CONTAINER1, "state": "exited"}
    client.async_get_containers = AsyncMock(return_value=[stopped])
    await coord.async_refresh_environment(1)

    assert coord.data["environments"][1]["containers"] == [stopped]
    assert coord.data["environments"][1]["stats"] is stats_before
    assert coord.data["environments"][2] is before_other
    client.async_get_containers.assert_awaited_once_with(1)
    client.async_get_all_dashboard_stats.assert_not_called()
    listener.assert_called()


async def test_refresh_environment_without_data_is_a_no_op(hass: HomeAssistant):
    client = _make_client()
    coord = _fast(hass, client)
    await coord.async_refresh_environment(1)
    client.async_get_containers.assert_not_called()


async def test_refresh_environment_loses_to_a_full_poll(hass: HomeAssistant):
    """A full poll that completes while a single-environment refresh is in
    flight has newer data, so the older single-environment result is
    dropped."""
    client = _make_client()
    coord = _fast(hass, client)
    await coord.async_refresh()

    release = asyncio.Event()
    stale = {**CONTAINER1, "state": "exited"}

    async def slow_containers(env_id: int) -> list[dict]:
        await release.wait()
        return [stale]

    client.async_get_containers = AsyncMock(side_effect=slow_containers)
    task = hass.async_create_task(coord.async_refresh_environment(1))
    await asyncio.sleep(0)
    client.async_get_containers = AsyncMock(return_value=[CONTAINER1])
    await coord.async_refresh()
    release.set()
    await task
    assert coord.data["environments"][1]["containers"] == [CONTAINER1]


async def test_concurrent_environment_refreshes_share_fetches(hass: HomeAssistant):
    """Callers arriving while a refresh runs all join one refresh queued
    behind it, which starts only after they arrived."""
    client = _make_client()
    coord = _fast(hass, client)
    await coord.async_refresh()

    release = asyncio.Event()
    calls: list[int] = []

    async def slow_containers(env_id: int) -> list[dict]:
        calls.append(env_id)
        await release.wait()
        return [CONTAINER1]

    client.async_get_containers = AsyncMock(side_effect=slow_containers)
    first = hass.async_create_task(coord.async_refresh_environment(1))
    for _ in range(3):
        await asyncio.sleep(0)
    assert calls == [1]  # the first refresh is under way
    later = [
        hass.async_create_task(coord.async_refresh_environment(1)) for _ in range(5)
    ]
    for _ in range(3):
        await asyncio.sleep(0)
    assert calls == [1]  # the rest wait for it
    release.set()
    await asyncio.gather(first, *later)
    assert calls == [1, 1]
    # Nothing left queued: the next caller starts a fresh refresh.
    await coord.async_refresh_environment(1)
    assert calls == [1, 1, 1]


async def test_a_failed_shared_refresh_reaches_every_caller(hass: HomeAssistant):
    client = _make_client()
    coord = _fast(hass, client)
    await coord.async_refresh()
    with patch.object(
        coord, "_async_refresh_environment_now", AsyncMock(side_effect=OSError("down"))
    ):
        results = await asyncio.gather(
            coord.async_refresh_environment(1),
            coord.async_refresh_environment(1),
            return_exceptions=True,
        )
    assert [type(r) for r in results] == [OSError, OSError]


async def test_fetched_since_tracks_the_fetch_behind_the_data(hass: HomeAssistant):
    client = _make_client(envs=[ENV1, {"id": 2, "name": "remote"}])
    coord = _fast(hass, client)
    assert not coord.fetched_since(1, 0)
    before_poll = hass.loop.time()
    await coord.async_refresh()
    after_poll = hass.loop.time()
    assert coord.fetched_since(1, before_poll - 1)
    assert not coord.fetched_since(1, after_poll)
    await coord.async_refresh_environment(1)
    assert coord.fetched_since(1, after_poll)
    assert not coord.fetched_since(2, after_poll)


async def test_fast_stats_failure_does_not_clear_environments(hass: HomeAssistant):
    """/api/dashboard/stats (no env param) is the fast coordinator's only
    source of which environments exist — no separate /api/environments
    call. If it fails entirely (e.g. DNS resolution failure reaching
    Dockhand), this must fail the update (last_update_success=False,
    coordinator.data left at its last-known-good value) rather than
    silently succeed with an empty dict — an empty-but-successful result
    previously fed "zero stacks/containers for every environment" through
    every downstream consumer that trusts non-empty coordinator data as
    authoritative, including _cleanup_stale_registry's "fast data must be
    non-empty" guard (empty *all_stats* still produced a non-empty
    *fast_coordinator.data*, since _fetch_env ran per known env_id
    regardless — the guard didn't catch this). A transient/total outage
    should leave everything in place (entities go unavailable via
    last_update_success) until it resolves, never look like every stack
    and container just disappeared."""
    client = _make_client()
    client.async_get_all_dashboard_stats = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.last_update_success is False


async def test_fast_stats_failure_preserves_previous_data(hass: HomeAssistant):
    """The actual real-world scenario: environments were successfully
    fetched once, then a later poll hits a total failure (DNS resolution
    to the Dockhand host, etc.) — coordinator.data must still hold the
    last-known-good environments, not go empty, so nothing gets cleaned
    up while the outage is transient."""
    client = _make_client(envs=[ENV1], stats=STATS1)
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert 1 in coord.data["environments"]

    client.async_get_all_dashboard_stats = AsyncMock(side_effect=Exception("timeout"))
    await coord.async_refresh()
    assert coord.last_update_success is False
    assert 1 in coord.data["environments"]


async def test_fast_empty_env_list_returns_empty_data(hass: HomeAssistant):
    coord = _fast(hass, _make_client(envs=[]))
    await coord.async_refresh()
    assert coord.data == {"environments": {}}


async def test_fast_pending_updates_fetched_when_scheduled_check_disabled(
    hass: HomeAssistant,
):
    """github.com/raetha/ha-dockhand/issues/42: Dockhand's scheduled update
    check being off doesn't mean there are no pending updates — a manual
    check in Dockhand records them in the same table, and Dockhand's own
    UI shows them."""
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": False})
    client.async_get_pending_updates = AsyncMock(
        return_value=[
            {
                "containerId": "abc",
                "containerName": "web",
                "hasImageUpdate": True,
                "newerVersion": None,
                "pinnedToDigest": False,
                "releaseAgeRemainingHours": None,
                "checkedAt": None,
            }
        ]
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    client.async_get_pending_updates.assert_called_once_with(1)
    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == {"abc"}
    assert set(env_data["pending_update_details"]) == {"abc"}


async def test_fast_pending_updates_fetched_when_update_check_enabled(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": True})
    client.async_get_pending_updates = AsyncMock(
        return_value=[
            {
                "containerId": "abc",
                "containerName": "web",
                "hasImageUpdate": True,
                "newerVersion": None,
                "pinnedToDigest": False,
                "releaseAgeRemainingHours": None,
                "checkedAt": None,
            }
        ]
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    client.async_get_pending_updates.assert_called_once_with(1)
    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == {"abc"}
    assert env_data["pending_update_details"] == {
        "abc": {
            "hasImageUpdate": True,
            "newerVersion": None,
            "pinnedToDigest": False,
            "releaseAgeRemainingHours": None,
            "checkedAt": None,
        }
    }


async def test_fast_pending_updates_failure_returns_empty_set(hass: HomeAssistant):
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": True})
    client.async_get_pending_updates = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client)
    await coord.async_refresh()
    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == set()
    assert env_data["pending_update_details"] == {}


async def test_fast_pending_updates_semver_only_row_excluded_from_ids(
    hass: HomeAssistant,
):
    """A row with hasImageUpdate=False but a newerVersion suggestion is a
    real, previously-unnoticed case: Dockhand's own scheduled update-check
    job persists a row here for semver-only suggestions too (no actionable
    digest update). Such a row must NOT contribute to
    pending_update_container_ids (that set means "actionable"), but its
    newerVersion must still be reachable via pending_update_details — this
    is the fix for the over-inclusion bug this whole feature branch
    uncovered."""
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": True})
    newer_version = {"tag": "16.4-alpine", "bump": "minor", "skipped": ["16.4-alpine"]}
    client.async_get_pending_updates = AsyncMock(
        return_value=[
            {
                "containerId": "abc",
                "containerName": "web",
                "hasImageUpdate": False,
                "newerVersion": newer_version,
                "pinnedToDigest": False,
                "releaseAgeRemainingHours": None,
                "checkedAt": None,
            }
        ]
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == set()
    assert env_data["pending_update_details"] == {
        "abc": {
            "hasImageUpdate": False,
            "newerVersion": newer_version,
            "pinnedToDigest": False,
            "releaseAgeRemainingHours": None,
            "checkedAt": None,
        }
    }


async def test_fast_pending_updates_mixed_actionable_and_semver_only_rows(
    hass: HomeAssistant,
):
    """One actionable row and one semver-only row in the same poll — only
    the actionable one's id ends up in pending_update_container_ids, but
    pending_update_details keeps both."""
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": True})
    client.async_get_pending_updates = AsyncMock(
        return_value=[
            {
                "containerId": "abc",
                "containerName": "web",
                "hasImageUpdate": True,
                "newerVersion": None,
            },
            {
                "containerId": "def",
                "containerName": "db",
                "hasImageUpdate": False,
                "newerVersion": {"tag": "9.0", "bump": "major", "skipped": ["9.0"]},
            },
        ]
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == {"abc"}
    assert set(env_data["pending_update_details"].keys()) == {"abc", "def"}
    assert env_data["pending_update_details"]["def"]["hasImageUpdate"] is False


@pytest.mark.parametrize(
    "stored", [{}, {"poll_interval_fast": 10, "poll_interval_slow": 30}]
)
async def test_poll_intervals_are_fixed(hass: HomeAssistant, stored: dict):
    """Home Assistant doesn't let users set polling intervals, and a value
    left in an entry by an older release is ignored."""
    client = _make_client(envs=[])
    assert _fast(hass, client, config=stored).update_interval == timedelta(minutes=1)
    assert _slow(hass, client, config=stored).update_interval == timedelta(minutes=10)
    assert _update_coord(hass, client).update_interval == timedelta(hours=24)


# ---------------------------------------------------------------------------
# Fast coordinator — async_merge_pending_updates_from_check
# ---------------------------------------------------------------------------


async def test_merge_pending_updates_from_check_builds_both_fields(
    hass: HomeAssistant,
):
    """Fed the raw check-updates POST response shape (containerId,
    hasUpdate, newerVersion, ...) — must rebuild both
    pending_update_container_ids (actionable subset only) and
    pending_update_details (every item), same split _fetch_env applies
    to the periodic pending-updates poll."""
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": True})
    coord = _fast(hass, client)
    await coord.async_refresh()

    newer_version = {"tag": "9.0", "bump": "major", "skipped": ["9.0"]}
    items = [
        {"containerId": "abc", "containerName": "web", "hasUpdate": True},
        {
            "containerId": "def",
            "containerName": "db",
            "hasUpdate": False,
            "newerVersion": newer_version,
        },
    ]
    coord.async_merge_pending_updates_from_check(1, items)

    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == {"abc"}
    assert env_data["pending_update_details"] == {
        "abc": {
            "hasImageUpdate": True,
            "newerVersion": None,
            "pinnedToDigest": False,
            "releaseAgeRemainingHours": None,
            "checkedAt": None,
        },
        "def": {
            "hasImageUpdate": False,
            "newerVersion": newer_version,
            "pinnedToDigest": False,
            "releaseAgeRemainingHours": None,
            "checkedAt": None,
        },
    }


async def test_merge_pending_updates_from_check_noop_when_env_missing(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1])
    coord = _fast(hass, client)
    await coord.async_refresh()
    # env 999 was never fetched — merging into it must be a silent no-op,
    # not raise or fabricate an environment entry.
    coord.async_merge_pending_updates_from_check(
        999, [{"containerId": "abc", "hasUpdate": True}]
    )
    assert 999 not in coord.data["environments"]


async def test_merge_pending_updates_from_check_ignores_items_without_id(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": True})
    coord = _fast(hass, client)
    await coord.async_refresh()
    coord.async_merge_pending_updates_from_check(
        1, [{"containerName": "web", "hasUpdate": True}]
    )
    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == set()
    assert env_data["pending_update_details"] == {}


SYSTEM_CONTAINER = {
    "id": "sys1",
    "name": "dockhand",
    "state": "running",
    "labels": {},
    "systemContainer": "dockhand",
}


async def test_system_container_check_result_survives_next_poll(
    hass: HomeAssistant,
):
    """Dockhand never writes a pending-updates row for a system container,
    so an on-demand check's result for one must outlive the next poll."""
    client = _make_client(
        envs=[ENV1],
        stats={**STATS1, "updateCheckEnabled": True},
        containers=[CONTAINER1, SYSTEM_CONTAINER],
    )
    client.async_get_pending_updates = AsyncMock(
        return_value=[{"containerId": "abc", "hasImageUpdate": True}]
    )
    coord = _fast(hass, client)
    await coord.async_refresh()

    coord.async_merge_pending_updates_from_check(
        1,
        [
            {"containerId": "abc", "hasUpdate": True},
            {"containerId": "sys1", "hasUpdate": True, "systemContainer": "dockhand"},
        ],
    )
    await coord.async_refresh()

    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == {"abc", "sys1"}
    assert env_data["pending_update_details"]["sys1"] == {
        "hasImageUpdate": True,
        "newerVersion": None,
        "pinnedToDigest": False,
        "releaseAgeRemainingHours": None,
        "checkedAt": None,
        "systemContainer": "dockhand",
    }


async def test_system_container_check_result_dropped_once_container_recreated(
    hass: HomeAssistant,
):
    client = _make_client(
        envs=[ENV1],
        stats={**STATS1, "updateCheckEnabled": True},
        containers=[CONTAINER1, SYSTEM_CONTAINER],
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    coord.async_merge_pending_updates_from_check(
        1, [{"containerId": "sys1", "hasUpdate": True, "systemContainer": "dockhand"}]
    )

    client.async_get_containers = AsyncMock(
        return_value=[CONTAINER1, {**SYSTEM_CONTAINER, "id": "sys2"}]
    )
    await coord.async_refresh()
    env_data = coord.data["environments"][1]
    assert env_data["pending_update_container_ids"] == set()
    assert "sys1" not in env_data["pending_update_details"]

    # Pruned for good, not just hidden while the id is absent.
    client.async_get_containers = AsyncMock(return_value=[CONTAINER1, SYSTEM_CONTAINER])
    await coord.async_refresh()
    assert coord.data["environments"][1]["pending_update_container_ids"] == set()


async def test_system_container_check_result_kept_when_containers_fetch_fails(
    hass: HomeAssistant,
):
    client = _make_client(
        envs=[ENV1],
        stats={**STATS1, "updateCheckEnabled": True},
        containers=[CONTAINER1, SYSTEM_CONTAINER],
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    coord.async_merge_pending_updates_from_check(
        1, [{"containerId": "sys1", "hasUpdate": True, "systemContainer": "dockhand"}]
    )

    client.async_get_containers = AsyncMock(side_effect=Exception("timeout"))
    await coord.async_refresh()
    client.async_get_containers = AsyncMock(return_value=[CONTAINER1, SYSTEM_CONTAINER])
    await coord.async_refresh()
    assert coord.data["environments"][1]["pending_update_container_ids"] == {"sys1"}


async def test_new_check_without_system_update_clears_stored_result(
    hass: HomeAssistant,
):
    client = _make_client(
        envs=[ENV1],
        stats={**STATS1, "updateCheckEnabled": True},
        containers=[CONTAINER1, SYSTEM_CONTAINER],
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    coord.async_merge_pending_updates_from_check(
        1, [{"containerId": "sys1", "hasUpdate": True, "systemContainer": "dockhand"}]
    )
    coord.async_merge_pending_updates_from_check(
        1, [{"containerId": "sys1", "hasUpdate": False, "systemContainer": "dockhand"}]
    )
    await coord.async_refresh()
    assert coord.data["environments"][1]["pending_update_container_ids"] == set()


# ---------------------------------------------------------------------------
# Fast coordinator — auth / error propagation
# ---------------------------------------------------------------------------


async def test_fast_auth_error_raises_config_entry_auth_failed(hass: HomeAssistant):
    """A 401 from the API must surface as ConfigEntryAuthFailed immediately."""
    client = _make_client()
    client.async_get_all_dashboard_stats = AsyncMock(
        side_effect=DockhandAuthError("token revoked")
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await _fast(hass, client)._async_update_data()


async def test_fast_auth_error_message_mentions_token(hass: HomeAssistant):
    """The ConfigEntryAuthFailed message should mention the token."""
    client = _make_client()
    client.async_get_all_dashboard_stats = AsyncMock(
        side_effect=DockhandAuthError("expired")
    )
    with pytest.raises(ConfigEntryAuthFailed, match="token"):
        await _fast(hass, client)._async_update_data()


# Note: a generic (non-auth) error from async_get_all_dashboard_stats now
# properly fails the update (last_update_success=False, coordinator.data
# preserved at its last-known-good value — see
# test_fast_stats_failure_does_not_clear_environments and
# test_fast_stats_failure_preserves_previous_data above) rather than being
# swallowed into an empty-but-successful result. Auth errors remain the
# one deliberate exception that gets special handling (re-auth), verified
# by the two tests above.


# ---------------------------------------------------------------------------
# Slow coordinator
# ---------------------------------------------------------------------------


async def test_slow_all_features_fetches_everything(hass: HomeAssistant):
    client = _make_client(
        envs=[ENV1],
        images=[IMAGE1],
        networks=[NETWORK1],
        volumes=[VOLUME1],
        schedules=[{"id": "s1"}],
    )
    coord = _slow(hass, client)
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert env["images"] == [IMAGE1]
    assert env["networks"] == [NETWORK1]
    assert env["volumes"] == [VOLUME1]
    assert coord.data["schedules"] == [{"id": "s1"}]


async def test_slow_all_features_disabled(hass: HomeAssistant):
    client = _make_client(envs=[ENV1])
    coord = _slow(
        hass,
        client,
        config={
            "enable_images": False,
            "enable_networks": False,
            "enable_volumes": False,
            "enable_schedules": False,
        },
    )
    await coord.async_refresh()
    client.async_get_images.assert_not_called()
    client.async_get_networks.assert_not_called()
    client.async_get_volumes.assert_not_called()
    client.async_get_schedules.assert_not_called()
    assert coord.data["schedules"] == []


async def test_slow_only_images_enabled(hass: HomeAssistant):
    client = _make_client(envs=[ENV1], images=[IMAGE1])
    coord = _slow(
        hass,
        client,
        config={
            "enable_images": True,
            "enable_networks": False,
            "enable_volumes": False,
            "enable_schedules": False,
        },
    )
    await coord.async_refresh()
    client.async_get_images.assert_called_once_with(1)
    client.async_get_networks.assert_not_called()
    env = coord.data["environments"][1]
    assert env["images"] == [IMAGE1]
    assert env["networks"] == []
    assert env["volumes"] == []


async def test_slow_derives_environment_ids_from_fast_coordinator(hass: HomeAssistant):
    """Which environments exist still comes from the fast coordinator's
    already-fetched data, not from /api/environments — that call is
    still made (for imagePruneEnabled/hawser agent fields, its only
    source), but only ever consulted for env_meta content, never for
    which environments to iterate."""
    fast_mock = MagicMock()
    fast_mock.data = {
        "environments": {
            1: {"stats": {"name": "local"}},
            2: {"stats": {"name": "remote"}},
        }
    }
    client = _make_client(envs=[ENV1])
    coord = _slow(hass, client, fast_coordinator=fast_mock)
    await coord.async_refresh()
    assert set(coord.data["environments"].keys()) == {1, 2}
    client.async_get_environments.assert_called_once()


async def test_slow_host_info_fetched_and_stored(hass: HomeAssistant):
    """GET /api/host is always fetched (not gated behind a feature flag)
    since it's the only reliable source for hawserVersion on
    hawser-standard connections."""
    host_payload = {"environment": {"hawserVersion": "1.5.1"}}
    client = _make_client(envs=[ENV1], host_info=host_payload)
    coord = _slow(hass, client)
    await coord.async_refresh()
    client.async_get_host_info.assert_called_once_with(1)
    assert coord.data["environments"][1]["host"] == host_payload


async def test_slow_host_info_failure_returns_empty_dict(hass: HomeAssistant):
    """A failed /api/host call shouldn't take down the whole slow poll —
    the hawser version sensor falls back to /api/environments itself.
    Also must be recorded in fetch_failures (not just silently defaulted
    to empty) so cleanup logic downstream can tell "host info genuinely
    empty" apart from "host info fetch failed" — see _unwrap's own doc
    comment. host itself doesn't currently drive any cleanup decision,
    but the tracking is unconditional across every resource this
    coordinator fetches, not scoped only to the ones that do today."""
    client = _make_client(envs=[ENV1])
    client.async_get_host_info = AsyncMock(side_effect=Exception("timeout"))
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["host"] == {}
    assert "host" in coord.data["environments"][1]["fetch_failures"]


async def test_slow_runtime_controls_disabled_by_default(hass: HomeAssistant):
    """Not enabled unless explicitly turned on — real per-container cost."""
    client = _make_client(envs=[ENV1])
    coord = _slow(hass, client)
    await coord.async_refresh()
    client.async_get_containers.assert_not_called()
    assert coord.data["environments"][1]["runtime_config"] == {}


async def test_slow_runtime_controls_inspects_stackless_containers_only(
    hass: HomeAssistant,
):
    compose_container = {
        "id": "def",
        "name": "compose-web",
        "state": "running",
        "labels": {"com.docker.compose.project": "myapp"},
    }
    client = _make_client(envs=[ENV1], containers=[CONTAINER1, compose_container])
    client.async_get_container_inspect = AsyncMock(
        return_value={
            "HostConfig": {
                "Memory": 268435456,
                "NanoCpus": 500000000,
                "PidsLimit": 50,
                "RestartPolicy": {"Name": "always"},
            }
        }
    )
    coord = _slow(
        hass,
        client,
        config={"enable_runtime_controls": True},
    )
    await coord.async_refresh()

    # Only the stack-less container (CONTAINER1 = "web") was inspected.
    client.async_get_container_inspect.assert_called_once_with(1, "abc")
    runtime_config = coord.data["environments"][1]["runtime_config"]
    assert "web" in runtime_config
    assert "compose-web" not in runtime_config
    assert runtime_config["web"] == {
        "memory": 268435456,
        "nano_cpus": 500000000,
        "pids_limit": 50,
        "restart_policy": "always",
    }


async def test_slow_runtime_controls_inspect_failure_omits_container(
    hass: HomeAssistant,
):
    """A per-container inspect failure is logged and that container is
    simply omitted, rather than failing the whole environment's slow poll."""
    client = _make_client(envs=[ENV1], containers=[CONTAINER1])
    client.async_get_container_inspect = AsyncMock(side_effect=Exception("timeout"))
    coord = _slow(
        hass,
        client,
        config={"enable_runtime_controls": True},
    )
    await coord.async_refresh()
    assert coord.data["environments"][1]["runtime_config"] == {}


async def test_slow_git_stacks_always_fetched(hass: HomeAssistant):
    """A single bulk call per environment (not per-stack like runtime
    controls), so there's no meaningful API cost to gate — entities are
    only created for stacks that actually appear in this list."""
    client = _make_client(envs=[ENV1])
    client.async_get_git_stacks = AsyncMock(
        return_value=[{"id": 1, "stackName": "app", "syncStatus": "synced"}]
    )
    coord = _slow(hass, client)
    await coord.async_refresh()
    client.async_get_git_stacks.assert_called_once_with(1)
    assert coord.data["environments"][1]["git_stacks"][0]["stackName"] == "app"


async def test_slow_git_stacks_defaults_to_empty_list(hass: HomeAssistant):
    client = _make_client(envs=[ENV1])
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["git_stacks"] == []


async def test_slow_auto_update_settings_always_fetched(hass: HomeAssistant):
    """Unlike git_stacks/runtime_config, this is a single bulk call per
    environment — cheap enough to not need an opt-in flag."""
    client = _make_client(envs=[ENV1])
    client.async_get_auto_update_settings = AsyncMock(
        return_value={"web": {"enabled": True}}
    )
    coord = _slow(hass, client)
    await coord.async_refresh()
    client.async_get_auto_update_settings.assert_called_once_with(1)
    assert coord.data["environments"][1]["auto_update_settings"] == {
        "web": {"enabled": True}
    }


def _fast_coord_with_stats(stats: dict):
    """A minimal fast-coordinator stand-in exposing the given per-env
    stats blob, for exercising the slow coordinator's collectActivity/
    scannerEnabled gating (both read from fast_coordinator.data, not a
    separate config option)."""
    fast_coordinator = MagicMock()
    fast_coordinator.data = {"environments": {1: {"stats": stats}}}
    return fast_coordinator


async def test_slow_recent_events_not_fetched_when_collect_activity_disabled(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1])
    client.async_get_recent_activity = AsyncMock(return_value={"events": []})
    coord = _slow(
        hass,
        client,
        fast_coordinator=_fast_coord_with_stats({"collectActivity": False}),
    )
    await coord.async_refresh()
    client.async_get_recent_activity.assert_not_called()
    assert coord.data["environments"][1]["recent_events"] == []


async def test_slow_recent_events_fetched_when_collect_activity_enabled(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1])
    client.async_get_recent_activity = AsyncMock(
        return_value={"events": [{"containerName": "web", "action": "start"}]}
    )
    coord = _slow(
        hass, client, fast_coordinator=_fast_coord_with_stats({"collectActivity": True})
    )
    await coord.async_refresh()
    client.async_get_recent_activity.assert_called_once_with(1, limit=10)
    assert coord.data["environments"][1]["recent_events"] == [
        {"containerName": "web", "action": "start"}
    ]


async def test_slow_recent_events_malformed_response_defaults_to_empty_list(
    hass: HomeAssistant,
):
    """A response that isn't a dict with an "events" list (e.g. Dockhand
    changing shape, or a proxy/error page slipping through as JSON) must
    not crash the coordinator or propagate a non-list into entity
    attributes — same "safe default, never guess" principle as every
    other _unwrap()'d field."""
    client = _make_client(envs=[ENV1])
    client.async_get_recent_activity = AsyncMock(return_value={"events": "not-a-list"})
    coord = _slow(
        hass, client, fast_coordinator=_fast_coord_with_stats({"collectActivity": True})
    )
    await coord.async_refresh()
    assert coord.data["environments"][1]["recent_events"] == []


async def test_slow_vulnerabilities_not_fetched_when_scanner_disabled(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1])
    client.async_get_vulnerabilities_count = AsyncMock(
        return_value={"summary": {"total": 5}}
    )
    coord = _slow(
        hass, client, fast_coordinator=_fast_coord_with_stats({"scannerEnabled": False})
    )
    await coord.async_refresh()
    client.async_get_vulnerabilities_count.assert_not_called()
    assert coord.data["environments"][1]["vulnerabilities"] == {}


async def test_slow_vulnerabilities_fetched_when_scanner_enabled(hass: HomeAssistant):
    client = _make_client(envs=[ENV1])
    client.async_get_vulnerabilities_count = AsyncMock(
        return_value={"summary": {"total": 5, "critical": 1}}
    )
    coord = _slow(
        hass, client, fast_coordinator=_fast_coord_with_stats({"scannerEnabled": True})
    )
    await coord.async_refresh()
    client.async_get_vulnerabilities_count.assert_called_once_with(1)
    assert coord.data["environments"][1]["vulnerabilities"] == {
        "total": 5,
        "critical": 1,
    }


async def test_slow_vulnerabilities_malformed_response_defaults_to_empty_dict(
    hass: HomeAssistant,
):
    """Same safe-default principle as recent_events above: a "summary"
    that isn't a dict (or a response that isn't a dict at all) must
    default to {}, not propagate garbage into vulnerability sensors."""
    client = _make_client(envs=[ENV1])
    client.async_get_vulnerabilities_count = AsyncMock(
        return_value={"summary": ["not", "a", "dict"]}
    )
    coord = _slow(
        hass, client, fast_coordinator=_fast_coord_with_stats({"scannerEnabled": True})
    )
    await coord.async_refresh()
    assert coord.data["environments"][1]["vulnerabilities"] == {}


async def test_slow_feature_api_failure_returns_empty(hass: HomeAssistant):
    """The real bug this whole file's _unwrap tracking exists for: a
    failed images fetch (DNS failure, timeout, 5xx — anything) must not
    look identical to "this environment genuinely has zero images." Both
    conditions previously produced images == [] with no way to tell them
    apart; fetch_failures is what makes that distinction visible to
    downstream cleanup logic (__init__.py's _build_live_sets)."""
    client = _make_client(envs=[ENV1])
    client.async_get_images = AsyncMock(side_effect=Exception("timeout"))
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["images"] == []
    assert "images" in coord.data["environments"][1]["fetch_failures"]


async def test_slow_schedules_api_failure_recorded_not_silently_empty(
    hass: HomeAssistant,
):
    """The actual reported incident: a transient schedules-fetch failure
    (the report's own suspicion: DNS resolution failing intermittently)
    used to become schedules: [] with the coordinator still reporting
    success — indistinguishable from "there really are zero schedules
    now" — which caused every existing schedule device and its entities
    to be wrongly treated as confirmed-deleted by cleanup. This is the
    top-level fetch_failures set (schedules is fetched once, not
    per-environment, unlike images/networks/volumes above)."""
    client = _make_client(envs=[ENV1])
    client.async_get_schedules = AsyncMock(
        side_effect=Exception("Name or service not known")
    )
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["schedules"] == []
    assert "schedules" in coord.data["fetch_failures"]
    # The poll as a whole still succeeds — that's the point. Only the one
    # sub-fetch that actually failed is marked as such; the rest of the
    # poll's data (this environment's images/networks/etc., assuming
    # those succeeded) is still trustworthy and shouldn't be thrown away
    # over an unrelated failure.
    assert coord.last_update_success is True


async def test_slow_fetch_failures_empty_on_full_success(hass: HomeAssistant):
    """The other half of the same guarantee: a genuinely successful poll
    with genuinely empty results must NOT be marked as failed — otherwise
    cleanup would never trust anything as confirmed-empty, and stale
    entities would never get cleaned up at all."""
    client = _make_client(envs=[ENV1])
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["fetch_failures"] == set()
    assert coord.data["environments"][1]["fetch_failures"] == set()


async def test_slow_auth_error_raises_update_failed_with_message(hass: HomeAssistant):
    """DockhandAuthError is wrapped in UpdateFailed by _async_update_data.

    /api/environments is the top-level call in the slow coordinator that
    explicitly propagates auth errors (unconditionally fetched every
    poll, unlike schedules) — everything else is gathered with
    return_exceptions=True."""
    client = _make_client()
    client.async_get_environments = AsyncMock(side_effect=DockhandAuthError("expired"))
    coord = _slow(hass, client)
    with pytest.raises(UpdateFailed, match="reauth"):
        await coord._async_update_data()


async def test_slow_general_error_raises_update_failed(hass: HomeAssistant):
    """The outer _async_update_data try/except still wraps unexpected
    errors as UpdateFailed — exercised here via a broken fast_coordinator
    reference, since every per-env call inside _fetch() itself is now
    gathered with return_exceptions=True and gracefully logged rather
    than raised (no remaining call path produces an unhandled generic
    exception on its own)."""
    fast_mock = MagicMock()
    fast_mock.data = MagicMock()
    fast_mock.data.get = MagicMock(side_effect=Exception("broken"))
    client = _make_client()
    coord = _slow(hass, client, fast_coordinator=fast_mock)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


# ---------------------------------------------------------------------------
# Update coordinator — per-env update-check failure handling
# ---------------------------------------------------------------------------


async def test_update_coord_env_failure_preserves_previous_data(hass: HomeAssistant):
    """A per-environment update-check failure (Dockhand unreachable, etc.)
    must not look like "confirmed zero pending updates" for that
    environment — that would flip every container's update entity there
    to "up to date" when we simply don't know this cycle. Same
    last-known-good principle as the fast/slow coordinator fixes; see
    architecture.md §3."""
    client = _make_client()
    client.async_check_container_updates = AsyncMock(
        return_value=[{"containerId": "abc", "hasUpdate": True}]
    )
    coord = _update_coord(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["abc"]["hasUpdate"] is True

    client.async_check_container_updates = AsyncMock(side_effect=Exception("timeout"))
    await coord.async_refresh()
    # Overall update still "succeeds" (per-env failures are caught, not
    # raised) but this environment's data must be unchanged, not emptied.
    assert coord.data["environments"][1]["abc"]["hasUpdate"] is True


async def test_update_coord_new_env_failure_is_empty_not_missing(hass: HomeAssistant):
    """An environment with no previous data that fails its first update
    check has nothing to "preserve" — it should get an empty dict, not
    a KeyError, and not be silently absent from coord.data."""
    client = _make_client()
    client.async_check_container_updates = AsyncMock(side_effect=Exception("timeout"))
    coord = _update_coord(hass, client)
    await coord.async_refresh()
    assert coord.data == {"environments": {1: {}}}


async def test_async_check_environment_only_touches_its_own_environment(
    hass: HomeAssistant,
):
    """The actual design fix from this session: a per-environment "Check
    for updates" button used to trigger a full coordinator refresh
    (async_refresh()), which always checks every environment in one
    gather — so pressing environment 1's button silently also re-checked
    every other environment too, a real mismatch between what the
    button's device implies and what pressing it actually does.
    async_check_environment() is genuinely scoped: checking environment 1
    must leave environment 2's already-known data completely untouched."""
    client = _make_client()
    client.async_check_container_updates = AsyncMock(
        return_value=[{"containerId": "abc", "hasUpdate": True}]
    )
    fast_coordinator = MagicMock()
    fast_coordinator.data = {
        "environments": {
            1: {"stats": {"name": "one"}},
            2: {"stats": {"name": "two"}},
        }
    }
    coord = _update_coord(hass, client, fast_coordinator=fast_coordinator)
    await coord.async_refresh()  # seeds both envs via the normal full path
    assert coord.data["environments"][1]["abc"]["hasUpdate"] is True
    assert coord.data["environments"][2]["abc"]["hasUpdate"] is True

    client.async_check_container_updates = AsyncMock(
        return_value=[{"containerId": "xyz", "hasUpdate": False}]
    )
    await coord.async_check_environment(1)
    client.async_check_container_updates.assert_called_once_with(1)
    assert coord.data["environments"][1] == {
        "xyz": {"containerId": "xyz", "hasUpdate": False}
    }
    # Environment 2's data must be exactly what it was before — untouched
    # by a check that was only ever supposed to be about environment 1.
    assert coord.data["environments"][2]["abc"]["hasUpdate"] is True


async def test_async_check_environment_raises_on_failure(hass: HomeAssistant):
    """Deliberately different from _fetch()'s per-environment resilience
    (which falls back to last-known-good data and never raises): this is
    an explicit user action via a button press, and silently falling back
    to stale data here would make a failed check look like nothing
    happened — the opposite of what pressing a button should communicate."""
    client = _make_client()
    client.async_check_container_updates = AsyncMock(side_effect=Exception("boom"))
    coord = _update_coord(hass, client)
    with pytest.raises(Exception, match="boom"):
        await coord.async_check_environment(1)


async def test_async_check_environment_marks_coordinator_successful(
    hass: HomeAssistant,
):
    client = _make_client()
    client.async_check_container_updates = AsyncMock(return_value=[])
    coord = _update_coord(hass, client)
    await coord.async_check_environment(1)
    assert coord.last_update_success is True


# ---------------------------------------------------------------------------
# _sync_fetch_issues — HA Repair issues for fetch failures
# ---------------------------------------------------------------------------


def _slow_with_entry(
    hass: HomeAssistant, client, config=None
) -> DockhandSlowCoordinator:
    """Same as _slow() above, but with a real, registered config entry —
    needed here specifically because _sync_fetch_issues silently no-ops
    without one (see its own doc comment: nothing meaningful to attach
    issue tracking to in that case). Every other test in this file
    doesn't need this, since none of them exercise issue creation."""
    entry = MockConfigEntry(domain="dockhand", title="test")
    entry.add_to_hass(hass)
    fast_coordinator = MagicMock()
    fast_coordinator.data = {"environments": {1: {"stats": {"name": "local"}}}}
    coord = DockhandSlowCoordinator(
        hass,
        client,
        config
        or {
            "enable_images": True,
            "enable_schedules": True,
        },
        fast_coordinator,
        entry=entry,
    )
    return coord


async def test_sync_creates_issue_for_top_level_fetch_failure(hass: HomeAssistant):
    client = _make_client(envs=[ENV1])
    client.async_get_schedules = AsyncMock(side_effect=Exception("timeout"))
    coord = _slow_with_entry(hass, client)
    await coord.async_refresh()

    issue = ir.async_get(hass).async_get_issue(
        "dockhand", f"{coord.config_entry.entry_id}_fetch_failed_top_level_slow"
    )
    assert issue is not None
    assert issue.translation_key == "fetch_failed_top_level"
    assert issue.translation_placeholders == {"resources": "schedules"}


async def test_sync_clears_top_level_issue_once_fetch_recovers(hass: HomeAssistant):
    client = _make_client(envs=[ENV1])
    client.async_get_schedules = AsyncMock(side_effect=Exception("timeout"))
    coord = _slow_with_entry(hass, client)
    await coord.async_refresh()
    issue_id = f"{coord.config_entry.entry_id}_fetch_failed_top_level_slow"
    assert ir.async_get(hass).async_get_issue("dockhand", issue_id) is not None

    # Recovery: the same call now succeeds.
    client.async_get_schedules = AsyncMock(return_value=[])
    await coord.async_refresh()
    assert ir.async_get(hass).async_get_issue("dockhand", issue_id) is None


async def test_sync_creates_issue_for_per_environment_fetch_failure(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1])
    client.async_get_images = AsyncMock(side_effect=Exception("connection refused"))
    coord = _slow_with_entry(hass, client)
    await coord.async_refresh()

    issue_id = f"{coord.config_entry.entry_id}_fetch_failed_env_1_slow"
    issue = ir.async_get(hass).async_get_issue("dockhand", issue_id)
    assert issue is not None
    assert issue.translation_key == "fetch_failed_env"
    assert issue.translation_placeholders["env_name"] == "local"
    assert issue.translation_placeholders["resources"] == "images"


async def test_sync_clears_per_environment_issue_once_fetch_recovers(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1])
    client.async_get_images = AsyncMock(side_effect=Exception("connection refused"))
    coord = _slow_with_entry(hass, client)
    await coord.async_refresh()
    issue_id = f"{coord.config_entry.entry_id}_fetch_failed_env_1_slow"
    assert ir.async_get(hass).async_get_issue("dockhand", issue_id) is not None

    client.async_get_images = AsyncMock(return_value=[])
    await coord.async_refresh()
    assert ir.async_get(hass).async_get_issue("dockhand", issue_id) is None


async def test_sync_creates_no_issues_on_a_fully_successful_poll(hass: HomeAssistant):
    client = _make_client(envs=[ENV1])
    coord = _slow_with_entry(hass, client)
    await coord.async_refresh()

    all_issues = ir.async_get(hass).issues
    dockhand_issues = [k for k in all_issues if k[0] == "dockhand"]
    assert dockhand_issues == []


# ---------------------------------------------------------------------------
# Retry recovery, malformed pending-update items, per-environment isolation
# ---------------------------------------------------------------------------


async def test_fast_401_then_success_recovers_without_reauth(hass: HomeAssistant):
    """A single 401 (Dockhand restarting, say) is retried, not re-auth."""
    client = _make_client()
    client.async_get_all_dashboard_stats = AsyncMock(
        side_effect=[DockhandAuthError("blip"), [{**STATS1, "id": 1}]]
    )
    with patch("custom_components.dockhand.coordinator.asyncio.sleep", AsyncMock()):
        data = await _fast(hass, client)._async_update_data()
    assert 1 in data["environments"]
    assert client.async_get_all_dashboard_stats.await_count == 2


async def test_fast_pending_updates_skip_malformed_items(hass: HomeAssistant):
    client = _make_client(stats={**STATS1, "updateCheckEnabled": True})
    client.async_get_pending_updates = AsyncMock(
        return_value=[
            "junk",
            {"containerId": None},
            {"containerId": "abc", "hasImageUpdate": True},
        ]
    )
    data = await _fast(hass, client)._async_update_data()
    assert data["environments"][1]["pending_update_container_ids"] == {"abc"}


async def test_fast_one_environment_failing_does_not_fail_the_poll(
    hass: HomeAssistant,
):
    """An unexpected error while processing one environment is logged and
    that environment left out; the poll itself still succeeds."""
    from custom_components.dockhand import coordinator as coordinator_module

    real_safe_list = coordinator_module._safe_list
    bad = object()

    def safe_list(value):
        if value is bad:
            raise RuntimeError("bad data")
        return real_safe_list(value)

    client = _make_client(envs=[ENV1, ENV2])
    client.async_get_containers = AsyncMock(
        side_effect=lambda env_id: bad if env_id == 2 else [CONTAINER1]
    )
    with patch.object(coordinator_module, "_safe_list", side_effect=safe_list):
        data = await _fast(hass, client)._async_update_data()
    assert set(data["environments"]) == {1}


@pytest.mark.parametrize(
    ("which", "helper"), [("fast", "_safe_list"), ("slow", "_unwrap")]
)
async def test_a_cancelled_environment_fetch_is_not_mistaken_for_data(
    hass: HomeAssistant, which, helper
):
    """Cancellation inside one environment's fetch propagates instead of
    being unpacked as that environment's data, or logged and skipped."""
    from custom_components.dockhand import coordinator as coordinator_module

    real = getattr(coordinator_module, helper)
    marker = object()

    def cancel_on_marker(value, *args):
        if value is marker:
            raise asyncio.CancelledError
        return real(value, *args)

    client = _make_client()
    if which == "fast":
        client.async_get_containers = AsyncMock(return_value=marker)
        coord = _fast(hass, client)
    else:
        client.async_get_host_info = AsyncMock(return_value=marker)
        coord = _slow(hass, client)
    with (
        patch.object(coordinator_module, helper, side_effect=cancel_on_marker),
        pytest.raises(asyncio.CancelledError),
    ):
        await coord._async_update_data()


async def test_update_coord_cancelled_environment_fetch_propagates(
    hass: HomeAssistant,
):
    client = _make_client()
    client.async_check_container_updates = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await _update_coord(hass, client)._async_update_data()


async def test_slow_one_environment_failing_does_not_fail_the_poll(
    hass: HomeAssistant,
):
    from custom_components.dockhand import coordinator as coordinator_module

    real_unwrap = coordinator_module._unwrap
    bad = object()

    def unwrap(value, *args):
        if value is bad:
            raise RuntimeError("bad data")
        return real_unwrap(value, *args)

    client = _make_client()
    client.async_get_host_info = AsyncMock(return_value=bad)
    with patch.object(coordinator_module, "_unwrap", side_effect=unwrap):
        data = await _slow(hass, client)._async_update_data()
    assert data["environments"] == {}


async def test_fast_pending_updates_keep_pinned_digests_and_held_updates(
    hass: HomeAssistant,
):
    client = _make_client(stats={**STATS1, "updateCheckEnabled": True})
    client.async_get_pending_updates = AsyncMock(
        return_value=[
            {"containerId": "p", "hasImageUpdate": False, "pinnedToDigest": True},
            {
                "containerId": "h",
                "hasImageUpdate": False,
                "releaseAgeRemainingHours": 7,
            },
            {
                "containerId": "b",
                "hasImageUpdate": False,
                "releaseAgeRemainingHours": True,
            },
        ]
    )
    env = (await _fast(hass, client)._async_update_data())["environments"][1]
    details = env["pending_update_details"]
    assert details["p"]["pinnedToDigest"] is True
    assert details["h"]["releaseAgeRemainingHours"] == 7
    assert details["b"]["releaseAgeRemainingHours"] is None
    assert env["pending_update_container_ids"] == set()


# ---------------------------------------------------------------------------
# Update coordinator — Dockhand's own release, via /api/self-update/check
# ---------------------------------------------------------------------------

DOCKHAND_CONTAINER = {
    "id": "dh1",
    "name": "dockhand",
    "image": "fnsys/dockhand:v1.0.53",
    "systemContainer": "dockhand",
}
DOCKHAND_ROW = {
    "containerId": "dh1",
    "containerName": "dockhand",
    "hasUpdate": False,
    "systemContainer": "dockhand",
}
SELF_UPDATE_NEWER = {
    "updateAvailable": True,
    "currentImage": "fnsys/dockhand:v1.0.53",
    "newImage": "fnsys/dockhand:v1.0.56",
    "latestVersion": "1.0.56",
    "containerName": "dockhand",
}


def _fast_with_dockhand(connection_type: str | None = "socket", containers=None):
    fast = MagicMock()
    stats = {"name": "local"}
    if connection_type is not None:
        stats["connectionType"] = connection_type
    fast.data = {
        "environments": {
            1: {
                "stats": stats,
                "containers": containers
                if containers is not None
                else [DOCKHAND_CONTAINER, CONTAINER1],
            }
        }
    }
    return fast


def _self_update_client(self_update=None, rows=None):
    client = _make_client()
    client.async_check_container_updates = AsyncMock(
        return_value=rows if rows is not None else [DOCKHAND_ROW]
    )
    client.async_check_self_update = AsyncMock(
        return_value=self_update if self_update is not None else SELF_UPDATE_NEWER
    )
    return client


async def test_self_update_adds_newer_version_to_dockhand_row(hass: HomeAssistant):
    client = _self_update_client()
    coord = _update_coord(hass, client, _fast_with_dockhand())
    await coord.async_refresh()

    newer = coord.data["environments"][1]["dh1"]["newerVersion"]
    assert newer == {"tag": "v1.0.56", "source": "self-update", "bump": "patch"}
    assert coord.self_update == {
        "env_id": 1,
        "container_id": "dh1",
        "newerVersion": newer,
    }


async def test_self_update_cleared_once_up_to_date(hass: HomeAssistant):
    client = _self_update_client()
    coord = _update_coord(hass, client, _fast_with_dockhand())
    await coord.async_refresh()
    client.async_check_self_update = AsyncMock(
        return_value={
            "updateAvailable": False,
            "currentImage": "fnsys/dockhand:v1.0.56",
        }
    )
    await coord.async_refresh()
    assert not coord.data["environments"][1]["dh1"].get("newerVersion")
    assert coord.self_update is None


@pytest.mark.parametrize("connection_type", ["hawser-standard", "hawser-edge"])
async def test_self_update_skipped_without_socket_or_direct_host(
    hass: HomeAssistant, connection_type: str
):
    """Through Hawser, Dockhand can't inspect its own container, so the
    check would only ever fail with ENOENT."""
    client = _self_update_client()
    coord = _update_coord(hass, client, _fast_with_dockhand(connection_type))
    await coord.async_refresh()
    client.async_check_self_update.assert_not_called()
    assert coord.self_update is None


async def test_self_update_skipped_when_dockhand_not_listed(hass: HomeAssistant):
    client = _self_update_client()
    coord = _update_coord(hass, client, _fast_with_dockhand(containers=[CONTAINER1]))
    await coord.async_refresh()
    client.async_check_self_update.assert_not_called()


@pytest.mark.parametrize("connection_type", ["direct", None])
async def test_self_update_runs_for_direct_or_untyped_env(
    hass: HomeAssistant, connection_type: str | None
):
    client = _self_update_client()
    coord = _update_coord(hass, client, _fast_with_dockhand(connection_type))
    await coord.async_refresh()
    assert coord.data["environments"][1]["dh1"]["newerVersion"]["tag"] == "v1.0.56"


@pytest.mark.parametrize(
    "response",
    [
        {"updateAvailable": False, "error": "Check failed: Error: connect ENOENT"},
        # A floating tag: check-updates already reports this one itself.
        {
            "updateAvailable": True,
            "currentImage": "fnsys/dockhand:latest",
            "newImage": "fnsys/dockhand:latest",
            "newDigest": "sha256:abc",
        },
    ],
)
async def test_self_update_without_newer_release_adds_nothing(
    hass: HomeAssistant, response: dict
):
    client = _self_update_client(response)
    coord = _update_coord(hass, client, _fast_with_dockhand())
    await coord.async_refresh()
    assert not coord.data["environments"][1]["dh1"].get("newerVersion")
    assert coord.self_update is None


async def test_self_update_failure_is_silent_and_keeps_last_result(
    hass: HomeAssistant,
):
    client = _self_update_client()
    coord = _update_coord(hass, client, _fast_with_dockhand())
    await coord.async_refresh()
    client.async_check_self_update = AsyncMock(side_effect=Exception("API error 403"))
    await coord.async_refresh()
    assert coord.last_update_success is True
    assert coord.data["environments"][1]["dh1"]["newerVersion"]["tag"] == "v1.0.56"


async def test_self_update_never_replaces_check_updates_newer_version(
    hass: HomeAssistant,
):
    row = {**DOCKHAND_ROW, "newerVersion": {"tag": "v1.0.55", "bump": "patch"}}
    client = _self_update_client(rows=[row])
    coord = _update_coord(hass, client, _fast_with_dockhand())
    await coord.async_refresh()
    assert coord.data["environments"][1]["dh1"]["newerVersion"]["tag"] == "v1.0.55"


async def test_self_update_dropped_once_dockhand_recreated(hass: HomeAssistant):
    client = _self_update_client()
    fast = _fast_with_dockhand()
    coord = _update_coord(hass, client, fast)
    await coord.async_refresh()

    recreated = {**DOCKHAND_CONTAINER, "id": "dh2"}
    fast.data["environments"][1]["containers"] = [recreated]
    client.async_check_container_updates = AsyncMock(
        return_value=[{**DOCKHAND_ROW, "containerId": "dh2"}]
    )
    client.async_check_self_update = AsyncMock(
        return_value={
            "updateAvailable": False,
            "currentImage": "fnsys/dockhand:v1.0.56",
        }
    )
    await coord.async_refresh()
    assert "dh1" not in coord.data["environments"][1]
    assert not coord.data["environments"][1]["dh2"].get("newerVersion")


async def test_self_update_survives_merged_check_results(hass: HomeAssistant):
    """A "Check for updates" press replaces the environment's rows; the
    self-update result must be carried onto the new ones."""
    client = _self_update_client()
    coord = _update_coord(hass, client, _fast_with_dockhand())
    await coord.async_refresh()
    coord.async_merge_check_results(1, [dict(DOCKHAND_ROW)])
    assert coord.data["environments"][1]["dh1"]["newerVersion"]["tag"] == "v1.0.56"


async def test_refresh_self_update_only_for_dockhand_host_env(hass: HomeAssistant):
    client = _self_update_client({"updateAvailable": False})
    coord = _update_coord(hass, client, _fast_with_dockhand())
    await coord.async_refresh()
    client.async_check_self_update.reset_mock()
    client.async_check_self_update.return_value = SELF_UPDATE_NEWER

    await coord.async_refresh_self_update(2)
    client.async_check_self_update.assert_not_called()

    await coord.async_refresh_self_update(1)
    client.async_check_self_update.assert_awaited_once()
    assert coord.data["environments"][1]["dh1"]["newerVersion"]["tag"] == "v1.0.56"


async def test_self_update_picks_container_by_name_when_ambiguous(
    hass: HomeAssistant,
):
    other = {**DOCKHAND_CONTAINER, "id": "dh-other", "name": "dockhand-test"}
    client = _self_update_client(
        rows=[DOCKHAND_ROW, {**DOCKHAND_ROW, "containerId": "dh-other"}]
    )
    coord = _update_coord(
        hass, client, _fast_with_dockhand(containers=[DOCKHAND_CONTAINER, other])
    )
    await coord.async_refresh()
    assert coord.data["environments"][1]["dh1"]["newerVersion"]["tag"] == "v1.0.56"
    assert not coord.data["environments"][1]["dh-other"].get("newerVersion")


@pytest.mark.parametrize(
    ("current", "new", "tag", "bump"),
    [
        ("fnsys/dockhand:v1.0.53", "fnsys/dockhand:v1.0.56", "v1.0.56", "patch"),
        ("fnsys/dockhand:v1.0.53", "fnsys/dockhand:v1.1.0", "v1.1.0", "minor"),
        (
            "reg.local:5000/dockhand:v1.9.2-baseline",
            "reg.local:5000/dockhand:v2.0.0-baseline",
            "v2.0.0-baseline",
            "major",
        ),
    ],
)
def test_self_update_newer_version_tag_and_bump(current, new, tag, bump):
    newer = coordinator_module._self_update_newer_version(
        {
            "updateAvailable": True,
            "currentImage": current,
            "newImage": new,
            "latestVersion": tag.lstrip("v"),
        }
    )
    assert newer == {"tag": tag, "source": "self-update", "bump": bump}


async def test_refresh_self_update_removes_result_once_up_to_date(
    hass: HomeAssistant,
):
    client = _self_update_client()
    coord = _update_coord(hass, client, _fast_with_dockhand())
    await coord.async_refresh()
    client.async_check_self_update.return_value = {"updateAvailable": False}
    await coord.async_refresh_self_update(1)
    assert not coord.data["environments"][1]["dh1"].get("newerVersion")


@pytest.mark.parametrize(
    "response",
    [
        # No tag to name.
        {"updateAvailable": True, "latestVersion": "1.0.56", "newImage": "dockhand"},
    ],
)
def test_self_update_newer_version_needs_a_tag(response):
    assert coordinator_module._self_update_newer_version(response) is None


@pytest.mark.parametrize(
    ("current", "new"),
    [("nightly", "v1.0.56"), ("v1.0.56", "v1.0.56-baseline")],
)
def test_version_bump_unknown(current, new):
    assert coordinator_module._version_bump(current, new) is None
