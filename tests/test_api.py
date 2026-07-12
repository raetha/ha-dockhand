"""
Tests for DockhandClient (api.py).

Covers: _request (all paths), async_probe, API endpoint URL construction,
        Bearer token header, Accept: application/json header,
        container/stack actions, host info, update-check settings,
        batch-update-stream, and job polling.
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


async def test_probe_success_calls_host_with_no_env_param():
    c = _client(token="dh_tok")
    c._request = AsyncMock(return_value={"hostname": "docker-host"})
    await c.async_probe()
    c._request.assert_called_once_with("GET", "/api/host")


async def test_probe_propagates_auth_error():
    c = _client(token="dh_tok")
    c._request = AsyncMock(side_effect=DockhandAuthError("401"))
    with pytest.raises(DockhandAuthError):
        await c.async_probe()


async def test_probe_propagates_other_error():
    c = _client(token="dh_tok")
    c._request = AsyncMock(side_effect=DockhandError("500"))
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
    assert (
        client_with_mock_request._request.call_args.args[1]
        == "/api/dashboard/stats?env=7"
    )


async def test_get_containers(client_with_mock_request):
    await client_with_mock_request.async_get_containers(2)
    assert (
        client_with_mock_request._request.call_args.args[1] == "/api/containers?env=2"
    )


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
    assert action_client._request.call_args.args == (
        "POST",
        "/api/containers/cid/start?env=1",
    )


async def test_stop_container(action_client):
    await action_client.async_stop_container(1, "cid")
    assert action_client._request.call_args.args == (
        "POST",
        "/api/containers/cid/stop?env=1",
    )


async def test_restart_container(action_client):
    await action_client.async_restart_container(1, "cid")
    assert action_client._request.call_args.args == (
        "POST",
        "/api/containers/cid/restart?env=1",
    )


async def test_start_stack(action_client):
    await action_client.async_start_stack(1, "myapp")
    assert action_client._request.call_args.args == (
        "POST",
        "/api/stacks/myapp/start?env=1",
    )


async def test_stop_stack(action_client):
    await action_client.async_stop_stack(1, "myapp")
    assert action_client._request.call_args.args == (
        "POST",
        "/api/stacks/myapp/stop?env=1",
    )


async def test_restart_stack(action_client):
    await action_client.async_restart_stack(1, "myapp")
    assert action_client._request.call_args.args == (
        "POST",
        "/api/stacks/myapp/restart?env=1",
    )


# ---------------------------------------------------------------------------
# Host info / update-check settings / batch-update-stream / jobs
# ---------------------------------------------------------------------------


async def test_get_host_info(client_with_mock_request):
    client_with_mock_request._request.return_value = {
        "environment": {"hawserVersion": "1.5.1"}
    }
    r = await client_with_mock_request.async_get_host_info(3)
    assert client_with_mock_request._request.call_args.args[1] == "/api/host?env=3"
    assert r["environment"]["hawserVersion"] == "1.5.1"


async def test_get_host_info_non_dict_response_returns_empty(client_with_mock_request):
    client_with_mock_request._request.return_value = "oops"
    assert await client_with_mock_request.async_get_host_info(3) == {}


async def test_get_update_check_settings(client_with_mock_request):
    client_with_mock_request._request.return_value = {
        "settings": {"enabled": True, "vulnerabilityCriteria": "critical_high"}
    }
    r = await client_with_mock_request.async_get_update_check_settings(5)
    assert (
        client_with_mock_request._request.call_args.args[1]
        == "/api/environments/5/update-check"
    )
    assert r["vulnerabilityCriteria"] == "critical_high"


async def test_get_update_check_settings_missing_settings_key_returns_empty(
    client_with_mock_request,
):
    client_with_mock_request._request.return_value = {}
    assert await client_with_mock_request.async_get_update_check_settings(5) == {}


async def test_start_batch_update_stream_includes_criteria(action_client):
    action_client._request.return_value = {"jobId": "job-42"}
    job_id = await action_client.async_start_batch_update_stream(
        1, ["cid"], vulnerability_criteria="critical"
    )
    assert job_id == "job-42"
    assert action_client._request.call_args.args == (
        "POST",
        "/api/containers/batch-update-stream?env=1",
    )
    assert action_client._request.call_args.kwargs["json"] == {
        "containerIds": ["cid"],
        "vulnerabilityCriteria": "critical",
    }


async def test_start_batch_update_stream_omits_criteria_when_none(action_client):
    action_client._request.return_value = {"jobId": "job-1"}
    await action_client.async_start_batch_update_stream(1, ["cid"])
    assert action_client._request.call_args.kwargs["json"] == {"containerIds": ["cid"]}


async def test_start_batch_update_stream_raises_without_job_id(action_client):
    action_client._request.return_value = {}
    with pytest.raises(DockhandError):
        await action_client.async_start_batch_update_stream(1, ["cid"])


async def test_get_job(client_with_mock_request):
    client_with_mock_request._request.return_value = {
        "id": "job-1",
        "status": "done",
        "lines": [],
    }
    r = await client_with_mock_request.async_get_job("job-1")
    assert client_with_mock_request._request.call_args.args[1] == "/api/jobs/job-1"
    assert r["status"] == "done"


async def test_get_job_non_dict_response_returns_empty(client_with_mock_request):
    client_with_mock_request._request.return_value = None
    assert await client_with_mock_request.async_get_job("job-1") == {}


# ---------------------------------------------------------------------------
# Git stacks
# ---------------------------------------------------------------------------


async def test_get_git_stacks(client_with_mock_request):
    client_with_mock_request._request.return_value = [{"id": 1, "stackName": "app"}]
    r = await client_with_mock_request.async_get_git_stacks(2)
    assert client_with_mock_request._request.call_args.args == (
        "GET",
        "/api/git/stacks?env=2",
    )
    assert r == [{"id": 1, "stackName": "app"}]


async def test_get_git_stacks_non_list_returns_empty(client_with_mock_request):
    client_with_mock_request._request.return_value = {"error": "oops"}
    assert await client_with_mock_request.async_get_git_stacks(2) == []


async def test_deploy_git_stack(action_client):
    action_client._request.return_value = {"success": True}
    r = await action_client.async_deploy_git_stack(7)
    assert action_client._request.call_args.args == (
        "POST",
        "/api/git/stacks/7/deploy",
    )
    assert r == {"success": True}


async def test_update_git_stack_partial_body(action_client):
    action_client._request.return_value = {"success": True}
    await action_client.async_update_git_stack(7, {"autoUpdate": True})
    assert action_client._request.call_args.args == ("PUT", "/api/git/stacks/7")
    assert action_client._request.call_args.kwargs["json"] == {"autoUpdate": True}


# ---------------------------------------------------------------------------
# Container auto-update
# ---------------------------------------------------------------------------


async def test_get_auto_update_settings(client_with_mock_request):
    client_with_mock_request._request.return_value = {"web": {"enabled": True}}
    r = await client_with_mock_request.async_get_auto_update_settings(3)
    assert (
        client_with_mock_request._request.call_args.args[1] == "/api/auto-update?env=3"
    )
    assert r == {"web": {"enabled": True}}


async def test_set_container_auto_update_enable_includes_defaults(action_client):
    action_client._request.return_value = {"success": True}
    await action_client.async_set_container_auto_update(3, "web", True)
    assert action_client._request.call_args.args == (
        "POST",
        "/api/auto-update/web?env=3",
    )
    body = action_client._request.call_args.kwargs["json"]
    assert body["enabled"] is True
    assert body["cronExpression"]
    assert body["vulnerabilityCriteria"] == "never"


async def test_set_container_auto_update_disable_sends_only_enabled(action_client):
    action_client._request.return_value = {"success": True, "deleted": True}
    await action_client.async_set_container_auto_update(3, "web", False)
    assert action_client._request.call_args.kwargs["json"] == {"enabled": False}


# ---------------------------------------------------------------------------
# Pending updates (Dockhand's own cached update-check results)
# ---------------------------------------------------------------------------


async def test_get_pending_updates(client_with_mock_request):
    client_with_mock_request._request.return_value = {
        "environmentId": 1,
        "pendingUpdates": [
            {
                "containerId": "abc",
                "containerName": "web",
                "currentImage": "nginx:latest",
                "checkedAt": "2026-07-01T00:00:00Z",
            }
        ],
    }
    r = await client_with_mock_request.async_get_pending_updates(1)
    assert (
        client_with_mock_request._request.call_args.args[1]
        == "/api/containers/pending-updates?env=1"
    )
    assert r[0]["containerId"] == "abc"


async def test_get_pending_updates_empty_when_none_configured(
    client_with_mock_request,
):
    """A normal, expected state — not an error — when the user hasn't
    configured update-check in Dockhand for this environment."""
    client_with_mock_request._request.return_value = {
        "environmentId": 1,
        "pendingUpdates": [],
    }
    assert await client_with_mock_request.async_get_pending_updates(1) == []


async def test_get_pending_updates_non_dict_returns_empty(client_with_mock_request):
    client_with_mock_request._request.return_value = None
    assert await client_with_mock_request.async_get_pending_updates(1) == []


# ---------------------------------------------------------------------------
# Runtime controls (update-runtime, inspect)
# ---------------------------------------------------------------------------


async def test_get_container_inspect(client_with_mock_request):
    client_with_mock_request._request.return_value = {"HostConfig": {"Memory": 100}}
    r = await client_with_mock_request.async_get_container_inspect(1, "cid")
    assert (
        client_with_mock_request._request.call_args.args[1]
        == "/api/containers/cid/inspect?env=1"
    )
    assert r["HostConfig"]["Memory"] == 100


async def test_get_container_inspect_non_dict_returns_empty(client_with_mock_request):
    client_with_mock_request._request.return_value = "oops"
    assert await client_with_mock_request.async_get_container_inspect(1, "cid") == {}


async def test_update_container_runtime(action_client):
    action_client._request.return_value = {"success": True, "warnings": []}
    r = await action_client.async_update_container_runtime(
        1, "cid", {"Memory": 536870912}
    )
    assert action_client._request.call_args.args == (
        "POST",
        "/api/containers/cid/update-runtime?env=1",
    )
    assert action_client._request.call_args.kwargs["json"] == {"Memory": 536870912}
    assert r == {"success": True, "warnings": []}


async def test_update_container_runtime_non_dict_returns_empty(action_client):
    action_client._request.return_value = None
    r = await action_client.async_update_container_runtime(1, "cid", {"Memory": 1})
    assert r == {}
