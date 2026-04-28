"""
Tests for DockhandClient (api.py).

Covers: _request (all paths), async_probe, API endpoint URL construction,
        Bearer token header, Accept: application/json header,
        container/stack actions.
"""
from __future__ import annotations
import asyncio, sys, os, unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import ha_stubs as stubs; stubs.install()

from custom_components.dockhand.api import (
    DockhandClient, DockhandAuthError, DockhandError,
)

run = asyncio.get_event_loop().run_until_complete


def _resp(status=200, json_data=None, text=""):
    r = MagicMock()
    r.status = status
    r.json = AsyncMock(return_value=json_data) if json_data is not None \
              else AsyncMock(side_effect=Exception("no json"))
    r.text = AsyncMock(return_value=text)
    return r


def _session(response):
    s = MagicMock()
    @asynccontextmanager
    async def _ctx(*a, **kw): yield response
    s.request = MagicMock(return_value=_ctx())
    return s


def _client(session=None, token=None):
    """Build a DockhandClient with an optional Bearer token."""
    cfg = {"api_url": "http://dh.test:3000"}
    if token:
        cfg["api_token"] = token
    return DockhandClient(session or MagicMock(), cfg)


class TestRequest(unittest.TestCase):

    def test_401_raises_auth_error(self):
        with self.assertRaises(DockhandAuthError) as ctx:
            run(_client(_session(_resp(401)))._request("GET", "/api/x"))
        self.assertIn("Unauthorized", str(ctx.exception))

    def test_4xx_raises_dockhand_error(self):
        with self.assertRaises(DockhandError) as ctx:
            run(_client(_session(_resp(404, text="nf")))._request("GET", "/api/x"))
        self.assertIn("404", str(ctx.exception))

    def test_200_returns_json(self):
        r = run(_client(_session(_resp(200, {"k": "v"})))._request("GET", "/api/x"))
        self.assertEqual(r, {"k": "v"})

    def test_200_no_json_returns_text(self):
        r = run(_client(_session(_resp(200, text="plain")))._request("GET", "/api/x"))
        self.assertEqual(r, "plain")

    def test_correct_url_constructed(self):
        s = _session(_resp(200, {}))
        run(_client(s)._request("GET", "/api/environments"))
        url = s.request.call_args.args[1]
        self.assertEqual(url, "http://dh.test:3000/api/environments")

    def test_bearer_token_in_header_when_token_set(self):
        s = _session(_resp(200, {}))
        run(_client(s, token="dh_mytoken")._request("GET", "/api/x"))
        headers = s.request.call_args.kwargs.get("headers", {})
        self.assertEqual(headers.get("Authorization"), "Bearer dh_mytoken")

    def test_no_auth_header_when_no_token(self):
        """No-auth install: no Authorization header should be sent."""
        s = _session(_resp(200, {}))
        run(_client(s)._request("GET", "/api/x"))
        headers = s.request.call_args.kwargs.get("headers", {})
        self.assertNotIn("Authorization", headers)

    def test_accept_json_header_always_set(self):
        """Accept: application/json must be present on every request."""
        s = _session(_resp(200, {}))
        run(_client(s, token="dh_tok")._request("GET", "/api/x"))
        headers = s.request.call_args.kwargs.get("headers", {})
        self.assertEqual(headers.get("Accept"), "application/json")

    def test_accept_json_without_token(self):
        """Accept header must also be set on no-auth requests."""
        s = _session(_resp(200, {}))
        run(_client(s)._request("GET", "/api/x"))
        headers = s.request.call_args.kwargs.get("headers", {})
        self.assertEqual(headers.get("Accept"), "application/json")


class TestProbe(unittest.TestCase):

    def test_probe_success_calls_environments(self):
        c = _client(token="dh_tok")
        c.async_get_environments = AsyncMock(return_value=[])
        run(c.async_probe())
        c.async_get_environments.assert_called_once()

    def test_probe_propagates_auth_error(self):
        c = _client(token="dh_tok")
        c.async_get_environments = AsyncMock(side_effect=DockhandAuthError("401"))
        with self.assertRaises(DockhandAuthError):
            run(c.async_probe())

    def test_probe_propagates_other_error(self):
        c = _client(token="dh_tok")
        c.async_get_environments = AsyncMock(side_effect=DockhandError("500"))
        with self.assertRaises(DockhandError):
            run(c.async_probe())


class TestEndpoints(unittest.TestCase):
    def setUp(self):
        self.c = _client(token="dh_tok")
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
        self.c = _client(token="dh_tok")
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
