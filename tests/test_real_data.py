"""The integration set up from one real Dockhand environment
(tests/fixtures/dockhand_environment.json), with every optional feature and
entity turned on: what the hand-written test data elsewhere can't promise
is that it looks like what Dockhand actually sends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.const import (
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_RESOURCE_STATS,
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_UPDATE_ENTITIES,
    CONF_ENABLE_VOLUMES,
    CONF_ENABLED_ENTITIES,
    DOMAIN,
    SCHEMA_MINOR_VERSION,
    SCHEMA_VERSION,
)
from custom_components.dockhand.entity_defaults import OPTIONAL_ENTITIES

from .conftest import config_entry

from .test_config_flow import _patch_full_setup

FIXTURE = Path(__file__).parent / "fixtures" / "dockhand_environment.json"

# Unknown here for a reason: a Hawser Standard connection has no agent to
# have been seen, and an event entity has no state until an event.
EXPECTED_UNKNOWN = {"hawser_last_seen", "docker_event"}
# Unavailable here for a reason: events are streamed, not polled; nothing
# has an update to install; and Dockhand reports no resource use for a
# stack with nothing running (staging and backup), so only its Running
# containers has a value (0).
EXPECTED_UNAVAILABLE = {
    "select.dockhand_dockhand_example_internal_3000_event_poll_interval",
    "button.atlas_update_all_containers",
    *(
        f"sensor.atlas_stacks_{stack}_{stat}"
        for stack in ("staging", "backup")
        for stat in (
            "cpu_usage",
            "memory_usage",
            "memory_limit",
            "network_in",
            "network_out",
            "disk_read",
            "disk_write",
        )
    ),
}


def _coordinator_data() -> tuple[dict[str, Any], dict[str, Any]]:
    """The fixture as the coordinators hold it: environment IDs are ints."""
    data = json.loads(FIXTURE.read_text())

    def by_int(part: dict[str, Any]) -> dict[str, Any]:
        envs = {int(k): v for k, v in part["environments"].items()}
        return {**part, "environments": envs}

    return by_int(data["fast"]), by_int(data["slow"])


async def setup_from_real_data(
    hass: HomeAssistant,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """The integration set up from the fixture with everything turned on:
    the fast and slow data, and the fast coordinator holding them."""
    fast, slow = _coordinator_data()
    entry = config_entry(
        hass,
        title="Dockhand",
        version=SCHEMA_VERSION,
        minor_version=SCHEMA_MINOR_VERSION,
        data={"api_url": "http://dockhand.example.internal:3000", "verify_ssl": True},
        options={
            CONF_ENABLE_SCHEDULES: True,
            CONF_ENABLE_IMAGES: True,
            CONF_ENABLE_VOLUMES: True,
            CONF_ENABLE_NETWORKS: True,
            CONF_ENABLE_UPDATE_ENTITIES: True,
            CONF_ENABLE_RESOURCE_STATS: True,
            CONF_ENABLE_RUNTIME_CONTROLS: True,
            CONF_ENABLED_ENTITIES: {k: list(v) for k, v in OPTIONAL_ENTITIES.items()},
        },
    )
    with _patch_full_setup(fast, slow):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return fast, slow, entry.runtime_data.fast_coordinator


async def test_every_entity_has_a_state_from_real_data(hass: HomeAssistant):
    fast, _slow, coordinator = await setup_from_real_data(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    env = fast["environments"][4]
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    names = {d.name for d in devices}
    for container in env["containers"]:
        assert any(n and n.endswith(f"Containers – {container['name']}") for n in names)
    for stack in env["stacks"]:
        assert any(n and n.endswith(f"Stacks – {stack['name']}") for n in names)

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert entities
    bad: list[str] = []
    for entity in entities:
        if entity.disabled_by is not None:
            continue
        state = hass.states.get(entity.entity_id)
        if state is None:
            bad.append(f"{entity.entity_id}: no state")
        elif state.state == STATE_UNAVAILABLE:
            if entity.entity_id not in EXPECTED_UNAVAILABLE:
                bad.append(f"{entity.entity_id}: unavailable")
        elif (
            state.state == STATE_UNKNOWN
            # A button's state is when it was last pressed.
            and entity.domain != "button"
            and entity.translation_key not in EXPECTED_UNKNOWN
        ):
            bad.append(f"{entity.entity_id}: unknown")
    assert bad == [], "\n".join(bad)
    # Every one of those is still here, so the list stays true.
    assert EXPECTED_UNAVAILABLE <= {e.entity_id for e in entities}
