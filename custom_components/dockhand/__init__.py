import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType

from .api import DockhandClient
from .const import (
    _LEGACY_CONF_PASSWORD,
    _LEGACY_CONF_SESSION_COOKIE,
    _LEGACY_CONF_USERNAME,
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_UPDATES,
    CONF_ENABLE_VOLUMES,
    CONF_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
    DockhandUpdateCoordinator,
)
from .helpers import (
    _container_url,
    _env_url,
    _image_url,
    _network_url,
    _sched_key,
    _schedules_url,
    _stack_url,
    _volume_url,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DockhandData:
    """Runtime data stored on the config entry."""

    client: DockhandClient
    fast_coordinator: DockhandFastCoordinator
    slow_coordinator: DockhandSlowCoordinator
    update_coordinator: DockhandUpdateCoordinator | None


# Typed config entry alias — used throughout all platform setup functions
# so that entry.runtime_data is typed as DockhandData without casting.
type DockhandConfigEntry = ConfigEntry[DockhandData]


async def async_setup_entry(hass: HomeAssistant, entry: DockhandConfigEntry) -> bool:
    """Set up Dockhand from a config entry."""
    verify_ssl = bool(entry.data.get(CONF_VERIFY_SSL, True))
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = DockhandClient(session, entry.data)

    # Detect legacy config entries (pre-1.2.0) that used session-cookie auth.
    has_legacy = entry.data.get(_LEGACY_CONF_USERNAME) or entry.data.get(
        _LEGACY_CONF_SESSION_COOKIE
    )
    if has_legacy:
        if entry.data.get(CONF_API_TOKEN):
            # Reauth flow already stored a token — strip the legacy keys so
            # this migration path is only triggered once.
            clean = {
                k: v
                for k, v in entry.data.items()
                if k
                not in (
                    _LEGACY_CONF_USERNAME,
                    _LEGACY_CONF_PASSWORD,
                    _LEGACY_CONF_SESSION_COOKIE,
                )
            }
            hass.config_entries.async_update_entry(entry, data=clean)
        else:
            # No token yet — prompt the user to provide one via reauth.
            raise ConfigEntryAuthFailed(
                "This Dockhand entry uses the old session-cookie auth, "
                "which is no longer supported. Use Reconfigure to provide "
                "an API token (Profile → API tokens in Dockhand)."
            )

    config = {**entry.data, **entry.options}

    fast_coordinator = DockhandFastCoordinator(hass, client, config, entry=entry)
    slow_coordinator = DockhandSlowCoordinator(hass, client, config, entry=entry)

    # Update coordinator is optional — only created when the feature is enabled.
    update_coordinator: DockhandUpdateCoordinator | None = None
    if config.get(CONF_ENABLE_UPDATES):
        update_coordinator = DockhandUpdateCoordinator(
            hass, client, fast_coordinator, config, entry=entry
        )

    try:
        # Fast coordinator must succeed — it provides the environment list that
        # all entity platforms depend on.
        await fast_coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Could not fetch initial Dockhand data: {err}"
        ) from err

    try:
        # Slow coordinator failure is non-fatal at startup — optional entities
        # will show as unavailable until the first successful poll.
        await slow_coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.warning(
            "Dockhand: initial slow data fetch failed, will retry at next poll: %s",
            err,
        )

    if update_coordinator is not None:
        try:
            # Update coordinator failure is non-fatal — entities will show as
            # unavailable until the first successful poll (up to 24h by default).
            await update_coordinator.async_config_entry_first_refresh()
        except Exception as err:
            _LOGGER.warning(
                "Dockhand: initial update check failed, will retry at next poll: %s",
                err,
            )

    entry.runtime_data = DockhandData(
        client=client,
        fast_coordinator=fast_coordinator,
        slow_coordinator=slow_coordinator,
        update_coordinator=update_coordinator,
    )

    # Pre-register group devices so they appear with correct names before
    # entity platforms load.
    base_url = entry.data.get(CONF_API_URL, "")
    _register_devices(hass, entry, fast_coordinator, slow_coordinator, config, base_url)

    # Migrate update entity unique_ids from the 1.4.0 container-ID-based scheme
    # to the 1.4.1 name-based scheme.
    _migrate_update_entity_unique_ids(hass, entry, fast_coordinator)

    # Migrate container device identifiers from the 1.4.x format (no env_id)
    # to the 1.5.0 format (env_id prefix for precise per-env cleanup).
    _migrate_container_device_identifiers(hass, entry, fast_coordinator)

    # Run cleanup immediately on setup so that stale registry entries from a
    # previous install/reload are removed before platforms add new entities.
    # Without this, entities pruned between reloads persist in the registry
    # and cause _2/_3/etc suffixes when new entities with the same name register.
    _cleanup_stale_registry(hass, entry)

    # All three coordinators share the same cleanup listener — guard logic is
    # handled inside _cleanup_stale_registry.
    entry.async_on_unload(
        fast_coordinator.async_add_listener(
            lambda: _cleanup_stale_registry(hass, entry)
        )
    )
    entry.async_on_unload(
        slow_coordinator.async_add_listener(
            lambda: _cleanup_stale_registry(hass, entry)
        )
    )
    if update_coordinator is not None:
        entry.async_on_unload(
            update_coordinator.async_add_listener(
                lambda: _cleanup_stale_registry(hass, entry)
            )
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


def _migrate_update_entity_unique_ids(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    fast_coordinator: DockhandFastCoordinator,
) -> None:
    """Migrate update entity unique_ids from 1.4.0 format to 1.4.1 format.

    1.4.0 used: dockhand_update_{container_id}  (64-char Docker hash — unstable)
    1.4.1 uses: dockhand_update_{env_id}_{container_name}  (stable across rebuilds)

    Builds a reverse map of container_id → (env_id, container_name) from the
    fast coordinator data, then rewrites any matching entity unique_ids in the
    entity registry. Runs once at setup time; is a no-op after the first run
    since old-format unique_ids will no longer exist.
    """
    fast_data = fast_coordinator.data or {}

    # Build reverse map: container_id → (env_id, name)
    id_to_name: dict[str, tuple[int, str]] = {}
    for env_id, env_data in fast_data.items():
        for c in env_data.get("containers") or []:
            cid = c.get("id", "")
            name = c.get("name", "")
            if cid and name:
                id_to_name[cid] = (env_id, name)

    if not id_to_name:
        return

    ent_registry = er.async_get(hass)
    migrated = 0
    for entity_entry in er.async_entries_for_config_entry(ent_registry, entry.entry_id):
        uid = entity_entry.unique_id or ""
        if not uid.startswith("dockhand_update_"):
            continue
        # Old format: "dockhand_update_" + 64-char hex container ID.
        # New format: "dockhand_update_" + digits + "_" + name.
        suffix = uid[len("dockhand_update_") :]
        # If suffix contains no underscore it's a plain container ID (old format).
        # If it starts with digits followed by underscore, it's already new format.
        if "_" in suffix:
            continue  # Already new format — skip.
        container_id = suffix
        if container_id not in id_to_name:
            # Container no longer running — will be cleaned up by stale registry pass.
            continue
        env_id, name = id_to_name[container_id]
        new_uid = f"dockhand_update_{env_id}_{name}"
        ent_registry.async_update_entity(entity_entry.entity_id, new_unique_id=new_uid)
        _LOGGER.debug(
            "Dockhand: migrated update entity unique_id %s → %s", uid, new_uid
        )
        migrated += 1

    if migrated:
        _LOGGER.info(
            "Dockhand: migrated %d update entity unique_id(s) to name-based scheme",
            migrated,
        )


def _migrate_container_device_identifiers(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    fast_coordinator: DockhandFastCoordinator,
) -> None:
    """Migrate container device identifiers from 1.4.x to 1.5.0 format.

    1.4.x used: container_{docker_hash}  (no env_id — conservative cleanup)
    1.5.0 uses: container_{env_id}_{docker_hash}  (precise per-env cleanup)

    Builds a map of container_id → env_id from the fast coordinator data,
    then updates any old-format device identifiers in the device registry.
    Runs once at setup time; is a no-op after the first run since old-format
    identifiers will no longer exist.
    """
    fast_data = fast_coordinator.data or {}

    # Build reverse map: container_id → env_id
    id_to_env: dict[str, int] = {}
    for env_id, env_data in fast_data.items():
        for c in env_data.get("containers") or []:
            cid = c.get("id", "")
            if cid:
                id_to_env[cid] = env_id

    if not id_to_env:
        return

    dev_registry = dr.async_get(hass)
    migrated = 0
    for device in dr.async_entries_for_config_entry(dev_registry, entry.entry_id):
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                continue
            if not identifier.startswith("container_"):
                continue
            suffix = identifier[len("container_") :]
            # Old format: no underscore in suffix (plain docker hash).
            # New format: starts with digits followed by underscore (env_id prefix).
            if "_" in suffix:
                continue  # Already new format.
            container_id = suffix
            if container_id not in id_to_env:
                continue  # Container gone — cleanup will handle it.
            env_id = id_to_env[container_id]
            new_identifier = f"container_{env_id}_{container_id}"
            new_identifiers = {
                (d, new_identifier if d == DOMAIN and i == identifier else i)
                for d, i in device.identifiers
            }
            dev_registry.async_update_device(device.id, new_identifiers=new_identifiers)
            _LOGGER.debug(
                "Dockhand: migrated container device %s → %s",
                identifier,
                new_identifier,
            )
            migrated += 1
            break  # Only one identifier per device.

    if migrated:
        _LOGGER.info(
            "Dockhand: migrated %d container device identifier(s) to env-scoped scheme",
            migrated,
        )


def _register_devices(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    fast_coordinator: DockhandFastCoordinator,
    slow_coordinator: DockhandSlowCoordinator,
    config: dict,
    base_url: str = "",
) -> None:
    """Pre-register environment hub devices and type-group child devices.

    Runs after both coordinators have completed their first refresh so that
    Networks/Images/Volumes group devices are only created when that feature is
    enabled AND the slow coordinator has confirmed the resources actually exist.
    The Containers group is still governed by fast data (compose vs freestanding).
    """
    registry = dr.async_get(hass)
    enable_schedules = bool(config.get(CONF_ENABLE_SCHEDULES, False))
    enable_images = bool(config.get(CONF_ENABLE_IMAGES, False))
    enable_volumes = bool(config.get(CONF_ENABLE_VOLUMES, False))
    enable_networks = bool(config.get(CONF_ENABLE_NETWORKS, False))

    for env_id, env_data in (fast_coordinator.data or {}).items():
        stats = env_data.get("stats") or {}
        env_name = stats.get("name", f"Environment {env_id}")

        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"env_{env_id}")},
            name=env_name,
            manufacturer="Dockhand",
            model="Environment",
            configuration_url=_env_url(base_url),
        )

        # Only create the Containers group if there are freestanding containers
        # (containers not managed by Compose). Compose containers are parented
        # directly to their Stack device, so the group would otherwise be empty.
        freestanding = [
            c
            for c in (env_data.get("containers") or [])
            if not (c.get("labels") or {}).get("com.docker.compose.project")
        ]
        if freestanding:
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"env_{env_id}_Containers")},
                name=f"{env_name} – Containers",
                manufacturer="Dockhand",
                model="Environment",
                configuration_url=_container_url(base_url),
                via_device=(DOMAIN, f"env_{env_id}"),
                entry_type=DeviceEntryType.SERVICE,
            )

        stacks = env_data.get("stacks") or []
        if stacks:
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"env_{env_id}_Stacks")},
                name=f"{env_name} – Stacks",
                manufacturer="Dockhand",
                model="Environment",
                configuration_url=_stack_url(base_url),
                via_device=(DOMAIN, f"env_{env_id}"),
                entry_type=DeviceEntryType.SERVICE,
            )
            # Pre-register individual stack devices so that compose-managed
            # container entities can safely reference them as via_device.
            for stack in stacks:
                stack_name = stack.get("name", "")
                if stack_name:
                    registry.async_get_or_create(
                        config_entry_id=entry.entry_id,
                        identifiers={(DOMAIN, f"stack_{env_id}_{stack_name}")},
                        name=f"{env_name} – {stack_name}",
                        manufacturer="Dockhand",
                        model="Stack",
                        configuration_url=_stack_url(base_url),
                        via_device=(DOMAIN, f"env_{env_id}_Stacks"),
                        entry_type=DeviceEntryType.SERVICE,
                    )

        # Optional resource group devices — only created when the feature is
        # enabled AND the slow coordinator confirmed that resources exist.
        slow_env = (slow_coordinator.data or {}).get("environments", {}).get(
            env_id
        ) or {}
        if enable_networks and slow_env.get("networks"):
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"env_{env_id}_Networks")},
                name=f"{env_name} – Networks",
                manufacturer="Dockhand",
                model="Environment",
                configuration_url=_network_url(base_url),
                via_device=(DOMAIN, f"env_{env_id}"),
                entry_type=DeviceEntryType.SERVICE,
            )
        if enable_images and slow_env.get("images"):
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"env_{env_id}_Images")},
                name=f"{env_name} – Images",
                manufacturer="Dockhand",
                model="Environment",
                configuration_url=_image_url(base_url),
                via_device=(DOMAIN, f"env_{env_id}"),
                entry_type=DeviceEntryType.SERVICE,
            )
        if enable_volumes and slow_env.get("volumes"):
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"env_{env_id}_Volumes")},
                name=f"{env_name} – Volumes",
                manufacturer="Dockhand",
                model="Environment",
                configuration_url=_volume_url(base_url),
                via_device=(DOMAIN, f"env_{env_id}"),
                entry_type=DeviceEntryType.SERVICE,
            )

    if enable_schedules:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "schedules_hub")},
            name="Schedules",
            manufacturer="Dockhand",
            model="Service",
            configuration_url=_schedules_url(base_url),
            entry_type=DeviceEntryType.SERVICE,
        )
        # Pre-register individual schedule devices so cleanup can compare
        # against registry entries consistently — same pattern as stacks.
        for sched in (slow_coordinator.data or {}).get("schedules") or []:
            key = _sched_key(sched)
            sched_name = sched.get("name", f"Schedule {key}")
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"schedule_{key}")},
                name=sched_name,
                manufacturer="Dockhand",
                model="Schedule",
                configuration_url=_schedules_url(base_url),
                via_device=(DOMAIN, "schedules_hub"),
                entry_type=DeviceEntryType.SERVICE,
            )


