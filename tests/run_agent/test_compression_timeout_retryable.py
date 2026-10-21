"""A compression TIMEOUT preserves the input and stays retryable.

A compression timeout is a TRANSIENT failure (the provider was busy), not a
verdict that the session is permanently uncompressible. The contract:

* the turn-start preflight timeout result carries ``compression_retryable``;
* the gateway therefore does NOT auto-reset the session (the transcript and
  the user's input survive) and does NOT skip the transcript persistence;
* the next turn retries the compaction and answers the preserved input.

Contrast: a genuine context overflow (the request cannot fit any window)
still auto-resets — that is the #7100 session-growth loop guard and it is
unchanged.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.session import SessionSource

SESSION_KEY = "agent:main:telegram:dm:12345"


def _agent():
    from run_agent import AIAgent

    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    agent.client = MagicMock()
    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.tool_delay = 0
    agent.save_trajectories = False
    agent.compression_enabled = True
    agent.context_compressor.protect_first_n = 0
    agent.context_compressor.protect_last_n = 0
    agent.context_compressor.threshold_tokens = 1
    agent.context_compressor.should_compress = MagicMock(return_value=True)
    agent.context_compressor.should_defer_preflight_to_real_usage = MagicMock(
        return_value=False
    )
    agent.context_compressor.get_active_compression_failure_cooldown = MagicMock(
        return_value=None
    )

    def _timed_out(messages, _system_message, **_kwargs):
        from agent.conversation_compression import (
            mark_context_compression_timed_out,
            reset_context_compression_timeout_outcome,
        )

        reset_context_compression_timeout_outcome(agent)
        mark_context_compression_timed_out(agent)
        return messages, agent._cached_system_prompt

    agent._compress_context = _timed_out
    return agent


def test_preflight_timeout_result_is_flagged_retryable():
    agent = _agent()
    with (
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation(
            "continue",
            conversation_history=[
                {"role": "user", "content": "old request"},
                {"role": "assistant", "content": "old response"},
            ],
        )
    assert result["failed"] is True
    assert result["compression_exhausted"] is True
    # The transient marker the gateway uses to keep the session.
    assert result.get("compression_retryable") is True
    assert result["turn_exit_reason"] == "context_compression_timeout"


class _SessionStore:
    def __init__(self):
        self.entry = SimpleNamespace(
            session_key=SESSION_KEY,
            session_id="session-before-compression",
        )
        self._entries = {SESSION_KEY: self.entry}
        self.save_calls = 0
        self.persisted_messages: list = []

    def _save(self):
        self.save_calls += 1

    def _record_gateway_session_peer(self, session_id, session_key, source):
        pass

    def save_messages(self, session_id, messages, **_kwargs):
        self.persisted_messages = list(messages)


class _RetryableCompressionAgent:
    """Returns the transient compression-timeout result."""

    def __init__(self, **kwargs):
        self.session_id = kwargs["session_id"]
        self.model = kwargs["model"]
        self.tools = []
        self.context_compressor = SimpleNamespace(
            last_prompt_tokens=109291, context_length=98304
        )
        self.session_prompt_tokens = 109291
        self.session_completion_tokens = 0

    def run_conversation(
        self, user_message, conversation_history=None, task_id=None, **_kwargs
    ):
        return {
            "final_response": (
                "Context compression timed out before it could commit while "
                "the request was still approximately 109,291 tokens. The "
                "provider call was not sent. Run /compress and wait for it to "
                "finish, then retry."
            ),
            "failed": True,
            "completed": False,
            "error": (
                "Context compression timed out before it could commit while "
                "the request was still approximately 109,291 tokens."
            ),
            "compression_exhausted": True,
            "compression_retryable": True,
            "messages": [
                *(conversation_history or []),
                {"role": "user", "content": user_message},
            ],
            "api_calls": 0,
        }

    def interrupt(self, *_args, **_kwargs):
        pass


class _StreamConsumer:
    final_response_sent = False

    def __init__(self, *_args, **_kwargs):
        pass

    async def run(self):
        return None

    def finish(self):
        pass


class _Adapter:
    SUPPORTS_MESSAGE_EDITING = True
    _pending_messages = {}

    def get_pending_message(self, _session_key):
        return None

    async def send_typing(self, *_args, **_kwargs):
        return None

    async def stop_typing(self, *_args, **_kwargs):
        return None


def _runner(session_store):
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {Platform.TELEGRAM: _Adapter()}
    runner.config = SimpleNamespace(
        streaming=None, group_sessions_per_user=True, thread_sessions_per_user=False
    )
    runner.hooks = SimpleNamespace(loaded_hooks=False, emit=AsyncMock())
    runner.session_store = session_store
    # ``async_session_store`` is a read-only facade over ``session_store``;
    # the facade is what the auto-reset path calls, so assert on it. The
    # facade is rebuilt when its backing store changes, so it must carry the
    # same ``_store`` reference.
    runner._async_session_store = SimpleNamespace(
        _store=session_store,
        reset_session=AsyncMock(return_value=session_store.entry),
    )
    runner._session_db = MagicMock()
    runner._session_db.get_telegram_topic_binding_by_session.return_value = None
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._session_run_generation = {}
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._pending_skills_reload_notes = {}
    runner._prefill_messages = []
    runner._ephemeral_system_prompt = ""
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._draining = False
    runner._get_proxy_url = lambda: None
    runner._resolve_session_agent_runtime = lambda **_kwargs: (
        "gpt-5.4",
        {
            "provider": "openai-codex",
            "api_mode": "codex_responses",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_key": "token",
        },
    )
    runner._resolve_session_reasoning_config = lambda **_kwargs: None
    runner._resolve_turn_agent_config = lambda message, model, runtime: {
        "model": model,
        "runtime": runtime,
    }
    runner._load_service_tier = lambda: None
    runner._agent_config_signature = lambda *_args, **_kwargs: ("sig",)
    runner._extract_cache_busting_config = lambda _config: ()
    runner._thread_metadata_for_source = lambda *_args, **_kwargs: None
    runner._sync_telegram_topic_binding = MagicMock()
    runner._release_running_agent_state = MagicMock()
    runner._clear_conversation_scope = MagicMock()
    runner._evict_cached_agent = MagicMock()
    return runner


def _install_agent(monkeypatch, agent_cls):
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = agent_cls
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    monkeypatch.setenv("HERMES_TOOL_PROGRESS_MODE", "off")
    monkeypatch.setenv("HERMES_AGENT_TIMEOUT", "0")
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr("gateway.stream_consumer.GatewayStreamConsumer", _StreamConsumer)

    import hermes_cli.tools_config as tools_config

    monkeypatch.setattr(
        tools_config, "_get_platform_tools", lambda *_args, **_kwargs: {"core"}
    )


def test_retryable_compression_keeps_the_session_and_the_input(monkeypatch):
    _install_agent(monkeypatch, _RetryableCompressionAgent)

    session_store = _SessionStore()
    runner = _runner(session_store)
    source = SessionSource(
        platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="user-1"
    )

    result = asyncio.run(
        asyncio.wait_for(
            runner._run_agent(
                message="the input that must survive",
                context_prompt="",
                history=[{"role": "user", "content": "old question"}],
                source=source,
                session_id="session-before-compression",
                session_key=SESSION_KEY,
                run_generation=None,
            ),
            timeout=5,
        )
    )

    assert result["failed"] is True
    # The session is NOT wiped: a compression timeout is transient.
    runner.async_session_store.reset_session.assert_not_called()
    # The session id is unchanged.
    assert session_store.entry.session_id == "session-before-compression"
    # The user's input is preserved in the turn's messages.
    assert any(
        m.get("content") == "the input that must survive"
        for m in result.get("messages") or []
    )
