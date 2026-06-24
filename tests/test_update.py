"""
Tests for ContainerUpdateEntity and helpers (update.py).

Covers:
- _short_digest: both currentDigest and newDigest formats, malformed input
- installed_version / latest_version: up-to-date, update available, missing data
- available: container in fast data, container missing, env missing,
  coordinator unhealthy (last_update_success=False)
- release_summary: always None (no longer populated, consistent with HACS)
- async_release_notes: image name, ha-alert types verified (warning/info),
  scanner warning, system container warning, update disabled, no data,
  scanner+system combo, systemContainer priority over updateDisabled
- _update_supported_features: normal, updateDisabled, systemContainer
- _handle_coordinator_update: triggers feature refresh
- async_install: success, container_not_found, action_failed, no container_id
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError

from custom_components.dockhand.update import ContainerUpdateEntity, _short_digest
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandUpdateCoordinator,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

ENV_ID = 1
ENTRY_ID = "test_entry_id_update"
ENV_NAME = "myenv"
BASE_URL = "http://dh.test:3000"
CONTAINER_NAME = "nginx"
CONTAINER_ID = "abc123def456"

ITEM_UP_TO_DATE = {
    "containerId": CONTAINER_ID,
    "containerName": CONTAINER_NAME,
    "imageName": "nginx:latest",
    "currentDigest": "nginx@sha256:53bb1e23fb302fabc0d",
    "hasUpdate": False,
    "updateDisabled": False,
    "systemContainer": None,
}

ITEM_HAS_UPDATE = {
    "containerId": CONTAINER_ID,
    "containerName": CONTAINER_NAME,
    "imageName": "nginx:latest",
    "currentDigest": "nginx@sha256:53bb1e23fb302fabc0d",
    "newDigest": "sha256:79f926e8d8fe31c0dfe90",
    "hasUpdate": True,
    "updateDisabled": False,
    "systemContainer": None,
}

ITEM_UPDATE_DISABLED = {**ITEM_UP_TO_DATE, "updateDisabled": True}
ITEM_SYSTEM = {**ITEM_UP_TO_DATE, "systemContainer": "hawser"}


def _make_update_coord(env_items: dict | None = None) -> MagicMock:
    """Return a mock DockhandUpdateCoordinator with given items for ENV_ID."""
    coord = MagicMock(spec=DockhandUpdateCoordinator)
    coord.data = {ENV_ID: {CONTAINER_ID: env_items or ITEM_UP_TO_DATE}}
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    coord.client = MagicMock()
    coord.client.async_batch_update_container = AsyncMock()
    return coord


def _make_fast_coord(
    containers: list | None = None, scanner_enabled: bool = False
) -> MagicMock:
    coord = MagicMock(spec=DockhandFastCoordinator)
    coord.data = {
        ENV_ID: {
            "containers": containers if containers is not None
                else [{"name": CONTAINER_NAME, "id": CONTAINER_ID, "state": "running", "labels": {}}],
            "stacks": [],
            "stats": {"scannerEnabled": scanner_enabled},
            "container_stats": {},
        }
    }
    return coord


def _make_entity(
    item: dict | None = None,
    containers: list | None = None,
    scanner_enabled: bool = False,
) -> ContainerUpdateEntity:
    update_coord = _make_update_coord(item or ITEM_UP_TO_DATE)
    fast_coord = _make_fast_coord(containers, scanner_enabled)
    return ContainerUpdateEntity(
        fast_coordinator=fast_coord,
        update_coordinator=update_coord,
        entry_id=ENTRY_ID,
        env_id=ENV_ID,
        env_name=ENV_NAME,
        container_name=CONTAINER_NAME,
        item=item or ITEM_UP_TO_DATE,
    )


# ---------------------------------------------------------------------------
# _short_digest
# ---------------------------------------------------------------------------


def test_short_digest_current_digest_format():
    """currentDigest: 'image@sha256:<hex>' → first 12 hex chars."""
    result = _short_digest("nginx@sha256:53bb1e23fb302fabc0d123456789")
    assert result == "53bb1e23fb30"


def test_short_digest_new_digest_format():
    """newDigest: 'sha256:<hex>' → first 12 hex chars."""
    result = _short_digest("sha256:79f926e8d8fe31c0dfe90858f90b")
    assert result == "79f926e8d8fe"


def test_short_digest_short_hex():
    """Digest shorter than 12 chars returns what's available."""
    result = _short_digest("sha256:abc")
    assert result == "abc"


def test_short_digest_malformed_falls_back():
    """Malformed string returns the original."""
    result = _short_digest("notadigest")
    assert result == "notadigest"


def test_short_digest_empty_string():
    result = _short_digest("")
    assert result == ""


# ---------------------------------------------------------------------------
# installed_version / latest_version
# ---------------------------------------------------------------------------


