"""Shared test fixtures for the Dockhand integration."""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.api import DockhandClient
from custom_components.dockhand.const import (
    DOMAIN,
    SCHEMA_MINOR_VERSION,
    SCHEMA_VERSION,
)
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
    DockhandUpdateCoordinator,
)

# ---------------------------------------------------------------------------
# Required by pytest-homeassistant-custom-component to load custom integrations
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests automatically."""
    return enable_custom_integrations


# ---------------------------------------------------------------------------
# Coordinators and config entries
# ---------------------------------------------------------------------------


def _coordinator(spec: type, data: dict[str, Any], **attrs: Any) -> MagicMock:
    """A coordinator stand-in holding `data`. The spec makes its async
    methods AsyncMocks and fails a test that reaches for something the real
    coordinator doesn't have; `attrs` sets or replaces attributes."""
    coord = MagicMock(spec=spec)
    coord.data = data
    coord.client = MagicMock(spec=DockhandClient)
    coord.last_update_success = True
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    for name, value in attrs.items():
        setattr(coord, name, value)
    return coord


def fast_coordinator(
    environments: dict[int, dict[str, Any]] | None = None, **attrs: Any
) -> MagicMock:
    """The fast coordinator, holding these environments' data."""
    return _coordinator(
        DockhandFastCoordinator, {"environments": environments or {}}, **attrs
    )


def slow_coordinator(
    environments: dict[int, dict[str, Any]] | None = None,
    schedules: list[dict[str, Any]] | None = None,
    attrs: dict[str, Any] | None = None,
    **data: Any,
) -> MagicMock:
    """The slow coordinator, holding these environments' data, the
    schedules and any other top-level data (`scanner_default`,
    `event_collection`)."""
    return _coordinator(
        DockhandSlowCoordinator,
        {"environments": environments or {}, "schedules": schedules or [], **data},
        **(attrs or {}),
    )


def update_coordinator(
    environments: dict[int, dict[str, Any]] | None = None, **attrs: Any
) -> MagicMock:
    """The update coordinator, holding each environment's results by
    container ID."""
    return _coordinator(
        DockhandUpdateCoordinator, {"environments": environments or {}}, **attrs
    )


@contextlib.contextmanager
def patch_setup(
    fast: MagicMock,
    slow: MagicMock,
    update: MagicMock | None = None,
    client: MagicMock | None = None,
) -> Iterator[MagicMock]:
    """Set an entry up with these coordinators and no network: yields the
    client. Without `update`, the update coordinator is the real one (made
    only when an option asks for it)."""
    if client is None:
        client = MagicMock()
        client.async_get_dockhand_version = AsyncMock(return_value="1.0.57")
    patches = [
        patch("custom_components.dockhand.async_get_clientsession"),
        patch("custom_components.dockhand.DockhandClient", return_value=client),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ]
    if update is not None:
        patches.append(
            patch(
                "custom_components.dockhand.DockhandUpdateCoordinator",
                return_value=update,
            )
        )
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield client


