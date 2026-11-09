"""The per-container Docker event entity."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

from custom_components.dockhand.const import CONTAINER_EVENT_TYPES
from custom_components.dockhand.event import DockhandContainerEventEntity
from custom_components.dockhand.events import (
    DockhandEventStream,
    container_event_signal,
)

WEB = {"id": "c1", "name": "web", "state": "running"}


def _fast(stats: dict, containers: list[dict]) -> MagicMock:
    coord = MagicMock()
    coord.data = {"environments": {1: {"stats": stats, "containers": containers}}}
    coord.last_update_success = True
    return coord


def _entity(stats: dict | None = None, containers: list[dict] | None = None):
    return DockhandContainerEventEntity(
        _fast(
            {"collectActivity": True} if stats is None else stats,
            [WEB] if containers is None else containers,
        ),
        "entry",
        1,
        "local",
        "http://dh.test:3000",
        WEB,
    )


def test_matches_portainers_event_entity():
    entity = _entity()
    assert entity.unique_id == "entry_1_container_web_docker_event"
    assert entity.translation_key == "docker_event"
    assert entity.entity_category is EntityCategory.DIAGNOSTIC
    assert entity.entity_registry_enabled_default is False
    assert entity.event_types == CONTAINER_EVENT_TYPES


@pytest.mark.parametrize(
    ("stats", "containers", "available"),
    [
        ({"collectActivity": True}, [WEB], True),
        ({"connectionType": "hawser-edge"}, [WEB], True),
        ({}, [WEB], False),  # Dockhand sends no events for it
        ({"collectMetrics": True}, [], False),  # container gone
    ],
)
def test_available_only_where_events_arrive(stats, containers, available):
    assert _entity(stats, containers).available is available


@pytest.mark.parametrize(
    ("data", "fired", "attributes"),
    [
        (
            {"action": "die", "actorAttributes": {"exitCode": "137"}},
            "die",
            {"exit_code": 137},
        ),
        (
            {"action": "die", "actorAttributes": {"exitCode": "n/a"}},
            "die",
            {"exit_code": "n/a"},
        ),
        ({"action": "die"}, "die", {}),
        ({"action": "oom", "actorAttributes": {"exitCode": "1"}}, "oom", {}),
        ({"action": "health_status: unhealthy"}, "health_status_unhealthy", {}),
        ({"action": "create"}, None, None),
        ({"action": "health_status"}, None, None),
        ({}, None, None),
    ],
)
def test_docker_events_fire(data, fired, attributes):
    entity = _entity()
    with (
        patch.object(entity, "_trigger_event") as trigger,
        patch.object(entity, "async_write_ha_state") as write,
    ):
        entity._async_docker_event(data)
    if fired is None:
        trigger.assert_not_called()
        write.assert_not_called()
    else:
        trigger.assert_called_once_with(fired, attributes)
        write.assert_called_once()


async def test_entity_follows_its_containers_signal(hass: HomeAssistant):
    entity = _entity()
    entity.hass = hass
    with (
        patch(
            "homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass"
        ),
        patch.object(entity, "_async_docker_event") as handler,
    ):
        await entity.async_added_to_hass()
        async_dispatcher_send(
            hass, container_event_signal("entry", 1, "web"), {"action": "start"}
        )
        async_dispatcher_send(
            hass, container_event_signal("entry", 1, "db"), {"action": "start"}
        )
        await hass.async_block_till_done()
    handler.assert_called_once_with({"action": "start"})


async def test_the_feed_routes_activity_to_its_container(hass: HomeAssistant):
    entry = MagicMock()
    entry.entry_id = "entry"
    stream = DockhandEventStream(hass, entry)
    received: list[dict] = []
    async_dispatcher_connect(
        hass, container_event_signal("entry", 1, "web"), received.append
    )
    with patch("custom_components.dockhand.events.async_call_later"):
        stream._async_handle(
            "activity", {"environmentId": 1, "containerName": "web", "action": "stop"}
        )
        stream._async_handle("activity", {"environmentId": 1, "containerName": ""})
    await hass.async_block_till_done()
    assert received == [{"environmentId": 1, "containerName": "web", "action": "stop"}]
