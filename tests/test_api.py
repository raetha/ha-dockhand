"""
Tests for DockhandClient (api.py).

Covers: async_login (all paths), _request (all paths),
        API endpoint URL construction, container/stack actions.
"""
from __future__ import annotations
import asyncio, sys, os, unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import ha_stubs as stubs; stubs.install()

from custom_components.dockhand.api import (
    DockhandClient, DockhandAuthError, DockhandMFARequiredError, DockhandError,
)

run = asyncio.get_event_loop().run_until_complete


def _resp(status=200, json_data=None, text="", cookies=None):
    r = MagicMock()
    r.status = status
    r.cookies = {}
    if cookies:
        for k, v in cookies.items():
            c = MagicMock(); c.value = v
            r.cookies[k] = c
    r.json = AsyncMock(return_value=json_data) if json_data is not None \
              else AsyncMock(side_effect=Exception("no json"))
    r.text = AsyncMock(return_value=text)
    return r


def _session(response):
    s = MagicMock()
    @asynccontextmanager
    async def _ctx(*a, **kw): yield response
    s.post = MagicMock(return_value=_ctx())
    s.request = MagicMock(return_value=_ctx())
    return s


def _client(session=None, cookie=None):
    return DockhandClient(session or MagicMock(), {
        "api_url": "http://dh.test:3000",
        "username": "admin", "password": "secret",
        "session_cookie": cookie,
    })


class TestLogin(unittest.TestCase):

    def test_success_returns_cookie(self):
        c = _client(_session(_resp(200, {}, cookies={"dockhand_session": "tok"})))
        self.assertEqual(run(c.async_login()), "tok")
        self.assertEqual(c._cookie, "tok")

    def test_401_no_mfa_raises_auth_error(self):
        with self.assertRaises(DockhandAuthError):
            run(_client(_session(_resp(401, {}))).async_login())

    def test_401_requires_mfa_flag_raises_mfa_error(self):
        with self.assertRaises(DockhandMFARequiredError):
            run(_client(_session(_resp(401, {"requiresMfa": True}))).async_login())

    def test_200_mfa_flag_in_body_raises_mfa_error(self):
        with self.assertRaises(DockhandMFARequiredError):
            run(_client(_session(_resp(200, {"mfaRequired": True}))).async_login())

    def test_200_missing_cookie_raises_auth_error(self):
        with self.assertRaises(DockhandAuthError) as ctx:
            run(_client(_session(_resp(200, {}))).async_login())
        self.assertIn("cookie", str(ctx.exception))

    def test_non_200_raises_auth_error(self):
        with self.assertRaises(DockhandAuthError) as ctx:
            run(_client(_session(_resp(503, text="down"))).async_login())
        self.assertIn("503", str(ctx.exception))

    def test_network_error_raises_auth_error(self):
        s = MagicMock()
        s.post = MagicMock(side_effect=Exception("refused"))
        with self.assertRaises(DockhandAuthError) as ctx:
            run(_client(s).async_login())
        self.assertIn("Unexpected error", str(ctx.exception))

    def test_mfa_token_included_in_post_body(self):
        resp = _resp(200, {}, cookies={"dockhand_session": "tok"})
        s = _session(resp)
        run(_client(s).async_login(mfa_token="999888"))
        posted = s.post.call_args.kwargs.get("json", {})
        self.assertEqual(posted.get("mfaToken"), "999888")


