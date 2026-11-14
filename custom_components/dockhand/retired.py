"""retired.py — entities a release replaced, and a repair while automations
or scripts still use the old ones.

A retired entity is removed from the entity registry by
`_cleanup_stale_registry`. Home Assistant keeps a removed entity among the
registry's deleted entities, entity ID included, for as long as its config
entry exists, so the old entity IDs are found there and nothing needs
storing here. The repair is checked once Home Assistant has started
(automations and scripts load after integrations) and again whenever
automations are reloaded, which includes saving one in the editor, so it
clears itself once nothing uses an old entity. Each automation or script
links to its editor. Templates inside automations and scripts are found by
searching their configuration's text; dashboards and template entities
aren't checked (Home Assistant offers no way to read every one), so the
changelog still has to cover them. Fixing automations for the user isn't
offered: YAML ones can't be edited from here, and a device trigger or a
template comparing states may need more than a new entity ID.

To retire an entity: add a `RetiredEntity`. Like a registry migration
(`migration.py`), it records the config schema major of the releases that
had the old entity, and stays while an entry from them can still be
upgraded; tests/test_retired.py fails once one is past that.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

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


def _issue_prefix(entry_id: str) -> str:
    return f"{entry_id}_retired_"


@dataclass(frozen=True)
class _Old:
    """A retired entity that's gone, and what replaced it."""

    entity_id: str
    registry_id: str
    new_entity_id: str | None
    pattern: re.Pattern[str]


def _retired_gone(registry: er.EntityRegistry, entry_id: str) -> list[_Old]:
    olds: list[_Old] = []
    for deleted in list(registry.deleted_entities.values()):
        if deleted.platform != DOMAIN or deleted.config_entry_id != entry_id:
            continue
        retired = retired_entity(deleted.domain, deleted.unique_id)
        if retired is None:
            continue
        prefix = deleted.unique_id[: -len(retired.key)]
        new_id = registry.async_get_entity_id(
            retired.new_domain, DOMAIN, prefix + (retired.new_key or retired.key)
        )
        olds.append(
            _Old(
                deleted.entity_id,
                deleted.id,
                new_id,
                # The entity ID as a whole word, so `…_checks_2` isn't a match.
                re.compile(rf"(?<!\w){re.escape(deleted.entity_id)}(?!\w)"),
            )
        )
    return olds


def _uses(entity: Any, old: _Old) -> bool:
    """Whether an automation or script uses `old`: as an entity it
    references, in a template (only in its configuration's text), or by
    entity registry ID (device triggers and conditions)."""
    if old.entity_id in entity.referenced_entities:
        return True
    raw = getattr(entity, "raw_config", None)
    if not raw:
        return False
    text = json.dumps(raw, default=str)
    return bool(old.pattern.search(text)) or old.registry_id in text


def _markdown_text(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", text)


@callback
def async_check_retired_entities(hass: HomeAssistant, entry_id: str) -> None:
    """Raise, update or clear a repair for each automation or script that
    still uses an entity this integration retired, as Spook raises one per
    automation for entities it can't find."""
    olds = _retired_gone(er.async_get(hass), entry_id)
    prefix = _issue_prefix(entry_id)
    raised: set[str] = set()
    if olds:
        for domain in ("automation", "script"):
            # The automation and script components keep their entities here;
            # automations_with_entity() reads the same, but only sees
            # entities they reference outside templates.
            component = hass.data.get(domain)
            for entity in list(getattr(component, "entities", ())):
                used = [old for old in olds if _uses(entity, old)]
                if not used:
                    continue
                state = hass.states.get(entity.entity_id)
                name = state.name if state else entity.entity_id
                # An automation without an `id` can't be edited in the UI.
                link = (
                    f"[{_markdown_text(name)}](/config/{domain}/edit/{entity.unique_id})"
                    if entity.unique_id
                    else f"{_markdown_text(name)} (`{entity.entity_id}`)"
                )
                changes = "\n".join(
                    f"- `{old.entity_id}`"
                    + (f" → `{old.new_entity_id}`" if old.new_entity_id else "")
                    for old in sorted(used, key=lambda o: o.entity_id)
                )
                issue_id = f"{prefix}{entity.entity_id}"
                raised.add(issue_id)
                create_issue(
                    hass,
                    entry_id,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=f"retired_entities_{domain}",
                    translation_placeholders={
                        "name": name,
                        "link": link,
                        "entities": changes,
                    },
                )

    # Clear the repairs for automations and scripts that no longer use one,
    # or are gone.
    issues = ir.async_get(hass).issues
    for domain, issue_id in list(issues):
        if domain == DOMAIN and issue_id.startswith(prefix) and issue_id not in raised:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