def config_entry(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> MockConfigEntry:
    """A current-schema Dockhand config entry, added to hass. `data`
    replaces the connection details; `kwargs` go to MockConfigEntry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=kwargs.pop("title", "http://dh.test:3000"),
        version=kwargs.pop("version", SCHEMA_VERSION),
        minor_version=kwargs.pop("minor_version", SCHEMA_MINOR_VERSION),
        data=(
            data
            if data is not None
            else {"api_url": "http://dh.test:3000", "api_token": "dh_test_token"}
        ),
        options=options or {},
        **kwargs,
    )
    entry.add_to_hass(hass)
    return entry


# ---------------------------------------------------------------------------
# Dockhand's own data, shaped as it sends it
# (tests/fixtures/dockhand_environment.json has a whole real environment)
# ---------------------------------------------------------------------------


def _fake_id(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def container(name: str, stack: str | None = None, **fields: Any) -> dict[str, Any]:
    """A container as GET /api/containers lists it: running, healthy-less,
    in `stack` (a compose project) if given. `fields` replace any field."""
    labels = (
        {"com.docker.compose.project": stack, "com.docker.compose.service": name}
        if stack
        else {}
    )
    return {
        "id": _fake_id(name),
        "name": name,
        "image": f"docker.io/library/{name}:latest",
        "imageId": f"sha256:{_fake_id(name + ':image')}",
        "state": "running",
        "status": "Up 2 days",
        "created": 1794458921,
        "ports": [],
        "networks": {"bridge": {"ipAddress": "172.17.0.2"}},
        "restartCount": 0,
        "mounts": [],
        "labels": labels,
        "command": "",
        "systemContainer": None,
        **fields,
    }


def stack(name: str, *containers: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """A stack as GET /api/stacks lists it, holding these containers
    (made with `container(..., stack=name)`). `fields` replace any field."""
    running = [c for c in containers if c.get("state") == "running"]
    return {
        "name": name,
        "containers": [c["id"] for c in containers],
        "containerDetails": [
            {
                "id": c["id"],
                "name": c["name"],
                "service": c["name"],
                "state": c.get("state"),
                "status": c.get("status"),
                "image": c.get("image"),
                "ports": [],
                "networks": [],
                "volumeCount": 0,
                "restartCount": c.get("restartCount", 0),
                "created": c.get("created"),
                "labels": c.get("labels", {}),
                "updateAvailable": False,
                "pinnedToDigest": False,
                "coolingDown": False,
                "newerVersion": None,
            }
            for c in containers
        ],
        "labelTags": [],
        "updatesAvailable": False,
        "updateCount": 0,
        "newerVersionCount": 0,
        "coolingDownCount": 0,
        "pinnedDigestCount": 0,
        "status": (
            "running"
            if containers and len(running) == len(containers)
            else ("partial" if running else ("stopped" if containers else "created"))
        ),
        "health": None,
        "sourceType": "internal",
        "icon": None,
        **fields,
    }


def api_client() -> MagicMock:
    """A DockhandClient stand-in answering every poll of one environment
    (ID 1, "local") holding a stand-alone container: for tests that run the
    real coordinators."""
    app = container("my-app")
    client = MagicMock(spec=DockhandClient)
    client.async_probe.return_value = None
    client.async_get_environments.return_value = [{"id": 1, "name": "local"}]
    stats = {
        "id": 1,
        "name": "local",
        "online": True,
        "connectionType": "socket",
        "containers": {"total": 1, "running": 1},
        "metrics": {"cpuPercent": 12.3, "memoryPercent": 42.5},
    }
    client.async_get_dashboard_stats.return_value = stats
    client.async_get_all_dashboard_stats.return_value = [stats]
    client.async_get_containers.return_value = [app]
    client.async_get_container_stats.return_value = []
    client.async_get_stacks.return_value = []
    client.async_get_stack_stats.return_value = []
    client.async_get_pending_updates.return_value = []
    client.async_get_images.return_value = []
    client.async_get_networks.return_value = []
    client.async_get_volumes.return_value = []
    client.async_get_schedules.return_value = []
    client.async_get_dockhand_version.return_value = "1.0.57"
    client.async_get_update_check_settings.return_value = {
        "enabled": True,
        "cron": "0 4 * * *",
        "autoUpdate": False,
    }
    client.async_get_image_prune_settings.return_value = {
        "enabled": True,
        "cronExpression": "0 3 * * 0",
        "pruneMode": "dangling",
    }
    client.async_get_scanner_setting.return_value = "grype"
    client.async_get_event_collection.return_value = {"mode": "stream", "interval": 60}
    client.async_check_self_update.return_value = {
        "updateAvailable": False,
        "currentVersion": "1.0.57",
    }
    client.async_get_tags.return_value = {"tags": []}
    client.async_get_container_tags.return_value = {}
    client.async_get_stack_tags.return_value = {}
    return client
