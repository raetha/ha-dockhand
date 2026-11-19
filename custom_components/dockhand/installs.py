"""Installing container updates.

Every Install in an environment goes through one queue, so updates that
start together share one Dockhand batch job: Home Assistant's own "update
all", the cards' Update all and a script updating several containers all
call each update entity's Install at once. Dockhand's batch-update-stream
fixes its container list when it starts, so the first Install waits a
moment for the others before starting the job; anything arriving while a
job runs goes into the next one. Dockhand updates a job's containers one
after another, which is also gentler on the host than parallel jobs.

Each container's own outcome (updated, skipped, blocked, failed) and
progress is tracked separately, so each update entity still reports its
own result. After a job, the environment is refreshed once, and the
precise update check (an environment-wide registry check, since Dockhand
can't check one container) runs once in the background.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN
from .helpers import async_dockhand_action

if TYPE_CHECKING:
    from .api import DockhandClient
    from .coordinator import DockhandFastCoordinator, DockhandUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# How long the first Install of a batch waits for others to join it.
GATHER_SECONDS = 2.0
JOB_POLL_INTERVAL_SECONDS = 2.0
# A scan plus a large image pull, for several containers in turn, can take
# a while; this only guards against a job stuck in "running" forever.
JOB_POLL_MAX_ATTEMPTS = 1800  # 1 hour

# Dockhand's own current/total on progress lines counts containers in the
# batch, not progress within one, so each container's percentage comes
# from the fixed order of its steps instead (scanning only with a scanner).
STEP_PERCENTAGES = {
    "pulling": 20,
    "scanning": 45,
    "creating": 75,
    "done": 100,
}


class InstallSkipped(Exception):
    """Dockhand skipped the container (reported as a successful job, but
    nothing was updated), e.g. the container it reaches the environment
    through."""


@dataclass
class _Batch:
    container_ids: dict[str, None] = field(default_factory=dict)
    # container id -> None (updated) or the exception to raise for it.
    outcomes: dict[str, Exception | None] = field(default_factory=dict)
    # container id -> the name Dockhand reported it under, for the log.
    names: dict[str, str] = field(default_factory=dict)
    task: asyncio.Task[None] | None = None


def install_signal(entry_id: str, env_id: int) -> str:
    """Dispatcher signal sent whenever an environment's install progress
    changes, so its update entities can show it."""
    return f"{DOMAIN}_{entry_id}_install_{env_id}"


def _failed(message: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="action_failed",
        translation_placeholders={"error": message},
    )


class DockhandInstaller:
    """One per config entry: the install queue for each environment."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        client: DockhandClient,
        fast: DockhandFastCoordinator,
        update_coordinator: DockhandUpdateCoordinator | None,
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._client = client
        self._fast = fast
        self._update_coordinator = update_coordinator
        self._waiting: dict[int, _Batch] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        # (env id, container id) -> percentage, while queued or installing.
        self._progress: dict[tuple[int, str], int] = {}
        self._check_queued: dict[int, asyncio.Task[None]] = {}
        self._check_locks: dict[int, asyncio.Lock] = {}

    def progress(self, env_id: int, container_id: str) -> int | None:
        """The container's install percentage while it's queued or being
        installed, else None."""
        return self._progress.get((env_id, container_id))

    async def async_install(
        self, env_id: int, container_ids: list[str]
    ) -> dict[str, Exception | None]:
        """Install updates for these containers, sharing a Dockhand job with
        any other Install in the environment that starts at the same time.

        Returns each container's outcome: None when updated, else the
        exception describing why not (HomeAssistantError, or InstallSkipped).
        Returns once the job has finished and the environment has been
        refreshed.
        """
        batch = self._waiting.get(env_id)
        if batch is None:
            batch = _Batch()
            self._waiting[env_id] = batch
            # Not eager: the batch must be registered as waiting before it
            # can start, or a later Install could miss it.
            batch.task = self._hass.async_create_task(
                self._async_run(env_id, batch),
                f"dockhand install batch {env_id}",
                eager_start=False,
            )
        for container_id in container_ids:
            batch.container_ids.setdefault(container_id)
            self._progress.setdefault((env_id, container_id), 0)
        self._async_notify(env_id)
        assert batch.task is not None
        await asyncio.shield(batch.task)
        return {cid: batch.outcomes.get(cid) for cid in container_ids}

    @callback
    def _async_notify(self, env_id: int) -> None:
        async_dispatcher_send(self._hass, install_signal(self._entry_id, env_id))

    async def _async_run(self, env_id: int, batch: _Batch) -> None:
        await asyncio.sleep(GATHER_SECONDS)
        lock = self._locks.setdefault(env_id, asyncio.Lock())
        async with lock:
            # From here the container list is fixed: later Installs queue
            # the next batch.
            if self._waiting.get(env_id) is batch:
                del self._waiting[env_id]
            ids = list(batch.container_ids)
            try:
                await self._async_run_job(env_id, ids, batch)
            except Exception as err:
                error = (
                    err if isinstance(err, HomeAssistantError) else _failed(str(err))
                )
                if not isinstance(err, HomeAssistantError):
                    _LOGGER.error(
                        "Dockhand: update job for %s in environment %s failed: %s",
                        ", ".join(ids),
                        env_id,
                        err,
                    )
                for cid in ids:
                    batch.outcomes.setdefault(cid, error)
            self._log_not_updated(env_id, batch)
            try:
                await self._fast.async_refresh_environment(env_id)
            except Exception as err:  # the next poll catches up
                _LOGGER.debug("Dockhand: refresh after updates failed: %s", err)
            finally:
                for cid in ids:
                    self._progress.pop((env_id, cid), None)
                self._async_notify(env_id)
        if self._update_coordinator is not None and None in batch.outcomes.values():
            self._async_queue_check(env_id)

    async def _async_run_job(self, env_id: int, ids: list[str], batch: _Batch) -> None:
        criteria = await self._vulnerability_criteria(env_id)
        job_id = await async_dockhand_action(
            self._client.async_start_batch_update_stream(
                env_id, ids, vulnerability_criteria=criteria
            )
        )
        for _ in range(JOB_POLL_MAX_ATTEMPTS):
            job = await self._client.async_get_job(job_id)
            self._read_lines(env_id, job.get("lines") or [], batch)
            status = job.get("status")
            if status == "done":
                # Dockhand reports every container it handles, so one it
                # never mentioned wasn't updated.
                for cid in ids:
                    batch.outcomes.setdefault(
                        cid, _failed("Dockhand finished without updating it")
                    )
                return
            if status == "error":
                result = job.get("result") or {}
                raise _failed(result.get("error", "update job failed"))
            await asyncio.sleep(JOB_POLL_INTERVAL_SECONDS)
        raise _failed("update timed out waiting for Dockhand")

    def _read_lines(
        self, env_id: int, lines: list[dict[str, Any]], batch: _Batch
    ) -> None:
        """Dockhand's job endpoint returns every line so far on each poll,
        so this re-reads them all; outcomes keep the first verdict."""
        changed = False
        for line in lines:
            data = line.get("data") or {}
            cid = data.get("containerId")
            if cid not in batch.container_ids:
                continue
            if name := data.get("containerName"):
                batch.names[cid] = str(name)
            step = data.get("step")
            pct = STEP_PERCENTAGES.get(step) if isinstance(step, str) else None
            key = (env_id, cid)
            if pct is not None and pct > self._progress.get(key, 0):
                self._progress[key] = pct
                changed = True
            event_type = data.get("type")
            if event_type == "progress" and step == "done":
                batch.outcomes.setdefault(cid, None)
            elif event_type == "blocked":
                reason = data.get("blockReason", "vulnerability findings")
                batch.outcomes.setdefault(cid, _failed(f"Update blocked: {reason}"))
            elif event_type == "progress" and step == "failed":
                batch.outcomes.setdefault(
                    cid, _failed(data.get("error", "update failed"))
                )
            elif event_type == "progress" and step == "skipped":
                batch.outcomes.setdefault(
                    cid,
                    InstallSkipped(data.get("message") or "update skipped by Dockhand"),
                )
        if changed:
            self._async_notify(env_id)

    @staticmethod
    def _log_not_updated(env_id: int, batch: _Batch) -> None:
        """Log each container the job didn't update: Install's error only
        reaches whoever started it (a toast, a script), and is gone by the
        time anyone looks."""
        for cid, outcome in batch.outcomes.items():
            if outcome is not None:
                _LOGGER.warning(
                    "Dockhand did not update %s in environment %s: %s",
                    batch.names.get(cid, cid),
                    env_id,
                    _message(outcome),
                )

    async def _vulnerability_criteria(self, env_id: int) -> str | None:
        """The environment's vulnerability blocking policy; on failure,
        None lets Dockhand use its own default ("never": scan, don't
        block) rather than failing the update."""
        try:
            settings = await self._client.async_get_update_check_settings(env_id)
        except Exception as err:
            _LOGGER.warning(
                "Could not fetch vulnerability criteria for env %s — Dockhand"
                " will use its own default ('never': scan but don't block): %s",
                env_id,
                err,
            )
            return None
        criteria = settings.get("vulnerabilityCriteria")
        return str(criteria) if criteria else None

    @callback
    def _async_queue_check(self, env_id: int) -> None:
        """Re-run the precise check after updates, so a precise digest
        shows without waiting for its daily run. It checks the whole
        environment against the registries, so batches finishing close
        together share one: at most one runs and one waits."""
        if env_id in self._check_queued:
            return
        self._check_queued[env_id] = self._hass.async_create_background_task(
            self._async_check(env_id),
            f"dockhand update check {env_id}",
            eager_start=False,
        )

    async def _async_check(self, env_id: int) -> None:
        lock = self._check_locks.setdefault(env_id, asyncio.Lock())
        async with lock:
            self._check_queued.pop(env_id, None)
            assert self._update_coordinator is not None
            try:
                await self._update_coordinator.async_check_environment(env_id)
            except Exception as err:  # the updates themselves worked
                _LOGGER.debug("Dockhand: update check after updates failed: %s", err)


def raise_for_outcome(outcome: Exception | None) -> None:
    """Raise what Install should for one container's outcome."""
    if isinstance(outcome, InstallSkipped):
        raise _failed(str(outcome))
    if outcome is not None:
        raise outcome


def summarize_failures(
    outcomes: dict[str, Exception | None], names: Callable[[str], str]
) -> None:
    """Raise one error naming every container that didn't update."""
    errors = [o for o in outcomes.values() if o is not None]
    if errors and all(o is errors[0] for o in errors):
        # One cause for the whole job (it couldn't start, a permission
        # refusal): raise it as it is.
        raise_for_outcome(errors[0])
    failures = [
        f"{names(cid)}: {_message(outcome)}"
        for cid, outcome in outcomes.items()
        if outcome is not None
    ]
    if failures:
        raise _failed("; ".join(dict.fromkeys(failures)))


def _message(outcome: Exception) -> str:
    if isinstance(outcome, HomeAssistantError) and outcome.translation_placeholders:
        return str(outcome.translation_placeholders.get("error", outcome))
    return str(outcome)
