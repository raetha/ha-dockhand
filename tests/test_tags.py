"""Dockhand's container and stack tags."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.dockhand import tags
from custom_components.dockhand.api import DockhandNotFoundError
from custom_components.dockhand.api import DockhandClient
from custom_components.dockhand.coordinator import DockhandFastCoordinator
from custom_components.dockhand.sensor import (
    DockhandContainerStateSensor,
    DockhandStackStatusSensor,
)

BLUE = tags.TAG_HEX["blue"]
RED = tags.TAG_HEX["red"]
SLATE = tags.TAG_HEX["slate"]
CATALOG = {
    "tags": [
        {"id": 1, "name": "media", "color": "blue"},
        {"id": 2, "name": "critical", "color": "red"},
    ]
}


def test_catalog_skips_what_dockhand_wouldnt_show():
    raw = {
        "tags": [
            {"id": 1, "name": " media ", "color": "blue"},
            {"id": 2, "name": "x" * 33, "color": "red"},
            {"id": 3, "name": "bad:name"},
            {"id": "4", "name": "no id"},
            {"id": 5, "name": "web/proxy", "color": "neon"},
            {"id": 6, "name": None},
            "junk",
        ]
    }
    assert tags.catalog_from_api(raw) == {
        1: {"name": "media", "color": BLUE},
        5: {"name": "web/proxy", "color": SLATE},
    }
    assert tags.catalog_from_api(None) == {}
    assert tags.catalog_from_api({"tags": "x"}) == {}


def test_label_tags():
    labels = {
        "dockhand.tags": "media:Blue, critical:red:shield,  ,home  cloud::server, bad!"
    }
    assert tags.label_tags(labels) == [
        {"name": "media", "color": BLUE},
        {"name": "critical", "color": RED},
        {"name": "home cloud", "color": SLATE},
    ]
    assert tags.label_tags({}) == []
    assert tags.label_tags(None) == []
    assert tags.label_tags({"dockhand.tags": 3}) == []


def test_resolve_merges_like_dockhand():
    catalog = tags.catalog_from_api(CATALOG)
    named = [
        {"name": "Media", "color": RED},  # the catalogue's colour wins
        {"name": "own", "color": RED},
        {"name": "OWN", "color": BLUE},  # once, first spelling wins
    ]
    assert tags.resolve([2, 9], named, catalog) == [
        {"name": "critical", "color": RED},
        {"name": "media", "color": BLUE},
        {"name": "own", "color": RED},
    ]
    assert tags.resolve(None, [], catalog) == []


def test_stack_label_tags():
    containers = [
        {"id": "a", "labels": {"dockhand.tags": "media"}},
        {"id": "b", "labels": {"dockhand.tags": "db:green"}},
        {"id": "c", "labels": {"dockhand.tags": "other"}},
    ]
    stack = {"name": "s", "containers": ["a", "b"]}
    assert [t["name"] for t in tags.stack_label_tags(stack, containers)] == [
        "media",
        "db",
    ]
    sent = {"labelTags": [{"name": "media", "color": "blue"}, {"name": "?"}, "x"]}
    assert tags.stack_label_tags(sent, containers) == [{"name": "media", "color": BLUE}]
    assert tags.stack_label_tags({"containers": 2}, containers) == []


def test_attributes():
    assert tags.attributes([{"name": "media", "color": BLUE}]) == {
        "tags": ["media"],
        "tag_colors": {"media": BLUE},
    }
    assert tags.attributes([]) == {"tags": [], "tag_colors": {}}


# --------------------------------------------------------------------------- #
# Read on the slow schedule by the fast coordinator
# --------------------------------------------------------------------------- #

WEB = {
    "id": "a",
    "name": "web",
    "state": "running",
    "labels": {"dockhand.tags": "edge:red"},
}
STACK = {"name": "app", "status": "running", "containers": ["a"]}


def _client() -> MagicMock:
    c = MagicMock(spec=DockhandClient)
    c.async_get_all_dashboard_stats = AsyncMock(
        return_value=[{"id": 1, "name": "local"}]
    )
    c.async_get_containers = AsyncMock(return_value=[WEB])
    c.async_get_stacks = AsyncMock(return_value=[STACK])
    c.async_get_pending_updates = AsyncMock(return_value=[])
    c.async_get_tags = AsyncMock(return_value=CATALOG)
    c.async_get_container_tags = AsyncMock(return_value={"web": [1]})
    c.async_get_stack_tags = AsyncMock(return_value={"app": [2]})
    return c


async def test_tags_reach_the_environments_data(hass: HomeAssistant):
    coord = DockhandFastCoordinator(hass, _client(), {})
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert env["container_tags"] == {
        "web": [{"name": "media", "color": BLUE}, {"name": "edge", "color": RED}]
    }
    assert env["stack_tags"] == {
        "app": [{"name": "critical", "color": RED}, {"name": "edge", "color": RED}]
    }


async def test_tags_are_read_on_the_slow_schedule(hass: HomeAssistant):
    client = _client()
    coord = DockhandFastCoordinator(hass, client, {})
    await coord.async_refresh()
    await coord.async_refresh()
    assert client.async_get_tags.await_count == 1
    assert client.async_get_container_tags.await_count == 1
    # Ten minutes on: age the reads rather than move the event loop's clock,
    # which would also fire the coordinator's own timers.
    age = timedelta(minutes=10).total_seconds()
    for key in coord._tags_read_at:
        coord._tags_read_at[key] -= age
    await coord.async_refresh()
    assert client.async_get_tags.await_count == 2
    assert client.async_get_stack_tags.await_count == 2


async def test_a_failed_read_keeps_the_tags_known(hass: HomeAssistant):
    client = _client()
    coord = DockhandFastCoordinator(hass, client, {})
    await coord.async_refresh()
    client.async_get_tags = AsyncMock(side_effect=OSError("down"))
    client.async_get_container_tags = AsyncMock(side_effect=OSError("down"))
    client.async_get_stack_tags = AsyncMock(return_value={})
    for key in coord._tags_read_at:
        coord._tags_read_at[key] -= 601
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert [t["name"] for t in env["container_tags"]["web"]] == ["media", "edge"]
    assert [t["name"] for t in env["stack_tags"]["app"]] == ["edge"]


async def test_without_tag_support_only_labels_show(hass: HomeAssistant):
    client = _client()
    for name in ("async_get_tags", "async_get_container_tags", "async_get_stack_tags"):
        setattr(client, name, AsyncMock(side_effect=DockhandNotFoundError("404")))
    coord = DockhandFastCoordinator(hass, client, {})
    await coord.async_refresh()
    env = coord.data["environments"][1]
    assert env["container_tags"] == {"web": [{"name": "edge", "color": RED}]}
    assert env["stack_tags"] == {"app": [{"name": "edge", "color": RED}]}


# --------------------------------------------------------------------------- #
# On the State and Status sensors
# --------------------------------------------------------------------------- #


def _fast_data() -> MagicMock:
    coord = MagicMock()
    coord.last_update_success = True
    coord.data = {
        "environments": {
            1: {
                "stats": {},
                "containers": [WEB],
                "stacks": [STACK],
                "container_tags": {"web": [{"name": "media", "color": BLUE}]},
                "stack_tags": {"app": [{"name": "critical", "color": RED}]},
            }
        }
    }
    return coord


@pytest.mark.parametrize(
    ("cls", "item", "expected"),
    [
        (
            DockhandContainerStateSensor,
            WEB,
            {"tags": ["media"], "tag_colors": {"media": BLUE}},
        ),
        (
            DockhandStackStatusSensor,
            STACK,
            {"tags": ["critical"], "tag_colors": {"critical": RED}},
        ),
    ],
)
def test_status_sensors_carry_tags(cls, item, expected):
    attrs = cls(
        _fast_data(), "entry", 1, "local", "http://dh", item
    ).extra_state_attributes
    assert {k: attrs[k] for k in ("tags", "tag_colors")} == expected


def test_untagged_items_have_empty_tags():
    coord = _fast_data()
    coord.data["environments"][1].pop("container_tags")
    attrs = DockhandContainerStateSensor(
        coord, "entry", 1, "local", "http://dh", WEB
    ).extra_state_attributes
    assert attrs["tags"] == []


def test_system_container_flag_on_container_and_stack():
    coord = _fast_data()
    env = coord.data["environments"][1]
    env["containers"] = [{**WEB, "systemContainer": "hawser"}]
    container = DockhandContainerStateSensor(
        coord, "entry", 1, "local", "http://dh", WEB
    )
    stack = DockhandStackStatusSensor(coord, "entry", 1, "local", "http://dh", STACK)
    assert container.extra_state_attributes["system_container"] is True
    assert stack.extra_state_attributes["system_container"] is True
    env["containers"] = [WEB]
    assert container.extra_state_attributes["system_container"] is False
    assert stack.extra_state_attributes["system_container"] is False


def test_stack_status_is_an_enum():
    coord = _fast_data()
    sensor = DockhandStackStatusSensor(coord, "entry", 1, "local", "http://dh", STACK)
    assert sensor.native_value == "running"
    coord.data["environments"][1]["stacks"] = [{**STACK, "status": "brand_new"}]
    assert sensor.native_value is None