def _build_live_sets(entry: DockhandConfigEntry) -> dict[str, Any]:
    """Derive the complete set of live identifiers from all coordinator data.

    Returns a dict with keys:
        env_ids          set[int]   — environments currently in fast data
        online_env_ids   set[int]   — environments with online=True (or unknown)
        containers       set[str]   — live device identifiers (container_<env_id>_<id>)
        stacks           set[str]   — live device identifiers (stack_<env>_<name>)
        schedules        set[str]   — live device identifiers (schedule_<id>)
        image_uids       set[str]   — live entity unique_ids
        network_uids     set[str]   — live entity unique_ids
        volume_uids      set[str]   — live entity unique_ids
        update_uids      set[str]   — live entity unique_ids
        slow_valid       bool       — slow coordinator last poll succeeded
        update_valid     bool       — update coordinator last poll succeeded
        slow_env_ids     set[int]   — envs present in slow data (for Guard 3)
    """
    fast_data = entry.runtime_data.fast_coordinator.data or {}
    slow = entry.runtime_data.slow_coordinator
    slow_data = slow.data or {}
    update = entry.runtime_data.update_coordinator

    env_ids: set[int] = set(fast_data.keys())
    containers: set[str] = set()
    stacks: set[str] = set()

    for env_id, env_data in fast_data.items():
        for c in env_data.get("containers") or []:
            containers.add(f"container_{env_id}_{c['id']}")
        for s in env_data.get("stacks") or []:
            stacks.add(f"stack_{env_id}_{s['name']}")

    # Environments that are offline have unreachable Docker daemons — their
    # container and stack lists will be empty but that is not ground truth.
    # Track which envs are confirmed online so cleanup skips offline ones.
    online_env_ids: set[int] = {
        env_id
        for env_id, env_data in fast_data.items()
        if env_data.get("stats", {}).get("online", True)
    }

    # Slow-coordinator-derived sets — only meaningful when slow data is valid.
    # slow_valid: slow coordinator has run successfully and returned data.
    slow_valid = slow.last_update_success and bool(slow_data)
    slow_env_map = slow_data.get("environments", {})
    slow_env_ids: set[int] = set(slow_env_map.keys())

    # Only populate schedule live set when schedules are enabled.
    # When disabled, slow_data has schedules=[] — treat as "not loaded", not "deleted".
    entry_config = {**entry.data, **entry.options}
    schedules_enabled = slow.last_update_success and bool(
        entry_config.get(CONF_ENABLE_SCHEDULES, False)
    )

    schedules: set[str] = set()
    image_uids: set[str] = set()
    network_uids: set[str] = set()
    volume_uids: set[str] = set()

    if slow_valid:
        # Only populate when enabled — empty list when disabled is not "deleted".
        if schedules_enabled:
            for sched in slow_data.get("schedules") or []:
                if sched.get("id") is not None:
                    schedules.add(f"schedule_{_sched_key(sched)}")

        for env_id, env_data in slow_env_map.items():
            for img in env_data.get("images") or []:
                raw_id = img.get("id") or ""
                short_id = raw_id.split(":")[-1] if ":" in raw_id else raw_id
                image_uids.add(f"dockhand_image_{env_id}_{short_id}")
            for net in env_data.get("networks") or []:
                network_uids.add(f"dockhand_network_{env_id}_{net.get('id', '')}")
            for vol in env_data.get("volumes") or []:
                vname = vol.get("name") or vol.get("Name", "")
                volume_uids.add(f"dockhand_volume_{env_id}_{vname}")

    # Update-coordinator-derived set.
    update_valid = (
        update is not None and update.last_update_success and bool(update.data)
    )
    update_uids: set[str] = set()
    if update_valid and update is not None:
        for env_id, by_container in (update.data or {}).items():
            for item in by_container.values():
                name = item.get("containerName", "")
                if name:
                    update_uids.add(f"dockhand_update_{env_id}_{name}")

    return {
        "env_ids": env_ids,
        "online_env_ids": online_env_ids,
        "containers": containers,
        "stacks": stacks,
        "schedules": schedules,
        "schedules_enabled": schedules_enabled,
        "image_uids": image_uids,
        "network_uids": network_uids,
        "volume_uids": volume_uids,
        "update_uids": update_uids,
        "slow_valid": slow_valid,
        "update_valid": update_valid,
        "slow_env_ids": slow_env_ids,
    }


