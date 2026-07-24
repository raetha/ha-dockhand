"""
Tests for helpers.py — URL builders, DeviceInfo factories, and device registration.

Covers:
- _section_url / all section-specific URL helpers
- _container_device: freestanding vs Compose via_device, name format
- _stack_device: name format, via_device
- _env_device: name, connectionType as hw_version
- group device helpers: network, volume, image
- _sched_key / _sched_device
- _image_display_name: tagged, untagged, multi-tag, empty
- _container_has_healthcheck: all states
- _compose_project: with/without label, None container
- _ensure_env_devices: all device creation branches
- _ensure_hub_devices: schedules hub and per-schedule devices
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from custom_components.dockhand.helpers import (
    _all_envs,
    _compose_project,
    _container_device,
    _container_has_healthcheck,
    _container_has_pending_update,
    _container_url,
    _coordinator_env,
    _ensure_env_devices,
    _ensure_hub_devices,
    _env_device,
    _env_settings_url,
    _image_display_name,
    _image_group_device,
    _image_url,
    _is_update_disabled_by_label,
    _network_group_device,
    _network_url,
    _sched_device,
    _sched_key,
    _schedules_url,
    _section_url,
    _stack_device,
    _stack_has_system_container,
    _stack_url,
    _volume_group_device,
    _volume_url,
)

# ---------------------------------------------------------------------------
# _section_url and derived helpers
# ---------------------------------------------------------------------------


def test_section_url_appends_section():
    assert (
        _section_url("http://dh.test:3000", "containers")
        == "http://dh.test:3000/containers"
    )


def test_section_url_strips_trailing_slash():
    assert (
        _section_url("http://dh.test:3000/", "stacks") == "http://dh.test:3000/stacks"
    )


def test_section_url_empty_base_returns_none():
    assert _section_url("", "containers") is None


def test_container_url():
    assert _container_url("http://dh.test:3000") == "http://dh.test:3000/containers"


def test_stack_url():
    assert _stack_url("http://dh.test:3000") == "http://dh.test:3000/stacks"


def test_network_url():
    assert _network_url("http://dh.test:3000") == "http://dh.test:3000/networks"


def test_volume_url():
    assert _volume_url("http://dh.test:3000") == "http://dh.test:3000/volumes"


def test_image_url():
    assert _image_url("http://dh.test:3000") == "http://dh.test:3000/images"


def test_env_settings_url():
    assert (
        _env_settings_url("http://dh.test:3000", 5)
        == "http://dh.test:3000/settings?tab=environments&edit=5"
    )


def test_schedules_url():
    assert (
        _schedules_url("http://dh.test:3000")
        == "http://dh.test:3000/settings/schedules"
    )


def test_container_url_empty_base_returns_none():
    assert _container_url("") is None


# ---------------------------------------------------------------------------
# _env_device
# ---------------------------------------------------------------------------


def test_env_device_identifier():
    info = _env_device(1, "myenv", "http://dh.test:3000")
    assert ("dockhand", "env_1") in info["identifiers"]


def test_env_device_name():
    info = _env_device(1, "myenv", "http://dh.test:3000")
    assert info["name"] == "myenv"


def test_env_device_sets_hw_version_from_connection_type():
    info = _env_device(
        1, "myenv", "http://dh.test:3000", stats={"connectionType": "local"}
    )
    assert info["hw_version"] == "local"


def test_env_device_no_hw_version_when_stats_missing_connection():
    info = _env_device(1, "myenv", "http://dh.test:3000", stats={"cpu": 10})
    assert "hw_version" not in info


def test_env_device_no_hw_version_when_no_stats():
    info = _env_device(1, "myenv", "http://dh.test:3000")
    assert "hw_version" not in info


# ---------------------------------------------------------------------------
# _container_device
# ---------------------------------------------------------------------------


def test_container_device_identifier():
    info = _container_device("nginx", 1, "myenv", "http://dh.test:3000")
    assert ("dockhand", "container_1_nginx") in info["identifiers"]


def test_container_device_name_format():
    info = _container_device("nginx", 1, "myenv", "http://dh.test:3000")
    assert info["name"] == "myenv – Containers – nginx"


def test_container_device_via_containers_group_when_freestanding():
    info = _container_device(
        "nginx", 1, "myenv", "http://dh.test:3000", stack_name=None
    )
    assert info["via_device"] == ("dockhand", "env_1_Containers")


def test_container_device_via_stack_when_compose():
    info = _container_device(
        "web", 1, "myenv", "http://dh.test:3000", stack_name="myapp"
    )
    assert info["via_device"] == ("dockhand", "stack_1_myapp")


def test_container_device_configuration_url():
    info = _container_device("nginx", 1, "myenv", "http://dh.test:3000")
    assert info["configuration_url"] == "http://dh.test:3000/containers"


# ---------------------------------------------------------------------------
# _stack_device
# ---------------------------------------------------------------------------


def test_stack_device_identifier():
    info = _stack_device("myapp", 1, "myenv", "http://dh.test:3000")
    assert ("dockhand", "stack_1_myapp") in info["identifiers"]


def test_stack_device_name_format():
    info = _stack_device("myapp", 1, "myenv", "http://dh.test:3000")
    assert info["name"] == "myenv – Stacks – myapp"


def test_stack_device_via_stacks_group():
    info = _stack_device("myapp", 1, "myenv", "http://dh.test:3000")
    assert info["via_device"] == ("dockhand", "env_1_Stacks")


# ---------------------------------------------------------------------------
# Group device helpers
# ---------------------------------------------------------------------------


def test_network_group_device_identifier():
    info = _network_group_device(1, "myenv", "http://dh.test:3000")
    assert ("dockhand", "env_1_Networks") in info["identifiers"]


def test_network_group_device_via_env():
    info = _network_group_device(1, "myenv", "http://dh.test:3000")
    assert info["via_device"] == ("dockhand", "env_1")


def test_volume_group_device_identifier():
    info = _volume_group_device(1, "myenv", "http://dh.test:3000")
    assert ("dockhand", "env_1_Volumes") in info["identifiers"]


def test_image_group_device_identifier():
    info = _image_group_device(1, "myenv", "http://dh.test:3000")
    assert ("dockhand", "env_1_Images") in info["identifiers"]


# ---------------------------------------------------------------------------
# _sched_key / _sched_device
# ---------------------------------------------------------------------------


def test_sched_key_format():
    assert _sched_key({"id": 5, "type": "maintenance"}) == "5_maintenance"


def test_sched_device_identifier():
    info = _sched_device(5, "maintenance", "nightly", "http://dh.test:3000")
    assert ("dockhand", "schedule_5_maintenance") in info["identifiers"]


def test_sched_device_name_format():
    info = _sched_device(5, "maintenance", "nightly", "http://dh.test:3000")
    assert info["name"] == "Dockhand – Schedules – nightly"


def test_sched_device_via_schedules_hub():
    info = _sched_device(5, "maintenance", "nightly", "http://dh.test:3000")
    assert info["via_device"] == ("dockhand", "schedules_hub")


# ---------------------------------------------------------------------------
# _image_display_name
# ---------------------------------------------------------------------------


def test_image_display_name_prefers_first_repo_tag():
    assert (
        _image_display_name({"repoTags": ["nginx:latest", "nginx:1.25"]})
        == "nginx:latest"
    )


def test_image_display_name_skips_none_tag():
    result = _image_display_name(
        {"repoTags": ["<none>:<none>"], "id": "sha256:abc123def456789"}
    )
    assert result == "abc123def456"


def test_image_display_name_falls_back_to_short_id():
    result = _image_display_name({"repoTags": [], "id": "sha256:deadbeef1234567890"})
    assert result == "deadbeef1234"


def test_image_display_name_handles_empty_id():
    result = _image_display_name({"repoTags": [], "id": ""})
    assert result == "unknown"


def test_image_display_name_handles_no_fields():
    result = _image_display_name({})
    assert result == "unknown"


def test_image_display_name_id_without_colon():
    result = _image_display_name({"repoTags": [], "id": "deadbeef1234567890"})
    assert result == "deadbeef1234"


# ---------------------------------------------------------------------------
# _container_has_healthcheck
# ---------------------------------------------------------------------------


def test_has_healthcheck_healthy():
    assert _container_has_healthcheck({"health": "healthy"}) is True


def test_has_healthcheck_unhealthy():
    assert _container_has_healthcheck({"health": "unhealthy"}) is True


def test_has_healthcheck_starting():
    assert _container_has_healthcheck({"health": "starting"}) is True


def test_no_healthcheck_when_none():
    assert _container_has_healthcheck({"health": "none"}) is False


def test_no_healthcheck_when_unknown():
    assert _container_has_healthcheck({"health": "unknown"}) is False


def test_no_healthcheck_when_null():
    assert _container_has_healthcheck({"health": None}) is False


def test_no_healthcheck_when_missing():
    assert _container_has_healthcheck({}) is False


# ---------------------------------------------------------------------------
# _compose_project
# ---------------------------------------------------------------------------


def test_compose_project_returns_project_name():
    c = {"labels": {"com.docker.compose.project": "myapp"}}
    assert _compose_project(c) == "myapp"


def test_compose_project_none_for_freestanding():
    assert _compose_project({"labels": {}}) is None


def test_compose_project_none_for_no_labels():
    assert _compose_project({"name": "nginx"}) is None


def test_compose_project_none_for_none_container():
    assert _compose_project(None) is None


# ---------------------------------------------------------------------------
# _extract_runtime_config
# ---------------------------------------------------------------------------


def test_extract_runtime_config_normal_values():
    from custom_components.dockhand.helpers import _extract_runtime_config

    inspect_data = {
        "HostConfig": {
            "Memory": 536870912,
            "NanoCpus": 1500000000,
            "PidsLimit": 100,
            "RestartPolicy": {"Name": "unless-stopped"},
        }
    }
    result = _extract_runtime_config(inspect_data)
    assert result == {
        "memory": 536870912,
        "nano_cpus": 1500000000,
        "pids_limit": 100,
        "restart_policy": "unless-stopped",
    }


def test_extract_runtime_config_unlimited_defaults():
    """Memory/NanoCpus 0 = unlimited (Docker's own convention); PidsLimit
    missing entirely also means unlimited, represented as -1 to match
    Docker's own sentinel for this field; RestartPolicy missing means "no"."""
    from custom_components.dockhand.helpers import _extract_runtime_config

    result = _extract_runtime_config({"HostConfig": {}})
    assert result == {
        "memory": 0,
        "nano_cpus": 0,
        "pids_limit": -1,
        "restart_policy": "no",
    }


def test_extract_runtime_config_explicit_pids_limit_zero_preserved():
    """PidsLimit=0 is an explicit value from Docker, distinct from the key
    being absent — our -1 "unlimited" default only kicks in when the key
    is truly missing, so an explicit 0 is passed through as-is."""
    from custom_components.dockhand.helpers import _extract_runtime_config

    result = _extract_runtime_config({"HostConfig": {"PidsLimit": 0}})
    assert result["pids_limit"] == 0


def test_extract_runtime_config_missing_host_config():
    from custom_components.dockhand.helpers import _extract_runtime_config

    assert _extract_runtime_config({}) == {
        "memory": 0,
        "nano_cpus": 0,
        "pids_limit": -1,
        "restart_policy": "no",
    }


# ---------------------------------------------------------------------------
# _ensure_env_devices
# ---------------------------------------------------------------------------


def _make_entry(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="dockhand", data={}, title="test")
    entry.add_to_hass(hass)
    return entry


def _device_ids(hass, entry) -> set[str]:
    from homeassistant.helpers import device_registry as dr

    reg = dr.async_get(hass)
    devs = reg.devices.get_devices_for_config_entry_id(entry.entry_id)
    return {next(iter(d.identifiers))[1] for d in devs}


def _device_by_id_suffix(hass, entry, id_suffix: str):
    from homeassistant.helpers import device_registry as dr

    reg = dr.async_get(hass)
    devs = reg.devices.get_devices_for_config_entry_id(entry.entry_id)
    for d in devs:
        if next(iter(d.identifiers))[1] == id_suffix:
            return d
    return None


def test_ensure_env_devices_stack_model_reflects_source_type(hass):
    """Regression test: _ensure_env_devices() is a SEPARATE device-
    registration path from _stack_device()/BaseFastStackSensor's
    device_info — it runs unconditionally on every coordinator update,
    calling registry.async_get_or_create() directly, rather than going
    through an entity at all. These two paths drifted out of sync once
    already (this one kept a hardcoded generic "Stack" after
    _stack_device() was updated to use sourceType), silently overwriting
    the correct model within about one poll cycle of every reload — a
    real bug shipped before being caught. This locks in that both stay
    in sync."""
    entry = _make_entry(hass)
    stacks = [{"name": "myapp", "sourceType": "git"}]
    _ensure_env_devices(
        hass, entry.entry_id, "http://dh.test:3000", 1, "myenv", stacks=stacks
    )
    device = _device_by_id_suffix(hass, entry, "stack_1_myapp")
    assert device is not None
    assert device.model == "Git Stack"


def test_ensure_env_devices_stack_model_internal(hass):
    entry = _make_entry(hass)
    stacks = [{"name": "myapp", "sourceType": "internal"}]
    _ensure_env_devices(
        hass, entry.entry_id, "http://dh.test:3000", 1, "myenv", stacks=stacks
    )
    device = _device_by_id_suffix(hass, entry, "stack_1_myapp")
    assert device.model == "Internal Stack"


def test_ensure_env_devices_stack_model_untracked_when_source_type_absent(hass):
    """No sourceType at all (no stackSources DB record) — matches
    Dockhand's own frontend default of 'external', not a generic
    fallback."""
    entry = _make_entry(hass)
    stacks = [{"name": "myapp"}]
    _ensure_env_devices(
        hass, entry.entry_id, "http://dh.test:3000", 1, "myenv", stacks=stacks
    )
    device = _device_by_id_suffix(hass, entry, "stack_1_myapp")
    assert device.model == "Untracked Stack"


def test_ensure_env_devices_stack_model_survives_repeated_calls(hass):
    """The actual shape of the bug: _ensure_env_devices() is called on
    every coordinator update (fast AND slow), not just once at entity
    add time. A second call with the same (correct) data must not
    regress the model — this is what would have caught the real bug,
    since the hardcoded "Stack" value would have shown up on the very
    next call after the first one happened to look right by coincidence
    of call order."""
    entry = _make_entry(hass)
    stacks = [{"name": "myapp", "sourceType": "git"}]
    for _ in range(3):
        _ensure_env_devices(
            hass, entry.entry_id, "http://dh.test:3000", 1, "myenv", stacks=stacks
        )
    device = _device_by_id_suffix(hass, entry, "stack_1_myapp")
    assert device.model == "Git Stack"


def test_ensure_env_devices_creates_env_hub(hass):
    entry = _make_entry(hass)
    _ensure_env_devices(hass, entry.entry_id, "http://dh.test:3000", 1, "myenv")
    assert "env_1" in _device_ids(hass, entry)


def test_ensure_env_devices_creates_containers_group_for_freestanding(hass):
    entry = _make_entry(hass)
    containers = [{"name": "nginx", "labels": {}}]
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        containers=containers,
    )
    assert "env_1_Containers" in _device_ids(hass, entry)


