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


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema({
        vol.Required(CONF_API_URL, default=d.get(CONF_API_URL, "")): str,
        vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): str,
        vol.Required(CONF_PASSWORD, default=d.get(CONF_PASSWORD, "")): str,
        vol.Optional(CONF_POLL_INTERVAL, default=d.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)): int,
        vol.Optional(CONF_POLL_INTERVAL_SLOW, default=d.get(CONF_POLL_INTERVAL_SLOW, DEFAULT_POLL_INTERVAL_SLOW)): int,
        vol.Optional(CONF_ENABLE_SCHEDULES, default=d.get(CONF_ENABLE_SCHEDULES, DEFAULT_ENABLE_SCHEDULES)): bool,
        vol.Optional(CONF_ENABLE_IMAGES, default=d.get(CONF_ENABLE_IMAGES, DEFAULT_ENABLE_IMAGES)): bool,
        vol.Optional(CONF_ENABLE_VOLUMES, default=d.get(CONF_ENABLE_VOLUMES, DEFAULT_ENABLE_VOLUMES)): bool,
        vol.Optional(CONF_ENABLE_NETWORKS, default=d.get(CONF_ENABLE_NETWORKS, DEFAULT_ENABLE_NETWORKS)): bool,
        vol.Optional(CONF_VERIFY_SSL, default=d.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)): bool,
    })


def _reconfigure_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema({
        vol.Required(CONF_API_URL, default=d.get(CONF_API_URL, "")): str,
        vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): str,
        vol.Optional(CONF_PASSWORD): str,  # blank = keep existing
        vol.Optional(CONF_POLL_INTERVAL, default=d.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)): int,
        vol.Optional(CONF_POLL_INTERVAL_SLOW, default=d.get(CONF_POLL_INTERVAL_SLOW, DEFAULT_POLL_INTERVAL_SLOW)): int,
        vol.Optional(CONF_ENABLE_SCHEDULES, default=d.get(CONF_ENABLE_SCHEDULES, DEFAULT_ENABLE_SCHEDULES)): bool,
        vol.Optional(CONF_ENABLE_IMAGES, default=d.get(CONF_ENABLE_IMAGES, DEFAULT_ENABLE_IMAGES)): bool,
        vol.Optional(CONF_ENABLE_VOLUMES, default=d.get(CONF_ENABLE_VOLUMES, DEFAULT_ENABLE_VOLUMES)): bool,
        vol.Optional(CONF_ENABLE_NETWORKS, default=d.get(CONF_ENABLE_NETWORKS, DEFAULT_ENABLE_NETWORKS)): bool,
        vol.Optional(CONF_VERIFY_SSL, default=d.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)): bool,
    })


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
        self._user_input: dict[str, Any] = {}
        # Tracks which flow triggered the MFA step so it can complete correctly.
        # Values: "user" | "reauth" | "reconfigure"
        self._mfa_origin: str = "user"

    # ------------------------------------------------------------------ #
    # Initial setup
    # ------------------------------------------------------------------ #

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._user_input = user_input
            self._mfa_origin = "user"

            # Use the normalised API URL as the unique ID so a second config
            # entry pointing at the same Dockhand instance is rejected.
            unique_id = user_input[CONF_API_URL].rstrip("/").lower()
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, user_input)
            try:
                cookie = await client.async_login()
                return self.async_create_entry(
                    title=user_input[CONF_API_URL],
                    data={**user_input, CONF_SESSION_COOKIE: cookie},
                )
            except DockhandMFARequiredError:
                return await self.async_step_mfa()
            except DockhandAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # MFA step — shared by user / reauth / reconfigure flows
    # ------------------------------------------------------------------ #

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            verify_ssl = self._user_input.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, self._user_input)
            try:
                cookie = await client.async_login(mfa_token=user_input["mfa_token"])

                if self._mfa_origin == "user":
                    return self.async_create_entry(
                        title=self._user_input[CONF_API_URL],
                        data={**self._user_input, CONF_SESSION_COOKIE: cookie},
                    )

                # reauth and reconfigure both update the existing entry
                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry, data={**self._user_input, CONF_SESSION_COOKIE: cookie}
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                reason = "reauth_successful" if self._mfa_origin == "reauth" else "reconfigure_successful"
                return self.async_abort(reason=reason)

            except DockhandAuthError:
                errors["base"] = "invalid_mfa"

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({"mfa_token": str}),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Re-authentication (session expired)
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
                cookie = await client.async_login()
                self.hass.config_entries.async_update_entry(
                    entry, data={**merged, CONF_SESSION_COOKIE: cookie}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except DockhandMFARequiredError:
                self._user_input = merged
                self._mfa_origin = "reauth"
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
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if user_input is not None and entry:
            password = user_input.get(CONF_PASSWORD) or entry.data.get(CONF_PASSWORD, "")
            merged = {**entry.data, **user_input, CONF_PASSWORD: password}
            verify_ssl = merged.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, merged)
            try:
                cookie = await client.async_login()
                self.hass.config_entries.async_update_entry(
                    entry, data={**merged, CONF_SESSION_COOKIE: cookie}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")
            except DockhandMFARequiredError:
                self._user_input = merged
                self._mfa_origin = "reconfigure"
                return await self.async_step_mfa()
            except DockhandAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        defaults = {**(entry.data if entry else {}), **(entry.options if entry else {})}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_schema(defaults),
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
