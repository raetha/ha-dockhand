"""
Tests for DockhandConfigFlow and DockhandOptionsFlow (config_flow.py).

Covers:
- async_step_user: no-auth (probe succeeds, entry created), auth required (→ token),
  connection error
- async_step_token: success (user origin), auth error, connection error,
  success (reauth/reconfigure origins)
- async_step_reauth_confirm: success, auth error, connection error, no input shows form
- async_step_reconfigure: no-auth (strips token), auth required (→ token), connection error
- DockhandOptionsFlow: saves user_input as options
"""

from __future__ import annotations

import contextlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dockhand.api import DockhandAuthError

BASE_CONNECTION = {
    "api_url": "http://dh.test:3000",
    "poll_interval": 60,
    "poll_interval_slow": 600,
    "enable_schedules": False,
    "enable_images": False,
    "enable_volumes": False,
    "enable_networks": False,
    "verify_ssl": True,
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
    fast.data = {1: {"stats": {}, "containers": [], "stacks": [], "container_stats": {}}}
    fast.async_config_entry_first_refresh = AsyncMock()
    fast.async_add_listener = MagicMock(return_value=lambda: None)
    slow = MagicMock()
    slow.data = {"environments": {}, "schedules": []}
    slow.last_update_success = True
    slow.async_config_entry_first_refresh = AsyncMock()
    slow.async_add_listener = MagicMock(return_value=lambda: None)
    with (
        patch("custom_components.dockhand.async_get_clientsession", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandClient", return_value=MagicMock()),
        patch("custom_components.dockhand.DockhandFastCoordinator", return_value=fast),
        patch("custom_components.dockhand.DockhandSlowCoordinator", return_value=slow),
    ):
        yield


# ---------------------------------------------------------------------------
# async_step_user
# ---------------------------------------------------------------------------


async def test_step_user_no_auth_creates_entry(hass: HomeAssistant):
    """Probe succeeds without token → auth disabled → create entry immediately."""
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "api_token" not in result["data"]


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
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["api_token"] == MOCK_TOKEN
    assert result["data"]["api_url"] == "http://dh.test:3000"


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
    """Probe succeeds without token → strip any stored token, update entry."""
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
    assert result["type"] == FlowResultType.CREATE_ENTRY
    entry = result["result"]

    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert "api_token" not in entry.data


async def test_step_reconfigure_auth_required_redirects_to_token(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        "dockhand", context={"source": "user"}
    )
    with _patch_client():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
        )
    entry = result["result"]

    result = await hass.config_entries.flow.async_init(
        "dockhand",
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    with _patch_client(probe_side_effect=DockhandAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], BASE_CONNECTION
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
        data={**BASE_CONNECTION, "api_token": "dh_test_token"},
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


async def test_options_flow_no_input_shows_form(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain="dockhand",
        data={**BASE_CONNECTION, "api_token": "dh_test_token"},
        title="http://dh.test:3000",
    )
    entry.add_to_hass(hass)

    with _patch_full_setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
