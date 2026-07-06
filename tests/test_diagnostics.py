"""
Tests for async_get_config_entry_diagnostics (diagnostics.py).

Covers:
- api_token redacted from config entry data
- container labels redacted from raw coordinator snapshots (labels can carry
  secrets such as reverse-proxy auth hashes)
- environment summary counts still computed from unredacted data
"""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from custom_components.dockhand.diagnostics import (
    async_get_config_entry_diagnostics,
)

SECRET_LABELS = {
    "com.docker.compose.project": "myapp",
    "traefik.http.middlewares.auth.basicauth.users": "admin:$apr1$secret",
}

FAST_DATA = {
    1: {
        "stats": {"name": "MyHost", "online": True, "connectionType": "local"},
        "containers": [
            {"id": "c1", "name": "web", "labels": SECRET_LABELS},
            {"id": "c2", "name": "nginx", "labels": {}},
        ],
        "stacks": [{"name": "myapp", "status": "running"}],
        "container_stats": {},
    }
}

SLOW_DATA = {
    "environments": {
        1: {
            "env": {"id": 1, "name": "MyHost"},
            "images": [{"id": "sha256:abc", "labels": {"org.label": "x"}}],
            "networks": [],
            "volumes": [],
        }
    },
    "schedules": [],
}


def _make_entry_with_runtime_data() -> MagicMock:
    entry = MagicMock()
    entry.data = {"api_url": "http://dh.test:3000", "api_token": "dh_secret"}
    entry.options = {}

    fast = MagicMock()
    fast.data = FAST_DATA
    fast.last_update_success = True
    fast.last_exception = None

    slow = MagicMock()
    slow.data = SLOW_DATA
    slow.last_update_success = True
    slow.last_exception = None

    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.runtime_data.update_coordinator = None
    return entry


async def test_api_token_is_redacted(hass: HomeAssistant):
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["config_entry"]["api_token"] == REDACTED
    assert result["config_entry"]["api_url"] == "http://dh.test:3000"


async def test_labels_redacted_from_coordinator_data(hass: HomeAssistant):
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)

    fast_dump = result["coordinator"]["fast"]["data"]
    for container in fast_dump[1]["containers"]:
        assert container["labels"] == REDACTED, container

    slow_dump = result["coordinator"]["slow"]["data"]
    image = slow_dump["environments"][1]["images"][0]
    assert image["labels"] == REDACTED


async def test_summary_counts_survive_redaction(hass: HomeAssistant):
    """Compose breakdown is computed before redaction, so counts stay correct."""
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)

    summary = result["environment_summary"]["1"]
    assert summary["container_count"] == 2
    assert summary["compose_containers"] == 1
    assert summary["freestanding_containers"] == 1
    assert summary["stack_count"] == 1
