from __future__ import annotations

import threading

import pytest

from tests.tui_gateway.test_protocol import server
from tui_gateway.host_supervisor import HostSupervisor


def _install_public_prompt_seams(server, monkeypatch, session, supervisor, *, route):
    import tools.approval as approval

    monkeypatch.setattr(server, "_ensure_active_session_slot", lambda *_args: None)
    monkeypatch.setattr(server, "_session_uses_compute_host", route)
    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda *_args: supervisor)
    monkeypatch.setattr(server, "_load_dashboard_process_isolation_config", lambda: {})
    monkeypatch.setattr(server, "_compute_host_turn_frame", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(server, "_session_info", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(server, "_tts_stream_stop", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_clear_pending", lambda *_args: None)
    monkeypatch.setattr(server, "_drain_queued_prompt", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(approval, "resolve_gateway_approval", lambda *_args, **_kwargs: None)
    server._sessions[session["_sid"]] = session


def _public_prompt_submit(server, sid, text):
    return server._methods["prompt.submit"](
        "prompt", {"session_id": sid, "text": text}
    )


def _public_interrupt(server, sid):
    return server.handle_request(
        {
            "id": "stop",
            "method": "session.interrupt",
            "params": {"session_id": sid},
        }
    )


@pytest.mark.parametrize("completion", ["normal", "crash", "send_failed"])
def test_taken_callback_remains_outstanding(tmp_path, monkeypatch, completion):
    supervisor = HostSupervisor(
        registry_path=tmp_path / "registry.json", autostart=False,
        expected_build_sha="test", expected_hermes_home=str(tmp_path),
    )
    entered, release = threading.Event(), threading.Event()
    calls = []

    def callback(frame):
        calls.append(frame)
        entered.set()
        assert release.wait(3)

    def finish():
        if completion == "send_failed":
            with pytest.raises(RuntimeError, match="pipe closed"):
                supervisor.submit_turn({"sid": "one", "request_id": "old"}, on_complete=callback)
        elif completion == "crash":
            supervisor._fail_pending_turns(reason="crash", message="gone")
        else:
            supervisor._complete_turn({"type": "turn.end", "request_id": "old"})

    monkeypatch.setattr(supervisor, "start", lambda: None)
    def fail_send(_frame):
        raise RuntimeError("pipe closed")
    monkeypatch.setattr(supervisor, "_send_frame", fail_send)
    if completion != "send_failed":
        supervisor._pending_turns["old"] = ("one", callback)
    worker = threading.Thread(target=finish)
    worker.start()
    try:
        assert entered.wait(3)
        assert supervisor.has_pending_turn("one")
        assert not supervisor.has_pending_turn("other")
        supervisor._complete_turn({"type": "turn.end", "request_id": "old"})
        assert len(calls) == 1
        supervisor._pending_turns["successor"] = ("one", None)
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert supervisor.has_pending_turn("one")
    supervisor._complete_turn({"type": "turn.end", "request_id": "successor"})
    assert not supervisor.has_pending_turn("one")


@pytest.mark.parametrize("timing", ["before", "during", "queued"])
def test_stop_during_dispatch_preserves_owner_until_dispatch_finishes(server, monkeypatch, timing):
    sid = "dispatch-owner"
    owner = {"dispatching": True}
    session = {
        "agent": None, "agent_ready": threading.Event(), "history": [],
        "history_lock": threading.Lock(), "running": True,
        "session_key": sid, "_compute_host_turn": owner,
        "queued_prompt": {"text": "discard"},
    }
    server._sessions[sid] = session
    calls = []

    def stop():
        return server.handle_request({"id": "stop", "method": "session.interrupt", "params": {"session_id": sid}})

    class Supervisor:
        def has_pending_turn(self, _sid):
            return False

        def submit_turn(self, frame, *, on_complete):
            calls.append("submit")
            if timing == "during":
                assert stop()["result"]["status"] == "interrupted"
                assert session["running"]
            on_complete({"type": "turn.end", "session_info_emitted": True})
            assert session["running"], "completion must wait for dispatch cancellation"

        def interrupt(self, target, *, request_id=None):
            assert target == sid
            assert session["running"]
            calls.append("interrupt")

    monkeypatch.setattr(server, "_session_uses_compute_host", lambda *_args: True)
    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda *_args: Supervisor())
    monkeypatch.setattr(server, "_load_dashboard_process_isolation_config", lambda: {})
    monkeypatch.setattr(server, "_compute_host_turn_frame", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(server, "_session_info", lambda *_args: {})
    monkeypatch.setattr(server, "_tts_stream_stop", lambda: None)
    try:
        if timing == "queued":
            session["running"] = False
            session.pop("_compute_host_turn")
            original_submit = server._submit_prompt_to_compute_host

            def submit_after_stop(*args, **kwargs):
                assert session["_compute_host_turn"]["dispatching"]
                assert stop()["result"]["status"] == "interrupted"
                return original_submit(*args, **kwargs)

            monkeypatch.setattr(server, "_submit_prompt_to_compute_host", submit_after_stop)
            assert server._drain_queued_prompt("queued", sid, session)
            assert not session["running"]
            assert "_compute_host_turn" not in session
            assert calls == []
            return
        if timing == "before":
            assert stop()["result"]["status"] == "interrupted"
            assert session["running"]
        response = server._submit_prompt_to_compute_host("submit", sid, session, "hello")
        assert "result" in response
        assert not session["running"]
        assert session["queued_prompt"] is None
        assert "_compute_host_turn" not in session
        assert calls == ([] if timing == "before" else ["submit", "interrupt"])
    finally:
        server._sessions.pop(sid, None)


def test_callback_exception_retains_unsettled_ownership(tmp_path):
    supervisor = HostSupervisor(
        registry_path=tmp_path / "registry.json", autostart=False,
        expected_build_sha="test", expected_hermes_home=str(tmp_path),
    )
    def fail(_frame):
        raise RuntimeError("settlement failed")
    supervisor._pending_turns["old"] = ("one", fail)
    supervisor._complete_turn({"type": "turn.end", "request_id": "old"})
    assert supervisor.has_pending_turn("one")
    assert not supervisor.has_pending_turn("other")


def test_probe_error_fails_closed_and_orphan_interrupt_keeps_error(server, monkeypatch):
    session = {
        "running": True, "history_lock": threading.Lock(),
        "session_key": "one", "queued_prompt": {"text": "keep"},
    }
    class Supervisor:
        def has_pending_turn(self, _sid):
            raise RuntimeError("probe failed")
        def interrupt(self, _sid, **_kwargs):
            raise RuntimeError("interrupt failed")
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda *_args: True)
    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda *_args: Supervisor())
    with pytest.raises(RuntimeError, match="probe failed"):
        server._interrupt_session_turn("one", session, recover_stale=True)
    assert session["running"]
    assert session["queued_prompt"] == {"text": "keep"}
    with pytest.raises(RuntimeError, match="interrupt failed"):
        server._interrupt_session_turn("one", session)
    assert session["running"]


def test_old_completion_cannot_clear_successor(server):
    old_owner, successor = {"dispatching": False}, {"dispatching": True}
    inflight = {"user": "new turn"}
    session = {
        "running": True, "history_lock": threading.Lock(),
        "_compute_host_turn": successor, "inflight_turn": inflight,
    }
    server._on_compute_host_turn_done(
        "old", "one", session, {"type": "turn.end"}, owner=old_owner
    )
    assert session["running"]
    assert session["inflight_turn"] is inflight
    assert session["_compute_host_turn"] is successor


@pytest.mark.parametrize("active", [False, True, "admitting"])
@pytest.mark.parametrize("failure", [None, "pending", "approval"])
def test_stop_holds_owner_through_card_cleanup_and_can_retry(server, monkeypatch, active, failure):
    import tools.approval as approval

    sid = "cleanup-owner"
    owner = {"dispatching": active == "admitting"}
    session = {
        "agent": None, "history": [], "session_key": sid,
        "history_lock": threading.Lock(), "running": True,
        "queued_prompt": {"text": "old queued"},
    }
    if active:
        session["_compute_host_turn"] = owner
    events = []
    class Supervisor:
        def has_pending_turn(self, _sid):
            return False
        def interrupt(self, _sid, **_kwargs):
            assert active
            server._on_compute_host_turn_done(
                "old", sid, session,
                {"type": "turn.end", "session_info_emitted": True}, owner=owner,
            )
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda *_args: True)
    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda *_args: Supervisor())
    monkeypatch.setattr(server, "_session_info", lambda *_args: {})
    def clear_pending(_sid):
        assert session["running"], "old Stop must not expose idle before card cleanup"
        assert session.get("_compute_host_turn") is not None
        if active == "admitting":
            # Dispatch consumes the pending cancellation while Stop is still
            # cleaning old cards; it must defer idle to the Stop owner.
            response = server._submit_prompt_to_compute_host("old", sid, session, "cancelled")
            assert response["result"]["status"] == "interrupted"
            assert session["running"]
        events.append("pending")
        if failure == "pending":
            raise RuntimeError("pending failed")
    def deny(*_args, **_kwargs):
        assert session["running"], "successor must not start before old approval denial"
        events.append("approval")
        if failure == "approval":
            raise RuntimeError("approval failed")
    monkeypatch.setattr(server, "_clear_pending", clear_pending)
    monkeypatch.setattr(approval, "resolve_gateway_approval", deny)
    def successor(_rid, _sid, _session):
        assert not session["running"]
        assert events[-1] == "approval"
        session["running"] = True
        session["_compute_host_turn"] = {"dispatching": True}
        events.append("successor-card")
        return True
    monkeypatch.setattr(server, "_drain_queued_prompt", successor)
    if failure is not None:
        with pytest.raises(RuntimeError, match=f"{failure} failed"):
            server._interrupt_session_turn(sid, session, recover_stale=True)
        assert session["running"]
        assert "successor-card" not in events
        failure = None
    server._interrupt_session_turn(sid, session, recover_stale=True)
    assert events[-1] == "successor-card"
    assert session["running"]
    assert session["_compute_host_turn"] is not owner


