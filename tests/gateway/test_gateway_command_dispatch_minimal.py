import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import threading
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.session import SessionEntry, SessionSource, SessionStore, build_session_key


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=_make_source(),
        message_id="m1",
        internal=True,
    )


def _session_entry() -> SessionEntry:
    return SessionEntry(
        session_key=build_session_key(_make_source()),
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
        total_tokens=0,
    )


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    adapter._pending_messages = {}
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(
        emit=AsyncMock(),
        emit_collect=AsyncMock(return_value=[]),
        loaded_hooks=False,
    )
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = _session_entry()
    runner.session_store.load_transcript.return_value = []
    runner.session_store.has_any_sessions.return_value = True
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._queued_events = {}
    runner._session_db = MagicMock()
    runner._session_db.get_session_title.return_value = None
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner._send_voice_reply = AsyncMock()
    runner._capture_gateway_honcho_if_configured = lambda *args, **kwargs: None
    runner._emit_gateway_run_progress = AsyncMock()
    runner._update_prompt_pending = {}
    runner._busy_input_mode = "interrupt"
    runner._draining = False
    runner._session_run_generation = {}
    runner._session_sources = {}
    runner._pending_native_image_paths_by_session = {}
    runner._background_tasks = {}
    runner._background_task_counter = 0
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._service_tier = None
    runner._fast_mode_by_session = {}
    runner._goal_state_by_session = {}
    runner._goal_runs_in_progress = set()
    runner._goal_queued_by_session = set()
    runner._is_telegram_topic_root_lobby = lambda _source: False
    runner._should_send_telegram_lobby_reminder = lambda _source: False
    runner._check_slash_access = lambda _source, _command: None
    runner._release_running_agent_state = lambda key: runner._running_agents.pop(key, None)
    return runner, adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("command_text", ["/queue do this next", "/q do this next"])
async def test_idle_queue_sends_payload_as_next_turn(command_text):
    runner, _adapter = _make_runner()
    captured = {}

    async def fake_handle_message_with_agent(event, source, key, generation, *, shared_input_owner=None):
        captured["text"] = event.text
        captured["command"] = event.get_command()
        captured["source"] = source
        captured["key"] = key
        captured["generation"] = generation
        return {"final_response": "", "messages": []}

    runner._handle_message_with_agent = fake_handle_message_with_agent

    result = await runner._handle_message(_make_event(command_text))

    assert result == {"final_response": "", "messages": []}
    assert captured["text"] == "do this next"
    assert captured["command"] is None
    assert captured["source"] == _make_source()
    assert captured["key"] == build_session_key(_make_source())
    assert captured["generation"] == 1
    assert runner._running_agents == {}


class _OwnedBusyAdapter(BasePlatformAdapter):
    """Run actual admission/queue/cancellation code with in-memory delivery."""

    async def connect(self, *, is_reconnect=False):
        return True

    async def disconnect(self):
        pass

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        return SendResult(success=True)

    async def get_chat_info(self, chat_id):
        return {}


def _busy_runner(tmp_path, *, multiplex=False):
    from gateway.run import GatewayRunner

    runner, _ = _make_runner()
    runner.config.multiplex_profiles = multiplex
    runner.session_store = SessionStore(tmp_path / "sessions", runner.config)
    runner.session_store._db = None
    runner._busy_text_mode = "interrupt"
    runner._profile_adapters = {}
    runner._agent_cache = {}
    runner._persist_active_agents = lambda: None
    runner._begin_session_run_generation = MethodType(GatewayRunner._begin_session_run_generation, runner)
    runner._release_running_agent_state = MethodType(GatewayRunner._release_running_agent_state, runner)
    runner._session_has_compression_in_flight = AsyncMock(return_value=False)
    runner._handle_message_with_agent = AsyncMock(side_effect=AssertionError("Unexpected agent turn in control/queue test"))
    adapter = _OwnedBusyAdapter(PlatformConfig(enabled=True), Platform.TELEGRAM)
    adapter.set_message_handler(runner._handle_message)
    adapter.set_busy_session_handler(runner._handle_active_session_busy_message)
    runner.adapters = {Platform.TELEGRAM: adapter}
    return runner, adapter


def _busy_event(text, *, chat="owned-chat", profile=None):
    event = _make_event(text)
    event.internal = False
    event.source.chat_id = chat
    event.source.profile = profile
    return event


