"""Shared test fixtures for the Dockhand integration."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dockhand.const import (
    CONF_API_URL,
    CONF_API_TOKEN,
    CONF_POLL_INTERVAL,
    CONF_POLL_INTERVAL_SLOW,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_VOLUMES,
    CONF_ENABLE_NETWORKS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_SLOW,
    DOMAIN,
)

# ---------------------------------------------------------------------------
# Canonical test data
# ---------------------------------------------------------------------------

MOCK_API_URL = "http://dockhand.test:3000"
MOCK_TOKEN = "dh_test_token_abc123"

# Config entry data as stored after successful authenticated setup
MOCK_CONFIG_DATA: dict[str, Any] = {
    CONF_API_URL: MOCK_API_URL,
    CONF_API_TOKEN: MOCK_TOKEN,
    CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
    CONF_POLL_INTERVAL_SLOW: DEFAULT_POLL_INTERVAL_SLOW,
    CONF_ENABLE_SCHEDULES: False,
    CONF_ENABLE_IMAGES: False,
    CONF_ENABLE_VOLUMES: False,
    CONF_ENABLE_NETWORKS: False,
}

# Config entry data for a no-auth install (no token stored)
MOCK_CONFIG_DATA_NOAUTH: dict[str, Any] = {
    CONF_API_URL: MOCK_API_URL,
    CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
    CONF_POLL_INTERVAL_SLOW: DEFAULT_POLL_INTERVAL_SLOW,
    CONF_ENABLE_SCHEDULES: False,
    CONF_ENABLE_IMAGES: False,
    CONF_ENABLE_VOLUMES: False,
    CONF_ENABLE_NETWORKS: False,
}

ENV_ID = 1
ENV_NAME = "local"

MOCK_STATS: dict[str, Any] = {
    "name": ENV_NAME,
    "online": True,
    "connectionType": "local",
    "metrics": {
        "memoryPercent": 42.5,
        "memoryUsed": 4_294_967_296,
        "memoryTotal": 8_589_934_592,
        "cpuUsage": 12.3,
    },
    "containers": {
        "total": 3, "running": 2, "stopped": 1,
        "paused": 0, "restarting": 0, "unhealthy": 0,
        "pendingUpdates": 0,
    },
    "stacks": {"total": 1, "running": 1, "partial": 0, "stopped": 0},
    "images":  {"total": 4, "totalSize": 2_147_483_648},
    "volumes": {"total": 2, "totalSize": 536_870_912},
    "networks": {"total": 3, "totalSize": 0},
    "events": {"total": 17, "today": 3},
    "containersSize": 1_073_741_824,
    "buildCacheSize": 268_435_456,
}

MOCK_CONTAINER_FREE: dict[str, Any] = {
    "id": "abc123def456",
    "name": "my-app",
    "state": "running",
    "status": "Up 2 days",
    "image": "nginx:latest",
    "restartCount": 0,
    "networks": {"bridge": {"ipAddress": "172.17.0.2"}},
    "labels": {},
    "health": None,
}

MOCK_CONTAINER_COMPOSE: dict[str, Any] = {
    "id": "compose111222",
    "name": "mystack_web_1",
    "state": "running",
    "status": "Up 1 day",
    "image": "nginx:latest",
    "restartCount": 0,
    "networks": {"mystack_default": {"ipAddress": "172.18.0.2"}},
    "labels": {"com.docker.compose.project": "mystack"},
    "health": None,
}

MOCK_CONTAINER_HEALTHY: dict[str, Any] = {
    "id": "healthy999",
    "name": "healthy-app",
    "state": "running",
    "status": "Up 3 hours (healthy)",
    "image": "postgres:15",
    "restartCount": 0,
    "networks": {},
    "labels": {},
    "health": "healthy",
    "healthcheck": {"test": ["CMD", "pg_isready"]},
}

MOCK_STACK: dict[str, Any] = {
    "name": "mystack",
    "status": "running",
    "type": 2,
    "containers": [MOCK_CONTAINER_COMPOSE["id"]],
}


def make_fast_data(
    containers: list | None = None,
    stacks: list | None = None,
) -> dict[int, dict]:
    return {
        ENV_ID: {
            "stats": MOCK_STATS,
            "containers": containers if containers is not None else [MOCK_CONTAINER_FREE],
            "stacks": stacks if stacks is not None else [MOCK_STACK],
        }
    }


def make_slow_data(
    images: list | None = None,
    networks: list | None = None,
    volumes: list | None = None,
    schedules: list | None = None,
) -> dict:
    return {
        "environments": {
            ENV_ID: {
                "env": {"id": ENV_ID, "name": ENV_NAME, "url": MOCK_API_URL},
                "images":   images   if images   is not None else [],
                "networks": networks if networks is not None else [],
                "volumes":  volumes  if volumes  is not None else [],
            }
        },
        "schedules": schedules if schedules is not None else [],
    }


# ---------------------------------------------------------------------------
# Reusable mock for DockhandClient
# ---------------------------------------------------------------------------

def make_mock_client(
    raise_on_probe: Exception | None = None,
) -> MagicMock:
    """Return a MagicMock that replaces DockhandClient."""
    client = MagicMock()
    if raise_on_probe:
        client.async_probe = AsyncMock(side_effect=raise_on_probe)
    else:
        client.async_probe = AsyncMock(return_value=None)

    client.async_get_environments = AsyncMock(return_value=[{"id": ENV_ID, "name": ENV_NAME}])
    client.async_get_dashboard_stats = AsyncMock(return_value=MOCK_STATS)
    client.async_get_containers = AsyncMock(return_value=[MOCK_CONTAINER_FREE])
    client.async_get_stacks = AsyncMock(return_value=[MOCK_STACK])
    client.async_get_images = AsyncMock(return_value=[])
    client.async_get_networks = AsyncMock(return_value=[])
    client.async_get_volumes = AsyncMock(return_value=[])
    client.async_get_schedules = AsyncMock(return_value=[])

    client.async_start_container = AsyncMock()
    client.async_stop_container = AsyncMock()
    client.async_restart_container = AsyncMock()
    client.async_start_stack = AsyncMock()
    client.async_stop_stack = AsyncMock()
    client.async_restart_stack = AsyncMock()
    return client


@pytest.fixture
def mock_client() -> MagicMock:
    """Standard mock DockhandClient with successful responses."""
    return make_mock_client()
