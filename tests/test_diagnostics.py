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

from .conftest import fast_coordinator, slow_coordinator, update_coordinator

SECRET_LABELS = {
    "com.docker.compose.project": "myapp",
    "traefik.http.middlewares.auth.basicauth.users": "admin:$apr1$secret",
}

FAST_DATA = {
    1: {
        "stats": {
            "name": "MyHost",
            "host": "myhost.lan",
            "online": True,
            "connectionType": "local",
        },
        "containers": [
            {
                "id": "c1",
                "name": "web",
                "labels": SECRET_LABELS,
                "networks": {"proxy": {"ipAddress": "172.20.0.5"}},
                "command": "app --password hunter2",
                "mounts": [
                    {"type": "bind", "source": "/home/me/web", "destination": "/data"}
                ],
            },
            {"id": "c2", "name": "nginx", "labels": {}},
        ],
        "stacks": [{"name": "myapp", "status": "running"}],
        "container_stats": {},
    }
}

SLOW_DATA = {
    "environments": {
        1: {
            "images": [{"id": "sha256:abc", "labels": {"org.label": "x"}}],
            "networks": [
                {
                    "name": "proxy",
                    "ipam": {
                        "config": [{"subnet": "172.20.0.0/24", "gateway": "172.20.0.1"}]
                    },
                    "containers": {"c1": {"name": "web", "ipv4Address": "172.20.0.5"}},
                }
            ],
            "volumes": [],
            "host": {
                "hostname": "myhost",
                "ipAddress": "192.168.1.5",
                "platform": "Linux",
                "environment": {
                    "id": 1,
                    "name": "MyHost",
                    "tlsKey": "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
                    "hawserToken": "hawser_plaintext_secret_token",
                },
            },
            "env_meta": {"connectionHost": "myhost.lan", "connectionPort": 2376},
            "git_stacks": [
                {
                    "stackName": "myapp",
                    "repository": {"url": "https://token@git.example/me/r.git"},
                }
            ],
            "recent_events": [
                {
                    "containerName": "web",
                    "action": "start",
                    "actorAttributes": SECRET_LABELS,
                }
            ],
        }
    },
    "schedules": [
        {"id": 1, "name": "x", "lastExecution": {"logs": "cloning https://token@git"}}
    ],
}


def _make_entry_with_runtime_data() -> MagicMock:
    entry = MagicMock()
    entry.data = {"api_url": "http://dh.test:3000", "api_token": "dh_secret"}
    entry.options = {}

    fast = fast_coordinator(FAST_DATA, last_exception=None)
    slow = slow_coordinator(**SLOW_DATA, attrs={"last_exception": None})

    entry.runtime_data.fast_coordinator = fast
    entry.runtime_data.slow_coordinator = slow
    entry.runtime_data.update_coordinator = None
    return entry


def _make_entry_with_update_coordinator() -> MagicMock:
    """Same as _make_entry_with_runtime_data, with the update coordinator's
    results too, which the update summary adds up per environment."""
    entry = _make_entry_with_runtime_data()
    update = update_coordinator(
        {
            1: {
                "c1": {"containerId": "c1", "hasUpdate": True},
                "c2": {"containerId": "c2", "hasUpdate": False},
                "dh": {
                    "containerId": "dh",
                    "containerName": "dockhand",
                    "imageName": "fnsys/dockhand:v1.0.53",
                    "hasUpdate": False,
                    "systemContainer": "dockhand",
                    "newerVersion": {"tag": "v1.0.56", "source": "self-update"},
                },
            }
        },
        last_exception=None,
    )
    update.self_update = {
        "env_id": 1,
        "container_id": "dh",
        "newerVersion": {"tag": "v1.0.56", "source": "self-update"},
    }
    entry.runtime_data.update_coordinator = update
    return entry