@asynccontextmanager
async def _owned_busy_turn(runner, adapter, source):
    entry = runner.session_store.get_or_create_session(source)
    key = entry.session_key
    agent = MagicMock()
    agent._active_children = []
    agent._gateway_turn_process_task_id = ""
    agent._gateway_turn_process_baseline = None
    agent.steer.return_value = True
    interrupt = asyncio.Event()
    task = asyncio.create_task(asyncio.Event().wait())
    runner._running_agents[key] = agent
    runner._begin_session_run_generation(key)
    adapter._active_sessions[key] = interrupt
    adapter._session_tasks[key] = task
    try:
        yield agent, key, task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if adapter._session_tasks.get(key) is task:
            adapter._session_tasks.pop(key, None)
        if adapter._active_sessions.get(key) is interrupt:
            adapter._active_sessions.pop(key, None)


def test_busy_is_a_gateway_command_without_interrupting_the_active_turn():
    from hermes_cli.commands import is_gateway_known_command, resolve_command, should_bypass_active_session

    command = resolve_command("busy")
    assert is_gateway_known_command("busy")
    assert command.busy_policy == "dispatch"
    assert should_bypass_active_session("busy")


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [False, True], ids=["idle", "busy"])
async def test_busy_command_dispatches_and_saves_without_starting_an_agent(tmp_path, active):
    runner, adapter = _busy_runner(tmp_path)
    event = _busy_event("/busy steer")
    runner._handle_message_with_agent = AsyncMock(side_effect=AssertionError("control command started an agent"))
    if active:
        async with _owned_busy_turn(runner, adapter, event.source) as (agent, key, task):
            reply = await runner._handle_message(event)
            assert runner._effective_busy_input_mode(event.source) == "steer"
            assert "steer" in reply
            agent.interrupt.assert_not_called()
            agent.steer.assert_not_called()
            assert not task.done()
    else:
        reply = await runner._handle_message(event)
        assert runner._effective_busy_input_mode(event.source) == "steer"
        assert "steer" in reply
    runner._handle_message_with_agent.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["queue", "steer", "interrupt"])
