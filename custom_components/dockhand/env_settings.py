"""An environment's own settings as switch and select entities
(docs/architecture.md §11): activity and metrics collection, update checks
and auto-update, image pruning and its mode, and the vulnerability scanner.

They're Dockhand's settings, changed through its API, so each entity reads
the saved value from a coordinator and, after a change, reads it back from
Dockhand rather than assuming it. Four of them read the flags Dockhand's
dashboard stats already carry (the fast poll); image pruning and the
scanner need their own endpoints, read on the slow poll. An entity is
created only once its setting could be read.
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

# Where a setting is read: the dashboard stats' flags (fast poll), or the
# slow poll's per-environment `settings`.
STATS = "stats"
IMAGE_PRUNE = "image_prune"
SCANNER = "scanner"

# Where a setting is written.
ENVIRONMENT = "environment"  # PUT /api/environments/{id}, partial
UPDATE_CHECK = "update_check"  # POST …/update-check, replaces every field


@dataclass(frozen=True, kw_only=True)
class EnvSettingDescription:
    """`key` is the translation key. `read`/`field` say where the value is,
    `write`/`write_field` where it's saved (the same unless given);
    `requires` names a stats flag that must be on for the setting to apply.
    `unique_suffix` ends the unique ID: its first word must not be one the
    registry cleanup dispatches on (image, update, …) unless
    __init__._TYPE_COLLISION_EXCLUDED_SUFFIXES lists it."""

    key: str
    read: str
    field: str = ""
    write: str = ""
    write_field: str = ""
    requires: str = ""
    unique_suffix: str


def setting_value(
    fast: DockhandFastCoordinator,
    slow: DockhandSlowCoordinator,
    env_id: int,
    description: EnvSettingDescription,
) -> Any:
    """The saved value, or None while it can't be read."""
    if description.read == STATS:
        stats = _coordinator_env(fast.data, env_id).get("stats") or {}
        return stats.get(description.field)
    settings = _coordinator_env(slow.data, env_id).get("settings") or {}
    value = settings.get(description.read)
    if description.read == SCANNER:
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
    target = description.write or description.read
    field = description.write_field or description.field
    if target == ENVIRONMENT:
        await async_dockhand_action(
            client.async_update_environment(env_id, **{field: value})
        )
    elif target == UPDATE_CHECK:
        # The endpoint replaces every setting: start from Dockhand's
        # current ones, not ours.
        current = await async_dockhand_action(
            client.async_get_update_check_settings(env_id)
        )
        await async_dockhand_action(
            client.async_set_update_check_settings(env_id, {**current, field: value})
        )
    elif target == IMAGE_PRUNE:
        current = await async_dockhand_action(
            client.async_get_image_prune_settings(env_id)
        )
        await async_dockhand_action(
            client.async_set_image_prune_settings(env_id, {**current, field: value})
        )
    else:
        await async_dockhand_action(client.async_set_scanner(env_id, value))
    if description.read == STATS:
        await fast.async_request_refresh()
        return
    await slow.async_refresh_env_settings(env_id)
    if description.read == SCANNER:
        # Whether scanning is on (the Vulnerability scanning sensor, and
        # the vulnerability counts it gates) comes from the dashboard
        # stats, which Dockhand recomputes from the scanner.
        await fast.async_request_refresh()


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
        super().__init__(fast if description.read == STATS else slow)
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
        if not super().available or self._value is None:
            return False
        if self._setting.requires:
            # Auto-update only applies while update checks are on, and
            # Dockhand reports it off whenever they aren't.
            stats = _coordinator_env(self._fast.data, self._env_id).get("stats") or {}
            return bool(stats.get(self._setting.requires))
        return True

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
