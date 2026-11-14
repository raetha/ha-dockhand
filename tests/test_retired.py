"""Retired entities: their removal and the repair while automations or
scripts still use them (retired.py)."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.automation import EVENT_AUTOMATION_RELOADED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.const import DOMAIN
from custom_components.dockhand.retired import (
    RETIRED_ENTITIES,
    async_check_retired_entities,
    retired_entity,
)

from .test_config_flow import LEGACY_ENTRY_DATA, _patch_full_setup

USERS = "custom_components.dockhand.retired.automations_with_entity"
SCRIPTS = "custom_components.dockhand.retired.scripts_with_entity"


def _entry(hass: HomeAssistant, entry_id: str = "ENTRY") -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id, data={})
    entry.add_to_hass(hass)
    return entry


def _retire(
    hass: HomeAssistant, entry: MockConfigEntry, key: str, domain: str = "binary_sensor"
) -> str:
    """Register an entity and remove it, as cleanup does: its entity ID."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_or_create(
        domain, DOMAIN, f"{entry.entry_id}_1_{key}", config_entry=entry
    ).entity_id
    registry.async_remove(entity_id)
    return entity_id


def _issue(hass: HomeAssistant, entry_id: str = "ENTRY") -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{entry_id}_retired_entities")


def test_retired_entity_matches_domain_and_key():
    assert retired_entity("binary_sensor", "E_1_collect_activity") is not None
    assert retired_entity("switch", "E_1_collect_activity") is None
    assert retired_entity("binary_sensor", "E_1_scanner_enabled") is None
    assert retired_entity("binary_sensor", "E_x_collect_activity") is None
    assert retired_entity("binary_sensor", "E_1") is None


def test_no_retired_entities_past_their_schema_major():
    """Once no entry from before a retirement can be upgraded (two schema
    majors on, like registry migrations), its entry here is dead: delete it."""
    from custom_components.dockhand.const import SCHEMA_VERSION

    assert [r for r in RETIRED_ENTITIES if r.from_major < SCHEMA_VERSION - 1] == []


async def test_repair_lists_users_with_the_replacement(hass: HomeAssistant):
    entry = _entry(hass)
    old = _retire(hass, entry, "collect_activity")
    switch = (
        er.async_get(hass)
        .async_get_or_create(
            "switch", DOMAIN, f"{entry.entry_id}_1_collect_activity", config_entry=entry
        )
        .entity_id
    )
    unused = _retire(hass, entry, "auto_update")
    with (
        patch(USERS, side_effect=lambda h, e: ["automation.b"] if e == old else []),
        patch(SCRIPTS, side_effect=lambda h, e: ["script.a"] if e == old else []),
    ):
        async_check_retired_entities(hass, entry.entry_id)

    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_key == "retired_entities"
    assert issue.severity == ir.IssueSeverity.WARNING
    entities = issue.translation_placeholders["entities"]
    assert entities == f"- `{old}` → `{switch}`: `automation.b`, `script.a`"
    assert unused not in entities


async def test_repair_without_a_replacement_names_only_the_old_entity(
    hass: HomeAssistant,
):
    entry = _entry(hass)
    old = _retire(hass, entry, "collect_metrics")
    with patch(USERS, return_value=["automation.a"]), patch(SCRIPTS, return_value=[]):
        async_check_retired_entities(hass, entry.entry_id)
    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_placeholders["entities"] == f"- `{old}`: `automation.a`"


async def test_repair_clears_once_nothing_uses_them(hass: HomeAssistant):
    entry = _entry(hass)
    _retire(hass, entry, "collect_activity")
    with patch(USERS, return_value=["automation.a"]), patch(SCRIPTS, return_value=[]):
        async_check_retired_entities(hass, entry.entry_id)
    assert _issue(hass) is not None
    with patch(USERS, return_value=[]), patch(SCRIPTS, return_value=[]):
        async_check_retired_entities(hass, entry.entry_id)
    assert _issue(hass) is None


async def test_repair_ignores_other_entries_and_entities(hass: HomeAssistant):
    entry = _entry(hass)
    other = _entry(hass, "OTHER")
    _retire(hass, other, "collect_activity")
    _retire(hass, entry, "collect_activity", domain="switch")
    _retire(hass, entry, "scanner_enabled")
    registry = er.async_get(hass)
    foreign = registry.async_get_or_create(
        "binary_sensor", "other", f"{entry.entry_id}_1_collect_activity"
    ).entity_id
    registry.async_remove(foreign)
    with patch(USERS, return_value=["automation.a"]), patch(SCRIPTS, return_value=[]):
        async_check_retired_entities(hass, entry.entry_id)
    assert _issue(hass) is None
    assert _issue(hass, "OTHER") is None


async def test_checked_at_start_and_on_automation_reload(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, data={**LEGACY_ENTRY_DATA, "api_token": "t"}, title="x"
    )
    entry.add_to_hass(hass)
    with (
        _patch_full_setup(),
        patch("custom_components.dockhand.async_check_retired_entities") as check,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert check.call_count == 1
        hass.bus.async_fire(EVENT_AUTOMATION_RELOADED)
        await hass.async_block_till_done()
        assert check.call_count == 2
        await hass.config_entries.async_unload(entry.entry_id)
        hass.bus.async_fire(EVENT_AUTOMATION_RELOADED)
        await hass.async_block_till_done()
        assert check.call_count == 2
