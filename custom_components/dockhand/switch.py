from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import CONF_API_URL
from .coordinator import DockhandFastCoordinator
from .helpers import _container_device, _stack_device


# Switches make action calls — limit to 1 parallel update to avoid
# overwhelming the Dockhand API with concurrent start/stop requests.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: DockhandConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    fast: DockhandFastCoordinator = entry.runtime_data.fast_coordinator
    client = entry.runtime_data.client
    base_url: str = entry.data.get(CONF_API_URL, "")

    known_container_ids: set[str] = set()
    known_stack_ids: set[str] = set()

    def _build_entities() -> list[SwitchEntity]:
        new: list[SwitchEntity] = []
        for env_id, env_data in (fast.data or {}).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")

            for container in env_data.get("containers") or []:
                cid = container["id"]
                if cid not in known_container_ids:
                    known_container_ids.add(cid)
                    new.append(
                        DockhandContainerRunningSwitch(fast, client, env_id, env_name, base_url, container)
                    )

            for stack in env_data.get("stacks") or []:
                sid = f"{env_id}_{stack['name']}"
                if sid not in known_stack_ids:
                    known_stack_ids.add(sid)
                    new.append(
                        DockhandStackRunningSwitch(fast, client, env_id, env_name, base_url, stack)
                    )

        return new

    async_add_entities(_build_entities())
    entry.async_on_unload(
        fast.async_add_listener(lambda: async_add_entities(_build_entities()))
    )


class _BaseFastContainerSwitch(CoordinatorEntity[DockhandFastCoordinator], SwitchEntity):
    """Common base for per-container switches."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: DockhandFastCoordinator, client: Any,
                 env_id: int, env_name: str, base_url: str, container: dict) -> None:
        super().__init__(coordinator)
        self._client = client
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._container_id = container.get("id", "")
        self._container_name = container.get("name", "")

    def _container(self) -> dict | None:
        for c in (self.coordinator.data or {}).get(self._env_id, {}).get("containers") or []:
            if c.get("id") == self._container_id:
                return c
        return None

    @property
    def device_info(self) -> DeviceInfo:
        c = self._container()
        stack_name = (c.get("labels") or {}).get("com.docker.compose.project") if c else None
        return _container_device(self._container_id, self._container_name,
                                  self._env_id, self._env_name, self._base_url, stack_name)


class _BaseFastStackSwitch(CoordinatorEntity[DockhandFastCoordinator], SwitchEntity):
    """Common base for per-stack switches."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: DockhandFastCoordinator, client: Any,
                 env_id: int, env_name: str, base_url: str, stack: dict) -> None:
        super().__init__(coordinator)
        self._client = client
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._stack_name = stack.get("name", "")

    def _stack(self) -> dict | None:
        for s in (self.coordinator.data or {}).get(self._env_id, {}).get("stacks") or []:
            if s.get("name") == self._stack_name:
                return s
        return None

    @property
    def device_info(self) -> DeviceInfo:
        return _stack_device(self._stack_name, self._env_id, self._env_name, self._base_url)


class DockhandContainerRunningSwitch(_BaseFastContainerSwitch):
    """Start/stop switch for a container — on=running, off=stopped."""
    _attr_translation_key = "running"
    _attr_name = "Container"

    def __init__(self, coordinator: DockhandFastCoordinator, client: Any,
                 env_id: int, env_name: str, base_url: str, container: dict) -> None:
        super().__init__(coordinator, client, env_id, env_name, base_url, container)
        self._attr_unique_id = f"dockhand_container_{self._container_id}_running"

    @property
    def is_on(self) -> bool:
        c = self._container()
        return c.get("state") == "running" if c else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.async_start_container(self._env_id, self._container_id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.async_stop_container(self._env_id, self._container_id)
        await self.coordinator.async_request_refresh()


class DockhandStackRunningSwitch(_BaseFastStackSwitch):
    """Start/stop switch for a compose stack — the primary entity for a Stack device.

    Named 'Stack' (not 'Running') to match the convention that the primary
    entity of a device shares the device's name, making it the canonical
    on/off control in dashboards and automations.
    """
    _attr_translation_key = "stack"
    _attr_name = "Stack"

    def __init__(self, coordinator: DockhandFastCoordinator, client: Any,
                 env_id: int, env_name: str, base_url: str, stack: dict) -> None:
        super().__init__(coordinator, client, env_id, env_name, base_url, stack)
        self._attr_unique_id = f"dockhand_stack_{self._env_id}_{self._stack_name}_running"

    @property
    def is_on(self) -> bool:
        s = self._stack()
        return s.get("status") in ("running", "partial") if s else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.async_start_stack(self._env_id, self._stack_name)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.async_stop_stack(self._env_id, self._stack_name)
        await self.coordinator.async_request_refresh()
