from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import CONF_API_URL, CONF_ENABLE_SCHEDULES
from .coordinator import DockhandFastCoordinator, DockhandSlowCoordinator
from .entity import (
    DockhandContainerEntity,
    DockhandScheduleEntity,
    DockhandStackEntity,
)
from .entity_defaults import enabling_chosen
from .helpers import (
    _all_envs,
    _compose_project,
    _container_device,
    _coordinator_env,
    _find_container,
    _find_git_stack,
    _schedule_can_toggle,
    _schedule_is_system_toggle,
    _stack_device,
    _stack_has_system_container,
    already_registered,
    async_dockhand_action,
)

# Reads come from the coordinators. Actions aren't limited: each is one
# request to Dockhand, which queues the Docker work itself.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities = enabling_chosen(
        entry.entry_id, entry.options, async_add_entities
    )
    fast: DockhandFastCoordinator = entry.runtime_data.fast_coordinator
    slow: DockhandSlowCoordinator = entry.runtime_data.slow_coordinator
    client = entry.runtime_data.client
    base_url: str = entry.data.get(CONF_API_URL, "")

    known_ids = entry.runtime_data.known_entity_ids
    pending_readd_ids = entry.runtime_data.pending_readd_entity_ids

    def _build_entities() -> list[SwitchEntity]:
        new: list[SwitchEntity] = []
        for env_id, env_data in _all_envs(fast.data).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")

            for container in env_data.get("containers") or []:
                if container.get("systemContainer"):
                    continue
                running_switch = DockhandContainerRunningSwitch(
                    fast,
                    client,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                    container,
                )
                if already_registered(
                    hass,
                    known_ids,
                    "switch",
                    running_switch.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    continue
                new.append(running_switch)

            for stack in env_data.get("stacks") or []:
                if _stack_has_system_container(stack, env_data.get("containers") or []):
                    continue
                stack_switch = DockhandStackRunningSwitch(
                    fast,
                    client,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                    stack,
                )
                if already_registered(
                    hass,
                    known_ids,
                    "switch",
                    stack_switch.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    continue
                new.append(stack_switch)

        return new

    def _build_auto_update_entities() -> list[SwitchEntity]:
        """Container auto-update toggles — primary coordinator is the slow
        one (auto_update_settings only changes there), fast is consulted
        directly for container existence. Not gated behind Compose vs
        stack-less like runtime controls: this setting is Dockhand's own,
        keyed by (environmentId, containerName), and survives recreation
        regardless of how the container is managed. Suppressed for system
        containers (Dockhand itself, or a Hawser agent), same as the
        running switch and restart button — an auto-update replacing
        Dockhand's own management container out from under it is exactly
        the kind of self-inflicted outage those two are already suppressed
        to avoid."""
        new: list[SwitchEntity] = []
        for env_id, env_data in _all_envs(fast.data).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")
            for container in env_data.get("containers") or []:
                name = container.get("name", "")
                if not name or container.get("systemContainer"):
                    continue
                auto_update_switch = DockhandContainerAutoUpdateSwitch(
                    fast,
                    slow,
                    client,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                    name,
                )
                if already_registered(
                    hass,
                    known_ids,
                    "switch",
                    auto_update_switch.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    continue
                new.append(auto_update_switch)
        return new

    def _build_git_stack_entities() -> list[SwitchEntity]:
        new: list[SwitchEntity] = []
        slow_envs = _all_envs(slow.data)
        fast_data = _all_envs(fast.data)
        for env_id, env_data in slow_envs.items():
            fast_stats = (fast_data.get(env_id) or {}).get("stats") or {}
            env_name = fast_stats.get("name", f"Environment {env_id}")
            for git_stack in env_data.get("git_stacks") or []:
                git_switch = DockhandGitStackAutoUpdateSwitch(
                    slow,
                    client,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                    git_stack,
                )
                if already_registered(
                    hass,
                    known_ids,
                    "switch",
                    git_switch.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    continue
                new.append(git_switch)
        if entry.options.get(CONF_ENABLE_SCHEDULES, False):
            for sched in (slow.data or {}).get("schedules") or []:
                if sched.get("id") is None or not _schedule_can_toggle(sched):
                    continue
                sched_switch = DockhandScheduleEnabledSwitch(
                    slow, client, entry.entry_id, sched, base_url
                )
                if not already_registered(
                    hass,
                    known_ids,
                    "switch",
                    sched_switch.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    new.append(sched_switch)
        return new

    def _add_fast_entities() -> None:
        async_add_entities(_build_entities())
        async_add_entities(_build_auto_update_entities())

    async_add_entities(_build_entities())
    async_add_entities(_build_auto_update_entities())
    async_add_entities(_build_git_stack_entities())
    entry.async_on_unload(fast.async_add_listener(_add_fast_entities))
    entry.async_on_unload(
        slow.async_add_listener(lambda: async_add_entities(_build_git_stack_entities()))
    )


class _BaseFastContainerSwitch(DockhandContainerEntity, SwitchEntity):
    """Common base for per-container switches."""

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        client: Any,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, container)
        self._client = client


class _BaseFastStackSwitch(DockhandStackEntity, SwitchEntity):
    """Common base for per-stack switches."""

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        client: Any,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry_id, env_id, env_name, base_url, stack)
        self._client = client


class DockhandContainerRunningSwitch(_BaseFastContainerSwitch):
    """Start/stop switch for a container — the primary entity for a Container device.

    No translation_key: with _attr_has_entity_name=True and no translation_key,
    the entity name equals the device name, making this the canonical on/off
    control. Entity_id becomes switch.{env}_containers_{name} with no suffix.
    on=running, off=stopped.
    """

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        client: Any,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container: dict,
    ) -> None:
        super().__init__(
            coordinator, client, entry_id, env_id, env_name, base_url, container
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{self._env_id}_container_{self._container_name}_running"
        )

    @property
    @override
    def is_on(self) -> bool:
        c = self._container()
        return c.get("state") == "running" if c else False

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        c = self._container()
        if not c:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="container_not_found",
            )
        # A paused container can't be started, only resumed.
        start = (
            self._client.async_unpause_container
            if c.get("state") == "paused"
            else self._client.async_start_container
        )
        await async_dockhand_action(start(self._env_id, c["id"]))
        await self.coordinator.async_refresh_environment(self._env_id)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        c = self._container()
        if not c:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="container_not_found",
            )
        await async_dockhand_action(
            self._client.async_stop_container(self._env_id, c["id"])
        )
        await self.coordinator.async_refresh_environment(self._env_id)


