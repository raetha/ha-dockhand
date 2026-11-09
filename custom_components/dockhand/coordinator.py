import asyncio
import logging
import re
from typing import Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DockhandAuthError, DockhandClient, DockhandNotFoundError
from .const import (
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_RESOURCE_STATS,
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_VOLUMES,
    DEFAULT_ENABLE_RESOURCE_STATS,
    DOMAIN,
    FAST_POLL_INTERVAL,
    PRECISE_UPDATES_POLL_INTERVAL,
    SLOW_POLL_INTERVAL,
    VERSION_POLL_INTERVAL,
)
from .helpers import (
    _all_envs,
    _compose_project,
    _coordinator_env,
    _extract_runtime_config,
)

_LOGGER = logging.getLogger(__name__)

# Seconds to wait before each successive 401 retry in DockhandFastCoordinator.
# Without retries, one transient 401 (e.g. during a brief Dockhand restart or
# a momentary connectivity hiccup) fires ConfigEntryAuthFailed immediately —
# prompting the user to "re-authenticate" with a token that is still valid.
# These delays give Dockhand time to recover before we surface a re-auth dialog
# that would turn out to be unnecessary. Total maximum wait before giving up:
# sum(_AUTH_RETRY_DELAYS) seconds = 30s across 2 retries.
_AUTH_RETRY_DELAYS: tuple[int, ...] = (5, 25)


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _unwrap(
    val: Any,
    default: Any,
    label: str,
    failures: set[str] | None = None,
    key: str | None = None,
) -> Any:
    """Unwrap a asyncio.gather(..., return_exceptions=True) result,
    returning `default` and logging a warning if it's an Exception.

    `failures`/`key` are optional for genuinely inconsequential fetches — but
    every call site that feeds into anything cleanup logic could act on (see
    __init__.py's _build_live_sets) MUST pass both. Without them, a real fetch
    failure (DNS resolution failure, timeout, connection reset, a 5xx —
    anything) silently becomes indistinguishable from "genuinely empty," and
    downstream cleanup — which exists specifically to remove entities for
    things that are actually gone — has no way to tell the difference. A
    transient schedules-fetch failure would otherwise read as every schedule
    deleted. See docs/architecture.md §9 for how `fetch_failures` closes this
    for every resource this coordinator fetches.
    """
    if isinstance(val, Exception):
        _LOGGER.warning("Dockhand: error fetching %s: %s", label, val)
        if failures is not None and key is not None:
            failures.add(key)
        return default
    return val


class _RemovalGuard:
    """Decides when a list from Dockhand is complete enough to remove things
    on its evidence.

    Dockhand's containers, stacks and images routes answer HTTP 200 with
    `[]` when Docker can't be reached, and a container being recreated (an
    update) briefly drops out of the list. Removing a device loses its
    entities' history in between, so whatever went missing has to still be
    missing on the next refresh, and an empty list also needs Dockhand's
    own count (when there is one) to agree.
    """

    def __init__(self) -> None:
        self._known: dict[tuple[int, str], set[str]] = {}
        self._missing: dict[tuple[int, str], set[str]] = {}

    def confirmed(
        self, env_id: int, key: str, names: set[str], dockhand_total: Any
    ) -> bool:
        """Whether a list holding `names` can be treated as complete."""
        slot = (env_id, key)
        if not names and isinstance(dockhand_total, int) and dockhand_total > 0:
            return False
        known = self._known.get(slot)
        # Nothing to compare against yet: an empty first list waits a poll.
        missing = {""} if known is None and not names else (known or set()) - names
        if missing and self._missing.get(slot) != missing:
            self._missing[slot] = missing
            return False
        self._known[slot] = names
        self._missing.pop(slot, None)
        return True


def _names(items: list, field: str) -> set[str]:
    return {str(i[field]) for i in items if isinstance(i, dict) and i.get(field)}


def _stats_total(stats: dict[str, Any], key: str) -> Any:
    return (stats.get(key) or {}).get("total")


def _pending_detail(has_update: bool, row: dict[str, Any]) -> dict[str, Any]:
    """One container's pending_update_details entry, from a pending-updates
    row or a check-updates result.

    Besides an installable update, Dockhand reports two that aren't:
    pinnedToDigest (1.0.54+) — the image is pinned to a digest whose tag has
    moved on, so the pin has to change — and releaseAgeRemainingHours
    (1.0.52+) — an update held back until the new image passes the minimum
    image age. Neither sets hasImageUpdate / hasUpdate.
    """
    hours = row.get("releaseAgeRemainingHours")
    return {
        "hasImageUpdate": has_update,
        "newerVersion": row.get("newerVersion") or None,
        "pinnedToDigest": bool(row.get("pinnedToDigest")),
        "releaseAgeRemainingHours": hours
        if isinstance(hours, int) and not isinstance(hours, bool) and hours > 0
        else None,
        # When Dockhand worked out the hours above; it doesn't update them
        # until its next check, so the countdown runs from here.
        "checkedAt": row.get("checkedAt"),
        # check-updates' own system-container classification, which can
        # catch one the containers list misses (see
        # helpers._is_system_container). pending-updates rows have none.
        **(
            {"systemContainer": row["systemContainer"]}
            if row.get("systemContainer")
            else {}
        ),
    }


# Dockhand's self-update check can only inspect its own container through
# an environment of one of these types (or its own socket/DOCKER_HOST); a
# Hawser environment never qualifies.
_SELF_UPDATE_CONNECTION_TYPES = frozenset({"socket", "direct"})

_SELF_UPDATE_SOURCE = "self-update"


def _dockhand_host_candidates(
    fast_data: dict[str, Any] | None,
) -> list[tuple[int, dict]]:
    """Dockhand's own container, in each environment through which Dockhand
    can reach it for /api/self-update/check. Empty means the check can't
    work (e.g. Dockhand only manages Hawser environments), so it's skipped."""
    out: list[tuple[int, dict]] = []
    for env_id, env in _all_envs(fast_data).items():
        # Dockhand treats a missing connection type as a socket.
        conn = (env.get("stats") or {}).get("connectionType")
        if conn and conn not in _SELF_UPDATE_CONNECTION_TYPES:
            continue
        for c in env.get("containers") or []:
            if (
                isinstance(c, dict)
                and c.get("id")
                and c.get("systemContainer") == "dockhand"
            ):
                out.append((env_id, c))
    return out


def _image_tag(image: str) -> str | None:
    name = image.split("@", 1)[0]
    last = name.rsplit("/", 1)[-1]
    return last.rsplit(":", 1)[1] if ":" in last else None


