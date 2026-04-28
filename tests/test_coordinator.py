"""Tests for DockhandFastCoordinator and DockhandSlowCoordinator."""
from __future__ import annotations
import asyncio, sys, os, unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT); sys.path.insert(0, TESTS)

import ha_stubs as stubs; stubs.install()
from ha_stubs import HomeAssistant, ConfigEntry, ConfigEntryAuthFailed, UpdateFailed
from custom_components.dockhand.api import (
    DockhandClient, DockhandAuthError,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator, DockhandSlowCoordinator,
    _safe_list, _safe_dict, _unwrap,
)

run = asyncio.get_event_loop().run_until_complete

ENV1 = {"id": 1, "name": "local"}
ENV2 = {"id": 2, "name": "remote"}
STATS1 = {"name": "local", "cpu": 10.5,
           "containers": {"running": 2, "stopped": 1}}
CONTAINER1 = {"id": "abc", "name": "web", "state": "running", "labels": {}}
STACK1 = {"name": "myapp", "status": "running", "containers": 2}
IMAGE1 = {"id": "sha256:deadbeef", "size": 104857600}
NETWORK1 = {"id": "net1", "name": "bridge", "containers": {}}
VOLUME1 = {"Name": "mydata", "UsageData": {"Size": 10485760}}


def _make_client(envs=None, stats=None, containers=None, stacks=None,
                 images=None, networks=None, volumes=None, schedules=None):
    c = MagicMock(spec=DockhandClient)
    c.async_get_environments = AsyncMock(return_value=envs if envs is not None else [ENV1])
    c.async_get_dashboard_stats = AsyncMock(return_value=stats or STATS1)
    c.async_get_containers = AsyncMock(return_value=containers if containers is not None else [CONTAINER1])
    c.async_get_stacks = AsyncMock(return_value=stacks or [])
    c.async_get_images = AsyncMock(return_value=images or [IMAGE1])
    c.async_get_networks = AsyncMock(return_value=networks or [NETWORK1])
    c.async_get_volumes = AsyncMock(return_value=volumes or [VOLUME1])
    c.async_get_schedules = AsyncMock(return_value=schedules or [])
    return c


def _fast(client, config=None, entry=None):
    return DockhandFastCoordinator(
        HomeAssistant(), client, config or {"poll_interval": 30}, entry=entry)


def _slow(client, config=None):
    return DockhandSlowCoordinator(HomeAssistant(), client, config or {
        "poll_interval_slow": 300,
        "enable_images": True, "enable_networks": True,
        "enable_volumes": True, "enable_schedules": True,
    })


# ── Helpers ──────────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_safe_list_with_list(self): self.assertEqual(_safe_list([1, 2]), [1, 2])
    def test_safe_list_with_none(self): self.assertEqual(_safe_list(None), [])
    def test_safe_list_with_dict(self): self.assertEqual(_safe_list({"a": 1}), [])
    def test_safe_dict_with_dict(self): self.assertEqual(_safe_dict({"a": 1}), {"a": 1})
    def test_safe_dict_with_list(self): self.assertEqual(_safe_dict([1, 2]), {})
    def test_safe_dict_with_none(self): self.assertEqual(_safe_dict(None), {})
    def test_unwrap_value(self): self.assertEqual(_unwrap("ok", "d", "t"), "ok")
    def test_unwrap_exception(self): self.assertEqual(_unwrap(ValueError(), "d", "t"), "d")


# ── Fast coordinator — data shape ─────────────────────────────────────────────

class TestFastData(unittest.TestCase):

    def test_basic_shape(self):
        coord = _fast(_make_client(stacks=[STACK1]))
        run(coord.async_config_entry_first_refresh())
        self.assertIn(1, coord.data)
        self.assertEqual(coord.data[1]["stats"], STATS1)
        self.assertEqual(coord.data[1]["containers"], [CONTAINER1])
        self.assertEqual(coord.data[1]["stacks"], [STACK1])

    def test_multiple_envs(self):
        client = _make_client(envs=[ENV1, ENV2])
        client.async_get_dashboard_stats = AsyncMock(
            side_effect=lambda eid: {"name": f"env{eid}"})
        client.async_get_containers = AsyncMock(return_value=[])
        client.async_get_stacks = AsyncMock(return_value=[])
        coord = _fast(client)
        run(coord.async_config_entry_first_refresh())
        self.assertIn(1, coord.data)
        self.assertIn(2, coord.data)

    def test_containers_failure_returns_empty(self):
        client = _make_client()
        client.async_get_containers = AsyncMock(side_effect=Exception("timeout"))
        coord = _fast(client)
        run(coord.async_config_entry_first_refresh())
        self.assertEqual(coord.data[1]["containers"], [])

    def test_stats_failure_returns_empty_dict(self):
        client = _make_client()
        client.async_get_dashboard_stats = AsyncMock(side_effect=Exception("timeout"))
        coord = _fast(client)
        run(coord.async_config_entry_first_refresh())
        self.assertEqual(coord.data[1]["stats"], {})

    def test_empty_env_list_returns_empty_data(self):
        client = _make_client(envs=[])
        coord = _fast(client)
        run(coord.async_config_entry_first_refresh())
        self.assertEqual(coord.data, {})

    def test_update_interval_from_config(self):
        coord = _fast(_make_client(envs=[]), config={"poll_interval": 90})
        self.assertEqual(coord.update_interval, timedelta(seconds=90))


