"""How Dockhand collects Docker's events: read on the slow poll, shown and
changed on the Dockhand device, and a repair while it polls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.api import DockhandClient
from custom_components.dockhand.const import DOMAIN
from custom_components.dockhand.coordinator import DockhandSlowCoordinator
from custom_components.dockhand.select import (
    DockhandEventCollectionSelect,
    DockhandEventPollIntervalSelect,
)


@pytest.fixture
def api_client():
    client = DockhandClient(MagicMock(), {"api_url": "http://dh.test"})
    client._request = AsyncMock()
    return client


async def test_api_reads_and_writes_the_general_settings(api_client):
    c = api_client
    c._request.return_value = {
        "eventCollectionMode": "poll",
        "eventPollInterval": 120000,
    }
    assert await c.async_get_event_collection() == {"mode": "poll", "interval": 120}
    assert c._request.call_args.args == ("GET", "/api/settings/general")
    c._request.return_value = {"eventCollectionMode": "stream"}
    assert await c.async_get_event_collection() == {"mode": "stream", "interval": None}
    # Without permission to view settings, Dockhand leaves them out.
    c._request.return_value = {"theme": "dark"}
    assert await c.async_get_event_collection() is None
    c._request.return_value = "oops"
    assert await c.async_get_event_collection() is None

    await c.async_set_event_collection_mode("stream")
    assert c._request.call_args.args == ("POST", "/api/settings/general")
    assert c._request.call_args.kwargs["json"] == {"eventCollectionMode": "stream"}
    await c.async_set_event_poll_interval(30)
    assert c._request.call_args.kwargs["json"] == {"eventPollInterval": 30000}


def _fast(*connection_types: str) -> MagicMock:
    fast = MagicMock()
    fast.data = {
        "environments": {
            env_id: {"stats": {"name": f"env{env_id}", "connectionType": kind}}
            for env_id, kind in enumerate(connection_types, start=1)
        }
    }
    return fast


def _coordinator(
    hass: HomeAssistant, fast: MagicMock, collection, entry=True
) -> DockhandSlowCoordinator:
    client = MagicMock()
    client.async_get_event_collection = AsyncMock(return_value=collection)
    config_entry = None
    if entry:
        config_entry = MockConfigEntry(domain=DOMAIN, entry_id="entry")
        config_entry.add_to_hass(hass)
    return DockhandSlowCoordinator(hass, client, {}, fast, config_entry)


def _issue(hass: HomeAssistant):
    return ir.async_get(hass).async_get_issue(DOMAIN, "entry_event_collection_poll")


async def test_a_repair_while_polling_cleared_by_streaming(hass: HomeAssistant):
    coord = _coordinator(
        hass, _fast("hawser-standard", "hawser-edge"), {"mode": "poll", "interval": 60}
    )
    await coord.async_refresh_event_collection()
    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_key == "event_collection_poll"
    # Hawser Edge agents send their own events.
    assert issue.translation_placeholders == {"interval": "60", "environments": "env1"}

    coord.client.async_get_event_collection.return_value = {
        "mode": "stream",
        "interval": 60,
    }
    await coord.async_refresh_event_collection()
    assert _issue(hass) is None
    assert coord.data["event_collection"]["mode"] == "stream"


async def test_no_repair_when_only_hawser_edge_depends_on_it(hass: HomeAssistant):
    coord = _coordinator(hass, _fast("hawser-edge"), {"mode": "poll", "interval": 60})
    await coord.async_refresh_event_collection()
    assert _issue(hass) is None


async def test_an_ignored_repair_stays_ignored_while_polling(hass: HomeAssistant):
    coord = _coordinator(hass, _fast("socket"), {"mode": "poll", "interval": 300})
    await coord.async_refresh_event_collection()
    ir.async_ignore_issue(hass, DOMAIN, "entry_event_collection_poll", True)
    await coord.async_refresh_event_collection()
    assert _issue(hass).dismissed_version is not None


async def test_unreadable_settings_keep_the_last_value(hass: HomeAssistant):
    coord = _coordinator(hass, _fast("socket"), None)
    await coord.async_refresh_event_collection()
    assert coord.data["event_collection"] is None
    assert _issue(hass) is None

    coord.data = {"event_collection": {"mode": "stream", "interval": 60}}
    coord.client.async_get_event_collection.side_effect = OSError("down")
    assert await coord._fetch_event_collection() == {"mode": "stream", "interval": 60}


async def test_no_repair_without_a_config_entry(hass: HomeAssistant):
    coord = _coordinator(
        hass, _fast("socket"), {"mode": "poll", "interval": 60}, entry=False
    )
    await coord.async_refresh_event_collection()
    assert _issue(hass) is None


def _slow(collection) -> MagicMock:
    slow = MagicMock()
    slow.data = {"event_collection": collection}
    slow.last_update_success = True
    slow.async_refresh_event_collection = AsyncMock()
    return slow


async def test_mode_select_on_the_dockhand_device():
    slow = _slow({"mode": "poll", "interval": 60})
    client = MagicMock()
    client.async_set_event_collection_mode = AsyncMock()
    select = DockhandEventCollectionSelect(slow, client, "entry")
    assert select.unique_id == "entry_instance_event_collection_mode"
    assert select.device_info["identifiers"] == {(DOMAIN, "entry_instance")}
    assert select.available
    assert select.current_option == "poll"
    await select.async_select_option("stream")
    client.async_set_event_collection_mode.assert_awaited_once_with("stream")
    slow.async_refresh_event_collection.assert_awaited_once()

    slow.data = {"event_collection": {"mode": "odd"}}
    assert select.current_option is None
    slow.data = {"event_collection": None}
    assert not select.available


async def test_poll_interval_select_only_while_polling():
    slow = _slow({"mode": "poll", "interval": 120})
    client = MagicMock()
    client.async_set_event_poll_interval = AsyncMock()
    select = DockhandEventPollIntervalSelect(slow, client, "entry")
    assert select.unique_id == "entry_instance_event_poll_interval"
    assert select.available
    assert select.current_option == "120"
    await select.async_select_option("30")
    client.async_set_event_poll_interval.assert_awaited_once_with(30)
    slow.async_refresh_event_collection.assert_awaited_once()

    slow.data = {"event_collection": {"mode": "poll", "interval": 45}}
    assert select.current_option is None
    slow.data = {"event_collection": {"mode": "stream", "interval": 60}}
    assert not select.available
