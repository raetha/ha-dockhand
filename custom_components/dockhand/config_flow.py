from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DockhandClient, DockhandAuthError, DockhandMFARequiredError
from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_POLL_INTERVAL_SLOW,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_VOLUMES,
    CONF_ENABLE_NETWORKS,
    CONF_VERIFY_SSL,
    CONF_SESSION_COOKIE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_SLOW,
    DEFAULT_ENABLE_SCHEDULES,
    DEFAULT_ENABLE_IMAGES,
    DEFAULT_ENABLE_VOLUMES,
    DEFAULT_ENABLE_NETWORKS,
)

DEFAULT_VERIFY_SSL = True


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Step 1: URL and feature/poll settings — no credentials."""
    d = defaults or {}
    return vol.Schema({
        vol.Required(CONF_API_URL, default=d.get(CONF_API_URL, "")): str,
        vol.Optional(CONF_POLL_INTERVAL, default=d.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)): int,
        vol.Optional(CONF_POLL_INTERVAL_SLOW, default=d.get(CONF_POLL_INTERVAL_SLOW, DEFAULT_POLL_INTERVAL_SLOW)): int,
        vol.Optional(CONF_ENABLE_SCHEDULES, default=d.get(CONF_ENABLE_SCHEDULES, DEFAULT_ENABLE_SCHEDULES)): bool,
        vol.Optional(CONF_ENABLE_IMAGES, default=d.get(CONF_ENABLE_IMAGES, DEFAULT_ENABLE_IMAGES)): bool,
        vol.Optional(CONF_ENABLE_VOLUMES, default=d.get(CONF_ENABLE_VOLUMES, DEFAULT_ENABLE_VOLUMES)): bool,
        vol.Optional(CONF_ENABLE_NETWORKS, default=d.get(CONF_ENABLE_NETWORKS, DEFAULT_ENABLE_NETWORKS)): bool,
        vol.Optional(CONF_VERIFY_SSL, default=d.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)): bool,
    })


def _credentials_schema(defaults: dict[str, Any] | None = None,
                         require_password: bool = True) -> vol.Schema:
    """Step 2: credentials — only shown when server returns 401."""
    d = defaults or {}
    fields: dict = {
        vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): str,
    }
    if require_password:
        fields[vol.Required(CONF_PASSWORD)] = str
    else:
        fields[vol.Optional(CONF_PASSWORD)] = str  # blank = keep existing (reconfigure)
    return vol.Schema(fields)


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema({
        vol.Optional(CONF_POLL_INTERVAL, default=d.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)): int,
        vol.Optional(CONF_POLL_INTERVAL_SLOW, default=d.get(CONF_POLL_INTERVAL_SLOW, DEFAULT_POLL_INTERVAL_SLOW)): int,
        vol.Optional(CONF_ENABLE_SCHEDULES, default=d.get(CONF_ENABLE_SCHEDULES, DEFAULT_ENABLE_SCHEDULES)): bool,
        vol.Optional(CONF_ENABLE_IMAGES, default=d.get(CONF_ENABLE_IMAGES, DEFAULT_ENABLE_IMAGES)): bool,
        vol.Optional(CONF_ENABLE_VOLUMES, default=d.get(CONF_ENABLE_VOLUMES, DEFAULT_ENABLE_VOLUMES)): bool,
        vol.Optional(CONF_ENABLE_NETWORKS, default=d.get(CONF_ENABLE_NETWORKS, DEFAULT_ENABLE_NETWORKS)): bool,
    })


class DockhandConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        # Accumulates data across multi-step flows.
        self._connection_data: dict[str, Any] = {}
        # Tracks which flow triggered the credentials/MFA step.
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
            # Probe with no credentials — if the server responds without a 401,
            # authentication is disabled in Dockhand.
            client = DockhandClient(session, user_input)
            try:
                await client.async_get_environments()
                # Success with no credentials — auth is disabled.
                return self.async_create_entry(
                    title=user_input[CONF_API_URL],
                    data=user_input,
                )
            except DockhandAuthError:
                # Server requires authentication — proceed to credentials step.
                self._connection_data = user_input
                self._flow_origin = "user"
                return await self.async_step_credentials()
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input or {}),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Step 2: credentials (only reached when server returned 401)
    # ------------------------------------------------------------------ #

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Credential step — shown only when the server requires authentication."""
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**self._connection_data, **user_input}
            verify_ssl = merged.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, merged)
            try:
                cookie = await client.async_login()

                if self._flow_origin == "user":
                    return self.async_create_entry(
                        title=merged[CONF_API_URL],
                        data={**merged, CONF_SESSION_COOKIE: cookie},
                    )

                # reauth and reconfigure — update the existing entry
                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry, data={**merged, CONF_SESSION_COOKIE: cookie}
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                reason = "reauth_successful" if self._flow_origin == "reauth" else "reconfigure_successful"
                return self.async_abort(reason=reason)

            except DockhandMFARequiredError:
                # Save merged (includes credentials) so async_step_mfa can
                # build a client with username+password to submit the token.
                self._connection_data = merged
                return await self.async_step_mfa()
            except DockhandAuthError:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="credentials",
            data_schema=_credentials_schema(
                self._connection_data,
                require_password=(self._flow_origin != "reconfigure"),
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Step 3: MFA (only reached when server requires TOTP)
    # ------------------------------------------------------------------ #

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            verify_ssl = self._connection_data.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, self._connection_data)
            try:
                cookie = await client.async_login(mfa_token=user_input["mfa_token"])

                if self._flow_origin == "user":
                    return self.async_create_entry(
                        title=self._connection_data[CONF_API_URL],
                        data={**self._connection_data, CONF_SESSION_COOKIE: cookie},
                    )

                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry, data={**self._connection_data, CONF_SESSION_COOKIE: cookie}
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                reason = "reauth_successful" if self._flow_origin == "reauth" else "reconfigure_successful"
                return self.async_abort(reason=reason)

            except DockhandAuthError:
                errors["base"] = "invalid_mfa"

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({"mfa_token": str}),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Re-authentication (session expired — auth clearly was enabled)
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
            self._connection_data = merged
            self._flow_origin = "reauth"
            verify_ssl = merged.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, merged)
            try:
                cookie = await client.async_login()
                self.hass.config_entries.async_update_entry(
                    entry, data={**merged, CONF_SESSION_COOKIE: cookie}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except DockhandMFARequiredError:
                return await self.async_step_mfa()
            except DockhandAuthError:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "") if entry else ""): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Reconfigure (change URL, credentials, or feature flags)
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
                await client.async_get_environments()
                # No auth required — strip any previously stored credentials.
                clean = {k: v for k, v in {**entry.data, **user_input}.items()
                         if k not in (CONF_USERNAME, CONF_PASSWORD, CONF_SESSION_COOKIE)}
                self.hass.config_entries.async_update_entry(entry, data=clean)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")
            except DockhandAuthError:
                # Auth required — carry connection data forward and show credentials.
                # Pre-fill username from existing entry so user only needs password.
                self._connection_data = {**entry.data, **user_input}
                self._flow_origin = "reconfigure"
                return await self.async_step_credentials()
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
        return self.async_show_form(step_id="init", data_schema=_options_schema(defaults))
