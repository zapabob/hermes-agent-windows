from __future__ import annotations

import threading

import pytest

from tests.tui_gateway.test_protocol import server


@pytest.mark.parametrize(
    ("build_state", "agent_error"),
    [("pending", None), ("failed", "agent build failed")],
    ids=["pending-build", "failed-build"],
)
def test_session_interrupt_does_not_wait_for_agent_build(
    server, monkeypatch, build_state, agent_error
):
    release_agent_wait = threading.Event()
    completed = threading.Event()
    response: dict = {}
    build_calls = []
    sid = f"interrupt-build-{build_state}"
    agent_ready = threading.Event()
    if agent_error:
        agent_ready.set()

    session = {
        "agent": None,
        "agent_ready": agent_ready,
        "history": [],
        "history_lock": threading.Lock(),
        "running": True,
        "session_key": sid,
        "queued_prompt": {"text": "discard me"},
        "queued_prompts": [{"text": "discard me too"}],
        "_queued_prompt_generation": 3,
        "_run_thread": None,
    }
    if agent_error:
        session["agent_error"] = agent_error
    server._sessions[sid] = session

    def _start_agent_build(*_args):
        build_calls.append("start")

    def _wait_for_agent(_session, _rid, timeout=30.0):
        build_calls.append("wait")
        release_agent_wait.wait(timeout=5.0)
        return None

    monkeypatch.setattr(server, "_start_agent_build", _start_agent_build)
    monkeypatch.setattr(server, "_wait_agent", _wait_for_agent)
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda _session: False)
    monkeypatch.setattr(server, "_tts_stream_stop", lambda: None)

    def _interrupt():
        response["rpc"] = server.handle_request(
            {
                "id": "stop",
                "method": "session.interrupt",
                "params": {"session_id": sid},
            }
        )
        completed.set()

    worker = threading.Thread(target=_interrupt, daemon=True)
    worker.start()
    try:
        assert completed.wait(timeout=1.0), (
            "session.interrupt waited for deferred agent construction"
        )
        assert response["rpc"]["result"]["status"] == "interrupted"
        assert build_calls == []
        assert session["_turn_cancel_requested"] is True
        assert session["queued_prompt"] is None
        assert "queued_prompts" not in session
        assert session["_queued_prompt_generation"] == 4
    finally:
        release_agent_wait.set()
        worker.join(timeout=2.0)
        server._sessions.pop(sid, None)

    assert not worker.is_alive()