class TestRequest(unittest.TestCase):

    def test_no_cookie_raises(self):
        with self.assertRaises(DockhandAuthError) as ctx:
            run(_client(cookie=None)._request("GET", "/api/x"))
        self.assertIn("Not authenticated", str(ctx.exception))

    def test_401_raises_session_expired(self):
        with self.assertRaises(DockhandAuthError) as ctx:
            run(_client(_session(_resp(401)), cookie="v")._request("GET", "/api/x"))
        self.assertIn("Session expired", str(ctx.exception))

    def test_4xx_raises_dockhand_error(self):
        with self.assertRaises(DockhandError) as ctx:
            run(_client(_session(_resp(404, text="nf")), cookie="v")._request("GET", "/api/x"))
        self.assertIn("404", str(ctx.exception))

    def test_200_returns_json(self):
        r = run(_client(_session(_resp(200, {"k": "v"})), cookie="v")._request("GET", "/api/x"))
        self.assertEqual(r, {"k": "v"})

    def test_200_no_json_returns_text(self):
        r = run(_client(_session(_resp(200, text="plain")), cookie="v")._request("GET", "/api/x"))
        self.assertEqual(r, "plain")

    def test_correct_url_constructed(self):
        s = _session(_resp(200, {}))
        run(_client(s, cookie="v")._request("GET", "/api/environments"))
        url = s.request.call_args.args[1]
        self.assertEqual(url, "http://dh.test:3000/api/environments")

    def test_cookie_in_header(self):
        s = _session(_resp(200, {}))
        run(_client(s, cookie="my_token")._request("GET", "/api/x"))
        headers = s.request.call_args.kwargs.get("headers", {})
        self.assertIn("my_token", headers.get("Cookie", ""))


class TestEndpoints(unittest.TestCase):
    def setUp(self):
        self.c = _client(cookie="v")
        self.c._request = AsyncMock(return_value=[])

    def _url(self): return self.c._request.call_args.args[1]

    def test_get_environments(self):
        run(self.c.async_get_environments())
        self.assertEqual(self._url(), "/api/environments")

    def test_get_dashboard_stats(self):
        self.c._request.return_value = {}
        run(self.c.async_get_dashboard_stats(7))
        self.assertEqual(self._url(), "/api/dashboard/stats?env=7")

    def test_get_containers(self):
        run(self.c.async_get_containers(2))
        self.assertEqual(self._url(), "/api/containers?env=2")

    def test_get_stacks(self):
        run(self.c.async_get_stacks(2))
        self.assertEqual(self._url(), "/api/stacks?env=2")

    def test_get_networks(self):
        run(self.c.async_get_networks(2))
        self.assertEqual(self._url(), "/api/networks?env=2")

    def test_get_images(self):
        run(self.c.async_get_images(2))
        self.assertEqual(self._url(), "/api/images?env=2")

    def test_get_volumes(self):
        run(self.c.async_get_volumes(2))
        self.assertEqual(self._url(), "/api/volumes?env=2")

    def test_get_schedules_list(self):
        self.c._request.return_value = [{"id": "s1"}]
        r = run(self.c.async_get_schedules())
        self.assertEqual(r, [{"id": "s1"}])

    def test_get_schedules_dict_unwraps(self):
        self.c._request.return_value = {"schedules": [{"id": "s1"}]}
        r = run(self.c.async_get_schedules())
        self.assertEqual(r, [{"id": "s1"}])

    def test_get_schedules_bad_type_returns_empty(self):
        self.c._request.return_value = "oops"
        self.assertEqual(run(self.c.async_get_schedules()), [])


class TestActions(unittest.TestCase):
    def setUp(self):
        self.c = _client(cookie="v")
        self.c._request = AsyncMock(return_value=None)

    def _call(self): return self.c._request.call_args

    def test_start_container(self):
        run(self.c.async_start_container(1, "cid"))
        self.assertEqual(self._call().args, ("POST", "/api/containers/cid/start?env=1"))

    def test_stop_container(self):
        run(self.c.async_stop_container(1, "cid"))
        self.assertEqual(self._call().args, ("POST", "/api/containers/cid/stop?env=1"))

    def test_restart_container(self):
        run(self.c.async_restart_container(1, "cid"))
        self.assertEqual(self._call().args, ("POST", "/api/containers/cid/restart?env=1"))

    def test_start_stack(self):
        run(self.c.async_start_stack(1, "myapp"))
        self.assertEqual(self._call().args, ("POST", "/api/stacks/myapp/start?env=1"))

    def test_stop_stack(self):
        run(self.c.async_stop_stack(1, "myapp"))
        self.assertEqual(self._call().args, ("POST", "/api/stacks/myapp/stop?env=1"))

    def test_restart_stack(self):
        run(self.c.async_restart_stack(1, "myapp"))
        self.assertEqual(self._call().args, ("POST", "/api/stacks/myapp/restart?env=1"))


if __name__ == "__main__":
    unittest.main()
