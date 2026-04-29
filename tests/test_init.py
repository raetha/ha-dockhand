"""
Tests for async_setup_entry, _register_devices, _remove_stale_devices (__init__.py).

Covers:
- async_setup_entry: success path, no-cookie triggers login, auth failure raises
  ConfigEntryAuthFailed, fast coordinator failure raises ConfigEntryNotReady,
  slow coordinator failure is non-fatal
- _register_devices: env hub always created, Containers group only for freestanding,
  Stacks group only when stacks exist, optional groups gated on slow data + enable flag,
  Schedules hub when enable_schedules=True
- _remove_stale_devices: removes stale container/stack device registry entries,
  preserves env and group devices, preserves live resource devices
- _remove_stale_entities: removes stale image/network/volume entity registry entries
  with three safety guards (last_update_success, non-empty env data, per-env scoping)
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

import ha_stubs as stubs

stubs.install()
from ha_stubs import (
    ConfigEntry,
    ConfigEntryNotReady,
    HomeAssistant,
    reset_registry,
)

from custom_components.dockhand import (
    DockhandData,
    _register_devices,
    _remove_stale_devices,
    _remove_stale_entities,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
)

run = asyncio.run

ENV1_STATS = {"name": "MyHost"}
CONTAINER_FREE = {"id": "c1", "name": "nginx", "labels": {}}
CONTAINER_COMPOSE = {
    "id": "c2",
    "name": "web",
    "labels": {"com.docker.compose.project": "myapp"},
}
STACK1 = {"name": "myapp", "status": "running"}


def _make_fast_coordinator(data, entry=None):
    coord = MagicMock(spec=DockhandFastCoordinator)
    coord.data = data
    coord.async_config_entry_first_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_slow_coordinator(data, entry=None):
    coord = MagicMock(spec=DockhandSlowCoordinator)
    coord.data = data
    coord.last_update_success = True
    coord.async_config_entry_first_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_entry(data=None, options=None):
    d = {
        "api_url": "http://dh.test:3000",
        "api_token": "dh_test_token",
        "enable_schedules": False,
        "enable_images": False,
        "enable_volumes": False,
        "enable_networks": False,
    }
    if data:
        d.update(data)
    return ConfigEntry(data=d, options=options or {})


def _make_registry():
    reset_registry()
    from ha_stubs import async_get

    hass = HomeAssistant()
    return async_get(hass), hass


# ── _register_devices ─────────────────────────────────────────────────────────


class TestRegisterDevices(unittest.TestCase):
    def setUp(self):
        reset_registry()

    def _run(self, fast_data, slow_data=None, config_overrides=None):
        reg, hass = _make_registry()
        entry = _make_entry(data=config_overrides)
        fast = _make_fast_coordinator(fast_data)
        slow_d = slow_data or {"environments": {}, "schedules": []}
        slow = _make_slow_coordinator(slow_d)
        config = {**entry.data}
        _register_devices(hass, entry, fast, slow, config, "http://dh.test:3000")
        return reg, entry

    def _identifiers(self, reg, entry):
        devs = reg.async_entries_for_config_entry(entry.entry_id)
        return {list(d.identifiers)[0][1] for d in devs}

    def test_env_hub_always_created(self):
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
        )
        ids = self._identifiers(reg, entry)
        self.assertIn("env_1", ids)

    def test_env_hub_uses_stats_name(self):
        reg, entry = self._run(
            {1: {"stats": {"name": "MyHost"}, "containers": [], "stacks": []}}
        )
        created = next(
            c for c in reg._created if c["identifiers"] == {("dockhand", "env_1")}
        )
        self.assertEqual(created["name"], "MyHost")

    def test_containers_group_created_for_freestanding(self):
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [CONTAINER_FREE], "stacks": []}}
        )
        self.assertIn("env_1_Containers", self._identifiers(reg, entry))

    def test_containers_group_not_created_compose_only(self):
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [CONTAINER_COMPOSE], "stacks": []}}
        )
        self.assertNotIn("env_1_Containers", self._identifiers(reg, entry))

    def test_stacks_group_created_when_stacks_exist(self):
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": [STACK1]}}
        )
        self.assertIn("env_1_Stacks", self._identifiers(reg, entry))

    def test_stacks_group_not_created_when_empty(self):
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
        )
        self.assertNotIn("env_1_Stacks", self._identifiers(reg, entry))

    def test_networks_group_when_enabled_and_data(self):
        slow = {
            "environments": {
                1: {"env": {}, "networks": [{"id": "n1"}], "images": [], "volumes": []}
            },
            "schedules": [],
        }
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
            slow_data=slow,
            config_overrides={"enable_networks": True},
        )
        self.assertIn("env_1_Networks", self._identifiers(reg, entry))

    def test_networks_group_not_created_when_disabled(self):
        slow = {
            "environments": {
                1: {"env": {}, "networks": [{"id": "n1"}], "images": [], "volumes": []}
            },
            "schedules": [],
        }
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
            slow_data=slow,
            config_overrides={"enable_networks": False},
        )
        self.assertNotIn("env_1_Networks", self._identifiers(reg, entry))

    def test_networks_group_not_created_when_enabled_but_empty(self):
        slow = {
            "environments": {
                1: {"env": {}, "networks": [], "images": [], "volumes": []}
            },
            "schedules": [],
        }
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
            slow_data=slow,
            config_overrides={"enable_networks": True},
        )
        self.assertNotIn("env_1_Networks", self._identifiers(reg, entry))

    def test_schedules_hub_created_when_enabled(self):
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
            config_overrides={"enable_schedules": True},
        )
        self.assertIn("schedules_hub", self._identifiers(reg, entry))

    def test_schedules_hub_not_created_when_disabled(self):
        reg, entry = self._run(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}},
            config_overrides={"enable_schedules": False},
        )
        self.assertNotIn("schedules_hub", self._identifiers(reg, entry))

    def test_empty_fast_data_creates_no_devices(self):
        reg, entry = self._run({})
        ids = self._identifiers(reg, entry)
        env_ids = {i for i in ids if i.startswith("env_")}
        self.assertEqual(env_ids, set())

    def test_idempotent_second_call(self):
        """Calling _register_devices twice should not create duplicate devices."""
        reg, hass = _make_registry()
        entry = _make_entry()
        fast = _make_fast_coordinator(
            {1: {"stats": ENV1_STATS, "containers": [], "stacks": []}}
        )
        slow = _make_slow_coordinator({"environments": {}, "schedules": []})
        config = {**entry.data}
        _register_devices(hass, entry, fast, slow, config, "http://dh.test:3000")
        _register_devices(hass, entry, fast, slow, config, "http://dh.test:3000")
        devs = reg.async_entries_for_config_entry(entry.entry_id)
        ids = [list(d.identifiers)[0][1] for d in devs]
        self.assertEqual(len(ids), len(set(ids)))  # no duplicates


# ── _remove_stale_devices ─────────────────────────────────────────────────────


class TestRemoveStaleDevices(unittest.TestCase):
    def setUp(self):
        reset_registry()

    def _make_runtime_data(self, fast_data, slow_data):
        rd = MagicMock()
        rd.fast_coordinator.data = fast_data
        rd.slow_coordinator.data = slow_data
        return rd

    def _add_device(self, reg, entry, identifier):
        return reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("dockhand", identifier)},
            name=identifier,
        )

    def test_removes_stale_container(self):
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={1: {"containers": [], "stacks": []}},
            slow_data={"environments": {}, "schedules": []},
        )
        stale = self._add_device(reg, entry, "container_old")
        _remove_stale_devices(hass, entry)
        self.assertIn(stale.id, reg._removed)

    def test_preserves_live_container(self):
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={1: {"containers": [{"id": "c1", "labels": {}}], "stacks": []}},
            slow_data={"environments": {}, "schedules": []},
        )
        live = self._add_device(reg, entry, "container_c1")
        _remove_stale_devices(hass, entry)
        self.assertNotIn(live.id, reg._removed)

    def test_removes_stale_stack(self):
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={1: {"containers": [], "stacks": []}},
            slow_data={"environments": {}, "schedules": []},
        )
        stale = self._add_device(reg, entry, "stack_1_oldapp")
        _remove_stale_devices(hass, entry)
        self.assertIn(stale.id, reg._removed)

    def test_preserves_live_stack(self):
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={1: {"containers": [], "stacks": [{"name": "myapp"}]}},
            slow_data={"environments": {}, "schedules": []},
        )
        live = self._add_device(reg, entry, "stack_1_myapp")
        _remove_stale_devices(hass, entry)
        self.assertNotIn(live.id, reg._removed)

    def test_image_devices_not_cleaned_up(self):
        """Images are entities under the Images group device, not individual devices.
        Any legacy 'image_*' device entries are preserved (user can remove manually)
        since the integration no longer creates or manages them."""
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={},
            slow_data={
                "environments": {1: {"images": [], "networks": [], "volumes": []}},
                "schedules": [],
            },
        )
        # An old image device — _remove_stale_devices no longer touches image_ identifiers
        leftover = self._add_device(reg, entry, "image_1_deadbeef")
        _remove_stale_devices(hass, entry)
        self.assertNotIn(leftover.id, reg._removed)

    def test_removes_stale_network_device(self):
        """Legacy network_ device entries are still cleaned up if present."""
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={},
            slow_data={
                "environments": {1: {"images": [], "networks": [], "volumes": []}},
                "schedules": [],
            },
        )
        stale = self._add_device(reg, entry, "network_netXYZ")
        _remove_stale_devices(hass, entry)
        self.assertIn(stale.id, reg._removed)

    def test_removes_stale_volume_device(self):
        """Legacy volume_ device entries are still cleaned up if present."""
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={},
            slow_data={
                "environments": {1: {"images": [], "networks": [], "volumes": []}},
                "schedules": [],
            },
        )
        stale = self._add_device(reg, entry, "volume_1_mydata")
        _remove_stale_devices(hass, entry)
        self.assertIn(stale.id, reg._removed)

    def test_preserves_env_device(self):
        """Env hub devices should never be auto-removed."""
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={1: {"containers": [], "stacks": []}},
            slow_data={"environments": {}, "schedules": []},
        )
        env_dev = self._add_device(reg, entry, "env_1")
        _remove_stale_devices(hass, entry)
        self.assertNotIn(env_dev.id, reg._removed)

    def test_preserves_group_device(self):
        """Group devices (env_1_Stacks, etc.) should never be auto-removed."""
        reg, hass = _make_registry()
        entry = _make_entry()
        entry.runtime_data = self._make_runtime_data(
            fast_data={},
            slow_data={"environments": {}, "schedules": []},
        )
        group = self._add_device(reg, entry, "env_1_Stacks")
        _remove_stale_devices(hass, entry)
        self.assertNotIn(group.id, reg._removed)


# ── Individual stack device pre-registration ──────────────────────────────────


class TestStackDevicePreRegistration(unittest.TestCase):
    """Verify that _register_devices pre-registers individual stack devices.

    This matters because compose-managed container entities use each stack
    device as their via_device. If the stack device doesn't exist yet when
    async_add_entities runs, HA logs a warning and will eventually error.
    """

    def setUp(self):
        reset_registry()
        reg, hass = _make_registry()
        entry = _make_entry()
        fast = _make_fast_coordinator(
            {
                1: {
                    "stats": ENV1_STATS,
                    "containers": [CONTAINER_COMPOSE],
                    "stacks": [STACK1, {"name": "second", "status": "running"}],
                },
            }
        )
        slow = _make_slow_coordinator({"environments": {}, "schedules": []})
        _register_devices(
            hass, entry, fast, slow, dict(entry.data), "http://dh.test:3000"
        )
        self.reg = reg
        self.entry = entry

    def _identifiers(self):
        return {
            list(d.identifiers)[0][1]
            for d in self.reg.async_entries_for_config_entry(self.entry.entry_id)
        }

    def test_individual_stack_device_registered(self):
        """Stack device must be registered alongside the Stacks group."""
        self.assertIn("stack_1_myapp", self._identifiers())

    def test_all_stacks_registered(self):
        """Every stack gets its own device pre-registered."""
        ids = self._identifiers()
        self.assertIn("stack_1_myapp", ids)
        self.assertIn("stack_1_second", ids)

    def test_stack_device_registered_before_group(self):
        """Both stack device and group must be present (order not assertable,
        but both must exist so container via_device links are always valid)."""
        ids = self._identifiers()
        self.assertIn("env_1_Stacks", ids)
        self.assertIn("stack_1_myapp", ids)

    def test_no_stack_devices_when_no_stacks(self):
        """No stack devices should be created when the env has no stacks."""
        reset_registry()
        reg, hass = _make_registry()
        entry = _make_entry()
        fast = _make_fast_coordinator(
            {
                1: {"stats": ENV1_STATS, "containers": [], "stacks": []},
            }
        )
        slow = _make_slow_coordinator({"environments": {}, "schedules": []})
        _register_devices(
            hass, entry, fast, slow, dict(entry.data), "http://dh.test:3000"
        )
        ids = {
            list(d.identifiers)[0][1]
            for d in reg.async_entries_for_config_entry(entry.entry_id)
        }
        stack_devices = {i for i in ids if i.startswith("stack_")}
        self.assertEqual(stack_devices, set())


# ── async_setup_entry ─────────────────────────────────────────────────────────


class TestSetupEntry(unittest.TestCase):
    """Tests for async_setup_entry in __init__.py."""

    def _make_mock_coordinators(
        self,
        fast_data=None,
        slow_data=None,
        fast_side_effect=None,
        slow_side_effect=None,
    ):
        fast = MagicMock(spec=DockhandFastCoordinator)
        fast.data = fast_data or {
            1: {"stats": ENV1_STATS, "containers": [], "stacks": []}
        }
        if fast_side_effect:
            fast.async_config_entry_first_refresh = AsyncMock(
                side_effect=fast_side_effect
            )
        else:
            fast.async_config_entry_first_refresh = AsyncMock()
        fast.async_add_listener = MagicMock(return_value=lambda: None)

        slow = MagicMock(spec=DockhandSlowCoordinator)
        slow.data = slow_data or {"environments": {}, "schedules": []}
        slow.last_update_success = True
        if slow_side_effect:
            slow.async_config_entry_first_refresh = AsyncMock(
                side_effect=slow_side_effect
            )
        else:
            slow.async_config_entry_first_refresh = AsyncMock()
        slow.async_add_listener = MagicMock(return_value=lambda: None)
        return fast, slow

    def test_success_stores_runtime_data(self):
        """Happy path: runtime_data is set with client, fast, and slow coordinator."""
        from custom_components.dockhand import async_setup_entry

        reset_registry()
        hass = HomeAssistant()
        entry = _make_entry({"api_token": "dh_test_token"})
        fast, slow = self._make_mock_coordinators()

        mock_client = MagicMock()
        with (
            patch(
                "custom_components.dockhand.async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.dockhand.DockhandClient", return_value=mock_client
            ),
            patch(
                "custom_components.dockhand.DockhandFastCoordinator", return_value=fast
            ),
            patch(
                "custom_components.dockhand.DockhandSlowCoordinator", return_value=slow
            ),
        ):
            run(async_setup_entry(hass, entry))

        self.assertIsNotNone(entry.runtime_data)
        self.assertIs(entry.runtime_data.fast_coordinator, fast)
        self.assertIs(entry.runtime_data.slow_coordinator, slow)

    def test_fast_coordinator_failure_raises_not_ready(self):
        """If the fast coordinator's first refresh fails, ConfigEntryNotReady is raised."""
        from custom_components.dockhand import async_setup_entry

        reset_registry()
        hass = HomeAssistant()
        entry = _make_entry({"api_token": "dh_test_token"})
        fast, slow = self._make_mock_coordinators(
            fast_side_effect=ConfigEntryNotReady("timeout")
        )

        mock_client = MagicMock()
        with (
            patch(
                "custom_components.dockhand.async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.dockhand.DockhandClient", return_value=mock_client
            ),
            patch(
                "custom_components.dockhand.DockhandFastCoordinator", return_value=fast
            ),
            patch(
                "custom_components.dockhand.DockhandSlowCoordinator", return_value=slow
            ),
        ):
            with self.assertRaises(ConfigEntryNotReady):
                run(async_setup_entry(hass, entry))

    def test_legacy_entry_without_token_raises_auth_failed(self):
        """A pre-1.2.0 entry with username/session_cookie but no api_token must
        raise ConfigEntryAuthFailed so HA prompts the user to provide a token."""
        from ha_stubs import ConfigEntryAuthFailed as CEAFailed

        from custom_components.dockhand import async_setup_entry

        reset_registry()
        hass = HomeAssistant()
        entry = _make_entry(
            {"username": "admin", "password": "pass", "session_cookie": "old_cookie"}
        )
        # Ensure no api_token present
        entry.data.pop("api_token", None)

        mock_client = MagicMock()
        with (
            patch(
                "custom_components.dockhand.async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.dockhand.DockhandClient", return_value=mock_client
            ),
        ):
            with self.assertRaises(CEAFailed):
                run(async_setup_entry(hass, entry))

    def test_legacy_entry_with_token_strips_legacy_keys_and_proceeds(self):
        """After reauth, a token is present alongside legacy keys. Setup must
        strip the legacy keys and continue normally rather than looping."""
        from custom_components.dockhand import async_setup_entry

        reset_registry()
        hass = HomeAssistant()
        # Simulate the state after reauth_confirm writes the token but leaves old keys
        entry = _make_entry(
            {
                "username": "admin",
                "password": "pass",
                "session_cookie": "old_cookie",
                "api_token": "dh_new_token",
            }
        )
        fast, slow = self._make_mock_coordinators()

        mock_client = MagicMock()
        with (
            patch(
                "custom_components.dockhand.async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.dockhand.DockhandClient", return_value=mock_client
            ),
            patch(
                "custom_components.dockhand.DockhandFastCoordinator", return_value=fast
            ),
            patch(
                "custom_components.dockhand.DockhandSlowCoordinator", return_value=slow
            ),
        ):
            run(async_setup_entry(hass, entry))

        # Legacy keys must have been stripped from the entry
        self.assertNotIn("username", entry.data)
        self.assertNotIn("session_cookie", entry.data)
        self.assertNotIn("password", entry.data)
        # Token must be retained
        self.assertEqual(entry.data.get("api_token"), "dh_new_token")
        # Integration must be fully set up
        self.assertIsNotNone(entry.runtime_data)

    def test_slow_coordinator_failure_is_non_fatal(self):
        """Slow coordinator first-refresh failure should not prevent setup."""
        from ha_stubs import UpdateFailed

        from custom_components.dockhand import async_setup_entry

        reset_registry()
        hass = HomeAssistant()
        entry = _make_entry({"api_token": "dh_test_token"})
        fast, slow = self._make_mock_coordinators(
            slow_side_effect=UpdateFailed("slow timeout")
        )

        mock_client = MagicMock()
        with (
            patch(
                "custom_components.dockhand.async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.dockhand.DockhandClient", return_value=mock_client
            ),
            patch(
                "custom_components.dockhand.DockhandFastCoordinator", return_value=fast
            ),
            patch(
                "custom_components.dockhand.DockhandSlowCoordinator", return_value=slow
            ),
        ):
            run(async_setup_entry(hass, entry))
        self.assertIsNotNone(entry.runtime_data)