# ── Fast coordinator — auth ───────────────────────────────────────────────────

class TestFastAuth(unittest.TestCase):

    def test_auth_error_raises_config_entry_auth_failed(self):
        """A 401 from the API must surface as ConfigEntryAuthFailed immediately.
        With token auth there is no silent re-login — HA prompts the user to
        provide a new token via the re-authentication flow.
        """
        client = _make_client()
        client.async_get_environments = AsyncMock(
            side_effect=DockhandAuthError("token revoked"))
        with self.assertRaises(ConfigEntryAuthFailed):
            run(_fast(client).async_config_entry_first_refresh())

    def test_auth_error_message_mentions_token(self):
        """The ConfigEntryAuthFailed message should mention the token so the
        HA notification gives the user a useful hint."""
        client = _make_client()
        client.async_get_environments = AsyncMock(
            side_effect=DockhandAuthError("expired"))
        with self.assertRaises(ConfigEntryAuthFailed) as ctx:
            run(_fast(client).async_config_entry_first_refresh())
        self.assertIn("token", str(ctx.exception).lower())

    def test_general_error_raises_update_failed(self):
        client = _make_client()
        client.async_get_environments = AsyncMock(
            side_effect=Exception("network down"))
        coord = _fast(client)
        with self.assertRaises(UpdateFailed):
            run(coord.async_config_entry_first_refresh())


# ── Slow coordinator ──────────────────────────────────────────────────────────

class TestSlowData(unittest.TestCase):

    def test_all_features_fetches_everything(self):
        client = _make_client(envs=[ENV1], images=[IMAGE1],
                               networks=[NETWORK1], volumes=[VOLUME1],
                               schedules=[{"id": "s1"}])
        coord = _slow(client)
        run(coord.async_config_entry_first_refresh())
        env = coord.data["environments"][1]
        self.assertEqual(env["images"], [IMAGE1])
        self.assertEqual(env["networks"], [NETWORK1])
        self.assertEqual(env["volumes"], [VOLUME1])
        self.assertEqual(coord.data["schedules"], [{"id": "s1"}])

    def test_all_features_disabled(self):
        client = _make_client(envs=[ENV1])
        coord = _slow(client, config={
            "poll_interval_slow": 300,
            "enable_images": False, "enable_networks": False,
            "enable_volumes": False, "enable_schedules": False,
        })
        run(coord.async_config_entry_first_refresh())
        client.async_get_images.assert_not_called()
        client.async_get_networks.assert_not_called()
        client.async_get_volumes.assert_not_called()
        client.async_get_schedules.assert_not_called()
        self.assertEqual(coord.data["schedules"], [])

    def test_only_images_enabled(self):
        client = _make_client(envs=[ENV1], images=[IMAGE1])
        coord = _slow(client, config={
            "poll_interval_slow": 300, "enable_images": True,
            "enable_networks": False, "enable_volumes": False,
            "enable_schedules": False,
        })
        run(coord.async_config_entry_first_refresh())
        client.async_get_images.assert_called_once_with(1)
        client.async_get_networks.assert_not_called()
        env = coord.data["environments"][1]
        self.assertEqual(env["images"], [IMAGE1])
        self.assertEqual(env["networks"], [])
        self.assertEqual(env["volumes"], [])

    def test_env_object_stored(self):
        coord = _slow(_make_client(envs=[ENV1]))
        run(coord.async_config_entry_first_refresh())
        self.assertEqual(coord.data["environments"][1]["env"], ENV1)

    def test_feature_api_failure_returns_empty(self):
        client = _make_client(envs=[ENV1])
        client.async_get_images = AsyncMock(side_effect=Exception("timeout"))
        coord = _slow(client)
        run(coord.async_config_entry_first_refresh())
        self.assertEqual(coord.data["environments"][1]["images"], [])

    def test_auth_error_raises_update_failed_with_message(self):
        client = _make_client()
        client.async_get_environments = AsyncMock(
            side_effect=DockhandAuthError("expired"))
        coord = _slow(client)
        with self.assertRaises(UpdateFailed) as ctx:
            run(coord.async_config_entry_first_refresh())
        self.assertIn("reauth", str(ctx.exception))

    def test_general_error_raises_update_failed(self):
        client = _make_client()
        client.async_get_environments = AsyncMock(
            side_effect=Exception("network down"))
        coord = _slow(client)
        with self.assertRaises(UpdateFailed):
            run(coord.async_config_entry_first_refresh())

    def test_update_interval_from_config(self):
        coord = _slow(_make_client(envs=[]),
                      config={"poll_interval_slow": 1200})
        self.assertEqual(coord.update_interval, timedelta(seconds=1200))


if __name__ == "__main__":
    unittest.main()
