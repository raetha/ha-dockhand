import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DockhandAuthError, DockhandClient
from .const import (
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_VOLUMES,
    CONF_POLL_INTERVAL,
    CONF_POLL_INTERVAL_SLOW,
    CONF_POLL_INTERVAL_UPDATES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_SLOW,
    DEFAULT_POLL_INTERVAL_UPDATES,
    DOMAIN,
)
from .helpers import _compose_project, _extract_runtime_config

_LOGGER = logging.getLogger(__name__)


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _unwrap(val: Any, default: Any, label: str) -> Any:
    if isinstance(val, Exception):
        _LOGGER.warning("Dockhand: error fetching %s: %s", label, val)
        return default
    return val


class DockhandFastCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls 60s: dashboard stats, containers, stacks, container resource
    stats, pending update flags.

    Pending update flags are fetched per-environment whenever that
    environment has updateCheckEnabled=True (from its own dashboard
    stats) — not gated by CONF_ENABLE_PRECISE_UPDATES. This is what backs the
    update platform's baseline (digest-free) entities, which now exist
    automatically for any environment where update-check is configured
    in Dockhand itself. CONF_ENABLE_PRECISE_UPDATES only controls whether the
    separate, opt-in DockhandUpdateCoordinator also runs (real registry
    queries) to layer precise digest-based versions onto those same
    entities.

    Shape: {
        env_id: {
            "stats": {},
            "containers": [],
            "stacks": [],
            "container_stats": {name: {}},
            "pending_update_container_ids": {container_id, ...},
        }
    }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: DockhandClient,
        config: dict[str, Any],
        entry: ConfigEntry | None = None,
    ) -> None:
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_fast",
            update_interval=timedelta(
                seconds=int(config.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
            ),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch()
        except DockhandAuthError as err:
            # Token is invalid or revoked — surface immediately so HA prompts
            # the user to re-authenticate. No retry is possible without a new token.
            raise ConfigEntryAuthFailed(
                "Dockhand API token is invalid or was revoked. "
                "Go to Settings → Devices & Services → Dockhand → Re-authenticate."
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Fast data error: {err}") from err

    async def _fetch(self) -> dict[str, Any]:
        # Fetch stats for all environments in a single API call — this is
        # also our only source of which environments exist. We used to
        # call /api/environments separately just for the id list, but
        # every env we need to iterate already has an "id" here, and this
        # endpoint doesn't leak decrypted secrets (tlsKey/hawserToken) the
        # way /api/environments does (see diagnostics.py's redaction
        # comment). A transient failure here is non-fatal — this poll
        # cycle simply produces no environments to iterate, and normal
        # coordinator retry picks it back up next cycle. An auth failure
        # is NOT swallowed though — this is now our only call that would
        # ever surface a 401, so it must propagate for
        # _async_update_data's re-auth handling to trigger at all.
        try:
            all_stats_list = _safe_list(
                await self.client.async_get_all_dashboard_stats()
            )
        except DockhandAuthError:
            raise
        except Exception as err:
            _LOGGER.warning("Dockhand: error fetching dashboard stats: %s", err)
            all_stats_list = []
        all_stats: dict[int, dict] = {
            s["id"]: s for s in all_stats_list if isinstance(s, dict) and "id" in s
        }

        async def _fetch_env(eid: int) -> tuple[int, dict]:
            update_check_enabled = bool(
                all_stats.get(eid, {}).get("updateCheckEnabled")
            )
            coros = [
                self.client.async_get_containers(eid),
                self.client.async_get_stacks(eid),
                self.client.async_get_container_stats(eid),
            ]
            if update_check_enabled:
                coros.append(self.client.async_get_pending_updates(eid))
            results = await asyncio.gather(*coros, return_exceptions=True)
            # Index container stats by name for O(1) lookup from sensor entities.
            # Stopped/exited containers are absent from the stats response — their
            # sensors will return None (unavailable) until the container is running.
            raw_stats = _safe_list(
                _unwrap(results[2], [], f"container_stats env={eid}")
            )
            container_stats: dict[str, dict] = {
                s["name"]: s for s in raw_stats if isinstance(s, dict) and "name" in s
            }
            pending_update_container_ids: set[str] = set()
            if update_check_enabled:
                pending = _safe_list(
                    _unwrap(results[3], [], f"pending_updates env={eid}")
                )
                pending_update_container_ids = {
                    p["containerId"]
                    for p in pending
                    if isinstance(p, dict) and p.get("containerId")
                }
            return eid, {
                "stats": all_stats.get(eid, {}),
                "containers": _safe_list(
                    _unwrap(results[0], [], f"containers env={eid}")
                ),
                "stacks": _safe_list(_unwrap(results[1], [], f"stacks env={eid}")),
                "container_stats": container_stats,
                "pending_update_container_ids": pending_update_container_ids,
            }

        out: dict[int, dict] = {}
        for result in await asyncio.gather(
            *[_fetch_env(eid) for eid in all_stats], return_exceptions=True
        ):
            if isinstance(result, Exception):
                _LOGGER.warning("Dockhand fast env error: %s", result)
            else:
                eid, data = result
                out[eid] = data
        return out


class DockhandSlowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls 600s: images, volumes, networks, schedules, runtime controls
    (all opt-in), git stacks/host/auto_update_settings/env_meta (always —
    cheap bulk calls, not gated).

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
                "env_meta": {"imagePruneEnabled": bool, "hawserAgentName": str|None,
                             "hawserAgentId": str|None, "hawserLastSeen": str|None,
                             "connectionHost": str|None, "connectionPort": int|None}
            }
        },
        "schedules": []
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
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_slow",
            update_interval=timedelta(
                seconds=int(
                    config.get(CONF_POLL_INTERVAL_SLOW, DEFAULT_POLL_INTERVAL_SLOW)
                )
            ),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch()
        except DockhandAuthError as err:
            # Let the fast coordinator own reauth — just surface as transient failure.
            raise UpdateFailed(
                "API token rejected — fast coordinator will surface reauth"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Slow data error: {err}") from err

    async def _fetch(self) -> dict[str, Any]:
        # Which environments exist still comes from the fast coordinator's
        # data, not from this call — fast completes its first refresh
        # before we do ours (see __init__.py setup order), so this is
        # reliably populated by the time we need it, and it means this
        # coordinator's environment enumeration doesn't depend on
        # /api/environments succeeding.
        env_ids = list((self._fast_coordinator.data or {}).keys())

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

        env_meta: dict[int, dict] = {}
        envs_raw = _unwrap(top_results[0], [], "environments")
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
            _safe_list(_unwrap(top_results[1], [], "schedules"))
            if self._enable_schedules and len(top_results) > 1
            else []
        )

        async def _fetch_runtime_config(eid: int) -> dict[str, dict]:
            """Current Memory/NanoCpus/PidsLimit/RestartPolicy for every
            stack-less container in an environment.

            Two-phase: list containers, then inspect each stack-less one.
            A per-container inspect failure is logged and that container is
            simply omitted (its number/select entities read as unknown)
            rather than failing the whole environment's slow poll.
            """
            containers = _safe_list(await self.client.async_get_containers(eid))
            stackless = [c for c in containers if not _compose_project(c)]
            inspected = await asyncio.gather(
                *[
                    self.client.async_get_container_inspect(eid, c["id"])
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
                        eid,
                        data,
                    )
                    continue
                if isinstance(data, dict) and name:
                    result[name] = _extract_runtime_config(data)
            return result

        async def _fetch_env(eid: int) -> tuple[int, dict]:
            # Build a named mapping of coroutines so result indexing is
            # explicit rather than fragile positional arithmetic.
            named: dict[str, Any] = {}
            if self._enable_images:
                named["images"] = self.client.async_get_images(eid)
            if self._enable_networks:
                named["networks"] = self.client.async_get_networks(eid)
            if self._enable_volumes:
                named["volumes"] = self.client.async_get_volumes(eid)
            if self._enable_runtime_controls:
                named["runtime_config"] = _fetch_runtime_config(eid)
            # Always fetched: a single bulk call per environment (not
            # per-container/per-stack like runtime controls), so there's no
            # meaningful API cost to gate. Entities are only created for
            # stacks that actually appear in this list — i.e. automatically
            # whenever a stack is detected as git-tracked, no separate
            # opt-in needed.
            named["git_stacks"] = self.client.async_get_git_stacks(eid)
            # Always fetched: one bulk call per environment, cheap, and
            # (unlike runtime controls) does not scale with container count.
            named["auto_update_settings"] = self.client.async_get_auto_update_settings(
                eid
            )
            # Always fetched: GET /api/host is the only reliable source for
            # hawserVersion on hawser-standard connections, which live-fetch
            # from the agent on every call.
            named["host"] = self.client.async_get_host_info(eid)

            results: dict[str, Any] = {}
            if named:
                keys = list(named)
                gathered = await asyncio.gather(*named.values(), return_exceptions=True)
                for key, val in zip(keys, gathered, strict=False):
                    if key == "host":
                        unwrapped = _unwrap(val, {}, f"host env={eid}")
                        results["host"] = (
                            unwrapped if isinstance(unwrapped, dict) else {}
                        )
                    elif key == "runtime_config":
                        unwrapped = _unwrap(val, {}, f"runtime_config env={eid}")
                        results["runtime_config"] = (
                            unwrapped if isinstance(unwrapped, dict) else {}
                        )
                    elif key == "auto_update_settings":
                        unwrapped = _unwrap(val, {}, f"auto_update_settings env={eid}")
                        results["auto_update_settings"] = (
                            unwrapped if isinstance(unwrapped, dict) else {}
                        )
                    else:
                        results[key] = _safe_list(_unwrap(val, [], f"{key} env={eid}"))

            return eid, {
                "host": results.get("host", {}),
                "images": results.get("images", []),
                "networks": results.get("networks", []),
                "volumes": results.get("volumes", []),
                "runtime_config": results.get("runtime_config", {}),
                "git_stacks": results.get("git_stacks", []),
                "auto_update_settings": results.get("auto_update_settings", {}),
                "env_meta": env_meta.get(eid, {}),
            }

        environments: dict[int, dict] = {}
        for result in await asyncio.gather(
            *[_fetch_env(eid) for eid in env_ids], return_exceptions=True
        ):
            if isinstance(result, Exception):
                _LOGGER.warning("Dockhand slow env error: %s", result)
            else:
                eid, data = result
                environments[eid] = data
        return {"environments": environments, "schedules": schedules}


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
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_updates",
            update_interval=timedelta(
                seconds=int(
                    config.get(
                        CONF_POLL_INTERVAL_UPDATES, DEFAULT_POLL_INTERVAL_UPDATES
                    )
                )
            ),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch()
        except DockhandAuthError as err:
            raise UpdateFailed(
                "API token rejected — fast coordinator will surface reauth"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Update check error: {err}") from err

    async def _fetch(self) -> dict[str, Any]:
        # Reuse the fast coordinator's environment list — it is always fresher
        # than making a separate async_get_environments() call and avoids a
        # redundant API round trip on every update check.
        env_ids = list(self._fast.data.keys()) if self._fast.data else []

        async def _fetch_env(eid: int) -> tuple[int, dict[str, dict]]:
            try:
                results = await self.client.async_check_container_updates(eid)
            except Exception as exc:
                _LOGGER.warning(
                    "Dockhand: update check failed for env %s: %s", eid, exc
                )
                results = []
            # Index by container ID for O(1) lookup by update entities.
            return eid, {
                item["containerId"]: item for item in results if item.get("containerId")
            }

        out: dict[int, dict] = {}
        for result in await asyncio.gather(
            *[_fetch_env(eid) for eid in env_ids], return_exceptions=True
        ):
            if isinstance(result, Exception):
                _LOGGER.warning("Dockhand update env error: %s", result)
            else:
                eid, data = result
                out[eid] = data
        return out