def test_public_prompt_submit_retries_after_stale_stop(server, monkeypatch):
    sid = "public-stale-retry"
    session = {
        "_sid": sid, "agent": None, "agent_ready": threading.Event(),
        "history": [], "history_lock": threading.Lock(), "running": True,
        "session_key": sid, "queued_prompt": {"text": "stale"},
        "attached_images": [],
    }
    submitted = []

    class Supervisor:
        def has_pending_turn(self, _sid):
            return False

        def submit_turn(self, frame, *, on_complete):
            submitted.append((frame, on_complete))

        def interrupt(self, _sid, **_kwargs):
            raise AssertionError("stale recovery must not interrupt a settled host")

    supervisor = Supervisor()
    _install_public_prompt_seams(
        server, monkeypatch, session, supervisor, route=lambda *_args: True
    )
    try:
        stopped = _public_interrupt(server, sid)
        assert stopped["result"]["status"] == "interrupted"
        assert not session["running"]
        assert "_compute_host_turn" not in session

        response = _public_prompt_submit(server, sid, "fresh prompt")
        assert response["result"]["status"] == "streaming"
        assert session["running"]
        assert session["_turn_cancel_requested"] is False
        assert len(submitted) == 1
        new_owner = session["_compute_host_turn"]
        assert new_owner.get("dispatching") is False
        submitted[0][1]({"type": "turn.end", "session_info_emitted": True})
        assert not session["running"]
        assert "_compute_host_turn" not in session
    finally:
        server._sessions.pop(sid, None)


