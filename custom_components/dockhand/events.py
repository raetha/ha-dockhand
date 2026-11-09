"""Dockhand's live activity feed, so a container change shows within seconds
instead of at the next poll.

Polling stays the source of truth: an event only triggers a refresh of the
environment it names, and anything missed while disconnected is caught by
the poll and by the full refresh after each reconnect.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started

from .api import DockhandAuthError, DockhandNotFoundError, DockhandPermissionError
from .helpers import _all_envs

if TYPE_CHECKING:
    from . import DockhandConfigEntry

_LOGGER = logging.getLogger(__name__)

# Docker sends several events for one change (kill, die, stop), so an
# environment is refreshed once they settle.
REFRESH_DELAY = 2.0
RETRY_MIN = 5.0
RETRY_MAX = 300.0
# The feed isn't there (Dockhand too old) or the token's user may not
# read activity: polling alone covers it, so ask again only occasionally.
RETRY_UNAVAILABLE = 3600.0


def events_expected(fast_data: dict[str, Any] | None) -> bool:
    """Whether Dockhand watches Docker events for any environment.

    It does for an environment that collects activity or metrics, and a
    Hawser Edge agent always sends its own. Otherwise the feed would only
    ever carry heartbeats.
    """
    for env in _all_envs(fast_data).values():
        stats = env.get("stats") or {}
        if (
            stats.get("collectActivity")
            or stats.get("collectMetrics")
            or stats.get("connectionType") == "hawser-edge"
        ):
            return True
    return False


class DockhandEventStream:
    """Keeps the activity feed open while any environment can send events."""

    def __init__(self, hass: HomeAssistant, entry: DockhandConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._task: asyncio.Task[None] | None = None
        self._pending: dict[int, CALLBACK_TYPE] = {}
        self._started = False
        self.connected = False

    @property
    def running(self) -> bool:
        return self._task is not None

    @callback
    def async_setup(self) -> None:
        """Start once Home Assistant has, then follow the gate on every
        fast poll."""
        data = self._entry.runtime_data
        self._entry.async_on_unload(self.async_stop)
        self._entry.async_on_unload(
            data.fast_coordinator.async_add_listener(self._async_evaluate)
        )
        self._entry.async_on_unload(async_at_started(self._hass, self._async_started))

    @callback
    def _async_started(self, _hass: HomeAssistant) -> None:
        self._started = True
        self._async_evaluate()

    @callback
    def _async_evaluate(self) -> None:
        if not self._started:
            return
        wanted = events_expected(self._entry.runtime_data.fast_coordinator.data)
        if wanted and self._task is None:
            self._task = self._entry.async_create_background_task(
                self._hass, self._async_run(), "dockhand activity feed"
            )
        elif not wanted and self._task is not None:
            self.async_stop()

    @callback
    def async_stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.connected = False
        for cancel in self._pending.values():
            cancel()
        self._pending.clear()

    async def _async_run(self) -> None:
        client = self._entry.runtime_data.client
        delay = RETRY_MIN
        first = True
        while True:
            wait = delay
            try:
                async with client.async_open_activity_stream() as resp:
                    async for name, data in _sse_events(resp.content):
                        if name == "connected":
                            self.connected = True
                            if not first:
                                self._async_catch_up()
                            first = False
                        else:
                            # Only once Dockhand streams (a heartbeat comes
                            # every 5 s): a user with no environments gets a
                            # stream that stays silent, then times out.
                            delay = wait = RETRY_MIN
                            self._async_handle(name, data)
                _LOGGER.debug("Dockhand: activity feed closed")
            except (DockhandNotFoundError, DockhandPermissionError) as err:
                _LOGGER.debug("Dockhand: activity feed unavailable: %s", err)
                wait = RETRY_UNAVAILABLE
            except DockhandAuthError:
                # The fast coordinator raises re-authentication.
                _LOGGER.debug("Dockhand: activity feed: token rejected")
            except (ClientError, TimeoutError) as err:
                _LOGGER.debug("Dockhand: activity feed lost: %s", err)
            self.connected = False
            await asyncio.sleep(wait)
            delay = min(delay * 2, RETRY_MAX)

    @callback
    def _async_catch_up(self) -> None:
        """After a reconnect: Dockhand may have restarted (or been
        upgraded) and events were missed."""
        data = self._entry.runtime_data
        self._entry.async_create_background_task(
            self._hass,
            data.fast_coordinator.async_request_refresh(),
            "dockhand refresh after reconnect",
        )
        self._entry.async_create_background_task(
            self._hass,
            data.version_coordinator.async_request_refresh(),
            "dockhand version after reconnect",
        )

    @callback
    def _async_handle(self, name: str, data: dict[str, Any]) -> None:
        fast = self._entry.runtime_data.fast_coordinator
        if name == "env_status":
            # Online state comes from Dockhand's totals, which only a full
            # poll reads.
            self._entry.async_create_background_task(
                self._hass, fast.async_request_refresh(), "dockhand env status"
            )
        elif name == "activity":
            env_id = data.get("environmentId")
            if isinstance(env_id, int) and env_id not in self._pending:
                self._pending[env_id] = async_call_later(
                    self._hass, REFRESH_DELAY, self._refresher(env_id)
                )

    def _refresher(self, env_id: int) -> Callable[[Any], None]:
        @callback
        def _refresh(_now: Any) -> None:
            self._pending.pop(env_id, None)
            self._entry.async_create_background_task(
                self._hass,
                self._async_refresh(env_id),
                f"dockhand refresh environment {env_id}",
            )

        return _refresh

    async def _async_refresh(self, env_id: int) -> None:
        try:
            await self._entry.runtime_data.fast_coordinator.async_refresh_environment(
                env_id
            )
        except Exception as err:  # the next poll retries
            _LOGGER.debug("Dockhand: refresh of environment %s failed: %s", env_id, err)


async def _sse_events(
    content: AsyncIterable[bytes],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """(event name, JSON data) for each Server-Sent Event; anything else
    in the stream (comments, data that isn't a JSON object) is skipped."""
    name = "message"
    lines: list[str] = []
    async for raw in content:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if lines:
                try:
                    data = json.loads("\n".join(lines))
                except ValueError:
                    data = None
                if isinstance(data, dict):
                    yield name, data
            name, lines = "message", []
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            lines.append(line[5:].lstrip(" "))
