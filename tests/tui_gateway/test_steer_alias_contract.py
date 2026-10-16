"""F03: slash.exec must steer the live session through its canonical owner."""
from contextlib import contextmanager
from copy import deepcopy
import threading
from types import SimpleNamespace

import pytest

from agent.prompt_builder import format_steer_marker
from run_agent import AIAgent
from tui_gateway import server


def _session(monkeypatch, *, active=True, cached_agent=False):
    agent = object.__new__(AIAgent)
    agent._pending_steer = None
    agent._pending_steer_lock = threading.Lock()
    agent._interrupt_requested = False
    worker_commands = []
    # A worker cannot steer the live agent. Its plausible success must not pass.
    worker = SimpleNamespace(run=lambda cmd: worker_commands.append(cmd) or "accepted")
    session = {"session_key": "F03-owned", "agent": agent if active or cached_agent else None,
               "slash_worker": worker, "history": [], "running": active,
               "history_lock": threading.Lock(), "history_version": 0,
               "attached_images": [], "transport": None}
    monkeypatch.setitem(server._sessions, "F03-owned", session)
    return agent, worker_commands


@pytest.mark.parametrize("command", ["/steer", "/s", "/S"])
def test_slash_exec_alias_reaches_live_tool_result(monkeypatch, command):
    agent, worker_commands = _session(monkeypatch)
    payload = "Auth.LOG 日本語"
    response = server._methods["slash.exec"]("F03", {
        "session_id": "F03-owned", "command": f"{command} {payload}",
    })
    assert "error" not in response
    messages = [{"role": "tool", "tool_call_id": "actual", "content": "result"}]
    agent._apply_pending_steer_to_tool_results(messages, 1)
    assert messages[0]["content"] == "result" + format_steer_marker(payload)
    assert worker_commands == []
    assert agent._interrupt_requested is False
    assert agent._drain_pending_steer() is None


def test_session_steer_stale_busy_client_delivers_idle_cached_agent_text(monkeypatch):
    agent, worker_commands = _session(monkeypatch, active=False, cached_agent=True)
    delivered = []
    monkeypatch.setattr(server, "_run_prompt_submit", lambda _rid, _sid, _session, text, **_kwargs: delivered.append(text))
    response = server._methods["session.steer"]("F03", {
        "session_id": "F03-owned", "text": "Keep Case 日本語",
    })
    assert response["result"]["status"] == "queued"
    assert delivered == ["Keep Case 日本語"]
    assert agent._drain_pending_steer() is None
    assert worker_commands == []


@pytest.mark.parametrize("entry", ["slash.exec", "session.steer", "busy-submit"])
def test_finishing_barrier_preserves_late_steer_as_exactly_one_followup(monkeypatch, entry):
    agent, worker_commands = _session(monkeypatch)
    session = server._sessions["F03-owned"]
    delivered = []
    monkeypatch.setattr(server, "_run_prompt_submit", lambda _rid, _sid, _session, text, **_kwargs: delivered.append(text))
    monkeypatch.setattr(server, "_emit", lambda *_args: None)
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "steer")
    # Actual AIAgent drain is the finalizer handoff. Admit a second public
    # request while the session still reports running, after that handoff.
    assert agent.steer("Before boundary")
    result = {"pending_steer": agent._drain_pending_steer()}
    payload = "After boundary 日本語"
    if entry == "busy-submit":
        response = server._handle_busy_submit("F03", "F03-owned", session, payload, None)
    else:
        params = {"session_id": "F03-owned"}
        params.update({"command": f"/s {payload}"} if entry == "slash.exec" else {"text": payload})
        response = server._methods[entry]("F03", params)
    assert "error" not in response
    # Release the teardown barrier through the actual lifecycle owner.
    server._settle_session_turn(session, agent, result, False)
    server._run_post_turn_followups("F03", "F03-owned", session, result, None)
    assert delivered == [f"Before boundary\n{payload}"]
    assert agent._drain_pending_steer() is None
    assert session.get("queued_prompt") is None
    assert agent._interrupt_requested is False
    assert worker_commands == []


