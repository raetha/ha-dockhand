from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_POLL_INTERVAL,
    CONF_POLL_INTERVAL_SLOW,
    CONF_SESSION_COOKIE,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_VOLUMES,
    CONF_ENABLE_NETWORKS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_SLOW,
)
from .api import DockhandClient, DockhandAuthError, DockhandMFARequiredError

_LOGGER = logging.getLogger(__name__)


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _unwrap(val: Any, default: Any, label: str) -> Any:
    if isinstance(val, Exception):
        _LOGGER.warning("Dockhand: error fetching %s: %s", label, val)
        return default
    return val


class DockhandFastCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls 60s: dashboard stats, containers, stacks.

    Shape: { env_id: {"stats": {}, "containers": [], "stacks": []} }
    """

    def __init__(self, hass: HomeAssistant, client: DockhandClient,
                 config: dict[str, Any], entry: ConfigEntry | None = None) -> None:
        self.client = client
        self._entry = entry
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_fast",
            update_interval=timedelta(seconds=int(config.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch()
        except DockhandAuthError:
            await self._handle_reauth()
            try:
                return await self._fetch()
            except Exception as err:
                raise UpdateFailed(f"Fast data error after re-auth: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Fast data error: {err}") from err

    async def _handle_reauth(self) -> None:
        try:
            cookie = await self.client.async_login()
            if self._entry:
                self.hass.config_entries.async_update_entry(
                    self._entry, data={**self._entry.data, CONF_SESSION_COOKIE: cookie})
        except DockhandMFARequiredError as err:
            raise ConfigEntryAuthFailed("MFA required — re-authenticate via integration page") from err
        except DockhandAuthError as err:
            raise ConfigEntryAuthFailed(f"Re-authentication failed: {err}") from err

    async def _fetch(self) -> dict[str, Any]:
        environments_list = _safe_list(await self.client.async_get_environments())

        async def _fetch_env(env: dict) -> tuple[int, dict]:
            eid = env["id"]
            results = await asyncio.gather(
                self.client.async_get_dashboard_stats(eid),
                self.client.async_get_containers(eid),
                self.client.async_get_stacks(eid),
                return_exceptions=True,
            )
            return eid, {
                "stats": _safe_dict(_unwrap(results[0], {}, f"stats env={eid}")),
                "containers": _safe_list(_unwrap(results[1], [], f"containers env={eid}")),
                "stacks": _safe_list(_unwrap(results[2], [], f"stacks env={eid}")),
            }

        out: dict[int, dict] = {}
        for result in await asyncio.gather(*[_fetch_env(e) for e in environments_list], return_exceptions=True):
            if isinstance(result, Exception):
                _LOGGER.warning("Dockhand fast env error: %s", result)
            else:
                eid, data = result
                out[eid] = data
        return out


class DockhandSlowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls 600s: images, volumes, networks, schedules (all optional).

    Shape: {
        "environments": { env_id: {"env": {}, "images": [], "networks": [], "volumes": []} },
        "schedules": []
    }
    """

    def __init__(self, hass: HomeAssistant, client: DockhandClient,
                 config: dict[str, Any], entry: ConfigEntry | None = None) -> None:
        self.client = client
        self._entry = entry
        self._enable_schedules = bool(config.get(CONF_ENABLE_SCHEDULES, False))
        self._enable_images = bool(config.get(CONF_ENABLE_IMAGES, False))
        self._enable_volumes = bool(config.get(CONF_ENABLE_VOLUMES, False))
        self._enable_networks = bool(config.get(CONF_ENABLE_NETWORKS, False))
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_slow",
            update_interval=timedelta(seconds=int(config.get(CONF_POLL_INTERVAL_SLOW, DEFAULT_POLL_INTERVAL_SLOW))),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch()
        except DockhandAuthError:
            raise UpdateFailed("Session expired — waiting for fast coordinator to re-authenticate")
        except Exception as err:
            raise UpdateFailed(f"Slow data error: {err}") from err

    async def _fetch(self) -> dict[str, Any]:
        top_coros: list = [self.client.async_get_environments()]
        if self._enable_schedules:
            top_coros.append(self.client.async_get_schedules())
        top_results = await asyncio.gather(*top_coros, return_exceptions=True)
        # Re-raise exceptions from the environments call — these are fatal since
        # we cannot proceed without the environment list. asyncio.gather with
        # return_exceptions=True returns exceptions as values, so we must check.
        if isinstance(top_results[0], BaseException):
            raise top_results[0]
        environments_list = _safe_list(_unwrap(top_results[0], [], "environments"))
        schedules: list = []
        if self._enable_schedules and len(top_results) > 1:
            schedules = _safe_list(_unwrap(top_results[1], [], "schedules"))

        async def _fetch_env(env: dict) -> tuple[int, dict]:
            eid = env["id"]
            coros, labels = [], []
            if self._enable_images:
                coros.append(self.client.async_get_images(eid))
                labels.append(f"images env={eid}")
            if self._enable_networks:
                coros.append(self.client.async_get_networks(eid))
                labels.append(f"networks env={eid}")
            if self._enable_volumes:
                coros.append(self.client.async_get_volumes(eid))
                labels.append(f"volumes env={eid}")

            results = await asyncio.gather(*coros, return_exceptions=True)
            idx = 0
            images, networks, volumes = [], [], []
            if self._enable_images:
                images = _safe_list(_unwrap(results[idx], [], labels[idx]))
                idx += 1
            if self._enable_networks:
                networks = _safe_list(_unwrap(results[idx], [], labels[idx]))
                idx += 1
            if self._enable_volumes:
                volumes = _safe_list(_unwrap(results[idx], [], labels[idx]))
                idx += 1
            return eid, {"env": env, "images": images, "networks": networks, "volumes": volumes}

        environments: dict[int, dict] = {}
        for result in await asyncio.gather(*[_fetch_env(e) for e in environments_list], return_exceptions=True):
            if isinstance(result, Exception):
                _LOGGER.warning("Dockhand slow env error: %s", result)
            else:
                eid, data = result
                environments[eid] = data
        return {"environments": environments, "schedules": schedules}
