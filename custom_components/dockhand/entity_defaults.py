"""Entities that are disabled by default, turned on for every device of a
kind from the options (docs/architecture.md §10).

Choosing a type there creates it enabled on every new device, and enables
the existing ones the integration had disabled; one you disabled yourself
stays off. Clearing it disables every one of that type again, including
any you enabled by hand: Home Assistant only records who disabled an
entity, not who enabled it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLED_ENTITIES,
    DEFAULT_ENABLE_RUNTIME_CONTROLS,
    DOMAIN,
)

# By device kind, the translation keys of the entities that are disabled by
# default. Container and stack stats and runtime controls aren't here:
# their own options decide.
OPTIONAL_ENTITIES: dict[str, tuple[str, ...]] = {
    "environment": (
        "vulnerability_scanning",
        "activity_events",
        "activity_events_today",
        "disk_usage",
        "disk_usage_images",
        "disk_usage_containers",
        "disk_usage_volumes",
        "disk_usage_build_cache",
        "vulnerabilities",
        "vulnerabilities_critical",
        "vulnerabilities_high",
        "vulnerabilities_medium",
        "vulnerabilities_low",
        "images_scanned",
        "pinned_digest_updates",
        "held_updates",
        "hawser_agent_version",
        "hawser_last_seen",
        "host_docker_version",
        "host_platform",
        "uptime",
    ),
    "container": (
        "docker_event",
        "pause",
        "resume",
        "container_auto_update",
    ),
    "stack": ("git_stack_auto_deploy",),
}

# Device identifier word → kind (helpers._device_id_env and the rest).
_KINDS = {"env": "environment", "container": "container", "stack": "stack"}


def chosen(options: Mapping[str, Any]) -> dict[str, set[str]]:
    """The entity types turned on for every device, by kind."""
    stored = options.get(CONF_ENABLED_ENTITIES) or {}
    return {
        kind: set(stored.get(kind) or ()) & set(keys)
        for kind, keys in OPTIONAL_ENTITIES.items()
    }


def _kind(entry_id: str, identifiers: Iterable[tuple[str, str]]) -> str | None:
    prefix = f"{entry_id}_"
    for domain, identifier in identifiers:
        if domain == DOMAIN and identifier.startswith(prefix):
            return _KINDS.get(identifier[len(prefix) :].split("_", 1)[0])
    return None


def enabling_chosen(
    entry_id: str, options: Mapping[str, Any], add: AddEntitiesCallback
) -> AddEntitiesCallback:
    """`add`, creating the chosen types enabled."""
    turned_on = chosen(options)

    def _add(new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        entities = list(new_entities)
        for entity in entities:
            kind = _kind(entry_id, (entity.device_info or {}).get("identifiers") or ())
            if kind and entity.translation_key in turned_on[kind]:
                entity._attr_entity_registry_enabled_default = True
        add(entities, update_before_add)

    return _add


@callback
def async_apply_choice(
    hass: HomeAssistant,
    entry_id: str,
    old: Mapping[str, Any],
    new: Mapping[str, Any],
) -> None:
    """Enable or disable the existing entities of the types whose choice
    changed between options `old` and `new`."""
    before, after = chosen(old), chosen(new)
    turn_on = {kind: after[kind] - before[kind] for kind in after}
    turn_off = {kind: before[kind] - after[kind] for kind in after}
    if not any(turn_on.values()) and not any(turn_off.values()):
        return
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    for entity in er.async_entries_for_config_entry(entities, entry_id):
        device = devices.async_get(entity.device_id) if entity.device_id else None
        kind = _kind(entry_id, device.identifiers) if device else None
        if kind is None:
            continue
        if (
            entity.translation_key in turn_on[kind]
            and entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        ):
            entities.async_update_entity(entity.entity_id, disabled_by=None)
        elif entity.translation_key in turn_off[kind] and entity.disabled_by is None:
            entities.async_update_entity(
                entity.entity_id,
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            )


# Runtime controls exist only while their option is on, which is the choice
# to use them, so they're created enabled. By platform too: the read-only
# Memory limit stats sensor shares its translation key with the control.
RUNTIME_CONTROLS = frozenset(
    {
        ("number", "container_cpu_limit"),
        ("number", "container_memory_limit"),
        ("number", "container_pids_limit"),
        ("select", "container_restart_policy"),
    }
)


@callback
def async_enable_runtime_controls(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Enable the runtime controls the integration disabled: ones created
    before they were enabled by default, and ones Home Assistant restores
    disabled when the option is turned back on. One you disabled yourself
    stays off, and so does every new entity while "Enable newly added
    entities" is off for the integration."""
    if entry.pref_disable_new_entities or not entry.options.get(
        CONF_ENABLE_RUNTIME_CONTROLS, DEFAULT_ENABLE_RUNTIME_CONTROLS
    ):
        return
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            (entity.domain, entity.translation_key) in RUNTIME_CONTROLS
            and entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        ):
            registry.async_update_entity(entity.entity_id, disabled_by=None)