# ── async_unload_entry ────────────────────────────────────────────────────────


class TestUnloadEntry(unittest.TestCase):
    """Tests for async_unload_entry in __init__.py."""

    def test_unload_returns_true_on_success(self):
        """async_unload_entry should return True when platform unloads succeed."""
        from custom_components.dockhand import async_unload_entry

        hass = HomeAssistant()
        entry = _make_entry()

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            result = run(async_unload_entry(hass, entry))
        self.assertTrue(result)

    def test_unload_returns_false_when_platform_fails(self):
        """async_unload_entry should propagate False from async_unload_platforms."""
        from custom_components.dockhand import async_unload_entry

        hass = HomeAssistant()
        entry = _make_entry()

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=False),
        ):
            result = run(async_unload_entry(hass, entry))
        self.assertFalse(result)

    def test_unload_calls_correct_platforms(self):
        """async_unload_entry must unload exactly the PLATFORMS list."""
        from custom_components.dockhand import async_unload_entry
        from custom_components.dockhand.const import PLATFORMS

        hass = HomeAssistant()
        entry = _make_entry()
        called_with = []

        async def _capture(e, platforms):
            called_with.extend(platforms)
            return True

        with patch.object(hass.config_entries, "async_unload_platforms", new=_capture):
            run(async_unload_entry(hass, entry))

        self.assertEqual(sorted(called_with), sorted(PLATFORMS))
        # diagnostics must NOT be in PLATFORMS (it's auto-discovered, not a loadable platform)
        self.assertNotIn("diagnostics", called_with)


