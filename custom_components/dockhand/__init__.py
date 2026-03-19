from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import (
    CONF_VERIFY_SSL,
    DOMAIN, PLATFORMS, CONF_API_URL, CONF_USERNAME, CONF_SESSION_COOKIE,
    CONF_ENABLE_SCHEDULES, CONF_ENABLE_IMAGES, CONF_ENABLE_VOLUMES, CONF_ENABLE_NETWORKS,
)
from .api import DockhandClient, DockhandAuthError, DockhandMFARequiredError
from .coordinator import DockhandFastCoordinator, DockhandSlowCoordinator
from .helpers import (
    _env_url, _container_url, _stack_url,
    _network_url, _image_url, _volume_url, _schedules_url,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DockhandData:
    """Runtime data stored on the config entry."""
    client: DockhandClient
    fast_coordinator: DockhandFastCoordinator
    slow_coordinator: DockhandSlowCoordinator


# Typed config entry alias — used throughout all platform setup functions
# so that entry.runtime_data is typed as DockhandData without casting.
type DockhandConfigEntry = ConfigEntry[DockhandData]


async def async_setup_entry(hass: HomeAssistant, entry: DockhandConfigEntry) -> bool:
    """Set up Dockhand from a config entry."""
    verify_ssl = bool(entry.data.get(CONF_VERIFY_SSL, True))
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = DockhandClient(session, entry.data)

    # Only attempt login if credentials are present. A no-auth install
    # has no username stored, so skip login entirely in that case.
    if entry.data.get(CONF_USERNAME) and not entry.data.get(CONF_SESSION_COOKIE):
        try:
            cookie = await client.async_login()
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_SESSION_COOKIE: cookie}
            )
        except DockhandMFARequiredError as err:
            raise ConfigEntryAuthFailed(
                "MFA is required — please re-add the integration to complete MFA setup"
            ) from err
        except DockhandAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Dockhand authentication failed: {err}"
            ) from err
        except Exception as err:
            raise ConfigEntryNotReady(
                f"Could not connect to Dockhand: {err}"
            ) from err

    config = {**entry.data, **entry.options}

    fast_coordinator = DockhandFastCoordinator(hass, client, config, entry=entry)
    slow_coordinator = DockhandSlowCoordinator(hass, client, config, entry=entry)

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
            "Dockhand: initial slow data fetch failed, will retry at next poll: %s", err
        )

    # Store runtime data on the entry itself (modern pattern — no hass.data).
    # Cleaned up automatically by HA when the entry is unloaded.
    entry.runtime_data = DockhandData(
        client=client,
        fast_coordinator=fast_coordinator,
        slow_coordinator=slow_coordinator,
    )

    # Pre-register group devices so they appear with correct names before
    # entity platforms load. Individual resource devices are created on-demand
    # by HA when their entities first reference them via via_device.
    base_url = entry.data.get(CONF_API_URL, "")
    _register_devices(hass, entry, fast_coordinator, slow_coordinator, config, base_url)

    # Run cleanup immediately on setup so that stale registry entries from a
    # previous install/reload are removed before platforms add new entities.
    # Without this, entities pruned between reloads (images, networks, volumes,
    # containers) persist in the registry and cause _2/_3/etc suffixes when new
    # entities with the same name try to register.
    _remove_stale_devices(hass, entry)
    _remove_stale_entities(hass, entry)

    # Register stale-device cleanup listeners BEFORE platform setup so that
    # cleanup fires before async_add_entities on each coordinator update.
    # Listener registration order determines fire order — if cleanup runs after
    # entity addition, a recreated container (new Docker ID, same name) briefly
    # has both old and new devices in the registry simultaneously, causing HA to
    # suffix the new entity_id with "_2". By cleaning up first, the old device
    # is gone before the new one is added, so the entity_id is clean.
    entry.async_on_unload(
        fast_coordinator.async_add_listener(
            lambda: _remove_stale_devices(hass, entry)
        )
    )
    entry.async_on_unload(
        slow_coordinator.async_add_listener(
            lambda: (
                _remove_stale_devices(hass, entry),
                _remove_stale_entities(hass, entry),
            )
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


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

    seen_envs: set[int] = set()

    for env_id, env_data in (fast_coordinator.data or {}).items():
        stats = env_data.get("stats") or {}
        env_name = stats.get("name", f"Environment {env_id}")
        seen_envs.add(env_id)

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
            c for c in (env_data.get("containers") or [])
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
            # HA will log a warning (and eventually error) if via_device points
            # to a device that doesn't exist yet when async_add_entities runs.
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
        # enabled AND the slow coordinator has confirmed that resources exist for
        # this environment. This preserves the "no empty groups" principle while
        # ensuring the parent device exists before its child entities load.
        slow_env = (slow_coordinator.data or {}).get("environments", {}).get(env_id) or {}
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


def _remove_stale_entities(
    hass: HomeAssistant,
    entry: "DockhandConfigEntry",
) -> None:
    """Remove entity registry entries for resources that no longer exist in Dockhand.

    Covers images, networks, and volumes — all represented as entities rather
    than devices. Called after each successful slow coordinator update.

    Safety policy — only clean up when we have confident data:
    - Guard 1: slow coordinator must have succeeded (last_update_success=True).
      If the last poll failed the coordinator retains old data, so we cannot
      trust it to represent reality.
    - Guard 2: at least one environment must be present in coordinator data.
      An empty environments dict could mean Dockhand is offline or returned a
      partial response — we do not wipe entities on ambiguous data.
    - Guard 3: only remove entities for environments that ARE present in the
      current data. Entities for a temporarily-offline environment are left
      alone; they will become unavailable via CoordinatorEntity instead.
    """
    slow = entry.runtime_data.slow_coordinator

    # Guard 1: last poll must have succeeded
    if not slow.last_update_success:
        return

    slow_data = slow.data or {}
    env_data_map = slow_data.get("environments", {})

    # Guard 2: must have at least one live environment in response
    if not env_data_map:
        return

    # Build live unique_id sets — only for environments present in this poll
    live_image_uids: set[str] = set()
    live_network_uids: set[str] = set()
    live_volume_uids: set[str] = set()

    for env_id, env_data in env_data_map.items():
        # Guard 3 is implicit: we only build live sets for present environments.
        # Entities belonging to absent environments are not touched.
        for img in env_data.get("images") or []:
            raw_id = img.get("id") or ""
            short_id = raw_id.split(":")[-1] if ":" in raw_id else raw_id
            live_image_uids.add(f"dockhand_image_{env_id}_{short_id}")

        for net in env_data.get("networks") or []:
            nid = net.get("id", "")
            live_network_uids.add(f"dockhand_network_{env_id}_{nid}")

        for vol in env_data.get("volumes") or []:
            vname = vol.get("name") or vol.get("Name", "")
            live_volume_uids.add(f"dockhand_volume_{env_id}_{vname}")

    registry = er.async_get(hass)
    present_env_ids = set(env_data_map.keys())

    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        uid = entity_entry.unique_id or ""

        if uid.startswith("dockhand_image_"):
            # Parse env_id from uid: "dockhand_image_{env_id}_{short_id}"
            parts = uid.split("_")
            # uid pattern: dockhand _ image _ {env_id} _ {short_id}  (4 parts min)
            if len(parts) >= 4:
                try:
                    env_id = int(parts[2])
                except ValueError:
                    continue
                if env_id in present_env_ids and uid not in live_image_uids:
                    _LOGGER.debug("Dockhand: removing stale image entity %s", uid)
                    registry.async_remove(entity_entry.entity_id)

        elif uid.startswith("dockhand_network_"):
            # uid pattern: dockhand _ network _ {env_id} _ {network_id}
            parts = uid.split("_")
            if len(parts) >= 4:
                try:
                    env_id = int(parts[2])
                except ValueError:
                    continue
                if env_id in present_env_ids and uid not in live_network_uids:
                    _LOGGER.debug("Dockhand: removing stale network entity %s", uid)
                    registry.async_remove(entity_entry.entity_id)

        elif uid.startswith("dockhand_volume_"):
            # uid pattern: dockhand _ volume _ {env_id} _ {volume_name}
            # volume_name may contain underscores — reconstruct from index 3+
            parts = uid.split("_")
            if len(parts) >= 4:
                try:
                    env_id = int(parts[2])
                except ValueError:
                    continue
                if env_id in present_env_ids and uid not in live_volume_uids:
                    _LOGGER.debug("Dockhand: removing stale volume entity %s", uid)
                    registry.async_remove(entity_entry.entity_id)


def _remove_stale_devices(
    hass: HomeAssistant,
    entry: "DockhandConfigEntry",
) -> None:
    """Remove devices whose backing objects have been deleted in Dockhand.

    Called after every coordinator update. Conservative policy:
    - Environment and group devices are never removed automatically (an
      environment could be temporarily offline or containers restarting).
    - Individual container and stack devices are removed when absent from
      coordinator data for an entire poll cycle.
    - Legacy network_ and volume_ device entries (from pre-entity-rollup
      installs) are also cleaned up if encountered.
    """
    registry = dr.async_get(hass)
    fast_data = entry.runtime_data.fast_coordinator.data or {}
    slow_data = entry.runtime_data.slow_coordinator.data or {}

    # Build sets of all live device identifiers from coordinator data
    live_containers: set[str] = set()
    live_stacks: set[str] = set()
    live_networks: set[str] = set()
    live_volumes: set[str] = set()

    for env_id, env_data in fast_data.items():
        for c in env_data.get("containers") or []:
            live_containers.add(f"container_{c['id']}")
        for s in env_data.get("stacks") or []:
            live_stacks.add(f"stack_{env_id}_{s['name']}")

    for env_id, env_data in slow_data.get("environments", {}).items():
        for net in env_data.get("networks") or []:
            live_networks.add(f"network_{net['id']}")
        for vol in env_data.get("volumes") or []:
            vname = vol.get("Name") or vol.get("name", "")
            live_volumes.add(f"volume_{env_id}_{vname}")

    # Walk every device registered to this config entry and remove stale ones
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                continue
            if identifier.startswith("container_") and identifier not in live_containers:
                _LOGGER.debug("Dockhand: removing stale container device %s", identifier)
                registry.async_remove_device(device.id)
            elif identifier.startswith("stack_") and identifier not in live_stacks:
                _LOGGER.debug("Dockhand: removing stale stack device %s", identifier)
                registry.async_remove_device(device.id)
            elif identifier.startswith("network_") and identifier not in live_networks:
                _LOGGER.debug("Dockhand: removing stale network device %s", identifier)
                registry.async_remove_device(device.id)
            elif identifier.startswith("volume_") and identifier not in live_volumes:
                _LOGGER.debug("Dockhand: removing stale volume device %s", identifier)
                registry.async_remove_device(device.id)


async def async_unload_entry(hass: HomeAssistant, entry: DockhandConfigEntry) -> bool:
    """Unload Dockhand config entry."""
    # runtime_data is cleaned up automatically by HA — no manual hass.data removal needed.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
