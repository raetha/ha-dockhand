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
    return c


def _fast(hass: HomeAssistant, client, config=None, entry=None):
    return DockhandFastCoordinator(
        hass, client, config or {"poll_interval": 30}, entry=entry
    )


def _slow(hass: HomeAssistant, client, config=None):
    return DockhandSlowCoordinator(
        hass,
        client,
        config or {
            "poll_interval_slow": 300,
            "enable_images": True,
            "enable_networks": True,
            "enable_volumes": True,
            "enable_schedules": True,
        },
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
    assert 1 in coord.data
    stats = coord.data[1]["stats"]
    assert stats["name"] == STATS1["name"]
    assert stats["cpu"] == STATS1["cpu"]
    assert coord.data[1]["containers"] == [CONTAINER1]
    assert coord.data[1]["stacks"] == [STACK1]
    assert "container_stats" in coord.data[1]


async def test_fast_container_stats_indexed_by_name(hass: HomeAssistant):
    """container_stats dict is keyed by container name for O(1) sensor lookup."""
    client = _make_client()
    client.async_get_container_stats = AsyncMock(
        return_value=[
            {"name": "nginx", "cpuPercent": 1.5, "memoryUsage": 52428800},
            {"name": "redis", "cpuPercent": 0.2, "memoryUsage": 10485760},
        ]
    )
    coord = _fast(hass, client)
    await coord.async_refresh()
    cs = coord.data[1]["container_stats"]
    assert "nginx" in cs
    assert "redis" in cs
    assert cs["nginx"]["cpuPercent"] == 1.5


async def test_fast_container_stats_failure_returns_empty_dict(hass: HomeAssistant):
    """A stats API failure is non-fatal — containers and stacks still update."""
    client = _make_client()
    client.async_get_container_stats = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.data[1]["container_stats"] == {}
    assert coord.data[1]["containers"] == [CONTAINER1]


async def test_fast_multiple_envs(hass: HomeAssistant):
    client = _make_client(envs=[ENV1, ENV2])
    client.async_get_all_dashboard_stats = AsyncMock(
        return_value=[{"id": 1, "name": "env1"}, {"id": 2, "name": "env2"}]
    )
    client.async_get_containers = AsyncMock(return_value=[])
    client.async_get_stacks = AsyncMock(return_value=[])
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert 1 in coord.data
    assert 2 in coord.data


async def test_fast_containers_failure_returns_empty(hass: HomeAssistant):
    client = _make_client()
    client.async_get_containers = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.data[1]["containers"] == []


async def test_fast_stats_failure_returns_empty_dict(hass: HomeAssistant):
    client = _make_client()
    client.async_get_all_dashboard_stats = AsyncMock(side_effect=Exception("timeout"))
    coord = _fast(hass, client)
    await coord.async_refresh()
    assert coord.data[1]["stats"] == {}


async def test_fast_empty_env_list_returns_empty_data(hass: HomeAssistant):
    coord = _fast(hass, _make_client(envs=[]))
    await coord.async_refresh()
    assert coord.data == {}


async def test_fast_update_interval_from_config(hass: HomeAssistant):
    coord = _fast(hass, _make_client(envs=[]), config={"poll_interval": 90})
    assert coord.update_interval == timedelta(seconds=90)


# ---------------------------------------------------------------------------
# Fast coordinator — auth / error propagation
# ---------------------------------------------------------------------------


async def test_fast_auth_error_raises_config_entry_auth_failed(hass: HomeAssistant):
    """A 401 from the API must surface as ConfigEntryAuthFailed immediately."""
    client = _make_client()
    client.async_get_environments = AsyncMock(
        side_effect=DockhandAuthError("token revoked")
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await _fast(hass, client)._async_update_data()


async def test_fast_auth_error_message_mentions_token(hass: HomeAssistant):
    """The ConfigEntryAuthFailed message should mention the token."""
    client = _make_client()
    client.async_get_environments = AsyncMock(
        side_effect=DockhandAuthError("expired")
    )
    with pytest.raises(ConfigEntryAuthFailed, match="token"):
        await _fast(hass, client)._async_update_data()


async def test_fast_general_error_raises_update_failed(hass: HomeAssistant):
    client = _make_client()
    client.async_get_environments = AsyncMock(side_effect=Exception("network down"))
    with pytest.raises(UpdateFailed):
        await _fast(hass, client)._async_update_data()


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


async def test_slow_env_object_stored(hass: HomeAssistant):
    coord = _slow(hass, _make_client(envs=[ENV1]))
    await coord.async_refresh()
    assert coord.data["environments"][1]["env"] == ENV1


async def test_slow_feature_api_failure_returns_empty(hass: HomeAssistant):
    client = _make_client(envs=[ENV1])
    client.async_get_images = AsyncMock(side_effect=Exception("timeout"))
    coord = _slow(hass, client)
    await coord.async_refresh()
    assert coord.data["environments"][1]["images"] == []


async def test_slow_auth_error_raises_update_failed_with_message(hass: HomeAssistant):
    """DockhandAuthError is wrapped in UpdateFailed by _async_update_data."""
    client = _make_client()
    client.async_get_environments = AsyncMock(
        side_effect=DockhandAuthError("expired")
    )
    coord = _slow(hass, client)
    with pytest.raises(UpdateFailed, match="reauth"):
        await coord._async_update_data()


async def test_slow_general_error_raises_update_failed(hass: HomeAssistant):
    client = _make_client()
    client.async_get_environments = AsyncMock(side_effect=Exception("network down"))
    coord = _slow(hass, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_slow_update_interval_from_config(hass: HomeAssistant):
    coord = _slow(hass, _make_client(envs=[]), config={"poll_interval_slow": 1200})
    assert coord.update_interval == timedelta(seconds=1200)
