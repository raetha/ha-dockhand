"""
Tests for migration.py.

Covers migrate_1_7_3_entry_scoped_unique_ids: correct rename of every old
dockhand_* unique_id pattern, no-op on already-migrated IDs, and no-op on
unrelated entities registered under the same config entry.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.const import DOMAIN
from custom_components.dockhand.migration import (
    _is_hex64,
    async_run_migrations,
    migrate_1_4_0_update_entity_unique_ids,
    migrate_1_5_0_container_device_identifiers,
    migrate_1_7_3_entry_scoped_unique_ids,
    migrate_1_8_0_container_stats_option,
    migrate_1_8_0_reenable_container_stats_entities,
    migrate_1_8_0_remove_consolidated_disk_sensors,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ENTRY_ID = "mock_entry_id_abcd1234"


def _make_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain="dockhand",
        entry_id=ENTRY_ID,
        data={
            "api_url": "http://dh.test:3000",
            "api_token": "tok",
            "enable_schedules": False,
            "enable_images": False,
            "enable_volumes": False,
            "enable_networks": False,
        },
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)
    return entry


def _add_entity(
    hass: HomeAssistant, entry: MockConfigEntry, unique_id: str
) -> er.RegistryEntry:
    registry = er.async_get(hass)
    return registry.async_get_or_create(
        "sensor",
        "dockhand",
        unique_id,
        config_entry=entry,
    )


def _add_binary_sensor(
    hass: HomeAssistant, entry: MockConfigEntry, unique_id: str
) -> er.RegistryEntry:
    registry = er.async_get(hass)
    return registry.async_get_or_create(
        "binary_sensor",
        "dockhand",
        unique_id,
        config_entry=entry,
    )


def _get_uid(hass: HomeAssistant, entity_id: str) -> str | None:
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    return entry.unique_id if entry else None


# ---------------------------------------------------------------------------
# migrate_1_7_3_entry_scoped_unique_ids
# ---------------------------------------------------------------------------


def test_env_entity_migrated(hass: HomeAssistant):
    """dockhand_env_{env_id}_{suffix} → {entry_id}_{env_id}_{suffix}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_env_1_cpu")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_cpu"


def test_env_entity_multiword_suffix(hass: HomeAssistant):
    """dockhand_env_{env_id}_{multi_word_suffix} → {entry_id}_{env_id}_{multi_word_suffix}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_env_1_image_prune_enabled")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_image_prune_enabled"


def test_container_entity_migrated(hass: HomeAssistant):
    """dockhand_container_{env_id}_{name}_{suffix} → {entry_id}_{env_id}_container_{name}_{suffix}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_container_1_nginx_state")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_container_nginx_state"


def test_stack_entity_migrated(hass: HomeAssistant):
    """dockhand_stack_{env_id}_{name}_{suffix} → {entry_id}_{env_id}_stack_{name}_{suffix}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_stack_1_myapp_running")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_stack_myapp_running"


def test_image_entity_migrated(hass: HomeAssistant):
    """dockhand_image_{env_id}_{hash} → {entry_id}_{env_id}_image_{hash}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_image_1_deadbeef1234")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_image_deadbeef1234"


def test_network_entity_migrated(hass: HomeAssistant):
    """dockhand_network_{env_id}_{id} → {entry_id}_{env_id}_network_{id}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_network_1_net123")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_network_net123"


def test_volume_entity_migrated(hass: HomeAssistant):
    """dockhand_volume_{env_id}_{name} → {entry_id}_{env_id}_volume_{name}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_volume_1_mydata")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_volume_mydata"


def test_update_entity_migrated(hass: HomeAssistant):
    """dockhand_update_{env_id}_{name} → {entry_id}_{env_id}_update_{name}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_update_1_nginx")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_update_nginx"


def test_sched_entity_migrated(hass: HomeAssistant):
    """dockhand_sched_{id}_{type}_{suffix} → {entry_id}_sched_{id}_{type}_{suffix}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_sched_42_system_next_run")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_sched_42_system_next_run"


