"""
Tests for DockhandConfigFlow and DockhandOptionsFlow (config_flow.py).

Covers:
- async_step_user: no-auth (probe succeeds, entry created), auth required (→ token),
  connection error
- async_step_token: success (user origin), auth error, connection error,
  success (reauth origin), success (reconfigure origin)
- async_step_reauth_confirm: success, auth error, connection error, no input shows form
- async_step_reconfigure: no-auth (strips token), auth required (→ token),
  connection error
- DockhandOptionsFlow: saves user_input as options
"""
from __future__ import annotations
import asyncio, sys, os, unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT); sys.path.insert(0, TESTS)

import ha_stubs as stubs; stubs.install()
from ha_stubs import ConfigEntry
from custom_components.dockhand.api import DockhandAuthError
from custom_components.dockhand.config_flow import DockhandConfigFlow, DockhandOptionsFlow

run = asyncio.get_event_loop().run_until_complete

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

EXISTING_ENTRY = ConfigEntry(
    entry_id="existing_entry",
    data={**BASE_CONNECTION, "api_token": MOCK_TOKEN},
)


def _flow() -> DockhandConfigFlow:
    """Create a flow instance with a stub hass that has the existing entry."""
    entry = ConfigEntry(
        entry_id="existing_entry",
        data={**BASE_CONNECTION, "api_token": MOCK_TOKEN},
    )
    flow = DockhandConfigFlow()
    flow.hass.config_entries._entries["existing_entry"] = entry
    flow.context = {"entry_id": "existing_entry"}
    return flow


def _patch_client(probe_side_effect=None):
    """Patch DockhandClient.async_probe."""
    mock_client = MagicMock()
    if probe_side_effect:
        mock_client.async_probe = AsyncMock(side_effect=probe_side_effect)
    else:
        mock_client.async_probe = AsyncMock(return_value=None)
    return patch(
        "custom_components.dockhand.config_flow.DockhandClient",
        return_value=mock_client,
    )


# ── async_step_user ───────────────────────────────────────────────────────────

