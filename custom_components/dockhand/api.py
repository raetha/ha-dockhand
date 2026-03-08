from __future__ import annotations

import logging
from typing import Any, Optional

from aiohttp import ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)


class DockhandError(Exception):
    """Base class for Dockhand API errors."""


class DockhandAuthError(DockhandError):
    """Authentication failed."""


class DockhandMFARequiredError(DockhandError):
    """MFA is required to complete login."""


class DockhandClient:
    """Client for interacting with the Dockhand API."""

    def __init__(self, session: ClientSession, config: dict[str, Any]) -> None:
        self._session = session
        self._api_url = config.get("api_url", "").rstrip("/")
        self._username = config.get("username")
        self._password = config.get("password")
        self._cookie: Optional[str] = config.get("session_cookie")

    # ------------------------------------------------------------------ #
    # Authentication
    # ------------------------------------------------------------------ #

    async def async_login(self, mfa_token: str | None = None) -> str:
        """Authenticate with Dockhand, store and return the session cookie."""
        url = f"{self._api_url}/api/auth/login"
        payload: dict[str, Any] = {
            "username": self._username,
            "password": self._password,
        }
        if mfa_token:
            payload["mfaToken"] = mfa_token

        try:
            async with self._session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            ) as resp:
                if resp.status == 401:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {}
                    if data.get("requiresMfa") or data.get("mfaRequired"):
                        raise DockhandMFARequiredError("MFA required")
                    raise DockhandAuthError("Invalid credentials (401)")

                if resp.status != 200:
                    text = await resp.text()
                    raise DockhandAuthError(f"Login failed: HTTP {resp.status}: {text}")

                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {}
                if data.get("requiresMfa") or data.get("mfaRequired"):
                    raise DockhandMFARequiredError("MFA required")

                if "dockhand_session" in resp.cookies:
                    self._cookie = resp.cookies["dockhand_session"].value
                    _LOGGER.debug("Dockhand login successful")
                    return self._cookie
                raise DockhandAuthError(
                    "Login returned HTTP 200 but no 'dockhand_session' cookie was present."
                )

        except (DockhandAuthError, DockhandMFARequiredError):
            raise
        except Exception as err:
            raise DockhandAuthError(f"Unexpected error during login: {err}") from err

    # ------------------------------------------------------------------ #
    # Internal helper
    # ------------------------------------------------------------------ #

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        if not self._cookie:
            raise DockhandAuthError("Not authenticated")
        url = f"{self._api_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Cookie"] = f"dockhand_session={self._cookie}"
        headers.setdefault("Accept", "application/json")

        timeout = ClientTimeout(total=30)
        async with self._session.request(method, url, headers=headers, timeout=timeout, **kwargs) as resp:
            if resp.status == 401:
                raise DockhandAuthError("Session expired or unauthorized")
            if resp.status >= 400:
                text = await resp.text()
                raise DockhandError(f"API error {resp.status}: {text}")
            try:
                return await resp.json(content_type=None)
            except Exception:
                return await resp.text()

    # ------------------------------------------------------------------ #
    # API endpoints
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
        """Return volumes for an environment. GET /api/volumes?env=X
        Docker volume fields use PascalCase (Name, Driver, Mountpoint, Scope,
        Labels, UsageData). UsageData.Size is -1 until Docker has run a disk
        usage calculation via 'docker system df'."""
        return await self._request("GET", f"/api/volumes?env={env_id}")

    # ------------------------------------------------------------------ #
    # Container actions
    # ------------------------------------------------------------------ #

    async def async_start_container(self, env_id: int, container_id: str) -> None:
        """Start a stopped container. POST /api/containers/[id]/start?env=X"""
        await self._request("POST", f"/api/containers/{container_id}/start?env={env_id}")

    async def async_stop_container(self, env_id: int, container_id: str) -> None:
        """Stop a running container. POST /api/containers/[id]/stop?env=X"""
        await self._request("POST", f"/api/containers/{container_id}/stop?env={env_id}")

    async def async_restart_container(self, env_id: int, container_id: str) -> None:
        """Restart a running container. POST /api/containers/[id]/restart?env=X
        Note: Only works on running containers. Use start for stopped ones."""
        await self._request("POST", f"/api/containers/{container_id}/restart?env={env_id}")

    # ------------------------------------------------------------------ #
    # Stack actions
    # ------------------------------------------------------------------ #

    async def async_start_stack(self, env_id: int, stack_name: str) -> None:
        """Start a stopped stack. POST /api/stacks/[name]/start?env=X"""
        await self._request(
            "POST", f"/api/stacks/{stack_name}/start?env={env_id}",
            headers={"Accept": "application/json"},
        )

    async def async_stop_stack(self, env_id: int, stack_name: str) -> None:
        """Stop a running stack. POST /api/stacks/[name]/stop?env=X"""
        await self._request(
            "POST", f"/api/stacks/{stack_name}/stop?env={env_id}",
            headers={"Accept": "application/json"},
        )

    async def async_restart_stack(self, env_id: int, stack_name: str) -> None:
        """Restart a running stack. POST /api/stacks/[name]/restart?env=X
        Note: Only works on running/partial stacks. Use start for stopped ones."""
        await self._request(
            "POST", f"/api/stacks/{stack_name}/restart?env={env_id}",
            headers={"Accept": "application/json"},
        )