def test_sched_last_status_migrated(hass: HomeAssistant):
    """dockhand_sched_{id}_{type}_last_status → {entry_id}_sched_{id}_{type}_last_status."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_sched_7_prune_last_status")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_sched_7_prune_last_status"


def test_all_env_entities_migrated_together(hass: HomeAssistant):
    """All old-format entities in one entry are migrated in a single call."""
    entry = _make_entry(hass)
    old_uids = [
        "dockhand_env_1_cpu",
        "dockhand_container_1_nginx_state",
        "dockhand_stack_1_myapp_running",
        "dockhand_image_1_deadbeef",
        "dockhand_network_1_netXYZ",
        "dockhand_volume_1_mydata",
        "dockhand_update_1_nginx",
        "dockhand_sched_1_system_next_run",
    ]
    entities = [_add_entity(hass, entry, uid) for uid in old_uids]

    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)

    new_uids = [_get_uid(hass, e.entity_id) for e in entities]
    assert all(uid.startswith(ENTRY_ID) for uid in new_uids), (
        f"Not all UIDs were migrated: {new_uids}"
    )
    assert not any(uid.startswith("dockhand_") for uid in new_uids), (
        f"Some UIDs still have old prefix: {new_uids}"
    )


def test_already_migrated_uid_is_no_op(hass: HomeAssistant):
    """Entities with new-format UIDs are not touched."""
    entry = _make_entry(hass)
    new_uid = f"{ENTRY_ID}_1_cpu"
    ent = _add_entity(hass, entry, new_uid)
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == new_uid


def test_unrelated_entity_uid_is_not_touched(hass: HomeAssistant):
    """Entities registered under the entry but with unrecognised UIDs are left alone."""
    entry = _make_entry(hass)
    # Simulate a hypothetical external entity or future format
    ent = _add_entity(hass, entry, "some_other_platform_entity_xyz")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    assert _get_uid(hass, ent.entity_id) == "some_other_platform_entity_xyz"


def test_entities_from_other_entry_are_not_touched(hass: HomeAssistant):
    """Entities belonging to a different config entry are never migrated."""
    other_entry = MockConfigEntry(
        domain="dockhand",
        data={
            "api_url": "http://other.test:3000",
            "api_token": "tok2",
            "enable_schedules": False,
            "enable_images": False,
            "enable_volumes": False,
            "enable_networks": False,
        },
        title="http://other.test:3000",
    )
    other_entry.add_to_hass(hass)

    # Same-looking old UID, but belongs to the other entry
    other_ent = _add_entity(hass, other_entry, "dockhand_env_1_cpu")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)

    # Must still have the old UID — we only migrated ENTRY_ID's entities
    assert _get_uid(hass, other_ent.entity_id) == "dockhand_env_1_cpu"


def test_env_id_word_dropped_not_preserved(hass: HomeAssistant):
    """The 'env' type word is dropped, not preserved, in the migrated UID."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_env_2_mem_percent")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    uid = _get_uid(hass, ent.entity_id)
    assert uid == f"{ENTRY_ID}_2_mem_percent"
    # Explicitly confirm 'env' does NOT appear between entry_id and env_id
    assert f"{ENTRY_ID}_env_" not in uid


def test_env_id_reordered_before_type(hass: HomeAssistant):
    """For object-type entities, env_id precedes the type word in the new UID."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_container_3_myapp_cpu")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    uid = _get_uid(hass, ent.entity_id)
    # Correct: {entry_id}_3_container_myapp_cpu
    assert uid == f"{ENTRY_ID}_3_container_myapp_cpu"
    # Confirm old order (container before env_id) is gone
    assert f"{ENTRY_ID}_container_3_" not in uid


def test_migration_idempotent(hass: HomeAssistant):
    """Running the migration twice produces the same result as running it once."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_env_1_cpu")
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    uid_after_first = _get_uid(hass, ent.entity_id)
    migrate_1_7_3_entry_scoped_unique_ids(hass, ENTRY_ID)
    uid_after_second = _get_uid(hass, ent.entity_id)
    assert uid_after_first == uid_after_second


# ---------------------------------------------------------------------------
# _is_hex64
# ---------------------------------------------------------------------------


def test_is_hex64_valid():
    assert _is_hex64("a" * 64)
    assert _is_hex64("0123456789abcdef" * 4)


def test_is_hex64_wrong_length():
    assert not _is_hex64("a" * 63)
    assert not _is_hex64("a" * 65)
    assert not _is_hex64("")


