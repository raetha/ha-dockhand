"""
Tests for migration.py.

Covers migrate_1_7_3_entry_scoped_unique_ids: correct rename of every old
dockhand_* unique_id pattern, no-op on already-migrated IDs, and no-op on
unrelated entities registered under the same config entry.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.migration import migrate_1_7_3_entry_scoped_unique_ids

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


def _add_entity(hass: HomeAssistant, entry: MockConfigEntry, unique_id: str) -> er.RegistryEntry:
    registry = er.async_get(hass)
    return registry.async_get_or_create(
        "sensor",
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
    entry = _make_entry(hass)

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
