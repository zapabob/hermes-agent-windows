"""Gateway followup ownership through real run-generation and runner methods.

Direct helpers: test_queued_followup_processing_hooks.HookRecordingAdapter,
_make_runner, _install_fake_agent, _source and SESSION_KEY. Only AIAgent,
configuration/credential/transport leaves and operational process/state leaves
are synthetic. No source inspection, real model, process scan or process kill.
Run in the parent's qualified fresh process with owned homes before imports.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from gateway.platforms.base import MessageEvent, MessageType, ProcessingOutcome
from tests.gateway.test_queued_followup_processing_hooks import (
    HookRecordingAdapter,
    SESSION_KEY,
    _install_fake_agent,
    _make_runner,
    _source,
)


FIRST = "owned original turn"
STEER = "owned leftover guidance from the original turn"
SESSION_ID = "owned-generation-session"


@pytest.fixture
def make_case(monkeypatch, tmp_path):
    """Retain real generation/state/FIFO owners, replacing external leaves."""
    home = tmp_path / "owned-gateway"
    home.mkdir()
    for key, directory in {
        "HOME": home, "USERPROFILE": home, "HERMES_HOME": home,
        "APPDATA": home / "appdata", "LOCALAPPDATA": home / "localappdata",
        "XDG_CONFIG_HOME": home / "config", "XDG_CACHE_HOME": home / "cache",
        "GH_CONFIG_DIR": home / "gh", "TEMP": home / "tmp", "TMP": home / "tmp",
    }.items():
        directory.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(key, str(directory))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HERMES_AGENT_TIMEOUT", "0")
    monkeypatch.setenv("HERMES_AGENT_TIMEOUT_WARNING", "0")
    monkeypatch.delenv("GATEWAY_PROXY_URL", raising=False)

    def make(*, block_worker=False, cache_gate=False, executor_gate=False,
             processing_start_gate=False, leftover=True):
        loop = asyncio.get_running_loop()
        case = SimpleNamespace(
            calls=[], constructed=[], entries=[], snapshots=[], reaps=[], releases=[],
            sends=[], persistence=[], worker_entered=asyncio.Event(),
            worker_finished=asyncio.Event(), worker_release=threading.Event(),
            gate_entered=asyncio.Event(), gate_release=asyncio.Event(),
            refresh_calls=[], executor_calls=[], interrupts=[], replacement=None,
        )
        if not block_worker:
            case.worker_release.set()

        class LeafAgent:
            def __init__(self, **kwargs):
                case.constructed.append(self)
                self.tools = []
                self.session_id = kwargs.get("session_id", SESSION_ID)
                self.context_compressor = None
                self.is_interrupted = False

            def run_conversation(self, message, conversation_history=None, task_id=None, **_kwargs):
                case.calls.append(message)
                first = len(case.calls) == 1
                if first:
                    loop.call_soon_threadsafe(case.worker_entered.set)
                try:
                    if first and not case.worker_release.wait(10):
                        raise AssertionError("Owned worker gate was not released")
                    messages = deepcopy(conversation_history or [])
                    reply = f"reply: {message}"
                    messages.extend([
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": reply},
                    ])
                    result = {"final_response": reply, "messages": messages,
                              "api_calls": 1, "completed": True}
                    if first and leftover:
                        result["pending_steer"] = STEER
                    return result
                finally:
                    if first:
                        loop.call_soon_threadsafe(case.worker_finished.set)

            def close(self):
                case.releases.append(self)

            def interrupt(self, *_args, **_kwargs):
                case.interrupts.append((self, _args, _kwargs))
                self.is_interrupted = True
                return True

        _install_fake_agent(monkeypatch, home, LeafAgent)
        gateway_run = importlib.import_module("gateway.run")
        case.gateway_run = gateway_run
        monkeypatch.setattr(gateway_run, "_env_path", home / ".env")
        monkeypatch.setattr(gateway_run, "load_dotenv", lambda *_a, **_k: None)
        config = {
            "display": {"tool_progress": "off", "thinking_progress": False,
                        "streaming": False, "interim_assistant_messages": False},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "checkpoints": {"enabled": False},
            "auxiliary": {"title_generation": {"enabled": False}},
            "mcp_servers": {}, "fallback_providers": [],
        }
        monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: deepcopy(config))
        monkeypatch.setattr(gateway_run, "_load_gateway_runtime_config", lambda: deepcopy(config))
        monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda *_a, **_k: "owned-model")
        monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", lambda: {
            "provider": "openai-compat", "api_key": "owned-placeholder",
            "base_url": "http://127.0.0.1:1/v1", "api_mode": "chat_completions",
        })

        def snapshot(task_id):
            case.snapshots.append(task_id)
            return frozenset()

        def reap(task_id, baseline, **kwargs):
            case.reaps.append((task_id, baseline, kwargs.get("source")))
            return 0

        from tools.process_registry import process_registry
        monkeypatch.setattr(process_registry, "snapshot_running_ids", snapshot)
        monkeypatch.setattr(gateway_run, "_reap_gateway_turn_processes", reap)

        class Adapter(HookRecordingAdapter):
            async def on_processing_start(self, event):
                await super().on_processing_start(event)
                if processing_start_gate and not case.gate_entered.is_set():
                    case.gate_entered.set()
                    await asyncio.wait_for(case.gate_release.wait(), timeout=10)

            async def send(self, chat_id, content, reply_to=None, metadata=None):
                case.sends.append(content)
                return await super().send(chat_id, content, reply_to=reply_to, metadata=metadata)

        case.adapter = Adapter()
        case.runner = _make_runner(case.adapter)
        runner = case.runner
        runner._model = "owned-model"
        runner._agent_cache = {}
        runner._agent_cache_lock = threading.RLock()
        runner._gateway_loop = loop
        monkeypatch.setattr(runner, "_get_proxy_url", lambda: None)
        monkeypatch.setattr(runner, "_persist_active_agents", lambda: case.persistence.append("active"))
        monkeypatch.setattr(runner, "_release_evicted_agent_soft", lambda agent: case.releases.append(agent))
        case.generation = runner._begin_session_run_generation(SESSION_KEY)
        assert runner._is_session_run_current(SESSION_KEY, case.generation)
        case.adapter._active_sessions[SESSION_KEY] = threading.Event()

        if executor_gate:
            real_executor = runner._run_in_executor_with_context

            async def delayed_executor(func, *args):
                if not case.gate_entered.is_set():
                    case.gate_entered.set()
                    await asyncio.wait_for(case.gate_release.wait(), timeout=10)
                case.executor_calls.append(func)
                return await real_executor(func, *args)

            monkeypatch.setattr(runner, "_run_in_executor_with_context", delayed_executor)

        real_refresh = runner._refresh_agent_cache_message_count

        async def refresh(session_key, session_id, **kwargs):
            case.refresh_calls.append((session_key, session_id))
            if cache_gate and not case.gate_entered.is_set():
                case.gate_entered.set()
                await asyncio.wait_for(case.gate_release.wait(), timeout=10)
            return await real_refresh(session_key, session_id, **kwargs)

        monkeypatch.setattr(runner, "_refresh_agent_cache_message_count", refresh)
        real_run = runner._run_agent

        async def observed_run(*args, **kwargs):
            # Observe recursive entry without replacing dispatch or its result.
            case.entries.append((kwargs.get("message", args[0] if args else None),
                                 kwargs.get("run_generation"), kwargs.get("_interrupt_depth", 0)))
            return await real_run(*args, **kwargs)

        monkeypatch.setattr(runner, "_run_agent", observed_run)
        case.leaf_class = LeafAgent
        return case

    return make


def _event(text, message_id):
    return MessageEvent(text=text, message_type=MessageType.TEXT,
                        source=_source(), message_id=message_id)


def _replace(case):
    """Use the real monotonic owner, then install another run's live state."""
    runner, adapter = case.runner, case.adapter
    generation = runner._invalidate_session_run_generation(SESSION_KEY, reason="owned test replacement")
    replacement_agent = object.__new__(case.leaf_class)
    replacement_agent.tools = []
    replacement_agent.session_id = SESSION_ID
    replacement_agent.context_compressor = None
    replacement_agent.is_interrupted = False
    old_entry = runner._agent_cache.get(SESSION_KEY)
    signature = old_entry[1] if old_entry else "replacement-only-signature"
    cache_entry = (replacement_agent, signature, 731, SESSION_ID)
    pending = _event("replacement pending must survive", "replacement-pending")
    overflow = _event("replacement overflow must survive", "replacement-overflow")
    interrupt = threading.Event()
    interrupt.set()
    interrupt._hermes_run_generation = generation
    state = runner._session_state(SESSION_KEY)
    state.turn.agent = replacement_agent
    state.turn.started_ts = 123.0
    state.conversation.queued_events[:] = [overflow]
    state.persistent.pending_command_text = "replacement command"
    runner._agent_cache[SESSION_KEY] = cache_entry
    adapter._pending_messages[SESSION_KEY] = pending
    adapter._active_sessions[SESSION_KEY] = interrupt
    case.replacement = SimpleNamespace(generation=generation, agent=replacement_agent,
                                       cache=cache_entry, pending=pending, overflow=overflow,
                                       interrupt=interrupt)
    assert not runner._is_session_run_current(SESSION_KEY, case.generation)