def test_ensure_env_devices_skips_containers_group_for_compose_only(hass):
    entry = _make_entry(hass)
    containers = [{"name": "web", "labels": {"com.docker.compose.project": "myapp"}}]
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        containers=containers,
    )
    assert "env_1_Containers" not in _device_ids(hass, entry)


def test_ensure_env_devices_creates_stacks_group_when_stacks(hass):
    entry = _make_entry(hass)
    stacks = [{"name": "myapp"}]
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        stacks=stacks,
    )
    ids = _device_ids(hass, entry)
    assert "env_1_Stacks" in ids
    assert "stack_1_myapp" in ids


def test_ensure_env_devices_creates_individual_stack_device(hass):
    entry = _make_entry(hass)
    stacks = [{"name": "alpha"}, {"name": "beta"}]
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        stacks=stacks,
    )
    ids = _device_ids(hass, entry)
    assert "stack_1_alpha" in ids
    assert "stack_1_beta" in ids


def test_ensure_env_devices_skips_individual_stack_device_with_empty_name(hass):
    """Stacks group is created for any non-empty stacks list, but the per-stack
    device is skipped when the stack name is empty."""
    entry = _make_entry(hass)
    stacks = [{"name": ""}]
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        stacks=stacks,
    )
    ids = _device_ids(hass, entry)
    # Group created (stacks list is truthy), but no individual device
    assert "env_1_Stacks" in ids
    assert "stack_1_" not in str(ids)


