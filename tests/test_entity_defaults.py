"""Turning disabled-by-default entity types on and off for every device of
a kind, from the options."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.const import CONF_ENABLED_ENTITIES, DOMAIN
from custom_components.dockhand.entity_defaults import (
    OPTIONAL_ENTITIES,
    async_apply_choice,
    async_enable_runtime_controls,
    chosen,
    enabling_chosen,
)

from .test_config_flow import LEGACY_ENTRY_DATA, _patch_full_setup

Disabler = er.RegistryEntryDisabler


def _entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    device: str,
    domain: str,
    key: str,
    disabled_by: Disabler | None = Disabler.INTEGRATION,
) -> str:
    device_id = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{device}")},
        )
        .id
    )
    return (
        er.async_get(hass)
        .async_get_or_create(
            domain,
            DOMAIN,
            f"{entry.entry_id}_{device}_{key}",
            config_entry=entry,
            device_id=device_id,
            translation_key=key,
            disabled_by=disabled_by,
        )
        .entity_id
    )


def _disabled_by(hass: HomeAssistant, entity_id: str) -> Disabler | None:
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None
    return entry.disabled_by


def _options(**kinds: list[str]) -> dict:
    return {CONF_ENABLED_ENTITIES: kinds}


def test_every_choice_is_a_real_translation_key():
    import json
    from pathlib import Path

    strings = json.loads(
        Path("custom_components/dockhand/strings.json").read_text(encoding="utf-8")
    )
    names = {key for platform in strings["entity"].values() for key in platform}
    for kind, keys in OPTIONAL_ENTITIES.items():
        assert set(keys) <= names
        assert list(strings["selector"][f"{kind}_entities"]["options"]) == list(keys)


def test_chosen_ignores_unknown_kinds_and_types():
    assert chosen({}) == {"environment": set(), "container": set(), "stack": set()}
    picked = chosen(_options(container=["pause", "nope"], other=["x"]))
    assert picked["container"] == {"pause"}


async def test_choosing_a_type_enables_and_clearing_it_disables(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    disk = _entity(hass, entry, "env_1", "sensor", "disk_usage")
    mine_off = _entity(
        hass, entry, "env_2", "sensor", "disk_usage", disabled_by=Disabler.USER
    )
    pause = _entity(hass, entry, "container_1_web", "button", "pause")
    resume = _entity(hass, entry, "container_1_web", "button", "resume")
    git = _entity(hass, entry, "stack_1_core", "switch", "git_stack_auto_deploy")
    # Same key on a device that isn't a stack: left alone.
    group = _entity(hass, entry, "env_1_Stacks", "switch", "git_stack_auto_deploy")
    unrelated = _entity(hass, entry, "instance", "binary_sensor", "live_updates")

    on = _options(environment=["disk_usage"], container=["pause"], stack=[])
    async_apply_choice(hass, entry.entry_id, {}, on)
    assert _disabled_by(hass, disk) is None
    assert _disabled_by(hass, mine_off) is Disabler.USER
    assert _disabled_by(hass, pause) is None
    assert _disabled_by(hass, resume) is Disabler.INTEGRATION
    assert _disabled_by(hass, git) is Disabler.INTEGRATION
    assert _disabled_by(hass, group) is Disabler.INTEGRATION
    assert _disabled_by(hass, unrelated) is Disabler.INTEGRATION

    # Nothing changed: nothing touched, even an entity disabled meanwhile.
    er.async_get(hass).async_update_entity(pause, disabled_by=Disabler.USER)
    async_apply_choice(hass, entry.entry_id, on, on)
    assert _disabled_by(hass, pause) is Disabler.USER

    off = _options(environment=[], container=["pause"], stack=["git_stack_auto_deploy"])
    async_apply_choice(hass, entry.entry_id, on, off)
    assert _disabled_by(hass, disk) is Disabler.INTEGRATION
    assert _disabled_by(hass, mine_off) is Disabler.USER
    assert _disabled_by(hass, pause) is Disabler.USER
    assert _disabled_by(hass, git) is None


def test_new_entities_of_a_chosen_type_are_created_enabled():
    def make(device: str, key: str) -> Entity:
        entity = Entity()
        entity._attr_translation_key = key
        entity._attr_entity_registry_enabled_default = False
        entity._attr_device_info = {"identifiers": {(DOMAIN, f"e_{device}")}}
        return entity

    added = MagicMock()
    add = enabling_chosen("e", _options(container=["docker_event"]), added)
    event = make("container_1_web", "docker_event")
    pause = make("container_1_web", "pause")
    elsewhere = make("env_1", "docker_event")
    no_device = Entity()
    add([event, pause, elsewhere, no_device])
    added.assert_called_once_with([event, pause, elsewhere, no_device], False)
    assert event.entity_registry_enabled_default is True
    assert pause.entity_registry_enabled_default is False
    assert elsewhere.entity_registry_enabled_default is False


async def test_options_flow_stores_the_choice_and_applies_it(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**LEGACY_ENTRY_DATA, "api_token": "dh_test_token"},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)
    with _patch_full_setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    sections = [
        key.schema for key in result["data_schema"].schema if hasattr(key, "schema")
    ]
    assert {"environment_entities", "container_entities", "stack_entities"} <= set(
        sections
    )
    with (
        _patch_full_setup(),
        patch("custom_components.dockhand.config_flow.async_apply_choice") as apply,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"container_entities": {"enabled": ["docker_event"]}},
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ENABLED_ENTITIES] == {
        "environment": [],
        "container": ["docker_event"],
        "stack": [],
    }
    apply.assert_called_once()
    _, entry_id, old, new = apply.call_args.args
    assert entry_id == entry.entry_id
    assert CONF_ENABLED_ENTITIES not in old
    assert new[CONF_ENABLED_ENTITIES]["container"] == ["docker_event"]

    # The form shows what's chosen.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    container = next(
        value
        for key, value in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == "container_entities"
    )
    all_box, enabled = container.schema.schema
    assert all_box.default() is False
    assert enabled.default() == ["docker_event"]
    stack = next(
        value
        for key, value in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == "stack_entities"
    )
    # One type: no "All".
    assert [str(k) for k in stack.schema.schema] == ["enabled"]


def test_all_checkbox_wins_when_changed():
    from custom_components.dockhand.config_flow import _chosen_in_section

    keys = ("a", "b", "c")
    # Checked: every type, whatever the list says.
    assert _chosen_in_section({"all": True, "enabled": ["a"]}, keys, {"a"}) == [
        "a",
        "b",
        "c",
    ]
    # Unchecked after everything was on: none.
    assert (
        _chosen_in_section({"all": False, "enabled": ["a", "b", "c"]}, keys, set(keys))
        == []
    )
    # Unchanged: the list decides, both ways.
    assert _chosen_in_section({"all": False, "enabled": ["b"]}, keys, {"a"}) == ["b"]
    assert _chosen_in_section(
        {"all": True, "enabled": ["a", "b"]}, keys, set(keys)
    ) == ["a", "b"]
    # No "All" (one type) or nothing answered.
    assert _chosen_in_section({"enabled": ["a"]}, keys, set()) == ["a"]
    assert _chosen_in_section({}, keys, set()) == []


async def test_runtime_controls_follow_their_option(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={"enable_runtime_controls": True}
    )
    entry.add_to_hass(hass)
    restored = _entity(
        hass, entry, "container_1_web", "number", "container_memory_limit"
    )
    mine = _entity(
        hass,
        entry,
        "container_1_web",
        "select",
        "container_restart_policy",
        disabled_by=Disabler.USER,
    )
    other = _entity(hass, entry, "container_1_web", "button", "pause")
    stats = _entity(hass, entry, "container_1_web", "sensor", "container_memory_limit")
    async_enable_runtime_controls(hass, entry)
    assert _disabled_by(hass, stats) is Disabler.INTEGRATION
    assert _disabled_by(hass, restored) is None
    assert _disabled_by(hass, mine) is Disabler.USER
    assert _disabled_by(hass, other) is Disabler.INTEGRATION

    # Option off, or new entities kept disabled: nothing changes.
    for options, pref in (({}, False), ({"enable_runtime_controls": True}, True)):
        er.async_get(hass).async_update_entity(
            restored, disabled_by=Disabler.INTEGRATION
        )
        hass.config_entries.async_update_entry(
            entry, options=options, pref_disable_new_entities=pref
        )
        async_enable_runtime_controls(hass, entry)
        assert _disabled_by(hass, restored) is Disabler.INTEGRATION


async def test_a_choice_includes_the_sensors_that_break_it_down(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, entry_id="e1")
    entry.add_to_hass(hass)
    total = _entity(hass, entry, "env_1", "sensor", "vulnerabilities")
    critical = _entity(hass, entry, "env_1", "sensor", "vulnerabilities_critical")
    scanned = _entity(hass, entry, "env_1", "sensor", "images_scanned")
    mine = _entity(hass, entry, "env_1", "sensor", "vulnerabilities_low", Disabler.USER)
    today = _entity(hass, entry, "env_1", "sensor", "activity_events_today")
    choice = {CONF_ENABLED_ENTITIES: {"environment": ["vulnerabilities"]}}

    async_apply_choice(hass, "e1", {}, choice)
    assert _disabled_by(hass, total) is None
    assert _disabled_by(hass, critical) is None
    assert _disabled_by(hass, scanned) is None
    assert _disabled_by(hass, mine) is Disabler.USER
    assert _disabled_by(hass, today) is Disabler.INTEGRATION

    async_apply_choice(hass, "e1", choice, {})
    assert _disabled_by(hass, critical) is Disabler.INTEGRATION


async def test_setup_enables_the_parts_of_a_type_chosen_earlier(hass: HomeAssistant):
    """A part added to a choice after it was made (or created disabled while
    it was off) is enabled at the next setup."""
    from custom_components.dockhand.entity_defaults import async_enable_chosen

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="e1",
        options={CONF_ENABLED_ENTITIES: {"environment": ["disk_usage"]}},
    )
    entry.add_to_hass(hass)
    part = _entity(hass, entry, "env_1", "sensor", "disk_usage_images")
    async_enable_chosen(hass, entry)
    assert _disabled_by(hass, part) is None
