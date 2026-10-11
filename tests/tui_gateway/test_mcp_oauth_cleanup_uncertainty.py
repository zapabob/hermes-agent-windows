"""Keep ownership when an acquired callback socket cannot confirm cleanup."""
import json
import socket
import sys
import threading

from tests.fakes.mcp_oauth_admission import admission as admission
from tests.fakes.mcp_oauth_gateway import homes as homes, refused


def test_unconfirmed_callback_startup_cleanup_keeps_admission(admission, monkeypatch, record_property):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    acquired = []
    close_attempts = []
    acquired_threads, thread_errors = [], []
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
                    acquired_threads.append(thread)
                    actual_run = thread.run
                    def observed_run():
                        try:
                            return actual_run()
                        except BaseException as error:
                            thread_errors.append(repr(error))
                            raise
                    thread.run = observed_run
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
        primary = sys.exception()
        failures = []
        def attempt(label, action):
            try:
                action()
            except BaseException as error:
                failures.append(label + ": " + repr(error))
        def join(listener):
            listener.join(timeout=6)
            assert not listener.is_alive()
        # Only this fixture knows its injected start skipped native allocation.
        # Close the captured sockets independently, then start/join those same
        # real callback Threads to let their stopped product targets settle.
        for index, (httpd, actual_close) in enumerate(acquired):
            attempt("actual_close_" + str(index), actual_close)
            attempt("actual_refusal_" + str(index), lambda httpd=httpd: refused(httpd.server_address[1]))
        for index, listener in enumerate(acquired_threads):
            attempt("actual_native_start_" + str(index), lambda listener=listener: actual_thread_start(listener))
            if listener._started.wait(2):
                attempt("actual_native_join_" + str(index), lambda listener=listener: join(listener))
            else:
                failures.append("actual_native_start_unconfirmed_" + str(index))
        attempt("cleanup_property", lambda: record_property("uncertain_callback_fixture_cleanup", json.dumps({
            "failures": failures, "thread_errors": thread_errors,
            "same_actual_callback_threads": len(acquired_threads),
            "actual_native_ids": [listener.native_id for listener in acquired_threads],
            "fixture_native_start_is_product_absence_proof": False,
        })))
        if failures or thread_errors:
            if primary is not None:
                primary.add_note("Uncertain callback fixture cleanup failed: " + repr(failures + thread_errors))
            else:
                raise AssertionError(failures + thread_errors)
