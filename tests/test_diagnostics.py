"""
Tests for async_get_config_entry_diagnostics (diagnostics.py).

Covers:
- api_token redacted from config entry data
- container labels redacted from raw coordinator snapshots (labels can carry
  secrets such as reverse-proxy auth hashes)
- environment summary counts still computed from unredacted data
- update coordinator summary reflects real per-environment data (regression
  guard for a real bug the update coordinator's "environments" reshape
  silently introduced, caught only once this specific computation actually
  had test coverage)
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
            "env": {
                "id": 1,
                "name": "MyHost",
                "tlsKey": "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
                "hawserToken": "hawser_plaintext_secret_token",
            },
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
    fast.data = {"environments": FAST_DATA}
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


def _make_entry_with_update_coordinator() -> MagicMock:
    """Same as _make_entry_with_runtime_data, but with a real update
    coordinator present — the update_summary computation had zero test
    coverage before this, which is exactly how the update coordinator's
    reshape (wrapping .data in "environments", same as fast/slow) broke
    it silently: iterating the old flat shape's top level now just
    iterated a single bogus "environments" key instead of real
    per-environment data, and nothing caught it."""
    entry = _make_entry_with_runtime_data()
    update = MagicMock()
    update.data = {
        "environments": {
            1: {
                "c1": {"containerId": "c1", "hasUpdate": True},
                "c2": {"containerId": "c2", "hasUpdate": False},
            }
        }
    }
    update.last_update_success = True
    update.last_exception = None
    entry.runtime_data.update_coordinator = update
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
    for container in fast_dump["environments"][1]["containers"]:
        assert container["labels"] == REDACTED, container

    slow_dump = result["coordinator"]["slow"]["data"]
    image = slow_dump["environments"][1]["images"][0]
    assert image["labels"] == REDACTED


async def test_environment_secrets_redacted_from_coordinator_data(
    hass: HomeAssistant,
):
    """Dockhand's own GET /api/environments returns tlsKey and hawserToken
    fully decrypted with no redaction on its side — our slow coordinator
    stores that response verbatim, so we must redact these ourselves or
    they'd end up in a diagnostics dump attached to a public bug report."""
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)

    env = result["coordinator"]["slow"]["data"]["environments"][1]["env"]
    assert env["tlsKey"] == REDACTED
    assert env["hawserToken"] == REDACTED
    assert env["name"] == "MyHost"  # non-secret fields survive


async def test_summary_counts_survive_redaction(hass: HomeAssistant):
    """Compose breakdown is computed before redaction, so counts stay correct."""
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)

    summary = result["environment_summary"]["1"]
    assert summary["container_count"] == 2
    assert summary["compose_containers"] == 1
    assert summary["freestanding_containers"] == 1
    assert summary["stack_count"] == 1


async def test_update_summary_reflects_real_per_environment_data(
    hass: HomeAssistant,
):
    """Regression guard for the actual bug: update_summary must reflect
    genuine per-environment container counts, not the wrapper key itself
    misread as if it were an environment ID."""
    entry = _make_entry_with_update_coordinator()
    result = await async_get_config_entry_diagnostics(hass, entry)

    summary = result["coordinator"]["update"]["summary"]
    assert "environments" not in summary
    assert summary["1"]["container_count"] == 2
    assert summary["1"]["updates_available"] == 1
