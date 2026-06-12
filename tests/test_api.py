"""
Tests for DockhandClient (api.py).

Covers: _request (all paths), async_probe, API endpoint URL construction,
        Bearer token header, Accept: application/json header,
        container/stack actions.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dockhand.api import (
    DockhandAuthError,
    DockhandClient,
    DockhandError,
)


def _resp(status=200, json_data=None, text=""):
    r = MagicMock()
    r.status = status
    r.json = (
        AsyncMock(return_value=json_data)
        if json_data is not None
        else AsyncMock(side_effect=Exception("no json"))
    )
    r.text = AsyncMock(return_value=text)
    return r


def _session(response):
    s = MagicMock()

    @asynccontextmanager
    async def _ctx(*a, **kw):
        yield response

    s.request = MagicMock(return_value=_ctx())
    return s


def _client(session=None, token=None):
    """Build a DockhandClient with an optional Bearer token."""
    cfg = {"api_url": "http://dh.test:3000"}
    if token:
        cfg["api_token"] = token
    return DockhandClient(session or MagicMock(), cfg)


# ---------------------------------------------------------------------------
# _request
# ---------------------------------------------------------------------------


async def test_request_401_raises_auth_error():
    with pytest.raises(DockhandAuthError, match="Unauthorized"):
        await _client(_session(_resp(401)))._request("GET", "/api/x")


async def test_request_4xx_raises_dockhand_error():
    with pytest.raises(DockhandError, match="404"):
        await _client(_session(_resp(404, text="nf")))._request("GET", "/api/x")


async def test_request_200_returns_json():
    r = await _client(_session(_resp(200, {"k": "v"})))._request("GET", "/api/x")
    assert r == {"k": "v"}


async def test_request_200_no_json_returns_text():
    r = await _client(_session(_resp(200, text="plain")))._request("GET", "/api/x")
    assert r == "plain"


async def test_request_correct_url_constructed():
    s = _session(_resp(200, {}))
    await _client(s)._request("GET", "/api/environments")
    url = s.request.call_args.args[1]
    assert url == "http://dh.test:3000/api/environments"


async def test_request_bearer_token_in_header_when_token_set():
    s = _session(_resp(200, {}))
    await _client(s, token="dh_mytoken")._request("GET", "/api/x")
    headers = s.request.call_args.kwargs.get("headers", {})
    assert headers.get("Authorization") == "Bearer dh_mytoken"


async def test_request_no_auth_header_when_no_token():
    """No-auth install: no Authorization header should be sent."""
    s = _session(_resp(200, {}))
    await _client(s)._request("GET", "/api/x")
    headers = s.request.call_args.kwargs.get("headers", {})
    assert "Authorization" not in headers


async def test_request_accept_json_header_always_set():
    """Accept: application/json must be present on every request."""
    s = _session(_resp(200, {}))
    await _client(s, token="dh_tok")._request("GET", "/api/x")
    headers = s.request.call_args.kwargs.get("headers", {})
    assert headers.get("Accept") == "application/json"


async def test_request_accept_json_without_token():
    """Accept header must also be set on no-auth requests."""
    s = _session(_resp(200, {}))
    await _client(s)._request("GET", "/api/x")
    headers = s.request.call_args.kwargs.get("headers", {})
    assert headers.get("Accept") == "application/json"


# ---------------------------------------------------------------------------
# async_probe
# ---------------------------------------------------------------------------


async def test_probe_success_calls_environments():
    c = _client(token="dh_tok")
    c.async_get_environments = AsyncMock(return_value=[])
    await c.async_probe()
    c.async_get_environments.assert_called_once()


async def test_probe_propagates_auth_error():
    c = _client(token="dh_tok")
    c.async_get_environments = AsyncMock(side_effect=DockhandAuthError("401"))
    with pytest.raises(DockhandAuthError):
        await c.async_probe()


async def test_probe_propagates_other_error():
    c = _client(token="dh_tok")
    c.async_get_environments = AsyncMock(side_effect=DockhandError("500"))
    with pytest.raises(DockhandError):
        await c.async_probe()


# ---------------------------------------------------------------------------
# Endpoint URL construction
# ---------------------------------------------------------------------------


@pytest.fixture
def client_with_mock_request():
    c = _client(token="dh_tok")
    c._request = AsyncMock(return_value=[])
    return c


async def test_get_environments(client_with_mock_request):
    await client_with_mock_request.async_get_environments()
    assert client_with_mock_request._request.call_args.args[1] == "/api/environments"


async def test_get_dashboard_stats(client_with_mock_request):
    client_with_mock_request._request.return_value = {}
    await client_with_mock_request.async_get_dashboard_stats(7)
    assert client_with_mock_request._request.call_args.args[1] == "/api/dashboard/stats?env=7"


async def test_get_containers(client_with_mock_request):
    await client_with_mock_request.async_get_containers(2)
    assert client_with_mock_request._request.call_args.args[1] == "/api/containers?env=2"


async def test_get_stacks(client_with_mock_request):
    await client_with_mock_request.async_get_stacks(2)
    assert client_with_mock_request._request.call_args.args[1] == "/api/stacks?env=2"


async def test_get_networks(client_with_mock_request):
    await client_with_mock_request.async_get_networks(2)
    assert client_with_mock_request._request.call_args.args[1] == "/api/networks?env=2"


async def test_get_images(client_with_mock_request):
    await client_with_mock_request.async_get_images(2)
    assert client_with_mock_request._request.call_args.args[1] == "/api/images?env=2"


async def test_get_volumes(client_with_mock_request):
    await client_with_mock_request.async_get_volumes(2)
    assert client_with_mock_request._request.call_args.args[1] == "/api/volumes?env=2"


async def test_get_schedules_list(client_with_mock_request):
    client_with_mock_request._request.return_value = [{"id": "s1"}]
    r = await client_with_mock_request.async_get_schedules()
    assert r == [{"id": "s1"}]


async def test_get_schedules_dict_unwraps(client_with_mock_request):
    client_with_mock_request._request.return_value = {"schedules": [{"id": "s1"}]}
    r = await client_with_mock_request.async_get_schedules()
    assert r == [{"id": "s1"}]


async def test_get_schedules_bad_type_returns_empty(client_with_mock_request):
    client_with_mock_request._request.return_value = "oops"
    assert await client_with_mock_request.async_get_schedules() == []


# ---------------------------------------------------------------------------
# Container/stack actions
# ---------------------------------------------------------------------------


@pytest.fixture
def action_client():
    c = _client(token="dh_tok")
    c._request = AsyncMock(return_value=None)
    return c


async def test_start_container(action_client):
    await action_client.async_start_container(1, "cid")
    assert action_client._request.call_args.args == ("POST", "/api/containers/cid/start?env=1")


async def test_stop_container(action_client):
    await action_client.async_stop_container(1, "cid")
    assert action_client._request.call_args.args == ("POST", "/api/containers/cid/stop?env=1")


async def test_restart_container(action_client):
    await action_client.async_restart_container(1, "cid")
    assert action_client._request.call_args.args == ("POST", "/api/containers/cid/restart?env=1")


async def test_start_stack(action_client):
    await action_client.async_start_stack(1, "myapp")
    assert action_client._request.call_args.args == ("POST", "/api/stacks/myapp/start?env=1")


async def test_stop_stack(action_client):
    await action_client.async_stop_stack(1, "myapp")
    assert action_client._request.call_args.args == ("POST", "/api/stacks/myapp/stop?env=1")


async def test_restart_stack(action_client):
    await action_client.async_restart_stack(1, "myapp")
    assert action_client._request.call_args.args == ("POST", "/api/stacks/myapp/restart?env=1")