async def test_busy_selected_mode_controls_actual_adapter_followups(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("HERMES_GATEWAY_BUSY_ACK_ENABLED", "false")
    runner, adapter = _busy_runner(tmp_path)
    command = _busy_event(f"/busy {mode}")
    await runner._handle_message(command)
    assert runner._effective_busy_input_mode(command.source) == mode
    key = runner._session_key_for_source(command.source)
    assert runner.session_store.get_session_metadata(key, "busy_input_mode") == mode
    async with _owned_busy_turn(runner, adapter, command.source) as (agent, key, task):
        for text in ("first followup", "second followup"):
            await adapter.handle_message(_busy_event(text))
        assert not task.done()
        if mode == "queue":
            assert runner._queue_depth(key, adapter=adapter) == 2
            assert adapter._pending_messages[key].text == "first followup"
            assert runner._queued_events[key][0].text == "second followup"
            agent.interrupt.assert_not_called()
            agent.steer.assert_not_called()
            assert not adapter.has_pending_interrupt(key)
        elif mode == "steer":
            assert [call.args[0] for call in agent.steer.call_args_list] == ["first followup", "second followup"]
            agent.interrupt.assert_not_called()
            assert runner._queue_depth(key, adapter=adapter) == 0
        else:
            assert [call.args[0] for call in agent.interrupt.call_args_list] == ["first followup", "second followup"]
            agent.steer.assert_not_called()


@pytest.mark.asyncio
async def test_busy_mode_survives_store_reload_without_affecting_other_chats_or_profiles(tmp_path):
    runner, adapter = _busy_runner(tmp_path, multiplex=True)
    event = _busy_event("/busy queue", profile="primary")
    handler = getattr(runner, "_handle_busy_command", None)
    assert callable(handler), "Gateway /busy has no handler"
    await handler(event)
    assert runner._effective_busy_input_mode(event.source) == "queue"
    assert runner._effective_busy_input_mode(_busy_event("next", chat="other-chat", profile="primary").source) == "interrupt"
    assert runner._effective_busy_input_mode(_busy_event("next", profile="secondary").source) == "interrupt"
    assert runner._busy_input_mode == runner._busy_text_mode == adapter._busy_text_mode == "interrupt"
    runner.session_store = SessionStore(tmp_path / "sessions", runner.config)
    runner.session_store._db = None
    assert runner._effective_busy_input_mode(event.source) == "queue"
    assert runner._effective_busy_text_mode(event.source) == "queue"


@pytest.mark.asyncio
@pytest.mark.parametrize("argument", ["", "status", "unknown mode"])
async def test_busy_status_and_invalid_mode_do_not_create_or_write_a_session(tmp_path, argument):
    runner, adapter = _busy_runner(tmp_path)
    event = _busy_event(f"/busy {argument}")
    handler = getattr(runner, "_handle_busy_command", None)
    assert callable(handler), "Gateway /busy has no handler"
    before = dict(runner.session_store._entries)
    reply = await handler(event)
    assert reply and not str(reply).startswith("gateway.busy.")
    assert runner.session_store._entries == before
    assert not (tmp_path / "sessions" / "sessions.json").exists()


@pytest.mark.asyncio
async def test_busy_save_failure_preserves_effective_mode_and_later_writes(tmp_path, monkeypatch):
    runner, adapter = _busy_runner(tmp_path)
    event = _busy_event("/busy steer")
    entry = runner.session_store.get_or_create_session(event.source)
    handler = getattr(runner, "_handle_busy_command", None)
    assert callable(handler), "Gateway /busy has no handler"
    def fail_write(_data):
        raise OSError("owned busy-mode persistence failure")
    with monkeypatch.context() as failure:
        failure.setattr(runner.session_store, "_save_sessions_json", fail_write)
        reply = await handler(event)
    assert reply
    assert runner._effective_busy_input_mode(event.source) == "interrupt"
    assert runner.session_store.set_session_metadata(entry.session_key, "unrelated", "saved")
    assert runner.session_store.get_session_metadata(entry.session_key, "busy_input_mode") is None


@pytest.mark.asyncio
async def test_busy_queue_stop_discards_every_followup_before_the_next_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_BUSY_ACK_ENABLED", "false")
    runner, adapter = _busy_runner(tmp_path)
    event = _busy_event("/busy queue")
    await runner._handle_message(event)
    assert runner._effective_busy_input_mode(event.source) == "queue"
    async with _owned_busy_turn(runner, adapter, event.source) as (agent, key, task):
        for text in ("discard first", "discard second", "discard third"):
            await adapter.handle_message(_busy_event(text))
        assert runner._queue_depth(key, adapter=adapter) == 3
        generation = runner._session_run_generation[key]
        await adapter.handle_message(_busy_event("/stop"))
        assert runner._queue_depth(key, adapter=adapter) == 0
        assert not runner._is_session_run_current(key, generation)
        assert key not in runner._running_agents
        assert runner._promote_queued_event(key, adapter=adapter, pending_event=None) is None
        runner._handle_message_with_agent.assert_not_called()


@pytest.mark.asyncio
async def test_stop_discards_fifo_overflow_even_without_a_busy_preference(tmp_path):
    runner, adapter = _busy_runner(tmp_path)
    source = _busy_event("active").source
    async with _owned_busy_turn(runner, adapter, source) as (agent, key, task):
        for text in ("discard head", "discard overflow"):
            runner._enqueue_fifo(key, _busy_event(text), adapter)
        assert runner._queue_depth(key, adapter=adapter) == 2
        await runner._busy_stop_command(_busy_event("/stop"), key, source)
        assert runner._queue_depth(key, adapter=adapter) == 0
        assert runner._promote_queued_event(key, adapter=adapter, pending_event=None) is None


@pytest.mark.asyncio
async def test_stop_yield_does_not_clear_a_replacement_run_or_its_followup(tmp_path, monkeypatch):
    runner, adapter = _busy_runner(tmp_path)
    source = _busy_event("active").source
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait_for_typing_stop(*_args, **_kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(adapter, "interrupt_session_activity", wait_for_typing_stop)
    async with _owned_busy_turn(runner, adapter, source) as (old_agent, key, task):
        stopping = asyncio.create_task(runner._busy_stop_command(_busy_event("/stop"), key, source))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            replacement = MagicMock()
            runner._running_agents[key] = replacement
            runner._begin_session_run_generation(key)
            runner._agent_cache[key] = replacement
            pending = _busy_event("keep replacement followup")
            runner._enqueue_fifo(key, pending, adapter)
            release.set()
            await stopping
            assert runner._running_agents.get(key) is replacement
            assert adapter._pending_messages.get(key) is pending
            assert runner._agent_cache.get(key) is replacement
        finally:
            release.set()
            await asyncio.gather(stopping, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [["queue"], {"mode": "queue"}, True, "invalid", None])
async def test_busy_status_rejects_malformed_persisted_modes(tmp_path, value):
    runner, adapter = _busy_runner(tmp_path)
    event = _busy_event("/busy status")
    entry = runner.session_store.get_or_create_session(event.source)
    runner.session_store.set_session_metadata(entry.session_key, "busy_input_mode", value)
    assert runner._effective_busy_input_mode(event.source) == "interrupt"
    assert runner._effective_busy_text_mode(event.source) == "interrupt"
    reply = await runner._handle_message(event)
    assert "interrupt" in reply
    runner._handle_message_with_agent.assert_not_called()


@pytest.mark.asyncio
async def test_busy_command_uses_existing_slash_access_gate(tmp_path):
    runner, adapter = _busy_runner(tmp_path)
    runner._check_slash_access = lambda _source, _command: "owned-policy-denied"
    event = _busy_event("/busy queue")
    assert await runner._handle_message(event) == "owned-policy-denied"
    assert runner._effective_busy_input_mode(event.source) == "interrupt"
    runner._handle_message_with_agent.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["queue", "steer", "interrupt"])
async def test_busy_switch_preserves_older_debounced_input_before_new_fifo_input(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("HERMES_GATEWAY_BUSY_ACK_ENABLED", "false")
    runner, adapter = _busy_runner(tmp_path)
    runner._busy_input_mode = runner._busy_text_mode = adapter._busy_text_mode = "queue"
    adapter._busy_text_debounce_seconds = adapter._busy_text_hard_cap_seconds = 60
    source = _busy_event("active").source
    async with _owned_busy_turn(runner, adapter, source) as (agent, key, task):
        older = _busy_event("before mode switch")
        newer = _busy_event("after mode switch")
        await adapter.handle_message(older)
        timer = adapter._text_debounce[key].task
        try:
            await adapter.handle_message(_busy_event(f"/busy {mode}"))
            await adapter.handle_message(newer)
            await adapter._flush_text_debounce_now(key)
            assert adapter._pending_messages.get(key) is older
            assert older.text == "before mode switch"
            if mode == "steer":
                agent.steer.assert_called_once_with("after mode switch")
                assert runner._queue_depth(key, adapter=adapter) == 1
            else:
                assert runner._queued_events[key] == [newer]
        finally:
            adapter._discard_text_debounce(key)
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("reset_mode", ["idle", "daily", "both"])
async def test_busy_change_does_not_reset_an_expired_but_running_conversation(tmp_path, reset_mode):
    runner, adapter = _busy_runner(tmp_path)
    runner.config.default_reset_policy.mode = reset_mode
    runner.config.default_reset_policy.idle_minutes = 1
    event = _busy_event("/busy queue")
    async with _owned_busy_turn(runner, adapter, event.source) as (agent, key, task):
        entry = runner.session_store._entries[key]
        runner.session_store.mark_turn_active(key)
        entry.updated_at -= timedelta(days=2)
        entry.created_at = entry.updated_at
        assert runner.session_store._is_session_expired(entry)
        original_id = entry.session_id
        generation = runner._session_run_generation[key]
        await runner._handle_message(event)
        assert runner.session_store._entries[key] is entry
        assert entry.session_id == original_id
        assert runner._session_run_generation[key] == generation
        assert runner._running_agents[key] is agent
        assert runner._effective_busy_input_mode(event.source) == "queue"


@pytest.mark.asyncio
@pytest.mark.parametrize("followup", ["arrived after publication", "/queue arrived after publication", "/q arrived after publication"])
async def test_busy_published_mode_preserves_debounce_while_save_reply_is_waiting(tmp_path, monkeypatch, followup):
    monkeypatch.setenv("HERMES_GATEWAY_BUSY_ACK_ENABLED", "false")
    runner, adapter = _busy_runner(tmp_path)
    runner._busy_input_mode = runner._busy_text_mode = adapter._busy_text_mode = "queue"
    adapter._busy_text_debounce_seconds = adapter._busy_text_hard_cap_seconds = 60
    saved, release = threading.Event(), threading.Event()
    original_save = runner.session_store.set_session_metadata

    def save_then_wait(*args, **kwargs):
        result = original_save(*args, **kwargs)
        saved.set()
        if not release.wait(timeout=5):
            raise TimeoutError("owned busy-save test did not release its worker")
        return result

    monkeypatch.setattr(runner.session_store, "set_session_metadata", save_then_wait)
    async with _owned_busy_turn(runner, adapter, _busy_event("active").source) as (agent, key, task):
        older = _busy_event("accepted before save")
        newer = _busy_event(followup)
        await adapter.handle_message(older)
        timer = adapter._text_debounce[key].task
        saving = asyncio.create_task(runner._handle_busy_command(_busy_event("/busy queue")))
        try:
            assert await asyncio.to_thread(saved.wait, 5)
            await adapter.handle_message(newer)
            await adapter._flush_text_debounce_now(key)
            assert adapter._pending_messages.get(key) is older
            assert older.text == "accepted before save"
            assert [event.text for event in runner._queued_events[key]] == ["arrived after publication"]
        finally:
            release.set()
            await asyncio.gather(saving, return_exceptions=True)
            adapter._discard_text_debounce(key)
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)


