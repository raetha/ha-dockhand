"""Setup and cleanup agree under every option setting.

The platforms decide which devices and entities to create, and
_cleanup_stale_registry decides separately which ones to keep. When the two
disagree for some option setting, a poll removes what setup just made and the
next one brings it back, over and over (github.com/raetha/ha-dockhand/issues/105).
So each setting here is set up from the real Dockhand data in
tests/fixtures, cleanup is run, and nothing may change. Each option is tried
off with the rest on, and on with the rest off, which covers every option's
effect on its own without trying every combination.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.dockhand import _cleanup_stale_registry
from custom_components.dockhand.const import (
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_PRECISE_UPDATES,
    CONF_ENABLE_RESOURCE_STATS,
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_UPDATE_ENTITIES,
    CONF_ENABLE_VOLUMES,
    CONF_ENABLED_ENTITIES,
    OPTION_KEYS,
    SCHEMA_MINOR_VERSION,
    SCHEMA_VERSION,
)
from custom_components.dockhand.entity_defaults import OPTIONAL_ENTITIES

from .conftest import (
    config_entry,
    fast_coordinator,
    patch_setup,
    slow_coordinator,
    update_coordinator,
)
from .test_real_data import _coordinator_data

SWITCHES = (
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_VOLUMES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_UPDATE_ENTITIES,
    CONF_ENABLE_PRECISE_UPDATES,
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLE_RESOURCE_STATS,
)
ALL_OPTIONAL = {k: list(v) for k, v in OPTIONAL_ENTITIES.items()}


def _options(on: bool, flipped: str | None = None) -> dict[str, Any]:
    """Every option `on` (or off), except `flipped`, which is the other way."""
    options: dict[str, Any] = {key: on != (key == flipped) for key in SWITCHES}
    optional_on = on != (flipped == CONF_ENABLED_ENTITIES)
    options[CONF_ENABLED_ENTITIES] = ALL_OPTIONAL if optional_on else {}
    return options


SETTINGS = {
    "all on": _options(True),
    "all off": _options(False),
    **{f"{key} off": _options(True, key) for key in OPTION_KEYS},
    **{f"{key} on": _options(False, key) for key in OPTION_KEYS},
}


def test_every_option_is_tried():
    """A new option has to join SWITCHES, or this file wouldn't try it."""
    assert set(OPTION_KEYS) == {*SWITCHES, CONF_ENABLED_ENTITIES}


def _registry(hass: HomeAssistant, entry_id: str) -> tuple[set[str], set[str]]:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry_id)
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry_id)
    return (
        {i for d in devices for _, i in d.identifiers},
        {e.unique_id for e in entities},
    )


@pytest.mark.parametrize("options", SETTINGS.values(), ids=SETTINGS.keys())
async def test_cleanup_keeps_what_setup_made(
    hass: HomeAssistant, options: dict[str, Any]
):
    fast_data, slow_data = _coordinator_data()
    fast = fast_coordinator()
    fast.data = fast_data
    slow = slow_coordinator()
    slow.data = slow_data
    update = update_coordinator()
    update.data = {}
    entry = config_entry(
        hass,
        title="Dockhand",
        version=SCHEMA_VERSION,
        minor_version=SCHEMA_MINOR_VERSION,
        data={"api_url": "http://dockhand.example.internal:3000", "verify_ssl": True},
        options=options,
    )
    with patch_setup(fast, slow, update):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    devices, entities = _registry(hass, entry.entry_id)
    # The fixture's containers always have devices, whatever the options.
    assert any(i.startswith(f"{entry.entry_id}_container_") for i in devices)

    entry.runtime_data.cleanup_seen = None
    _cleanup_stale_registry(hass, entry)
    after_devices, after_entities = _registry(hass, entry.entry_id)
    assert sorted(devices - after_devices) == []
    assert sorted(entities - after_entities) == []
