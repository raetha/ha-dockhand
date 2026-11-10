"""Dockhand's user-defined container and stack tags (Dockhand 1.0.49+).

A tag is a short label with a colour, assigned in Dockhand or named in a
container's `dockhand.tags` label (`name[:colour[:icon]]`, comma-separated).
This mirrors Dockhand's own merge (src/lib/utils/tags-core.ts) so Home
Assistant shows the tags Dockhand's lists do: assigned tags first, then label
tags; a label naming a catalogue tag shows as that tag; a name appears once
whatever its case.

A container's tags don't include its stack's: Dockhand only adds those when
a viewer turns that on in its containers list.
"""

import re
from typing import Any

TAGS_LABEL = "dockhand.tags"

# Dockhand stores a colour key and draws it with this palette.
TAG_HEX: dict[str, str] = {
    "slate": "#64748b",
    "graphite": "#334155",
    "ruby": "#e11d48",
    "red": "#ef4444",
    "coral": "#fb7185",
    "orange": "#f97316",
    "amber": "#f59e0b",
    "gold": "#eab308",
    "lime": "#84cc16",
    "green": "#22c55e",
    "emerald": "#10b981",
    "forest": "#15803d",
    "teal": "#14b8a6",
    "cyan": "#06b6d4",
    "sky": "#0ea5e9",
    "blue": "#3b82f6",
    "indigo": "#6366f1",
    "royal": "#4338ca",
    "violet": "#8b5cf6",
    "purple": "#a855f7",
    "grape": "#7e22ce",
    "fuchsia": "#d946ef",
    "magenta": "#c026d3",
    "pink": "#ec4899",
}
DEFAULT_COLOR = "slate"
_MAX_LENGTH = 32
_TAG_CHARS = re.compile(r"^[A-Za-z0-9 _.\-/]+$")

Tag = dict[str, str]  # {"name": ..., "color": "#rrggbb"}


def _normalize(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    name = " ".join(raw.split())
    if not name or len(name) > _MAX_LENGTH or not _TAG_CHARS.match(name):
        return None
    return name


def _hex(color: Any) -> str:
    key = color.strip().lower() if isinstance(color, str) else DEFAULT_COLOR
    return TAG_HEX.get(key, TAG_HEX[DEFAULT_COLOR])


def catalog_from_api(raw: Any) -> dict[int, Tag]:
    """GET /api/tags → {id: tag}."""
    tags = raw.get("tags") if isinstance(raw, dict) else None
    catalog: dict[int, Tag] = {}
    for tag in tags if isinstance(tags, list) else []:
        if not isinstance(tag, dict) or not isinstance(tag.get("id"), int):
            continue
        name = _normalize(tag.get("name"))
        if name:
            catalog[tag["id"]] = {"name": name, "color": _hex(tag.get("color"))}
    return catalog


def label_tags(labels: Any) -> list[Tag]:
    """The tags a container's `dockhand.tags` label names."""
    raw = labels.get(TAGS_LABEL) if isinstance(labels, dict) else None
    if not isinstance(raw, str):
        return []
    tags: list[Tag] = []
    for part in raw.split(","):
        name_part, _, rest = part.partition(":")
        name = _normalize(name_part)
        if not name:
            continue
        tags.append({"name": name, "color": _hex(rest.partition(":")[0])})
    return tags


def resolve(assigned_ids: Any, named: list[Tag], catalog: dict[int, Tag]) -> list[Tag]:
    """Assigned tags, then named ones; a name matching a catalogue tag takes
    the catalogue's colour, and each name appears once."""
    by_name = {tag["name"].lower(): tag for tag in catalog.values()}
    out: list[Tag] = []
    seen: set[str] = set()
    ids = assigned_ids if isinstance(assigned_ids, list) else []
    for tag in [catalog[i] for i in ids if i in catalog] + named:
        key = tag["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(by_name.get(key, tag))
    return out


def stack_label_tags(stack: dict[str, Any], containers: list[dict]) -> list[Tag]:
    """The tags a stack's services name in their labels: Dockhand's own
    `labelTags` on the stack when it sends them, else read from the stack's
    containers (compose puts no label of its own on a stack)."""
    sent = stack.get("labelTags")
    if isinstance(sent, list):
        tags: list[Tag] = []
        for spec in sent:
            if isinstance(spec, dict) and (name := _normalize(spec.get("name"))):
                tags.append({"name": name, "color": _hex(spec.get("color"))})
        return tags
    listed = stack.get("containers")
    ids = set(listed) if isinstance(listed, list) else set()
    out: list[Tag] = []
    for container in containers:
        if container.get("id") in ids:
            out.extend(label_tags(container.get("labels")))
    return out


def attributes(tags: list[Tag]) -> dict[str, Any]:
    """State attributes: names to match in automations and templates, and
    the colour of each for dashboards."""
    return {
        "tags": [tag["name"] for tag in tags],
        "tag_colors": {tag["name"]: tag["color"] for tag in tags},
    }
