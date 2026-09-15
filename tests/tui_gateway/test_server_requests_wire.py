"""NC-0213-D1: server→client JSON-RPC request wire (U_NEXT COMPOSE, no contracts pkg)."""

from __future__ import annotations

import threading

import pytest

from tui_gateway import server_requests as sr


@pytest.fixture(autouse=True)
def _reset_server_requests():
    frames: list[dict] = []
    events: list[tuple[str, str, dict]] = []
    sr.reset_for_tests()
    sr.bind_sinks(frames.append, lambda ev, sid, payload: events.append((ev, sid, payload)))
    yield frames, events
    sr.reset_for_tests()


def test_send_resolve_round_trip( _reset_server_requests):
    frames, _events = _reset_server_requests
    result_box: dict = {}

    def worker():
        result_box["value"] = sr.send("clarify", "sess-a", {"question": "go?"}, timeout=2.0)

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(50):
        if frames:
            break
        t.join(0.01)
    assert frames, "expected outbound request frame"
    frame = frames[0]
    assert frame["id"].startswith("srq-")
    assert frame["method"] == "clarify"
    assert frame["params"]["session_id"] == "sess-a"
    assert sr.resolve_response({"id": frame["id"], "result": {"answer": "yes"}}) is True
    t.join(2.0)
    assert result_box["value"] == {"answer": "yes"}


def test_stale_response_dropped(_reset_server_requests):
    assert sr.resolve_response({"id": "srq-deadbeef000", "result": {"answer": "no"}}) is False


def test_cancel_is_session_scoped(_reset_server_requests):
    _frames, events = _reset_server_requests
    opened = []

    def open_one(sid: str):
        def worker():
            opened.append(sr.send("sudo", sid, {"prompt": "pw"}, timeout=3.0))

        t = threading.Thread(target=worker)
        t.start()
        return t

    t1 = open_one("s1")
    t2 = open_one("s2")
    for _ in range(100):
        if len(sr.open_requests("s1")) == 1 and len(sr.open_requests("s2")) == 1:
            break
        threading.Event().wait(0.01)
    assert sr.cancel("s1", reason="interrupted") == 1
    t1.join(2.0)
    assert opened[0] is None
    assert any(ev == "request.cancel" and sid == "s1" for ev, sid, _ in events)
    assert len(sr.open_requests("s2")) == 1
    assert sr.cancel("s2") == 1
    t2.join(2.0)


def test_open_requests_snapshot_and_batch_lock(_reset_server_requests):
    frames, _ = _reset_server_requests
    box: dict = {}

    def worker():
        box["value"] = sr.send(
            "clarify",
            "sess-b",
            {"questions": [{"qid": "q1", "question": "a"}, {"qid": "q2", "question": "b"}]},
            timeout=2.0,
            qids=["q1", "q2"],
        )

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(50):
        if frames:
            break
        t.join(0.01)
    rid = frames[0]["id"]
    assert sr.lock_answer(rid, "q1", "one") == ["q2"]
    snap = sr.open_requests("sess-b")
    assert len(snap) == 1
    assert snap[0]["params"]["answers"] == {"q1": "one"}
    assert sr.lock_answer(rid, "q2", "two") == []
    t.join(2.0)
    assert box["value"] == {"answers": {"q1": "one", "q2": "two"}}


def test_is_response_frame_and_unknown_method(_reset_server_requests):
    assert sr.is_response_frame({"id": "srq-1", "result": {}}) is True
    assert sr.is_response_frame({"id": 1, "method": "session.list", "params": {}}) is False
    with pytest.raises(RuntimeError, match="not an allowed"):
        sr.send("not.a.method", "s", {}, timeout=0)