_SEMVER_PREFIX = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _version_bump(current_tag: str, new_tag: str) -> str | None:
    cur = _SEMVER_PREFIX.match(current_tag)
    new = _SEMVER_PREFIX.match(new_tag)
    if not cur or not new:
        return None
    for part, bump in zip((1, 2, 3), ("major", "minor", "patch"), strict=True):
        if int(new.group(part)) != int(cur.group(part)):
            return bump
    return None


def _self_update_newer_version(result: dict[str, Any]) -> dict[str, Any] | None:
    """A check-updates-style newerVersion for Dockhand's own container, from
    a self-update check that found a newer release for a version-tagged
    image. check-updates never reports one for a system container, so for
    a pinned Dockhand this is the only source. Its digest-based answer for
    a floating tag is ignored: check-updates already reports that one."""
    if not result.get("updateAvailable") or not result.get("latestVersion"):
        return None
    tag = _image_tag(str(result.get("newImage") or ""))
    if not tag:
        return None
    newer: dict[str, Any] = {"tag": tag, "source": _SELF_UPDATE_SOURCE}
    current = _image_tag(str(result.get("currentImage") or ""))
    bump = _version_bump(current, tag) if current else None
    if bump:
        newer["bump"] = bump
    return newer


class DockhandFastCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls 60s: dashboard stats, containers, stacks, container resource
    stats, pending update flags.

    Pending update flags are fetched for every environment, whether or
    not its scheduled update check (updateCheckEnabled) is on, and are
    not gated by CONF_ENABLE_PRECISE_UPDATES. This is what backs the
    update platform's baseline (digest-free) entities.
    CONF_ENABLE_PRECISE_UPDATES only controls whether the
    separate, opt-in DockhandUpdateCoordinator also runs (real registry
    queries) to layer precise digest-based versions onto those same
    entities.

    Shape: {
        "environments": {
            env_id: {
                "stats": {},
                "containers": [],
                "stacks": [],
                "container_stats": {name: {}},
                "stack_stats": {stack_name: {}} | None,
                "pending_update_container_ids": {container_id, ...},
                "pending_update_details": {
                    container_id: {
                        "hasImageUpdate": bool,
                        "newerVersion": {"tag": str, "bump": str,
                                         "skipped": [str, ...],
                                         "digest": str | None} | None,
                        "pinnedToDigest": bool,
                        "releaseAgeRemainingHours": int | None,
                        "checkedAt": str | None,
                    }
                },
            }
        }
    }

    pending_update_container_ids vs. pending_update_details: GET
    /api/containers/pending-updates?env=X (confirmed from Dockhand's own
    source, src/routes/api/containers/pending-updates/+server.ts) returns
    one row per container an update check persisted a record for — the
    scheduled job (env-update-check.ts, runEnvUpdateCheckJob) or a
    manual POST /api/containers/check-updates — and the scheduled job
    persists a row for the UNION of (a) containers
    with a real, actionable digest update (hasImageUpdate=True) and (b)
    containers with ONLY a semver "newer version tag" suggestion and no
    actionable digest update (hasImageUpdate=False, newerVersion still
    populated). Case (b) is advisory only (see update.py's module
    docstring on why Install must never be offered for it alone), so
    pending_update_details holds every row, for update.py to show
    newerVersion/hasImageUpdate per container, while
    pending_update_container_ids holds only the ids where hasImageUpdate
    is True: "pending" means "actionable" everywhere that set is used
    (the stack "pending updates" binary sensor, Update all's eligibility
    list, entity-cleanup gating and the Tier-1 "update-pending" state).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: DockhandClient,
        config: dict[str, Any],
        entry: ConfigEntry | None = None,
    ) -> None:
        self.client = client
        self._enable_resource_stats = bool(
            config.get(CONF_ENABLE_RESOURCE_STATS, DEFAULT_ENABLE_RESOURCE_STATS)
        )
        # Dockhand never persists a pending-updates row for a system
        # container (dockhand itself, Hawser) — both its scheduled check and
        # POST check-updates skip them when writing that table — so the only
        # update signal a system container ever gets is an on-demand
        # check-updates response. Kept here per env_id → container_id so the
        # next poll of pending-updates doesn't silently discard it. Keyed by
        # container id: once the container is recreated (updated), its new id
        # no longer matches and the stale result drops out on its own.
        self._system_check_results: dict[int, dict[str, dict]] = {}
        self._removal_guard = _RemovalGuard()
        self._full_poll_generation = 0
        # Per environment, when the fetch behind its current data started
        # (event-loop time), so a live event can tell whether that data
        # already reflects it.
        self._as_of: dict[int, float] = {}
        # Per environment: the refresh waiting to start, which any caller
        # arriving before it starts can share, and a lock so only one runs.
        self._queued_env_refresh: dict[int, asyncio.Task[None]] = {}
        self._env_refresh_locks: dict[int, asyncio.Lock] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_fast",
            update_interval=FAST_POLL_INTERVAL,
            config_entry=entry,
        )

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        # Retry on 401 before surfacing ConfigEntryAuthFailed. A single transient
        # 401 — e.g. during a brief Dockhand restart or Hawser connectivity hiccup —
        # would otherwise immediately prompt the user to re-authenticate with a
        # token that is still valid. Each entry in _AUTH_RETRY_DELAYS is how long
        # to sleep before that retry attempt; only after all retries are exhausted
        # do we conclude the token is genuinely invalid and surface the re-auth
        # dialog. Non-auth exceptions (network errors, 5xx, ...) still propagate
        # immediately as UpdateFailed — no retry needed there, they don't trigger
        # re-auth anyway.
        _total_attempts = len(_AUTH_RETRY_DELAYS) + 1
        started = self.hass.loop.time()
        last_auth_err: DockhandAuthError | None = None
        result: dict[str, Any] | None = None

        for attempt, delay_before in enumerate((None, *_AUTH_RETRY_DELAYS), start=1):
            if delay_before is not None:
                _LOGGER.warning(
                    "Dockhand: 401 on attempt %d of %d — waiting %ds before retry "
                    "(may be a transient Dockhand restart rather than a revoked token)",
                    attempt - 1,
                    _total_attempts,
                    delay_before,
                )
                await asyncio.sleep(delay_before)
            try:
                result = await self._fetch()
                if last_auth_err is not None:
                    _LOGGER.info(
                        "Dockhand: authentication recovered on attempt %d of %d "
                        "— token is still valid",
                        attempt,
                        _total_attempts,
                    )
                break
            except DockhandAuthError as err:
                last_auth_err = err
            except Exception as err:
                raise UpdateFailed(f"Fast data error: {err}") from err
        else:
            # Every attempt returned 401 — the token is genuinely invalid or
            # revoked. Surface re-auth so the user can fix it.
            _LOGGER.error(
                "Dockhand: 401 persisted across all %d attempt(s) — surfacing "
                "re-auth. If re-entering the same token immediately resolves it, "
                "this was a transient auth issue; consider filing a report with "
                "your Dockhand logs from around this time.",
                _total_attempts,
            )
            raise ConfigEntryAuthFailed(
                "Dockhand API token is invalid or was revoked. "
                "Go to Settings → Devices & Services → Dockhand → Re-authenticate."
            ) from last_auth_err

        # stats_source is this coordinator's own result — unlike the slow
        # coordinator, which needs the fast coordinator's data to look up
        # environment names, the fast coordinator's own data already has
        # them.
        assert result is not None  # loop always breaks or raises above
        self._full_poll_generation += 1
        self._as_of = dict.fromkeys(_all_envs(result), started)
        _sync_fetch_issues(self.hass, self.config_entry, "fast", result, result)
        return result

    async def _fetch(self) -> dict[str, Any]:
        # Stats for all environments in a single API call, which is also
        # the list of environments: unlike /api/environments, it doesn't
        # return decrypted secrets (tlsKey/hawserToken; see diagnostics.py).
        #
        # A failure here must raise, never become an empty successful
        # result: that would read as every environment losing all its
        # stacks and containers (docs/architecture.md §3). Auth failures
        # propagate for _async_update_data's re-auth handling.
        try:
            all_stats_list = _safe_list(
                await self.client.async_get_all_dashboard_stats()
            )
        except DockhandAuthError:
            raise
        except Exception as err:
            raise UpdateFailed(
                f"Could not reach Dockhand for dashboard stats: {err}"
            ) from err
        all_stats: dict[int, dict] = {
            s["id"]: s for s in all_stats_list if isinstance(s, dict) and "id" in s
        }

        out: dict[int, dict] = {}
        for result in await asyncio.gather(
            *[self._fetch_env(env_id, stats) for env_id, stats in all_stats.items()],
            return_exceptions=True,
        ):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                _LOGGER.warning("Dockhand fast env error: %s", result)
            else:
                env_id, data = result
                out[env_id] = data
        # Wrapped in "environments", matching the slow and update
        # coordinators' own shape — all three now share one access
        # pattern via _coordinator_env()/_all_envs() (helpers.py), and
        # this coordinator has somewhere to put any future hub-level
        # (non-per-environment) data without another reshape.
        return {"environments": out}

    async def _fetch_env(self, env_id: int, stats: dict[str, Any]) -> tuple[int, dict]:
        # Named tasks rather than a positionally-indexed list, so an
        # optional call can't shift the position of the ones after it.
        # pending-updates is fetched whether or not the environment's
        # scheduled update check is on: manual checks in Dockhand and
        # this integration's own check-updates calls write the same
        # rows, and Dockhand's UI shows them either way.
        tasks: dict[str, Any] = {
            "containers": self.client.async_get_containers(env_id),
            "stacks": self.client.async_get_stacks(env_id),
            "pending_updates": self.client.async_get_pending_updates(env_id),
        }
        if self._enable_resource_stats:
            tasks["container_stats"] = self.client.async_get_container_stats(env_id)
            tasks["stack_stats"] = self.client.async_get_stack_stats(env_id)

        results = dict(
            zip(
                tasks.keys(),
                await asyncio.gather(*tasks.values(), return_exceptions=True),
                strict=True,
            )
        )

        # Same tracking as the slow coordinator's per-environment fetches
        # (docs/architecture.md §9), with the most at stake: a failed
        # containers or stacks fetch must not read as "this environment has
        # none", or cleanup would remove every container and stack device
        # of an environment that's still online.
        failures: set[str] = set()

        # Index container stats by name for O(1) lookup from sensor entities.
        # Stopped/exited containers are absent from the stats response — their
        # sensors will return None (unavailable) until the container is running.
        # Empty (not fetched at all) whenever "Enable container and stack
        # stats" is off — nothing consumes it in that case, so there's no
        # reason to pay for the API call every 60s just to throw it away.
        container_stats: dict[str, dict] = {}
        if "container_stats" in results:
            raw_stats = _safe_list(
                _unwrap(
                    results["container_stats"],
                    [],
                    f"container_stats env={env_id}",
                    failures,
                    "container_stats",
                )
            )
            container_stats = {
                s["name"]: s for s in raw_stats if isinstance(s, dict) and "name" in s
            }

        # Dockhand's own per-stack totals (1.0.52+). None means "no stack
        # stats here": not fetched (container stats off), or a Dockhand
        # too old to have the endpoint (404 — checked every poll, so an
        # upgrade is picked up without a reload, at the cost of one
        # cheap 404). A real failure is recorded in `failures` instead,
        # so cleanup can tell it apart from the endpoint not existing.
        stack_stats: dict[str, dict] | None = None
        if "stack_stats" in results:
            raw = results["stack_stats"]
            if isinstance(raw, DockhandNotFoundError):
                _LOGGER.debug(
                    "Dockhand: no stack stats for env=%s (needs Dockhand 1.0.52+)",
                    env_id,
                )
            else:
                raw_list = _unwrap(
                    raw, None, f"stack_stats env={env_id}", failures, "stack_stats"
                )
                if raw_list is not None:
                    stack_stats = {
                        s["name"]: s
                        for s in _safe_list(raw_list)
                        if isinstance(s, dict) and "name" in s
                    }

        # pending_update_details keeps EVERY row from pending-updates —
        # both actionable (hasImageUpdate=True) and semver-advisory-only
        # (hasImageUpdate=False, newerVersion populated) — since
        # update.py's Tier-1 merge needs newerVersion even when there's
        # no actionable update to go with it. pending_update_container_ids
        # is then rebuilt from only the actionable subset — see this
        # coordinator's own docstring above ("pending_update_container_ids
        # vs. pending_update_details") for why the two must not be the
        # same set.
        pending_update_details: dict[str, dict] = {}
        pending_update_container_ids: set[str] = set()
        if "pending_updates" in results:
            pending = _safe_list(
                _unwrap(
                    results["pending_updates"],
                    [],
                    f"pending_updates env={env_id}",
                    failures,
                    "pending_updates",
                )
            )
            for p in pending:
                if not isinstance(p, dict) or not p.get("containerId"):
                    continue
                container_id = p["containerId"]
                has_image_update = bool(p.get("hasImageUpdate"))
                pending_update_details[container_id] = _pending_detail(
                    has_image_update, p
                )
                if has_image_update:
                    pending_update_container_ids.add(container_id)

        containers = _safe_list(
            _unwrap(
                results["containers"],
                [],
                f"containers env={env_id}",
                failures,
                "containers",
            )
        )
        stacks = _safe_list(
            _unwrap(
                results["stacks"],
                [],
                f"stacks env={env_id}",
                failures,
                "stacks",
            )
        )
        unconfirmed: set[str] = {
            key
            for key, items in (("containers", containers), ("stacks", stacks))
            if key not in failures
            and not self._removal_guard.confirmed(
                env_id, key, _names(items, "name"), _stats_total(stats, key)
            )
        }
        self._apply_system_check_results(
            env_id,
            containers,
            "containers" in failures or "containers" in unconfirmed,
            pending_update_details,
            pending_update_container_ids,
        )
        return env_id, {
            "stats": stats,
            "containers": containers,
            "stacks": stacks,
            "container_stats": container_stats,
            "stack_stats": stack_stats,
            "pending_update_container_ids": pending_update_container_ids,
            "pending_update_details": pending_update_details,
            # Checked by __init__.py's _build_live_sets before an empty
            # list counts as grounds for cleanup. Unconfirmed emptiness
            # isn't a failure, so it raises no repair issue.
            "fetch_failures": failures,
            "unconfirmed": unconfirmed,
        }

    async def async_refresh_environment(self, env_id: int) -> None:
        """Re-fetch one environment's containers, stacks and update flags,
        for an action or a Dockhand event that only touched that one.

        Dockhand's per-environment totals stay as the last full poll left
        them. The scheduled poll isn't pushed back (async_set_updated_data
        would do that), so a busy environment can't starve the full poll.
        A full poll that finishes while this runs wins.

        Concurrent callers share fetches: while one refresh runs, every
        caller that arrives joins the single refresh queued behind it,
        which starts after all of them, so each still sees its own change.
        One service call on ten containers (HA runs them concurrently)
        costs two refreshes instead of ten.
        """
        task = self._queued_env_refresh.get(env_id)
        if task is None:
            # Not eager: the task must stay queued until this caller has
            # registered it, or a later caller could join a refresh that
            # started before its action finished.
            task = self.hass.async_create_task(
                self._async_run_queued_refresh(env_id),
                f"dockhand refresh environment {env_id}",
                eager_start=False,
            )
            self._queued_env_refresh[env_id] = task
        await asyncio.shield(task)

    async def _async_run_queued_refresh(self, env_id: int) -> None:
        lock = self._env_refresh_locks.setdefault(env_id, asyncio.Lock())
        async with lock:
            # From here the fetch is under way, so later callers queue
            # another.
            self._queued_env_refresh.pop(env_id, None)
            await self._async_refresh_environment_now(env_id)

    async def _async_refresh_environment_now(self, env_id: int) -> None:
        current = _coordinator_env(self.data, env_id)
        if not current:
            return
        generation = self._full_poll_generation
        started = self.hass.loop.time()
        _, env_data = await self._fetch_env(env_id, current.get("stats") or {})
        if generation != self._full_poll_generation:
            return
        self._as_of[env_id] = started
        environments = dict(_all_envs(self.data))
        environments[env_id] = env_data
        self.data = {**self.data, "environments": environments}
        self.async_update_listeners()

    def fetched_since(self, env_id: int, when: float) -> bool:
        """Whether an environment's current data comes from a fetch that
        started after `when` (event-loop time)."""
        return self._as_of.get(env_id, float("-inf")) > when

    def _apply_system_check_results(
        self,
        env_id: int,
        containers: list[dict],
        containers_failed: bool,
        pending_update_details: dict[str, dict],
        pending_update_container_ids: set[str],
    ) -> None:
        """Overlay the last on-demand check's system-container results onto
        a freshly polled environment, pruning any whose container id no
        longer exists (see self._system_check_results)."""
        stored = self._system_check_results.get(env_id)
        if not stored:
            return
        if not containers_failed:
            live_ids = {c.get("id") for c in containers}
            stored = {cid: d for cid, d in stored.items() if cid in live_ids}
            self._system_check_results[env_id] = stored
        for container_id, detail in stored.items():
            pending_update_details[container_id] = dict(detail)
            if detail.get("hasImageUpdate"):
                pending_update_container_ids.add(container_id)

    def async_merge_pending_updates_from_check(
        self, env_id: int, items: list[dict]
    ) -> None:
        """Merge a fresh Tier 1 pending-update signal for one environment,
        obtained from an on-demand real registry check (the env-level
        "Check for updates" button, DockhandCheckUpdatesButton), directly
        into this coordinator's existing data — without waiting for this
        environment's next scheduled 60s poll.

        `items` is the raw list POST /api/containers/check-updates?env=X
        returns (client.async_check_container_updates's own return shape):
        per-item {containerId, containerName, imageName, hasUpdate,
        currentDigest, newDigest, systemContainer, updateDisabled,
        newerVersion?} — the same shape button.py already has in hand
        after firing the check itself, so it can hand it here directly
        instead of building an id-only set that would lose newerVersion
        and digests.

        Rebuilds both pending_update_container_ids and
        pending_update_details for this environment from `items`, mirroring
        exactly how the periodic 60s poll (_fetch_env above) builds them
        from pending-updates — hasUpdate is check-updates' own name for the
        same "actionable digest update" concept pending-updates calls
        hasImageUpdate, so it's mapped the same way: only items with
        hasUpdate=True contribute to pending_update_container_ids, while
        pending_update_details keeps every item (actionable or
        semver-only) so its newerVersion still reaches update.py's merge
        even when hasUpdate is False.

        Uses async_set_updated_data() rather than a full refresh, same
        reasoning as DockhandUpdateCoordinator.async_check_environment():
        replaces just these two fields for this one environment, leaves
        every other environment and every other field of this
        environment's data untouched, and notifies listeners without
        triggering a full refresh of anything else.

        A no-op if this coordinator has no data yet for the environment
        (e.g. it's offline, or this coordinator hasn't completed its own
        first refresh yet) — nothing safe to merge into in that case;
        the next successful poll will populate it normally instead.
        """
        environments = dict(_all_envs(self.data))
        env_data = environments.get(env_id)
        if not env_data:
            return

        pending_update_details: dict[str, dict] = {}
        pending_update_container_ids: set[str] = set()
        system_results: dict[str, dict] = {}
        for item in items:
            container_id = item.get("containerId")
            if not container_id:
                continue
            has_update = bool(item.get("hasUpdate"))
            pending_update_details[container_id] = _pending_detail(has_update, item)
            if has_update:
                pending_update_container_ids.add(container_id)
            if item.get("systemContainer") and has_update:
                system_results[container_id] = pending_update_details[container_id]
        self._system_check_results[env_id] = {
            cid: dict(d) for cid, d in system_results.items()
        }

        new_env_data = dict(env_data)
        new_env_data["pending_update_container_ids"] = pending_update_container_ids
        new_env_data["pending_update_details"] = pending_update_details
        environments[env_id] = new_env_data
        self.async_set_updated_data({"environments": environments})


class DockhandSlowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls 600s: images, volumes, networks, schedules, runtime controls
    (all opt-in), git stacks/host/auto_update_settings/env_meta (always —
    cheap bulk calls, not gated), recent_events (gated on collectActivity),
    vulnerabilities (gated on scannerEnabled).

    env_meta (imagePruneEnabled, hawserAgentName/Id/LastSeen) is the one
    thing still sourced from /api/environments — the only endpoint with
    these fields. Extracted immediately into a clean per-env dict
    (env_meta below); the raw response — which includes tlsKey/hawserToken
    fully decrypted with no redaction on Dockhand's side — is never stored.
    Still not used for environment enumeration (that stays derived from
    the fast coordinator's data, per DockhandFastCoordinator).

    Shape: {
        "environments": {
            env_id: {
                "host": {}, "images": [], "networks": [],
                "volumes": [], "runtime_config": {container_name: {...}},
                "git_stacks": [], "auto_update_settings": {container_name: {...}},
                "recent_events": [{"containerName", "action", "timestamp", ...}],
                "vulnerabilities": {"total", "critical", "high", "medium",
                                    "low", "imagesScanned", "totalImages"},
                "env_meta": {"imagePruneEnabled": bool, "hawserAgentName": str|None,
                             "hawserAgentId": str|None, "hawserLastSeen": str|None,
                             "connectionHost": str|None, "connectionPort": int|None},
                # Which of this env's resource fetches failed this cycle
                # (a subset of the keys above) rather than genuinely being
                # empty — e.g. {"images"} means the images fetch itself
                # failed, not that this env has zero images. See _unwrap's
                # own doc comment; checked by __init__.py's
                # _build_live_sets before trusting an empty result as
                # grounds for cleanup. Empty set on a fully successful
                # fetch, same as every list/dict field above being empty
                # on a genuinely-empty environment.
                "fetch_failures": set(),
            }
        },
        "schedules": [],
        # Same idea as each environment's own "fetch_failures", for the
        # two top-level (not per-environment) fetches: {"environments"}
        # and/or {"schedules"}.
        "fetch_failures": set(),
    }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: DockhandClient,
        config: dict[str, Any],
        fast_coordinator: DockhandFastCoordinator,
        entry: ConfigEntry | None = None,
    ) -> None:
        self.client = client
        self._fast_coordinator = fast_coordinator
        self._enable_schedules = bool(config.get(CONF_ENABLE_SCHEDULES, False))
        self._enable_images = bool(config.get(CONF_ENABLE_IMAGES, False))
        self._enable_volumes = bool(config.get(CONF_ENABLE_VOLUMES, False))
        self._enable_networks = bool(config.get(CONF_ENABLE_NETWORKS, False))
        self._enable_runtime_controls = bool(
            config.get(CONF_ENABLE_RUNTIME_CONTROLS, False)
        )
        self._removal_guard = _RemovalGuard()
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_slow",
            update_interval=SLOW_POLL_INTERVAL,
            config_entry=entry,
        )

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            result = await self._fetch()
        except DockhandAuthError as err:
            # Let the fast coordinator own reauth — just surface as transient failure.
            raise UpdateFailed(
                "API token rejected — fast coordinator will surface reauth"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Slow data error: {err}") from err
        _sync_fetch_issues(
            self.hass, self.config_entry, "slow", result, self._fast_coordinator.data
        )
        return result

    async def _fetch(self) -> dict[str, Any]:
        # Which environments exist still comes from the fast coordinator's
        # data, not from this call — fast completes its first refresh
        # before we do ours (see __init__.py setup order), so this is
        # reliably populated by the time we need it, and it means this
        # coordinator's environment enumeration doesn't depend on
        # /api/environments succeeding.
        env_ids = list(_all_envs(self._fast_coordinator.data).keys())

        # /api/environments is the only source for imagePruneEnabled and
        # the Hawser agent identity fields (agent_name/agent_id/last_seen)
        # — confirmed from Dockhand's source, no other endpoint has them.
        # It also returns tlsKey/hawserToken fully decrypted with no
        # redaction on Dockhand's side, so we extract only the four
        # fields we actually want immediately below and never store the
        # raw response — env_meta (not the raw list) is what ends up in
        # coordinator.data.
        top_coros: list = [self.client.async_get_environments()]
        if self._enable_schedules:
            top_coros.append(self.client.async_get_schedules())
        top_results = await asyncio.gather(*top_coros, return_exceptions=True)

        # /api/environments is the one call here that explicitly
        # propagates auth errors (unconditionally fetched every poll,
        # unlike schedules) — everything else is gathered with
        # return_exceptions=True and just logged.
        if isinstance(top_results[0], DockhandAuthError):
            raise top_results[0]

        top_failures: set[str] = set()
        env_meta: dict[int, dict] = {}
        envs_raw = _unwrap(
            top_results[0], [], "environments", top_failures, "environments"
        )
        if isinstance(envs_raw, list):
            for e in envs_raw:
                if isinstance(e, dict) and e.get("id") is not None:
                    env_meta[e["id"]] = {
                        "imagePruneEnabled": bool(e.get("imagePruneEnabled")),
                        "hawserAgentName": e.get("hawserAgentName"),
                        "hawserAgentId": e.get("hawserAgentId"),
                        "hawserLastSeen": e.get("hawserLastSeen"),
                        # Named connectionHost/connectionPort, not host/port,
                        # to avoid colliding with the per-env "host" key
                        # below (the *other* /api/host response dict) —
                        # this is the Docker daemon connection endpoint
                        # (environments.host/port DB columns), an
                        # unrelated concept that happens to share a name.
                        "connectionHost": e.get("host"),
                        "connectionPort": e.get("port"),
                    }

        schedules = (
            _safe_list(
                _unwrap(top_results[1], [], "schedules", top_failures, "schedules")
            )
            if self._enable_schedules and len(top_results) > 1
            else []
        )

        async def _fetch_runtime_config(env_id: int) -> dict[str, dict]:
            """Current Memory/NanoCpus/PidsLimit/RestartPolicy for every
            stack-less container in an environment.

            Two-phase: list containers, then inspect each stack-less one.
            A per-container inspect failure is logged and that container is
            simply omitted (its number/select entities read as unknown)
            rather than failing the whole environment's slow poll.
            """
            containers = _safe_list(await self.client.async_get_containers(env_id))
            stackless = [c for c in containers if not _compose_project(c)]
            inspected = await asyncio.gather(
                *[
                    self.client.async_get_container_inspect(env_id, c["id"])
                    for c in stackless
                ],
                return_exceptions=True,
            )
            result: dict[str, dict] = {}
            for c, data in zip(stackless, inspected, strict=False):
                name = c.get("name", "")
                if isinstance(data, Exception):
                    _LOGGER.warning(
                        "Dockhand: error inspecting container '%s' env=%s: %s",
                        name,
                        env_id,
                        data,
                    )
                    continue
                if isinstance(data, dict) and name:
                    result[name] = _extract_runtime_config(data)
            return result

        async def _fetch_env(env_id: int) -> tuple[int, dict]:
            # Build a named mapping of coroutines so result indexing is
            # explicit rather than fragile positional arithmetic.
            named: dict[str, Any] = {}
            if self._enable_images:
                named["images"] = self.client.async_get_images(env_id)
            if self._enable_networks:
                named["networks"] = self.client.async_get_networks(env_id)
            if self._enable_volumes:
                named["volumes"] = self.client.async_get_volumes(env_id)
            if self._enable_runtime_controls:
                named["runtime_config"] = _fetch_runtime_config(env_id)
            # Both flags below live on the same per-env "stats" blob (the
            # fast coordinator's dashboard-stats data), fetched once here
            # rather than repeating the same lookup chain twice. Every
            # level uses `or {}`, not a dict.get(key, {}) default — the
            # latter only substitutes for an *absent* key, not one Dockhand
            # sends with an explicit null (docs/architecture.md §6,
            # github.com/raetha/ha-dockhand/issues/20).
            env_stats = (
                _coordinator_env(self._fast_coordinator.data, env_id).get("stats") or {}
            )
            # Gated on collectActivity (the fast coordinator's per-env
            # dashboard-stats flag) rather than a separate CONF_ option —
            # if Dockhand isn't collecting activity for this environment,
            # querying its event list would just return nothing every
            # 600s for no reason. No setup required beyond what the user
            # already configured in Dockhand itself, same reasoning as
            # the update platform's Tier 1 entities.
            if bool(env_stats.get("collectActivity")):
                named["recent_events"] = self.client.async_get_recent_activity(
                    env_id, limit=10
                )
            # Same reasoning as recent_events: gated on Dockhand's own
            # scannerEnabled flag rather than a separate CONF_ option, and
            # cheap regardless (Dockhand serves this from its own cache,
            # not a fresh scan — see api.py).
            if bool(env_stats.get("scannerEnabled")):
                named["vulnerabilities"] = self.client.async_get_vulnerabilities_count(
                    env_id
                )
            # Always fetched: a single bulk call per environment (not
            # per-container/per-stack like runtime controls), so there's no
            # meaningful API cost to gate. Entities are only created for
            # stacks that actually appear in this list — i.e. automatically
            # whenever a stack is detected as git-tracked, no separate
            # opt-in needed.
            named["git_stacks"] = self.client.async_get_git_stacks(env_id)
            # Always fetched: one bulk call per environment, cheap, and
            # (unlike runtime controls) does not scale with container count.
            named["auto_update_settings"] = self.client.async_get_auto_update_settings(
                env_id
            )
            # Always fetched: GET /api/host is the only reliable source for
            # hawserVersion on hawser-standard connections, which live-fetch
            # from the agent on every call.
            named["host"] = self.client.async_get_host_info(env_id)

            results: dict[str, Any] = {}
            failures: set[str] = set()
            if named:
                keys = list(named)
                gathered = await asyncio.gather(*named.values(), return_exceptions=True)
                for key, val in zip(keys, gathered, strict=False):
                    if key == "host":
                        unwrapped = _unwrap(
                            val, {}, f"host env={env_id}", failures, "host"
                        )
                        results["host"] = (
                            unwrapped if isinstance(unwrapped, dict) else {}
                        )
                    elif key == "runtime_config":
                        unwrapped = _unwrap(
                            val,
                            {},
                            f"runtime_config env={env_id}",
                            failures,
                            "runtime_config",
                        )
                        results["runtime_config"] = (
                            unwrapped if isinstance(unwrapped, dict) else {}
                        )
                    elif key == "auto_update_settings":
                        unwrapped = _unwrap(
                            val,
                            {},
                            f"auto_update_settings env={env_id}",
                            failures,
                            "auto_update_settings",
                        )
                        results["auto_update_settings"] = (
                            unwrapped if isinstance(unwrapped, dict) else {}
                        )
                    elif key == "recent_events":
                        unwrapped = _unwrap(
                            val,
                            {},
                            f"recent_events env={env_id}",
                            failures,
                            "recent_events",
                        )
                        events = (
                            unwrapped.get("events")
                            if isinstance(unwrapped, dict)
                            else None
                        )
                        results["recent_events"] = (
                            events if isinstance(events, list) else []
                        )
                    elif key == "vulnerabilities":
                        unwrapped = _unwrap(
                            val,
                            {},
                            f"vulnerabilities env={env_id}",
                            failures,
                            "vulnerabilities",
                        )
                        summary = (
                            unwrapped.get("summary")
                            if isinstance(unwrapped, dict)
                            else None
                        )
                        results["vulnerabilities"] = (
                            summary if isinstance(summary, dict) else {}
                        )
                    else:
                        results[key] = _safe_list(
                            _unwrap(val, [], f"{key} env={env_id}", failures, key)
                        )

            unconfirmed: set[str] = set()
            if (
                "images" in results
                and "images" not in failures
                and not self._removal_guard.confirmed(
                    env_id,
                    "images",
                    _names(results["images"], "id"),
                    _stats_total(env_stats, "images"),
                )
            ):
                unconfirmed.add("images")

            return env_id, {
                "host": results.get("host", {}),
                "images": results.get("images", []),
                "networks": results.get("networks", []),
                "volumes": results.get("volumes", []),
                "runtime_config": results.get("runtime_config", {}),
                "git_stacks": results.get("git_stacks", []),
                "auto_update_settings": results.get("auto_update_settings", {}),
                "recent_events": results.get("recent_events", []),
                "vulnerabilities": results.get("vulnerabilities", {}),
                "env_meta": env_meta.get(env_id, {}),
                # See the fast coordinator's matching keys.
                "fetch_failures": failures,
                "unconfirmed": unconfirmed,
            }

        environments: dict[int, dict] = {}
        for result in await asyncio.gather(
            *[_fetch_env(env_id) for env_id in env_ids], return_exceptions=True
        ):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                _LOGGER.warning("Dockhand slow env error: %s", result)
            else:
                env_id, data = result
                environments[env_id] = data
        return {
            "environments": environments,
            "schedules": schedules,
            # Which top-level (not per-environment) fetches failed this
            # cycle — currently just "environments" and "schedules", the
            # only two fetched via top_coros above. See _unwrap's own doc
            # comment for why this exists at all.
            "fetch_failures": top_failures,
        }


def _sync_fetch_issues(
    hass: HomeAssistant,
    config_entry: ConfigEntry | None,
    source: str,
    result: dict[str, Any],
    stats_source: dict[str, Any],
) -> None:
    """Create or clear a HA repair issue for each fetch failure this
    cycle — the "place to go" for a real, reported gap: _unwrap()
    already logs a warning when a fetch fails, but a warning in the
    log is easy to miss entirely, and gives no indication after the
    fact that anything's still degraded. An issue in Settings ->
    System -> Repairs is what actually answers "why is this entity
    unavailable" — it's there for as long as the problem persists,
    and clears itself the moment a poll succeeds again, so it never
    needs cleaning up by hand and never lingers past being useful.

    Shared between DockhandFastCoordinator and DockhandSlowCoordinator
    (called from each one's own _async_update_data) rather than a
    method on either — both need the exact same logic, just against
    their own data shape. `source` ("fast"/"slow") disambiguates issue
    ids between them so a failure in one doesn't silently overwrite or
    clear an unrelated one already raised by the other for the same
    environment. `stats_source` is whichever coordinator's data
    actually has each environment's display name in its own "stats"
    key — the fast coordinator's own result for the fast coordinator's
    calls, or the fast coordinator's already-populated data for the
    slow coordinator's calls (since slow's own result doesn't carry
    names at all).

    One issue for top-level failures (schedules/environments — not
    tied to any one environment; never fires for the fast coordinator,
    which has no top-level fetch of its own with this problem — see
    docs/architecture.md §9 on why dashboard-stats already raises
    correctly instead of needing this), one per environment for the
    rest — not one issue per resource per environment, which would
    mean up to 9 issues per environment during a broad outage; a
    single per-environment issue listing every currently-failing
    resource in its own description is both less noisy and, if
    several resources are failing together (e.g. the whole environment
    briefly unreachable), a clearer picture of what's actually going
    on than a wall of near-identical individual issues would be.

    No config_entry means this coordinator was constructed without
    one (only ever true in tests) — skip silently rather than raising
    on a null config_entry, since issue tracking has nothing
    meaningful to attach itself to in that case anyway.
    """
    if config_entry is None:
        return
    entry_id = config_entry.entry_id
    stats_envs = _all_envs(stats_source)

    top_failures: set[str] = result.get("fetch_failures") or set()
    top_issue_id = f"{entry_id}_fetch_failed_top_level_{source}"
    if top_failures:
        ir.async_create_issue(
            hass,
            DOMAIN,
            top_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="fetch_failed_top_level",
            translation_placeholders={"resources": ", ".join(sorted(top_failures))},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, top_issue_id)

    for env_id, env_data in _all_envs(result).items():
        env_failures: set[str] = env_data.get("fetch_failures") or set()
        issue_id = f"{entry_id}_fetch_failed_env_{env_id}_{source}"
        if env_failures:
            env_name = (
                (stats_envs.get(env_id) or {})
                .get("stats", {})
                .get("name", f"Environment {env_id}")
            )
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="fetch_failed_env",
                translation_placeholders={
                    "env_name": env_name,
                    "resources": ", ".join(sorted(env_failures)),
                },
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


class DockhandUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls for container image update availability — Tier 2 only.

    Default interval: 86400s (24 hours). Only created when the user enables
    CONF_ENABLE_PRECISE_UPDATES ("Enable precise update versions" in Configure).
    This is purely additive to the update platform, which is always active
    on its own (see update.py's module docstring) — this coordinator just
    layers precise digest-based version numbers onto those already-existing
    entities. Each poll calls POST /api/containers/check-updates for every
    environment, which performs real registry queries — deliberately
    infrequent to avoid bogging down the Docker host.

    Requires a reference to the fast coordinator so it can reuse the already-
    fetched environment list rather than making a redundant API call.

    Data shape:
        {
            "environments": {
                env_id: {
                    container_id: {
                        "containerName": str,
                        "imageName": str,
                        "hasUpdate": bool,
                        "currentDigest": str,
                        "newDigest": str,          # only present when hasUpdate=True
                        "systemContainer": str | None,
                        "updateDisabled": bool,
                    }
                }
            }
        }

    Dockhand's own container also gets a newerVersion (marked
    "source": "self-update") from GET /api/self-update/check when Dockhand
    runs a version tag with a newer release out, since check-updates never
    reports one for a system container. That check is only made when
    Dockhand's container is visible in a socket or direct environment
    (_dockhand_host_candidates); through Hawser alone it always fails.

    Wrapped in "environments" to match the fast and slow coordinators'
    shape exactly — all three are now structurally identical, even though
    this one has no second, non-per-environment concern the way slow's
    "schedules" does. Done so a single generic accessor
    (_coordinator_env() in helpers.py) works for all three without
    needing to know which coordinator it's reading from.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: DockhandClient,
        fast_coordinator: DockhandFastCoordinator,
        config: dict[str, Any],
        entry: ConfigEntry | None = None,
    ) -> None:
        self.client = client
        self._fast = fast_coordinator
        # {"env_id", "container_id", "newerVersion"} from the last self-update
        # check that found a newer release, else None. Keyed by container id,
        # so it stops applying once Dockhand's container is recreated.
        self._self_update: dict[str, Any] | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_updates",
            update_interval=PRECISE_UPDATES_POLL_INTERVAL,
            config_entry=entry,
        )

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        # Never fails as a whole: each environment's failure (a rejected token
        # included, which the fast coordinator surfaces as re-auth) only keeps
        # that environment's last result — see _fetch().
        return await self._fetch()

    async def _fetch_one_env(self, env_id: int) -> dict[str, dict]:
        """Fetch and index one environment's pending updates. Raises on
        failure — callers decide how to handle that (see _fetch()'s
        resilient wrapping below vs. async_check_environment()'s
        let-it-raise-to-the-button approach)."""
        results = await self.client.async_check_container_updates(env_id)
        # Index by container ID for O(1) lookup by update entities.
        return {
            item["containerId"]: item for item in results if item.get("containerId")
        }

    async def _fetch(self) -> dict[str, Any]:
        # Reuse the fast coordinator's environment list — it is always fresher
        # than making a separate async_get_environments() call and avoids a
        # redundant API round trip on every update check.
        env_ids = list(_all_envs(self._fast.data).keys())

        async def _fetch_env_resilient(env_id: int) -> tuple[int, dict[str, dict]]:
            try:
                return env_id, await self._fetch_one_env(env_id)
            except Exception as exc:
                # Don't let a transient failure (e.g. Dockhand unreachable)
                # look like "confirmed zero pending updates" — that would
                # flip every container's update entity in this environment
                # to "up to date" when we simply don't know right now.
                # Keep whatever we already had for this environment instead
                # (same "last known good, not a false empty" principle as
                # the fast/slow coordinators — see architecture.md §3). This
                # resilience is deliberately only here, in the background
                # periodic-refresh path — async_check_environment() below
                # (the explicit per-button user action) lets the same
                # exception raise instead, so a press that fails actually
                # tells the user it failed rather than looking like nothing
                # happened.
                _LOGGER.warning(
                    "Dockhand: update check for env %s raised: %s", env_id, exc
                )
                return env_id, _coordinator_env(self.data, env_id)

        out: dict[int, dict] = {}
        for result in await asyncio.gather(
            *[_fetch_env_resilient(env_id) for env_id in env_ids],
            return_exceptions=True,
        ):
            if isinstance(result, BaseException):
                # Only a cancellation gets here: _fetch_env_resilient
                # handles every Exception itself.
                raise result
            else:
                env_id, data = result
                out[env_id] = data
        await self._refresh_self_update()
        return {"environments": self._with_self_update(out)}

    @property
    def self_update(self) -> dict[str, Any] | None:
        """The newer Dockhand release found by the last self-update check,
        with the environment and container it applies to, or None."""
        return dict(self._self_update) if self._self_update else None

    async def _refresh_self_update(self, env_id: int | None = None) -> bool:
        """Re-run Dockhand's self-update check when it can work. With
        `env_id`, only when Dockhand's container is in that environment.
        Returns whether a check completed. Every failure (no Docker access,
        a non-admin token, Dockhand unreachable) is silent: it only means
        there's nothing to show."""
        candidates = _dockhand_host_candidates(self._fast.data)
        if env_id is not None and all(e != env_id for e, _ in candidates):
            return False
        if not candidates:
            self._self_update = None
            return False
        try:
            result = await self.client.async_check_self_update()
        except Exception as err:
            # Keep the last result: an unreachable Dockhand says nothing new.
            _LOGGER.debug("Dockhand: self-update check raised: %s", err)
            return False
        if result.get("error"):
            _LOGGER.debug("Dockhand: self-update check: %s", result["error"])

        host: tuple[int, dict] | None = None
        if len(candidates) == 1:
            host = candidates[0]
        else:
            named = [
                c for c in candidates if c[1].get("name") == result.get("containerName")
            ]
            host = named[0] if len(named) == 1 else None

        newer = _self_update_newer_version(result)
        self._self_update = (
            {"env_id": host[0], "container_id": host[1]["id"], "newerVersion": newer}
            if host and newer
            else None
        )
        return True

    def _with_self_update(self, environments: dict[int, dict]) -> dict[int, dict]:
        """`environments` with the self-update result applied to Dockhand's
        own container row, replacing any earlier one. Never overrides a
        newerVersion that check-updates itself reported."""
        out: dict[int, dict] = {}
        for env_id, rows in environments.items():
            stale = [
                cid
                for cid, row in rows.items()
                if isinstance(row, dict)
                and (row.get("newerVersion") or {}).get("source") == _SELF_UPDATE_SOURCE
            ]
            if stale:
                rows = dict(rows)
                for cid in stale:
                    rows[cid] = {**rows[cid], "newerVersion": None}
            out[env_id] = rows

        su = self._self_update
        if not su:
            return out
        rows = out.get(su["env_id"]) or {}
        row = rows.get(su["container_id"])
        if not isinstance(row, dict) or row.get("newerVersion"):
            return out
        out[su["env_id"]] = {
            **rows,
            su["container_id"]: {**row, "newerVersion": dict(su["newerVersion"])},
        }
        return out

    async def async_refresh_self_update(self, env_id: int) -> None:
        """Re-run the self-update check after an environment's "Check for
        updates" press, when Dockhand's own container is in it."""
        if await self._refresh_self_update(env_id):
            self.async_set_updated_data(
                {"environments": self._with_self_update(dict(_all_envs(self.data)))}
            )

    def async_merge_check_results(self, env_id: int, items: list[dict]) -> None:
        """Merge already-fetched check-updates results for one environment
        into this coordinator's data — same end effect as
        async_check_environment() below, but for a caller that already
        has the raw items in hand and shouldn't trigger a second,
        redundant registry query to get them again.

        Used by DockhandCheckUpdatesButton: since 1.8.1 that button
        always fires the real check itself directly against the client
        (so it has something to feed Tier 1 with too, even when this
        coordinator doesn't exist at all — see button.py), then hands
        the same response here to update Tier 2 if this coordinator is
        present, rather than calling async_check_environment() and
        paying for the same check twice.
        """
        indexed = {
            item["containerId"]: item for item in items if item.get("containerId")
        }
        merged_environments = dict(_all_envs(self.data))
        merged_environments[env_id] = indexed
        self.async_set_updated_data(
            {"environments": self._with_self_update(merged_environments)}
        )

    async def async_check_environment(self, env_id: int) -> None:
        """Check just one environment for updates — the real fix for a
        design mismatch: this coordinator's periodic/full refresh
        (_fetch(), via async_refresh()) always checks every environment
        in one gather, since that's genuinely the cheapest way to keep
        the *whole* integration's update state current on a schedule.
        But the per-environment "Check for updates" button attached to
        each environment's device was calling that same full refresh —
        so pressing any one environment's button silently re-checked
        every environment, not just the one the button's device implies.
        Matches Dockhand's own UI too, which has no global "check
        everything" action either — it's environment by environment
        there as well, so this isn't us being less capable, just no
        longer pretending to be more capable than Dockhand itself.

        Raises on failure (unlike _fetch()'s per-environment resilience)
        — this is an explicit user action, and any caller should convert
        the exception into something visible to the user rather than
        silently falling back to stale data, which would make a failed
        check look like nothing happened.

        DockhandCheckUpdatesButton doesn't use this: it needs the raw
        items for Tier 1 too, so it fetches once and calls
        async_merge_check_results() itself.
        """
        items = await self.client.async_check_container_updates(env_id)
        self.async_merge_check_results(env_id, items)


class DockhandVersionCoordinator(DataUpdateCoordinator[str | None]):
    """Dockhand's own version, for the instance device's software version
    and system health.

    Separate from the fast and slow coordinators because it changes only
    when Dockhand is upgraded, while its source is a large response.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: DockhandClient,
        entry: ConfigEntry | None = None,
    ) -> None:
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_version",
            update_interval=VERSION_POLL_INTERVAL,
            config_entry=entry,
        )

    @override
    async def _async_update_data(self) -> str | None:
        try:
            return await self.client.async_get_dockhand_version()
        except Exception as err:
            raise UpdateFailed(f"Version error: {err}") from err
