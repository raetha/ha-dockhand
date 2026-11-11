"""An environment's settings as switch and select entities, and Dockhand's
default scanner."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.dockhand.api import DockhandPermissionError
from custom_components.dockhand.coordinator import (
    DockhandSlowCoordinator,
    _fetch_env_settings,
)
from custom_components.dockhand.select import (
    ENV_SETTING_SELECTS,
    DockhandDefaultScannerSelect,
    DockhandEnvSettingSelect,
)
from custom_components.dockhand.switch import (
    ENV_SETTING_SWITCHES,
    DockhandEnvSettingSwitch,
)

ENV_ID = 1
STATS = {
    "collectActivity": True,
    "collectMetrics": False,
    "updateCheckEnabled": True,
    "updateCheckAutoUpdate": False,
}
SETTINGS = {
    "image_prune": {
        "enabled": False,
        "cronExpression": "0 3 * * 0",
        "pruneMode": "dangling",
    },
    "scanner": "grype",
}


def _coordinators(
    settings: dict[str, Any] | None = None, stats: dict | None = None
) -> tuple[MagicMock, MagicMock]:
    fast = MagicMock()
    fast.data = {
        "environments": {ENV_ID: {"stats": dict(STATS if stats is None else stats)}}
    }
    fast.last_update_success = True
    fast.async_request_refresh = AsyncMock()
    slow = MagicMock()
    slow.data = {
        "environments": {
            ENV_ID: {"settings": SETTINGS if settings is None else settings}
        },
        "scanner_default": "trivy",
    }
    slow.last_update_success = True
    slow.async_refresh_env_settings = AsyncMock()
    slow.async_refresh_scanner_default = AsyncMock()
    return fast, slow


def _client() -> MagicMock:
    client = MagicMock()
    for name in (
        "async_update_environment",
        "async_set_update_check_settings",
        "async_set_image_prune_settings",
        "async_set_scanner",
    ):
        setattr(client, name, AsyncMock())
    client.async_get_update_check_settings = AsyncMock(
        return_value={"enabled": True, "cron": "0 5 * * *", "autoUpdate": False}
    )
    client.async_get_image_prune_settings = AsyncMock(
        return_value={
            "enabled": False,
            "cronExpression": "0 1 * * *",
            "pruneMode": "all",
        }
    )
    return client


def _entity(cls, descriptions, key, fast, slow, client):
    description = next(d for d in descriptions if d.key == key)
    return cls(fast, slow, client, "entry", ENV_ID, "local", "http://dh", description)


async def test_switches_read_the_stats_and_save_where_each_setting_lives():
    fast, slow = _coordinators()
    client = _client()

    def switch(key: str) -> DockhandEnvSettingSwitch:
        return _entity(
            DockhandEnvSettingSwitch, ENV_SETTING_SWITCHES, key, fast, slow, client
        )

    activity = switch("activity_logging")
    assert activity.is_on is True
    assert activity.unique_id == "entry_1_collect_activity"
    assert activity.coordinator is fast
    await activity.async_turn_off()
    client.async_update_environment.assert_awaited_once_with(
        ENV_ID, collectActivity=False
    )
    fast.async_request_refresh.assert_awaited_once()
    slow.async_refresh_env_settings.assert_not_awaited()

    # Update checks: Dockhand's current settings, with the change.
    checks = switch("update_checks")
    assert checks.is_on is True
    auto = switch("auto_update")
    assert auto.is_on is False
    assert auto.available
    await auto.async_turn_on()
    client.async_set_update_check_settings.assert_awaited_once_with(
        ENV_ID, {"enabled": True, "cron": "0 5 * * *", "autoUpdate": True}
    )
    assert fast.async_request_refresh.await_count == 2

    # Auto-update only applies while update checks are on.
    fast.data["environments"][ENV_ID]["stats"]["updateCheckEnabled"] = False
    assert not auto.available

    prune = switch("image_pruning")
    assert prune.coordinator is slow
    assert prune.is_on is False
    await prune.async_turn_on()
    client.async_set_image_prune_settings.assert_awaited_once_with(
        ENV_ID, {"enabled": True, "cronExpression": "0 1 * * *", "pruneMode": "all"}
    )
    slow.async_refresh_env_settings.assert_awaited_with(ENV_ID)

    # A setting not read yet: unavailable.
    fast, slow = _coordinators(settings={}, stats={})
    assert not _entity(
        DockhandEnvSettingSwitch,
        ENV_SETTING_SWITCHES,
        "image_pruning",
        fast,
        slow,
        client,
    ).available
    assert (
        _entity(
            DockhandEnvSettingSwitch,
            ENV_SETTING_SWITCHES,
            "metrics_collection",
            fast,
            slow,
            client,
        ).is_on
        is None
    )


async def test_selects():
    fast, slow = _coordinators()
    client = _client()
    scanner = _entity(
        DockhandEnvSettingSelect,
        ENV_SETTING_SELECTS,
        "vulnerability_scanner",
        fast,
        slow,
        client,
    )
    assert scanner.options == ["none", "grype", "trivy", "both"]
    assert scanner.current_option == "grype"
    assert scanner.entity_category == "config"
    assert scanner.device_info["identifiers"] == {("dockhand", "entry_env_1")}
    await scanner.async_select_option("both")
    client.async_set_scanner.assert_awaited_once_with(ENV_ID, "both")
    slow.async_refresh_env_settings.assert_awaited_with(ENV_ID)

    mode = _entity(
        DockhandEnvSettingSelect,
        ENV_SETTING_SELECTS,
        "image_prune_mode",
        fast,
        slow,
        client,
    )
    assert mode.current_option == "dangling"
    slow.data["environments"][ENV_ID]["settings"] = {
        "image_prune": {"pruneMode": "weird"}
    }
    assert mode.current_option is None


async def test_default_scanner_on_the_dockhand_device():
    _, slow = _coordinators()
    client = _client()
    default = DockhandDefaultScannerSelect(slow, client, "entry")
    assert default.unique_id == "entry_instance_vulnerability_scanner"
    assert default.device_info["identifiers"] == {("dockhand", "entry_instance")}
    assert default.current_option == "trivy"
    await default.async_select_option("none")
    client.async_set_scanner.assert_awaited_once_with(None, "none")
    slow.async_refresh_scanner_default.assert_awaited_once()
    slow.data["scanner_default"] = "odd"
    assert default.current_option is None
    slow.data["scanner_default"] = None
    assert not default.available


async def test_a_refused_change_says_so():
    fast, slow = _coordinators()
    client = _client()
    client.async_update_environment = AsyncMock(
        side_effect=DockhandPermissionError("403")
    )
    activity = _entity(
        DockhandEnvSettingSwitch,
        ENV_SETTING_SWITCHES,
        "activity_logging",
        fast,
        slow,
        client,
    )
    with pytest.raises(HomeAssistantError):
        await activity.async_turn_off()


async def test_fetch_keeps_what_it_had_and_skips_what_it_never_read():
    client = MagicMock()
    client.async_get_image_prune_settings = AsyncMock(
        side_effect=DockhandPermissionError("403")
    )
    client.async_get_scanner_setting = AsyncMock(side_effect=OSError("down"))
    assert await _fetch_env_settings(client, ENV_ID, {"scanner": "trivy"}) == {
        "scanner": "trivy"
    }
    client.async_get_scanner_setting = AsyncMock(return_value=None)
    assert await _fetch_env_settings(client, ENV_ID, {}) == {}


async def test_refreshing_settings_and_the_default(hass: HomeAssistant):
    client = MagicMock()
    client.async_get_image_prune_settings = AsyncMock(return_value={"enabled": True})
    client.async_get_scanner_setting = AsyncMock(return_value="none")
    coord = DockhandSlowCoordinator(hass, client, {}, MagicMock())
    listener = MagicMock()
    coord.async_add_listener(listener)
    coord.data = {
        "environments": {ENV_ID: {"host": {}, "settings": {}}},
        "schedules": [],
    }
    await coord.async_refresh_env_settings(ENV_ID)
    assert coord.data["environments"][ENV_ID] == {
        "host": {},
        "settings": {"image_prune": {"enabled": True}, "scanner": "none"},
    }
    listener.assert_called()

    # The default, and every environment's scanner after it.
    client.async_get_scanner_setting = AsyncMock(return_value="grype")
    await coord.async_refresh_scanner_default()
    assert coord.data["scanner_default"] == "grype"
    assert coord.data["environments"][ENV_ID]["settings"]["scanner"] == "grype"
    client.async_get_scanner_setting = AsyncMock(side_effect=OSError("down"))
    assert await coord._fetch_scanner_default() == "grype"

    # An environment that's gone, before or during the read: nothing.
    await coord.async_refresh_env_settings(99)

    async def _gone(env_id: int) -> str:
        coord.data = {"environments": {}}
        return "none"

    client.async_get_scanner_setting = _gone
    await coord.async_refresh_env_settings(ENV_ID)
    assert coord.data == {"environments": {}}