def test_is_hex64_uppercase_rejected():
    assert not _is_hex64("A" * 64)


def test_is_hex64_non_hex_chars():
    assert not _is_hex64("g" * 64)
    assert not _is_hex64("z" * 64)


# ---------------------------------------------------------------------------
# migrate_1_4_0_update_entity_unique_ids
# ---------------------------------------------------------------------------

CONTAINER_HASH = "a" * 64
FAST_DATA_1_4 = {
    1: {
        "containers": [{"id": CONTAINER_HASH, "name": "nginx"}],
        "stacks": [],
    }
}


def test_1_4_0_migrates_hash_to_name(hass: HomeAssistant):
    """Old dockhand_update_{64-char-hash} → dockhand_update_{env_id}_{name}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"dockhand_update_{CONTAINER_HASH}")
    migrate_1_4_0_update_entity_unique_ids(hass, ENTRY_ID, FAST_DATA_1_4)
    assert _get_uid(hass, ent.entity_id) == "dockhand_update_1_nginx"


def test_1_4_0_already_name_based_is_no_op(hass: HomeAssistant):
    """New-format dockhand_update_{env_id}_{name} is left untouched."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_update_1_nginx")
    migrate_1_4_0_update_entity_unique_ids(hass, ENTRY_ID, FAST_DATA_1_4)
    assert _get_uid(hass, ent.entity_id) == "dockhand_update_1_nginx"


def test_1_4_0_hash_not_in_fast_data_is_skipped(hass: HomeAssistant):
    """Hash not in live data (container gone) is left for stale cleanup."""
    entry = _make_entry(hass)
    other_hash = "b" * 64
    ent = _add_entity(hass, entry, f"dockhand_update_{other_hash}")
    migrate_1_4_0_update_entity_unique_ids(hass, ENTRY_ID, FAST_DATA_1_4)
    # UID unchanged — stale cleanup will handle it
    assert _get_uid(hass, ent.entity_id) == f"dockhand_update_{other_hash}"


def test_1_4_0_empty_fast_data_returns_early(hass: HomeAssistant):
    """Empty fast data short-circuits with no registry reads."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"dockhand_update_{CONTAINER_HASH}")
    migrate_1_4_0_update_entity_unique_ids(hass, ENTRY_ID, {})
    assert _get_uid(hass, ent.entity_id) == f"dockhand_update_{CONTAINER_HASH}"


def test_1_4_0_non_update_entity_is_not_touched(hass: HomeAssistant):
    """Non-update entities are ignored even if uid starts with dockhand_."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"dockhand_container_{CONTAINER_HASH}_state")
    migrate_1_4_0_update_entity_unique_ids(hass, ENTRY_ID, FAST_DATA_1_4)
    assert _get_uid(hass, ent.entity_id) == f"dockhand_container_{CONTAINER_HASH}_state"


def test_1_4_0_multiple_envs_and_containers(hass: HomeAssistant):
    """Migration handles multiple environments and containers correctly."""
    hash1, hash2 = "1" * 64, "2" * 64
    fast_data = {
        1: {"containers": [{"id": hash1, "name": "nginx"}], "stacks": []},
        2: {"containers": [{"id": hash2, "name": "redis"}], "stacks": []},
    }
    entry = _make_entry(hass)
    ent1 = _add_entity(hass, entry, f"dockhand_update_{hash1}")
    ent2 = _add_entity(hass, entry, f"dockhand_update_{hash2}")
    migrate_1_4_0_update_entity_unique_ids(hass, ENTRY_ID, fast_data)
    assert _get_uid(hass, ent1.entity_id) == "dockhand_update_1_nginx"
    assert _get_uid(hass, ent2.entity_id) == "dockhand_update_2_redis"


# ---------------------------------------------------------------------------
# migrate_1_5_0_container_device_identifiers
# ---------------------------------------------------------------------------

FAST_DATA_1_5 = {
    1: {
        "containers": [{"id": CONTAINER_HASH, "name": "nginx"}],
        "stacks": [],
    }
}


def _add_device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str):
    reg = dr.async_get(hass)
    return reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, identifier)},
    )


def _get_device_identifiers(hass: HomeAssistant, device_id: str) -> set:
    reg = dr.async_get(hass)
    dev = reg.async_get(device_id)
    return set(dev.identifiers) if dev else set()


