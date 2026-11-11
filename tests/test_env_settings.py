"""An environment's settings as switch, select and number entities."""

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
from custom_components.dockhand.number import (
    ENV_SETTING_NUMBERS,
    DockhandEnvSettingNumber,
)
from custom_components.dockhand.select import (
    ENV_SETTING_SELECTS,
    DockhandEnvSettingSelect,
)
from custom_components.dockhand.switch import (
    ENV_SETTING_SWITCHES,
    DockhandEnvSettingSwitch,
)

ENV_ID = 1
SETTINGS = {
    "update_check": {"enabled": True, "cron": "0 4 * * *", "autoUpdate": False},
    "image_prune": {
        "enabled": False,
        "cronExpression": "0 3 * * 0",
        "pruneMode": "dangling",
    },
    "disk_warning": {
        "enabled": True,
        "mode": "absolute",
        "threshold": 80,
        "thresholdGb": 50,
    },
    "scanner": "grype",
}


def _coordinators(settings: dict[str, Any] | None = None, stats: dict | None = None):
    fast = MagicMock()
    fast.data = {
        "environments": {ENV_ID: {"stats": stats or {"collectActivity": True}}}
    }
    fast.last_update_success = True
    fast.async_request_refresh = AsyncMock()
    slow = MagicMock()
    slow.data = {
        "environments": {
            ENV_ID: {"settings": SETTINGS if settings is None else settings}
        }
    }
    slow.last_update_success = True
    slow.async_refresh_env_settings = AsyncMock()
    return fast, slow


def _client() -> MagicMock:
    client = MagicMock()
    for name in (
        "async_update_environment",
        "async_set_update_check_settings",
        "async_set_image_prune_settings",
        "async_set_disk_warning_settings",
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


async def test_switches_read_and_save_each_setting():
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

    # Metrics: no value yet, so unavailable.
    metrics = switch("metrics_collection")
    assert metrics.is_on is None
    assert not metrics.available

    # Update checks: Dockhand's current settings, with the change.
    auto = switch("auto_update")
    assert auto.is_on is False
    await auto.async_turn_on()
    client.async_set_update_check_settings.assert_awaited_once_with(
        ENV_ID, {"enabled": True, "cron": "0 5 * * *", "autoUpdate": True}
    )
    slow.async_refresh_env_settings.assert_awaited_with(ENV_ID)

    prune = switch("image_pruning")
    await prune.async_turn_on()
    client.async_set_image_prune_settings.assert_awaited_once_with(
        ENV_ID, {"enabled": True, "cronExpression": "0 1 * * *", "pruneMode": "all"}
    )

    disk = switch("disk_warning")
    assert disk.is_on is True
    await disk.async_turn_off()
    client.async_set_disk_warning_settings.assert_awaited_once_with(
        ENV_ID, enabled=False
    )


async def test_selects_and_numbers():
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
    await scanner.async_select_option("both")
    client.async_set_scanner.assert_awaited_once_with(ENV_ID, "both")

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

    fast, slow = _coordinators()
    threshold = _entity(
        DockhandEnvSettingNumber,
        ENV_SETTING_NUMBERS,
        "disk_warning_threshold",
        fast,
        slow,
        client,
    )
    assert (
        threshold.native_value,
        threshold.native_min_value,
        threshold.native_max_value,
    ) == (80.0, 1, 100)
    assert threshold.native_unit_of_measurement == "%"
    await threshold.async_set_native_value(90.0)
    client.async_set_disk_warning_settings.assert_awaited_with(ENV_ID, threshold=90)
    gb = _entity(
        DockhandEnvSettingNumber,
        ENV_SETTING_NUMBERS,
        "disk_warning_threshold_gb",
        fast,
        slow,
        client,
    )
    assert gb.native_value == 50.0
    assert gb.device_info["identifiers"] == {("dockhand", "entry_env_1")}
    slow.data["environments"][ENV_ID]["settings"] = {
        "disk_warning": {"thresholdGb": "x"}
    }
    assert gb.native_value is None


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
    client.async_get_update_check_settings = AsyncMock(side_effect=OSError("down"))
    client.async_get_image_prune_settings = AsyncMock(
        side_effect=DockhandPermissionError("403")
    )
    client.async_get_disk_warning_settings = AsyncMock(return_value={"enabled": True})
    client.async_get_scanner_setting = AsyncMock(return_value=None)
    previous = {"update_check": {"enabled": False}, "scanner": "trivy"}
    assert await _fetch_env_settings(client, ENV_ID, previous) == {
        "update_check": {"enabled": False},
        "disk_warning": {"enabled": True},
        "scanner": "trivy",
    }


async def test_refresh_one_environments_settings(hass: HomeAssistant):
    client = MagicMock()
    client.async_get_update_check_settings = AsyncMock(return_value={"enabled": True})
    client.async_get_image_prune_settings = AsyncMock(return_value={})
    client.async_get_disk_warning_settings = AsyncMock(return_value={})
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
        "settings": {"update_check": {"enabled": True}, "scanner": "none"},
    }
    listener.assert_called()
    # An environment that's gone, before or during the read: nothing.
    await coord.async_refresh_env_settings(99)

    async def _gone(env_id: int) -> str:
        coord.data = {"environments": {}}
        return "none"

    client.async_get_scanner_setting = _gone
    await coord.async_refresh_env_settings(ENV_ID)
    assert coord.data == {"environments": {}}