def test_public_stop_buffers_completion_until_prompt_dispatch_finishes(server, monkeypatch):
    sid = "public-dispatch-stop"
    session = {
        "_sid": sid, "agent": None, "agent_ready": threading.Event(),
        "history": [], "history_lock": threading.Lock(), "running": False,
        "session_key": sid, "queued_prompt": None, "attached_images": [],
    }
    entered, release = threading.Event(), threading.Event()
    callback = {}
    worker_result = {}

    class Supervisor:
        def has_pending_turn(self, _sid):
            return False

        def submit_turn(self, _frame, *, on_complete):
            callback["done"] = on_complete
            entered.set()
            assert release.wait(5)

        def interrupt(self, _sid, **_kwargs):
            assert session["running"]

    supervisor = Supervisor()
    _install_public_prompt_seams(
        server, monkeypatch, session, supervisor, route=lambda *_args: True
    )

    def clear_pending(_sid):
        callback["done"]({"type": "turn.end", "session_info_emitted": True})
        assert session["running"], "Stop must retain ownership while cleanup is active"

    monkeypatch.setattr(server, "_clear_pending", clear_pending)

    def submit():
        try:
            worker_result["response"] = _public_prompt_submit(server, sid, "active prompt")
        except BaseException as exc:
            worker_result["error"] = exc

    worker = threading.Thread(target=submit)
    worker.start()
    try:
        assert entered.wait(5)
        owner = session["_compute_host_turn"]
        assert owner["dispatching"]
        stopped = _public_interrupt(server, sid)
        assert stopped["result"]["status"] == "interrupted"
        assert session["running"]
        assert session["_compute_host_turn"] is owner
        assert owner.get("completion") is not None
    finally:
        release.set()
        worker.join(5)
        server._sessions.pop(sid, None)
    assert not worker.is_alive()
    assert "error" not in worker_result
    assert worker_result["response"]["result"]["status"] == "streaming"
    assert not session["running"]
    assert "_compute_host_turn" not in session