if __name__ == "__main__":
    unittest.main()


# ── _remove_stale_entities ────────────────────────────────────────────────────


class TestRemoveStaleEntities(unittest.TestCase):
    """Covers the three safety guards and each resource type cleanup."""

    def _make_slow_coord(self, data, last_update_success=True):
        coord = MagicMock()
        coord.data = data
        coord.last_update_success = last_update_success
        return coord

    def _setup(self, slow_data, last_update_success=True):
        from ha_stubs import er_async_get, reset_entity_registry

        reset_entity_registry()
        hass = HomeAssistant()
        entry = _make_entry()
        er = er_async_get(hass)
        entry.runtime_data = DockhandData(
            client=MagicMock(),
            fast_coordinator=MagicMock(),
            slow_coordinator=self._make_slow_coord(slow_data, last_update_success),
        )
        return hass, entry, er

    # ── Safety guards ────────────────────────────────────────────────────

    def test_guard1_skips_when_last_update_failed(self):
        """No entities removed if last slow poll failed."""
        hass, entry, er = self._setup(
            slow_data={
                "environments": {1: {"images": [], "networks": [], "volumes": []}},
                "schedules": [],
            },
            last_update_success=False,
        )
        stale = er._add(entry.entry_id, "dockhand_image_1_deadbeef")
        _remove_stale_entities(hass, entry)
        self.assertNotIn(stale.entity_id, er._removed)

    def test_guard2_skips_when_no_environments(self):
        """No entities removed if coordinator returned zero environments."""
        hass, entry, er = self._setup(slow_data={"environments": {}, "schedules": []})
        stale = er._add(entry.entry_id, "dockhand_image_1_deadbeef")
        _remove_stale_entities(hass, entry)
        self.assertNotIn(stale.entity_id, er._removed)

    def test_guard3_skips_entities_for_absent_env(self):
        """Entities for env_id=2 are untouched when only env_id=1 is in data."""
        hass, entry, er = self._setup(
            slow_data={
                "environments": {1: {"images": [], "networks": [], "volumes": []}},
                "schedules": [],
            }
        )
        preserved = er._add(entry.entry_id, "dockhand_image_2_abc123")
        _remove_stale_entities(hass, entry)
        self.assertNotIn(preserved.entity_id, er._removed)

    # ── Image cleanup ────────────────────────────────────────────────────

    def test_removes_stale_image_entity(self):
        hass, entry, er = self._setup(
            slow_data={
                "environments": {1: {"images": [], "networks": [], "volumes": []}},
                "schedules": [],
            }
        )
        stale = er._add(entry.entry_id, "dockhand_image_1_deadbeef")
        _remove_stale_entities(hass, entry)
        self.assertIn(stale.entity_id, er._removed)

    def test_preserves_live_image_entity(self):
        hass, entry, er = self._setup(
            slow_data={
                "environments": {
                    1: {
                        "images": [{"id": "sha256:deadbeef"}],
                        "networks": [],
                        "volumes": [],
                    }
                },
                "schedules": [],
            }
        )
        live = er._add(entry.entry_id, "dockhand_image_1_deadbeef")
        _remove_stale_entities(hass, entry)
        self.assertNotIn(live.entity_id, er._removed)

    # ── Network cleanup ──────────────────────────────────────────────────

    def test_removes_stale_network_entity(self):
        hass, entry, er = self._setup(
            slow_data={
                "environments": {1: {"images": [], "networks": [], "volumes": []}},
                "schedules": [],
            }
        )
        stale = er._add(entry.entry_id, "dockhand_network_1_netXYZ")
        _remove_stale_entities(hass, entry)
        self.assertIn(stale.entity_id, er._removed)

    def test_preserves_live_network_entity(self):
        hass, entry, er = self._setup(
            slow_data={
                "environments": {
                    1: {"images": [], "networks": [{"id": "netXYZ"}], "volumes": []}
                },
                "schedules": [],
            }
        )
        live = er._add(entry.entry_id, "dockhand_network_1_netXYZ")
        _remove_stale_entities(hass, entry)
        self.assertNotIn(live.entity_id, er._removed)

    # ── Volume cleanup ───────────────────────────────────────────────────

    def test_removes_stale_volume_entity(self):
        hass, entry, er = self._setup(
            slow_data={
                "environments": {1: {"images": [], "networks": [], "volumes": []}},
                "schedules": [],
            }
        )
        stale = er._add(entry.entry_id, "dockhand_volume_1_mydata")
        _remove_stale_entities(hass, entry)
        self.assertIn(stale.entity_id, er._removed)

    def test_preserves_live_volume_entity(self):
        hass, entry, er = self._setup(
            slow_data={
                "environments": {
                    1: {
                        "images": [],
                        "networks": [],
                        "volumes": [{"name": "mydata", "usedBy": []}],
                    }
                },
                "schedules": [],
            }
        )
        live = er._add(entry.entry_id, "dockhand_volume_1_mydata")
        _remove_stale_entities(hass, entry)
        self.assertNotIn(live.entity_id, er._removed)

    # ── Mixed: stale + live in same env ──────────────────────────────────

    def test_removes_stale_but_preserves_live_in_same_env(self):
        hass, entry, er = self._setup(
            slow_data={
                "environments": {
                    1: {
                        "images": [{"id": "sha256:aabbccdd"}],
                        "networks": [],
                        "volumes": [],
                    }
                },
                "schedules": [],
            }
        )
        live = er._add(entry.entry_id, "dockhand_image_1_aabbccdd")
        stale = er._add(entry.entry_id, "dockhand_image_1_deadbeef")
        _remove_stale_entities(hass, entry)
        self.assertNotIn(live.entity_id, er._removed)
        self.assertIn(stale.entity_id, er._removed)
