"""A Docker event entity per container, fired from Dockhand's live feed."""

from typing import Any, override

from homeassistant.components.event import EventEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DockhandConfigEntry
from .const import CONF_API_URL, CONTAINER_EVENT_TYPES
from .entity import DockhandContainerEntity
from .entity_defaults import enabling_chosen
from .events import container_event_signal, env_sends_events
from .helpers import _all_envs, _coordinator_env, already_registered

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities = enabling_chosen(
        entry.entry_id, entry.options, async_add_entities
    )
    fast = entry.runtime_data.fast_coordinator
    base_url: str = entry.data.get(CONF_API_URL, "")
    known_ids = entry.runtime_data.known_entity_ids
    pending_readd_ids = entry.runtime_data.pending_readd_entity_ids

    def _build_entities() -> list[EventEntity]:
        new: list[EventEntity] = []
        for env_id, env_data in _all_envs(fast.data).items():
            env_name = (env_data.get("stats") or {}).get(
                "name", f"Environment {env_id}"
            )
            for container in env_data.get("containers") or []:
                if not container.get("name"):
                    continue
                entity = DockhandContainerEventEntity(
                    fast, entry.entry_id, env_id, env_name, base_url, container
                )
                if not already_registered(
                    hass,
                    known_ids,
                    "event",
                    entity.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    new.append(entity)
        return new

    async_add_entities(_build_entities())
    entry.async_on_unload(
        fast.async_add_listener(lambda: async_add_entities(_build_entities()))
    )


class DockhandContainerEventEntity(DockhandContainerEntity, EventEntity):
    """Fires when Docker reports a container starting, stopping, dying,
    running out of memory, changing health and so on.

    Off by default: it's for automations, and every container gets one.
    Only fires while the live feed is connected; Dockhand sends events only
    for environments that collect activity or metrics (or use Hawser Edge),
    so elsewhere it's unavailable.
    """

    _attr_translation_key = "docker_event"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_event_types = CONTAINER_EVENT_TYPES

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._attr_unique_id = (
            f"{self._entry_id}_{self._env_id}_container_"
            f"{self._container_name}_docker_event"
        )

    @property
    @override
    def available(self) -> bool:
        return (
            super().available
            and self._container() is not None
            and env_sends_events(_coordinator_env(self.coordinator.data, self._env_id))
        )

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                container_event_signal(
                    self._entry_id, self._env_id, self._container_name
                ),
                self._async_docker_event,
            )
        )

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        # Nothing here is keyed on entity_id, so a rename can happen in
        # place (HA 2026.11+) instead of removing and re-adding the entity,
        # which defining async_added_to_hass otherwise forces. Only ever
        # called by HA versions that have this method, which is also why
        # mypy (checking against an older one) can't see it yet.
        super().async_entity_id_changed(old_entity_id)  # type: ignore[misc, unused-ignore]

    @callback
    def _async_docker_event(self, data: dict[str, Any]) -> None:
        action = str(data.get("action") or "")
        if action.startswith("health_status"):
            action = "health_status_" + action.partition(":")[2].strip()
        if action not in CONTAINER_EVENT_TYPES:
            return
        attributes: dict[str, Any] = {}
        exit_code = (data.get("actorAttributes") or {}).get("exitCode")
        if action == "die" and exit_code is not None:
            attributes["exit_code"] = _int_or_str(exit_code)
        self._trigger_event(action, attributes)
        self.async_write_ha_state()


def _int_or_str(value: Any) -> int | str:
    try:
        return int(value)
    except TypeError, ValueError:
        return str(value)