def test_settle_waits_for_admitted_steer_and_preserves_it_once(monkeypatch):
    agent, _worker_commands = _session(monkeypatch)
    session = server._sessions["F03-owned"]
    admitted, release, settling, settled = (threading.Event() for _ in range(4))
    errors = []
    delivered = []
    real_steer = agent.steer

    def paused_steer(text):
        admitted.set()
        assert release.wait(2)
        return real_steer(text)

    def send():
        try:
            response = server._methods["slash.exec"]("F03", {
                "session_id": "F03-owned", "command": "/s Boundary 日本語",
            })
            assert "error" not in response
        except BaseException as exc:
            errors.append(exc)

    def settle():
        try:
            settling.set()
            server._settle_session_turn(session, agent, {}, False)
            settled.set()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(agent, "steer", paused_steer)
    monkeypatch.setattr(server, "_run_prompt_submit", lambda _rid, _sid, _session, text, **_kwargs: delivered.append(text))
    monkeypatch.setattr(server, "_emit", lambda *_args: None)
    sender = threading.Thread(target=send)
    finalizer = threading.Thread(target=settle)
    sender.start()
    try:
        assert admitted.wait(2)
        finalizer.start()
        assert settling.wait(2)
        assert not settled.wait(0.1), "settle must not pass an admitted steer"
    finally:
        release.set()
        sender.join(2)
        if finalizer.ident is not None:
            finalizer.join(2)
    assert not sender.is_alive() and not finalizer.is_alive()
    assert errors == []
    server._run_post_turn_followups("F03", "F03-owned", session, {}, None)
    assert delivered == ["Boundary 日本語"]
    assert agent._drain_pending_steer() is None


def test_old_followup_does_not_drain_a_later_turn_steer(monkeypatch):
    agent, _worker_commands = _session(monkeypatch)
    session = server._sessions["F03-owned"]
    server._settle_session_turn(session, agent, {}, False)
    session["running"] = True
    assert agent.steer("Later turn only")
    server._run_post_turn_followups("F03", "F03-owned", session, {}, None)
    assert session.get("queued_prompt") is None
    assert agent._drain_pending_steer() == "Later turn only"


@pytest.mark.parametrize("error_retained", [False, True])
@pytest.mark.parametrize("entry", ["slash.exec", "session.steer", "busy-submit"])
def test_explicit_late_steer_equal_to_original_is_delivered(monkeypatch, entry, error_retained):
    agent, _workers = _session(monkeypatch)
    session = server._sessions["F03-owned"]
    payload = "Original 日本語"
    session["inflight_turn"] = {"user": payload, "assistant": "retained"}
    delivered = []
    monkeypatch.setattr(server, "_run_prompt_submit", lambda _rid, _sid, _session, text, **_kwargs: delivered.append(text))
    monkeypatch.setattr(server, "_emit", lambda *_args: None)
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "steer")
    if entry == "busy-submit":
        response = server._handle_busy_submit("F03", "F03-owned", session, payload, None)
    else:
        params = {"session_id": "F03-owned"}
        params.update({"command": f"/s {payload}"} if entry == "slash.exec" else {"text": payload})
        response = server._methods[entry]("F03", params)
    assert "error" not in response
    server._settle_session_turn(session, agent, {}, error_retained)
    # Another ordinary enqueue must not scrub an explicitly accepted steer.
    with session["history_lock"]:
        server._enqueue_prompt(session, "Later ordinary text", None)
    server._run_post_turn_followups("F03", "F03-owned", session, {}, None)
    assert delivered[0] == payload
    assert agent._drain_pending_steer() is None


def test_explicit_idle_retry_equal_to_retained_error_is_delivered(monkeypatch):
    agent, _workers = _session(monkeypatch, active=False, cached_agent=True)
    session = server._sessions["F03-owned"]
    payload = "Retry 日本語"
    session["inflight_turn"] = {"user": payload, "assistant": "", "error": "retained"}
    delivered = []
    monkeypatch.setattr(server, "_run_prompt_submit", lambda _rid, _sid, _session, text, **_kwargs: delivered.append(text))
    monkeypatch.setattr(server, "_emit", lambda *_args: None)
    response = server._methods["session.steer"]("F03", {"session_id": "F03-owned", "text": payload})
    assert response["result"]["status"] == "queued"
    assert delivered == [payload]
    assert agent._drain_pending_steer() is None