def test_1_5_0_migrates_pre_1_5_device_hash_format(hass: HomeAssistant):
    """container_{64-char-hash} → container_{env_id}_{name}."""
    entry = _make_entry(hass)
    dev = _add_device(hass, entry, f"container_{CONTAINER_HASH}")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    idents = _get_device_identifiers(hass, dev.id)
    assert (DOMAIN, "container_1_nginx") in idents


def test_1_5_0_migrates_1_5_device_env_hash_format(hass: HomeAssistant):
    """container_{env_id}_{64-char-hash} → container_{env_id}_{name}."""
    entry = _make_entry(hass)
    dev = _add_device(hass, entry, f"container_1_{CONTAINER_HASH}")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    idents = _get_device_identifiers(hass, dev.id)
    assert (DOMAIN, "container_1_nginx") in idents


def test_1_5_0_name_based_device_is_no_op(hass: HomeAssistant):
    """Already-migrated container_{env_id}_{name} device is not touched."""
    entry = _make_entry(hass)
    dev = _add_device(hass, entry, "container_1_nginx")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    idents = _get_device_identifiers(hass, dev.id)
    assert (DOMAIN, "container_1_nginx") in idents


def test_1_5_0_migrates_pre_1_5_entity_hash_format(hass: HomeAssistant):
    """dockhand_container_{hash}_{suffix} → dockhand_container_{env_id}_{name}_{suffix}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"dockhand_container_{CONTAINER_HASH}_state")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    assert _get_uid(hass, ent.entity_id) == "dockhand_container_1_nginx_state"


def test_1_5_0_migrates_1_5_entity_env_hash_format(hass: HomeAssistant):
    """dockhand_container_{env_id}_{hash}_{suffix} → dockhand_container_{env_id}_{name}_{suffix}."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"dockhand_container_1_{CONTAINER_HASH}_running")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    assert _get_uid(hass, ent.entity_id) == "dockhand_container_1_nginx_running"


def test_1_5_0_all_suffixes_migrated(hass: HomeAssistant):
    """All four entity suffixes (_state, _health, _running, _restart) are migrated."""
    entry = _make_entry(hass)
    suffixes = ["_state", "_health", "_running", "_restart"]
    entities = [
        _add_entity(hass, entry, f"dockhand_container_{CONTAINER_HASH}{sfx}")
        for sfx in suffixes
    ]
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    for ent, sfx in zip(entities, suffixes, strict=True):
        assert _get_uid(hass, ent.entity_id) == f"dockhand_container_1_nginx{sfx}"