def _assert_replacement_untouched(case):
    replacement = case.replacement
    state = case.runner._peek_session_state(SESSION_KEY)
    assert case.runner._is_session_run_current(SESSION_KEY, replacement.generation)
    assert state.turn.agent is replacement.agent
    assert state.turn.started_ts == 123.0
    assert state.persistent.pending_command_text == "replacement command"
    assert state.conversation.queued_events == [replacement.overflow]
    assert state.conversation.queued_events[0] is replacement.overflow
    assert case.runner._agent_cache[SESSION_KEY] is replacement.cache
    assert case.adapter._pending_messages[SESSION_KEY] is replacement.pending
    assert case.adapter._active_sessions[SESSION_KEY] is replacement.interrupt
    assert replacement.interrupt.is_set()
    assert "replacement-pending" not in case.adapter.started
    assert "replacement-overflow" not in case.adapter.started
    assert case.replacement.agent not in case.releases


async def _run(case):
    return await asyncio.wait_for(case.runner._run_agent(
        message=FIRST, context_prompt="", history=[], source=_source(),
        session_id=SESSION_ID, session_key=SESSION_KEY,
        run_generation=case.generation,
    ), timeout=20)


async def _settle(case, task):
    """Always release both owned gates and await the real runner's cleanup."""
    case.worker_release.set()
    case.gate_release.set()
    if not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise AssertionError("Owned gateway run did not finish cleanup") from None
    if case.worker_entered.is_set():
        await asyncio.wait_for(case.worker_finished.wait(), timeout=5)