@pytest.mark.parametrize("entry", ["session.steer", "busy-submit"])
def test_accepted_correction_is_recorded_before_admission_unlock(monkeypatch, entry):
    agent, _workers = _session(monkeypatch)
    session = server._sessions["F03-owned"]
    session["inflight_turn"] = {"user": "original", "assistant": ""}
    observed = []
    real_steer = agent.steer

    def observe_admission(text):
        accepted = real_steer(text)
        # A separate lock acquisition after this helper returns would allow
        # settle and a new turn to replace the snapshot before recording it.
        return accepted

    real_helper = server._try_session_steer

    def observe_helper(*args, **kwargs):
        accepted = real_helper(*args, **kwargs)
        observed.append(list(session["inflight_turn"].get("corrections", [])))
        return accepted

    monkeypatch.setattr(agent, "steer", observe_admission)
    monkeypatch.setattr(server, "_try_session_steer", observe_helper)
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "steer")
    if entry == "busy-submit":
        response = server._handle_busy_submit("F03", "F03-owned", session, "Correction 日本語", None)
    else:
        response = server._methods[entry]("F03", {"session_id": "F03-owned", "text": "Correction 日本語"})
    assert "error" not in response
    assert observed == [["Correction 日本語"]]
    assert session["inflight_turn"]["corrections"] == ["Correction 日本語"]


def _stoppable_session(monkeypatch):
    agent, _workers = _session(monkeypatch)
    agent._pending_redirect = None
    agent._pending_redirect_lock = threading.Lock()
    agent._model_request_active = threading.Event()
    agent._executing_tools = False
    agent._execution_thread_id = None
    agent._interrupt_thread_signal_pending = False
    agent._interrupt_message = None
    agent._active_children = []
    agent._active_children_lock = threading.Lock()
    agent._tool_worker_threads = None
    agent._tool_worker_threads_lock = None
    agent.api_mode = "chat_completions"
    agent.quiet_mode = True
    session = server._sessions["F03-owned"]
    # Hold the actual turn teardown boundary after the public Stop response.
    session["_run_thread"] = SimpleNamespace(is_alive=lambda: True)
    session["_queued_prompt_generation"] = 7
    monkeypatch.setattr(server, "_emit", lambda *_args: None)
    return agent, session


@pytest.mark.parametrize("stop_at", ["before-finalizer", "after-finalizer", "after-settle"])
def test_stop_does_not_resurrect_pre_stop_accepted_steer(monkeypatch, stop_at):
    agent, session = _stoppable_session(monkeypatch)
    delivered = []
    monkeypatch.setattr(server, "_run_prompt_submit", lambda _rid, _sid, _session, text, **_kwargs: delivered.append(text))
    result = {}
    response = server._methods["slash.exec"]("F03", {
        "session_id": "F03-owned", "command": "/s Cancelled 日本語",
    })
    assert "error" not in response
    if stop_at != "before-finalizer":
        result["pending_steer"] = agent._drain_pending_steer()
    if stop_at == "after-settle":
        server._settle_session_turn(session, agent, result, False)
    stopped = server._methods["session.interrupt"]("F03", {"session_id": "F03-owned"})
    assert "error" not in stopped
    assert session["_queued_prompt_generation"] == 8
    if stop_at != "after-settle":
        server._settle_session_turn(session, agent, result, False)
    server._run_post_turn_followups("F03", "F03-owned", session, result, None)
    assert delivered == []
    assert agent._drain_pending_steer() is None
    assert session.get("queued_prompt") is None


@pytest.mark.parametrize("entry", ["slash.exec", "session.steer", "busy-submit"])
def test_steer_rejects_a_stopping_turn_without_reopening_it(monkeypatch, entry):
    agent, session = _stoppable_session(monkeypatch)
    stopped = server._methods["session.interrupt"]("F03", {"session_id": "F03-owned"})
    assert "error" not in stopped
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "steer")
    if entry == "busy-submit":
        response = server._handle_busy_submit("F03", "F03-owned", session, "New 日本語", None)
    else:
        params = {"session_id": "F03-owned"}
        params.update({"command": "/s New 日本語"} if entry == "slash.exec" else {"text": "New 日本語"})
        response = server._methods[entry]("F03", params)
    assert response.get("error", {}).get("code") == 4009
    assert session["_queued_prompt_generation"] == 8
    assert agent._drain_pending_steer() is None
    assert session.get("queued_prompt") is None


