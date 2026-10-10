"""Public admission wait/start failure effects; SDK success is separate."""
import json
import socket
import threading
import time

import pytest

from tests.fakes.mcp_oauth_admission import admission as admission
from tests.fakes.mcp_oauth_gateway import homes as homes, refused




def test_cancelled_owner_accepts_one_of_two_concurrent_replacements(admission, record_property):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    first = rpc("start")["result"]
    old = sessions._sessions[first["session_id"]]
    release.clear()
    assert rpc("cancel", session_id=first["session_id"])["result"]["cancelled"]
    assert not old["flow"].worker_done
    entered = [threading.Event(), threading.Event()]
    outcomes = {}

    def retry(index):
        entered[index].set()
        try:
            result = rpc("start")
        except BaseException as error:
            result = {"observed_exception": repr(error)}
        with guard:
            outcomes[index] = result

    try:
        for index in range(2):
            thread = threading.Thread(target=retry, args=(index,), name="owned-edge-retry-" + str(index))
            thread.start()
            callers.append(thread)
        assert all(event.wait(2) for event in entered)
        for thread in callers:
            thread.join(timeout=0.1)
        with guard:
            before_release = dict(outcomes)
        record_property("replacement_before_old_release", json.dumps({
            "old_worker_done": old["flow"].worker_done, "completed_public_responses": before_release,
        }))
        release.set()
        for thread in callers:
            thread.join(timeout=6)
            assert not thread.is_alive()
        with guard:
            completed = dict(outcomes)
        record_property("replacement_public_responses", json.dumps(completed))
        assert set(completed) == {0, 1}, completed
        assert all("observed_exception" not in row for row in completed.values()), completed
        allowed = [row["result"] for row in completed.values() if "result" in row and row["result"].get("ok")]
        assert len(allowed) == 1, completed
        assert allowed[0]["session_id"] != first["session_id"]
        assert sum("error" in row for row in completed.values()) == 1
        assert old["flow"].snapshot()["error"] == "Cancelled by user"
        with sessions._sessions_lock:
            pending = [rec["flow"] for rec in sessions._sessions.values()]
        assert sum(not flow.worker_done for flow in pending) == 1
    finally:
        release.set()


def test_cancelled_worker_exhaustion_uses_one_bounded_budget(admission, monkeypatch, record_property):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    first = rpc("start")["result"]
    release.clear()
    assert rpc("cancel", session_id=first["session_id"])["result"]["cancelled"]
    actual_start = sessions.start_flow

    def short_budget(*args, **kwargs):
        return actual_start(*args, **kwargs, url_timeout=0.25)

    monkeypatch.setattr(sessions, "start_flow", short_budget)
    started = time.monotonic()
    result = rpc("start")
    elapsed = time.monotonic() - started
    record_property("cancelled_budget", json.dumps({"response": result, "elapsed": elapsed,
                    "old_worker_done": sessions._sessions[first["session_id"]]["flow"].worker_done}))
    assert "error" in result and "cancelled" in result["error"]["message"].lower(), result
    assert 0.2 <= elapsed < 2
    assert len(sessions._sessions) == 1


def test_cancelled_cleanup_and_new_url_wait_share_deadline(admission, monkeypatch, record_property):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    first = rpc("start")["result"]
    old = sessions._sessions[first["session_id"]]
    release.clear()
    assert rpc("cancel", session_id=first["session_id"])["result"]["cancelled"]
    assert not old["flow"].worker_done
    authorization_release.clear()
    actual_start = sessions.start_flow

    def shared_budget(*args, **kwargs):
        return actual_start(*args, **kwargs, url_timeout=1.5)

    monkeypatch.setattr(sessions, "start_flow", shared_budget)
    timer = threading.Timer(0.6, release.set)
    timer.name = "owned-edge-old-cleanup-release"
    timer.start()
    callers.append(timer)
    started = time.monotonic()
    result = rpc("start")
    elapsed = time.monotonic() - started
    record_property("actual_two_phase_budget", json.dumps({
        "response": result, "elapsed": elapsed, "old_worker_done": old["flow"].worker_done,
        "replacement_waited_for_url": authorization_held.is_set(),
    }))
    assert old["flow"].worker_done and authorization_held.is_set(), result
    assert "error" in result and "authorization URL" in result["error"]["message"], result
    assert 1.3 <= elapsed < 1.8


