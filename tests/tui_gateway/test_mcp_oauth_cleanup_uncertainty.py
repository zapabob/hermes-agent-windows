"""Keep ownership when an acquired callback socket cannot confirm cleanup."""
import json
import socket
import threading

from tests.fakes.mcp_oauth_admission import admission as admission
from tests.fakes.mcp_oauth_gateway import homes as homes, refused


def test_unconfirmed_callback_startup_cleanup_keeps_admission(admission, monkeypatch, record_property):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    acquired = []
    close_attempts = []
    actual_server = sessions.http.server.HTTPServer
    actual_thread_start = threading.Thread.start
    try:
        with monkeypatch.context() as local:
            def observed_server(*args, **kwargs):
                httpd = actual_server(*args, **kwargs)
                actual_close = httpd.server_close
                acquired.append((httpd, actual_close))

                def failed_close():
                    close_attempts.append(httpd.server_address[1])
                    raise OSError("Owned synthetic socket cleanup uncertainty")

                local.setattr(httpd, "server_close", failed_close)
                return httpd

            def failed_start(thread):
                if thread.name == "mcp-oauth-cb-reports":
                    raise RuntimeError("Owned synthetic callback startup failure")
                return actual_thread_start(thread)

            local.setattr(sessions.http.server, "HTTPServer", observed_server)
            local.setattr(threading.Thread, "start", failed_start)
            result = rpc("start")
            assert len(acquired) == 1
            port = acquired[0][0].server_address[1]
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2):
                    port_outcome = {"status": "accepted"}
            except ConnectionRefusedError:
                port_outcome = {"status": "refused"}
            except BaseException as error:
                port_outcome = {"status": "unexpected_exception", "error": repr(error)}
            with sessions._sessions_lock:
                snapshot = [{"id": sid, "done": rec["flow"].worker_done,
                             "listener_owned": rec.get("httpd") is acquired[0][0],
                             "flow": rec["flow"].snapshot()} for sid, rec in sessions._sessions.items()]
            record_property("actual_uncertain_callback_cleanup", json.dumps({
                "response": result, "port_outcome": port_outcome,
                "close_attempts": close_attempts, "reservations": snapshot,
            }))
            assert port_outcome["status"] == "accepted", port_outcome
            assert "error" in result and "Owned synthetic callback startup failure" in result["error"]["message"], result
            assert len(snapshot) == 1 and not snapshot[0]["done"] and snapshot[0]["listener_owned"], snapshot
            assert snapshot[0]["flow"]["error"] == "Owned synthetic callback startup failure"
            assert close_attempts, close_attempts
            overlap = rpc("start")
            with sessions._sessions_lock:
                ids = list(sessions._sessions)
            record_property("uncertain_owner_overlap", json.dumps({"response": overlap, "registered_ids": ids}))
            assert "error" in overlap and "already in progress" in overlap["error"]["message"], overlap
            assert ids == [snapshot[0]["id"]] and len(acquired) == 1
    finally:
        # The callback thread never starts. Recover only each captured socket
        # through its original bound close method after removing the seam.
        failures = []
        for httpd, actual_close in acquired:
            try:
                actual_close()
                refused(httpd.server_address[1])
            except BaseException as error:
                failures.append(repr(error))
        record_property("uncertain_callback_fixture_cleanup", json.dumps({"failures": failures}))
        assert not failures, failures