def _cleanup_stale_registry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
) -> None:
    """Remove stale device and entity registry entries after any coordinator update.

    Called from all three coordinator listeners and once at startup. Uses a
    single pass over the device registry and a single pass over the entity
    registry, both driven by live sets built from the current coordinator data.

    Safety guards — data ambiguity is handled in _build_live_sets:
    - Fast coordinator data must be non-empty (≥1 environment) before any
      device or entity removal is attempted.
    - Container and stack device cleanup is scoped per-environment using the
      env_id embedded in their identifiers. Only devices whose environment is
      confirmed online are candidates for removal — offline environments
      (host rebooting, Hawser temporarily unreachable) are preserved until
      they come back online.
    - Image, network, volume, and update entity cleanup uses the same per-env
      online guard. Schedule cleanup is gated on schedules being enabled.
    - Slow-derived sets are only populated when the slow coordinator's last
      poll succeeded.
    - Env/group device removal uses the fast env_ids set — an environment
      offline in Dockhand still appears in async_get_environments() and is
      preserved. A permanently deleted environment disappears from env_ids
      and all its devices and entities are cleaned up.
    """
    fast_data = entry.runtime_data.fast_coordinator.data or {}
    if not fast_data:
        # No confirmed environment data — do not remove anything.
        return

    live = _build_live_sets(entry)
    dev_registry = dr.async_get(hass)
    ent_registry = er.async_get(hass)

    # ── Device registry pass ─────────────────────────────────────────────────
    for device in dr.async_entries_for_config_entry(dev_registry, entry.entry_id):
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                continue

            if identifier.startswith("container_"):
                # Container identifiers are now "container_{env_id}_{docker_hash}".
                # Extract env_id from position [1] to scope the offline guard
                # precisely — only skip cleanup for containers in offline envs.
                try:
                    env_id = int(identifier.split("_")[1])
                except ValueError:
                    continue
                if identifier not in live["containers"]:
                    if env_id in live["online_env_ids"]:
                        _LOGGER.debug(
                            "Dockhand: removing stale container device %s", identifier
                        )
                        dev_registry.async_remove_device(device.id)
                    else:
                        _LOGGER.debug(
                            "Dockhand: env offline, skipping container cleanup: %s",
                            identifier,
                        )

            elif identifier.startswith("stack_"):
                # Stack identifiers are "stack_{env_id}_{name}" — extract env_id
                # for the same precise per-env offline guard.
                try:
                    env_id = int(identifier.split("_")[1])
                except ValueError:
                    continue
                if identifier not in live["stacks"]:
                    if env_id in live["online_env_ids"]:
                        _LOGGER.debug(
                            "Dockhand: removing stale stack device %s", identifier
                        )
                        dev_registry.async_remove_device(device.id)
                    else:
                        _LOGGER.debug(
                            "Dockhand: env offline, skipping stack cleanup: %s",
                            identifier,
                        )

            elif identifier.startswith("env_"):
                # Covers both env hub devices ("env_5") and group devices
                # ("env_5_Containers", "env_5_Stacks", etc.) — all keyed to
                # the same env_id in position [1] after splitting on "_".
                try:
                    env_id = int(identifier.split("_")[1])
                except ValueError:
                    continue
                if env_id not in live["env_ids"]:
                    _LOGGER.debug(
                        "Dockhand: removing stale env/group device %s", identifier
                    )
                    dev_registry.async_remove_device(device.id)

            elif identifier == "schedules_hub":
                # Remove the schedules hub device when schedules are disabled
                # in the config. It has no cleanup path otherwise since it has
                # no env_id and is not in any live set.
                if not live["schedules_enabled"]:
                    _LOGGER.debug("Dockhand: removing stale schedules_hub device")
                    dev_registry.async_remove_device(device.id)

            elif identifier.startswith("schedule_"):
                # Only clean up schedule devices when schedules are enabled and
                # the slow coordinator has valid data. When disabled, the live
                # set is empty but that means "not loaded", not "deleted".
                if live["schedules_enabled"] and identifier not in live["schedules"]:
                    _LOGGER.debug(
                        "Dockhand: removing stale schedule device %s", identifier
                    )
                    dev_registry.async_remove_device(device.id)

    # ── Entity registry pass ─────────────────────────────────────────────────
    # Only standalone entities (no device) need explicit cleanup here;
    # device-attached entities are handled by the device removal cascade above.
    for entity_entry in er.async_entries_for_config_entry(ent_registry, entry.entry_id):
        uid = entity_entry.unique_id or ""

        if uid.startswith("dockhand_image_"):
            if not live["slow_valid"]:
                continue
            try:
                env_id = int(uid.split("_")[2])
            except ValueError:
                continue
            # Only clean up if env is present in slow data AND online.
            if (
                env_id in live["slow_env_ids"]
                and env_id in live["online_env_ids"]
                and uid not in live["image_uids"]
            ):
                _LOGGER.debug("Dockhand: removing stale image entity %s", uid)
                ent_registry.async_remove(entity_entry.entity_id)

        elif uid.startswith("dockhand_network_"):
            if not live["slow_valid"]:
                continue
            try:
                env_id = int(uid.split("_")[2])
            except ValueError:
                continue
            if (
                env_id in live["slow_env_ids"]
                and env_id in live["online_env_ids"]
                and uid not in live["network_uids"]
            ):
                _LOGGER.debug("Dockhand: removing stale network entity %s", uid)
                ent_registry.async_remove(entity_entry.entity_id)

        elif uid.startswith("dockhand_volume_"):
            if not live["slow_valid"]:
                continue
            try:
                env_id = int(uid.split("_")[2])
            except ValueError:
                continue
            if (
                env_id in live["slow_env_ids"]
                and env_id in live["online_env_ids"]
                and uid not in live["volume_uids"]
            ):
                _LOGGER.debug("Dockhand: removing stale volume entity %s", uid)
                ent_registry.async_remove(entity_entry.entity_id)

        elif uid.startswith("dockhand_update_"):
            if not live["update_valid"]:
                continue
            # uid format: dockhand_update_{env_id}_{name}
            try:
                env_id = int(uid.split("_")[2])
            except ValueError:
                continue
            # Only clean up update entities for online environments.
            if env_id in live["online_env_ids"] and uid not in live["update_uids"]:
                _LOGGER.debug("Dockhand: removing stale update entity %s", uid)
                ent_registry.async_remove(entity_entry.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: DockhandConfigEntry) -> bool:
    """Unload Dockhand config entry."""
    # runtime_data is cleaned up automatically by HA.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
