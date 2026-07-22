"""Tests for DockhandFastCoordinator and DockhandSlowCoordinator."""

from __future__ import annotations

import pytest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.dockhand.api import DockhandAuthError, DockhandClient
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
    return DockhandFastCoordinator(
        hass, client, config or {"poll_interval": 30}, entry=entry
    )


def _update_coord(hass: HomeAssistant, client, fast_coordinator=None):
    if fast_coordinator is None:
        fast_coordinator = MagicMock()
        fast_coordinator.data = {"environments": {1: {"stats": {"name": "local"}}}}
    return DockhandUpdateCoordinator(
        hass, client, fast_coordinator, {"poll_interval_updates": 86400}
    )


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
            "poll_interval_slow": 300,
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
    coord = _fast(hass, client, config={"enable_container_stats": True})
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
    coord = _fast(hass, client)  # default config — enable_container_stats off
    await coord.async_refresh()
    assert coord.data["environments"][1]["container_stats"] == {}
    client.async_get_container_stats.assert_not_called()


async def test_fast_container_stats_fetched_when_enabled(hass: HomeAssistant):
    client = _make_client()
    client.async_get_container_stats = AsyncMock(
        return_value=[{"name": "nginx", "cpuPercent": 1.5}]
    )
    coord = _fast(hass, client, config={"enable_container_stats": True})
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


async def test_fast_pending_updates_not_fetched_when_update_check_disabled(
    hass: HomeAssistant,
):
    """Gated per-environment on updateCheckEnabled (from dashboard stats,
    Dockhand's own setting) — not a config option on our side at all."""
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": False})
    coord = _fast(hass, client, config={"poll_interval": 30})
    await coord.async_refresh()
    client.async_get_pending_updates.assert_not_called()
    assert coord.data["environments"][1]["pending_update_container_ids"] == set()


async def test_fast_pending_updates_fetched_when_update_check_enabled(
    hass: HomeAssistant,
):
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": True})
    client.async_get_pending_updates = AsyncMock(
        return_value=[{"containerId": "abc", "containerName": "web"}]
    )
    coord = _fast(hass, client, config={"poll_interval": 30})
    await coord.async_refresh()
    client.async_get_pending_updates.assert_called_once_with(1)
    assert coord.data["environments"][1]["pending_update_container_ids"] == {"abc"}


async def test_fast_pending_updates_failure_returns_empty_set(hass: HomeAssistant):
    client = _make_client(envs=[ENV1], stats={**STATS1, "updateCheckEnabled": True})
    client.async_get_pending_updates = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client, config={"poll_interval": 30})
    await coord.async_refresh()
    assert coord.data["environments"][1]["pending_update_container_ids"] == set()


async def test_fast_update_interval_from_config(hass: HomeAssistant):
    coord = _fast(hass, _make_client(envs=[]), config={"poll_interval": 90})
    assert coord.update_interval == timedelta(seconds=90)


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
            "poll_interval_slow": 300,
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
            "poll_interval_slow": 300,
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
    the hawser version sensor falls back to /api/environments itself."""
    client = _make_client(envs=[ENV1])
    client.async_get_host_info = AsyncMock(side_effect=Exception("timeout"))
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["host"] == {}


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
        config={"poll_interval_slow": 300, "enable_runtime_controls": True},
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
        config={"poll_interval_slow": 300, "enable_runtime_controls": True},
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


async def test_slow_feature_api_failure_returns_empty(hass: HomeAssistant):
    client = _make_client(envs=[ENV1])
    client.async_get_images = AsyncMock(side_effect=Exception("timeout"))
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["images"] == []


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


async def test_slow_update_interval_from_config(hass: HomeAssistant):
    coord = _slow(hass, _make_client(envs=[]), config={"poll_interval_slow": 1200})
    assert coord.update_interval == timedelta(seconds=1200)


# ---------------------------------------------------------------------------
# Update coordinator — per-env update-check failure handling
# ---------------------------------------------------------------------------


async def test_update_coord_env_failure_preserves_previous_data(hass: HomeAssistant):
    """A per-environment update-check failure (Dockhand unreachable, etc.)
    must not look like "confirmed zero pending updates" for that
    environment — that would flip every container's update entity there
    to "up to date" when we simply don't know this cycle. Same
    last-known-good principle as the fast/slow coordinator fixes; see
    ARCHITECTURE.md §3."""
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