def test_ensure_env_devices_creates_networks_group_when_enabled(hass):
    entry = _make_entry(hass)
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        networks=[{"id": "n1"}],
        enable_networks=True,
    )
    assert "env_1_Networks" in _device_ids(hass, entry)


def test_ensure_env_devices_skips_networks_group_when_disabled(hass):
    entry = _make_entry(hass)
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        networks=[{"id": "n1"}],
        enable_networks=False,
    )
    assert "env_1_Networks" not in _device_ids(hass, entry)


def test_ensure_env_devices_skips_networks_group_when_empty_list(hass):
    entry = _make_entry(hass)
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        networks=[],
        enable_networks=True,
    )
    assert "env_1_Networks" not in _device_ids(hass, entry)


def test_ensure_env_devices_creates_images_group_when_enabled(hass):
    entry = _make_entry(hass)
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        images=[{"id": "sha256:abc"}],
        enable_images=True,
    )
    assert "env_1_Images" in _device_ids(hass, entry)


def test_ensure_env_devices_creates_volumes_group_when_enabled(hass):
    entry = _make_entry(hass)
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        volumes=[{"Name": "mydata"}],
        enable_volumes=True,
    )
    assert "env_1_Volumes" in _device_ids(hass, entry)


def test_ensure_env_devices_is_idempotent(hass):
    entry = _make_entry(hass)
    stacks = [{"name": "app"}]
    for _ in range(3):
        _ensure_env_devices(
            hass,
            entry.entry_id,
            "http://dh.test:3000",
            1,
            "myenv",
            stacks=stacks,
        )
    from homeassistant.helpers import device_registry as dr

    reg = dr.async_get(hass)
    devs = reg.devices.get_devices_for_config_entry_id(entry.entry_id)
    ids = [next(iter(d.identifiers))[1] for d in devs]
    assert len(ids) == len(set(ids))  # no duplicates


