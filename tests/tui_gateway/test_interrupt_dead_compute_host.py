from __future__ import annotations

import threading

from tests.tui_gateway.test_protocol import server


def test_session_interrupt_cleans_queued_prompts_when_compute_host_has_no_turn(
    server, monkeypatch
):
    class _DeadSupervisor:
        def __init__(self):
            self.interrupt_calls = []

        def has_pending_turn(self, _sid):
            return False

        def interrupt(self, sid, *, request_id=None):
            self.interrupt_calls.append((sid, request_id))
            raise RuntimeError("compute host is unavailable")

    supervisor = _DeadSupervisor()
    session = {
        "agent": None,
        "agent_ready": threading.Event(),
        "history": [],
        "history_lock": threading.Lock(),
        "running": True,
        "session_key": "dead-compute-host-session",
        "queued_prompt": {"text": "must be discarded"},
        "queued_prompts": [{"text": "also discard"}],
        "_queued_prompt_generation": 4,
        "_compute_host_active": True,
    }
    server._sessions["dead-compute-host-sid"] = session
    monkeypatch.setattr(
        server, "_load_cfg", lambda: {"dashboard": {"turn_isolation": True}}
    )
    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda _cfg=None: supervisor)
    monkeypatch.setattr(server, "_tts_stream_stop", lambda: None)

    try:
        response = server.handle_request(
            {
                "id": "stop-dead-host",
                "method": "session.interrupt",
                "params": {"session_id": "dead-compute-host-sid"},
            }
        )
    finally:
        server._sessions.pop("dead-compute-host-sid", None)

    assert response.get("result"), f"got error: {response.get('error')}"
    assert response["result"] == {
        "status": "interrupted",
        "turn_isolation": True,
    }
    assert supervisor.interrupt_calls == []
    assert session["_turn_cancel_requested"] is True
    assert session["queued_prompt"] is None
    assert "queued_prompts" not in session
    assert session["_queued_prompt_generation"] == 5
    assert session["running"] is False
    assert session["inflight_turn"] is None