@pytest.mark.asyncio
async def test_initial_stale_supplied_generation_does_no_agent_work(make_case):
    case = make_case()
    _replace(case)
    task = asyncio.create_task(_run(case))
    try:
        await task
    finally:
        await _settle(case, task)
    assert case.constructed == []
    assert case.calls == []
    assert case.snapshots == []
    assert case.adapter.started == []
    assert case.adapter.completed == []
    assert case.sends == []
    _assert_replacement_untouched(case)


@pytest.mark.asyncio
async def test_generation_invalidated_before_executor_start_does_no_agent_work(make_case):
    case = make_case(executor_gate=True)
    task = asyncio.create_task(_run(case))
    try:
        await asyncio.wait_for(case.gate_entered.wait(), timeout=10)
        assert case.constructed == []
        assert case.calls == []
        assert case.executor_calls == []
        _replace(case)
        case.gate_release.set()
        result = await task
    finally:
        await _settle(case, task)
    # The actual executor ran its actual callback after invalidation; the
    # worker entry fence must reject it before constructing or running an agent.
    assert len(case.executor_calls) == 1
    assert case.constructed == []
    assert case.calls == []
    assert case.entries == [(FIRST, case.generation, 0)]
    assert case.adapter.started == []
    assert case.adapter.completed == []
    assert case.sends == []
    assert result["cancelled"] is True
    assert result["final_response"] == ""
    _assert_replacement_untouched(case)


@pytest.mark.asyncio
async def test_generation_invalidated_before_worker_return_cannot_drain_or_recurse(make_case):
    case = make_case(block_worker=True)
    task = asyncio.create_task(_run(case))
    try:
        await asyncio.wait_for(case.worker_entered.wait(), timeout=10)
        _replace(case)
        case.worker_release.set()
        result = await task
    finally:
        await _settle(case, task)
    assert case.calls == [FIRST]
    assert case.entries == [(FIRST, case.generation, 0)]
    assert case.adapter.started == []
    assert case.adapter.completed == []
    assert case.sends == []
    assert result["cancelled"] is True
    assert result["final_response"] == ""
    assert all(key not in result for key in (
        "pending_steer", "pending_steer_generation", "pending_steer_handoff", "interrupt_message",
    ))
    _assert_replacement_untouched(case)