# ---------------------------------------------------------------------------
# _ensure_hub_devices
# ---------------------------------------------------------------------------


def test_ensure_hub_devices_creates_schedules_hub(hass):
    entry = _make_entry(hass)
    _ensure_hub_devices(hass, entry.entry_id, "http://dh.test:3000", schedules=[])
    assert "schedules_hub" in _device_ids(hass, entry)


def test_ensure_hub_devices_creates_per_schedule_device(hass):
    entry = _make_entry(hass)
    schedules = [{"id": 5, "type": "maintenance", "name": "nightly"}]
    _ensure_hub_devices(
        hass, entry.entry_id, "http://dh.test:3000", schedules=schedules
    )
    assert "schedule_5_maintenance" in _device_ids(hass, entry)


def test_ensure_hub_devices_creates_multiple_schedules(hass):
    entry = _make_entry(hass)
    schedules = [
        {"id": 1, "type": "backup", "name": "nightly-backup"},
        {"id": 2, "type": "maintenance", "name": "weekly-clean"},
    ]
    _ensure_hub_devices(
        hass, entry.entry_id, "http://dh.test:3000", schedules=schedules
    )
    ids = _device_ids(hass, entry)
    assert "schedule_1_backup" in ids
    assert "schedule_2_maintenance" in ids


