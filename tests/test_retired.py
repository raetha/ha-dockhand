"""Retired entities: their removal and the repair while automations or
scripts still use them (retired.py)."""

from __future__ import annotations

from types import SimpleNamespace
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


def _user(
    entity_id: str,
    unique_id: str | None = None,
    refs: tuple[str, ...] = (),
    raw: dict | None = None,
) -> SimpleNamespace:
    """A stand-in automation or script entity."""
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=unique_id,
        referenced_entities=set(refs),
        raw_config=raw,
    )


def _install(hass: HomeAssistant, domain: str, *entities: SimpleNamespace) -> None:
    hass.data[domain] = SimpleNamespace(entities=list(entities))


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


def _issues(hass: HomeAssistant, entry_id: str = "ENTRY") -> dict[str, ir.IssueEntry]:
    """This entry's retired-entity repairs, by the automation or script."""
    prefix = f"{entry_id}_retired_"
    return {
        issue_id.removeprefix(prefix): issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue_id.startswith(prefix)
    }


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


async def test_repair_lists_each_user_with_a_link_and_the_replacements(
    hass: HomeAssistant,
):
    entry = _entry(hass)
    old = _retire(hass, entry, "collect_activity")
    registry = er.async_get(hass)
    old_registry_id = next(
        d.id for d in registry.deleted_entities.values() if d.entity_id == old
    )
    switch = registry.async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_1_collect_activity", config_entry=entry
    ).entity_id
    other = _retire(hass, entry, "auto_update")
    _retire(hass, entry, "image_prune_enabled")
    hass.states.async_set("automation.named", "on", {"friendly_name": "Named [x]"})
    _install(
        hass,
        "automation",
        # Referenced directly, with an id: linked to its editor.
        _user("automation.named", "1700", refs=(old, other)),
        # Only by registry ID (a device trigger), and without an id.
        _user("automation.device", raw={"triggers": [{"entity_id": old_registry_id}]}),
        # A longer entity ID that starts with the old one isn't a use.
        _user("automation.longer", "1701", raw={"t": f"{{{{ is_state('{old}_2') }}}}"}),
        _user("automation.none", "1702"),
    )
    _install(
        hass,
        "script",
        # Only inside a template.
        _user("script.tmpl", "tmpl", raw={"v": f"{{{{ is_state('{old}', 'on') }}}}"}),
    )
    async_check_retired_entities(hass, entry.entry_id)

    issues = _issues(hass)
    assert sorted(issues) == ["automation.device", "automation.named", "script.tmpl"]
    assert all(i.severity == ir.IssueSeverity.WARNING for i in issues.values())
    named = issues["automation.named"]
    assert named.translation_key == "retired_entities_automation"
    assert named.translation_placeholders == {
        "name": "Named [x]",
        "link": "[Named \\[x\\]](/config/automation/edit/1700)",
        "entities": f"- `{other}`\n- `{old}` → `{switch}`",
    }
    # Without an id, an automation can't be opened in the editor.
    assert issues["automation.device"].translation_placeholders["link"] == (
        "automation.device (`automation.device`)"
    )
    script = issues["script.tmpl"]
    assert script.translation_key == "retired_entities_script"
    assert (
        script.translation_placeholders["link"]
        == "[script.tmpl](/config/script/edit/tmpl)"
    )
    assert script.translation_placeholders["entities"] == f"- `{old}` → `{switch}`"


async def test_repair_clears_once_nothing_uses_them(hass: HomeAssistant):
    entry = _entry(hass)
    old = _retire(hass, entry, "collect_activity")
    user = _user("automation.a", "1", refs=(old,))
    _install(hass, "automation", user)
    async_check_retired_entities(hass, entry.entry_id)
    assert list(_issues(hass)) == ["automation.a"]
    user.referenced_entities = set()
    async_check_retired_entities(hass, entry.entry_id)
    assert _issues(hass) == {}


async def test_repair_ignores_other_entries_and_entities(hass: HomeAssistant):
    entry = _entry(hass)
    other = _entry(hass, "OTHER")
    used = [
        _retire(hass, other, "collect_activity"),
        _retire(hass, entry, "collect_activity", domain="switch"),
        _retire(hass, entry, "scanner_enabled"),
    ]
    registry = er.async_get(hass)
    foreign = registry.async_get_or_create(
        "binary_sensor", "other", f"{entry.entry_id}_1_collect_activity"
    ).entity_id
    registry.async_remove(foreign)
    _install(hass, "automation", _user("automation.a", "1", refs=(*used, foreign)))
    async_check_retired_entities(hass, entry.entry_id)
    assert _issues(hass) == {}
    assert _issues(hass, "OTHER") == {}


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


async def test_clears_only_this_entrys_retired_repairs(hass: HomeAssistant):
    """Including the single repair earlier test builds raised, and none of
    the entry's other repairs."""
    entry = _entry(hass)
    for issue_id in (
        "ENTRY_retired_entities",
        "ENTRY_event_collection_poll",
        "OTHER_retired_automation.a",
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="x",
        )
    async_check_retired_entities(hass, entry.entry_id)
    remaining = {
        issue_id for domain, issue_id in ir.async_get(hass).issues if domain == DOMAIN
    }
    assert remaining == {"ENTRY_event_collection_poll", "OTHER_retired_automation.a"}


async def test_repair_link_encodes_the_automation_id(hass: HomeAssistant):
    entry = _entry(hass)
    old = _retire(hass, entry, "collect_activity")
    _install(hass, "automation", _user("automation.odd", "a b)", refs=(old,)))
    async_check_retired_entities(hass, entry.entry_id)
    link = _issues(hass)["automation.odd"].translation_placeholders["link"]
    assert link == "[automation.odd](/config/automation/edit/a%20b%29)"
