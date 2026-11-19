"""An entity skips writing its state while its inputs are unchanged
(`_update_inputs()`), so its inputs must cover everything its state and
attributes are worked out from. Set up from the real-data fixture, every
value in the fast coordinator's data is changed in turn, and every entity
whose state or attributes changed must have seen its inputs change too.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import async_get_platforms

from custom_components.dockhand.const import DOMAIN
from custom_components.dockhand.entity import DockhandEnvScopedEntity

from .test_real_data import setup_from_real_data

Change = tuple[str, Callable[[dict[str, Any]], None]]


def _changed(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int | float):
        return value + 1
    if isinstance(value, str):
        return value + "x"
    return "x"


def _leaf_changes(node: Any, path: tuple[Any, ...] = ()) -> Iterator[Change]:
    """One change per value, and per list one with its first item gone."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaf_changes(value, (*path, key))
        return
    if isinstance(node, list):
        if node:

            def drop_first(env: dict[str, Any], path: tuple[Any, ...] = path) -> None:
                _at(env, path).pop(0)

            yield f"{path} without its first item", drop_first
        for i, value in enumerate(node):
            yield from _leaf_changes(value, (*path, i))
        return

    if node is None:
        # Dockhand's own type for an empty value is unknown here.
        return

    def change(env: dict[str, Any], path: tuple[Any, ...] = path) -> None:
        parent = _at(env, path[:-1])
        parent[path[-1]] = _changed(parent[path[-1]])

    yield str(path), change


def _at(node: Any, path: tuple[Any, ...]) -> Any:
    for key in path:
        node = node[key]
    return node


def _additions(env: dict[str, Any]) -> Iterator[Change]:
    """Entries the fixture has none of: tags and pending updates."""
    for c in env["containers"]:
        name, cid = c["name"], c["id"]

        def tag(env: dict[str, Any], name: str = name) -> None:
            env["container_tags"][name] = [{"name": "db", "color": "blue"}]

        def pending(env: dict[str, Any], cid: str = cid) -> None:
            env["pending_update_container_ids"] = [cid]
            env["pending_update_details"] = {cid: {"newerVersion": "2.0"}}

        yield f"tag on {name}", tag
        yield f"pending update for {name}", pending
    for s in env["stacks"]:

        def stack_tag(env: dict[str, Any], name: str = s["name"]) -> None:
            env["stack_tags"][name] = [{"name": "prod", "color": "red"}]

        yield f"tag on stack {s['name']}", stack_tag


async def test_every_input_an_entity_reads_is_in_its_inputs(hass: HomeAssistant):
    fast, _slow, coordinator = await setup_from_real_data(hass)
    entities = [
        e
        for platform in async_get_platforms(hass, DOMAIN)
        for e in platform.entities.values()
        if isinstance(e, DockhandEnvScopedEntity)
    ]
    assert entities

    def snapshot() -> dict[str, tuple[Any, Any]]:
        out = {}
        for e in entities:
            calculated = e._async_calculate_state()
            out[e.entity_id] = (
                copy.deepcopy(e._update_inputs()),
                (calculated.state, dict(calculated.attributes)),
            )
        return out

    before = snapshot()
    env_id = next(iter(fast["environments"]))
    env = fast["environments"][env_id]
    missed: list[str] = []
    for what, change in [*_leaf_changes(env), *_additions(env)]:
        changed = copy.deepcopy(fast)
        change(changed["environments"][env_id])
        coordinator.data = changed
        after = snapshot()
        missed += [
            f"{entity_id}: {what}"
            for entity_id, (inputs, state) in after.items()
            if state != before[entity_id][1] and inputs == before[entity_id][0]
        ]
    coordinator.data = fast
    assert missed == [], "\n".join(missed[:40])
