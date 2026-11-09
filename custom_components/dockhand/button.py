import asyncio
from typing import Any, override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import (
    CONF_API_URL,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_UPDATE_ENTITIES,
    DEFAULT_ENABLE_UPDATE_ENTITIES,
)
from .coordinator import (
    DockhandFastCoordinator,
    DockhandSlowCoordinator,
    DockhandUpdateCoordinator,
)
from .entity import (
    DockhandContainerEntity,
    DockhandScheduleEntity,
    DockhandStackEntity,
)
from .helpers import (
    _actionable_pending_update_container_ids,
    _all_envs,
    _coordinator_env,
    _env_device,
    _find_git_stack,
    _schedule_can_run,
    _stack_device,
    _stack_has_system_container,
    already_registered,
    async_dockhand_action,
)

# Reads come from the coordinators. Actions aren't limited: each is one
# request to Dockhand, which queues the Docker work itself.
PARALLEL_UPDATES = 0

# Same values as update.py's _poll_job — one shared job-polling budget
# across both platforms since Dockhand's job endpoint behaves identically
# either way.
_JOB_POLL_INTERVAL_SECONDS = 2
_JOB_POLL_MAX_ATTEMPTS = 900  # 900 * 2s = 30 minutes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    fast: DockhandFastCoordinator = entry.runtime_data.fast_coordinator
    slow: DockhandSlowCoordinator = entry.runtime_data.slow_coordinator
    update_coordinator: DockhandUpdateCoordinator | None = (
        entry.runtime_data.update_coordinator
    )
    client = entry.runtime_data.client
    base_url: str = entry.data.get(CONF_API_URL, "")
    # Update entities off also means no Update all button (issue #23).
    update_entities_enabled = entry.options.get(
        CONF_ENABLE_UPDATE_ENTITIES, DEFAULT_ENABLE_UPDATE_ENTITIES
    )

    known_ids = entry.runtime_data.known_entity_ids
    pending_readd_ids = entry.runtime_data.pending_readd_entity_ids

    def _build_entities() -> list[ButtonEntity]:
        new: list[ButtonEntity] = []
        for env_id, env_data in _all_envs(fast.data).items():
            stats = env_data.get("stats") or {}
            env_name = stats.get("name", f"Environment {env_id}")

            # Per-environment "Check for updates" button — always present,
            # regardless of CONF_ENABLE_PRECISE_UPDATES or
            # CONF_ENABLE_UPDATE_ENTITIES (github.com/raetha/ha-dockhand/issues/23
            # design discussion): it's a read-only, user-initiated, one-off
            # forced check, not a way to perform updates, so neither option
            # needs to gate its existence. What each option controls is
            # only what happens to the *result* — see DockhandCheckUpdatesButton
            # itself.
            check_updates_button = DockhandCheckUpdatesButton(
                fast,
                client,
                update_coordinator,
                update_entities_enabled,
                entry.entry_id,
                env_id,
                env_name,
                base_url,
            )
            if not already_registered(
                hass,
                known_ids,
                "button",
                check_updates_button.unique_id,
                pending_readd_ids=pending_readd_ids,
            ):
                new.append(check_updates_button)

            # Bulk "Update all" button: present while update entities are
            # on, available only while something can be updated (Dockhand's
            # own button disappears instead, but an entity that comes and
            # goes breaks automations and history).
            if update_entities_enabled:
                bulk_button = DockhandEnvBulkUpdateButton(
                    fast,
                    update_coordinator,
                    client,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                )
                if not already_registered(
                    hass,
                    known_ids,
                    "button",
                    bulk_button.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    new.append(bulk_button)

            for container in env_data.get("containers") or []:
                if container.get("systemContainer"):
                    continue
                restart_button = DockhandContainerRestartButton(
                    fast,
                    client,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                    container,
                )
                for button in (
                    restart_button,
                    DockhandContainerPauseButton(
                        fast,
                        client,
                        entry.entry_id,
                        env_id,
                        env_name,
                        base_url,
                        container,
                    ),
                    DockhandContainerResumeButton(
                        fast,
                        client,
                        entry.entry_id,
                        env_id,
                        env_name,
                        base_url,
                        container,
                    ),
                ):
                    if not already_registered(
                        hass,
                        known_ids,
                        "button",
                        button.unique_id,
                        pending_readd_ids=pending_readd_ids,
                    ):
                        new.append(button)

            for stack in env_data.get("stacks") or []:
                has_system = _stack_has_system_container(
                    stack, env_data.get("containers") or []
                )
                if not has_system:
                    stack_restart_button = DockhandStackRestartButton(
                        fast,
                        client,
                        entry.entry_id,
                        env_id,
                        env_name,
                        base_url,
                        stack,
                    )
                    if not already_registered(
                        hass,
                        known_ids,
                        "button",
                        stack_restart_button.unique_id,
                        pending_readd_ids=pending_readd_ids,
                    ):
                        new.append(stack_restart_button)
                    if stack.get("sourceType") == "internal":
                        deploy_button = DockhandStackDeployButton(
                            fast,
                            client,
                            entry.entry_id,
                            env_id,
                            env_name,
                            base_url,
                            stack,
                        )
                        if not already_registered(
                            hass,
                            known_ids,
                            "button",
                            deploy_button.unique_id,
                            pending_readd_ids=pending_readd_ids,
                        ):
                            new.append(deploy_button)

        return new

    def _build_slow_entities() -> list[ButtonEntity]:
        new: list[ButtonEntity] = []
        slow_envs = _all_envs(slow.data)
        fast_data = _all_envs(fast.data)
        for env_id, env_data in slow_envs.items():
            fast_stats = (fast_data.get(env_id) or {}).get("stats") or {}
            env_name = fast_stats.get("name", f"Environment {env_id}")
            for git_stack in env_data.get("git_stacks") or []:
                git_deploy_button = DockhandGitStackDeployButton(
                    fast,
                    slow,
                    client,
                    entry.entry_id,
                    env_id,
                    env_name,
                    base_url,
                    git_stack,
                )
                if not already_registered(
                    hass,
                    known_ids,
                    "button",
                    git_deploy_button.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    new.append(git_deploy_button)
        if entry.options.get(CONF_ENABLE_SCHEDULES, False):
            for sched in (slow.data or {}).get("schedules") or []:
                if sched.get("id") is None or not _schedule_can_run(sched):
                    continue
                run_button = DockhandScheduleRunButton(
                    slow, client, entry.entry_id, sched, base_url
                )
                if not already_registered(
                    hass,
                    known_ids,
                    "button",
                    run_button.unique_id,
                    pending_readd_ids=pending_readd_ids,
                ):
                    new.append(run_button)
        return new

    async_add_entities(_build_entities())
    async_add_entities(_build_slow_entities())
    entry.async_on_unload(
        fast.async_add_listener(lambda: async_add_entities(_build_entities()))
    )
    entry.async_on_unload(
        slow.async_add_listener(lambda: async_add_entities(_build_slow_entities()))
    )


class _BaseFastContainerButton(DockhandContainerEntity, ButtonEntity):
    """Common base for per-container buttons."""

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


class _BaseFastStackButton(DockhandStackEntity, ButtonEntity):
    """Common base for per-stack buttons."""

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


class DockhandContainerRestartButton(_BaseFastContainerButton):
    """Restart a running container."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "restart"

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
            f"{self._entry_id}_{self._env_id}_container_{self._container_name}_restart"
        )

    @override
    async def async_press(self) -> None:
        c = self._container()
        if not c:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="container_not_found",
            )
        await async_dockhand_action(
            self._client.async_restart_container(self._env_id, c["id"])
        )
        await self.coordinator.async_refresh_environment(self._env_id)


class _ContainerStateButton(_BaseFastContainerButton):
    """Pause or resume: only offered in the state it applies to, and off by
    default, since most people never pause a container."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _from_state: str
    _suffix: str
    _client_call: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_unique_id = (
            f"{self._entry_id}_{self._env_id}_container_"
            f"{self._container_name}_{self._suffix}"
        )

    @property
    @override
    def available(self) -> bool:
        c = self._container()
        return (
            super().available and c is not None and c.get("state") == self._from_state
        )

    @override
    async def async_press(self) -> None:
        c = self._container()
        if not c:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="container_not_found",
            )
        call = getattr(self._client, self._client_call)
        await async_dockhand_action(call(self._env_id, c["id"]))
        await self.coordinator.async_refresh_environment(self._env_id)


class DockhandContainerPauseButton(_ContainerStateButton):
    """Freeze a running container's processes."""

    _attr_translation_key = "pause"
    _from_state = "running"
    _suffix = "pause"
    _client_call = "async_pause_container"


class DockhandContainerResumeButton(_ContainerStateButton):
    """Let a paused container's processes run again."""

    _attr_translation_key = "resume"
    _from_state = "paused"
    _suffix = "resume"
    _client_call = "async_unpause_container"


class DockhandStackRestartButton(_BaseFastStackButton):
    """Restart a running compose stack."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "restart"

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
            f"{self._entry_id}_{self._env_id}_stack_{self._stack_name}_restart"
        )

    @override
    async def async_press(self) -> None:
        await async_dockhand_action(
            self._client.async_restart_stack(self._env_id, self._stack_name)
        )
        await self.coordinator.async_refresh_environment(self._env_id)


class DockhandStackDeployButton(_BaseFastStackButton):
    """Redeploy an internal (non-git) stack — pull latest images and
    recreate whatever Compose's own diffing decides changed.

    Labeled "Redeploy" — confirmed as Dockhand's own literal button
    title for this exact action (RedeployPopover.svelte's own
    `title="Redeploy"`), not a name we chose. See async_deploy_stack's
    docstring for exactly which Dockhand UI default this mirrors.

    Only created for stacks with sourceType == "internal" — confirmed
    from Dockhand's own frontend source that its Redeploy control is
    hidden entirely for "external"/untracked stacks (no compose file
    location to redeploy from). Git stacks have their own Deploy button
    via a completely separate code path (DockhandGitStackDeployButton),
    which dynamically renames itself "Deploy"/"Sync from Git" to match
    Dockhand's own state-dependent labeling for that button — the two
    buttons are named independently, not required to match each other.
    """

    _attr_translation_key = "stack_deploy"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_unique_id = (
            f"{self._entry_id}_{self._env_id}_stack_{self._stack_name}_deploy"
        )

    @override
    async def async_press(self) -> None:
        if not self._stack():
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="action_failed",
                translation_placeholders={"error": "Stack not found"},
            )
        result = await async_dockhand_action(
            self._client.async_deploy_stack(self._env_id, self._stack_name)
        )
        # Dockhand returns HTTP 200 with {"success": false, "error": "..."}
        # for an expected failure mode (e.g. compose file location not
        # configured) rather than an HTTP error — _request() wouldn't
        # raise on this, so check explicitly.
        if not result.get("success", True):
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="action_failed",
                translation_placeholders={
                    "error": result.get("error", "Stack deploy failed")
                },
            )
        await self.coordinator.async_refresh_environment(self._env_id)


class DockhandEnvBulkUpdateButton(
    CoordinatorEntity[DockhandFastCoordinator], ButtonEntity
):
    """Update every container in this environment with a pending update,
    in a single batch-update-stream call — matching Dockhand's own
    "Update all" button exactly (confirmed from its frontend source:
    same endpoint, same non-system-container exclusion).

    Conditionally present, not just conditionally enabled: only created
    when there is at least one non-system-container pending update in
    this environment (same as Dockhand's own `{#if updatableContainersCount
    > 0}` gating for its "Update all" button) — removed via the central
    cleanup system the moment there's nothing left to update, exactly
    mirroring how the button disappears in Dockhand's own UI rather than
    just going idle/disabled.

    "Pending update" here means either Tier 1 (Dockhand's own cached
    pending-updates check) or Tier 2 (the optional precise digest-based
    check-updates coordinator) — via the shared _container_has_pending_update()
    helper, same definition update.py's own entities use. Folding Tier 2
    in is safe against staleness specifically because that helper looks
    Tier 2 up by each container's *current* id: a container recreated
    since Tier 2 last polled (the normal effect of an image update) gets
    a new id, so Tier 2's old entry — still under the old id — is never
    found and can't keep this button alive, or its own container list,
    past the point an update actually resolved.

    Named "Update all containers" — a static name via translation_key,
    not a live count in the name. An earlier version showed "Update all
    (N)" matching Dockhand's own wording, but a changing friendly_name on
    a persistent (not recreated) entity reads as confusing entity churn
    in HA's own UI/history, so this reverted to a plain static name.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "env_bulk_update"

    def __init__(
        self,
        fast_coordinator: DockhandFastCoordinator,
        update_coordinator: DockhandUpdateCoordinator | None,
        client: Any,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(fast_coordinator)
        self._update_coordinator = update_coordinator
        self._client = client
        self._entry_id = entry_id
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._attr_unique_id = f"{entry_id}_{env_id}_bulk_update"

    def _updatable_container_ids(self) -> list[str]:
        """Pending-update container IDs for this env, excluding system
        containers — same exclusion Dockhand's own "Update all" applies
        (confirmed from its frontend: `!container.systemContainer`), via
        the shared _actionable_pending_update_container_ids() helper (see
        helpers.py) rather than rebuilding that exclusion inline here —
        the same combined Tier 1 + Tier 2 definition as this button's own
        creation gate (see async_setup_entry above) and the update
        entities in update.py, so the button can never exist while
        reporting nothing to actually update, and never omit a container
        Tier 2 alone flagged. Install itself doesn't care which tier
        flagged a container — batch-update-stream only needs a container
        id — so there's no reason the trigger list should be more
        restrictive than the button's own visibility.
        """
        env_data = _coordinator_env(self.coordinator.data, self._env_id)
        containers = env_data.get("containers") or []
        pending = env_data.get("pending_update_container_ids") or set()
        update_env_data = (
            _coordinator_env(self._update_coordinator.data, self._env_id)
            if self._update_coordinator is not None
            else None
        )
        return _actionable_pending_update_container_ids(
            containers,
            pending,
            update_env_data,
            env_data.get("pending_update_details"),
        )

    @property
    @override
    def available(self) -> bool:
        return super().available and bool(self._updatable_container_ids())

    @property
    @override
    def device_info(self) -> DeviceInfo:
        return _env_device(self._entry_id, self._env_id, self._env_name, self._base_url)

    async def _vulnerability_criteria(self) -> str | None:
        """Same best-effort fetch-then-fall-back-to-Dockhand's-own-default
        pattern as the per-container update entities in update.py."""
        try:
            settings = await self._client.async_get_update_check_settings(self._env_id)
        except Exception:
            return None
        criteria = settings.get("vulnerabilityCriteria")
        return str(criteria) if criteria else None

    @override
    async def async_press(self) -> None:
        container_ids = self._updatable_container_ids()
        if not container_ids:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="action_failed",
                translation_placeholders={"error": "No pending updates"},
            )
        try:
            criteria = await self._vulnerability_criteria()
            job_id = await async_dockhand_action(
                self._client.async_start_batch_update_stream(
                    self._env_id, container_ids, vulnerability_criteria=criteria
                )
            )
            await self._poll_job(job_id)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_refresh_environment(self._env_id)

    async def _poll_job(self, job_id: str) -> None:
        """Poll GET /api/jobs/{id} until the whole batch finishes.

        Unlike update.py's per-entity _poll_job, this covers multiple
        containers in one job with no single update_percentage to
        report (ButtonEntity has no progress concept) — collects every
        per-container failure/block across the batch and raises a
        single summary error covering all of them, rather than stopping
        at the first one, since a partial batch failure shouldn't hide
        that other containers in the same press may have failed too.
        """
        failures: list[str] = []
        for _ in range(_JOB_POLL_MAX_ATTEMPTS):
            job = await self._client.async_get_job(job_id)

            for line in job.get("lines") or []:
                data = line.get("data") or {}
                event_type = data.get("type")
                if event_type == "blocked":
                    reason = data.get("blockReason", "vulnerability findings")
                    cid = data.get("containerId", "?")
                    failures.append(f"{cid}: blocked ({reason})")
                elif event_type == "progress" and data.get("step") == "failed":
                    failures.append(
                        f"{data.get('containerId', '?')}: {data.get('error', 'failed')}"
                    )

            status = job.get("status")
            if status == "done":
                if failures:
                    raise HomeAssistantError(
                        translation_domain="dockhand",
                        translation_key="action_failed",
                        translation_placeholders={
                            "error": "; ".join(dict.fromkeys(failures))
                        },
                    )
                return
            if status == "error":
                result = job.get("result") or {}
                raise HomeAssistantError(
                    translation_domain="dockhand",
                    translation_key="action_failed",
                    translation_placeholders={
                        "error": result.get("error", "batch update failed")
                    },
                )
            await asyncio.sleep(_JOB_POLL_INTERVAL_SECONDS)

        raise HomeAssistantError(
            translation_domain="dockhand",
            translation_key="action_failed",
            translation_placeholders={"error": "Timed out waiting for batch update"},
        )


class DockhandCheckUpdatesButton(
    CoordinatorEntity[DockhandFastCoordinator], ButtonEntity
):
    """Trigger an immediate, one-off, user-forced image update check for
    this environment only — always present, regardless of
    CONF_ENABLE_PRECISE_UPDATES or CONF_ENABLE_UPDATE_ENTITIES.

    Design settled on for github.com/raetha/ha-dockhand/issues/23: this
    button is an isolated action, deliberately decoupled from
    DockhandUpdateCoordinator's own scheduled background polling (that
    coordinator may not even exist). Pressing it always calls Dockhand's
    real check-updates API for this environment via the client directly
    — that's the entire point of the button, forcing Dockhand to refresh
    its own cached values right now, which is useful on its own even if
    neither tier is configured to consume the result locally. What
    happens to the *result* then depends on what's actually enabled:

      - CONF_ENABLE_PRECISE_UPDATES on (update_coordinator exists): the
        result also updates Tier 2's data, via
        DockhandUpdateCoordinator.async_merge_check_results() — same
        end effect the button always had, just fed with the response
        already in hand instead of triggering a second, redundant check.

      - CONF_ENABLE_UPDATE_ENTITIES on: the result also updates Tier 1's
        pending_update_container_ids AND pending_update_details for this
        environment immediately, via
        DockhandFastCoordinator.async_merge_pending_updates_from_check()
        — so a forced check shows at once rather than at the next poll.
        The full per-container response (hasUpdate, newerVersion,
        digests) goes to that merge, not just the ids with an update, so
        newer-version suggestions show at once too.

      - Neither on: the check still runs (Dockhand's cache still gets
        refreshed), but nothing local captures the response — there's
        nothing configured to show it.

    Attached to the environment device and scoped to that environment
    only, like Dockhand's own UI, which has no "check everything" action
    either: a button on one environment's device shouldn't change
    another's update state. The Updates card's "Check for updates"
    presses every environment's button in scope when that's wanted.

    Raises on failure — this is an explicit user action, and a failed
    check should tell the user it failed rather than silently doing
    nothing, unlike the coordinator's own resilient background refresh
    (see coordinator.py's docstrings for that distinction).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "check_updates"

    def __init__(
        self,
        fast_coordinator: DockhandFastCoordinator,
        client: Any,
        update_coordinator: DockhandUpdateCoordinator | None,
        update_entities_enabled: bool,
        entry_id: str,
        env_id: int,
        env_name: str,
        base_url: str,
    ) -> None:
        super().__init__(fast_coordinator)
        self._client = client
        self._update_coordinator = update_coordinator
        self._update_entities_enabled = update_entities_enabled
        self._entry_id = entry_id
        self._env_id = env_id
        self._env_name = env_name
        self._base_url = base_url
        self._attr_unique_id = f"{entry_id}_{env_id}_check_updates"

    @property
    @override
    def device_info(self) -> DeviceInfo:
        return _env_device(self._entry_id, self._env_id, self._env_name, self._base_url)

    @override
    async def async_press(self) -> None:
        items = await async_dockhand_action(
            self._client.async_check_container_updates(self._env_id)
        )

        if self._update_coordinator is not None:
            self._update_coordinator.async_merge_check_results(self._env_id, items)
            await self._update_coordinator.async_refresh_self_update(self._env_id)

        if self._update_entities_enabled:
            # Pass the full per-container response straight through — the
            # coordinator itself now derives both pending_update_container_ids
            # (actionable only) and pending_update_details (actionable +
            # semver-only, with newerVersion) from it, the same split the
            # periodic 60s poll applies to pending-updates. See this
            # button's own docstring above.
            self.coordinator.async_merge_pending_updates_from_check(self._env_id, items)


class _BaseSlowGitStackButton(CoordinatorEntity[DockhandSlowCoordinator], ButtonEntity):
    """Common base for per-git-stack buttons (slow coordinator).

    Lives on the same device as the regular Stack — see
    sensor.BaseSlowGitStackSensor for why there's no separate device type.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

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

    def _git_stack(self) -> dict[str, Any] | None:
        return _find_git_stack(self.coordinator.data, self._env_id, self._stack_name)

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


class DockhandGitStackDeployButton(_BaseSlowGitStackButton):
    """Pull latest and redeploy the stack.

    name and icon are live @properties matching Dockhand's own state-
    dependent labeling exactly, confirmed from its frontend source:
    "Deploy" + a rocket icon when the stack is down (status 'not
    deployed' or 'created'), "Sync from Git" + a refresh icon otherwise
    — both cases call the identical underlying action in Dockhand
    (deployGitStackWithProgress), it's purely a cosmetic change for UX
    clarity based on context, not two different operations. Our button
    mirrors that same relabeling for the same reason.

    If Dockhand ever changes this terminology or iconography, this needs
    to be updated to match — check stacks/+page.svelte's conditional
    around GitDeployProgressPopover on a future Dockhand version review.
    """

    _attr_translation_key = "git_stack_deploy"

    def __init__(
        self, fast_coordinator: DockhandFastCoordinator, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._fast_coordinator = fast_coordinator
        self._attr_unique_id = (
            f"{self._entry_id}_{self._env_id}_stack_{self._stack_name}_git_deploy"
        )

    def _is_down(self) -> bool:
        for s in (
            _coordinator_env(self._fast_coordinator.data, self._env_id).get("stacks")
            or []
        ):
            if s.get("name") == self._stack_name:
                return s.get("status") in ("not deployed", "created")
        return False

    @property
    @override
    def name(self) -> str:
        return "Deploy" if self._is_down() else "Sync from Git"

    @property
    @override
    def icon(self) -> str:
        # Rocket for Deploy, refresh (Dockhand's own RefreshCw, styled
        # like its restart icon) for Sync from Git — same source as name.
        return "mdi:rocket-launch-outline" if self._is_down() else "mdi:refresh"

    @override
    async def async_press(self) -> None:
        gs = self._git_stack()
        if not gs:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="git_stack_not_found",
            )
        await async_dockhand_action(self._client.async_deploy_git_stack(gs["id"]))
        await self.coordinator.async_refresh()


class DockhandScheduleRunButton(DockhandScheduleEntity, ButtonEntity):
    """Run a schedule once now, outside its own timing."""

    _attr_translation_key = "schedule_run"

    def __init__(
        self,
        coordinator: DockhandSlowCoordinator,
        client: Any,
        entry_id: str,
        sched: dict[str, Any],
        base_url: str,
    ) -> None:
        super().__init__(coordinator, entry_id, sched, base_url, "run")
        self._client = client

    @property
    @override
    def available(self) -> bool:
        return super().available and self._find() is not None

    @override
    async def async_press(self) -> None:
        await async_dockhand_action(
            self._client.async_run_schedule(self._sched_type, self._sched_id)
        )
        await self.coordinator.async_refresh()
