"""Actions that change a whole environment or recreate a container.

Registered once for the integration (not per config entry) and admin-only:
pruning deletes data and recreating replaces a container.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN
from .helpers import (
    _device_id_env,
    _find_container,
    async_dockhand_action,
    device_config_entry_ids,
    ha_schema,
)

if TYPE_CHECKING:
    from . import DockhandConfigEntry


class DockhandService(StrEnum):
    PRUNE = "prune"
    RECREATE_CONTAINER = "recreate_container"


class DockhandServiceArgument(StrEnum):
    RESOURCES = "resources"
    ALL_IMAGES = "all_images"
    PULL = "pull"


# Docker's prune report field for each resource's deleted items.
PRUNE_RESOURCES: dict[str, str] = {
    "containers": "ContainersDeleted",
    "images": "ImagesDeleted",
    "volumes": "VolumesDeleted",
    "networks": "NetworksDeleted",
}

PRUNE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(DockhandServiceArgument.RESOURCES): vol.All(
            cv.ensure_list, [vol.In(list(PRUNE_RESOURCES))], vol.Length(min=1)
        ),
        vol.Optional(DockhandServiceArgument.ALL_IMAGES, default=False): cv.boolean,
    }
)

RECREATE_CONTAINER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(DockhandServiceArgument.PULL, default=True): cv.boolean,
    }
)


def _invalid_target() -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key="invalid_target"
    )


@callback
def _device_and_entry(
    hass: HomeAssistant, device_id: str
) -> tuple[set[str], DockhandConfigEntry]:
    """A Dockhand device's identifiers and its loaded config entry."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise _invalid_target()
    for entry_id in device_config_entry_ids(device):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            if entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="entry_not_loaded"
                )
            idents = {ident for domain, ident in device.identifiers if domain == DOMAIN}
            return idents, entry
    raise _invalid_target()


@callback
def _environment(
    hass: HomeAssistant, device_id: str
) -> tuple[DockhandConfigEntry, int]:
    idents, entry = _device_and_entry(hass, device_id)
    for env_id in entry.runtime_data.fast_coordinator.data.get("environments", {}):
        if _device_id_env(entry.entry_id, env_id) in idents:
            return entry, env_id
    raise _invalid_target()


@callback
def _container(
    hass: HomeAssistant, device_id: str
) -> tuple[DockhandConfigEntry, int, dict[str, Any]]:
    idents, entry = _device_and_entry(hass, device_id)
    prefix = f"{entry.entry_id}_container_"
    for ident in idents:
        if not ident.startswith(prefix):
            continue
        env_part, _, name = ident[len(prefix) :].partition("_")
        if not env_part.isdigit():
            continue
        env_id = int(env_part)
        container = _find_container(
            entry.runtime_data.fast_coordinator.data, env_id, name
        )
        if container is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="container_not_found"
            )
        return entry, env_id, container
    raise _invalid_target()


async def _async_prune(call: ServiceCall) -> ServiceResponse:
    entry, env_id = _environment(call.hass, call.data[ATTR_DEVICE_ID])
    data = entry.runtime_data
    response: dict[str, Any] = {"space_reclaimed": 0}
    for resource in PRUNE_RESOURCES:
        if resource not in call.data[DockhandServiceArgument.RESOURCES]:
            continue
        report = await async_dockhand_action(
            data.client.async_prune(
                env_id,
                resource,
                all_images=call.data[DockhandServiceArgument.ALL_IMAGES],
            )
        )
        response[f"{resource}_deleted"] = len(
            report.get(PRUNE_RESOURCES[resource]) or []
        )
        response["space_reclaimed"] += int(report.get("SpaceReclaimed") or 0)
    await data.fast_coordinator.async_refresh_environment(env_id)
    await data.slow_coordinator.async_refresh()
    return response


async def _async_recreate_container(call: ServiceCall) -> None:
    entry, env_id, container = _container(call.hass, call.data[ATTR_DEVICE_ID])
    if container.get("systemContainer"):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="system_container"
        )
    data = entry.runtime_data
    await async_dockhand_action(
        data.client.async_recreate_container(
            env_id,
            container["id"],
            name=container.get("name", ""),
            image=container.get("image", ""),
            pull=call.data[DockhandServiceArgument.PULL],
            start=container.get("state") == "running",
        )
    )
    await data.fast_coordinator.async_refresh_environment(env_id)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async_register_admin_service(
        hass,
        DOMAIN,
        DockhandService.PRUNE,
        _async_prune,
        schema=ha_schema(PRUNE_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        DockhandService.RECREATE_CONTAINER,
        _async_recreate_container,
        schema=ha_schema(RECREATE_CONTAINER_SCHEMA),
    )
