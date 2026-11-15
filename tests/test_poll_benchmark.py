"""How long one poll's listeners take on a large host (docs/audits.md).

Skipped unless DOCKHAND_BENCH is set: it times, it doesn't assert. Sets the
integration up from the real-data fixture with its containers and stacks
copied out DOCKHAND_BENCH_COPIES times (default 32: 192 containers), with
every coordinator's fetch mocked, then times the fast coordinator's refresh
with all its listeners and prints the slowest functions.

    DOCKHAND_BENCH=1 .venv/bin/pytest tests/test_poll_benchmark.py -s --no-cov
"""

from __future__ import annotations

import copy
import cProfile
import io
import os
import pstats
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.dockhand.const import (
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_RESOURCE_STATS,
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_UPDATE_ENTITIES,
    CONF_ENABLE_VOLUMES,
    SCHEMA_MINOR_VERSION,
    SCHEMA_VERSION,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
    DockhandVersionCoordinator,
)

from .conftest import config_entry
from .test_real_data import _coordinator_data

pytestmark = pytest.mark.skipif(
    not os.environ.get("DOCKHAND_BENCH"), reason="set DOCKHAND_BENCH to run"
)


def _copied_out(env: dict[str, Any], copies: int) -> dict[str, Any]:
    """The environment with each container and stack copied `copies` times
    under new names and IDs, stack membership and stats following them."""
    out = {
        **copy.deepcopy(env),
        "containers": [],
        "stacks": [],
        "container_stats": {},
        "stack_stats": {},
    }
    for n in range(copies):
        new_id: dict[str, str] = {}
        for c in env["containers"]:
            c2 = copy.deepcopy(c)
            c2["id"] = new_id[c["id"]] = f"{c['id'][:-6]}{n:06d}"
            c2["name"] = f"{c['name']}{n}"
            labels = c2.get("labels") or {}
            if "com.docker.compose.project" in labels:
                labels["com.docker.compose.project"] += str(n)
            out["containers"].append(c2)
            if c["name"] in env["container_stats"]:
                out["container_stats"][c2["name"]] = env["container_stats"][c["name"]]
        for s in env["stacks"]:
            s2 = copy.deepcopy(s)
            s2["name"] = f"{s['name']}{n}"
            s2["containers"] = [new_id.get(i, i) for i in s["containers"]]
            for detail in s2.get("containerDetails") or []:
                detail["id"] = new_id.get(detail["id"], detail["id"])
                detail["name"] = f"{detail['name']}{n}"
            out["stacks"].append(s2)
            if s["name"] in env.get("stack_stats") or {}:
                out["stack_stats"][s2["name"]] = env["stack_stats"][s["name"]]
    return out


async def test_poll_benchmark(hass: HomeAssistant) -> None:
    copies = int(os.environ.get("DOCKHAND_BENCH_COPIES", "32"))
    fast, slow = _coordinator_data()
    fast["environments"] = {
        env_id: _copied_out(env, copies) for env_id, env in fast["environments"].items()
    }
    entry = config_entry(
        hass,
        title="Dockhand",
        version=SCHEMA_VERSION,
        minor_version=SCHEMA_MINOR_VERSION,
        data={"api_url": "http://dockhand.example.internal:3000", "verify_ssl": True},
        options={
            CONF_ENABLE_SCHEDULES: True,
            CONF_ENABLE_IMAGES: True,
            CONF_ENABLE_VOLUMES: True,
            CONF_ENABLE_NETWORKS: True,
            CONF_ENABLE_UPDATE_ENTITIES: True,
            CONF_ENABLE_RESOURCE_STATS: True,
            CONF_ENABLE_RUNTIME_CONTROLS: True,
        },
    )
    client = MagicMock()
    with (
        patch("custom_components.dockhand.async_get_clientsession"),
        patch("custom_components.dockhand.DockhandClient", return_value=client),
        patch("custom_components.dockhand.DockhandEventStream"),
        # A new copy each poll, as a real fetch makes.
        patch.object(
            DockhandFastCoordinator,
            "_async_update_data",
            AsyncMock(side_effect=lambda: copy.deepcopy(fast)),
        ),
        patch.object(
            DockhandSlowCoordinator,
            "_async_update_data",
            AsyncMock(side_effect=lambda: copy.deepcopy(slow)),
        ),
        patch.object(
            DockhandVersionCoordinator,
            "_async_update_data",
            AsyncMock(return_value="1.0.57"),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data.fast_coordinator
        entities = len(
            er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        )
        # The copy the mocked fetch makes is timed too; subtract it.
        started = time.perf_counter()
        copy.deepcopy(fast)
        copying = time.perf_counter() - started
        timings = []
        for _ in range(3):
            started = time.perf_counter()
            await coordinator.async_refresh()
            timings.append(time.perf_counter() - started - copying)
            await hass.async_block_till_done()
        profile = cProfile.Profile()
        profile.enable()
        await coordinator.async_refresh()
        profile.disable()
        await hass.async_block_till_done()
        await hass.config_entries.async_unload(entry.entry_id)

    containers = sum(len(env["containers"]) for env in fast["environments"].values())
    report = io.StringIO()
    pstats.Stats(profile, stream=report).sort_stats("cumulative").print_stats(
        r"dockhand", 25
    )
    print(  # noqa: T201
        f"\n{containers} containers, {entities} entities: one poll takes "
        f"{', '.join(f'{t:.3f}' for t in timings)} s\n{report.getvalue()}"
    )
