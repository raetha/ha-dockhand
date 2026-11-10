"""The install queue: Installs that start together share one Dockhand job."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from custom_components.dockhand import installs
from custom_components.dockhand.api import DockhandPermissionError
from custom_components.dockhand.installs import (
    DockhandInstaller,
    InstallSkipped,
    install_signal,
    raise_for_outcome,
    summarize_failures,
)

ENV = 1


@pytest.fixture(autouse=True)
def _no_waiting():
    with (
        patch.object(installs, "GATHER_SECONDS", 0),
        patch.object(installs, "JOB_POLL_INTERVAL_SECONDS", 0),
    ):
        yield


def _line(cid: str, step: str | None = None, **data) -> dict:
    payload = {"type": "progress", "containerId": cid, **data}
    if step is not None:
        payload["step"] = step
    return {"data": payload}


def _done(*lines: dict) -> dict:
    return {"status": "done", "lines": list(lines)}


def _installer(hass: HomeAssistant, tier2: bool = True):
    client = MagicMock()
    client.async_get_update_check_settings = AsyncMock(
        return_value={"vulnerabilityCriteria": "critical"}
    )
    client.async_start_batch_update_stream = AsyncMock(
        side_effect=lambda env, ids, **kw: (
            f"job-{len(client.async_start_batch_update_stream.await_args_list)}"
        )
    )
    client.async_get_job = AsyncMock(return_value=_done())
    fast = MagicMock()
    fast.async_refresh_environment = AsyncMock()
    update = MagicMock() if tier2 else None
    if update is not None:
        update.async_check_environment = AsyncMock()
    return DockhandInstaller(hass, "entry", client, fast, update), client, fast, update


async def test_installs_that_start_together_share_one_job(hass: HomeAssistant):
    installer, client, fast, update = _installer(hass)
    results = await asyncio.gather(
        installer.async_install(ENV, ["a"]),
        installer.async_install(ENV, ["b"]),
        installer.async_install(ENV, ["a", "c"]),
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert results == [{"a": None}, {"b": None}, {"a": None, "c": None}]
    client.async_start_batch_update_stream.assert_awaited_once_with(
        ENV, ["a", "b", "c"], vulnerability_criteria="critical"
    )
    client.async_get_update_check_settings.assert_awaited_once_with(ENV)
    fast.async_refresh_environment.assert_awaited_once_with(ENV)
    update.async_check_environment.assert_awaited_once_with(ENV)


async def test_an_install_during_a_job_joins_the_next_one(hass: HomeAssistant):
    installer, client, _, _ = _installer(hass)
    release = asyncio.Event()

    async def job(job_id: str) -> dict:
        if job_id == "job-1":
            await release.wait()
        return _done()

    client.async_get_job = AsyncMock(side_effect=job)
    first = hass.async_create_task(installer.async_install(ENV, ["a"]))
    while not client.async_get_job.await_count:
        await asyncio.sleep(0)
    later = [
        hass.async_create_task(installer.async_install(ENV, [cid])) for cid in "bc"
    ]
    for _ in range(5):
        await asyncio.sleep(0)
    assert client.async_start_batch_update_stream.await_count == 1
    release.set()
    await asyncio.gather(first, *later)
    assert [
        c.args[1] for c in client.async_start_batch_update_stream.await_args_list
    ] == [
        ["a"],
        ["b", "c"],
    ]


async def test_environments_queue_separately(hass: HomeAssistant):
    installer, client, _, _ = _installer(hass)
    await asyncio.gather(
        installer.async_install(1, ["a"]), installer.async_install(2, ["b"])
    )
    assert sorted(
        (c.args[0], c.args[1])
        for c in client.async_start_batch_update_stream.await_args_list
    ) == [(1, ["a"]), (2, ["b"])]


async def test_each_container_gets_its_own_outcome(hass: HomeAssistant):
    installer, client, _, update = _installer(hass)
    client.async_get_job = AsyncMock(
        return_value=_done(
            _line("a", "pulling"),
            _line("a", "done"),
            {"data": {"type": "blocked", "containerId": "b", "blockReason": "CVE"}},
            _line("c", "failed", error="pull timeout"),
            _line("c", "skipped", message="later verdicts don't count"),
            _line("d", "skipped", message="Skipping d"),
            _line("e", "skipped"),
            _line("other", "failed"),
            {"data": {"type": "start"}},
        )
    )
    outcomes = await installer.async_install(ENV, ["a", "b", "c", "d", "e"])
    assert outcomes["a"] is None
    assert outcomes["b"].translation_placeholders == {"error": "Update blocked: CVE"}
    assert outcomes["c"].translation_placeholders == {"error": "pull timeout"}
    assert isinstance(outcomes["d"], InstallSkipped)
    assert str(outcomes["d"]) == "Skipping d"
    assert str(outcomes["e"]) == "update skipped by Dockhand"
    await hass.async_block_till_done(wait_background_tasks=True)
    update.async_check_environment.assert_awaited_once()


async def test_progress_is_tracked_and_announced(hass: HomeAssistant):
    installer, client, _, _ = _installer(hass)
    seen: list[int | None] = []
    async_dispatcher_connect(
        hass,
        install_signal("entry", ENV),
        callback(lambda: seen.append(installer.progress(ENV, "a"))),
    )
    polls = iter(
        [
            {"status": "running", "lines": [_line("a", "pulling")]},
            {"status": "running", "lines": [_line("a", "pulling"), _line("a")]},
            _done(_line("a", "pulling"), _line("a", "creating"), _line("a", "pulling")),
        ]
    )
    client.async_get_job = AsyncMock(side_effect=lambda job_id: next(polls))
    await installer.async_install(ENV, ["a"])
    # Queued (0), then each step only when it moves forward, then cleared.
    assert seen == [0, 20, 75, None]
    assert installer.progress(ENV, "a") is None


@pytest.mark.parametrize(
    ("start", "job", "translation_key", "message"),
    [
        (
            DockhandPermissionError("403"),
            None,
            "permission_denied",
            None,
        ),
        (Exception("boom"), None, "action_failed", "boom"),
        (
            None,
            {"status": "error", "result": {"error": "pull failed"}},
            "action_failed",
            "pull failed",
        ),
        (None, {"status": "error"}, "action_failed", "update job failed"),
        (None, OSError("connection reset"), "action_failed", "connection reset"),
    ],
)
async def test_a_failed_job_fails_every_container(
    hass: HomeAssistant, start, job, translation_key, message
):
    installer, client, fast, update = _installer(hass)
    if start is not None:
        client.async_start_batch_update_stream = AsyncMock(side_effect=start)
    if isinstance(job, Exception):
        client.async_get_job = AsyncMock(side_effect=job)
    elif job is not None:
        client.async_get_job = AsyncMock(return_value=job)
    outcomes = await installer.async_install(ENV, ["a", "b"])
    assert outcomes["a"] is outcomes["b"]
    assert outcomes["a"].translation_key == translation_key
    if message is not None:
        assert outcomes["a"].translation_placeholders == {"error": message}
    fast.async_refresh_environment.assert_awaited_once()
    await hass.async_block_till_done(wait_background_tasks=True)
    update.async_check_environment.assert_not_called()


async def test_a_job_that_never_finishes_times_out(hass: HomeAssistant):
    installer, client, _, _ = _installer(hass)
    client.async_get_job = AsyncMock(return_value={"status": "running"})
    with patch.object(installs, "JOB_POLL_MAX_ATTEMPTS", 3):
        outcomes = await installer.async_install(ENV, ["a"])
    assert "timed out" in outcomes["a"].translation_placeholders["error"]
    assert client.async_get_job.await_count == 3


async def test_without_the_vulnerability_policy_dockhand_uses_its_default(
    hass: HomeAssistant,
):
    installer, client, _, _ = _installer(hass)
    client.async_get_update_check_settings = AsyncMock(side_effect=OSError("500"))
    await installer.async_install(ENV, ["a"])
    assert client.async_start_batch_update_stream.await_args.kwargs == {
        "vulnerability_criteria": None
    }
    client.async_get_update_check_settings = AsyncMock(return_value={})
    await installer.async_install(ENV, ["a"])
    assert client.async_start_batch_update_stream.await_args.kwargs == {
        "vulnerability_criteria": None
    }


async def test_refresh_and_check_failures_dont_fail_the_install(hass: HomeAssistant):
    installer, _, fast, update = _installer(hass)
    fast.async_refresh_environment = AsyncMock(side_effect=OSError("down"))
    update.async_check_environment = AsyncMock(side_effect=OSError("registry"))
    assert await installer.async_install(ENV, ["a"]) == {"a": None}
    await hass.async_block_till_done(wait_background_tasks=True)
    update.async_check_environment.assert_awaited_once()


async def test_without_precise_updates_there_is_no_check(hass: HomeAssistant):
    installer, client, _, _ = _installer(hass, tier2=False)
    assert await installer.async_install(ENV, ["a"]) == {"a": None}
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_jobs_finishing_during_a_check_share_the_next_one(hass: HomeAssistant):
    installer, _, _, update = _installer(hass)
    release = asyncio.Event()
    checks = 0

    async def check(env_id: int) -> None:
        nonlocal checks
        checks += 1
        if checks == 1:
            await release.wait()

    update.async_check_environment = AsyncMock(side_effect=check)
    await installer.async_install(ENV, ["a"])
    while checks < 1:
        await asyncio.sleep(0)
    await installer.async_install(ENV, ["b"])
    await installer.async_install(ENV, ["c"])
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert checks == 2


def test_raise_for_outcome():
    raise_for_outcome(None)
    with pytest.raises(HomeAssistantError) as err:
        raise_for_outcome(InstallSkipped("Skipping a"))
    assert err.value.translation_placeholders == {"error": "Skipping a"}
    with pytest.raises(OSError):
        raise_for_outcome(OSError("x"))


def test_summarize_failures():
    summarize_failures({"a": None}, str)
    with pytest.raises(HomeAssistantError) as err:
        summarize_failures(
            {"a": OSError("disk"), "b": InstallSkipped("skip"), "c": None},
            str.upper,
        )
    assert err.value.translation_placeholders == {"error": "A: disk; B: skip"}
    shared = OSError("one cause")
    with pytest.raises(OSError):
        summarize_failures({"a": shared, "b": shared}, str)
