from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DockhandAuthError, DockhandClient
from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_UPDATES,
    CONF_ENABLE_VOLUMES,
    CONF_POLL_INTERVAL,
    CONF_POLL_INTERVAL_SLOW,
    CONF_POLL_INTERVAL_UPDATES,
    CONF_VERIFY_SSL,
    DEFAULT_ENABLE_IMAGES,
    DEFAULT_ENABLE_NETWORKS,
    DEFAULT_ENABLE_SCHEDULES,
    DEFAULT_ENABLE_UPDATES,
    DEFAULT_ENABLE_VOLUMES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_SLOW,
    DEFAULT_POLL_INTERVAL_UPDATES,
    DOMAIN,
)

DEFAULT_VERIFY_SSL = True


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Step 1: URL and feature/poll settings."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_API_URL, default=d.get(CONF_API_URL, "")): str,
            vol.Optional(
                CONF_POLL_INTERVAL,
                default=d.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): int,
            vol.Optional(
                CONF_POLL_INTERVAL_SLOW,
                default=d.get(CONF_POLL_INTERVAL_SLOW, DEFAULT_POLL_INTERVAL_SLOW),
            ): int,
            vol.Optional(
                CONF_ENABLE_SCHEDULES,
                default=d.get(CONF_ENABLE_SCHEDULES, DEFAULT_ENABLE_SCHEDULES),
            ): bool,
            vol.Optional(
                CONF_ENABLE_IMAGES,
                default=d.get(CONF_ENABLE_IMAGES, DEFAULT_ENABLE_IMAGES),
            ): bool,
            vol.Optional(
                CONF_ENABLE_VOLUMES,
                default=d.get(CONF_ENABLE_VOLUMES, DEFAULT_ENABLE_VOLUMES),
            ): bool,
            vol.Optional(
                CONF_ENABLE_NETWORKS,
                default=d.get(CONF_ENABLE_NETWORKS, DEFAULT_ENABLE_NETWORKS),
            ): bool,
            vol.Optional(
                CONF_ENABLE_UPDATES,
                default=d.get(CONF_ENABLE_UPDATES, DEFAULT_ENABLE_UPDATES),
            ): bool,
            vol.Optional(
                CONF_POLL_INTERVAL_UPDATES,
                default=d.get(
                    CONF_POLL_INTERVAL_UPDATES, DEFAULT_POLL_INTERVAL_UPDATES
                ),
            ): int,
            vol.Optional(
                CONF_VERIFY_SSL, default=d.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            ): bool,
        }
    )


def _token_schema() -> vol.Schema:
    """Step 2: API token — only shown when server requires authentication."""
    return vol.Schema(
        {
            vol.Required(CONF_API_TOKEN): str,
        }
    )


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_POLL_INTERVAL,
                default=d.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): int,
            vol.Optional(
                CONF_POLL_INTERVAL_SLOW,
                default=d.get(CONF_POLL_INTERVAL_SLOW, DEFAULT_POLL_INTERVAL_SLOW),
            ): int,
            vol.Optional(
                CONF_ENABLE_SCHEDULES,
                default=d.get(CONF_ENABLE_SCHEDULES, DEFAULT_ENABLE_SCHEDULES),
            ): bool,
            vol.Optional(
                CONF_ENABLE_IMAGES,
                default=d.get(CONF_ENABLE_IMAGES, DEFAULT_ENABLE_IMAGES),
            ): bool,
            vol.Optional(
                CONF_ENABLE_VOLUMES,
                default=d.get(CONF_ENABLE_VOLUMES, DEFAULT_ENABLE_VOLUMES),
            ): bool,
            vol.Optional(
                CONF_ENABLE_NETWORKS,
                default=d.get(CONF_ENABLE_NETWORKS, DEFAULT_ENABLE_NETWORKS),
            ): bool,
            vol.Optional(
                CONF_ENABLE_UPDATES,
                default=d.get(CONF_ENABLE_UPDATES, DEFAULT_ENABLE_UPDATES),
            ): bool,
            vol.Optional(
                CONF_POLL_INTERVAL_UPDATES,
                default=d.get(
                    CONF_POLL_INTERVAL_UPDATES, DEFAULT_POLL_INTERVAL_UPDATES
                ),
            ): int,
        }
    )


class DockhandConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        # Accumulates data across multi-step flows.
        self._connection_data: dict[str, Any] = {}
        # Tracks which flow triggered the token step.
        # Values: "user" | "reauth" | "reconfigure"
        self._flow_origin: str = "user"

    # ------------------------------------------------------------------ #
    # Step 1: connection settings (URL + feature flags)
    # ------------------------------------------------------------------ #

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First step: URL and settings. Probe server to detect auth requirement."""
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id = user_input[CONF_API_URL].rstrip("/").lower()
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, user_input)
            try:
                await client.async_probe()
                # Probe succeeded with no token — auth is disabled.
                return self.async_create_entry(
                    title=user_input[CONF_API_URL],
                    data=user_input,
                )
            except DockhandAuthError:
                # Server requires authentication — proceed to token step.
                self._connection_data = user_input
                self._flow_origin = "user"
                return await self.async_step_token()
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input or {}),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Step 2: API token (only reached when server returned 401)
    # ------------------------------------------------------------------ #

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Token step — shown only when the server requires authentication."""
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**self._connection_data, **user_input}
            verify_ssl = merged.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, merged)
            try:
                await client.async_probe()

                if self._flow_origin == "user":
                    return self.async_create_entry(
                        title=merged[CONF_API_URL],
                        data=merged,
                    )

                # reauth and reconfigure — update the existing entry
                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                if entry:
                    self.hass.config_entries.async_update_entry(entry, data=merged)
                    await self.hass.config_entries.async_reload(entry.entry_id)
                reason = (
                    "reauth_successful"
                    if self._flow_origin == "reauth"
                    else "reconfigure_successful"
                )
                return self.async_abort(reason=reason)

            except DockhandAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="token",
            data_schema=_token_schema(),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Re-authentication (token revoked / auth re-enabled on no-auth install)
    # ------------------------------------------------------------------ #

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if user_input is not None and entry:
            merged = {**entry.data, **user_input}
            verify_ssl = merged.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, merged)
            try:
                await client.async_probe()
                self.hass.config_entries.async_update_entry(entry, data=merged)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except DockhandAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_token_schema(),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Reconfigure (change URL, token, or feature flags)
    # ------------------------------------------------------------------ #

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1 of reconfigure: connection settings. Probe to detect auth state."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if user_input is not None and entry:
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, user_input)
            try:
                await client.async_probe()
                # No auth required — strip any previously stored token.
                clean = {
                    k: v
                    for k, v in {**entry.data, **user_input}.items()
                    if k != CONF_API_TOKEN
                }
                self.hass.config_entries.async_update_entry(entry, data=clean)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")
            except DockhandAuthError:
                # Auth required — carry connection data forward and show token step.
                self._connection_data = {**entry.data, **user_input}
                self._flow_origin = "reconfigure"
                return await self.async_step_token()
            except Exception:
                errors["base"] = "cannot_connect"

        defaults = {**(entry.data if entry else {}), **(entry.options if entry else {})}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(defaults),
            errors=errors,
        )


class DockhandOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        defaults = {**self._entry.data, **self._entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(defaults)
        )
