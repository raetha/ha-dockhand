"""The prune and recreate_container actions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.api import DockhandPermissionError
from custom_components.dockhand.const import DOMAIN
from custom_components.dockhand.services import async_setup_services

WEB = {"id": "c1", "name": "web_app", "state": "running", "image": "nginx:1"}
HAWSER = {"id": "c2", "name": "hawser", "state": "running", "systemContainer": "hawser"}


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={"api_url": "http://dh.test:3000"})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    data = MagicMock()
    data.client.async_prune = AsyncMock(
        side_effect=lambda env_id, resource, all_images: {
            "images": {"ImagesDeleted": ["a", "b"], "SpaceReclaimed": 300},
            "volumes": {"VolumesDeleted": ["v"], "SpaceReclaimed": 20},
            "networks": {"NetworksDeleted": None},
        }[resource]
    )
    data.client.async_recreate_container = AsyncMock(return_value={"success": True})
    data.fast_coordinator.data = {
        "environments": {1: {"stats": {}, "containers": [WEB, HAWSER]}}
    }
    data.fast_coordinator.async_refresh_environment = AsyncMock()
    data.slow_coordinator.async_refresh = AsyncMock()
    entry.runtime_data = data
    async_setup_services(hass)
    return entry


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> str:
    return (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, identifier)}
        )
        .id
    )


async def test_prune_reports_what_was_removed(
    hass: HomeAssistant, entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
):
    device_id = _device(hass, entry, f"{entry.entry_id}_env_1")
    response = await hass.services.async_call(
        DOMAIN,
        "prune",
        {
            "device_id": device_id,
            "resources": ["networks", "images", "volumes"],
            "all_images": True,
        },
        blocking=True,
        return_response=True,
    )
    assert response == {
        "space_reclaimed": 320,
        "images_deleted": 2,
        "volumes_deleted": 1,
        "networks_deleted": 0,
    }
    client = entry.runtime_data.client
    assert [c.args[1] for c in client.async_prune.await_args_list] == [
        "images",
        "volumes",
        "networks",
    ]
    assert client.async_prune.await_args.kwargs == {"all_images": True}
    entry.runtime_data.fast_coordinator.async_refresh_environment.assert_awaited_with(1)
    entry.runtime_data.slow_coordinator.async_refresh.assert_awaited_once()
    # Finding the device's entry doesn't read the deprecated config_entries.
    assert "config_entries" not in caplog.text


async def test_prune_rejects_an_unknown_resource(
    hass: HomeAssistant, entry: MockConfigEntry
):
    device_id = _device(hass, entry, f"{entry.entry_id}_env_1")
    with pytest.raises(Exception, match="resources"):
        await hass.services.async_call(
            DOMAIN,
            "prune",
            {"device_id": device_id, "resources": ["build_cache"]},
            blocking=True,
        )


@pytest.mark.parametrize(
    "identifier",
    ["{entry}_container_1_web_app", "{entry}_env_9", "{entry}_env_1_Containers"],
)
async def test_prune_needs_an_environment_device(
    hass: HomeAssistant, entry: MockConfigEntry, identifier: str
):
    device_id = _device(hass, entry, identifier.format(entry=entry.entry_id))
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "prune",
            {"device_id": device_id, "resources": ["images"]},
            blocking=True,
        )
    assert err.value.translation_key == "invalid_target"


async def test_prune_reports_a_permission_refusal(
    hass: HomeAssistant, entry: MockConfigEntry
):
    entry.runtime_data.client.async_prune = AsyncMock(
        side_effect=DockhandPermissionError("403")
    )
    device_id = _device(hass, entry, f"{entry.entry_id}_env_1")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "prune",
            {"device_id": device_id, "resources": ["images"]},
            blocking=True,
        )
    assert err.value.translation_key == "permission_denied"


async def test_recreate_container(hass: HomeAssistant, entry: MockConfigEntry):
    device_id = _device(hass, entry, f"{entry.entry_id}_container_1_web_app")
    await hass.services.async_call(
        DOMAIN, "recreate_container", {"device_id": device_id}, blocking=True
    )
    entry.runtime_data.client.async_recreate_container.assert_awaited_once_with(
        1, "c1", name="web_app", image="nginx:1", pull=True, start=True
    )
    entry.runtime_data.fast_coordinator.async_refresh_environment.assert_awaited_once_with(
        1
    )


async def test_recreate_refuses_a_system_container(
    hass: HomeAssistant, entry: MockConfigEntry
):
    device_id = _device(hass, entry, f"{entry.entry_id}_container_1_hawser")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "recreate_container", {"device_id": device_id}, blocking=True
        )
    assert err.value.translation_key == "system_container"
    entry.runtime_data.client.async_recreate_container.assert_not_called()


@pytest.mark.parametrize(
    ("identifier", "translation_key"),
    [
        ("{entry}_container_1_gone", "container_not_found"),
        ("{entry}_container_x_web_app", "invalid_target"),
        ("{entry}_env_1", "invalid_target"),
    ],
)
async def test_recreate_needs_a_known_container_device(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    identifier: str,
    translation_key: str,
):
    device_id = _device(hass, entry, identifier.format(entry=entry.entry_id))
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "recreate_container", {"device_id": device_id}, blocking=True
        )
    assert err.value.translation_key == translation_key


async def test_actions_refuse_an_unknown_device(
    hass: HomeAssistant, entry: MockConfigEntry
):
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "recreate_container", {"device_id": "nope"}, blocking=True
        )
    assert err.value.translation_key == "invalid_target"


async def test_actions_refuse_another_integrations_device(
    hass: HomeAssistant, entry: MockConfigEntry
):
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    device_id = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=other.entry_id, identifiers={("other", "x")}
        )
        .id
    )
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "recreate_container", {"device_id": device_id}, blocking=True
        )
    assert err.value.translation_key == "invalid_target"


async def test_actions_need_a_loaded_entry(hass: HomeAssistant, entry: MockConfigEntry):
    device_id = _device(hass, entry, f"{entry.entry_id}_env_1")
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "prune",
            {"device_id": device_id, "resources": ["images"]},
            blocking=True,
        )
    assert err.value.translation_key == "entry_not_loaded"


async def test_prune_buttons_follow_the_image_prune_mode():
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.dockhand.button import DockhandEnvPruneButton

    data = MagicMock()
    data.client.async_prune = AsyncMock(
        return_value={"ImagesDeleted": [{}, {}], "SpaceReclaimed": 2048}
    )
    data.fast_coordinator.async_refresh_environment = AsyncMock()
    data.slow_coordinator.async_refresh = AsyncMock()
    slow = MagicMock()
    slow.data = {
        "environments": {1: {"settings": {"image_prune": {"pruneMode": "all"}}}}
    }

    def button(resource: str) -> DockhandEnvPruneButton:
        return DockhandEnvPruneButton(
            MagicMock(), slow, data, "entry", 1, "local", "http://dh", resource
        )

    images = button("images")
    assert images.unique_id == "entry_1_prune_images"
    assert images.translation_key == "prune_images"
    assert not images.entity_registry_enabled_default
    await images.async_press()
    data.client.async_prune.assert_awaited_once_with(1, "images", all_images=True)
    data.fast_coordinator.async_refresh_environment.assert_awaited_once_with(1)
    data.slow_coordinator.async_refresh.assert_awaited_once()

    # Without a readable mode, dangling images only, as Dockhand defaults.
    slow.data = {"environments": {1: {}}}
    data.client.async_prune.reset_mock()
    await button("volumes").async_press()
    data.client.async_prune.assert_awaited_once_with(1, "volumes", all_images=False)
