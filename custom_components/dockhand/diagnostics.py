"""diagnostics.py — HA Diagnostics platform for Dockhand.

When a user opens the integration page and clicks "Download diagnostics",
HA calls async_get_config_entry_diagnostics and includes the result in a
ZIP file they can attach to a bug report.

Sensitive fields (API token) are redacted before export.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.diagnostics import async_redact_data

from . import DockhandConfigEntry

# Fields to redact from config entry data before including in diagnostics
TO_REDACT = {"api_token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics data for a Dockhand config entry.

    Includes:
    - Redacted config entry data and options
    - Fast coordinator data shape summary (env count, container/stack counts)
    - Slow coordinator data shape summary (image/volume/network counts)
    - Raw coordinator data for detailed inspection
    """
    fast = entry.runtime_data.fast_coordinator
    slow = entry.runtime_data.slow_coordinator

    fast_data = fast.data or {}
    slow_data = slow.data or {}

    # Build a lightweight summary so the key numbers are visible at a glance
    env_summaries: dict[str, Any] = {}
    for env_id, env_data in fast_data.items():
        stats = env_data.get("stats") or {}
        containers = env_data.get("containers") or []
        stacks = env_data.get("stacks") or []
        slow_env = slow_data.get("environments", {}).get(env_id) or {}
        env_summaries[str(env_id)] = {
            "name": stats.get("name", f"env_{env_id}"),
            "online": stats.get("online"),
            "connection_type": stats.get("connectionType"),
            "container_count": len(containers),
            "stack_count": len(stacks),
            "image_count": len(slow_env.get("images") or []),
            "volume_count": len(slow_env.get("volumes") or []),
            "network_count": len(slow_env.get("networks") or []),
            # Include freestanding vs compose-managed breakdown
            "freestanding_containers": sum(
                1 for c in containers
                if not (c.get("labels") or {}).get("com.docker.compose.project")
            ),
            "compose_containers": sum(
                1 for c in containers
                if (c.get("labels") or {}).get("com.docker.compose.project")
            ),
        }

    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "environment_summary": env_summaries,
        "schedule_count": len(slow_data.get("schedules") or []),
        "coordinator": {
            "fast": {
                "last_update_success": fast.last_update_success,
                "last_exception": str(fast.last_exception) if fast.last_exception else None,
                "data": fast_data,
            },
            "slow": {
                "last_update_success": slow.last_update_success,
                "last_exception": str(slow.last_exception) if slow.last_exception else None,
                "data": slow_data,
            },
        },
    }