def test_1_5_0_name_based_entity_is_no_op(hass: HomeAssistant):
    """Already-migrated dockhand_container_{env_id}_{name}_{suffix} is not touched."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, "dockhand_container_1_nginx_state")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    assert _get_uid(hass, ent.entity_id) == "dockhand_container_1_nginx_state"


def test_1_5_0_hash_not_in_fast_data_is_skipped(hass: HomeAssistant):
    """Container no longer running — left for stale cleanup, not migrated."""
    entry = _make_entry(hass)
    gone_hash = "c" * 64
    dev = _add_device(hass, entry, f"container_{gone_hash}")
    ent = _add_entity(hass, entry, f"dockhand_container_{gone_hash}_state")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    assert (DOMAIN, f"container_{gone_hash}") in _get_device_identifiers(hass, dev.id)
    assert _get_uid(hass, ent.entity_id) == f"dockhand_container_{gone_hash}_state"


def test_1_5_0_empty_fast_data_returns_early(hass: HomeAssistant):
    """Empty fast data short-circuits with no registry changes."""
    entry = _make_entry(hass)
    dev = _add_device(hass, entry, f"container_{CONTAINER_HASH}")
    ent = _add_entity(hass, entry, f"dockhand_container_{CONTAINER_HASH}_state")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, {})
    assert (DOMAIN, f"container_{CONTAINER_HASH}") in _get_device_identifiers(
        hass, dev.id
    )
    assert _get_uid(hass, ent.entity_id) == f"dockhand_container_{CONTAINER_HASH}_state"


def test_1_5_0_non_container_device_not_touched(hass: HomeAssistant):
    """Devices with non-container identifiers are ignored."""
    entry = _make_entry(hass)
    dev = _add_device(hass, entry, "env_1")
    migrate_1_5_0_container_device_identifiers(hass, ENTRY_ID, FAST_DATA_1_5)
    assert (DOMAIN, "env_1") in _get_device_identifiers(hass, dev.id)


# ---------------------------------------------------------------------------
# async_run_migrations — orchestration
# ---------------------------------------------------------------------------


def test_async_run_migrations_is_no_op_when_nothing_to_migrate(hass: HomeAssistant):
    """Running migrations on a clean install with no old-format entities is safe."""
    entry = _make_entry(hass)
    new_uid = f"{ENTRY_ID}_1_cpu"
    ent = _add_entity(hass, entry, new_uid)
    # Should not raise, and should not touch the already-new-format entity
    async_run_migrations(hass, entry, {})
    assert _get_uid(hass, ent.entity_id) == new_uid


def test_async_run_migrations_runs_all_in_order(hass: HomeAssistant):
    """All four migrations fire: 1.4.0 → 1.5.0 → 1.7.3 → 1.8.0, each a no-op
    here except 1.7.3."""
    entry = _make_entry(hass)
    # Seed an entity that would be touched by 1.7.3 if 1.4.0/1.5.0 leave it alone
    ent = _add_entity(hass, entry, "dockhand_env_1_cpu")
    async_run_migrations(hass, entry, {})
    # 1.7.3 should have fired and renamed it
    assert _get_uid(hass, ent.entity_id) == f"{ENTRY_ID}_1_cpu"


# ---------------------------------------------------------------------------
# migrate_1_8_0_container_stats_option
# ---------------------------------------------------------------------------


def test_container_stats_option_turned_on_when_stat_entity_enabled(
    hass: HomeAssistant,
):
    """A user who manually enabled even one of the 8 stat sensors before
    "Enable container stats" existed must not silently lose it — the
    option gets turned on automatically instead."""
    entry = _make_entry(hass)
    _add_entity(hass, entry, f"{ENTRY_ID}_1_container_web_cpu_percent")
    migrate_1_8_0_container_stats_option(hass, entry)
    assert entry.options.get("enable_container_stats") is True


def test_container_stats_option_untouched_when_nothing_enabled(hass: HomeAssistant):
    entry = _make_entry(hass)
    migrate_1_8_0_container_stats_option(hass, entry)
    assert "enable_container_stats" not in entry.options


# ---------------------------------------------------------------------------
# migrate_1_8_0_reenable_container_stats_entities
# ---------------------------------------------------------------------------
#
# Real, reported bug: a pre-1.8.0 container-stats entity can come back
# still disabled once a user turns "Enable container stats" on — not our
# own bug, but HA's own DeletedRegistryEntry mechanism, which restores a
# recreated entity's prior disabled_by to preserve deliberate user
# customizations across reloads/removals. It can't tell "the user
# disabled this" apart from "this was only ever disabled by the
# pre-1.8.0 default." The fix only touches entities disabled specifically
# via RegistryEntryDisabler.INTEGRATION (never a user's own choice,
# always a default) and leaves RegistryEntryDisabler.USER alone. A
# genuine one-time migration, not a per-load reconciliation — within
# 1.8.0's own architecture these entities are only ever created with
# enabled_default=True, so there's no ongoing source of fresh
# INTEGRATION-disabled entries to keep checking for.


def test_reenables_container_stats_entity_disabled_by_integration(hass: HomeAssistant):
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"{ENTRY_ID}_1_container_web_cpu_percent")
    ent_registry = er.async_get(hass)
    ent_registry.async_update_entity(
        ent.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
    )
    assert ent_registry.async_get(ent.entity_id).disabled_by is not None

    migrate_1_8_0_reenable_container_stats_entities(hass, entry)

    assert ent_registry.async_get(ent.entity_id).disabled_by is None


def test_does_not_reenable_container_stats_entity_disabled_by_user(
    hass: HomeAssistant,
):
    """The critical safety check: a user's own deliberate "I don't want
    this specific sensor" choice must survive this migration untouched —
    only the stale-default case gets cleared."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"{ENTRY_ID}_1_container_web_cpu_percent")
    ent_registry = er.async_get(hass)
    ent_registry.async_update_entity(
        ent.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )

    migrate_1_8_0_reenable_container_stats_entities(hass, entry)

    assert (
        ent_registry.async_get(ent.entity_id).disabled_by
        == er.RegistryEntryDisabler.USER
    )