def test_ensure_hub_devices_skips_schedule_with_no_id(hass):
    entry = _make_entry(hass)
    schedules = [{"id": None, "type": "maintenance", "name": "bad"}]
    _ensure_hub_devices(
        hass, entry.entry_id, "http://dh.test:3000", schedules=schedules
    )
    ids = _device_ids(hass, entry)
    # Only hub itself, no schedule device
    assert ids == {"schedules_hub"}


def test_ensure_hub_devices_is_idempotent(hass):
    entry = _make_entry(hass)
    schedules = [{"id": 5, "type": "maintenance", "name": "nightly"}]
    for _ in range(3):
        _ensure_hub_devices(
            hass, entry.entry_id, "http://dh.test:3000", schedules=schedules
        )
    from homeassistant.helpers import device_registry as dr

    reg = dr.async_get(hass)
    devs = reg.devices.get_devices_for_config_entry_id(entry.entry_id)
    ids = [next(iter(d.identifiers))[1] for d in devs]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# _network_group_device / _volume_group_device / _image_group_device
# — via_device and configuration_url (identifier already tested above)
# ---------------------------------------------------------------------------


def test_network_group_device_configuration_url():
    info = _network_group_device(1, "myenv", "http://dh.test:3000")
    assert info["configuration_url"] == "http://dh.test:3000/networks"