def test_idle_steer_after_stop_admits_a_new_turn(monkeypatch):
    agent, session = _stoppable_session(monkeypatch)
    stopped = server._methods["session.interrupt"]("F03", {"session_id": "F03-owned"})
    assert "error" not in stopped
    server._settle_session_turn(session, agent, {}, False)
    delivered = []
    monkeypatch.setattr(server, "_run_prompt_submit", lambda _rid, _sid, _session, text, **_kwargs: delivered.append((text, session.get("_turn_cancel_requested"))))
    response = server._methods["session.steer"]("F03", {"session_id": "F03-owned", "text": "Fresh 日本語"})
    assert response["result"]["status"] == "queued"
    assert delivered == [("Fresh 日本語", False)]
    assert session["_queued_prompt_generation"] == 8
    assert agent._drain_pending_steer() is None


def test_stop_cancels_an_explicit_steer_already_claimed_from_fifo(monkeypatch):
    agent, session = _stoppable_session(monkeypatch)
    agent.steer("Cancelled claimed 日本語")
    server._settle_session_turn(session, agent, {}, False)
    delivered = []
    monkeypatch.setattr(server, "_run_prompt_submit", lambda *_args, **_kwargs: delivered.append(True))
    original_lock = session["history_lock"]

    @contextmanager
    def stop_between_claim_and_generation_check():
        with original_lock:
            yield
        # Routing is resolved before claim; use the actual claim unlock so
        # Stop observes a claimed envelope and the unchanged generation token.
        session["history_lock"] = original_lock
        assert session["running"] is True
        assert session.get("queued_prompt") is None
        assert session["_queued_prompt_generation"] == 7
        response = server._methods["session.interrupt"]("F03", {"session_id": "F03-owned"})
        assert "error" not in response

    session["history_lock"] = stop_between_claim_and_generation_check()
    assert server._drain_queued_prompt("F03", "F03-owned", session)
    assert delivered == []
    assert session.get("queued_prompt") is None
    assert session.get("queued_prompts") is None
    assert session["_queued_prompt_generation"] == 8


def test_stop_before_fifo_claim_leaves_nothing_to_drain(monkeypatch):
    agent, session = _stoppable_session(monkeypatch)
    agent.steer("Cancelled before claim 日本語")
    server._settle_session_turn(session, agent, {}, False)
    delivered = []
    monkeypatch.setattr(server, "_run_prompt_submit", lambda *_args, **_kwargs: delivered.append(True))
    real_compute_host_decision = server._session_uses_compute_host

    def stop_before_claim(_session):
        monkeypatch.setattr(server, "_session_uses_compute_host", real_compute_host_decision)
        assert session["running"] is False
        assert session["queued_prompt"]["_explicit_steer"] is True
        response = server._methods["session.interrupt"]("F03", {"session_id": "F03-owned"})
        assert "error" not in response
        return False

    monkeypatch.setattr(server, "_session_uses_compute_host", stop_before_claim)
    assert server._drain_queued_prompt("F03", "F03-owned", session) is False
    assert delivered == []
    assert session.get("queued_prompt") is None
    assert session.get("queued_prompts") is None
    assert session["_queued_prompt_generation"] == 8


def test_busy_steer_fallback_rechecks_a_later_turn_stop(monkeypatch):
    agent, session = _stoppable_session(monkeypatch)
    real_admission = server._try_session_steer
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "steer")

    def settle_then_stop_later_turn(*args, **kwargs):
        server._settle_session_turn(session, agent, {}, False)
        accepted = real_admission(*args, **kwargs)
        assert accepted is False
        with session["history_lock"]:
            session["running"] = True
        response = server._methods["session.interrupt"]("F03", {"session_id": "F03-owned"})
        assert "error" not in response
        return accepted

    monkeypatch.setattr(server, "_try_session_steer", settle_then_stop_later_turn)
    response = server._handle_busy_submit("F03", "F03-owned", session, "New 日本語", None)
    assert response.get("error", {}).get("code") == 4009
    assert session.get("queued_prompt") is None
    assert agent._drain_pending_steer() is None
    assert session["_queued_prompt_generation"] == 8