def test_installed_version_returns_short_digest():
    entity = _make_entity(ITEM_UP_TO_DATE)
    assert entity.installed_version == "53bb1e23fb30"


def test_installed_version_missing_digest_returns_none():
    item = {**ITEM_UP_TO_DATE, "currentDigest": ""}
    entity = _make_entity(item)
    assert entity.installed_version is None


def test_latest_version_equals_installed_when_no_update():
    entity = _make_entity(ITEM_UP_TO_DATE)
    assert entity.latest_version == entity.installed_version


def test_latest_version_new_digest_when_update_available():
    entity = _make_entity(ITEM_HAS_UPDATE)
    assert entity.latest_version == "79f926e8d8fe"


def test_latest_version_falls_back_when_new_digest_missing():
    item = {**ITEM_HAS_UPDATE, "newDigest": ""}
    entity = _make_entity(item)
    assert entity.latest_version == entity.installed_version


def test_latest_version_returns_installed_when_item_empty():
    """If container has left update coordinator data, return installed_version."""
    update_coord = MagicMock(spec=DockhandUpdateCoordinator)
    update_coord.data = {ENV_ID: {}}  # container gone
    update_coord.last_update_success = True
    update_coord.async_add_listener = MagicMock(return_value=lambda: None)
    entity = ContainerUpdateEntity(
        fast_coordinator=_make_fast_coord(),
        update_coordinator=update_coord,
        entry_id=ENTRY_ID,
        env_id=ENV_ID,
        env_name=ENV_NAME,
        container_name=CONTAINER_NAME,
        item=ITEM_UP_TO_DATE,
    )
    assert entity.latest_version == entity.installed_version


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


def test_available_true_when_container_in_fast_data():
    entity = _make_entity()
    assert entity.available is True


def test_available_false_when_container_missing_from_fast_data():
    entity = _make_entity(containers=[])
    assert entity.available is False


def test_available_false_when_coordinator_not_successful():
    """available requires both container present in fast data AND coordinator healthy."""
    entity = _make_entity()
    entity.coordinator.last_update_success = False
    assert entity.available is False


def test_available_false_when_env_missing_from_fast_data():
    update_coord = _make_update_coord()
    fast_coord = MagicMock(spec=DockhandFastCoordinator)
    fast_coord.data = {}  # no env at all
    entity = ContainerUpdateEntity(
        fast_coordinator=fast_coord,
        update_coordinator=update_coord,
        entry_id=ENTRY_ID,
        env_id=ENV_ID,
        env_name=ENV_NAME,
        container_name=CONTAINER_NAME,
        item=ITEM_UP_TO_DATE,
    )
    assert entity.available is False


# ---------------------------------------------------------------------------
# _update_supported_features
# ---------------------------------------------------------------------------


def test_install_supported_for_normal_container():
    from homeassistant.components.update import UpdateEntityFeature
    entity = _make_entity(ITEM_UP_TO_DATE)
    assert UpdateEntityFeature.INSTALL in entity._attr_supported_features


def test_install_suppressed_when_update_disabled():
    from homeassistant.components.update import UpdateEntityFeature
    entity = _make_entity(ITEM_UPDATE_DISABLED)
    assert UpdateEntityFeature.INSTALL not in entity._attr_supported_features
    assert UpdateEntityFeature.RELEASE_NOTES in entity._attr_supported_features


def test_install_suppressed_for_system_container():
    from homeassistant.components.update import UpdateEntityFeature
    entity = _make_entity(ITEM_SYSTEM)
    assert UpdateEntityFeature.INSTALL not in entity._attr_supported_features


# ---------------------------------------------------------------------------
# release_summary
# ---------------------------------------------------------------------------


def test_release_summary_always_none():
    # release_summary is no longer populated — consistent with HACS convention.
    # Image name and warnings appear in async_release_notes instead.
    # This holds regardless of item state, image name, or scanner state.
    assert _make_entity(ITEM_UP_TO_DATE).release_summary is None
    assert _make_entity(ITEM_UP_TO_DATE, scanner_enabled=True).release_summary is None
    assert _make_entity(ITEM_SYSTEM).release_summary is None
    assert _make_entity(ITEM_UPDATE_DISABLED).release_summary is None


# ---------------------------------------------------------------------------
# async_release_notes
# ---------------------------------------------------------------------------


async def test_release_notes_includes_image_name():
    entity = _make_entity(ITEM_UP_TO_DATE)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "nginx:latest" in notes


async def test_release_notes_includes_scanner_warning():
    entity = _make_entity(ITEM_UP_TO_DATE, scanner_enabled=True)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "<ha-alert alert-type='warning'>" in notes
    assert "Vulnerability" in notes


async def test_release_notes_includes_system_container_warning():
    entity = _make_entity(ITEM_SYSTEM)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "<ha-alert alert-type='warning'>" in notes
    assert "system container" in notes.lower()


