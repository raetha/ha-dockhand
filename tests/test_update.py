"""
Tests for ContainerUpdateEntity and helpers (update.py).

Two-tier architecture: Tier 1 (always on) is sourced entirely from the
fast coordinator; Tier 2 (CONF_ENABLE_UPDATES, via update_coordinator,
optionally None) layers precise digest data on top.

Covers:
- _short_digest: both currentDigest and newDigest formats, malformed input
- installed_version / latest_version: Tier 1 (image tag, update-pending
  cache signal) and Tier 2 (real digests, prioritized over Tier 1 signals)
- available: container in fast data, container missing, env missing,
  coordinator unhealthy (last_update_success=False)
- release_summary: always None (no longer populated, consistent with HACS)
- async_release_notes: image name, ha-alert types verified (warning/info),
  scanner info note, system container warning, update disabled, no
  container, scanner+system combo, systemContainer priority over
  updateDisabled — all computed client-side from container image/labels
- _update_supported_features: normal, updateDisabled, systemContainer
- _handle_coordinator_update: triggers feature refresh
- async_install: works identically with or without Tier 2 (only ever
  needs the container ID), starts batch-update-stream with the env's
  configured vulnerabilityCriteria, polls the job to completion, reports
  update_percentage from progress lines, resets progress state in a
  finally block, requests a coordinator refresh (fast + Tier 2 if
  present), and surfaces container_not_found / action_failed (API error,
  blocked update, job error status, timeout) as HomeAssistantError.
  Falls back to vulnerability_criteria=None if the settings fetch itself
  fails.
"""