def test_stop_discards_pending_steer_before_cancelled_tool_result_is_recorded(monkeypatch):
    agent, session = _stoppable_session(monkeypatch)
    payload = "Cancelled tool boundary 日本語"
    response = server._methods["slash.exec"]("F03", {
        "session_id": "F03-owned", "command": f"/s {payload}",
    })
    assert "error" not in response
    stopped = server._methods["session.interrupt"]("F03", {"session_id": "F03-owned"})
    assert "error" not in stopped
    messages = [{"role": "tool", "tool_call_id": "cancelled", "content": "cancelled tool result"}]
    before = deepcopy(messages)
    agent._apply_pending_steer_to_tool_results(messages, 1)
    assert messages == before
    assert agent._drain_pending_steer() is None
    assert session.get("queued_prompt") is None


@pytest.mark.parametrize("drain_kind", ["absent", "raises"])
def test_stop_preserves_hard_interrupt_and_cleanup_for_legacy_drain(monkeypatch, drain_kind):
    agent, session = _stoppable_session(monkeypatch)
    cleaned = []
    real_cleanup = server._clear_pending

    def observe_cleanup(sid):
        cleaned.append(sid)
        return real_cleanup(sid)

    def failing_drain():
        raise RuntimeError("test-owned legacy drain failure")

    monkeypatch.setattr(agent, "_drain_pending_steer", None if drain_kind == "absent" else failing_drain)
    monkeypatch.setattr(server, "_clear_pending", observe_cleanup)
    response = server._methods["session.interrupt"]("F03", {"session_id": "F03-owned"})
    assert "error" not in response
    assert agent._interrupt_requested is True
    assert cleaned == ["F03-owned"]
    assert session["_queued_prompt_generation"] == 8


@pytest.mark.parametrize("command", ["/steer", "/s", "/S"])
@pytest.mark.parametrize("cached_agent", [False, True])
def test_slash_exec_idle_alias_returns_next_turn_text(monkeypatch, command, cached_agent):
    agent, worker_commands = _session(monkeypatch, active=False, cached_agent=cached_agent)
    response = server._methods["slash.exec"]("F03", {
        "session_id": "F03-owned", "command": f"{command} Keep Case",
    })
    assert response["result"] == {"type": "send", "message": "Keep Case"}
    assert worker_commands == []
    assert agent._drain_pending_steer() is None


@pytest.mark.parametrize("command", ["/steer", "/s"])
def test_slash_exec_empty_alias_rejects_without_effect(monkeypatch, command):
    agent, worker_commands = _session(monkeypatch)
    response = server._methods["slash.exec"]("F03", {
        "session_id": "F03-owned", "command": command,
    })
    assert "error" in response
    assert response["error"]["code"] == 4004
    assert worker_commands == []
    assert agent._drain_pending_steer() is None


def test_slash_exec_stale_session_does_not_steer_another_session(monkeypatch):
    agent, worker_commands = _session(monkeypatch)
    before = deepcopy(server._sessions["F03-owned"]["history"])
    response = server._methods["slash.exec"]("F03", {
        "session_id": "F03-missing", "command": "/s Cross-session text",
    })
    assert response["error"]["code"] == 4001
    assert server._sessions["F03-owned"]["history"] == before
    assert worker_commands == []
    assert agent._drain_pending_steer() is None


@pytest.mark.parametrize("name", ["steer", "s", "S"])
def test_direct_dispatch_missing_session_preserves_send_fallback(monkeypatch, name):
    agent, worker_commands = _session(monkeypatch)
    response = server._methods["command.dispatch"]("F03", {
        "session_id": "F03-missing", "name": name, "arg": "Keep Case",
    })
    assert response["result"] == {"type": "send", "message": "Keep Case"}
    assert worker_commands == []
    assert agent._drain_pending_steer() is None
