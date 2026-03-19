"""
Tests for DockhandConfigFlow and DockhandOptionsFlow (config_flow.py).

Covers:
- async_step_user: auth disabled (no credentials needed), auth required (→ credentials),
  connection error
- async_step_credentials: success (user origin), MFA redirect, auth error,
  success (reauth origin), success (reconfigure origin)
- async_step_mfa: success (user origin), auth error, success (reauth origin)
- async_step_reauth_confirm: success, MFA redirect, auth error
- async_step_reconfigure: auth disabled (strips credentials), auth required (→ credentials),
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
from custom_components.dockhand.api import DockhandAuthError, DockhandMFARequiredError
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

BASE_CREDENTIALS = {
    "username": "admin",
    "password": "secret",
}

BASE_INPUT = {**BASE_CONNECTION, **BASE_CREDENTIALS}

EXISTING_ENTRY = ConfigEntry(
    entry_id="existing_entry",
    data={**BASE_INPUT, "session_cookie": "old_cookie"},
)


def _flow() -> DockhandConfigFlow:
    """Create a flow instance with a stub hass that has the existing entry."""
    entry = ConfigEntry(
        entry_id="existing_entry",
        data={**BASE_INPUT, "session_cookie": "old_cookie"},
    )
    flow = DockhandConfigFlow()
    flow.hass.config_entries._entries["existing_entry"] = entry
    flow.context = {"entry_id": "existing_entry"}
    return flow


def _patch_client(login_return=None, login_side_effect=None,
                  environments_return=None, environments_side_effect=None):
    """Patch DockhandClient for both login and environments calls."""
    mock_client = MagicMock()
    if login_side_effect:
        mock_client.async_login = AsyncMock(side_effect=login_side_effect)
    else:
        mock_client.async_login = AsyncMock(return_value=login_return or "cookie123")
    if environments_side_effect:
        mock_client.async_get_environments = AsyncMock(side_effect=environments_side_effect)
    else:
        mock_client.async_get_environments = AsyncMock(return_value=environments_return or [])
    return patch(
        "custom_components.dockhand.config_flow.DockhandClient",
        return_value=mock_client,
    )


# ── async_step_user ───────────────────────────────────────────────────────────

class TestStepUser(unittest.TestCase):

    def test_no_auth_creates_entry_directly(self):
        """Server responds without 401 → auth disabled → create entry immediately."""
        with _patch_client():  # environments succeeds, no login needed
            result = run(_flow().async_step_user(BASE_CONNECTION))
        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn("session_cookie", result["data"])
        self.assertNotIn("username", result["data"])

    def test_auth_required_redirects_to_credentials(self):
        """Server returns 401 → redirect to credentials step."""
        with _patch_client(environments_side_effect=DockhandAuthError("401")):
            result = run(_flow().async_step_user(BASE_CONNECTION))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "credentials")

    def test_connection_error_shows_cannot_connect(self):
        with _patch_client(environments_side_effect=Exception("refused")):
            result = run(_flow().async_step_user(BASE_CONNECTION))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "cannot_connect")

    def test_no_input_shows_form(self):
        result = run(_flow().async_step_user(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "user")

    def test_duplicate_aborts(self):
        flow = _flow()
        def _abort(): raise Exception("already_configured")
        flow._abort_if_unique_id_configured = _abort
        with _patch_client():
            with self.assertRaises(Exception):
                run(flow.async_step_user(BASE_CONNECTION))

    def test_verify_ssl_false_stored_in_entry(self):
        ssl_input = {**BASE_CONNECTION, "verify_ssl": False}
        with _patch_client():
            result = run(_flow().async_step_user(ssl_input))
        self.assertEqual(result["type"], "create_entry")
        self.assertFalse(result["data"].get("verify_ssl"))


# ── async_step_credentials ────────────────────────────────────────────────────

class TestStepCredentials(unittest.TestCase):

    def _flow_at_credentials(self, origin="user"):
        """Return a flow already at the credentials step."""
        flow = _flow()
        flow._connection_data = {**BASE_CONNECTION}
        flow._flow_origin = origin
        return flow

    def test_success_creates_entry_from_user_origin(self):
        flow = self._flow_at_credentials("user")
        with _patch_client("tok"):
            result = run(flow.async_step_credentials(BASE_CREDENTIALS))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["session_cookie"], "tok")
        self.assertEqual(result["data"]["username"], "admin")

    def test_mfa_required_redirects_to_mfa(self):
        flow = self._flow_at_credentials("user")
        with _patch_client(login_side_effect=DockhandMFARequiredError("mfa")):
            result = run(flow.async_step_credentials(BASE_CREDENTIALS))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "mfa")
        # Credentials must be saved into _connection_data so async_step_mfa
        # can build a client with username+password to submit the TOTP token.
        self.assertEqual(flow._connection_data.get("username"), "admin")
        self.assertEqual(flow._connection_data.get("password"), "secret")

    def test_auth_error_shows_invalid_auth(self):
        flow = self._flow_at_credentials("user")
        with _patch_client(login_side_effect=DockhandAuthError("bad")):
            result = run(flow.async_step_credentials(BASE_CREDENTIALS))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "invalid_auth")

    def test_no_input_shows_form(self):
        flow = self._flow_at_credentials("user")
        result = run(flow.async_step_credentials(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "credentials")

    def test_reauth_origin_aborts_with_reauth_successful(self):
        flow = self._flow_at_credentials("reauth")
        flow._connection_data = {**BASE_INPUT, "session_cookie": "old"}
        with _patch_client("new_tok"):
            result = run(flow.async_step_credentials(BASE_CREDENTIALS))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reauth_successful")

    def test_reconfigure_origin_aborts_with_reconfigure_successful(self):
        flow = self._flow_at_credentials("reconfigure")
        flow._connection_data = {**BASE_INPUT, "session_cookie": "old"}
        with _patch_client("new_tok"):
            result = run(flow.async_step_credentials(BASE_CREDENTIALS))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")


# ── async_step_mfa ────────────────────────────────────────────────────────────

class TestStepMfa(unittest.TestCase):

    def _flow_at_mfa(self, origin="user"):
        flow = _flow()
        flow._connection_data = {**BASE_INPUT}
        flow._flow_origin = origin
        return flow

    def test_success_creates_entry(self):
        flow = self._flow_at_mfa("user")
        with _patch_client("tok"):
            result = run(flow.async_step_mfa({"mfa_token": "123456"}))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["session_cookie"], "tok")

    def test_auth_error_shows_invalid_mfa(self):
        flow = self._flow_at_mfa("user")
        with _patch_client(login_side_effect=DockhandAuthError("bad mfa")):
            result = run(flow.async_step_mfa({"mfa_token": "000"}))
        self.assertEqual(result["errors"]["base"], "invalid_mfa")

    def test_no_input_shows_form(self):
        result = run(self._flow_at_mfa().async_step_mfa(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "mfa")

    def test_reauth_origin_aborts_with_reauth_successful(self):
        flow = self._flow_at_mfa("reauth")
        with _patch_client("new_tok"):
            result = run(flow.async_step_mfa({"mfa_token": "123456"}))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reauth_successful")


# ── async_step_reauth_confirm ─────────────────────────────────────────────────

class TestStepReauth(unittest.TestCase):

    def test_success_aborts_with_reauth_successful(self):
        flow = _flow()
        with _patch_client("new_tok"):
            result = run(flow.async_step_reauth_confirm({
                "username": "admin", "password": "newpass"
            }))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reauth_successful")

    def test_mfa_required_redirects_to_mfa(self):
        flow = _flow()
        with _patch_client(login_side_effect=DockhandMFARequiredError("mfa")):
            result = run(flow.async_step_reauth_confirm({
                "username": "admin", "password": "pass"
            }))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "mfa")

    def test_auth_error_shows_invalid_auth(self):
        flow = _flow()
        with _patch_client(login_side_effect=DockhandAuthError("bad")):
            result = run(flow.async_step_reauth_confirm({
                "username": "admin", "password": "wrong"
            }))
        self.assertEqual(result["errors"]["base"], "invalid_auth")

    def test_no_input_shows_form(self):
        result = run(_flow().async_step_reauth_confirm(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "reauth_confirm")


# ── async_step_reconfigure ────────────────────────────────────────────────────

class TestStepReconfigure(unittest.TestCase):

    def test_auth_disabled_strips_credentials_and_succeeds(self):
        """Server responds without 401 → strip stored credentials, update entry."""
        flow = _flow()
        with _patch_client():  # environments succeeds
            result = run(flow.async_step_reconfigure(BASE_CONNECTION))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")
        updated = flow.hass.config_entries._entries["existing_entry"].data
        self.assertNotIn("username", updated)
        self.assertNotIn("password", updated)
        self.assertNotIn("session_cookie", updated)

    def test_auth_required_redirects_to_credentials(self):
        """Server returns 401 → redirect to credentials step."""
        flow = _flow()
        with _patch_client(environments_side_effect=DockhandAuthError("401")):
            result = run(flow.async_step_reconfigure(BASE_CONNECTION))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "credentials")

    def test_auth_required_then_credentials_updates_entry(self):
        """Full reconfigure with auth: connection → credentials → success."""
        flow = _flow()
        with _patch_client(environments_side_effect=DockhandAuthError("401")):
            run(flow.async_step_reconfigure(BASE_CONNECTION))
        with _patch_client("new_tok"):
            result = run(flow.async_step_credentials(BASE_CREDENTIALS))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")

    def test_blank_password_uses_existing(self):
        """Blank password during reconfigure keeps the stored password."""
        flow = _flow()
        # First trigger the 401 to reach credentials
        with _patch_client(environments_side_effect=DockhandAuthError("401")):
            run(flow.async_step_reconfigure(BASE_CONNECTION))
        # Submit with blank password — should use existing "secret" from entry
        with _patch_client("new_tok") as mock_patch:
            result = run(flow.async_step_credentials({"username": "admin", "password": ""}))
        self.assertEqual(result["type"], "abort")
        # password in _connection_data should fall back to stored value
        self.assertEqual(flow._connection_data.get("password"), "secret")

    def test_connection_error_shows_error(self):
        flow = _flow()
        with _patch_client(environments_side_effect=Exception("timeout")):
            result = run(flow.async_step_reconfigure(BASE_CONNECTION))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "cannot_connect")

    def test_mfa_required_redirects(self):
        flow = _flow()
        with _patch_client(environments_side_effect=DockhandAuthError("401")):
            run(flow.async_step_reconfigure(BASE_CONNECTION))
        with _patch_client(login_side_effect=DockhandMFARequiredError("mfa")):
            result = run(flow.async_step_credentials(BASE_CREDENTIALS))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "mfa")

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
