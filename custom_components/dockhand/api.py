import logging
from typing import Any

from aiohttp import ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)


class DockhandError(Exception):
    """Base class for Dockhand API errors."""


class DockhandAuthError(DockhandError):
    """Authentication failed — 401 received.

    With token auth this means the token is invalid or revoked.
    With no-auth installs it means authentication was re-enabled in Dockhand.
    """


class DockhandClient:
    """Client for interacting with the Dockhand API.

    Authentication is handled via an optional Bearer token (dh_...).
    When no token is stored the client sends unauthenticated requests,
    which works when Dockhand authentication is disabled.
    """

    def __init__(self, session: ClientSession, config: dict[str, Any]) -> None:
        self._session = session
        self._api_url = config.get("api_url", "").rstrip("/")
        self._api_token: str | None = config.get("api_token")

    # ------------------------------------------------------------------ #
    # Internal helper
    # ------------------------------------------------------------------ #

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self._api_url}{path}"
        headers = kwargs.pop("headers", {})

        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"

        headers.setdefault("Accept", "application/json")

        timeout = ClientTimeout(total=30)
        async with self._session.request(
            method, url, headers=headers, timeout=timeout, **kwargs
        ) as resp:
            if resp.status == 401:
                raise DockhandAuthError("Unauthorized — token invalid or revoked")
            if resp.status >= 400:
                text = await resp.text()
                raise DockhandError(f"API error {resp.status}: {text}")
            try:
                return await resp.json(content_type=None)
            except Exception:
                return await resp.text()

    # ------------------------------------------------------------------ #
    # Connectivity probe — used by config flow to detect auth state
    # ------------------------------------------------------------------ #

    async def async_probe(self) -> None:
        """Probe the server by fetching environments.

        Raises DockhandAuthError on 401, DockhandError on other failures,
        or an aiohttp exception if the server is unreachable.
        """
        await self.async_get_environments()

    # ------------------------------------------------------------------ #
    # Read endpoints
    # ------------------------------------------------------------------ #

    async def async_get_environments(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/api/environments")

    async def async_get_dashboard_stats(self, env_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/dashboard/stats?env={env_id}")

    async def async_get_containers(self, env_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/api/containers?env={env_id}")

    async def async_get_stacks(self, env_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/api/stacks?env={env_id}")

    async def async_get_networks(self, env_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/api/networks?env={env_id}")

    async def async_get_images(self, env_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/api/images?env={env_id}")

    async def async_get_schedules(self) -> list[dict[str, Any]]:
        """Return all schedules (global, not per-environment). GET /api/schedules"""
        data = await self._request("GET", "/api/schedules")
        if isinstance(data, dict):
            return data.get("schedules", [])
        return data if isinstance(data, list) else []

    async def async_get_volumes(self, env_id: int) -> list[dict[str, Any]]:
        """Return volumes for an environment. GET /api/volumes?env=X"""
        return await self._request("GET", f"/api/volumes?env={env_id}")

    # ------------------------------------------------------------------ #
    # Container actions
    # ------------------------------------------------------------------ #

    async def async_start_container(self, env_id: int, container_id: str) -> None:
        """Start a stopped container. POST /api/containers/[id]/start?env=X"""
        await self._request(
            "POST", f"/api/containers/{container_id}/start?env={env_id}"
        )

    async def async_stop_container(self, env_id: int, container_id: str) -> None:
        """Stop a running container. POST /api/containers/[id]/stop?env=X"""
        await self._request("POST", f"/api/containers/{container_id}/stop?env={env_id}")

    async def async_restart_container(self, env_id: int, container_id: str) -> None:
        """Restart a running container. POST /api/containers/[id]/restart?env=X"""
        await self._request(
            "POST", f"/api/containers/{container_id}/restart?env={env_id}"
        )

    # ------------------------------------------------------------------ #
    # Stack actions
    #
    # Stack endpoints support long-running operations. Sending
    # Accept: application/json (set by _request's default) causes Dockhand
    # to run the operation synchronously and return a single JSON result
    # rather than a job-ID reference for async polling. This ensures our
    # switch/button entities surface real success or failure.
    # ------------------------------------------------------------------ #

    async def async_start_stack(self, env_id: int, stack_name: str) -> None:
        """Start a stopped stack. POST /api/stacks/[name]/start?env=X"""
        await self._request("POST", f"/api/stacks/{stack_name}/start?env={env_id}")

    async def async_stop_stack(self, env_id: int, stack_name: str) -> None:
        """Stop a running stack. POST /api/stacks/[name]/stop?env=X"""
        await self._request("POST", f"/api/stacks/{stack_name}/stop?env={env_id}")

    async def async_restart_stack(self, env_id: int, stack_name: str) -> None:
        """Restart a running stack. POST /api/stacks/[name]/restart?env=X"""
        await self._request("POST", f"/api/stacks/{stack_name}/restart?env={env_id}")
