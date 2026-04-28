from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import CONF_API_URL
from .coordinator import DockhandFastCoordinator
from .helpers import _container_device, _stack_device

# Buttons make action calls — limit to 1 parallel update.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    fast: DockhandFastCoordinator = entry.runtime_data.fast_coordinator
    client = entry.runtime_data.client
    base_url: str = entry.data.get(CONF_API_URL, "")

    known_container_ids: set[str] = set()
    known_stack_ids: set[str] = set()

    def _build_entities() -> list[ButtonEntity]:
        new: list[ButtonEntity] = []
        for env_id, env_data in (fast.data or {}).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")

            for container in env_data.get("containers") or []:
                cid = container["id"]
                if cid not in known_container_ids:
                    known_container_ids.add(cid)
                    new.append(
                        DockhandContainerRestartButton(
                            fast, client, env_id, env_name, base_url, container
                        )
                    )

            for stack in env_data.get("stacks") or []:
                sid = f"{env_id}_{stack['name']}"
                if sid not in known_stack_ids:
                    known_stack_ids.add(sid)
                    new.append(
                        DockhandStackRestartButton(
                            fast, client, env_id, env_name, base_url, stack
                        )
                    )

        return new

    async_add_entities(_build_entities())
    entry.async_on_unload(
        fast.async_add_listener(lambda: async_add_entities(_build_entities()))
    )


class _BaseFastContainerButton(
    CoordinatorEntity[DockhandFastCoordinator], ButtonEntity
):
    """Common base for per-container buttons."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        client: Any,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._container_id = container.get("id", "")
        self._container_name = container.get("name", "")

    def _container(self) -> dict | None:
        for c in (self.coordinator.data or {}).get(self._env_id, {}).get(
            "containers"
        ) or []:
            if c.get("id") == self._container_id:
                return c
        return None

    @property
    def device_info(self) -> DeviceInfo:
        c = self._container()
        stack_name = (
            (c.get("labels") or {}).get("com.docker.compose.project") if c else None
        )
        return _container_device(
            self._container_id,
            self._container_name,
            self._env_id,
            self._env_name,
            self._base_url,
            stack_name,
        )


class _BaseFastStackButton(CoordinatorEntity[DockhandFastCoordinator], ButtonEntity):
    """Common base for per-stack buttons."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        client: Any,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._stack_name = stack.get("name", "")

    @property
    def device_info(self) -> DeviceInfo:
        return _stack_device(
            self._stack_name, self._env_id, self._env_name, self._base_url
        )


class DockhandContainerRestartButton(_BaseFastContainerButton):
    """Restart a running container — mirrors Portainer's restart button entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "restart"
    _attr_name = "Restart"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        client: Any,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
    ) -> None:
        super().__init__(coordinator, client, env_id, env_name, base_url, container)
        self._attr_unique_id = f"dockhand_container_{self._container_id}_restart"

    async def async_press(self) -> None:
        await self._client.async_restart_container(self._env_id, self._container_id)
        await self.coordinator.async_request_refresh()


class DockhandStackRestartButton(_BaseFastStackButton):
    """Restart a running compose stack."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "restart"
    _attr_name = "Restart"

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        client: Any,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict,
    ) -> None:
        super().__init__(coordinator, client, env_id, env_name, base_url, stack)
        self._attr_unique_id = (
            f"dockhand_stack_{self._env_id}_{self._stack_name}_restart"
        )

    async def async_press(self) -> None:
        await self._client.async_restart_stack(self._env_id, self._stack_name)
        await self.coordinator.async_request_refresh()
