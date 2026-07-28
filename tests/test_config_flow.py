"""
Tests for DockhandConfigFlow and DockhandOptionsFlow (config_flow.py).

Covers:
- async_step_user: no-auth (→ setup_options → entry), auth required (→ token),
  connection error
- async_step_token: success (→ setup_options → entry), auth error, connection error,
  success (reauth origin), success (reconfigure origin)
- async_step_setup_options: covered implicitly by all full-flow tests
- async_step_reauth_confirm: success, auth error, connection error, no input shows form
- async_step_reconfigure: success (token kept), success (token cleared disables auth),
  success (new token supplied), auth-required routes to token step, connection error
- DockhandOptionsFlow: saves user_input as options
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.api import DockhandAuthError
from custom_components.dockhand.config_flow import _options_schema

BASE_CONNECTION = {
    "api_url": "http://dh.test:3000",
    "verify_ssl": True,
}

# Minimal options submitted on the setup_options step (all defaults accepted).
BASE_OPTIONS = {
    "poll_interval": 60,
    "poll_interval_slow": 600,
    "enable_schedules": False,
    "enable_images": False,
    "enable_volumes": False,
    "enable_networks": False,
    "enable_update_entities": True,
    "enable_precise_updates": False,
    "poll_interval_updates": 86400,
}

# Legacy entry data shape (poll/enable keys stored in data by older versions).
# Used in tests that exercise the options flow or migration paths.
LEGACY_ENTRY_DATA = {
    "api_url": "http://dh.test:3000",
    "verify_ssl": True,
    "poll_interval": 60,
    "poll_interval_slow": 600,
    "enable_schedules": False,
    "enable_images": False,
    "enable_volumes": False,
    "enable_networks": False,
}

MOCK_TOKEN = "dh_test_token_abc123"


def _patch_client(probe_side_effect=None):
    """Patch DockhandClient.async_probe."""
    mock_client = MagicMock()
    mock_client.async_probe = (
        AsyncMock(side_effect=probe_side_effect)
        if probe_side_effect
        else AsyncMock(return_value=None)
    )
    return patch(
        "custom_components.dockhand.config_flow.DockhandClient",
        return_value=mock_client,
    )


@contextlib.contextmanager
def _patch_full_setup():
    """Patch everything needed for async_setup_entry to succeed without network access."""
    fast = MagicMock()
    fast.data = {
        "environments": {
            1: {"stats": {}, "containers": [], "stacks": [], "container_stats": {}}
        }
    }
    fast.async_config_entry_first_refresh = AsyncMock()
    fast.async_add_listener = MagicMock(return_value=lambda: None)
    slow = MagicMock()
    slow.data = {"environments": {}, "schedules": []}
    slow.last_update_success = True
    slow.async_config_entry_first_refresh = AsyncMock()
    slow.async_add_listener = MagicMock(return_value=lambda: None)
    with (
        patch(
            "custom_components.dockhand.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        yield


# ---------------------------------------------------------------------------
# async_step_user
# ---------------------------------------------------------------------------


async def test_step_user_no_auth_creates_entry(hass: HomeAssistant):
    """Probe succeeds without token → auth disabled → setup_options → create entry."""
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "setup_options"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "api_token" not in result["data"]
    assert result["options"]["poll_interval"] == 60


async def test_step_user_strips_whitespace_from_api_url(hass: HomeAssistant):
    """Regression test: a URL with incidental leading/trailing whitespace
    (e.g. from copy-pasting) used to get stored verbatim, silently
    breaking every "open in Dockhand" link this integration ever set —
    see test_helpers.py's identical regression test for the mechanism.
    The stored entry, not just the unique_id, needs the clean value."""
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"api_url": "  http://dh.test:3000  ", "verify_ssl": True},
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["api_url"] == "http://dh.test:3000"


async def test_step_user_auth_required_redirects_to_token(hass: HomeAssistant):
    """Server returns 401 → redirect to token step."""
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "token"


async def test_step_user_connection_error_shows_cannot_connect(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client(probe_side_effect=Exception("refused")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


async def test_step_user_no_input_shows_form(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_step_user_verify_ssl_false_stored(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_CONNECTION, "verify_ssl": False}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "setup_options"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["verify_ssl"] is False


# ---------------------------------------------------------------------------
# async_step_token
# ---------------------------------------------------------------------------


async def test_step_token_success_creates_entry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    assert result["step_id"] == "token"

    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": MOCK_TOKEN}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "setup_options"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["api_token"] == MOCK_TOKEN
    assert result["data"]["api_url"] == "http://dh.test:3000"
    assert result["options"]["poll_interval"] == 60


async def test_step_token_invalid_token_shows_invalid_auth(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )

    with _patch_client(probe_side_effect=DockhandAuthError("bad token")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": "dh_bad"}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_step_token_connection_error_shows_cannot_connect(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )

    with _patch_client(probe_side_effect=Exception("refused")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": MOCK_TOKEN}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


# ---------------------------------------------------------------------------
# async_step_reauth_confirm
# ---------------------------------------------------------------------------


async def test_step_reauth_confirm_success(hass: HomeAssistant):
    """Happy-path reauth: valid token → reauth_successful."""
    # First create an entry to reauth against
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    entry = result["result"]

    # Now initiate reauth
    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reauth", "entry_id": entry.entry_id},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": "dh_newtoken"}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


async def test_step_reauth_confirm_invalid_token(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    entry = result["result"]

    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reauth", "entry_id": entry.entry_id},
    )
    with _patch_client(probe_side_effect=DockhandAuthError("bad")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": "dh_bad"}
        )
    assert result["errors"]["base"] == "invalid_auth"


async def test_step_reauth_confirm_no_input_shows_form(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    entry = result["result"]

    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reauth", "entry_id": entry.entry_id},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


# ---------------------------------------------------------------------------
# async_step_reconfigure
# ---------------------------------------------------------------------------


async def test_step_reconfigure_no_auth_strips_token(hass: HomeAssistant):
    """Blank token + probe succeeds → strip any stored token, update entry."""
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": MOCK_TOKEN}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data.get("api_token") == MOCK_TOKEN

    # Reconfigure with blank token — server no longer requires auth.
    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_CONNECTION, "api_token": ""}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert "api_token" not in entry.data


async def test_step_reconfigure_clearing_token_disables_auth(hass: HomeAssistant):
    """Clearing the token field → probe without auth → if probe succeeds, strip token."""
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": MOCK_TOKEN}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    entry = result["result"]
    assert entry.data.get("api_token") == MOCK_TOKEN

    # Clear the token — server no longer requires auth.
    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_CONNECTION, "api_token": ""}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    # Token must be removed since probe succeeded without auth.
    assert "api_token" not in entry.data


async def test_step_reconfigure_new_token_replaces_existing(hass: HomeAssistant):
    """Supplying a new token replaces the stored one after a successful probe."""
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_token": MOCK_TOKEN}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    entry = result["result"]

    new_token = "dh_new_token_xyz789"
    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_CONNECTION, "api_token": new_token}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data.get("api_token") == new_token


async def test_step_reconfigure_auth_required_routes_to_token(hass: HomeAssistant):
    """DockhandAuthError on reconfigure → routes to token step for re-entry."""
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    entry = result["result"]

    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    # Clear token; server still requires auth → should route to token step
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_CONNECTION, "api_token": ""}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "token"


async def test_step_reconfigure_connection_error(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_OPTIONS
    )
    entry = result["result"]

    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    with _patch_client(probe_side_effect=Exception("timeout")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


# ---------------------------------------------------------------------------
# DockhandOptionsFlow
# ---------------------------------------------------------------------------


async def test_options_flow_saves_options(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain="dockhand",
        data={**LEGACY_ENTRY_DATA, "api_token": "dh_test_token"},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)

    with _patch_full_setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"poll_interval": 120}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["poll_interval"] == 120


async def test_options_flow_runtime_controls_defaults_off(hass: HomeAssistant):
    """enable_runtime_controls defaults to False when not submitted — the
    extra per-container inspect cost is opt-in only."""
    entry = MockConfigEntry(
        domain="dockhand",
        data={**LEGACY_ENTRY_DATA, "api_token": "dh_test_token"},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)

    with _patch_full_setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"poll_interval": 60}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["enable_runtime_controls"] is False


async def test_options_flow_runtime_controls_can_be_enabled(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain="dockhand",
        data={**LEGACY_ENTRY_DATA, "api_token": "dh_test_token"},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)

    with _patch_full_setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**BASE_OPTIONS, "enable_runtime_controls": True}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["enable_runtime_controls"] is True


async def test_options_flow_rejects_interval_below_minimum(hass: HomeAssistant):
    """Zero/negative poll intervals are rejected by the options schema.

    Without validation a zero interval would make the coordinator refresh
    in a tight loop and hammer the Dockhand API.
    """
    entry = MockConfigEntry(
        domain="dockhand",
        data={**LEGACY_ENTRY_DATA, "api_token": "dh_test_token"},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)

    with _patch_full_setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"poll_interval": 0}
        )


async def test_options_flow_no_input_shows_form(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain="dockhand",
        data={**LEGACY_ENTRY_DATA, "api_token": "dh_test_token"},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)

    with _patch_full_setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_change_triggers_reload(hass: HomeAssistant):
    """The actual behavior being added: a changed option should take
    effect right away (via a reload), not only on the next poll or a
    manual reload — __init__.py registers an update listener for
    exactly this. Confirmed by re-entering setup with the full mock
    still active (a real reload calls async_setup_entry again) and
    watching for a second call, not just checking the option saved."""
    entry = MockConfigEntry(
        domain="dockhand",
        data={**LEGACY_ENTRY_DATA, "api_token": "dh_test_token"},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)

    with _patch_full_setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        with patch(
            "homeassistant.config_entries.ConfigEntries.async_reload",
            wraps=hass.config_entries.async_reload,
        ) as mock_reload:
            result = await hass.config_entries.options.async_init(entry.entry_id)
            await hass.config_entries.options.async_configure(
                result["flow_id"], {"poll_interval": 120}
            )
            await hass.async_block_till_done()
            mock_reload.assert_called_once_with(entry.entry_id)


# ---------------------------------------------------------------------------
# strings.json / translations coverage: every schema field must resolve to
# a real, non-empty label — a missing translation key doesn't error
# anywhere, it just silently falls back to showing the raw snake_case
# config key in the UI. These tests can only verify that strings.json has
# non-empty values at the right JSON paths, not that HA's frontend actually
# renders them correctly — that distinction mattered for real: an attempt
# to group enable_update_entities/enable_precise_updates/poll_interval_updates
# via HA's section() helper (briefly, in an unreleased 1.8.1 dev cycle) kept
# rendering the fields inside the section as raw config keys with no text no
# matter how the translation JSON was structured, and was reverted — see
# docs/BACKLOG.md. What these tests reliably do catch is a schema field with
# no strings.json entry at all, or a locale silently missing/emptying one —
# which is exactly what caught the second bug below.
#
# _options_schema() backs TWO step_ids — config.step.setup_options (first-time
# setup) and options.step.init (Configure, reused later) — so both need their
# own full copy of the translations, and both are checked below. They drifted
# apart for real once already: config.step.setup_options was still showing
# the pre-1.8.0 "enable_updates" key and was missing enable_runtime_controls/
# enable_container_stats entirely, undetected until this test existed.
# ---------------------------------------------------------------------------

_OPTIONS_SCHEMA_STEP_PATHS = [
    ("config", "step", "setup_options"),
    ("options", "step", "init"),
]


def _walk_options_schema_fields(schema):
    """Return (top_level_field_names, {section_name: [nested_field_names]})
    for the options schema — including reaching inside any section()
    wrapper, since those fields still need flat top-level translations
    (only the section's own name/description are looked up separately,
    under "sections") per how HA's frontend actually resolves labels for
    fields inside a section."""
    from homeassistant.data_entry_flow import section as ha_section

    top_level: list[str] = []
    sections: dict[str, list[str]] = {}
    for key, validator in schema.schema.items():
        name = str(key)
        if isinstance(validator, ha_section):
            sections[name] = [str(k) for k in validator.schema.schema]
        else:
            top_level.append(name)
    return top_level, sections


def _get_path(d: dict, path: tuple[str, ...]) -> dict:
    for part in path:
        d = d.get(part, {})
    return d


def _load_strings() -> dict:
    strings_path = (
        Path(__file__).parent.parent / "custom_components" / "dockhand" / "strings.json"
    )
    with open(strings_path, encoding="utf-8") as f:
        return json.load(f)


def test_options_schema_fields_have_non_empty_translations():
    strings = _load_strings()
    top_level, sections = _walk_options_schema_fields(_options_schema())
    all_field_names = list(top_level)
    for nested in sections.values():
        all_field_names.extend(nested)

    for step_path in _OPTIONS_SCHEMA_STEP_PATHS:
        step = _get_path(strings, step_path)
        data = step.get("data", {})
        section_strings = step.get("sections", {})
        step_id = ".".join(step_path)

        # Every field — whether top-level or living inside a section — must
        # have a non-empty label. data_description is a nice-to-have (some
        # simple fields like poll intervals could reasonably skip it), so
        # that's checked separately and more leniently below.
        missing_labels = [
            name for name in all_field_names if not (data.get(name) or "").strip()
        ]
        assert not missing_labels, (
            f"Missing/empty strings.json 'data' label under {step_id} for "
            f"options field(s): {missing_labels} — these will render as raw "
            f"config keys in the UI."
        )

        # Every section itself needs a non-empty name (and, since we always
        # write one, a description) — this is the header text, checked
        # separately from its fields' own labels above.
        for section_name in sections:
            section_entry = section_strings.get(section_name) or {}
            assert (section_entry.get("name") or "").strip(), (
                f"Missing/empty strings.json '{step_id}.sections.{section_name}.name' "
                f"— the section header will render blank or fall back to the raw key."
            )


def test_options_schema_fields_have_data_description():
    """Stricter than the label check above: this integration's own
    convention (CONTRIBUTING.md) is that every option gets explanatory
    help text, not just a label — so hold every field to that bar, not
    just the ones that happen to have one today."""
    strings = _load_strings()
    top_level, sections = _walk_options_schema_fields(_options_schema())
    all_field_names = list(top_level)
    for nested in sections.values():
        all_field_names.extend(nested)

    for step_path in _OPTIONS_SCHEMA_STEP_PATHS:
        step = _get_path(strings, step_path)
        data_description = step.get("data_description", {})
        step_id = ".".join(step_path)

        missing_help_text = [
            name
            for name in all_field_names
            if not (data_description.get(name) or "").strip()
        ]
        assert not missing_help_text, (
            f"Missing/empty strings.json 'data_description' under {step_id} "
            f"for options field(s): {missing_help_text}"
        )


# ---------------------------------------------------------------------------
# Whole-tree translation coverage. Deliberately generic and exhaustive —
# walks every single leaf value strings.json defines, anywhere in the file,
# and requires each locale to have the same leaf paths with non-empty
# values. This is comprehensive by construction: it needs no updates when a
# new key is added anywhere (a new abort reason, a new entity name, a new
# option, a service field, ...) — it just diffs the tree shape against
# strings.json, which is the single source of truth. This is the test that
# caught the long-stale config.step.setup_options block (missing keys
# entirely, in every locale) in one shot. It can only verify a key exists
# with a non-empty value, not that HA's frontend resolves it to the right
# place on screen — see the note above this section for the section()
# rendering issue that check couldn't have caught either way.
# ---------------------------------------------------------------------------


def _flatten_leaves(node, prefix: str = "") -> dict[str, str]:
    """Return {dotted.path: value} for every leaf (non-dict, non-list)
    value in a nested translation structure. Lists (none currently used
    in this integration's strings, but HA's schema allows them e.g. for
    selector options) are walked by index so a missing/empty entry deep
    inside one is still caught rather than silently skipped."""
    leaves: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            leaves.update(_flatten_leaves(value, child_prefix))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            leaves.update(_flatten_leaves(value, f"{prefix}[{i}]"))
    else:
        leaves[prefix] = node
    return leaves


def test_strings_json_has_no_empty_leaf_values():
    """A mistake in strings.json itself (the source of truth) — checked
    independently of what any locale file does."""
    source = _load_strings()
    empty = [
        path
        for path, value in _flatten_leaves(source).items()
        if isinstance(value, str) and not value.strip()
    ]
    assert not empty, f"Empty string value(s) in strings.json: {empty}"


def test_translations_en_json_matches_strings_json_exactly():
    """CONTRIBUTING.md: strings.json and translations/en.json must stay
    byte-for-byte identical canonical sources."""
    base_dir = Path(__file__).parent.parent / "custom_components" / "dockhand"
    source = _load_strings()
    with open(base_dir / "translations" / "en.json", encoding="utf-8") as f:
        en = json.load(f)
    assert source == en, "strings.json and translations/en.json have drifted apart"


def test_every_locale_covers_every_strings_json_key_with_non_empty_value():
    """The comprehensive check: for every non-English locale, every leaf
    key strings.json defines must exist with a real, non-empty value.
    Nothing here is hand-picked to a particular step or section — add a
    key anywhere in strings.json and this test starts covering it
    automatically, for every locale, with no test changes required."""
    base_dir = Path(__file__).parent.parent / "custom_components" / "dockhand"
    source_leaves = _flatten_leaves(_load_strings())

    locales_dir = base_dir / "translations"
    problems: dict[str, dict[str, list[str]]] = {}
    for locale_path in sorted(locales_dir.glob("*.json")):
        if locale_path.stem == "en":
            continue
        with open(locale_path, encoding="utf-8") as f:
            locale_data = json.load(f)
        locale_leaves = _flatten_leaves(locale_data)

        missing = sorted(set(source_leaves) - set(locale_leaves))
        empty = sorted(
            path
            for path, value in locale_leaves.items()
            if path in source_leaves and isinstance(value, str) and not value.strip()
        )
        locale_problems = {}
        if missing:
            locale_problems["missing"] = missing
        if empty:
            locale_problems["empty"] = empty
        if locale_problems:
            problems[locale_path.stem] = locale_problems

    assert not problems, (
        f"Locale file(s) missing or with empty values for strings.json "
        f"key(s): {problems}"
    )