from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.dockhand.const import CONF_ENABLE_UPDATE_ENTITIES
from custom_components.dockhand.coordinator import (
    DockhandFastCoordinator,
    DockhandUpdateCoordinator,
)
from custom_components.dockhand.update import (
    ContainerUpdateEntity,
    _short_digest,
    async_setup_entry,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

ENV_ID = 1
ENTRY_ID = "test_entry_id_update"
ENV_NAME = "myenv"
CONTAINER_NAME = "nginx"
CONTAINER_ID = "abc123def456"

CONTAINER_NORMAL = {
    "id": CONTAINER_ID,
    "name": CONTAINER_NAME,
    "state": "running",
    "image": "nginx:latest",
    "labels": {},
    "systemContainer": None,
}
CONTAINER_SYSTEM = {
    **CONTAINER_NORMAL,
    "image": "ghcr.io/finsys/hawser:latest",
    "systemContainer": "hawser",
}
CONTAINER_UPDATE_DISABLED = {
    **CONTAINER_NORMAL,
    "labels": {"dockhand.update": "false"},
}

# Tier 2 (check-updates) item shapes
ITEM_UP_TO_DATE = {
    "containerId": CONTAINER_ID,
    "containerName": CONTAINER_NAME,
    "imageName": "nginx:latest",
    "currentDigest": "nginx@sha256:53bb1e23fb302fabc0d",
    "hasUpdate": False,
}

ITEM_HAS_UPDATE = {
    "containerId": CONTAINER_ID,
    "containerName": CONTAINER_NAME,
    "imageName": "nginx:latest",
    "currentDigest": "nginx@sha256:53bb1e23fb302fabc0d",
    "newDigest": "sha256:79f926e8d8fe31c0dfe90",
    "hasUpdate": True,
}


def _make_fast_coord(
    containers: list | None = None,
    scanner_enabled: bool = False,
    pending_ids: set | None = None,
) -> MagicMock:
    coord = MagicMock(spec=DockhandFastCoordinator)
    coord.data = {
        "environments": {
            ENV_ID: {
                "containers": containers
                if containers is not None
                else [CONTAINER_NORMAL],
                "stacks": [],
                "stats": {
                    "scannerEnabled": scanner_enabled,
                    "name": ENV_NAME,
                    "updateCheckEnabled": True,
                },
                "container_stats": {},
                "pending_update_container_ids": pending_ids or set(),
            }
        }
    }
    coord.last_update_success = True
    coord.async_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    coord.client = MagicMock()
    coord.client.async_start_batch_update_stream = AsyncMock(return_value="job-1")
    coord.client.async_get_update_check_settings = AsyncMock(
        return_value={"vulnerabilityCriteria": "critical_high"}
    )
    # Default: job completes immediately in "done" status with one progress
    # line reporting 100%, matching a successful single-container update.
    coord.client.async_get_job = AsyncMock(
        return_value={
            "status": "done",
            "lines": [
                {
                    "data": {
                        "type": "progress",
                        "containerId": CONTAINER_ID,
                        "step": "done",
                        "current": 1,
                        "total": 1,
                    }
                }
            ],
            "result": {"summary": {"total": 1, "success": 1}},
        }
    )
    return coord


def _make_update_coord(item: dict | None = None) -> MagicMock:
    """Tier 2 mock. item=None means "no data for this container yet" (not
    the same as update_coordinator=None, which means Tier 2 disabled
    entirely — see _make_entity's update_coordinator=... override)."""
    coord = MagicMock(spec=DockhandUpdateCoordinator)
    coord.data = {
        "environments": {ENV_ID: {CONTAINER_ID: item}} if item else {ENV_ID: {}}
    }
    coord.last_update_success = True
    coord.async_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


_UNSET = object()


def _make_entity(
    update_item: dict | None = None,
    containers: list | None = None,
    scanner_enabled: bool = False,
    pending_ids: set | None = None,
    update_coordinator=_UNSET,
    fast_coordinator: MagicMock | None = None,
) -> ContainerUpdateEntity:
    fast_coord = fast_coordinator or _make_fast_coord(
        containers, scanner_enabled, pending_ids
    )
    if update_coordinator is _UNSET:
        update_coord = _make_update_coord(update_item)
    else:
        update_coord = update_coordinator  # explicit None => Tier 2 disabled
    return ContainerUpdateEntity(
        fast_coordinator=fast_coord,
        update_coordinator=update_coord,
        entry_id=ENTRY_ID,
        env_id=ENV_ID,
        env_name=ENV_NAME,
        container_name=CONTAINER_NAME,
    )


# ---------------------------------------------------------------------------
# _short_digest
# ---------------------------------------------------------------------------


def test_short_digest_current_digest_format():
    """currentDigest: 'image@sha256:<hex>' → first 12 hex chars."""
    result = _short_digest("nginx@sha256:53bb1e23fb302fabc0d123456789")
    assert result == "53bb1e23fb30"


def test_short_digest_new_digest_format():
    """newDigest: 'sha256:<hex>' → first 12 hex chars."""
    result = _short_digest("sha256:79f926e8d8fe31c0dfe90858f90b")
    assert result == "79f926e8d8fe"


def test_short_digest_short_hex():
    """Digest shorter than 12 chars returns what's available."""
    result = _short_digest("sha256:abc")
    assert result == "abc"


def test_short_digest_malformed_falls_back():
    """Malformed string returns the original."""
    result = _short_digest("notadigest")
    assert result == "notadigest"


def test_short_digest_empty_string():
    result = _short_digest("")
    assert result == ""


# ---------------------------------------------------------------------------
# installed_version / latest_version — Tier 1 (no Tier 2 data)
# ---------------------------------------------------------------------------


def test_tier1_installed_version_is_image_tag_without_tier2():
    """No update_coordinator data at all for this container — falls back
    to the image tag from the fast coordinator's container list."""
    entity = _make_entity(update_item=None)
    assert entity.installed_version == "nginx:latest"


def test_tier1_installed_version_none_when_container_gone():
    entity = _make_entity(update_item=None, containers=[])
    assert entity.installed_version is None


def test_tier1_latest_version_equals_installed_when_no_pending_flag():
    entity = _make_entity(update_item=None)
    assert entity.latest_version == entity.installed_version == "nginx:latest"


def test_tier1_latest_version_update_pending_from_dockhand_cache():
    """Dockhand's own cheap pending-updates cache flags this container —
    even with Tier 2 (update_coordinator) entirely disabled."""
    entity = _make_entity(
        update_item=None, pending_ids={CONTAINER_ID}, update_coordinator=None
    )
    assert entity.latest_version == "update-pending"


def test_tier1_latest_version_pending_cache_ignored_for_different_container():
    entity = _make_entity(update_item=None, pending_ids={"some-other-container-id"})
    assert entity.latest_version == entity.installed_version


def test_tier1_works_fully_with_update_coordinator_none():
    """Tier 2 entirely disabled (not just empty data) — Tier 1 still
    works: image tag as installed_version, update-pending when flagged."""
    entity = _make_entity(update_coordinator=None, pending_ids={CONTAINER_ID})
    assert entity.installed_version == "nginx:latest"
    assert entity.latest_version == "update-pending"


# ---------------------------------------------------------------------------
# installed_version / latest_version — Tier 2 (real digest data present)
# ---------------------------------------------------------------------------


def test_tier2_installed_version_returns_short_digest():
    entity = _make_entity(ITEM_UP_TO_DATE)
    assert entity.installed_version == "53bb1e23fb30"


def test_tier2_installed_version_missing_digest_falls_back_to_tier1():
    item = {**ITEM_UP_TO_DATE, "currentDigest": ""}
    entity = _make_entity(item)
    assert entity.installed_version == "nginx:latest"


def test_tier2_latest_version_equals_installed_when_no_update():
    entity = _make_entity(ITEM_UP_TO_DATE)
    assert entity.latest_version == entity.installed_version


def test_tier2_latest_version_new_digest_when_update_available():
    entity = _make_entity(ITEM_HAS_UPDATE)
    assert entity.latest_version == "79f926e8d8fe"


def test_tier2_latest_version_falls_back_when_new_digest_missing():
    item = {**ITEM_HAS_UPDATE, "newDigest": ""}
    entity = _make_entity(item)
    assert entity.latest_version == entity.installed_version


def test_tier2_real_digest_prioritized_over_pending_cache():
    """Once Tier 2 has confirmed a real digest, that takes priority over
    the Tier 1 bridge sentinel even if the pending cache also flags this
    container."""
    entity = _make_entity(ITEM_HAS_UPDATE, pending_ids={CONTAINER_ID})
    assert entity.latest_version == "79f926e8d8fe"


def test_tier2_falls_back_to_tier1_pending_when_no_item_yet():
    """update_coordinator exists (Tier 2 enabled) but hasn't produced data
    for this container yet — Tier 1's pending signal still works."""
    entity = _make_entity(update_item=None, pending_ids={CONTAINER_ID})
    assert entity.latest_version == "update-pending"


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


def test_available_true_when_container_in_fast_data():
    entity = _make_entity()
    assert entity.available is True


def test_available_false_when_container_missing_from_fast_data():
    entity = _make_entity(containers=[])
    assert entity.available is False


def test_available_false_when_coordinator_not_successful():
    entity = _make_entity()
    entity.coordinator.last_update_success = False
    assert entity.available is False


def test_available_false_when_env_missing_from_fast_data():
    fast_coord = MagicMock(spec=DockhandFastCoordinator)
    fast_coord.data = {}  # no env at all
    entity = _make_entity(fast_coordinator=fast_coord)
    assert entity.available is False


def test_available_true_even_with_tier2_entirely_disabled():
    entity = _make_entity(update_coordinator=None)
    assert entity.available is True


# ---------------------------------------------------------------------------
# _update_supported_features (computed client-side from image/labels)
# ---------------------------------------------------------------------------


def test_install_supported_for_normal_container():
    from homeassistant.components.update import UpdateEntityFeature

    entity = _make_entity(containers=[CONTAINER_NORMAL])
    assert UpdateEntityFeature.INSTALL in entity._attr_supported_features


def test_install_suppressed_when_update_disabled_label():
    from homeassistant.components.update import UpdateEntityFeature

    entity = _make_entity(containers=[CONTAINER_UPDATE_DISABLED])
    assert UpdateEntityFeature.INSTALL not in entity._attr_supported_features
    assert UpdateEntityFeature.RELEASE_NOTES in entity._attr_supported_features


def test_install_suppressed_for_system_container():
    from homeassistant.components.update import UpdateEntityFeature

    entity = _make_entity(containers=[CONTAINER_SYSTEM])
    assert UpdateEntityFeature.INSTALL not in entity._attr_supported_features


def test_supported_features_work_without_tier2_data_at_all():
    """Computed purely from the container's image/labels — never needed
    check-updates data, so this works identically with Tier 2 disabled."""
    from homeassistant.components.update import UpdateEntityFeature

    entity = _make_entity(containers=[CONTAINER_SYSTEM], update_coordinator=None)
    assert UpdateEntityFeature.INSTALL not in entity._attr_supported_features


# ---------------------------------------------------------------------------
# release_summary
# ---------------------------------------------------------------------------


def test_release_summary_always_none():
    # release_summary is no longer populated — consistent with HACS convention.
    # Image name and warnings appear in async_release_notes instead.
    assert _make_entity(containers=[CONTAINER_NORMAL]).release_summary is None
    assert (
        _make_entity(
            containers=[CONTAINER_NORMAL], scanner_enabled=True
        ).release_summary
        is None
    )
    assert _make_entity(containers=[CONTAINER_SYSTEM]).release_summary is None
    assert _make_entity(containers=[CONTAINER_UPDATE_DISABLED]).release_summary is None


# ---------------------------------------------------------------------------
# async_release_notes
# ---------------------------------------------------------------------------


async def test_release_notes_includes_image_name():
    entity = _make_entity(containers=[CONTAINER_NORMAL])
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "nginx:latest" in notes


async def test_release_notes_includes_scanner_info():
    entity = _make_entity(containers=[CONTAINER_NORMAL], scanner_enabled=True)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "<ha-alert alert-type='info'>" in notes
    assert "scans images for vulnerabilities" in notes


async def test_release_notes_includes_system_container_warning():
    entity = _make_entity(containers=[CONTAINER_SYSTEM])
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "<ha-alert alert-type='warning'>" in notes
    assert "system container" in notes.lower()


async def test_release_notes_includes_update_disabled_message():
    entity = _make_entity(containers=[CONTAINER_UPDATE_DISABLED])
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "<ha-alert alert-type='info'>" in notes
    assert "dockhand.update=false" in notes


async def test_release_notes_scanner_and_system_container_both_appear():
    """Scanner note and system container warning are independent — both show."""
    entity = _make_entity(containers=[CONTAINER_SYSTEM], scanner_enabled=True)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert notes.count("<ha-alert") == 2
    assert "scans images for vulnerabilities" in notes
    assert "system container" in notes.lower()


async def test_release_notes_system_container_takes_priority_over_update_disabled():
    """A container that's both a system container AND has the label set —
    system container warning wins, update-disabled message doesn't also show."""
    container = {**CONTAINER_SYSTEM, "labels": {"dockhand.update": "false"}}
    entity = _make_entity(containers=[container])
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "system container" in notes.lower()
    assert "dockhand.update=false" not in notes


async def test_release_notes_none_when_container_gone():
    entity = _make_entity(containers=[])
    notes = await entity.async_release_notes()
    assert notes is None


async def test_release_notes_work_without_tier2_data_at_all():
    entity = _make_entity(containers=[CONTAINER_NORMAL], update_coordinator=None)
    notes = await entity.async_release_notes()
    assert notes is not None
    assert "nginx:latest" in notes


# ---------------------------------------------------------------------------
# _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_handle_coordinator_update_refreshes_features():
    from homeassistant.components.update import UpdateEntityFeature

    entity = _make_entity(containers=[CONTAINER_NORMAL])
    # Simulate the container becoming system-classified on the next poll.
    entity.coordinator.data["environments"][ENV_ID]["containers"] = [CONTAINER_SYSTEM]
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()
    assert UpdateEntityFeature.INSTALL not in entity._attr_supported_features


# ---------------------------------------------------------------------------
# async_install
# ---------------------------------------------------------------------------


async def _install(entity, **kwargs):
    """Run async_install with async_write_ha_state patched out.

    The entity is never added to hass in these unit tests, so the real
    async_write_ha_state would raise — every async_install test needs this,
    since async_install now writes state at start, on each progress line,
    and in its finally block.
    """
    with patch.object(entity, "async_write_ha_state"):
        await entity.async_install(version=None, backup=False, **kwargs)


async def test_async_install_starts_batch_update_stream():
    entity = _make_entity(ITEM_HAS_UPDATE)
    await _install(entity)
    entity.coordinator.client.async_start_batch_update_stream.assert_called_once_with(
        ENV_ID, [CONTAINER_ID], vulnerability_criteria="critical_high"
    )


async def test_async_install_works_with_tier2_entirely_disabled():
    """Install never needs a digest — only the container ID — so it works
    the same whether or not update_coordinator exists at all."""
    entity = _make_entity(update_coordinator=None)
    await _install(entity)
    entity.coordinator.client.async_start_batch_update_stream.assert_called_once_with(
        ENV_ID, [CONTAINER_ID], vulnerability_criteria="critical_high"
    )


async def test_async_install_polls_job_until_done():
    entity = _make_entity(ITEM_HAS_UPDATE)
    await _install(entity)
    entity.coordinator.client.async_get_job.assert_called_with("job-1")


async def test_async_install_reports_progress_percentage():
    """update_percentage is derived from the known step pipeline
    (pulling/scanning/creating/done), not Dockhand's current/total —
    those are a batch-index counter (current = i+1 over
    containerIds.length) that's always 1/1 for our single-container
    calls, and would incorrectly read as 100% on the very first progress
    line otherwise. Reset to None once the install finishes."""
    entity = _make_entity(ITEM_HAS_UPDATE)
    percentages_seen = []
    entity.coordinator.client.async_get_job = AsyncMock(
        return_value={
            "status": "done",
            "lines": [
                {
                    "data": {
                        "type": "progress",
                        "containerId": CONTAINER_ID,
                        "step": "pulling",
                        "current": 1,
                        "total": 1,
                    }
                },
            ],
        }
    )
    with patch.object(
        entity,
        "async_write_ha_state",
        side_effect=lambda: percentages_seen.append(entity._attr_update_percentage),
    ):
        await entity.async_install(version=None, backup=False)
    # 0 (start), 20 (pulling step), then None (finally block resets it)
    assert 20 in percentages_seen
    assert 100 not in percentages_seen  # the current/total=1/1 bug this replaced
    assert entity._attr_update_percentage is None
    assert entity._attr_in_progress is False


async def test_async_install_percentage_increases_through_full_pipeline():
    """Regression test for the current/total=1/1 bug: with scanning
    enabled, percentage should climb through pulling -> scanning ->
    creating -> done, never jumping to 100 early."""
    entity = _make_entity(ITEM_HAS_UPDATE)
    percentages_seen = []
    entity.coordinator.client.async_get_job = AsyncMock(
        return_value={
            "status": "done",
            "lines": [
                {"data": {"type": "start", "total": 1}},
                {
                    "data": {
                        "type": "progress",
                        "containerId": CONTAINER_ID,
                        "step": "pulling",
                        "current": 1,
                        "total": 1,
                    }
                },
                {
                    "data": {
                        "type": "scan_start",
                        "containerId": CONTAINER_ID,
                        "step": "scanning",
                        "current": 1,
                        "total": 1,
                    }
                },
                {
                    "data": {
                        "type": "progress",
                        "containerId": CONTAINER_ID,
                        "step": "creating",
                        "current": 1,
                        "total": 1,
                    }
                },
                {
                    "data": {
                        "type": "progress",
                        "containerId": CONTAINER_ID,
                        "step": "done",
                        "current": 1,
                        "total": 1,
                        "success": True,
                    }
                },
            ],
        }
    )
    with patch.object(
        entity,
        "async_write_ha_state",
        side_effect=lambda: percentages_seen.append(entity._attr_update_percentage),
    ):
        await entity.async_install(version=None, backup=False)
    non_none = [p for p in percentages_seen if p is not None]
    assert non_none == sorted(non_none)
    assert 20 in non_none  # pulling
    assert 45 in non_none  # scanning
    assert 75 in non_none  # creating
    assert 100 in non_none  # done


async def test_async_install_percentage_ignores_events_without_known_step():
    """pull_log/scan_log/scan_complete events have no 'step' field —
    should be silently ignored rather than clearing/erroring."""
    entity = _make_entity(ITEM_HAS_UPDATE)
    entity.coordinator.client.async_get_job = AsyncMock(
        return_value={
            "status": "done",
            "lines": [
                {
                    "data": {
                        "type": "progress",
                        "containerId": CONTAINER_ID,
                        "step": "pulling",
                        "current": 1,
                        "total": 1,
                    }
                },
                {
                    "data": {
                        "type": "pull_log",
                        "containerId": CONTAINER_ID,
                        "pullStatus": "Downloading",
                    }
                },
            ],
        }
    )
    with patch.object(entity, "async_write_ha_state"):
        await entity.async_install(version=None, backup=False)
    # Just confirming no exception — pull_log's lack of a "step" key must
    # not crash _STEP_PERCENTAGES.get() or regress the percentage.


async def test_async_install_requests_refresh_after_update():
    entity = _make_entity(ITEM_HAS_UPDATE)
    await _install(entity)
    entity.coordinator.async_refresh.assert_called_once()


async def test_async_install_also_refreshes_tier2_when_present():
    entity = _make_entity(ITEM_HAS_UPDATE)
    update_coord = entity._update_coordinator
    await _install(entity)
    update_coord.async_refresh.assert_called_once()


async def test_async_install_skips_tier2_refresh_when_disabled():
    entity = _make_entity(update_coordinator=None)
    await _install(entity)  # must not raise trying to refresh None


async def test_async_install_raises_not_found_when_container_gone():
    entity = _make_entity(containers=[])
    with pytest.raises(HomeAssistantError) as exc_info:
        await _install(entity)
    assert exc_info.value.translation_key == "container_not_found"


async def test_async_install_raises_action_failed_on_api_error():
    entity = _make_entity(ITEM_HAS_UPDATE)
    entity.coordinator.client.async_start_batch_update_stream = AsyncMock(
        side_effect=Exception("connection refused")
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await _install(entity)
    assert exc_info.value.translation_key == "action_failed"
    assert entity._attr_in_progress is False


async def test_async_install_raises_action_failed_when_blocked():
    """A 'blocked' event (vulnerability criteria exceeded) surfaces as
    action_failed with the block reason in the message."""
    entity = _make_entity(ITEM_HAS_UPDATE)
    entity.coordinator.client.async_get_job = AsyncMock(
        return_value={
            "status": "running",
            "lines": [
                {
                    "data": {
                        "type": "blocked",
                        "containerId": CONTAINER_ID,
                        "blockReason": "2 critical vulnerabilities found",
                    }
                }
            ],
        }
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await _install(entity)
    assert exc_info.value.translation_key == "action_failed"
    assert "critical vulnerabilities" in str(
        exc_info.value.translation_placeholders["error"]
    )


async def test_async_install_raises_action_failed_on_job_error_status():
    entity = _make_entity(ITEM_HAS_UPDATE)
    entity.coordinator.client.async_get_job = AsyncMock(
        return_value={"status": "error", "lines": [], "result": {"error": "boom"}}
    )
    with pytest.raises(HomeAssistantError) as exc_info:
        await _install(entity)
    assert exc_info.value.translation_key == "action_failed"
    assert "boom" in str(exc_info.value.translation_placeholders["error"])


async def test_async_install_falls_back_to_default_criteria_on_settings_error():
    """If fetching vulnerabilityCriteria fails, the update still proceeds
    with vulnerability_criteria=None (Dockhand's own server-side default)."""
    entity = _make_entity(ITEM_HAS_UPDATE)
    entity.coordinator.client.async_get_update_check_settings = AsyncMock(
        side_effect=Exception("settings unavailable")
    )
    await _install(entity)
    entity.coordinator.client.async_start_batch_update_stream.assert_called_once_with(
        ENV_ID, [CONTAINER_ID], vulnerability_criteria=None
    )


# ---------------------------------------------------------------------------
# async_setup_entry: entity lifecycle (add on qualify, remove on disqualify)
# ---------------------------------------------------------------------------


def _make_hass_mock() -> MagicMock:
    """A minimal hass mock whose async_create_task actually consumes the
    coroutine (via asyncio.ensure_future) rather than just recording the
    call — avoids a spurious 'coroutine was never awaited' warning when
    _sync_entities schedules entity.async_remove()."""
    hass = MagicMock()
    hass.async_create_task = lambda coro, *a, **k: asyncio.ensure_future(coro)
    return hass


def _make_setup_env(containers=None, update_check_enabled=True, options=None):
    """A fast coordinator + entry pair for async_setup_entry tests, with a
    capturable listener callback (mimics what
    fast_coordinator.async_add_listener(cb) would return/store)."""
    fast_coord = MagicMock(spec=DockhandFastCoordinator)
    fast_coord.data = {
        "environments": {
            ENV_ID: {
                "containers": containers
                if containers is not None
                else [CONTAINER_NORMAL],
                "stats": {
                    "name": ENV_NAME,
                    "updateCheckEnabled": update_check_enabled,
                },
            }
        }
    }
    listeners = []
    fast_coord.async_add_listener = MagicMock(
        side_effect=lambda cb: (listeners.append(cb), lambda: None)[1]
    )

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.runtime_data.fast_coordinator = fast_coord
    entry.runtime_data.update_coordinator = None
    entry.async_on_unload = MagicMock()
    entry.options = options if options is not None else {}

    return fast_coord, entry, listeners


async def test_setup_entry_creates_entity_for_qualifying_environment():
    fast_coord, entry, _ = _make_setup_env()
    add_entities = MagicMock()
    await async_setup_entry(_make_hass_mock(), entry, add_entities)
    add_entities.assert_called_once()
    created = add_entities.call_args.args[0]
    assert len(created) == 1
    assert created[0]._container_name == CONTAINER_NAME


async def test_setup_entry_skips_non_qualifying_environment():
    fast_coord, entry, _ = _make_setup_env(update_check_enabled=False)
    add_entities = MagicMock()
    await async_setup_entry(_make_hass_mock(), entry, add_entities)
    add_entities.assert_not_called()


async def test_setup_entry_skips_everything_when_update_entities_disabled():
    """CONF_ENABLE_UPDATE_ENTITIES off must skip entity creation entirely,
    even for an otherwise-qualifying environment/container — this is the
    platform-level gate added for github.com/raetha/ha-dockhand/issues/23."""
    fast_coord, entry, _ = _make_setup_env(options={CONF_ENABLE_UPDATE_ENTITIES: False})
    add_entities = MagicMock()
    await async_setup_entry(_make_hass_mock(), entry, add_entities)
    add_entities.assert_not_called()


async def test_setup_entry_creates_entities_when_update_entities_explicitly_enabled():
    fast_coord, entry, _ = _make_setup_env(options={CONF_ENABLE_UPDATE_ENTITIES: True})
    add_entities = MagicMock()
    await async_setup_entry(_make_hass_mock(), entry, add_entities)
    add_entities.assert_called_once()


async def test_setup_entry_creates_entity_when_update_check_enabled_later():
    """Turning on update-check for an environment (in Dockhand) creates
    entities on the next poll, without needing a reload."""
    fast_coord, entry, listeners = _make_setup_env(update_check_enabled=False)
    add_entities = MagicMock()
    await async_setup_entry(_make_hass_mock(), entry, add_entities)
    add_entities.assert_not_called()

    # Simulate the next fast-coordinator poll after update-check was
    # turned on in Dockhand.
    fast_coord.data["environments"][ENV_ID]["stats"]["updateCheckEnabled"] = True
    listeners[0]()

    add_entities.assert_called_once()
    created = add_entities.call_args.args[0]
    assert len(created) == 1


# Note: removal when updateCheckEnabled turns off, or a container
# disappears, is NOT tested here — that logic now lives entirely in
# __init__.py's _cleanup_stale_registry/_build_live_sets, alongside every
# other conditionally-present entity type. See test_init.py.


def test_unique_id_format():
    entity = _make_entity()
    assert entity.unique_id == f"{ENTRY_ID}_{ENV_ID}_update_{CONTAINER_NAME}"


def test_device_info_references_container_device():
    entity = _make_entity()
    identifiers = entity._attr_device_info["identifiers"]
    assert list(identifiers)[0][1] == f"container_{ENV_ID}_{CONTAINER_NAME}"


def test_has_entity_name():
    entity = _make_entity()
    assert entity._attr_has_entity_name is True


def test_translation_key():
    # Update entity uses no translation_key — consistent with HA convention
    # for devices that have a single update entity (ESPHome, UniFi, etc.).
    entity = _make_entity()
    assert not hasattr(entity, "_attr_translation_key")
