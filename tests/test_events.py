"""Dockhand's live activity feed."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.dockhand import events
from custom_components.dockhand.api import (
    DockhandAuthError,
    DockhandClient,
    DockhandError,
    DockhandNotFoundError,
    DockhandPermissionError,
)
from custom_components.dockhand.events import (
    RETRY_MAX,
    RETRY_MIN,
    RETRY_UNAVAILABLE,
    DockhandEventStream,
    _sse_events,
    events_expected,
)


def _fast_data(**stats) -> dict:
    return {"environments": {1: {"stats": {"name": "local", **stats}}}}


@pytest.mark.parametrize(
    ("stats", "expected"),
    [
        ({}, False),
        ({"collectActivity": True}, True),
        ({"collectMetrics": True}, True),
        ({"connectionType": "hawser-edge"}, True),
        ({"connectionType": "socket", "collectMetrics": False}, False),
    ],
)
def test_events_only_when_dockhand_watches_docker(stats, expected):
    assert events_expected(_fast_data(**stats)) is expected
    assert events_expected(None) is False


async def _lines(*chunks: str):
    """As aiohttp iterates a response: one line at a time."""
    for chunk in chunks:
        for line in chunk.splitlines(keepends=True):
            yield line.encode()


async def test_server_sent_events_are_parsed():
    stream = _lines(
        ": a comment\n",
        "event: connected\n",
        'data: {"timestamp": "now"}\n',
        "\n",
        "event: activity\r\n",
        'data: {"environmentId": 1,\n',
        'data:  "action": "die"}\n',
        "\n",
        "data: not json\n",
        "\n",
        "data: [1]\n",
        "\n",
        "\n",
    )
    assert [e async for e in _sse_events(stream)] == [
        ("connected", {"timestamp": "now"}),
        ("activity", {"environmentId": 1, "action": "die"}),
    ]


# --------------------------------------------------------------------------- #
# The client's stream
# --------------------------------------------------------------------------- #


def _client(status: int) -> DockhandClient:
    response = MagicMock(status=status, content=_lines("event: connected\n"))
    response.text = AsyncMock(return_value="denied")
    session = MagicMock()

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield response

    session.get = MagicMock(side_effect=lambda *a, **kw: _ctx())
    return DockhandClient(session, {"api_url": "http://dh.test:3000", "api_token": "t"})


async def test_stream_opens_with_the_token_and_a_read_timeout():
    client = _client(200)
    async with client.async_open_activity_stream() as resp:
        assert resp.status == 200
    args = client._session.get.call_args
    assert args.args[0] == "http://dh.test:3000/api/activity/events"
    assert args.kwargs["headers"] == {
        "Accept": "text/event-stream",
        "Authorization": "Bearer t",
    }
    assert args.kwargs["timeout"].total is None
    assert args.kwargs["timeout"].sock_read == 30


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, DockhandAuthError),
        (403, DockhandPermissionError),
        (404, DockhandNotFoundError),
        (500, DockhandError),
    ],
)
async def test_stream_errors(status, error):
    with pytest.raises(error):
        async with _client(status).async_open_activity_stream():
            pass  # pragma: no cover


# --------------------------------------------------------------------------- #
# DockhandEventStream
# --------------------------------------------------------------------------- #


class _Stop(Exception):
    """Ends the feed loop from a patched sleep."""


def _entry(hass: HomeAssistant, fast_data: dict) -> MagicMock:
    entry = MagicMock()
    entry.async_on_unload = MagicMock()
    entry.async_create_background_task = MagicMock(
        side_effect=lambda hass, coro, name: hass.async_create_task(coro)
    )
    data = entry.runtime_data
    data.fast_coordinator.data = fast_data
    data.fast_coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    data.fast_coordinator.async_request_refresh = AsyncMock()
    data.fast_coordinator.async_refresh_environment = AsyncMock()
    data.version_coordinator.async_request_refresh = AsyncMock()
    return entry


def _feed(entry: MagicMock, *sessions) -> None:
    """Each session is a list of SSE chunks, or an exception to raise."""
    queue = list(sessions)

    @asynccontextmanager
    async def _open():
        session = queue.pop(0)
        if isinstance(session, BaseException):
            raise session
        yield MagicMock(content=_lines(*session))

    entry.runtime_data.client.async_open_activity_stream = _open


CONNECTED = ["event: connected\n", "data: {}\n", "\n"]


def _activity(env_id: int) -> list[str]:
    return ["event: activity\n", f'data: {{"environmentId": {env_id}}}\n', "\n"]


async def _run(stream: DockhandEventStream, sleeps: int) -> list[float]:
    """Run the loop until it has slept `sleeps` times; return the waits."""
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == sleeps:
            raise _Stop

    with patch.object(events.asyncio, "sleep", _sleep), pytest.raises(_Stop):
        await stream._async_run()
    return waits


async def test_the_feed_starts_after_home_assistant_and_follows_the_gate(
    hass: HomeAssistant,
):
    hass.set_state(CoreState.starting)
    entry = _entry(hass, _fast_data())
    stream = DockhandEventStream(hass, entry)
    with patch.object(stream, "_async_run", AsyncMock()):
        stream.async_setup()
        listener = entry.runtime_data.fast_coordinator.async_add_listener.call_args[0][
            0
        ]
        entry.runtime_data.fast_coordinator.data = _fast_data(collectActivity=True)
        listener()
        assert not stream.running  # Home Assistant hasn't started yet

        await hass.async_start()
        await hass.async_block_till_done()
        assert stream.running

        listener()  # still wanted: nothing changes
        assert stream.running

        entry.runtime_data.fast_coordinator.data = _fast_data()
        listener()
        assert not stream.running
        stream.async_stop()  # stopping twice is harmless


async def test_activity_refreshes_its_environment_once_events_settle(
    hass: HomeAssistant,
):
    entry = _entry(hass, _fast_data(collectActivity=True))
    stream = DockhandEventStream(hass, entry)
    _feed(
        entry,
        [
            *CONNECTED,
            *_activity(1),
            *_activity(1),
            *_activity(2),
            'event: activity\ndata: {"environmentId": null}\n\n',
            "event: heartbeat\ndata: {}\n\n",
        ],
    )
    assert await _run(stream, 1) == [RETRY_MIN]
    fast = entry.runtime_data.fast_coordinator
    fast.async_refresh_environment.assert_not_called()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    assert sorted(
        c.args[0] for c in fast.async_refresh_environment.await_args_list
    ) == [
        1,
        2,
    ]
    # Not a reconnect, so no catch-up refresh.
    fast.async_request_refresh.assert_not_called()


async def test_environment_status_refreshes_everything(hass: HomeAssistant):
    entry = _entry(hass, _fast_data(collectActivity=True))
    stream = DockhandEventStream(hass, entry)
    _feed(entry, [*CONNECTED, 'event: env_status\ndata: {"envId": 1}\n\n'])
    await _run(stream, 1)
    await hass.async_block_till_done()
    entry.runtime_data.fast_coordinator.async_request_refresh.assert_awaited_once()


async def test_reconnecting_catches_up(hass: HomeAssistant):
    entry = _entry(hass, _fast_data(collectActivity=True))
    stream = DockhandEventStream(hass, entry)
    _feed(entry, CONNECTED, ClientError("reset"), CONNECTED)
    assert await _run(stream, 3) == [RETRY_MIN, RETRY_MIN * 2, RETRY_MIN]
    await hass.async_block_till_done()
    data = entry.runtime_data
    data.fast_coordinator.async_request_refresh.assert_awaited_once()
    data.version_coordinator.async_request_refresh.assert_awaited_once()
    assert stream.connected is False


async def test_retries_back_off(hass: HomeAssistant):
    entry = _entry(hass, _fast_data(collectActivity=True))
    stream = DockhandEventStream(hass, entry)
    _feed(
        entry,
        *[TimeoutError() for _ in range(6)],
        DockhandAuthError("401"),
        DockhandPermissionError("403"),
        DockhandNotFoundError("404"),
    )
    assert await _run(stream, 9) == [
        5,
        10,
        20,
        40,
        80,
        160,
        RETRY_MAX,
        RETRY_UNAVAILABLE,
        RETRY_UNAVAILABLE,
    ]


async def test_stopping_cancels_pending_refreshes(hass: HomeAssistant):
    entry = _entry(hass, _fast_data(collectActivity=True))
    stream = DockhandEventStream(hass, entry)
    _feed(entry, [*CONNECTED, *_activity(1)])
    await _run(stream, 1)
    stream.async_stop()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    entry.runtime_data.fast_coordinator.async_refresh_environment.assert_not_called()
