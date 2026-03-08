"""
Tests for DockhandConfigFlow and DockhandOptionsFlow (config_flow.py).

Covers:
- async_step_user: success, MFA redirect, auth error, connection error, duplicate
- async_step_mfa: success (user origin), auth error
- async_step_reauth_confirm: success, MFA redirect, auth error
- async_step_reconfigure: success, reuse existing password, MFA redirect, auth error
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

BASE_INPUT = {
    "api_url": "http://dh.test:3000",
    "username": "admin",
    "password": "secret",
    "poll_interval": 60,
    "poll_interval_slow": 600,
    "enable_schedules": False,
    "enable_images": False,
    "enable_volumes": False,
    "enable_networks": False,
    "verify_ssl": True,
}

EXISTING_ENTRY = ConfigEntry(
    entry_id="existing_entry",
    data={**BASE_INPUT, "session_cookie": "old_cookie"},
)


def _flow() -> DockhandConfigFlow:
    """Create a flow instance with a stub hass that has the existing entry."""
    # Create a fresh ConfigEntry each call — tests that call async_update_entry
    # on the stub mutate the entry object, and a shared module-level entry would
    # bleed state between tests.
    entry = ConfigEntry(
        entry_id="existing_entry",
        data={**BASE_INPUT, "session_cookie": "old_cookie"},
    )
    flow = DockhandConfigFlow()
    flow.hass.config_entries._entries["existing_entry"] = entry
    flow.context = {"entry_id": "existing_entry"}
    return flow


def _patch_client(login_return=None, login_side_effect=None):
    """Patch DockhandClient so async_login returns/raises as specified."""
    mock_client = MagicMock()
    if login_side_effect:
        mock_client.async_login = AsyncMock(side_effect=login_side_effect)
    else:
        mock_client.async_login = AsyncMock(return_value=login_return or "cookie123")
    return patch(
        "custom_components.dockhand.config_flow.DockhandClient",
        return_value=mock_client,
    )


# ── async_step_user ───────────────────────────────────────────────────────────

class TestStepUser(unittest.TestCase):

    def test_success_creates_entry(self):
        with _patch_client("tok"):
            result = run(_flow().async_step_user(BASE_INPUT))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["session_cookie"], "tok")

    def test_mfa_required_redirects_to_mfa_step(self):
        with _patch_client(login_side_effect=DockhandMFARequiredError("mfa")):
            result = run(_flow().async_step_user(BASE_INPUT))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "mfa")

    def test_auth_error_shows_invalid_auth(self):
        with _patch_client(login_side_effect=DockhandAuthError("bad")):
            result = run(_flow().async_step_user(BASE_INPUT))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "invalid_auth")

    def test_connection_error_shows_cannot_connect(self):
        with _patch_client(login_side_effect=Exception("refused")):
            result = run(_flow().async_step_user(BASE_INPUT))
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
        with _patch_client("tok"):
            with self.assertRaises(Exception):
                run(flow.async_step_user(BASE_INPUT))

    def test_verify_ssl_false_stored_in_entry(self):
        """verify_ssl=False should be stored in the config entry data."""
        ssl_input = {**BASE_INPUT, "verify_ssl": False}
        with _patch_client("tok"):
            result = run(_flow().async_step_user(ssl_input))
        self.assertEqual(result["type"], "create_entry")
        self.assertFalse(result["data"].get("verify_ssl"))


# ── async_step_mfa ────────────────────────────────────────────────────────────

class TestStepMfa(unittest.TestCase):

    def test_success_creates_entry(self):
        flow = _flow()
        flow._user_input = BASE_INPUT
        flow._mfa_origin = "user"
        with _patch_client("tok"):
            result = run(flow.async_step_mfa({"mfa_token": "123456"}))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["session_cookie"], "tok")

    def test_auth_error_shows_invalid_mfa(self):
        flow = _flow()
        flow._user_input = BASE_INPUT
        with _patch_client(login_side_effect=DockhandAuthError("bad mfa")):
            result = run(flow.async_step_mfa({"mfa_token": "000"}))
        self.assertEqual(result["errors"]["base"], "invalid_mfa")

    def test_no_input_shows_form(self):
        result = run(_flow().async_step_mfa(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "mfa")

    def test_reauth_origin_aborts_with_reauth_successful(self):
        flow = _flow()
        flow._user_input = {**BASE_INPUT, "session_cookie": "old"}
        flow._mfa_origin = "reauth"
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
                "username": "admin", "password": "secret"
            }))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "mfa")
        self.assertEqual(flow._mfa_origin, "reauth")

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

    def test_success_aborts_with_reconfigure_successful(self):
        flow = _flow()
        with _patch_client("new_tok"):
            result = run(flow.async_step_reconfigure({
                **BASE_INPUT, "password": "newpass"
            }))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "reconfigure_successful")

    def test_blank_password_uses_existing(self):
        """Empty password in reconfigure should reuse stored password."""
        flow = _flow()
        captured = {}
        mock_client = MagicMock()
        mock_client.async_login = AsyncMock(return_value="tok")
        def _capture_init(session, config):
            captured["config"] = config
            return mock_client
        with patch("custom_components.dockhand.config_flow.DockhandClient",
                   side_effect=_capture_init):
            run(flow.async_step_reconfigure({**BASE_INPUT, "password": ""}))
        # The merged config should contain the original password from the entry
        self.assertEqual(captured["config"].get("password"), "secret")

    def test_mfa_required_redirects(self):
        flow = _flow()
        with _patch_client(login_side_effect=DockhandMFARequiredError("mfa")):
            result = run(flow.async_step_reconfigure({**BASE_INPUT}))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "mfa")
        self.assertEqual(flow._mfa_origin, "reconfigure")

    def test_auth_error_shows_error(self):
        flow = _flow()
        with _patch_client(login_side_effect=DockhandAuthError("bad")):
            result = run(flow.async_step_reconfigure({**BASE_INPUT}))
        self.assertEqual(result["errors"]["base"], "invalid_auth")

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