def test_does_not_reenable_non_container_stats_entity(hass: HomeAssistant):
    """Only the 8 container-stats suffixes are in scope — an unrelated
    entity that happens to also be INTEGRATION-disabled (e.g. a niche
    sensor that's genuinely meant to stay off by default) must not get
    swept up by this."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"{ENTRY_ID}_1_disk_usage")
    ent_registry = er.async_get(hass)
    ent_registry.async_update_entity(
        ent.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
    )

    migrate_1_8_0_reenable_container_stats_entities(hass, entry)

    assert (
        ent_registry.async_get(ent.entity_id).disabled_by
        == er.RegistryEntryDisabler.INTEGRATION
    )


def test_container_stats_option_ignores_disabled_entities(hass: HomeAssistant):
    """A disabled-by-default stat entity that was never actually turned on
    shouldn't force the option on — only a genuinely enabled one should."""
    entry = _make_entry(hass)
    registry = er.async_get(hass)
    ent = _add_entity(hass, entry, f"{ENTRY_ID}_1_container_web_cpu_percent")
    registry.async_update_entity(
        ent.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
    )
    migrate_1_8_0_container_stats_option(hass, entry)
    assert "enable_container_stats" not in entry.options


def test_container_stats_option_respects_explicit_false(hass: HomeAssistant):
    """Once the option is explicitly set (even to False), this migration
    must never override that — it only acts when the key is entirely
    absent from options."""
    entry = _make_entry(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "enable_container_stats": False}
    )
    _add_entity(hass, entry, f"{ENTRY_ID}_1_container_web_cpu_percent")
    migrate_1_8_0_container_stats_option(hass, entry)
    assert entry.options.get("enable_container_stats") is False


def test_container_stats_option_ignores_unrelated_entity(hass: HomeAssistant):
    """A container's state sensor (not a stats sensor) enabled shouldn't
    trigger this — only the specific 8 stat-sensor suffixes count."""
    entry = _make_entry(hass)
    _add_entity(hass, entry, f"{ENTRY_ID}_1_container_web_state")
    migrate_1_8_0_container_stats_option(hass, entry)
    assert "enable_container_stats" not in entry.options


# ---------------------------------------------------------------------------
# migrate_1_8_0_remove_consolidated_disk_sensors
# ---------------------------------------------------------------------------
#
# Real, reported issue: "Containers disk usage" and "Build cache size" were
# consolidated into attributes on the single "Disk usage" sensor, but their
# entity classes being removed from sensor.py never removed their registry
# entries — they'd have orphaned on a future restart, forcing manual
# cleanup, rather than being cleanly gone the moment a user upgrades.


def test_removes_retired_containers_size_entity(hass: HomeAssistant):
    """Unique_id suffix verified against the actual released v1.7.4
    source — this sensor's unique_id ("_containers_size") didn't match
    its own translation_key ("containers_disk_usage"), which is exactly
    what caused the real, reported bug: assuming they matched (like
    build_cache_size's did) meant this specific entity was never
    actually cleaned up."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"{ENTRY_ID}_1_containers_size")
    migrate_1_8_0_remove_consolidated_disk_sensors(hass, entry)
    assert er.async_get(hass).async_get(ent.entity_id) is None


def test_removes_retired_build_cache_size_entity(hass: HomeAssistant):
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"{ENTRY_ID}_1_build_cache_size")
    migrate_1_8_0_remove_consolidated_disk_sensors(hass, entry)
    assert er.async_get(hass).async_get(ent.entity_id) is None


def test_does_not_remove_current_disk_usage_entity(hass: HomeAssistant):
    """The current, consolidated sensor must not be swept up by its
    retired predecessors' cleanup — different unique_id suffix entirely."""
    entry = _make_entry(hass)
    ent = _add_entity(hass, entry, f"{ENTRY_ID}_1_disk_usage")
    migrate_1_8_0_remove_consolidated_disk_sensors(hass, entry)
    assert er.async_get(hass).async_get(ent.entity_id) is not None