async def test_release_notes_includes_update_disabled_message():
    entity = _make_entity(ITEM_UPDATE_DISABLED)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "<ha-alert alert-type='info'>" in notes
    assert "dockhand.update=false" in notes


async def test_release_notes_scanner_and_system_container_both_appear():
    """Scanner warning and system container warning are independent — both show."""
    item = {**ITEM_SYSTEM}  # systemContainer set
    entity = _make_entity(item, scanner_enabled=True)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert notes.count("<ha-alert") == 2
    assert "Vulnerability" in notes
    assert "system container" in notes.lower()


async def test_release_notes_system_container_takes_priority_over_update_disabled():
    """systemContainer and updateDisabled: systemContainer warning shown, not update_disabled."""
    item = {**ITEM_SYSTEM, "updateDisabled": True}
    entity = _make_entity(item)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "system container" in notes.lower()
    assert "dockhand.update=false" not in notes


async def test_release_notes_none_when_no_item():
    update_coord = MagicMock(spec=DockhandUpdateCoordinator)
    update_coord.data = {ENV_ID: {}}
    update_coord.last_update_success = True
    update_coord.async_add_listener = MagicMock(return_value=lambda: None)
    entity = ContainerUpdateEntity(
        fast_coordinator=_make_fast_coord(),
        update_coordinator=update_coord,
        entry_id=ENTRY_ID,
        env_id=ENV_ID,
        env_name=ENV_NAME,
        container_name=CONTAINER_NAME,
        item=ITEM_UP_TO_DATE,
    )
    assert await entity.async_release_notes() is None


# ---------------------------------------------------------------------------
# _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_handle_coordinator_update_refreshes_features():
    """Coordinator update triggers _update_supported_features before writing state."""
    from homeassistant.components.update import UpdateEntityFeature

    entity = _make_entity(ITEM_UP_TO_DATE)
    # Initially INSTALL should be supported
    assert UpdateEntityFeature.INSTALL in entity._attr_supported_features

    # Simulate coordinator data changing to a disabled container
    entity.coordinator.data = {ENV_ID: {CONTAINER_ID: ITEM_UPDATE_DISABLED}}

    # Patch async_write_ha_state since hass is not wired up in unit tests
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert UpdateEntityFeature.INSTALL not in entity._attr_supported_features


# ---------------------------------------------------------------------------
# async_install
# ---------------------------------------------------------------------------


async def test_async_install_calls_batch_update():
    entity = _make_entity(ITEM_HAS_UPDATE)
    await entity.async_install(version=None, backup=False)
    entity.coordinator.client.async_batch_update_container.assert_called_once_with(
        ENV_ID, CONTAINER_ID
    )


async def test_async_install_requests_refresh_after_update():
    entity = _make_entity(ITEM_HAS_UPDATE)
    await entity.async_install(version=None, backup=False)
    entity.coordinator.async_request_refresh.assert_called_once()


async def test_async_install_raises_not_found_when_container_gone():
    update_coord = _make_update_coord()
    update_coord.data = {ENV_ID: {}}  # container gone
    fast_coord = _make_fast_coord()
    entity = ContainerUpdateEntity(
        fast_coordinator=fast_coord,
        update_coordinator=update_coord,
        entry_id=ENTRY_ID,
        env_id=ENV_ID,
        env_name=ENV_NAME,
        container_name=CONTAINER_NAME,
        item=ITEM_UP_TO_DATE,
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_install(version=None, backup=False)
    assert exc_info.value.translation_key == "container_not_found"


async def test_async_install_raises_action_failed_on_api_error():
    entity = _make_entity(ITEM_HAS_UPDATE)
    entity.coordinator.client.async_batch_update_container = AsyncMock(
        side_effect=Exception("connection refused")
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_install(version=None, backup=False)
    assert exc_info.value.translation_key == "action_failed"


async def test_async_install_raises_not_found_when_no_container_id():
    item = {**ITEM_HAS_UPDATE, "containerId": ""}
    entity = _make_entity(item)
    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_install(version=None, backup=False)
    assert exc_info.value.translation_key == "container_not_found"


# ---------------------------------------------------------------------------
# Entity metadata
# ---------------------------------------------------------------------------


def test_unique_id_format():
    entity = _make_entity()
    assert entity._attr_unique_id == f"{ENTRY_ID}_{ENV_ID}_update_{CONTAINER_NAME}"


def test_translation_key():
    # Update entity uses no translation_key — consistent with HA convention for
    # devices that have a single update entity (ESPHome, UniFi, etc.).
    entity = _make_entity()
    assert not hasattr(entity, "_attr_translation_key")


def test_device_info_references_container_device():
    entity = _make_entity()
    identifiers = entity._attr_device_info["identifiers"]
    assert ("dockhand", f"container_{ENV_ID}_{CONTAINER_NAME}") in identifiers


def test_has_entity_name():
    entity = _make_entity()
    assert entity._attr_has_entity_name is True
