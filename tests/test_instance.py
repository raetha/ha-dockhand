"""The Dockhand instance device, its version, and system health."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    _instance_device,
    instance_host,
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
    assert instance.name == "Dockhand (dh.test:3000)"
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


async def test_a_container_device_carries_its_image_version(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    fast = loaded_entry.runtime_data.fast_coordinator
    env_id, env = next(iter(fast.data["environments"].items()))
    container = env["containers"][0]
    identifier = (
        DOMAIN,
        f"{loaded_entry.entry_id}_container_{env_id}_{container['name']}",
    )
    registry = dr.async_get(hass)

    container["image"] = "nginx:1.27"
    container["labels"] = {}
    fast.async_set_updated_data(fast.data)
    assert (
        _device_by_identifier(registry, identifier, loaded_entry.entry_id).sw_version
        == "1.27"
    )

    # Recreated on a newer image.
    container["labels"] = {"org.opencontainers.image.version": "1.28.0"}
    fast.async_set_updated_data(fast.data)
    assert (
        _device_by_identifier(registry, identifier, loaded_entry.entry_id).sw_version
        == "1.28.0"
    )

    # A container whose device isn't registered yet, or without a name, is skipped.
    env["containers"].append({"name": "brand_new", "image": "x:1"})
    env["containers"].append({"image": "y:1"})
    fast.async_set_updated_data(fast.data)


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


async def test_unloading_stops_the_version_poll(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    version = loaded_entry.runtime_data.version_coordinator
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    assert not version._listeners


def test_instance_host_falls_back_to_dockhand():
    assert instance_host("https://dockhand.example.com") == "dockhand.example.com"
    assert _instance_device("e", "", None)["name"] == "Dockhand"


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def test_dockhand_update_entity(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    entity_id = _entity_id(hass, "update", f"{loaded_entry.entry_id}_instance_update")
    assert entity_id == "update.dockhand_dh_test_3000"
    state = hass.states.get(entity_id)
    assert state.state == "off"
    assert state.attributes["installed_version"] == "1.0.57"
    assert state.attributes["latest_version"] == "1.0.57"
    assert state.attributes["supported_features"] == 0

    version = loaded_entry.runtime_data.version_coordinator
    cases = [
        ({"updateAvailable": True, "latestVersion": "1.0.58"}, "on", "1.0.58"),
        (
            {"updateAvailable": True, "newDigest": "sha256:abcdef0123456789"},
            "on",
            "abcdef012345",
        ),
    ]
    for check, expected, latest in cases:
        version.self_update = check
        version.async_set_updated_data("1.0.57")
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state.state == expected
        assert state.attributes["latest_version"] == latest

    # A check that can't tell, or couldn't run: unavailable.
    for check in ({"updateAvailable": False, "error": "no Docker"}, None):
        version.self_update = check
        version.async_set_updated_data("1.0.57")
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "unavailable"


def _patched(client: MagicMock):
    return (
        patch("custom_components.dockhand.async_get_clientsession"),
        patch("custom_components.dockhand.DockhandClient", return_value=client),
    )


async def _setup_with_check(
    hass: HomeAssistant, check: dict
) -> tuple[MockConfigEntry, MagicMock]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="t",
        data={"api_url": "http://dh.test:3000", "api_token": "t"},
        options={},
    )
    entry.add_to_hass(hass)
    client = make_mock_client()
    client.async_check_self_update = AsyncMock(return_value=check)
    client.async_get_pending_updates = AsyncMock(return_value=[])
    client.async_get_stack_stats = AsyncMock(return_value=[])
    session, dockhand = _patched(client)
    with session, dockhand:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, client


async def test_dockhand_update_entity_waits_for_a_working_check(hass: HomeAssistant):
    """Hawser-only: Dockhand can't inspect its own container, so no entity
    until a check says something, then it's added without a reload."""
    entry, client = await _setup_with_check(
        hass, {"updateAvailable": False, "error": "Failed to inspect own container"}
    )
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_instance_update"
    assert registry.async_get_entity_id("update", DOMAIN, unique_id) is None

    version = entry.runtime_data.version_coordinator
    version.self_update = {"updateAvailable": False, "currentVersion": "1.0.57"}
    version.async_set_updated_data("1.0.57")
    await hass.async_block_till_done()
    entity_id = registry.async_get_entity_id("update", DOMAIN, unique_id)
    assert hass.states.get(entity_id).state == "off"
    # Added once.
    version.async_set_updated_data("1.0.57")
    await hass.async_block_till_done()

    # A check that fails after that leaves it unavailable until the next.
    version.self_update = {"updateAvailable": False, "error": "down"}
    version.async_set_updated_data("1.0.57")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unavailable"

    # One that doesn't work at setup isn't kept, rather than unavailable for
    # good (an entity left by an earlier release, or Dockhand moved to a
    # host it can't inspect itself on).
    client.async_check_self_update = AsyncMock(
        return_value={"updateAvailable": False, "error": "down"}
    )
    session, dockhand = _patched(client)
    with session, dockhand:
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert registry.async_get_entity_id("update", DOMAIN, unique_id) is None
    assert hass.states.get(entity_id) is None


async def test_dockhand_update_check_is_feature_detected(hass: HomeAssistant):
    from custom_components.dockhand.api import (
        DockhandNotFoundError,
        DockhandPermissionError,
    )

    for error, allowed in (
        (DockhandPermissionError("403"), False),
        (DockhandNotFoundError("404"), False),
        (OSError("down"), True),
    ):
        client = MagicMock()
        client.async_get_dockhand_version = AsyncMock(return_value="1.0.57")
        client.async_check_self_update = AsyncMock(side_effect=error)
        coordinator = DockhandVersionCoordinator(hass, client)
        assert await coordinator._async_update_data() == "1.0.57"
        assert coordinator.self_update is None
        assert coordinator.self_update_allowed is allowed
        # Once refused, it isn't asked again.
        await coordinator._async_update_data()
        assert client.async_check_self_update.await_count == (1 if not allowed else 2)


async def test_no_update_entity_without_permission(hass: HomeAssistant):
    from custom_components.dockhand.api import DockhandPermissionError

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="t",
        data={"api_url": "http://dh.test:3000", "api_token": "t"},
        options={},
    )
    entry.add_to_hass(hass)
    client = make_mock_client()
    client.async_check_self_update = AsyncMock(side_effect=DockhandPermissionError())
    client.async_get_pending_updates = AsyncMock(return_value=[])
    client.async_get_stack_stats = AsyncMock(return_value=[])
    with (
        patch("custom_components.dockhand.async_get_clientsession"),
        patch("custom_components.dockhand.DockhandClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert (
        er.async_get(hass).async_get_entity_id(
            "update", DOMAIN, f"{entry.entry_id}_instance_update"
        )
        is None
    )


async def test_live_updates_sensor(hass: HomeAssistant, loaded_entry: MockConfigEntry):
    entity_id = _entity_id(
        hass, "binary_sensor", f"{loaded_entry.entry_id}_instance_live_updates"
    )
    stream = loaded_entry.runtime_data.event_stream
    assert hass.states.get(entity_id).state == "off"
    stream.connected = True
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"
    # No change, no write.
    stream.connected = True
    stream.async_stop()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "off"
    assert state.attributes["in_use"] is False
