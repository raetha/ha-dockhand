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

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLED_ENTITIES, DOMAIN

# By device kind, the translation keys of the entities that are disabled by
# default. Container and stack stats aren't here: their own option decides.
OPTIONAL_ENTITIES: dict[str, tuple[str, ...]] = {
    "environment": (
        "activity_logging",
        "metrics_collection",
        "vulnerability_scanning",
        "update_checks",
        "auto_update",
        "image_pruning",
        "activity_events",
        "disk_usage",
        "vulnerabilities",
        "hawser_agent_version",
        "host_docker_version",
        "host_platform",
        "uptime",
    ),
    "container": (
        "docker_event",
        "pause",
        "resume",
        "container_auto_update",
        "container_cpu_limit",
        "container_memory_limit",
        "container_pids_limit",
        "container_restart_policy",
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
