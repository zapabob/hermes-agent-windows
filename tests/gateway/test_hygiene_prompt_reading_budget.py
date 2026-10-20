"""Exercise the actual gateway hygiene wait with isolated synthetic workers."""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import threading
import time

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource
from tests.gateway.test_session_hygiene import HygieneCaptureAdapter, _make_history


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["reading", "worker-timeout"])
async def test_hygiene_uses_extended_fence_and_stops_waiting_for_completed_worker(monkeypatch, tmp_path, outcome):
    import gateway.run as gateway_run
    import run_agent
    import agent.conversation_compression as conversation_compression

    # Charge the budget only for this fixture's measured reading. Later gateway
    # work must not expire a successfully committed fence before its assertions.
    # Keep asyncio and the stdlib clock real so the actual gateway wait runs.
    budget = SimpleNamespace(now=0.0)
    budget_lock = threading.Lock()

    def budget_monotonic():
        with budget_lock:
            return budget.now

    def advance_reading(seconds):
        with budget_lock:
            budget.now += seconds

    budget_time = SimpleNamespace(**vars(time))
    budget_time.monotonic = budget_monotonic
    monkeypatch.setattr(gateway_run, "time", budget_time)
    monkeypatch.setattr(conversation_compression, "time", budget_time)

    fake_db = MagicMock()
    fake_db.get_compression_failure_cooldown.return_value = None
    cleaned = threading.Event()
    calls = []
    fences = []
    class Agent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
            self._last_compaction_in_place = False
            self.context_compressor = SimpleNamespace(
                bind_session_state=MagicMock(), _last_compress_aborted=False,
                _last_aux_model_failure_model=None,
            )
            self.shutdown_memory_provider = MagicMock()
            self.close = MagicMock(side_effect=cleaned.set)

        def _compress_context(self, messages, *_args, commit_fence=None, **_kwargs):
            fences.append(commit_fence)
            if outcome == "worker-timeout":
                commit_fence.touch_progress()
                raise TimeoutError("finished provider timeout")
            for _ in range(8):
                time.sleep(0.1)
                advance_reading(0.1)
                assert commit_fence.extend_deadline(0.1)
                commit_fence.touch_progress()
            commit_fence.close_progress()
            if not commit_fence.begin_commit():
                return messages, ""
            try:
                calls.append("committed")
                self._last_compaction_in_place = True
                return [{"role": "assistant", "content": "owned summary"}], ""
            finally:
                commit_fence.finish_commit()

    monkeypatch.setattr(run_agent, "AIAgent", Agent)
    (tmp_path / "config.yaml").write_text(
        "compression:\n  enabled: true\n  hygiene_timeout_seconds: 0.4\n"
        "  hygiene_total_ceiling_seconds: 0.5\n  hygiene_failure_cooldown_seconds: 120\n", encoding="utf-8")
    adapter = HygieneCaptureAdapter()
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="owned-token")})
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = SessionEntry(
        session_key="agent:main:telegram:dm:12345", session_id="owned-hygiene",
        created_at=datetime.now(), updated_at=datetime.now(), platform=Platform.TELEGRAM, chat_type="dm")
    runner.session_store.load_transcript.return_value = _make_history(6, content_size=400)
    runner.session_store.has_any_sessions.return_value = True
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_db = SimpleNamespace(_db=fake_db)
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._run_agent = AsyncMock(return_value={"final_response": "ok", "messages": [], "tools": [], "history_offset": 0, "last_prompt_tokens": 0})
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "owned-key"})
    monkeypatch.setattr("agent.model_metadata.get_model_context_length", lambda *_a, **_kw: 100)
    logs = []
    original_info = gateway_run.logger.info
    def record_info(message, *args, **kwargs):
        if "still streaming after" in message:
            logs.append(message)
        original_info(message, *args, **kwargs)
    monkeypatch.setattr(gateway_run.logger, "info", record_info)
    event = MessageEvent(text="hello", source=SessionSource(
        platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="12345"), message_id="owned")
    assert await runner._handle_message(event) == "ok"
    assert await asyncio.to_thread(cleaned.wait, 2)
    assert runner._run_agent.await_count == 1 and len(fences) == 1
    if outcome == "reading":
        assert calls == ["committed"] and not fences[0].is_cancelled
        fake_db.record_compression_failure_cooldown.assert_not_called()
    else:
        assert calls == [] and fences[0].is_cancelled
        assert logs == [], "a completed worker must not be polled as a pending stream"
        assert fake_db.record_compression_failure_cooldown.called