def test_public_stop_cancels_inline_fallback_after_send_failure(server, monkeypatch):
    import agent.interrupt_compat as interrupt_compat

    sid = "public-inline-fallback-stop"
    session = {
        "_sid": sid, "agent": None, "agent_ready": threading.Event(),
        "history": [], "history_lock": threading.Lock(), "running": False,
        "session_key": sid, "queued_prompt": None, "attached_images": [],
    }
    entered_db, release_db, cancelled = (
        threading.Event(), threading.Event(), threading.Event()
    )
    run_calls, interrupt_calls = [], []
    worker_result = {}

    class Supervisor:
        def has_pending_turn(self, _sid):
            return False

        def submit_turn(self, _frame, *, on_complete):
            on_complete({"reason": "send_failed"})
            raise RuntimeError("pipe closed")

        def interrupt(self, _sid, **_kwargs):
            raise AssertionError("fallback Stop must follow local ownership")

    supervisor = Supervisor()
    route = lambda *_args: not session.get("_compute_host_inline_fallback")
    _install_public_prompt_seams(server, monkeypatch, session, supervisor, route=route)

    def persist(_session):
        entered_db.set()
        assert release_db.wait(5)

    def start_build(_sid, target):
        target["agent_ready"].set()

    monkeypatch.setattr(server, "_ensure_session_db_row", persist)
    monkeypatch.setattr(server, "_persist_branch_seed", lambda *_args: None)
    monkeypatch.setattr(server, "_start_agent_build", start_build)
    monkeypatch.setattr(server, "_run_prompt_submit", lambda *args, **kwargs: run_calls.append(args))
    monkeypatch.setattr(server, "_emit", lambda event, *_args: cancelled.set() if event == "error" else None)
    monkeypatch.setattr(
        interrupt_compat, "request_hard_interrupt", lambda _agent: interrupt_calls.append("stop")
    )

    def submit():
        try:
            worker_result["response"] = _public_prompt_submit(server, sid, "inline prompt")
        except BaseException as exc:
            worker_result["error"] = exc

    worker = threading.Thread(target=submit)
    worker.start()
    try:
        assert entered_db.wait(5)
        assert session["_compute_host_inline_fallback"] is True
        stopped = _public_interrupt(server, sid)
        assert stopped["result"]["status"] == "interrupted"
        assert not session["running"]
        assert interrupt_calls == ["stop"]
    finally:
        release_db.set()
        worker.join(5)
    run_thread = session.get("_run_thread")
    if run_thread is not None:
        run_thread.join(5)
    assert not worker.is_alive()
    assert "error" not in worker_result
    assert worker_result["response"]["result"]["status"] == "streaming"
    assert cancelled.wait(5)
    assert run_calls == []
    server._sessions.pop(sid, None)