class TestStepUser(unittest.TestCase):

    def test_no_auth_creates_entry_directly(self):
        """Probe succeeds without token → auth disabled → create entry immediately."""
        with _patch_client():
            result = run(_flow().async_step_user(BASE_CONNECTION))
        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn("api_token", result["data"])

    def test_auth_required_redirects_to_token(self):
        """Server returns 401 → redirect to token step."""
        with _patch_client(probe_side_effect=DockhandAuthError("401")):
            result = run(_flow().async_step_user(BASE_CONNECTION))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "token")

    def test_connection_error_shows_cannot_connect(self):
        with _patch_client(probe_side_effect=Exception("refused")):
            result = run(_flow().async_step_user(BASE_CONNECTION))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "cannot_connect")

    def test_no_input_shows_form(self):
        result = run(_flow().async_step_user(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "user")

    def test_verify_ssl_false_stored_in_entry(self):
        ssl_input = {**BASE_CONNECTION, "verify_ssl": False}
        with _patch_client():
            result = run(_flow().async_step_user(ssl_input))
        self.assertEqual(result["type"], "create_entry")
        self.assertFalse(result["data"].get("verify_ssl"))


# ── async_step_token ──────────────────────────────────────────────────────────

class TestStepToken(unittest.TestCase):

    def _flow_at_token(self, origin="user"):
        flow = _flow()
        flow._connection_data = {**BASE_CONNECTION}
        flow._flow_origin = origin
        return flow

    def test_success_creates_entry_from_user_origin(self):
        flow = self._flow_at_token("user")
        with _patch_client():
            result = run(flow.async_step_token({"api_token": MOCK_TOKEN}))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["api_token"], MOCK_TOKEN)

    def test_invalid_token_shows_invalid_auth(self):
        flow = self._flow_at_token("user")
        with _patch_client(probe_side_effect=DockhandAuthError("bad token")):
            result = run(flow.async_step_token({"api_token": "dh_bad"}))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "invalid_auth")

    def test_connection_error_shows_cannot_connect(self):
        flow = self._flow_at_token("user")
        with _patch_client(probe_side_effect=Exception("refused")):
            result = run(flow.async_step_token({"api_token": MOCK_TOKEN}))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "cannot_connect")

    def test_no_input_shows_form(self):
        flow = self._flow_at_token("user")
        result = run(flow.async_step_token(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "token")

    def test_reauth_origin_aborts_with_reauth_successful(self):
        flow = self._flow_at_token("reauth")
        flow._connection_data = {**BASE_CONNECTION, "api_token": "dh_old"}
        with _patch_client():
            result = run(flow.async_step_token({"api_token": "dh_new"}))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reauth_successful")

    def test_reconfigure_origin_aborts_with_reconfigure_successful(self):
        flow = self._flow_at_token("reconfigure")
        flow._connection_data = {**BASE_CONNECTION, "api_token": "dh_old"}
        with _patch_client():
            result = run(flow.async_step_token({"api_token": "dh_new"}))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")

    def test_token_merged_into_connection_data(self):
        """Token provided in step_token must be present in the created entry."""
        flow = self._flow_at_token("user")
        with _patch_client():
            result = run(flow.async_step_token({"api_token": "dh_specific"}))
        self.assertEqual(result["data"]["api_token"], "dh_specific")
        # Connection settings must also be carried through
        self.assertEqual(result["data"]["api_url"], "http://dh.test:3000")


# ── async_step_reauth_confirm ─────────────────────────────────────────────────

class TestStepReauth(unittest.TestCase):

    def test_success_aborts_with_reauth_successful(self):
        flow = _flow()
        with _patch_client():
            result = run(flow.async_step_reauth_confirm({"api_token": "dh_newtoken"}))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reauth_successful")

    def test_invalid_token_shows_invalid_auth(self):
        flow = _flow()
        with _patch_client(probe_side_effect=DockhandAuthError("bad")):
            result = run(flow.async_step_reauth_confirm({"api_token": "dh_bad"}))
        self.assertEqual(result["errors"]["base"], "invalid_auth")

    def test_connection_error_shows_cannot_connect(self):
        flow = _flow()
        with _patch_client(probe_side_effect=Exception("refused")):
            result = run(flow.async_step_reauth_confirm({"api_token": "dh_tok"}))
        self.assertEqual(result["errors"]["base"], "cannot_connect")

    def test_no_input_shows_form(self):
        result = run(_flow().async_step_reauth_confirm(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "reauth_confirm")


# ── async_step_reconfigure ────────────────────────────────────────────────────

class TestStepReconfigure(unittest.TestCase):

    def test_auth_disabled_strips_token_and_succeeds(self):
        """Probe succeeds without token → strip any stored token, update entry."""
        flow = _flow()
        with _patch_client():
            result = run(flow.async_step_reconfigure(BASE_CONNECTION))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")
        updated = flow.hass.config_entries._entries["existing_entry"].data
        self.assertNotIn("api_token", updated)

    def test_auth_required_redirects_to_token(self):
        """Server returns 401 → redirect to token step."""
        flow = _flow()
        with _patch_client(probe_side_effect=DockhandAuthError("401")):
            result = run(flow.async_step_reconfigure(BASE_CONNECTION))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "token")

    def test_auth_required_then_token_updates_entry(self):
        """Full reconfigure with auth: connection → token → success."""
        flow = _flow()
        with _patch_client(probe_side_effect=DockhandAuthError("401")):
            run(flow.async_step_reconfigure(BASE_CONNECTION))
        with _patch_client():
            result = run(flow.async_step_token({"api_token": "dh_new"}))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")

    def test_connection_error_shows_error(self):
        flow = _flow()
        with _patch_client(probe_side_effect=Exception("timeout")):
            result = run(flow.async_step_reconfigure(BASE_CONNECTION))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "cannot_connect")

    def test_no_input_shows_form(self):
        result = run(_flow().async_step_reconfigure(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "reconfigure")


# ── DockhandOptionsFlow ───────────────────────────────────────────────────────

class TestOptionsFlow(unittest.TestCase):

    def test_saves_options(self):
        flow = DockhandOptionsFlow(EXISTING_ENTRY)
        result = run(flow.async_step_init({"poll_interval": 120}))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["poll_interval"], 120)

    def test_no_input_shows_form(self):
        flow = DockhandOptionsFlow(EXISTING_ENTRY)
        result = run(flow.async_step_init(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")


if __name__ == "__main__":
    unittest.main()
