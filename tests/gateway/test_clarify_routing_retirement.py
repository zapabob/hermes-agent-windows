"""Real routing and callback owners across the remaining retirement barriers."""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from gateway.platforms.base import MessageEvent
from tests.gateway.test_clarify_run_lifecycle import (
    BodyBarrier, DeliveryAdapter, finish, owned_registry, trace, until,
)
from tests.gateway.test_queued_followup_processing_hooks import (
    SESSION_KEY, _install_fake_agent, _make_runner, _source,
)
from tools import clarify_gateway as cm
from tools.clarify_tool import clarify_tool


def inbound(monkeypatch, adapter):
    runner = _make_runner(adapter)
    runner._startup_restore_in_progress = False
    runner._scale_to_zero_note_real_inbound = lambda: None
    runner._is_user_authorized = lambda source: True
    runner._session_key_for_source = lambda source: SESSION_KEY
    runner._update_prompt_pending = {}
    runner._draining = False
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *args, **kwargs: [])
    return runner


@pytest.mark.asyncio
async def test_retired_scheduled_send_returns_real_disposition(monkeypatch, tmp_path, trace, caplog):
    from tests.gateway.test_clarify_run_lifecycle import test_queued_send_rechecks_owner_on_actual_event_loop

    await test_queued_send_rechecks_owner_on_actual_event_loop(monkeypatch, tmp_path, trace)
    messages = [record.getMessage() for record in caplog.records]
    assert not any("name 'SendResult' is not defined" in message for message in messages)
    assert any("Clarify run retired" in message for message in messages)
    trace["real_retired_send_disposition"] = messages


@pytest.mark.asyncio
@pytest.mark.parametrize("retire", [False, True])
async def test_prose_compression_cannot_queue_into_replacement(monkeypatch, trace, retire):
    adapter = DeliveryAdapter()
    runner = inbound(monkeypatch, adapter)
    runner._begin_session_run_generation(SESSION_KEY)
    old_agent = SimpleNamespace()
    runner._running_agents[SESSION_KEY] = old_agent
    runner._effective_busy_input_mode = lambda source: "interrupt"
    runner._agent_has_active_subagents = lambda agent: False
    entered, release = asyncio.Event(), asyncio.Event()

    async def compression(session_key):
        entered.set()
        await release.wait()
        return True

    runner._session_has_compression_in_flight = compression
    entry = cm.register("compression-prose", SESSION_KEY, "old", ["alpha", "beta"])
    event = MessageEvent(text="unrelated old prose", source=_source(), message_id="old-prose")
    task = asyncio.create_task(runner._handle_message(event))
    try:
        await asyncio.wait_for(entered.wait(), 6)
        assert entry.event.is_set() and entry.response == ""
        if retire:
            runner._clear_conversation_scope(SESSION_KEY, reason="owned compression replacement")
            runner._begin_session_run_generation(SESSION_KEY)
            runner._running_agents[SESSION_KEY] = SimpleNamespace()
        release.set()
        await asyncio.wait_for(task, 6)
        head = adapter._pending_messages.get(SESSION_KEY)
        tail = runner._session_state(SESSION_KEY).conversation.queued_events
        trace.update(retire=retire, head=getattr(head, "text", None), tail=len(tail))
        if retire:
            assert head is None and not tail, "old prose entered replacement queue after compression await"
        else:
            assert head is event, "current unrelated prose must retain normal busy queue utility"
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 8)


@pytest.mark.asyncio
@pytest.mark.parametrize("retire", [False, True])
async def test_received_answer_cannot_resume_replacement_typing(monkeypatch, trace, retire):
    class Adapter(DeliveryAdapter):
        resumed = 0

        def resume_typing_for_chat(self, chat_id):
            self.resumed += 1
            return super().resume_typing_for_chat(chat_id)

    adapter = Adapter()
    runner = inbound(monkeypatch, adapter)
    runner._begin_session_run_generation(SESSION_KEY)
    old = cm.register("typing-old", SESSION_KEY, "question", ["alpha", "beta"])
    actual = cm.resolve_gateway_clarify
    replacements = []

    def resolve(*args, **kwargs):
        result = actual(*args, **kwargs)
        if result and args[0] == old.clarify_id and retire:
            # The real waiting worker may finish and retire its run before the
            # inbound coroutine performs its immediate typing side effect.
            def replace():
                runner._clear_conversation_scope(SESSION_KEY, reason="owned answer replacement")
                runner._begin_session_run_generation(SESSION_KEY)
                replacements.append(cm.register("typing-new", SESSION_KEY, "new", None))

            worker = threading.Thread(target=replace)
            worker.start()
            worker.join(6)
            assert not worker.is_alive()
        return result

    monkeypatch.setattr(cm, "resolve_gateway_clarify", resolve)
    result = await runner._handle_message(MessageEvent(text="2", source=_source(), message_id="old-answer"))
    trace.update(retire=retire, resumed=adapter.resumed, first_answer=old.response)
    assert result == "" and old.response == "beta"
    assert adapter.resumed == (0 if retire else 1), "old inbound answer resumed replacement typing"
    if retire:
        assert cm.is_pending(replacements[0])
        assert actual(replacements[0].clarify_id, "new useful answer", entry=replacements[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt", [False, True])
async def test_global_interrupt_fences_callback_not_yet_registered(monkeypatch, tmp_path, trace, interrupt):
    from run_agent import AIAgent as RealAgent
    from tools.interrupt import set_interrupt

    gate = BodyBarrier()
    answers, instances = [], []

    class Agent(RealAgent):
        def __init__(self, **kwargs):
            self.tools = []
            self._active_children_lock = threading.Lock()
            self._active_children = []
            self.quiet_mode = True
            instances.append(self)

        def run_conversation(self, message, **kwargs):
            self._execution_thread_id = threading.get_ident()
            gate.wait()
            answers.append(json.loads(clarify_tool(question="owned-old", choices=["alpha", "beta"],
                callback=self.clarify_callback))["user_response"])
            return {"final_response": "owned reply", "messages": [], "api_calls": 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    adapter = DeliveryAdapter()
    runner = _make_runner(adapter)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(runner._run_agent(message="old", context_prompt="", history=[], source=_source(),
        session_id="global-late-callback", session_key=SESSION_KEY, run_generation=generation))
    try:
        await asyncio.wait_for(gate.entered.wait(), 6)
        if interrupt:
            # Direct _run_agent entry bypasses the outer handler's tracking
            # coroutine. Supply its actual session->agent ownership before
            # exercising the real global interrupt and real Agent hard signal.
            runner._running_agents[SESSION_KEY] = instances[0]
            runner._interrupt_running_agents("gateway shutdown")
            assert instances[0]._hard_interrupt_requested.is_set()
        gate.release.set()
        await until(lambda: task.done() or bool(adapter.sent))
        trace.update(interrupt=interrupt, sent=list(adapter.sent), answers=list(answers))
        if interrupt:
            assert not adapter.sent, "global interrupt admitted a late clarify callback after clearing its session"
            await asyncio.wait_for(task, 6)
            assert not cm.has_pending(SESSION_KEY)
        else:
            assert adapter.sent == ["old"]
            entry = cm.get_pending_for_session(SESSION_KEY, include_choice_prompts=True)
            assert cm.resolve_gateway_clarify(entry.clarify_id, "beta", entry=entry)
            await asyncio.wait_for(task, 6)
            assert answers == ["beta"]
    finally:
        await finish([task], adapter, gate)
        if instances:
            set_interrupt(False, instances[0]._execution_thread_id)