class DockhandStackRunningSwitch(_BaseFastStackSwitch):
    """Start/stop switch for a compose stack — the primary entity for a Stack device.

    No translation_key: with _attr_has_entity_name=True and no translation_key,
    the entity name equals the device name, making this the canonical on/off
    control. Entity_id becomes switch.{env}_stacks_{name} with no suffix.
    """

    def __init__(
        self,
        coordinator: DockhandFastCoordinator,
        client: Any,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        stack: dict,
    ) -> None:
        super().__init__(
            coordinator, client, entry_id, env_id, env_name, base_url, stack
        )
        self._attr_unique_id = (
            f"{self._entry_id}_{self._env_id}_stack_{self._stack_name}_running"
        )

    @property
    @override
    def is_on(self) -> bool:
        s = self._stack()
        return s.get("status") in ("running", "partial") if s else False

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        await async_dockhand_action(
            self._client.async_start_stack(self._env_id, self._stack_name)
        )
        await self.coordinator.async_refresh_environment(self._env_id)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await async_dockhand_action(
            self._client.async_stop_stack(self._env_id, self._stack_name)
        )
        await self.coordinator.async_refresh_environment(self._env_id)


class DockhandContainerAutoUpdateSwitch(
    CoordinatorEntity[DockhandSlowCoordinator], SwitchEntity
):
    """Toggle Dockhand's own scheduled auto-update for one container.

    Distinct from our `update` entity (a manual/HA-triggered pull-and-
    recreate) — this toggles Dockhand's own cron-based check-and-update
    job. Primary coordinator is the slow one (auto_update_settings only
    changes there); the fast coordinator is consulted directly for
    container existence, the same dual-coordinator pattern number.py uses
    for runtime controls.

    Not restricted to stack-less containers: Dockhand persists this
    setting keyed by (environmentId, containerName), not container ID, so
    it survives recreation regardless of how the container is managed.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "container_auto_update"

    def __init__(
        self,
        fast_coordinator: DockhandFastCoordinator,
        slow_coordinator: DockhandSlowCoordinator,
        client: Any,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        container_name: str,
    ) -> None:
        super().__init__(slow_coordinator)
        self._fast_coordinator = fast_coordinator
        self._client = client
        self._entry_id = entry_id
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._container_name = container_name
        self._optimistic_value: bool | None = None
        self._attr_unique_id = (
            f"{entry_id}_{env_id}_container_{container_name}_auto_update"
        )

    def _container(self) -> dict | None:
        return _find_container(
            self._fast_coordinator.data, self._env_id, self._container_name
        )

    @property
    @override
    def available(self) -> bool:
        if self._container() is None or not super().available:
            return False
        env = _coordinator_env(self.coordinator.data, self._env_id)
        return "auto_update_settings" not in (env.get("fetch_failures") or set())

    @override
    def _handle_coordinator_update(self) -> None:
        self._optimistic_value = None
        super()._handle_coordinator_update()

    @property
    @override
    def is_on(self) -> bool | None:
        if self._optimistic_value is not None:
            return self._optimistic_value
        slow_data = self.coordinator.data or {}
        env = _coordinator_env(slow_data, self._env_id)
        settings = env.get("auto_update_settings") or {}
        # Absence from the map means disabled — Dockhand's batch endpoint
        # only includes containers with the setting currently enabled.
        return self._container_name in settings

    async def _async_set(self, enabled: bool) -> None:
        if not self._container():
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="container_not_found",
            )
        await async_dockhand_action(
            self._client.async_set_container_auto_update(
                self._env_id, self._container_name, enabled
            )
        )
        self._optimistic_value = enabled
        self.async_write_ha_state()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    @property
    @override
    def device_info(self) -> DeviceInfo:
        c = self._container()
        return _container_device(
            getattr(self, "hass", None),
            self._entry_id,
            self._container_name,
            self._env_id,
            self._env_name,
            self._base_url,
            _compose_project(c),
        )


class DockhandGitStackAutoUpdateSwitch(
    CoordinatorEntity[DockhandSlowCoordinator], SwitchEntity
):
    """Toggle a git stack's own auto-deploy schedule (its `autoUpdate` flag).

    Distinct from DockhandContainerAutoUpdateSwitch — this is the git
    stack's own scheduled sync+redeploy job, set via PUT on the git stack
    itself, not the per-container update-check schedule.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "git_stack_auto_deploy"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        client: Any,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
        git_stack: dict,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry_id = entry_id
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._stack_name = git_stack.get("stackName", "")
        self._optimistic_value: bool | None = None
        self._attr_unique_id = (
            f"{entry_id}_{env_id}_stack_{self._stack_name}_git_auto_deploy"
        )

    def _git_stack(self) -> dict[str, Any] | None:
        return _find_git_stack(self.coordinator.data, self._env_id, self._stack_name)

    @override
    def _handle_coordinator_update(self) -> None:
        self._optimistic_value = None
        super()._handle_coordinator_update()

    @property
    @override
    def is_on(self) -> bool | None:
        if self._optimistic_value is not None:
            return self._optimistic_value
        gs = self._git_stack()
        return bool(gs.get("autoUpdate")) if gs else None

    async def _async_set(self, enabled: bool) -> None:
        gs = self._git_stack()
        if not gs:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="git_stack_not_found",
            )
        await async_dockhand_action(
            self._client.async_update_git_stack(gs["id"], {"autoUpdate": enabled})
        )
        self._optimistic_value = enabled
        self.async_write_ha_state()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    @property
    @override
    def device_info(self) -> DeviceInfo:
        return _stack_device(
            getattr(self, "hass", None),
            self._entry_id,
            self._stack_name,
            self._env_id,
            self._env_name,
            self._base_url,
            source_type="git",
        )


class DockhandScheduleEnabledSwitch(DockhandScheduleEntity, SwitchEntity):
    """Whether a Dockhand schedule runs: off pauses it, as in Dockhand."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "schedule_enabled"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        client: Any,
        entry_id: str,
        sched: dict[str, Any],
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, sched, base_url, "enabled")
        self._client = client
        self._system = _schedule_is_system_toggle(sched)

    @property
    @override
    def available(self) -> bool:
        return super().available and self._find() is not None

    @property
    @override
    def is_on(self) -> bool | None:
        s = self._find()
        return bool(s.get("enabled")) if s else None

    async def _set(self, enabled: bool) -> None:
        # Dockhand only flips, and this entity's state can be up to a poll
        # old, so flip until Dockhand reports the wanted state (at most
        # twice: the second flip undoes a change made elsewhere meanwhile).
        for _ in range(2):
            now = await async_dockhand_action(
                self._client.async_toggle_schedule(
                    self._sched_type, self._sched_id, system=self._system
                )
            )
            if now == enabled:
                break
        await self.coordinator.async_refresh_schedules()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
