"""Actual clarify owners at deterministic lifecycle barriers; external leaves only."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
import json
import threading
import uuid
from unittest.mock import AsyncMock

import pytest

from gateway.platforms.base import MessageType, SendResult
from tests.gateway.test_queued_followup_processing_hooks import (
    HookRecordingAdapter, SESSION_KEY, _install_fake_agent, _make_runner, _source,
)
from tools import clarify_gateway as cm
from tools.clarify_tool import clarify_tool


@pytest.fixture(autouse=True)
def owned_registry(monkeypatch, tmp_path):
    # Real config loading and registry; no mock clarify module or answer drain.
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(json.dumps({"agent": {"clarify_timeout": 0},
        "display": {"streaming": False}}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    with cm._lock:
        cm._entries.clear()
        cm._session_index.clear()
        cm._notify_cbs.clear()
    yield
    with cm._lock:
        keys = list(cm._session_index)
    for key in keys:
        cm.clear_session(key)
    from tools import approval
    approval.unregister_gateway_notify(SESSION_KEY)


@pytest.fixture
def trace(tmp_path, request):
    record = {"node": request.node.nodeid, "nonce": uuid.uuid4().hex, "events": []}
    yield record
    (tmp_path / "clarify-case.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


class BodyBarrier:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.release = threading.Event()

    def wait(self):
        self.loop.call_soon_threadsafe(self.entered.set)
        assert self.release.wait(8), "test failed to release owned dependency"


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), 6)


def entries():
    with cm._lock:
        return list(cm._entries.values())


class DeliveryAdapter(HookRecordingAdapter):
    """Use inherited real send_clarify; only the outbound send leaf is synthetic."""
    def __init__(self):
        super().__init__()
        self.sent = []
        self.gates = {}
        self.failed = set()

    async def send(self, chat_id, content, **kwargs):
        for label in ("old", "new", "current"):
            if "owned-" + label in content:
                self.sent.append(label)
                gate = self.gates.get(label)
                if gate is not None:
                    await gate.wait()
                return SendResult(success=label not in self.failed, message_id=label,
                                  error="owned failed send" if label in self.failed else None)
        return SendResult(success=True, message_id="owned-leaf")


def install_turn(monkeypatch, tmp_path, runner, answers, *, body_gate=None, skip_old_question=False):
    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            if message == "old" and body_gate is not None:
                body_gate.wait()
            if message != "old" or not skip_old_question:
                answer = json.loads(clarify_tool(question="owned-" + message,
                    choices=["alpha", "beta"], callback=self.clarify_callback))
                answers[message] = answer["user_response"]
            return {"final_response": "owned reply", "messages": [], "api_calls": 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)

    async def turn(label):
        return await runner._run_agent(message=label, context_prompt="", history=[], source=_source(),
            session_id="owned-clarify-session", session_key=SESSION_KEY,
            run_generation=runner._session_state(SESSION_KEY).persistent.run_generation)
    return turn


async def finish(tasks, adapter=None, body_gate=None):
    # Failure-only fixture release is after the assertion, never the success oracle.
    if adapter is not None:
        for gate in adapter.gates.values():
            gate.set()
    if body_gate is not None:
        body_gate.release.set()
    for _ in range(4):
        for entry in entries():
            cm.resolve_gateway_clarify(entry.clarify_id, "owned fixture cleanup")
        if all(task.done() for task in tasks):
            break
        await asyncio.sleep(0.01)
    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)


@pytest.mark.asyncio
async def test_c1_old_actual_send_failure_preserves_new_prompt(monkeypatch, tmp_path, trace):
    adapter = DeliveryAdapter()
    adapter.gates["old"] = asyncio.Event()
    adapter.failed.add("old")
    runner = _make_runner(adapter)
    answers = {}
    turn = install_turn(monkeypatch, tmp_path, runner, answers)
    runner._begin_session_run_generation(SESSION_KEY)
    old = asyncio.create_task(turn("old"))
    tasks = [old]
    try:
        await until(lambda: "old" in adapter.sent)
        runner._clear_conversation_scope(SESSION_KEY, reason="owned clarify replacement")
        runner._begin_session_run_generation(SESSION_KEY)
        new = asyncio.create_task(turn("new"))
        tasks.append(new)
        await until(lambda: "new" in adapter.sent)
        entry = next(e for e in entries() if e.question == "owned-new")
        adapter.gates["old"].set()
        await asyncio.wait_for(old, 6)
        trace.update(answers=dict(answers), sent=list(adapter.sent), new_id=entry.clarify_id,
                     new_event=entry.event.is_set(), new_response=entry.response,
                     new_registered=cm._entries.get(entry.clarify_id) is entry)
        assert not entry.event.is_set(), "C1: old failed send/finally cancelled the replacement prompt"
        assert cm._entries.get(entry.clarify_id) is entry
        assert cm.resolve_gateway_clarify(entry.clarify_id, "beta")
        await asyncio.wait_for(new, 6)
        assert answers["new"] == "beta"
    finally:
        await finish(tasks, adapter)


def test_c1_failed_send_cancels_only_its_exact_request(trace):
    from gateway.run import _clarify_send_then_wait
    old = cm.register("owned-old", SESSION_KEY, "old", ["a", "b"])
    new = cm.register("owned-new", SESSION_KEY, "new", ["a", "b"])
    future = Future()
    future.set_result(SendResult(success=False, error="owned old failure"))
    result = _clarify_send_then_wait(future, clarify_id=old.clarify_id,
                                   session_key=SESSION_KEY, clarify_mod=cm)
    trace.update(result=result, new_event=new.event.is_set(), new_response=new.response)
    assert "could not be delivered" in result
    assert not new.event.is_set(), "C1: request failure cleared a different live question"


@pytest.mark.parametrize("failure", ["result", "exception", "missing_future"])
def test_no_id_failure_has_no_authority_over_real_entries(trace, failure):
    from gateway.run import _clarify_send_disposition

    old = cm.register("no-id-old", SESSION_KEY, "old", None)
    replacement = cm.register("no-id-new", SESSION_KEY, "new", None)
    future = Future()
    if failure == "exception":
        future.set_exception(RuntimeError("owned delivery failure"))
    else:
        future.set_result(SendResult(success=False, error="owned delivery failure"))
    if failure == "missing_future":
        future = None
    response = _clarify_send_disposition(future, session_key=SESSION_KEY, clarify_mod=cm)
    assert response == "[clarify prompt could not be delivered]"
    assert cm.is_pending(old) and cm.is_pending(replacement)
    assert old.response is None and replacement.response is None
    assert cm.resolve_gateway_clarify(old.clarify_id, "old still useful", entry=old)
    assert cm.wait_for_response(old.clarify_id, 1, entry=old) == "old still useful"
    assert cm.resolve_gateway_clarify(replacement.clarify_id, "new still useful", entry=replacement)
    assert cm.wait_for_response(replacement.clarify_id, 1, entry=replacement) == "new still useful"
    trace.update(failure=failure, abort=response, old=old.response, replacement=replacement.response)


@pytest.mark.asyncio
async def test_c2_actual_callback_retains_answer_resolved_before_ack_and_clear(monkeypatch, tmp_path, trace):
    adapter = DeliveryAdapter()
    adapter.gates["old"] = asyncio.Event()
    runner = _make_runner(adapter)
    answers = {}
    turn = install_turn(monkeypatch, tmp_path, runner, answers)
    runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(turn("old"))
    try:
        await until(lambda: "old" in adapter.sent)
        entry = next(e for e in entries() if e.question == "owned-old")
        assert cm.resolve_gateway_clarify(entry.clarify_id, "beta")
        assert cm.clear_session(SESSION_KEY) == 0
        assert entry.response == "beta" and entry.event.is_set()
        adapter.gates["old"].set()
        await asyncio.wait_for(task, 6)
        trace.update(captured_entry_answer=entry.response, actual_tool_answer=answers["old"],
                     sent=list(adapter.sent), id=entry.clarify_id)
        assert answers["old"] == "beta", "C2: answer preserved on entry was lost before the ID-based wait"
    finally:
        await finish([task], adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("edge", ["callback-admission", "finally"])
async def test_c5_old_real_callback_or_finally_cannot_affect_new_prompt(monkeypatch, tmp_path, trace, edge):
    gate = BodyBarrier()
    adapter = DeliveryAdapter()
    runner = _make_runner(adapter)
    answers = {}
    turn = install_turn(monkeypatch, tmp_path, runner, answers, body_gate=gate,
                        skip_old_question=edge == "finally")
    runner._begin_session_run_generation(SESSION_KEY)
    old = asyncio.create_task(turn("old"))
    tasks = [old]
    try:
        await asyncio.wait_for(gate.entered.wait(), 6)
        runner._clear_conversation_scope(SESSION_KEY, reason="owned retired callback")
        runner._begin_session_run_generation(SESSION_KEY)
        new = asyncio.create_task(turn("new"))
        tasks.append(new)
        await until(lambda: "new" in adapter.sent)
        entry = next(e for e in entries() if e.question == "owned-new")
        gate.release.set()
        await until(lambda: old.done() or "old" in adapter.sent)
        trace.update(edge=edge, sent=list(adapter.sent), new_event=entry.event.is_set(),
                     new_response=entry.response, new_registered=cm._entries.get(entry.clarify_id) is entry)
        assert "old" not in adapter.sent, "C5: retired actual callback admitted and sent a new prompt"
        await asyncio.wait_for(old, 6)
        assert cm._entries.get(entry.clarify_id) is entry and not entry.event.is_set(), \
            "C5: old actual run finally cleared the replacement prompt"
        assert cm.resolve_gateway_clarify(entry.clarify_id, "beta")
        await asyncio.wait_for(new, 6)
        assert answers["new"] == "beta"
    finally:
        await finish(tasks, adapter, gate)


@pytest.mark.asyncio
async def test_positive_actual_callback_schedules_sends_and_returns_answer(monkeypatch, tmp_path, trace):
    adapter = DeliveryAdapter()
    runner = _make_runner(adapter)
    answers = {}
    turn = install_turn(monkeypatch, tmp_path, runner, answers)
    runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(turn("current"))
    try:
        await until(lambda: "current" in adapter.sent)
        entry = next(e for e in entries() if e.question == "owned-current")
        assert cm.attempt_text_response_for_session(SESSION_KEY, "2") == cm.TEXT_RESOLVED
        await asyncio.wait_for(task, 6)
        trace.update(answer=answers["current"], sends=list(adapter.sent), exact_id=entry.clarify_id)
        assert answers["current"] == "beta" and adapter.sent == ["current"]
        assert not cm.has_pending(SESSION_KEY)
    finally:
        await finish([task], adapter)


def inbound_runner(monkeypatch):
    from tests.gateway.test_clarify_thread_followup_not_swallowed import _StubAdapter, _make_runner as make
    runner = make(_StubAdapter())
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *args, **kwargs: [])
    return runner


@pytest.mark.asyncio
async def test_c3_old_voice_transcript_cannot_resolve_replacement(monkeypatch, trace):
    from tests.gateway.test_clarify_thread_followup_not_swallowed import SESSION_KEY as key, _event
    runner = inbound_runner(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def transcribe(text, paths):
        trace["events"].append("real transcription-cache owner reached controlled STT leaf")
        entered.set()
        await release.wait()
        return "2", ["2"]

    monkeypatch.setattr(runner, "_enrich_message_with_transcription", transcribe)
    old = cm.register("voice-old", key, "old", ["alpha", "beta"])
    event = _event("")
    event.message_type = MessageType.VOICE
    event.media_urls, event.media_types = ["owned-no-real-audio.ogg"], ["audio/ogg"]
    task = asyncio.create_task(runner._handle_message(event))
    try:
        await asyncio.wait_for(entered.wait(), 6)
        cm.clear_session(key)
        new = cm.register("voice-new", key, "new", ["alpha", "beta"])
        release.set()
        await asyncio.wait_for(task, 6)
        trace.update(captured_old=old.clarify_id, new_id=new.clarify_id,
                     new_response=new.response, new_event=new.event.is_set(),
                     cached_transcript=getattr(event, "_gateway_pending_stt_transcripts", None))
        assert not new.event.is_set(), "C3: old voice reply selected and answered the replacement prompt"
        assert new.response is None
        assert cm.attempt_text_response_for_session(key, "2") == cm.TEXT_RESOLVED
        assert new.response == "beta"
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 8)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,voice,expected", [("2", False, "beta"), ("99", False, None),
                                                 ("", True, None), ("2", True, "beta")])
async def test_positive_real_inbound_selection_and_voice_controls(monkeypatch, trace, reply, voice, expected):
    from tests.gateway.test_clarify_thread_followup_not_swallowed import SESSION_KEY as key, _event
    runner = inbound_runner(monkeypatch)
    entry = cm.register("current-inbound", key, "question", ["alpha", "beta"])
    event = _event("" if voice else reply)
    if voice:
        event.message_type = MessageType.VOICE
        event.media_urls, event.media_types = ["owned-voice.ogg"], ["audio/ogg"]

        async def transcribe(text, paths):
            return reply, [reply] if reply else []
        monkeypatch.setattr(runner, "_enrich_message_with_transcription", transcribe)
    assert await runner._handle_message(event) == ""
    trace.update(reply=reply, voice=voice, actual=entry.response, event=entry.event.is_set())
    assert entry.response == expected and entry.event.is_set() == (expected is not None)


async def entered_wait(monkeypatch, entry, timeout=0, observed=None):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    actual = entry.event.wait

    def observe(timeout=None):
        if observed is not None:
            observed["thread_id"] = threading.get_ident()
        loop.call_soon_threadsafe(entered.set)
        return actual(timeout)

    monkeypatch.setattr(entry.event, "wait", observe)
    task = asyncio.create_task(asyncio.to_thread(cm.wait_for_response, entry.clarify_id, timeout))
    await asyncio.wait_for(entered.wait(), 6)
    return task


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["conversation", "security", "stop"])
async def test_c4_real_boundary_releases_unlimited_wait(monkeypatch, trace, boundary):
    runner = _make_runner(HookRecordingAdapter())
    runner._begin_session_run_generation(SESSION_KEY)
    entry = cm.register("unlimited-old", SESSION_KEY, "question", None)
    observed = {}
    task = await entered_wait(monkeypatch, entry, observed=observed)
    agent = None
    try:
        if boundary == "conversation":
            runner._clear_conversation_scope(SESSION_KEY, reason="owned boundary")
        elif boundary == "security":
            runner._clear_session_boundary_security_state(SESSION_KEY)
        else:
            # Real hard_interrupt/per-thread publication; bypass only expensive
            # provider construction, with no inference/client/process attached.
            from run_agent import AIAgent
            assert AIAgent.__module__ == "run_agent"
            agent = object.__new__(AIAgent)
            agent._execution_thread_id = observed["thread_id"]
            agent._active_children_lock = threading.Lock()
            agent._active_children = []
            agent.quiet_mode = True
            runner._session_state(SESSION_KEY).turn.agent = agent
            runner._persist_active_agents = lambda: None
            runner._clear_durable_active_turn = AsyncMock()
            await runner._interrupt_and_clear_session(SESSION_KEY, _source(),
                interrupt_reason="owned stop", invalidation_reason="owned stop")
            trace["hard_interrupt_published"] = agent._hard_interrupt_requested.is_set()
            assert trace["hard_interrupt_published"]
        trace.update(boundary=boundary, event_after_boundary=entry.event.is_set(),
                     registered=cm._entries.get(entry.clarify_id) is entry, worker_done=task.done())
        assert entry.event.is_set(), "C4: real boundary/stop left the unlimited clarify event blocked"
        assert await asyncio.wait_for(task, 3) in (None, "")
    finally:
        cm.clear_session(SESSION_KEY)
        await asyncio.wait_for(task, 6)
        if agent is not None:
            from tools.interrupt import set_interrupt
            set_interrupt(False, agent._execution_thread_id)


@pytest.mark.asyncio
async def test_positive_unlimited_live_wait_requires_real_answer(monkeypatch, trace):
    entry = cm.register("unlimited-live", SESSION_KEY, "question", None)
    task = await entered_wait(monkeypatch, entry)
    try:
        assert cm.get_clarify_timeout() == 0
        assert not task.done() and not entry.event.is_set()
        assert cm.resolve_gateway_clarify(entry.clarify_id, "owned live answer")
        assert not cm.resolve_gateway_clarify(entry.clarify_id, "duplicate")
        answer = await asyncio.wait_for(task, 3)
        trace.update(answer=answer, timeout=cm.get_clarify_timeout())
        assert answer == "owned live answer"
    finally:
        cm.clear_session(SESSION_KEY)
        await asyncio.wait_for(task, 6)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["gateway shutdown", "gateway restart"])
@pytest.mark.parametrize("answered", [False, True])
async def test_global_interrupt_releases_only_its_waiting_sessions(monkeypatch, trace, reason, answered):
    from run_agent import AIAgent
    from tools.interrupt import set_interrupt

    runner = _make_runner(HookRecordingAdapter())
    entry = cm.register("global-wait", SESSION_KEY, "question", None)
    unrelated = cm.register("other-runner-wait", SESSION_KEY + ":unrelated", "other", None)
    observed = {}
    waiter = await entered_wait(monkeypatch, entry, observed=observed)
    other_waiter = await entered_wait(monkeypatch, unrelated)
    # Real hard_interrupt publication, with no provider, model, active children,
    # process registry discovery or native channel attached to this bare agent.
    agent = object.__new__(AIAgent)
    agent._execution_thread_id = observed["thread_id"]
    agent._active_children_lock = threading.Lock()
    agent._active_children = []
    agent.quiet_mode = True
    runner._running_agents[SESSION_KEY] = agent
    try:
        assert cm.get_clarify_timeout() == 0
        assert not waiter.done() and not other_waiter.done()
        if answered:
            assert cm.resolve_gateway_clarify(entry.clarify_id, "first answer")
        runner._interrupt_running_agents(reason)
        trace.update(reason=reason, answered=answered, event=entry.event.is_set(),
                     response=entry.response, hard_interrupt=agent._hard_interrupt_requested.is_set(),
                     unrelated_event=unrelated.event.is_set())
        assert agent._hard_interrupt_requested.is_set()
        assert entry.event.is_set(), "C4/global: shutdown interrupt left the cooperative clarify worker waiting"
        assert await asyncio.wait_for(waiter, 3) == ("first answer" if answered else "")
        assert not unrelated.event.is_set() and not other_waiter.done()
        assert cm.resolve_gateway_clarify(unrelated.clarify_id, "still useful")
        assert await asyncio.wait_for(other_waiter, 3) == "still useful"
    finally:
        # Fixture release only after the product assertions; never evidence
        # that the shutdown owner itself released the real worker.
        cm.clear_session(SESSION_KEY)
        cm.clear_session(SESSION_KEY + ":unrelated")
        await asyncio.wait_for(asyncio.gather(waiter, other_waiter), 6)
        set_interrupt(False, agent._execution_thread_id)


@pytest.mark.asyncio
async def test_positive_started_wait_preserves_first_answer_and_other_session(monkeypatch, trace):
    first = cm.register("first-answer", SESSION_KEY, "question", None)
    other = cm.register("other-session", SESSION_KEY + ":other", "other", None)
    task = await entered_wait(monkeypatch, first)
    try:
        assert cm.resolve_gateway_clarify(first.clarify_id, "first real answer")
        assert cm.clear_session(SESSION_KEY) == 0
        assert not cm.resolve_gateway_clarify(first.clarify_id, "late answer")
        assert not other.event.is_set()
        answer = await asyncio.wait_for(task, 3)
        assert answer == "first real answer"
        assert cm.resolve_gateway_clarify(other.clarify_id, "other answer")
        assert cm.wait_for_response(other.clarify_id, 1) == "other answer"
        trace.update(answer=answer, other_response=other.response)
    finally:
        cm.clear_session(SESSION_KEY)
        cm.clear_session(SESSION_KEY + ":other")
        await asyncio.wait_for(task, 6)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,cancel_current", [("/help", False), ("new unrelated topic", True)])
async def test_positive_native_prose_and_slash_route_past_intercept(monkeypatch, trace, reply, cancel_current):
    from tests.gateway.test_clarify_thread_followup_not_swallowed import (
        SESSION_KEY as key, _event, _dispatch, _FellThroughIntercept,
    )
    runner = inbound_runner(monkeypatch)
    entry = cm.register("native-routing", key, "question", ["alpha", "beta"])
    with pytest.raises(_FellThroughIntercept):
        await _dispatch(runner, _event(reply))
    trace.update(reply=reply, cancelled=entry.event.is_set(), response=entry.response)
    assert entry.event.is_set() == cancel_current
    assert entry.response == ("" if cancel_current else None)


@pytest.mark.asyncio
async def test_positive_other_mode_accepts_free_text(monkeypatch, trace):
    from tests.gateway.test_clarify_thread_followup_not_swallowed import SESSION_KEY as key, _event
    runner = inbound_runner(monkeypatch)
    entry = cm.register("other-mode", key, "question", ["alpha", "beta"])
    assert cm.mark_awaiting_text(entry.clarify_id)
    assert await runner._handle_message(_event("owned free answer")) == ""
    trace.update(response=entry.response, event=entry.event.is_set())
    assert entry.response == "owned free answer" and entry.event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("barrier", ["coercion", "rejected_prose_return"])
@pytest.mark.parametrize("voice", [False, True])
async def test_retired_prose_is_full_routing_noop(monkeypatch, trace, barrier, voice):
    from tests.gateway.test_clarify_thread_followup_not_swallowed import SESSION_KEY as key, _event
    import tools.slash_confirm as slash_confirm

    runner = inbound_runner(monkeypatch)
    old = cm.register("retired-prose", key, "old", ["alpha", "beta"], owner=object())
    entered, finished = threading.Event(), threading.Event()
    replacement = []
    failures = []
    downstream = []

    def replace():
        try:
            assert entered.wait(6)
            # A real worker resolves A first, then the real registration owner
            # retires A and admits B while the event loop is coercing A's input.
            assert cm.resolve_gateway_clarify(old.clarify_id, "alpha", entry=old)
            replacement.append(cm.register("replacement-prose", key, "new",
                ["alpha", "beta"], owner=object()))
        except BaseException as exc:
            failures.append(exc)
        finally:
            finished.set()

    def rendezvous():
        entered.set()
        assert finished.wait(6), "owned replacement worker did not finish"
        assert not failures, failures

    if barrier == "coercion":
        actual = cm._coerce_text_response_detailed

        def coerce(entry, response):
            rendezvous()
            return actual(entry, response)

        monkeypatch.setattr(cm, "_coerce_text_response_detailed", coerce)
    else:
        actual = cm.attempt_text_response_for_session

        def attempt(*args, **kwargs):
            outcome = actual(*args, **kwargs)
            assert outcome == cm.TEXT_REJECTED_PROSE
            rendezvous()
            return outcome

        monkeypatch.setattr(cm, "attempt_text_response_for_session", attempt)

    def routing_admission(session_key):
        # This is the first actual owner after the clarify intercept, before
        # busy routing or new-run admission. Any call is already an input leak.
        downstream.append(session_key)
        return None

    monkeypatch.setattr(slash_confirm, "get_pending", routing_admission)
    event = _event("unrelated old prose")
    if voice:
        event.text = ""
        event.message_type = MessageType.VOICE
        event.media_urls, event.media_types = ["owned-no-audio.ogg"], ["audio/ogg"]

        async def transcribe(text, paths):
            return "unrelated old prose", ["unrelated old prose"]

        monkeypatch.setattr(runner, "_enrich_message_with_transcription", transcribe)
    worker = threading.Thread(target=replace)
    worker.start()
    try:
        error = None
        try:
            result = await runner._handle_message(event)
        except Exception as exc:
            # A later fixture dependency is intentionally absent: the primary
            # oracle is whether actual routing admitted the captured old input.
            error = type(exc).__name__
            result = None
        trace.update(barrier=barrier, voice=voice, downstream=downstream, error=error,
                     old_response=old.response, replacement_response=replacement[0].response)
        assert downstream == [], "C3/P2: retired prose entered ordinary routing for the replacement run"
        assert error is None and result == ""
        assert old.response == "alpha", "first answer must remain unchanged"
        new = replacement[0]
        assert not new.event.is_set() and new.response is None
        # B remains useful through the actual registry, with the barrier removed.
        if barrier == "coercion":
            monkeypatch.setattr(cm, "_coerce_text_response_detailed", actual)
        else:
            monkeypatch.setattr(cm, "attempt_text_response_for_session", actual)
        assert cm.attempt_text_response_for_session(key, "2", entry=new) == cm.TEXT_RESOLVED
        assert new.response == "beta"
    finally:
        entered.set()
        await asyncio.to_thread(worker.join, 8)
        assert not worker.is_alive()


@pytest.mark.asyncio
async def test_positive_ambiguous_actual_scheduling_keeps_delayed_answer(monkeypatch, trace):
    from agent.async_utils import safe_schedule_threadsafe
    from gateway.run import _clarify_send_then_wait
    loop = asyncio.get_running_loop()
    sent, ack_release, observed_wait = asyncio.Event(), asyncio.Event(), asyncio.Event()
    ack_done = asyncio.Event()
    entry = cm.register("ambiguous-live", SESSION_KEY, "question", ["alpha", "beta"])
    actual_wait = entry.event.wait

    def observe(timeout=None):
        loop.call_soon_threadsafe(observed_wait.set)
        return actual_wait(timeout)
    monkeypatch.setattr(entry.event, "wait", observe)

    async def send_leaf():
        sent.set()
        await ack_release.wait()
        ack_done.set()
        return SendResult(success=True, message_id="late-owned-ack")

    class ShortAckDeadline(Future):
        # Real scheduled Future; shorten only the ACK wait at this external seam.
        def __init__(self, future):
            super().__init__()
            self.future = future

        def result(self, timeout=None):
            return self.future.result(timeout=0.01)

    def work():
        future = safe_schedule_threadsafe(send_leaf(), loop)
        return _clarify_send_then_wait(ShortAckDeadline(future), clarify_id=entry.clarify_id,
                                      session_key=SESSION_KEY, clarify_mod=cm)
    task = asyncio.create_task(asyncio.to_thread(work))
    try:
        await asyncio.wait_for(sent.wait(), 3)
        await asyncio.wait_for(observed_wait.wait(), 3)
        assert not task.done() and not entry.event.is_set()
        assert cm.resolve_gateway_clarify(entry.clarify_id, "beta")
        answer = await asyncio.wait_for(task, 3)
        trace.update(answer=answer, ack_released_when_answer_returned=ack_release.is_set())
        assert answer == "beta" and not ack_release.is_set()
    finally:
        ack_release.set()
        cm.clear_session(SESSION_KEY)
        await asyncio.wait_for(task, 6)
        await asyncio.wait_for(ack_done.wait(), 3)
        trace["late_ack_completed"] = True


def test_positive_captured_entry_cannot_remove_reused_id(trace):
    old = cm.register("reused-id", SESSION_KEY, "old", None)
    assert cm.resolve_gateway_clarify(old.clarify_id, "old answer")
    cm.clear_session(SESSION_KEY)
    new = cm.register("reused-id", SESSION_KEY, "new", None)
    assert cm.wait_for_response(old.clarify_id, 1, entry=old) == "old answer"
    assert cm._entries.get(new.clarify_id) is new
    assert not cm.cancel_request(old.clarify_id, entry=old)
    assert cm.resolve_gateway_clarify(new.clarify_id, "new answer")
    assert cm.wait_for_response(new.clarify_id, 1) == "new answer"
    trace.update(old=old.response, new=new.response)


def test_positive_answer_wins_even_if_send_ack_reports_failure(trace):
    from gateway.run import _clarify_send_then_wait
    entry = cm.register("answered-failed-ack", SESSION_KEY, "question", None)
    assert cm.resolve_gateway_clarify(entry.clarify_id, "already answered")
    future = Future()
    future.set_result(SendResult(success=False, error="owned late failed ACK"))
    answer = _clarify_send_then_wait(future, clarify_id=entry.clarify_id,
        session_key=SESSION_KEY, clarify_mod=cm, entry=entry)
    trace.update(answer=answer)
    assert answer == "already answered"


@pytest.mark.asyncio
async def test_positive_replacement_answers_before_old_ack_returns(monkeypatch, tmp_path, trace):
    adapter = DeliveryAdapter()
    adapter.gates["old"] = asyncio.Event()
    runner = _make_runner(adapter)
    answers = {}
    turn = install_turn(monkeypatch, tmp_path, runner, answers)
    runner._begin_session_run_generation(SESSION_KEY)
    old = asyncio.create_task(turn("old"))
    tasks = [old]
    try:
        await until(lambda: "old" in adapter.sent)
        old_entry = next(e for e in entries() if e.question == "owned-old")
        runner._begin_session_run_generation(SESSION_KEY)
        new = asyncio.create_task(turn("new"))
        tasks.append(new)
        await until(lambda: "new" in adapter.sent)
        new_entry = next(e for e in entries() if e.question == "owned-new")
        assert old_entry.event.is_set(), "replacement admission did not retire the old entry"
        assert cm.attempt_text_response_for_session(SESSION_KEY, "2") == cm.TEXT_RESOLVED
        assert new_entry.response == "beta", "old queue head captured the replacement's answer"
        await asyncio.wait_for(new, 6)
        assert answers["new"] == "beta" and not old.done()
        assert not adapter.gates["old"].is_set()
        trace.update(new_answer=answers["new"], old_ack_released=False, old_entry_retired=True)
        adapter.gates["old"].set()
        await asyncio.wait_for(old, 6)
    finally:
        await finish(tasks, adapter)


@pytest.mark.asyncio
async def test_positive_same_run_parallel_questions_keep_fifo(monkeypatch, tmp_path, trace):
    from concurrent.futures import ThreadPoolExecutor
    adapter = DeliveryAdapter()
    runner = _make_runner(adapter)
    answers = {}

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            def ask(label):
                result = json.loads(clarify_tool(question="owned-current-" + label,
                    choices=["alpha", "beta"], callback=self.clarify_callback))
                answers[label] = result["user_response"]
            with ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(ask, label) for label in ("one", "two")]
                for future in futures:
                    future.result(timeout=7)
            return {"final_response": "owned reply", "messages": [], "api_calls": 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(runner._run_agent(message="parallel", context_prompt="", history=[],
        source=_source(), session_id="owned-parallel", session_key=SESSION_KEY, run_generation=generation))
    try:
        await until(lambda: len(adapter.sent) == 2)
        pending = [e for e in entries() if e.session_key == SESSION_KEY]
        assert len(pending) == 2 and pending[0].owner is pending[1].owner
        order = [e.question.rsplit("-", 1)[-1] for e in pending]
        assert cm.attempt_text_response_for_session(SESSION_KEY, "1") == cm.TEXT_RESOLVED
        assert cm.attempt_text_response_for_session(SESSION_KEY, "2") == cm.TEXT_RESOLVED
        await asyncio.wait_for(task, 6)
        trace.update(order=order, answers=dict(answers))
        assert answers[order[0]] == "alpha" and answers[order[1]] == "beta"
    finally:
        await finish([task], adapter)


def test_positive_profile_namespaced_keys_remain_independent(trace):
    from gateway.session import build_session_key
    keys = [build_session_key(_source(), profile=name) for name in ("owned-a", "owned-b")]
    assert keys[0] != keys[1]
    owner_a, owner_b = object(), object()
    a = cm.register("profile-a", keys[0], "a", None, owner=owner_a)
    b = cm.register("profile-b", keys[1], "b", None, owner=owner_b)
    assert cm.clear_session(keys[0], owner=owner_a) == 1
    assert not b.event.is_set() and cm.is_pending(b)
    assert cm.resolve_gateway_clarify(b.clarify_id, "profile b answer")
    assert cm.wait_for_response(b.clarify_id, 1, entry=b) == "profile b answer"
    trace.update(keys=keys, a_cancelled=a.event.is_set(), b_answer=b.response)


@pytest.mark.asyncio
async def test_queued_send_rechecks_owner_on_actual_event_loop(monkeypatch, tmp_path, trace):
    import gateway.run as gateway_run
    adapter = DeliveryAdapter()
    runner = _make_runner(adapter)
    answers = {}
    turn = install_turn(monkeypatch, tmp_path, runner, answers)
    queued, release = asyncio.Event(), asyncio.Event()
    actual_schedule = gateway_run.safe_schedule_threadsafe

    def schedule(coro, loop, **kwargs):
        if coro.cr_code.co_name == "_send_current_clarify":
            async def queued_leaf():
                queued.set()
                await release.wait()
                return await coro
            return actual_schedule(queued_leaf(), loop, **kwargs)
        return actual_schedule(coro, loop, **kwargs)

    monkeypatch.setattr(gateway_run, "safe_schedule_threadsafe", schedule)
    runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(turn("old"))
    try:
        await asyncio.wait_for(queued.wait(), 6)
        runner._clear_conversation_scope(SESSION_KEY, reason="owned queued send boundary")
        new = cm.register("queued-replacement", SESSION_KEY, "replacement", None)
        release.set()
        await asyncio.wait_for(task, 6)
        trace.update(sent=list(adapter.sent), new_event=new.event.is_set())
        assert not adapter.sent, "queued stale coroutine entered the outbound send leaf"
        assert not new.event.is_set() and cm.is_pending(new)
    finally:
        release.set()
        await finish([task], adapter)


@pytest.mark.asyncio
async def test_retirement_after_answer_prevents_old_typing_resume(monkeypatch, tmp_path, trace):
    gate = BodyBarrier()

    class Adapter(DeliveryAdapter):
        resumed = 0

        def resume_typing_for_chat(self, chat_id):
            self.resumed += 1
            return super().resume_typing_for_chat(chat_id)

    adapter = Adapter()
    runner = _make_runner(adapter)
    answers = {}
    turn = install_turn(monkeypatch, tmp_path, runner, answers)
    actual_wait = cm.wait_for_response

    def wait(clarify_id, timeout, **kwargs):
        answer = actual_wait(clarify_id, timeout, **kwargs)
        gate.wait()
        return answer

    monkeypatch.setattr(cm, "wait_for_response", wait)
    runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(turn("old"))
    try:
        await until(lambda: "old" in adapter.sent)
        old = next(e for e in entries() if e.question == "owned-old")
        assert cm.resolve_gateway_clarify(old.clarify_id, "beta")
        await asyncio.wait_for(gate.entered.wait(), 6)
        runner._clear_conversation_scope(SESSION_KEY, reason="owned post-answer boundary")
        new = cm.register("post-answer-replacement", SESSION_KEY, "new", None)
        gate.release.set()
        await asyncio.wait_for(task, 6)
        trace.update(resumed=adapter.resumed, new_event=new.event.is_set(), answer=answers["old"])
        assert adapter.resumed == 0, "old callback resumed replacement typing after its answer wait"
        assert not new.event.is_set()
    finally:
        await finish([task], adapter, gate)
