"""Dockhand's entry on Home Assistant's System information page."""

import asyncio
from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    register.async_register_info(
        system_health_info, f"/config/integrations/integration/{DOMAIN}"
    )


async def _can_reach(hass: HomeAssistant) -> str | dict[str, str]:
    """ "ok" only when every loaded Dockhand answers.

    Through each entry's own client rather than system_health's helper, so
    an entry that skips certificate verification isn't reported unreachable.
    """
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    results = await asyncio.gather(
        *(entry.runtime_data.client.async_check_health() for entry in entries),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, TimeoutError):
            return {"type": "failed", "error": "timeout"}
        if isinstance(result, BaseException):
            return {"type": "failed", "error": "unreachable"}
    return "ok"


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    versions = sorted(
        {
            entry.runtime_data.version_coordinator.data
            for entry in entries
            if entry.runtime_data.version_coordinator.data
        }
    )
    info: dict[str, Any] = {"can_reach_server": _can_reach(hass)}
    if versions:
        info["version"] = ", ".join(versions)
    streams = [entry.runtime_data.event_stream for entry in entries]
    running = [stream for stream in streams if stream.running]
    if running:
        info["live_events"] = (
            "ok"
            if all(stream.connected for stream in running)
            else {"type": "failed", "error": "disconnected"}
        )
    info["environments"] = sum(
        len(entry.runtime_data.fast_coordinator.data.get("environments") or {})
        for entry in entries
    )
    return info
