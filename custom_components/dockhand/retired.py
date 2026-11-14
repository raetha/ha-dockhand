"""retired.py — entities a release replaced, and a repair while automations
or scripts still use the old ones.

A retired entity is removed from the entity registry by
`_cleanup_stale_registry`. Home Assistant keeps a removed entity among the
registry's deleted entities, entity ID included, for as long as its config
entry exists, so the old entity IDs are found there and nothing needs
storing here. The repair is checked once Home Assistant has started
(automations and scripts load after integrations) and again whenever
automations are reloaded, which includes saving one in the editor, so it
clears itself once nothing uses an old entity. Templates and dashboards
can't be checked; the changelog has to cover them.

To retire an entity: add a `RetiredEntity`. Like a registry migration
(`migration.py`), it records the config schema major of the releases that
had the old entity, and stays while an entry from them can still be
upgraded; tests/test_retired.py fails once one is past that.
"""

from dataclasses import dataclass

from homeassistant.components.automation import automations_with_entity
from homeassistant.components.script import scripts_with_entity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .helpers import create_issue


@dataclass(frozen=True)
class RetiredEntity:
    """An environment entity (unique ID `{entry_id}_{env_id}_{key}`) on
    platform `domain`, replaced by `new_key` (the same key unless given)
    on platform `new_domain`, in releases after config schema major
    `from_major`."""

    domain: str
    key: str
    new_domain: str
    from_major: int
    new_key: str | None = None


RETIRED_ENTITIES: tuple[RetiredEntity, ...] = (
    # 2.0.0: environment settings became switches.
    RetiredEntity("binary_sensor", "collect_activity", "switch", 2),
    RetiredEntity("binary_sensor", "collect_metrics", "switch", 2),
    RetiredEntity("binary_sensor", "update_check_enabled", "switch", 2),
    RetiredEntity("binary_sensor", "auto_update", "switch", 2),
    RetiredEntity("binary_sensor", "image_prune_enabled", "switch", 2),
)


def retired_entity(domain: str, unique_id: str) -> RetiredEntity | None:
    """The retirement this entity falls under, if any."""
    parts = unique_id.split("_", 2)
    if len(parts) < 3 or not parts[1].isdigit():
        return None
    for retired in RETIRED_ENTITIES:
        if retired.domain == domain and retired.key == parts[2]:
            return retired
    return None


def _issue_id(entry_id: str) -> str:
    return f"{entry_id}_retired_entities"


@callback
def async_check_retired_entities(hass: HomeAssistant, entry_id: str) -> None:
    """Raise, update or clear the repair listing automations and scripts
    that still use an entity this integration retired."""
    registry = er.async_get(hass)
    lines: list[str] = []
    for deleted in list(registry.deleted_entities.values()):
        if deleted.platform != DOMAIN or deleted.config_entry_id != entry_id:
            continue
        retired = retired_entity(deleted.domain, deleted.unique_id)
        if retired is None:
            continue
        users = sorted(
            automations_with_entity(hass, deleted.entity_id)
            + scripts_with_entity(hass, deleted.entity_id)
        )
        if not users:
            continue
        prefix = deleted.unique_id[: -len(retired.key)]
        new_id = registry.async_get_entity_id(
            retired.new_domain, DOMAIN, prefix + (retired.new_key or retired.key)
        )
        old = f"`{deleted.entity_id}`" + (f" → `{new_id}`" if new_id else "")
        lines.append(f"- {old}: " + ", ".join(f"`{u}`" for u in users))

    if not lines:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry_id))
        return
    create_issue(
        hass,
        entry_id,
        _issue_id(entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="retired_entities",
        translation_placeholders={"entities": "\n".join(sorted(lines))},
    )
