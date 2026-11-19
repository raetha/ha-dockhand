from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import DockhandConfigEntry
from .api import DockhandAuthError, DockhandClient
from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_PRECISE_UPDATES,
    CONF_ENABLE_RESOURCE_STATS,
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_UPDATE_ENTITIES,
    CONF_ENABLE_VOLUMES,
    CONF_ENABLED_ENTITIES,
    CONF_VERIFY_SSL,
    DEFAULT_ENABLE_IMAGES,
    DEFAULT_ENABLE_NETWORKS,
    DEFAULT_ENABLE_PRECISE_UPDATES,
    DEFAULT_ENABLE_RESOURCE_STATS,
    DEFAULT_ENABLE_RUNTIME_CONTROLS,
    DEFAULT_ENABLE_SCHEDULES,
    DEFAULT_ENABLE_UPDATE_ENTITIES,
    DEFAULT_ENABLE_VOLUMES,
    DOMAIN,
    SCHEMA_MINOR_VERSION,
    SCHEMA_VERSION,
)
from .entity_defaults import OPTIONAL_ENTITIES, async_apply_choice, chosen
from .helpers import ha_schema

DEFAULT_VERIFY_SSL = True


_form = ha_schema


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Initial setup step: URL and SSL only. Token collected separately if needed."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_API_URL, default=d.get(CONF_API_URL, "")): str,
            vol.Optional(
                CONF_VERIFY_SSL, default=d.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            ): bool,
        }
    )


def _reconfigure_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """Reconfigure step: URL, SSL, and token.

    The token field is pre-populated (masked) with the existing token so the
    user can see one is stored.  Clearing it and submitting will probe without
    auth — if the server still requires it, the user will be prompted again.
    """
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_API_URL, default=d.get(CONF_API_URL, "")): str,
            vol.Optional(
                CONF_VERIFY_SSL, default=d.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            ): bool,
            vol.Optional(
                CONF_API_TOKEN, default=d.get(CONF_API_TOKEN, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        }
    )


def _token_schema() -> vol.Schema:
    """Step 2: API token — only shown when server requires authentication."""
    return vol.Schema(
        {
            vol.Required(CONF_API_TOKEN): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


def _entity_sections(options: Mapping[str, Any]) -> dict[Any, Any]:
    """One collapsed section per device kind: the disabled-by-default entity
    types to turn on for every device of that kind (entity_defaults.py),
    with an "All" box where there's more than one, since Home Assistant's
    checkbox list has no select all."""
    current = chosen(options)
    return {
        vol.Optional(f"{kind}_entities"): section(
            _form(
                vol.Schema(
                    {
                        **(
                            {
                                vol.Optional(
                                    "all", default=current[kind] == set(keys)
                                ): bool
                            }
                            if len(keys) > 1
                            else {}
                        ),
                        vol.Optional(
                            "enabled", default=[k for k in keys if k in current[kind]]
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=list(keys),
                                multiple=True,
                                mode=SelectSelectorMode.LIST,
                                translation_key=f"{kind}_entities",
                            )
                        ),
                    }
                )
            ),
            {"collapsed": True},
        )
        for kind, keys in OPTIONAL_ENTITIES.items()
    }


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
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
                CONF_ENABLE_RESOURCE_STATS,
                default=d.get(
                    CONF_ENABLE_RESOURCE_STATS, DEFAULT_ENABLE_RESOURCE_STATS
                ),
            ): bool,
            # Directly above enable_precise_updates, which refines it. Not
            # grouped with section(): see docs/backlog.md.
            vol.Optional(
                CONF_ENABLE_UPDATE_ENTITIES,
                default=d.get(
                    CONF_ENABLE_UPDATE_ENTITIES, DEFAULT_ENABLE_UPDATE_ENTITIES
                ),
            ): bool,
            vol.Optional(
                CONF_ENABLE_PRECISE_UPDATES,
                default=d.get(
                    CONF_ENABLE_PRECISE_UPDATES, DEFAULT_ENABLE_PRECISE_UPDATES
                ),
            ): bool,
            # Last: the only setting that adds controls which change a
            # container's configuration.
            vol.Optional(
                CONF_ENABLE_RUNTIME_CONTROLS,
                default=d.get(
                    CONF_ENABLE_RUNTIME_CONTROLS, DEFAULT_ENABLE_RUNTIME_CONTROLS
                ),
            ): bool,
        }
    )


def _unique_id(api_url: str) -> str:
    return api_url.rstrip("/").lower()


class DockhandConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    # Set in const.py, where the rename rules that depend on them live.
    VERSION = SCHEMA_VERSION
    MINOR_VERSION = SCHEMA_MINOR_VERSION

    def __init__(self) -> None:
        # Accumulates data across multi-step flows.
        self._connection_data: dict[str, Any] = {}
        # Stores confirmed connection data while the setup_options step runs.
        self._confirmed_data: dict[str, Any] = {}
        # Tracks which flow triggered the token step: "user" or "reconfigure".
        # (Re-authentication has its own token form, reauth_confirm.)
        self._flow_origin: str = "user"

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: DockhandConfigEntry,
    ) -> DockhandOptionsFlow:
        """Return the options flow handler."""
        return DockhandOptionsFlow(config_entry)

    # ------------------------------------------------------------------ #
    # Step 1: connection settings (URL + SSL only)
    # ------------------------------------------------------------------ #

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """First step: URL and settings. Probe server to detect auth requirement."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Stripped here, once, rather than at each of the several
            # places this value gets used below (unique_id, the API
            # client, the stored config entry) — a URL with incidental
            # leading/trailing whitespace (e.g. from copy-pasting) would
            # otherwise get baked into every device's configuration_url
            # this integration ever sets, silently breaking every
            # "open in Dockhand" link without any visible error anywhere.
            user_input[CONF_API_URL] = user_input[CONF_API_URL].strip()
            await self.async_set_unique_id(_unique_id(user_input[CONF_API_URL]))
            self._abort_if_unique_id_configured()

            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, user_input)
            try:
                await client.async_probe()
                # Probe succeeded with no token — auth is disabled.
                # Proceed to the options step to collect feature preferences.
                self._confirmed_data = user_input
                return await self.async_step_setup_options()
            except DockhandAuthError:
                # Server requires authentication — proceed to token step.
                self._connection_data = user_input
                self._flow_origin = "user"
                return await self.async_step_token()
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=_form(_connection_schema(user_input or {})),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Step 2: API token (only reached when server returned 401)
    # ------------------------------------------------------------------ #

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
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
                    # Connection confirmed with token — collect options next.
                    self._confirmed_data = merged
                    return await self.async_step_setup_options()

                # Reconfigure, the only other way here.
                return self._finish_reconfigure(merged)

            except DockhandAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="token",
            data_schema=_form(_token_schema()),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Re-authentication (token revoked / auth re-enabled on no-auth install)
    # ------------------------------------------------------------------ #

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if user_input is not None and entry:
            merged = {**entry.data, **user_input}
            verify_ssl = merged.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = DockhandClient(session, merged)
            try:
                await client.async_probe()
                # async_update_entry() alone triggers a reload via
                # __init__.py's update listener now — an explicit reload
                # here would be redundant.
                self.hass.config_entries.async_update_entry(entry, data=merged)
                return self.async_abort(reason="reauth_successful")
            except DockhandAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_form(_token_schema()),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Step 3: optional features (initial setup only)
    # ------------------------------------------------------------------ #

    async def async_step_setup_options(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect feature flags during initial setup.

        Stores them directly into entry.options so the Options flow can
        present and edit them without touching entry.data.
        """
        if user_input is not None:
            return self.async_create_entry(
                title=self._confirmed_data[CONF_API_URL],
                data=self._confirmed_data,
                options=user_input,
            )
        return self.async_show_form(
            step_id="setup_options",
            data_schema=_form(_options_schema()),
        )

    # ------------------------------------------------------------------ #
    # Reconfigure (change URL, SSL, or token; features in Options)
    # ------------------------------------------------------------------ #

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reconfigure connection settings (URL, SSL, token).

        The token field is pre-populated with the existing token (masked).
        - Leave as-is or change it → probe with that token
        - Clear it → probe without auth; if server still requires auth, route
          to the token step so the user can re-enter one
        Feature flags live in the Options flow.
        """
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            user_input[CONF_API_URL] = user_input[CONF_API_URL].strip()
            submitted_token = (user_input.get(CONF_API_TOKEN) or "").strip()
            probe_data = {
                CONF_API_URL: user_input[CONF_API_URL],
                CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, True),
                **({CONF_API_TOKEN: submitted_token} if submitted_token else {}),
            }
            if self._url_used_elsewhere(user_input[CONF_API_URL]):
                errors["base"] = "already_configured"
            else:
                session = async_get_clientsession(
                    self.hass, verify_ssl=probe_data[CONF_VERIFY_SSL]
                )
                try:
                    await DockhandClient(session, probe_data).async_probe()
                except DockhandAuthError:
                    self._connection_data = probe_data
                    self._flow_origin = "reconfigure"
                    return await self.async_step_token()
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    # A cleared token that still probes fine means auth is off.
                    updated = {**entry.data, **probe_data}
                    if not submitted_token:
                        updated.pop(CONF_API_TOKEN, None)
                    return self._finish_reconfigure(updated)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_form(_reconfigure_schema(user_input or dict(entry.data))),
            errors=errors,
        )

    def _url_used_elsewhere(self, api_url: str) -> bool:
        """Whether another Dockhand entry already uses this URL."""
        own = self._get_reconfigure_entry().entry_id
        return any(
            other.entry_id != own and other.unique_id == _unique_id(api_url)
            for other in self._async_current_entries(include_ignore=False)
        )

    def _finish_reconfigure(
        self, data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Save new connection settings. The unique ID follows the URL so the
        old URL can be added again; the title does too, unless the user has
        renamed the entry. __init__.py's update listener reloads it."""
        entry = self._get_reconfigure_entry()
        title = entry.title
        if title == entry.data.get(CONF_API_URL):
            title = data[CONF_API_URL]
        self.hass.config_entries.async_update_entry(
            entry, data=data, unique_id=_unique_id(data[CONF_API_URL]), title=title
        )
        return self.async_abort(reason="reconfigure_successful")


def _chosen_in_section(
    answer: Mapping[str, Any], keys: tuple[str, ...], before: set[str]
) -> list[str]:
    """The types chosen in one section. Changing "All" wins over the list:
    checked, every type; unchecked, none. Otherwise the list decides."""
    was_all = before == set(keys)
    if "all" in answer and answer["all"] != was_all:
        return list(keys) if answer["all"] else []
    return list(answer.get("enabled") or [])


class DockhandOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: DockhandConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            options = dict(user_input)
            before = chosen(self._entry.options)
            options[CONF_ENABLED_ENTITIES] = {
                kind: _chosen_in_section(
                    options.pop(f"{kind}_entities", {}), keys, before[kind]
                )
                for kind, keys in OPTIONAL_ENTITIES.items()
            }
            async_apply_choice(
                self.hass, self._entry.entry_id, self._entry.options, options
            )
            return self.async_create_entry(title="", data=options)
        defaults = dict(self._entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=_form(
                _options_schema(defaults).extend(_entity_sections(defaults))
            ),
        )
