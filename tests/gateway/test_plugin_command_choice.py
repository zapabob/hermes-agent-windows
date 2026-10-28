"""A plugin slash command asks its user to pick an option (``PluginContext.ask_choice``) and gets the
picked value back, on the surfaces this tree serves:

* a messaging chat gets the clarify prompt (here the base adapter's numbered text) and the typed
  number answers it while the command is still running;
* a TUI-gateway session (Ink TUI, Desktop) gets the ``clarify.request`` prompt through
  ``slash.exec``, answered by the viewer's ``clarify.respond``.

Concurrency, cancellation and ContextVar hygiene are asserted at the seams the dispatch paths share.
"""
import asyncio
import contextvars
import threading
import time
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.plugin_command_choice import chat_choices, run_plugin_handler, viewer_choices
from gateway.session import SessionEntry, SessionSource, build_session_key
from hermes_cli.plugin_choices import ask_choice, asker_bound, bind_asker
from tools import clarify_gateway

_CHOICES = [{"value": "default", "label": "Default", "description": "delegation.model / parent model"},
            {"value": "model_map", "label": "Model routes"}, "profile_routes"]
_LABELS = ["Default — delegation.model / parent model", "Model routes", "profile_routes"]


async def _wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached before the timeout")
        await asyncio.sleep(0.01)


class _TextAdapter(BasePlatformAdapter):
    """A chat with no native card: the base ``send_clarify`` numbered list is what the user sees."""

    def __init__(self, platform=Platform.TELEGRAM):
        super().__init__(PlatformConfig(enabled=True, token="t"), platform)
        self.sent = []

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, content))
        return SendResult(success=True, message_id=str(len(self.sent)))

    async def get_chat_info(self, chat_id):
        return {"id": chat_id, "type": "private"}

    def texts(self):
        return [content for _chat, content in self.sent]


def _source(chat_id="c1", user_id="u1"):
    return SessionSource(platform=Platform.TELEGRAM, chat_id=chat_id, chat_type="dm", user_id=user_id)


def _runner(adapter):
    from gateway.run import GatewayRunner
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="t")})
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), emit_collect=AsyncMock(return_value=[]), loaded_hooks=False)
    entry = SessionEntry(session_key=build_session_key(_source()), session_id="sess-1", created_at=datetime.now(),
                         updated_at=datetime.now(), platform=Platform.TELEGRAM, chat_type="dm")
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = entry
    runner.session_store.load_transcript.return_value = []
    runner.session_store.has_any_sessions.return_value = True
    runner._running_agents, runner._pending_messages, runner._pending_approvals = {}, {}, {}
    runner._session_db = None
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._emit_gateway_run_progress = AsyncMock()
    return runner


@pytest.fixture(autouse=True)
def _clean_clarify_registry():
    yield
    with clarify_gateway._lock:
        clarify_gateway._entries.clear()
        clarify_gateway._session_index.clear()


@pytest.mark.asyncio
async def test_a_chat_answers_the_plugin_command_choice_with_a_typed_number(monkeypatch):
    from hermes_cli import plugins as plugins_mod

    adapter = _TextAdapter()
    runner = _runner(adapter)
    adapter.set_message_handler(runner._handle_message)
    monkeypatch.setattr(plugins_mod, "get_plugin_command_handler", lambda name: (
        (lambda arg: f"MODE={ask_choice('Delegation mode', _CHOICES)}") if name == "delegation" else None))
    monkeypatch.setattr(clarify_gateway, "get_clarify_timeout", lambda: 20)

    def event(text):
        return MessageEvent(text=text, message_type=MessageType.TEXT, source=_source(), message_id=text)

    await adapter.handle_message(event("/delegation"))
    await _wait_until(lambda: any("Model routes" in s for s in adapter.texts()))
    prompt = next(s for s in adapter.texts() if "Model routes" in s)
    assert "Delegation mode" in prompt and "delegation.model / parent model" in prompt, prompt
    await adapter.handle_message(event("2"))  # the command still runs: this must answer it, not queue
    await _wait_until(lambda: any(s.startswith("MODE=") for s in adapter.texts()))
    assert [s for s in adapter.texts() if s.startswith("MODE=")] == ["MODE=model_map"], adapter.texts()