@pytest.mark.asyncio
async def test_monitor_stt_return_after_invalidation_cannot_interrupt_old_agent(make_case, monkeypatch, tmp_path):
    case = make_case(block_worker=True, leftover=False)
    stt_entered = asyncio.Event()
    stt_release = asyncio.Event()
    stt_calls = []
    monitor_tasks = []
    caption = "owned voice caption before replacement"
    transcript = "owned stale voice transcript"
    audio_path = str(tmp_path / "owned-monitor-voice.ogg")

    async def owned_transcription(user_text, audio_paths):
        # Keep the real monitor, pending-event STT cache and stale-result
        # helper. Replace only provider/media processing; no audio is opened.
        stt_calls.append((user_text, list(audio_paths)))
        monitor_tasks.append(asyncio.current_task())
        stt_entered.set()
        await asyncio.wait_for(stt_release.wait(), timeout=10)
        return transcript, [transcript]

    monkeypatch.setattr(case.runner, "_enrich_message_with_transcription", owned_transcription)
    task = asyncio.create_task(_run(case))
    try:
        await asyncio.wait_for(case.worker_entered.wait(), timeout=10)
        old_agent = case.constructed[0]
        voice_event = MessageEvent(
            text=caption, message_type=MessageType.VOICE, source=_source(),
            message_id="owned-monitor-voice", media_urls=[audio_path],
            media_types=["audio/ogg"],
        )
        case.adapter._pending_messages[SESSION_KEY] = voice_event
        case.adapter._active_sessions[SESSION_KEY].set()
        await asyncio.wait_for(stt_entered.wait(), timeout=5)
        assert len(monitor_tasks) == 1
        monitor_task = monitor_tasks[0]
        assert monitor_task is not None
        assert not case.worker_finished.is_set()
        _replace(case)
        stt_release.set()
        # Await the actual monitor's exit before releasing the worker. This
        # prevents outer cleanup from cancelling it before the faulty interrupt.
        await asyncio.wait_for(asyncio.shield(monitor_task), timeout=5)
        case.worker_release.set()
        result = await task
    finally:
        stt_release.set()
        await _settle(case, task)
    assert stt_calls == [(caption, [audio_path])]
    assert case.interrupts == []
    assert old_agent.is_interrupted is False
    assert case.replacement.agent.is_interrupted is False
    assert case.calls == [FIRST]
    assert case.entries == [(FIRST, case.generation, 0)]
    assert case.sends == []
    assert result["cancelled"] is True
    assert result["final_response"] == ""
    _assert_replacement_untouched(case)


@pytest.mark.asyncio
async def test_generation_invalidated_during_cache_refresh_cannot_recurse(make_case):
    case = make_case(cache_gate=True, leftover=False)
    case.runner._enqueue_fifo(SESSION_KEY, _event("old queued followup", "old-queued"), case.adapter)
    task = asyncio.create_task(_run(case))
    try:
        await asyncio.wait_for(case.gate_entered.wait(), timeout=10)
        assert case.adapter.started == ["old-queued"]
        _replace(case)
        case.gate_release.set()
        await task
    finally:
        await _settle(case, task)
    assert case.calls == [FIRST]
    assert case.entries == [(FIRST, case.generation, 0)]
    assert case.refresh_calls == [(SESSION_KEY, SESSION_ID)]
    assert case.adapter.completed == [("old-queued", ProcessingOutcome.CANCELLED)]
    _assert_replacement_untouched(case)


@pytest.mark.asyncio
async def test_generation_invalidated_during_processing_start_cancels_hook_pair(make_case):
    case = make_case(processing_start_gate=True, leftover=False)
    case.runner._enqueue_fifo(SESSION_KEY, _event("old queued followup", "old-queued"), case.adapter)
    task = asyncio.create_task(_run(case))
    try:
        await asyncio.wait_for(case.gate_entered.wait(), timeout=10)
        assert case.adapter.started == ["old-queued"]
        _replace(case)
        case.gate_release.set()
        result = await task
    finally:
        await _settle(case, task)
    assert case.calls == [FIRST]
    assert case.entries == [(FIRST, case.generation, 0)]
    assert case.refresh_calls == []
    assert case.adapter.completed == [("old-queued", ProcessingOutcome.CANCELLED)]
    assert result["cancelled"] is True
    assert result["final_response"] == ""
    _assert_replacement_untouched(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("followup", ["queued", "steer"])
async def test_same_generation_followups_keep_order_and_processing_hooks(make_case, followup):
    case = make_case(leftover=followup == "steer")
    if followup == "queued":
        for text, message_id in [("queued A", "owned-A"), ("queued B", "owned-B")]:
            case.runner._enqueue_fifo(SESSION_KEY, _event(text, message_id), case.adapter)
        expected = [FIRST, "queued A", "queued B"]
    else:
        expected = [FIRST, STEER]
    task = asyncio.create_task(_run(case))
    try:
        result = await task
    finally:
        await _settle(case, task)
    assert case.calls == expected
    assert case.entries == [(message, case.generation, depth) for depth, message in enumerate(expected)]
    assert result["final_response"] == f"reply: {expected[-1]}"
    assert case.runner._is_session_run_current(SESSION_KEY, case.generation)
    assert SESSION_KEY not in case.adapter._pending_messages
    assert case.runner._session_state(SESSION_KEY).conversation.queued_events == []
    if followup == "queued":
        assert case.adapter.started == ["owned-A", "owned-B"]
        # Completion hooks unwind the real recursive call stack: B, then A.
        assert case.adapter.completed == [("owned-B", ProcessingOutcome.SUCCESS),
                                          ("owned-A", ProcessingOutcome.SUCCESS)]
    else:
        assert case.adapter.started == []
        assert case.adapter.completed == []