def test_volume_group_device_via_env():
    info = _volume_group_device(1, "myenv", "http://dh.test:3000")
    assert info["via_device"] == ("dockhand", "env_1")


def test_volume_group_device_configuration_url():
    info = _volume_group_device(1, "myenv", "http://dh.test:3000")
    assert info["configuration_url"] == "http://dh.test:3000/volumes"


def test_image_group_device_via_env():
    info = _image_group_device(1, "myenv", "http://dh.test:3000")
    assert info["via_device"] == ("dockhand", "env_1")


def test_image_group_device_configuration_url():
    info = _image_group_device(1, "myenv", "http://dh.test:3000")
    assert info["configuration_url"] == "http://dh.test:3000/images"


def test_image_group_device_name():
    info = _image_group_device(2, "prodenv", "http://dh.test:3000")
    assert info["name"] == "prodenv \u2013 Images"


def test_volume_group_device_name():
    info = _volume_group_device(2, "prodenv", "http://dh.test:3000")
    assert info["name"] == "prodenv \u2013 Volumes"


def test_network_group_device_name():
    info = _network_group_device(2, "prodenv", "http://dh.test:3000")
    assert info["name"] == "prodenv \u2013 Networks"


# ---------------------------------------------------------------------------
# _ensure_env_devices — individual container device creation
# ---------------------------------------------------------------------------


def test_ensure_env_devices_no_containers_group_when_all_compose_managed(hass):
    """Containers group is not created when every container is Compose-managed."""
    from custom_components.dockhand.helpers import _ensure_env_devices
    from homeassistant.helpers import device_registry as dr

    entry = _make_entry(hass)
    # compose.project label → compose-managed, not freestanding
    containers = [
        {
            "name": "web",
            "id": "abc",
            "state": "running",
            "labels": {"com.docker.compose.project": "myapp"},
        }
    ]
    _ensure_env_devices(
        hass,
        entry.entry_id,
        "http://dh.test:3000",
        1,
        "myenv",
        containers=containers,
    )
    reg = dr.async_get(hass)
    devs = reg.devices.get_devices_for_config_entry_id(entry.entry_id)
    ids = {next(iter(d.identifiers))[1] for d in devs}
    assert "env_1_Containers" not in ids