@pytest.mark.asyncio
async def test_an_unanswered_chat_prompt_times_out_to_none_and_unregisters(monkeypatch):
    from hermes_cli import plugins as plugins_mod

    adapter = _TextAdapter()
    runner = _runner(adapter)
    adapter.set_message_handler(runner._handle_message)
    monkeypatch.setattr(plugins_mod, "get_plugin_command_handler", lambda name: (
        (lambda arg: f"MODE={ask_choice('Delegation mode', _CHOICES)}") if name == "delegation" else None))
    monkeypatch.setattr(clarify_gateway, "get_clarify_timeout", lambda: 1)

    await adapter.handle_message(MessageEvent(text="/delegation", message_type=MessageType.TEXT,
                                              source=_source(), message_id="cmd"))
    # nobody answers: the clarify timeout ends the wait and the handler falls back
    await _wait_until(lambda: any(s.startswith("MODE=") for s in adapter.texts()), timeout=20)
    assert [s for s in adapter.texts() if s.startswith("MODE=")] == ["MODE=None"], adapter.texts()
    assert not clarify_gateway._entries, "a timed-out prompt must not stay answerable"


class _CardAdapter(_TextAdapter):
    """An adapter whose card is answered by a scripted user (no typed reply path)."""

    def __init__(self, answers, wait_for_cards=1):
        super().__init__()
        self.answers = answers
        self.cards = []
        self.wait_for_cards = wait_for_cards
        self._all_open = asyncio.Event()

    async def send_clarify(self, chat_id, question, choices, clarify_id, session_key, metadata=None):
        self.cards.append((chat_id, session_key, question, list(choices)))
        if len(self.cards) >= self.wait_for_cards:
            self._all_open.set()
        await asyncio.wait_for(self._all_open.wait(), timeout=10)  # every prompt is open before any reply
        reply = self.answers(chat_id, choices)
        if reply is not None:
            clarify_gateway.resolve_gateway_clarify(clarify_id, reply)
        return SendResult(success=True, message_id="card")


def _chat_runner(adapter):
    runner = SimpleNamespace(_adapter_for_source=lambda source: adapter,
                             _thread_metadata_for_source=lambda source: None)
    return runner


@pytest.mark.asyncio
async def test_concurrent_chats_never_cross_choices_or_replies(monkeypatch):
    monkeypatch.setattr(clarify_gateway, "get_clarify_timeout", lambda: 10)

    def answers(chat_id, choices):
        # Each chat is asked its own list; the user of chat "A" picks the second, "B" the third.
        return {"A": choices[1], "B": choices[2]}[chat_id]

    adapter = _CardAdapter(answers, wait_for_cards=2)
    runner = _chat_runner(adapter)

    async def command(chat_id, question, choices):
        source = _source(chat_id=chat_id)
        return await run_plugin_handler(runner, source, f"key-{chat_id}", lambda arg: ask_choice(question, choices), "")

    picked = await asyncio.gather(
        command("A", "which for A?", ["a1", "a2", "a3"]),
        command("B", "which for B?", ["b1", "b2", "b3"]),
    )
    assert picked == ["a2", "b3"]
    assert sorted((chat, key, question, tuple(labels)) for chat, key, question, labels in adapter.cards) == [
        ("A", "key-A", "which for A?", ("a1", "a2", "a3")),
        ("B", "key-B", "which for B?", ("b1", "b2", "b3")),
    ]


@pytest.mark.asyncio
async def test_a_reply_to_a_retired_prompt_is_not_adopted_by_the_next_command(monkeypatch):
    monkeypatch.setattr(clarify_gateway, "get_clarify_timeout", lambda: 1)
    stale_ids = []

    def answers(chat_id, choices):
        return None  # nobody answers the first prompt: it times out

    adapter = _CardAdapter(answers)
    original = adapter.send_clarify

    async def spy(chat_id, question, choices, clarify_id, session_key, metadata=None):
        stale_ids.append(clarify_id)
        return await original(chat_id, question, choices, clarify_id, session_key, metadata)

    adapter.send_clarify = spy
    runner = _chat_runner(adapter)
    source = _source()
    first = await run_plugin_handler(runner, source, "key", lambda arg: ask_choice("first?", ["x", "y"]), "")
    assert first is None

    # The late tap on the first card resolves nothing ...
    assert clarify_gateway.resolve_gateway_clarify(stale_ids[0], "x") is False
    # ... and the second command waits for its own answer instead of inheriting it.
    adapter.answers = lambda chat_id, choices: choices[1]
    second = await run_plugin_handler(runner, source, "key", lambda arg: ask_choice("second?", ["x", "y"]), "")
    assert second == "y"
    assert len(set(stale_ids)) == 2


@pytest.mark.asyncio
async def test_an_undeliverable_card_is_none_and_unregisters_the_prompt(monkeypatch):
    monkeypatch.setattr(clarify_gateway, "get_clarify_timeout", lambda: 5)
    adapter = _TextAdapter()
    adapter.send_clarify = AsyncMock(return_value=SendResult(success=False, error="blocked"))
    runner = _chat_runner(adapter)
    picked = await run_plugin_handler(runner, _source(), "key", lambda arg: ask_choice("q?", ["x", "y"]), "")
    assert picked is None
    assert not clarify_gateway._entries


