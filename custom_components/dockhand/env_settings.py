"""An environment's own settings as switch, select and number entities
(docs/architecture.md §11): activity logging and metrics collection,
update checks and auto-update, image pruning, the disk-space warning and
the vulnerability scanner.

They're Dockhand's settings, changed through its API, so each entity reads
the saved value from a coordinator and, after a change, reads it back from
Dockhand rather than assuming it. An entity is created only once its
setting could be read: a token that can't see a setting gets no control
for it.
"""

from dataclasses import dataclass
from typing import Any, override

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import DockhandConfigEntry
from .api import DockhandClient
from .const import CONF_API_URL
from .coordinator import DockhandFastCoordinator, DockhandSlowCoordinator
from .helpers import (
    _all_envs,
    _coordinator_env,
    _env_device,
    already_registered,
    async_dockhand_action,
)

# Where each setting lives in Dockhand. "environment" is the environment
# record itself (read from the fast coordinator's dashboard stats); the
# rest come from their own endpoints, read on the slow poll.
ENVIRONMENT = "environment"
UPDATE_CHECK = "update_check"
IMAGE_PRUNE = "image_prune"
DISK_WARNING = "disk_warning"
SCANNER = "scanner"


@dataclass(frozen=True, kw_only=True)
class EnvSettingDescription:
    """`key` is the translation key; `section`/`field` say where the value
    is; `unique_suffix` ends the unique ID. A suffix's first word must not
    be one the registry cleanup dispatches on (image, update, …) unless
    __init__._TYPE_COLLISION_EXCLUDED_SUFFIXES lists it."""

    key: str
    section: str
    field: str = ""
    unique_suffix: str


def setting_value(
    fast: DockhandFastCoordinator,
    slow: DockhandSlowCoordinator,
    env_id: int,
    description: EnvSettingDescription,
) -> Any:
    """The saved value, or None while it can't be read."""
    if description.section == ENVIRONMENT:
        stats = _coordinator_env(fast.data, env_id).get("stats") or {}
        return stats.get(description.field)
    settings = _coordinator_env(slow.data, env_id).get("settings") or {}
    value = settings.get(description.section)
    if description.section == SCANNER:
        return value
    return value.get(description.field) if isinstance(value, dict) else None


async def async_save_setting(
    client: DockhandClient,
    fast: DockhandFastCoordinator,
    slow: DockhandSlowCoordinator,
    env_id: int,
    description: EnvSettingDescription,
    value: Any,
) -> None:
    """Save one setting in Dockhand, then read it back."""
    section, field = description.section, description.field
    if section == ENVIRONMENT:
        await async_dockhand_action(
            client.async_update_environment(env_id, **{field: value})
        )
        await fast.async_request_refresh()
        return
    if section == UPDATE_CHECK:
        # The endpoint replaces every setting: start from Dockhand's
        # current ones, not ours, which may be up to a poll old.
        current = await async_dockhand_action(
            client.async_get_update_check_settings(env_id)
        )
        await async_dockhand_action(
            client.async_set_update_check_settings(env_id, {**current, field: value})
        )
    elif section == IMAGE_PRUNE:
        current = await async_dockhand_action(
            client.async_get_image_prune_settings(env_id)
        )
        await async_dockhand_action(
            client.async_set_image_prune_settings(env_id, {**current, field: value})
        )
    elif section == DISK_WARNING:
        await async_dockhand_action(
            client.async_set_disk_warning_settings(env_id, **{field: value})
        )
    else:
        await async_dockhand_action(client.async_set_scanner(env_id, value))
    await slow.async_refresh_env_settings(env_id)


class DockhandEnvSettingEntity(CoordinatorEntity[DataUpdateCoordinator[Any]]):
    """One environment setting, on the environment's device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        fast: DockhandFastCoordinator,
        slow: DockhandSlowCoordinator,
        client: DockhandClient,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        description: EnvSettingDescription,
    ) -> None:
        super().__init__(fast if description.section == ENVIRONMENT else slow)
        self._setting = description
        self._attr_translation_key = description.key
        self._fast = fast
        self._slow = slow
        self._client = client
        self._env_id = env_id
        self._attr_unique_id = f"{entry_id}_{env_id}_{description.unique_suffix}"
        self._device = _env_device(entry_id, env_id, env_name, base_url)

    @property
    @override
    def device_info(self) -> DeviceInfo:
        return self._device

    @property
    def _value(self) -> Any:
        return setting_value(self._fast, self._slow, self._env_id, self._setting)

    @property
    @override
    def available(self) -> bool:
        return super().available and self._value is not None

    async def _save(self, value: Any) -> None:
        await async_save_setting(
            self._client,
            self._fast,
            self._slow,
            self._env_id,
            self._setting,
            value,
        )


def build_setting_entities[E: DockhandEnvSettingEntity](
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    platform: str,
    descriptions: tuple[EnvSettingDescription, ...],
    entity_class: type[E],
) -> list[E]:
    """This platform's setting entities not yet added, for every
    environment whose setting can be read."""
    data = entry.runtime_data
    fast, slow = data.fast_coordinator, data.slow_coordinator
    base_url = entry.data.get(CONF_API_URL, "")
    new: list[E] = []
    for env_id, env_data in _all_envs(fast.data).items():
        env_name = (env_data.get("stats") or {}).get("name", f"Environment {env_id}")
        for description in descriptions:
            if setting_value(fast, slow, env_id, description) is None:
                continue
            entity = entity_class(
                fast,
                slow,
                data.client,
                entry.entry_id,
                env_id,
                env_name,
                base_url,
                description,
            )
            if already_registered(
                hass,
                data.known_entity_ids,
                platform,
                entity.unique_id,
                pending_readd_ids=data.pending_readd_entity_ids,
            ):
                continue
            new.append(entity)
    return new
