"""An invalidated turn must not start the Gateway's remote execution lane."""

from unittest.mock import AsyncMock

import pytest

from tests.gateway.test_queued_followup_processing_hooks import (
    HookRecordingAdapter,
    SESSION_KEY,
    _make_runner,
    _source,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed", [False, True], ids=["generation-zero", "claimed-generation"])
async def test_stale_generation_never_enters_proxy(monkeypatch, claimed):
    runner = _make_runner(HookRecordingAdapter())
    generation = runner._begin_session_run_generation(SESSION_KEY) if claimed else 0
    runner._invalidate_session_run_generation(SESSION_KEY, reason="owned stop")
    remote = AsyncMock(return_value={"final_response": "stale remote reply"})
    monkeypatch.setattr(runner, "_get_proxy_url", lambda: "https://unused.invalid")
    monkeypatch.setattr(runner, "_run_agent_via_proxy", remote)

    result = await runner._run_agent(
        message="retired guidance", context_prompt="", history=[], source=_source(),
        session_id="owned-entry", session_key=SESSION_KEY, run_generation=generation,
    )

    remote.assert_not_awaited()
    assert result["final_response"] == ""
    assert result["interrupted"] is True
    assert result["completed"] is False
    assert not result.get("pending_steer")


@pytest.mark.asyncio
@pytest.mark.parametrize("qualified", [False, True], ids=["legacy-no-generation", "current-generation"])
async def test_current_generation_keeps_proxy_route(monkeypatch, qualified):
    runner = _make_runner(HookRecordingAdapter())
    generation = runner._begin_session_run_generation(SESSION_KEY) if qualified else None
    expected = {"final_response": "owned remote reply", "completed": True}
    remote = AsyncMock(return_value=expected)
    monkeypatch.setattr(runner, "_get_proxy_url", lambda: "https://unused.invalid")
    monkeypatch.setattr(runner, "_run_agent_via_proxy", remote)

    result = await runner._run_agent(
        message="current guidance", context_prompt="", history=[], source=_source(),
        session_id="owned-entry", session_key=SESSION_KEY, run_generation=generation,
    )

    assert result is expected
    remote.assert_awaited_once()
    assert remote.await_args.kwargs["run_generation"] == generation
