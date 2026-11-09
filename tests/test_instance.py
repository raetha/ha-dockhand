"""The Dockhand instance device, its version, and system health."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    get_system_health_info,
)

from custom_components.dockhand import (
    _update_instance_version,
    async_remove_config_entry_device,
)
from custom_components.dockhand.api import DockhandClient
from custom_components.dockhand.const import DOMAIN
from custom_components.dockhand.coordinator import DockhandVersionCoordinator
from custom_components.dockhand.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.dockhand.helpers import (
    _device_by_identifier,
    _ensure_hub_devices,
)

from .conftest import make_mock_client


def _client_returning(payload) -> DockhandClient:
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value=payload)
    session = MagicMock()

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield response

    session.request = MagicMock(return_value=_ctx())
    return DockhandClient(session, {"api_url": "http://dh.test:3000"})


@pytest.mark.parametrize(
    ("payload", "version"),
    [
        ([{"version": "1.0.57"}, {"version": "1.0.56"}], "1.0.57"),
        ([], None),
        (["1.0.57"], None),
        ([{"version": ""}], None),
    ],
)
async def test_version_is_the_newest_changelog_entry(payload, version):
    client = _client_returning(payload)
    assert await client.async_get_dockhand_version() == version
    client._session.request.assert_called_once()
    assert client._session.request.call_args.args[1].endswith("/api/changelog")


async def test_version_coordinator_reports_failures(hass: HomeAssistant):
    client = MagicMock()
    client.async_get_dockhand_version = AsyncMock(side_effect=OSError("down"))
    coordinator = DockhandVersionCoordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.fixture
async def loaded_entry(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home Dockhand",
        data={"api_url": "http://dh.test:3000", "api_token": "t"},
        options={},
    )
    entry.add_to_hass(hass)
    client = make_mock_client()
    client.async_check_health = AsyncMock()
    client.async_get_pending_updates = AsyncMock(return_value=[])
    client.async_get_stack_stats = AsyncMock(return_value=[])
    with (
        patch("custom_components.dockhand.async_get_clientsession"),
        patch("custom_components.dockhand.DockhandClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _instance(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    device = _device_by_identifier(
        dr.async_get(hass), (DOMAIN, f"{entry.entry_id}_instance"), entry.entry_id
    )
    assert device is not None
    return device


async def test_instance_device_parents_the_environments(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    instance = _instance(hass, loaded_entry)
    assert instance.name == "Home Dockhand"
    assert instance.sw_version == "1.0.57"
    assert instance.configuration_url == "http://dh.test:3000"
    env = _device_by_identifier(
        dr.async_get(hass),
        (DOMAIN, f"{loaded_entry.entry_id}_env_1"),
        loaded_entry.entry_id,
    )
    assert env is not None
    assert env.via_device_id == instance.id
    _ensure_hub_devices(hass, loaded_entry.entry_id, "http://dh.test:3000", [])
    hub = _device_by_identifier(
        dr.async_get(hass),
        (DOMAIN, f"{loaded_entry.entry_id}_schedules_hub"),
        loaded_entry.entry_id,
    )
    assert hub is not None
    assert hub.via_device_id == instance.id


async def test_an_upgrade_updates_the_software_version(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    version = loaded_entry.runtime_data.version_coordinator
    version.async_set_updated_data("1.0.58")
    assert _instance(hass, loaded_entry).sw_version == "1.0.58"
    # A failed fetch leaves the last known version.
    version.data = None
    _update_instance_version(hass, loaded_entry)
    assert _instance(hass, loaded_entry).sw_version == "1.0.58"


async def test_the_instance_device_cant_be_deleted_while_loaded(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    assert not await async_remove_config_entry_device(
        hass, loaded_entry, _instance(hass, loaded_entry)
    )


async def test_diagnostics_include_the_version(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    result = await async_get_config_entry_diagnostics(hass, loaded_entry)
    assert result["dockhand_version"] == "1.0.57"


async def test_system_health(hass: HomeAssistant, loaded_entry: MockConfigEntry):
    assert await async_setup_component(hass, "system_health", {})
    await hass.async_block_till_done()
    info = await get_system_health_info(hass, DOMAIN)
    info["can_reach_server"] = await info["can_reach_server"]
    assert info == {
        "can_reach_server": "ok",
        "version": "1.0.57",
        "environments": 1,
    }


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), {"type": "failed", "error": "timeout"}),
        (OSError("refused"), {"type": "failed", "error": "unreachable"}),
    ],
)
async def test_system_health_when_dockhand_doesnt_answer(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, error, expected
):
    loaded_entry.runtime_data.client.async_check_health = AsyncMock(side_effect=error)
    loaded_entry.runtime_data.version_coordinator.data = None
    assert await async_setup_component(hass, "system_health", {})
    await hass.async_block_till_done()
    info = await get_system_health_info(hass, DOMAIN)
    assert await info["can_reach_server"] == expected
    assert "version" not in info


async def test_health_check_calls_the_public_liveness_route():
    client = _client_returning({"status": "ok"})
    await client.async_check_health()
    args = client._session.request.call_args
    assert args.args[1].endswith("/api/health")
    assert args.kwargs["timeout"].total == 5


async def test_unloading_stops_the_version_poll(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    version = loaded_entry.runtime_data.version_coordinator
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    assert not version._listeners