def test_expired_cancelled_worker_keeps_its_owned_slot(admission, monkeypatch, record_property):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    first = rpc("start")["result"]
    old = sessions._sessions[first["session_id"]]
    release.clear()
    assert rpc("cancel", session_id=first["session_id"])["result"]["cancelled"]
    assert not old["flow"].worker_done
    with sessions._sessions_lock:
        old["created_at"] -= sessions._SESSION_TTL_SECONDS + 1
    actual_start = sessions.start_flow

    def short_budget(*args, **kwargs):
        return actual_start(*args, **kwargs, url_timeout=0.25)

    monkeypatch.setattr(sessions, "start_flow", short_budget)
    result = rpc("start")
    with sessions._sessions_lock:
        retained = sessions._sessions.get(first["session_id"]) is old
        pending = list(sessions._sessions)
    record_property("expired_pending_reservation", json.dumps({
        "response": result, "original_retained": retained, "registered_ids": pending,
        "old_worker_done": old["flow"].worker_done,
    }))
    assert retained and pending == [first["session_id"]], result
    assert "error" in result and "cancelled" in result["error"]["message"].lower(), result


@pytest.mark.parametrize("failure_kind", ["listener-start", "callback-thread-start", "worker-start"])
def test_setup_failure_does_not_leave_a_pending_reservation(admission, monkeypatch, failure_kind, record_property):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    acquired = []
    try:
        with monkeypatch.context() as local:
            if failure_kind == "listener-start":
                def failed_listener(flow):
                    raise OSError("Owned synthetic listener startup failure")
                local.setattr(sessions, "_start_loopback_listener", failed_listener)
            else:
                original = threading.Thread.start
                def failed_worker(thread):
                    target = "mcp-oauth-cb-reports" if failure_kind == "callback-thread-start" else "mcp-oauth-reports"
                    if thread.name == target:
                        raise RuntimeError("Owned synthetic worker startup failure")
                    return original(thread)
                local.setattr(threading.Thread, "start", failed_worker)
                if failure_kind == "callback-thread-start":
                    actual_server = sessions.http.server.HTTPServer
                    def observed_server(*args, **kwargs):
                        httpd = actual_server(*args, **kwargs)
                        acquired.append(httpd)
                        return httpd
                    local.setattr(sessions.http.server, "HTTPServer", observed_server)
            result = rpc("start")
            with sessions._sessions_lock:
                snapshot = [{"id": sid, "done": rec["flow"].worker_done, "flow": rec["flow"].snapshot(),
                             "listener_present": rec.get("httpd") is not None} for sid, rec in sessions._sessions.items()]
            record_property("failed_start_reservations", json.dumps({"response": result, "reservations": snapshot,
                            "callback_ports_before_fixture_close": [httpd.server_address[1] for httpd in acquired]}))
            assert "error" in result and "Owned synthetic" in result["error"]["message"], result
            assert all(row["done"] and not row["listener_present"] for row in snapshot), snapshot
            if failure_kind == "callback-thread-start":
                assert len(acquired) == 1
                try:
                    with socket.create_connection(("127.0.0.1", acquired[0].server_address[1]), timeout=4):
                        port_outcome = {"status": "accepted"}
                except ConnectionRefusedError:
                    port_outcome = {"status": "refused"}
                except BaseException as error:
                    port_outcome = {"status": "unexpected_exception", "error": repr(error)}
                record_property("unstarted_callback_before_fixture_close", json.dumps(port_outcome))
                assert port_outcome["status"] == "refused", port_outcome
    finally:
        # These servers belong to the constructor spy; the injected callback
        # thread failure occurs before Thread.start and never enters serving.
        failures = []
        for httpd in acquired:
            port = httpd.server_address[1]
            try:
                httpd.server_close()
                refused(port)
            except BaseException as error:
                failures.append(repr(error))
        record_property("unstarted_callback_cleanup", json.dumps({"failures": failures}))
        assert not failures, failures
    recovery = rpc("start")
    assert recovery.get("result", {}).get("ok"), recovery


def test_foreign_cancel_cannot_release_owner_admission(admission, record_property):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    first = rpc("start")["result"]
    rec = sessions._sessions[first["session_id"]]
    foreign = rpc("cancel", profile="other", session_id=first["session_id"])
    overlap = rpc("start")
    record_property("foreign_admission", json.dumps({"cancel": foreign, "overlap": overlap}))
    assert not foreign.get("result", {}).get("cancelled")
    assert not rec["flow"]._callback_ready.is_set() and not rec["flow"].worker_done
    assert "error" in overlap and "already in progress" in overlap["error"]["message"]
    assert len(sessions._sessions) == 1