@pytest.mark.asyncio
async def test_a_failing_send_does_not_leave_the_prompt_registered(monkeypatch):
    adapter = _TextAdapter()
    adapter.send_clarify = AsyncMock(side_effect=RuntimeError("adapter exploded"))
    runner = _chat_runner(adapter)
    picked = await run_plugin_handler(runner, _source(), "key", lambda arg: ask_choice("q?", ["x"]), "")
    assert picked is None
    assert not clarify_gateway._entries


@pytest.mark.asyncio
async def test_a_chat_with_no_live_adapter_is_none():
    runner = SimpleNamespace(_adapter_for_source=lambda source: None, _thread_metadata_for_source=lambda s: None)
    assert await run_plugin_handler(runner, _source(), "key", lambda arg: ask_choice("q?", ["x"]), "") is None


@pytest.mark.asyncio
async def test_the_asker_is_unbound_after_a_handler_that_raises():
    runner = _chat_runner(_TextAdapter())

    def boom(arg):
        assert asker_bound()
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        await run_plugin_handler(runner, _source(), "key", boom, "")
    assert not asker_bound()
    assert ask_choice("q?", ["x"]) is None


@pytest.mark.asyncio
async def test_a_sync_handler_runs_off_the_event_loop_and_an_async_one_gets_none():
    runner = _chat_runner(_TextAdapter())
    loop_thread = threading.get_ident()
    ran_on = []

    def sync_handler(arg):
        ran_on.append(threading.get_ident())
        return f"sync:{arg}"

    async def async_handler(arg):
        ran_on.append(threading.get_ident())
        return f"async:{arg}:{ask_choice('q?', ['x'])}"

    assert await run_plugin_handler(runner, _source(), "key", sync_handler, "a") == "sync:a"
    assert await run_plugin_handler(runner, _source(), "key", async_handler, "b") == "async:b:None"
    assert ran_on[0] != loop_thread and ran_on[1] == loop_thread


@pytest.mark.asyncio
async def test_a_sync_handler_returning_an_awaitable_is_awaited():
    runner = _chat_runner(_TextAdapter())

    async def later():
        return "done"

    assert await run_plugin_handler(runner, _source(), "key", lambda arg: later(), "") == "done"


@pytest.mark.asyncio
async def test_handler_threads_inherit_the_callers_context_values():
    runner = _chat_runner(_TextAdapter())
    scope = contextvars.ContextVar("profile_scope_probe", default="default")
    token = scope.set("secondary-profile")
    try:
        seen = await run_plugin_handler(runner, _source(), "key", lambda arg: scope.get(), "")
    finally:
        scope.reset(token)
    assert seen == "secondary-profile"


@pytest.mark.asyncio
async def test_a_local_source_has_no_chat_to_prompt_and_an_existing_binding_is_kept():
    local = SessionSource(platform=Platform.LOCAL, chat_id="local", chat_type="dm", user_id="u")
    runner = _chat_runner(_TextAdapter())
    assert await run_plugin_handler(runner, local, "key", lambda arg: ask_choice("q?", ["x"]), "") is None

    with bind_asker(lambda question, labels: labels[0]):
        # a viewer-bound asker (slash.exec) wins over the chat asker: no second binding is stacked
        assert isinstance(chat_choices(runner, _source(), "key", asyncio.get_running_loop()), nullcontext)
        assert await run_plugin_handler(runner, _source(), "key", lambda arg: ask_choice("q?", ["x", "y"]), "") == "x"


def test_viewer_choices_maps_the_viewer_label_back_to_the_value():
    asked = []

    def clarify_block(session_id, question, labels):
        asked.append((session_id, question, list(labels)))
        return "Model routes"

    with viewer_choices(clarify_block, "sid-1"):
        assert ask_choice("Delegation mode", _CHOICES) == "model_map"
    assert asked == [("sid-1", "Delegation mode", _LABELS)]
    assert not asker_bound()


@pytest.mark.parametrize("answer", ["", None, "no such option"])
def test_viewer_cancel_timeout_and_unknown_answers_are_none(answer):
    with viewer_choices(lambda sid, question, labels: answer, "sid-1"):
        assert ask_choice("Delegation mode", _CHOICES) is None


def test_two_viewer_sessions_keep_their_own_choices():
    barrier = threading.Barrier(2, timeout=10)
    results = {}

    def session(sid, reply):
        def block(session_id, question, labels):
            assert session_id == sid
            barrier.wait()
            return reply

        with viewer_choices(block, sid):
            results[sid] = ask_choice("q?", ["one", "two"])

    threads = [threading.Thread(target=contextvars.copy_context().run, args=(session, "s1", "one")),
               threading.Thread(target=contextvars.copy_context().run, args=(session, "s2", "two"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == {"s1": "one", "s2": "two"}