async def test_api_token_is_redacted(hass: HomeAssistant):
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["config_entry"]["api_token"] == REDACTED
    # The host goes; how Home Assistant reaches Dockhand stays.
    assert result["config_entry"]["api_url"] == f"http://{REDACTED}:3000"


async def test_labels_redacted_from_coordinator_data(hass: HomeAssistant):
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)

    fast_dump = result["coordinator"]["fast"]["data"]
    for container in fast_dump["environments"][1]["containers"]:
        assert container["labels"] == REDACTED, container

    slow_dump = result["coordinator"]["slow"]["data"]
    image = slow_dump["environments"][1]["images"][0]
    assert image["labels"] == REDACTED
    # Docker events carry the same labels as actor attributes.
    event = slow_dump["environments"][1]["recent_events"][0]
    assert event["actorAttributes"] == REDACTED
    assert event["action"] == "start"


async def test_addresses_and_credentials_redacted(hass: HomeAssistant):
    """Diagnostics get attached to public bug reports: the user's hosts,
    addresses and paths, git URLs and schedule logs stay out."""
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)
    fast_env = result["coordinator"]["fast"]["data"]["environments"][1]
    assert fast_env["stats"]["host"] == REDACTED
    container = fast_env["containers"][0]
    assert container["networks"]["proxy"]["ipAddress"] == REDACTED
    assert container["mounts"][0]["source"] == REDACTED
    assert container["mounts"][0]["destination"] == "/data"
    assert container["command"] == REDACTED
    slow = result["coordinator"]["slow"]["data"]
    env = slow["environments"][1]
    assert env["host"]["hostname"] == REDACTED
    assert env["host"]["ipAddress"] == REDACTED
    assert env["host"]["platform"] == "Linux"
    assert env["env_meta"] == {"connectionHost": REDACTED, "connectionPort": 2376}
    network = env["networks"][0]
    assert network["ipam"]["config"] == [{"subnet": REDACTED, "gateway": REDACTED}]
    assert network["containers"]["c1"] == {"name": "web", "ipv4Address": REDACTED}
    assert env["git_stacks"][0]["repository"]["url"] == REDACTED
    assert slow["schedules"][0]["lastExecution"]["logs"] == REDACTED
    # The source data itself is untouched.
    assert FAST_DATA[1]["stats"]["host"] == "myhost.lan"


async def test_api_url_without_a_host_is_redacted_whole(hass: HomeAssistant):
    entry = _make_entry_with_runtime_data()
    entry.data = {"api_url": "not a url", "api_token": "x"}
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["config_entry"]["api_url"] == REDACTED
    entry.data = {"api_token": "x"}
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["config_entry"]["api_url"] is None


async def test_environment_secrets_redacted_from_coordinator_data(
    hass: HomeAssistant,
):
    """Dockhand's GET /api/environments returns tlsKey and hawserToken
    decrypted, and /api/host carries the environment too: wherever they
    turn up in coordinator data, diagnostics posted in a public issue must
    not show them."""
    entry = _make_entry_with_runtime_data()
    result = await async_get_config_entry_diagnostics(hass, entry)

    slow = result["coordinator"]["slow"]["data"]["environments"][1]
    env = slow["host"]["environment"]
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
    assert summary["1"]["container_count"] == 3
    assert summary["1"]["updates_available"] == 1


async def test_update_summary_shows_system_containers_and_self_update(
    hass: HomeAssistant,
):
    entry = _make_entry_with_update_coordinator()
    result = await async_get_config_entry_diagnostics(hass, entry)

    update = result["coordinator"]["update"]
    assert update["summary"]["1"]["system_containers"] == [
        {
            "name": "dockhand",
            "image": "fnsys/dockhand:v1.0.53",
            "system_container": "dockhand",
            "has_update": False,
            "newer_version": "v1.0.56",
            "update_disabled": False,
            "error": None,
        }
    ]
    assert update["self_update"]["newerVersion"]["tag"] == "v1.0.56"