# ---------------------------------------------------------------------------
# _stack_has_system_container
# ---------------------------------------------------------------------------


def test_stack_has_system_container_true_when_member_is_system():
    """stack['containers'] is a list of container IDs, not names —
    confirmed from Dockhand's own source (stacks.ts populates it from a
    Set matched against container.id). Using names here was a real bug
    that shipped: this check silently never matched anything, for any
    stack, ever, since IDs and names never overlap in practice."""
    stack = {"name": "infra", "containers": ["id-dockhand", "id-web"]}
    all_containers = [
        {"id": "id-dockhand", "name": "dockhand", "systemContainer": "dockhand"},
        {"id": "id-web", "name": "web", "systemContainer": None},
    ]
    assert _stack_has_system_container(stack, all_containers) is True


def test_stack_has_system_container_false_when_no_member_is_system():
    stack = {"name": "myapp", "containers": ["id-web", "id-db"]}
    all_containers = [
        {"id": "id-web", "name": "web", "systemContainer": None},
        {"id": "id-db", "name": "db", "systemContainer": None},
    ]
    assert _stack_has_system_container(stack, all_containers) is False


def test_stack_has_system_container_false_for_empty_container_list():
    stack = {"name": "myapp", "containers": []}
    all_containers = [
        {"id": "id-dockhand", "name": "dockhand", "systemContainer": "dockhand"}
    ]
    assert _stack_has_system_container(stack, all_containers) is False


def test_stack_has_system_container_false_for_none_stack():
    assert _stack_has_system_container(None, []) is False


def test_stack_has_system_container_false_when_ids_dont_match():
    """The stack's container IDs must actually match an entry in the
    full container list — an ID that doesn't appear there at all (e.g.
    a stale ID after recreation) is not treated as a match."""
    stack = {"name": "myapp", "containers": ["id-ghost"]}
    all_containers = [
        {"id": "id-dockhand", "name": "dockhand", "systemContainer": "dockhand"}
    ]
    assert _stack_has_system_container(stack, all_containers) is False


def test_stack_has_system_container_ignores_name_collision_with_id():
    """Regression guard for the exact bug: a container whose NAME
    happens to equal another container's ID string must not produce a
    false match — only real id-to-id equality counts."""
    stack = {"name": "myapp", "containers": ["dockhand"]}  # looks like a name!
    all_containers = [
        {"id": "id-dockhand", "name": "dockhand", "systemContainer": "dockhand"}
    ]
    assert _stack_has_system_container(stack, all_containers) is False


# ---------------------------------------------------------------------------
# _container_has_pending_update
# ---------------------------------------------------------------------------


def test_container_has_pending_update_true_via_tier1_only():
    container = {"id": "id-web"}
    assert _container_has_pending_update(container, {"id-web"}, None) is True


def test_container_has_pending_update_true_via_tier2_only():
    """Tier 2's hasUpdate alone is a valid reason, even with an empty
    Tier 1 pending set — Tier 2 can catch real digest-level updates
    Dockhand's own cheap scheduled check hasn't (yet)."""
    container = {"id": "id-web"}
    update_env_data = {"id-web": {"containerName": "web", "hasUpdate": True}}
    assert _container_has_pending_update(container, set(), update_env_data) is True


def test_container_has_pending_update_false_when_neither_tier_says_so():
    container = {"id": "id-web"}
    update_env_data = {"id-web": {"containerName": "web", "hasUpdate": False}}
    assert _container_has_pending_update(container, set(), update_env_data) is False


def test_container_has_pending_update_false_for_no_container_id():
    assert _container_has_pending_update({}, {"id-web"}, None) is False


def test_container_has_pending_update_ignores_stale_tier2_entry():
    """The core staleness fix: a Tier 2 entry keyed under an id the
    container no longer has (left over from before it was recreated by
    an update) must not count — looking it up by the container's
    *current* id makes a stale entry simply invisible, rather than
    needing to be explicitly detected and discarded. Real bug: this
    used to be a name-based scan, which kept a resolved update looking
    pending for up to Tier 2's full poll interval."""
    container = {"id": "id-web-new"}  # recreated since Tier 2 last ran
    update_env_data = {"id-web-old": {"containerName": "web", "hasUpdate": True}}
    assert _container_has_pending_update(container, set(), update_env_data) is False


def test_container_has_pending_update_tier1_still_wins_over_stale_tier2():
    """Even when Tier 2's cached entry is stale/invisible for the current
    id, Tier 1's own live signal must still be honored on its own."""
    container = {"id": "id-web-new"}
    update_env_data = {"id-web-old": {"containerName": "web", "hasUpdate": True}}
    assert (
        _container_has_pending_update(container, {"id-web-new"}, update_env_data)
        is True
    )


def test_container_has_pending_update_handles_none_update_env_data():
    """update_env_data is None when Tier 2 (update_coordinator) isn't
    configured at all — must behave exactly like Tier 1 alone."""
    container = {"id": "id-web"}
    assert _container_has_pending_update(container, {"id-web"}, None) is True
    assert _container_has_pending_update(container, set(), None) is False


# ---------------------------------------------------------------------------
# _coordinator_env / _all_envs — null-safety for Dockhand sending an
# explicit null, and a single accessor shared by all three coordinators
# ---------------------------------------------------------------------------
#
# The actual bug (github.com/raetha/ha-dockhand/issues/20, and a live crash
# reported in this same session): `dict.get(key, default)` only supplies
# `default` when `key` is *absent*. If Dockhand's API sends that key present
# with an explicit `null` — which it does for optional/runtime data, not
# just when a value is omitted — `.get(key, {})` returns that `None`, and
# the next chained `.get()`/`.items()`/`.values()` call crashes with
# `AttributeError: 'NoneType' object has no attribute '...'`. These helpers
# use `or` instead, which correctly substitutes the default for both cases.
#
# _coordinator_env and _all_envs were originally two pairs of near-identical
# functions (_fast_env/_slow_env for the single-environment case) — merged
# once the fast, slow, and update coordinators all ended up sharing the same
# {"environments": {env_id: {...}}} top-level shape, since there was nothing
# left for two separate functions to document that a shared one couldn't.


def test_coordinator_env_missing_key_entirely():
    assert _coordinator_env({}, 1) == {}
    assert _coordinator_env(None, 1) == {}


def test_coordinator_env_environments_key_explicitly_null():
    """The exact shape of the reported bug: "environments" present but
    null, not absent."""
    assert _coordinator_env({"environments": None}, 1) == {}


def test_coordinator_env_specific_env_id_explicitly_null():
    """The exact shape of the live crash this session: an environment's
    slice of coordinator data present but null."""
    assert _coordinator_env({"environments": {1: None, 2: {"host": {}}}}, 1) == {}


def test_coordinator_env_returns_real_data_when_present():
    data = {"environments": {1: {"host": {"cpus": 8}}}}
    assert _coordinator_env(data, 1) == {"host": {"cpus": 8}}


def test_all_envs_missing_key_entirely():
    assert _all_envs({}) == {}
    assert _all_envs(None) == {}


def test_all_envs_environments_key_explicitly_null():
    assert _all_envs({"environments": None}) == {}


def test_all_envs_returns_real_data_when_present():
    data = {"environments": {1: {"host": {}}, 2: {"host": {}}}}
    assert _all_envs(data) == {1: {"host": {}}, 2: {"host": {}}}
