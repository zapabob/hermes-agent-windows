"""Actual callback native startup failures retain their acquired owners."""
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from tests.fakes.mcp_oauth_admission import admission as admission
from tests.fakes.mcp_oauth_gateway import homes as homes, refused


class InvalidListenerExperiment(RuntimeError):
    """A barrier failed before the deliberately injected startup exception."""


class ListenerCapture:
    def __init__(self, sessions, mode):
        self.sessions, self.mode = sessions, mode
        self.cause = "Owned callback listener startup failure: " + mode
        self.native_acquired = threading.Event()
        self.fault_raised = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()
        self.patch = pytest.MonkeyPatch()
        self.rows, self.servers, self.thread_errors = [], [], []
        self.barrier_errors = []
        self.response = None
        self.caller_error = None
        original_thread = threading.Thread
        original_server = sessions.http.server.HTTPServer

        def observed_server(*args, **kwargs):
            result = original_server(*args, **kwargs)
            self.servers.append(result)
            return result

        def factory(*args, **kwargs):
            if kwargs.get("name") != "mcp-oauth-cb-reports" or self.rows:
                return original_thread(*args, **kwargs)
            original_target = kwargs["target"]
            row = {"native_acquired": False, "intended_error_raised": False,
                "original_start_invoked": False}
            self.rows.append(row)

            def observed_target(*target_args, **target_kwargs):
                if mode == "target_held":
                    row.update(native_acquired=True, native_id=threading.get_native_id(),
                        native_ident=threading.get_ident(), object_id=id(row["thread"]))
                    self.native_acquired.set()
                    if not self.release.wait(15):
                        self.barrier_errors.append("Target barrier was not released")
                try:
                    original_target(*target_args, **target_kwargs)
                except BaseException as error:
                    # The original closes the socket before the acquired pre-ident
                    # thread runs. Retain its actual secondary error as evidence.
                    self.thread_errors.append({"type": type(error).__name__, "message": str(error)})

            kwargs["target"] = observed_target
            listener = original_thread(*args, **kwargs)
            row["thread"] = listener
            native_start = listener.start
            native_bootstrap = listener._bootstrap_inner

            if mode == "bootstrap_held":
                def held_bootstrap():
                    row.update(native_acquired=True, native_id=threading.get_native_id(),
                        native_ident=threading.get_ident(), object_id=id(listener))
                    self.native_acquired.set()
                    try:
                        if not self.release.wait(15):
                            self.barrier_errors.append("Bootstrap barrier was not released")
                    finally:
                        native_bootstrap()

                def failed_started_wait(*args, **kwargs):
                    if not self.native_acquired.wait(5):
                        self.barrier_errors.append("Native allocation was not observed")
                        raise InvalidListenerExperiment("Native allocation was not observed")
                    row["intended_error_raised"] = True
                    self.fault_raised.set()
                    raise RuntimeError(self.cause)

                self.patch.setattr(listener, "_bootstrap_inner", held_bootstrap)
                self.patch.setattr(listener._started, "wait", failed_started_wait)

            def failing_start():
                row["original_start_invoked"] = True
                native_start()
                if mode == "target_held":
                    if not self.native_acquired.wait(5):
                        self.barrier_errors.append("Actual target entry was not observed")
                        raise InvalidListenerExperiment("Actual target entry was not observed")
                    row.update(native_acquired=True, native_id=listener.native_id,
                        native_ident=listener.ident, object_id=id(listener))
                    row["intended_error_raised"] = True
                    self.fault_raised.set()
                    raise RuntimeError(self.cause)

            self.patch.setattr(listener, "start", failing_start)
            return listener

        self.patch.setattr(sessions, "threading", SimpleNamespace(Thread=factory,
            Event=threading.Event, Lock=threading.Lock, RLock=threading.RLock,
            current_thread=threading.current_thread))
        self.patch.setattr(sessions, "http", SimpleNamespace(server=SimpleNamespace(
            HTTPServer=observed_server, BaseHTTPRequestHandler=sessions.http.server.BaseHTTPRequestHandler)))

    def invoke(self, rpc, callers):
        def call():
            try:
                self.response = rpc("start")
            except BaseException as error:
                self.caller_error = repr(error)
            finally:
                self.returned.set()

        self.caller = threading.Thread(target=call, name="owned-listener-start-rpc", daemon=True)
        callers.append(self.caller)
        self.caller.start()

    def finish(self, record_property):
        primary = sys.exception()
        errors = list(self.barrier_errors)
        shutdown_rows = []

        def attempt(label, action):
            try:
                return action()
            except BaseException as error:
                errors.append(label + ": " + repr(error))
                return None

        def joined(thread, timeout):
            thread.join(timeout=timeout)
            assert not thread.is_alive(), thread.name

        def shutdown(server):
            row = {"object_id": None, "start_invoked": False, "native_id": None,
                "ident": None, "started_event": False, "joined": False, "errors": []}
            shutdown_rows.append(row)

            def stop():
                try:
                    server.shutdown()
                except BaseException as error:
                    row["errors"].append(repr(error))

            closing = threading.Thread(target=stop, name="owned-listener-fixture-shutdown", daemon=True)
            row["object_id"] = id(closing)
            row["start_invoked"] = True
            try:
                closing.start()
            finally:
                # A start exception is uncertain, so retain the actual thread
                # and still try its native-start confirmation and bounded join.
                row["started_event"] = closing._started.wait(6)
                row["native_id"], row["ident"] = closing.native_id, closing.ident
                if row["started_event"]:
                    try:
                        joined(closing, 6)
                        row["joined"] = True
                    except BaseException as error:
                        row["errors"].append(repr(error))
                else:
                    row["errors"].append("Fixture shutdown native start unconfirmed")
            assert row["joined"] and not row["errors"], row

        attempt("all_barriers_release", self.release.set)
        attempt("fault_seams_restore", self.patch.undo)
        caller = getattr(self, "caller", None)
        if caller is not None:
            attempt("public_caller_join", lambda: joined(caller, 6))
        for row in self.rows:
            listener = row["thread"]
            if not attempt("native_start_confirmation", lambda: listener._started.wait(6)):
                errors.append("Captured native listener did not bootstrap")
            # The target was released before waiting or shutting the actual
            # server down. This teardown does not count as product cleanup.
            attempt("initial_listener_wait", lambda: listener.join(timeout=1))
            for server in self.servers:
                if attempt("listener_liveness", listener.is_alive):
                    attempt("bounded_fixture_shutdown", lambda server=server: shutdown(server))
                attempt("actual_socket_close", server.server_close)
            attempt("actual_listener_join", lambda listener=listener: joined(listener, 6))
        for server in self.servers:
            attempt("actual_port_refusal", lambda server=server: refused(server.server_address[1]))
        listener_exited = all(attempt("final_listener_liveness", row["thread"].is_alive) is False for row in self.rows)
        caller_exited = caller is None or attempt("final_caller_liveness", caller.is_alive) is False
        shutdown_exited = all(row["joined"] and row["started_event"] and row["native_id"] is not None
            and row["ident"] is not None and not row["errors"] for row in shutdown_rows)
        attempt("cleanup_property", lambda: record_property("actual_listener_startup_cleanup", json.dumps({
            "failures": errors, "thread_errors": self.thread_errors,
            "caller_error": self.caller_error, "actual_native_threads": len(self.rows),
            "actual_servers": len(self.servers), "fixture_release_is_product_cleanup": False,
            "shutdown_helpers": shutdown_rows, "actual_shutdown_helpers": len(shutdown_rows),
            "all_native_threads_exited": listener_exited and caller_exited and shutdown_exited,
        })))
        if errors:
            if primary is not None:
                primary.add_note("Listener fixture cleanup failed: " + repr(errors))
            else:
                raise AssertionError(errors)


@pytest.mark.parametrize("mode", ["bootstrap_held", "target_held"])
def test_acquired_listener_failure_returns_identity_and_retains_native_owner(
    admission, mode, record_property,
):
    rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held = admission
    capture = ListenerCapture(sessions, mode)
    try:
        capture.invoke(rpc, callers)
        assert capture.native_acquired.wait(5), "Actual native allocation was not observed"
        if not capture.fault_raised.wait(5) or capture.barrier_errors:
            raise InvalidListenerExperiment("Intended startup fault was not reached cleanly")
        assert len(capture.rows) == len(capture.servers) == 1
        row = capture.rows[0]
        listener = row["thread"]
        if mode == "bootstrap_held":
            assert listener.ident is None and not listener._started.is_set()
        else:
            assert listener.ident is not None and listener._started.is_set()
        record_property("actual_listener_native_barrier", json.dumps({
            "mode": mode, "native_id": row["native_id"], "native_ident": row["native_ident"],
            "object_id": row["object_id"], "object_ident": listener.ident,
            "started_event": listener._started.is_set(), "release_is_set": capture.release.is_set(),
            "original_start_invoked": row["original_start_invoked"],
            "intended_error_raised": row["intended_error_raised"],
            "fault_event": capture.fault_raised.is_set(), "cause": capture.cause,
            "barrier_errors": list(capture.barrier_errors),
        }))
        # A response deadline is an asserted public contract. The command's
        # external timeout and any failed experimental barrier are excluded REDs.
        assert capture.returned.wait(1), "Startup failure must return before the held HTTP loop is released"
        assert capture.caller_error is None
        result = capture.response
        assert result["error"]["code"] == 5024
        data = result["error"]["data"]
        assert data["server_name"] == "reports" and data["session_id"]
        sid = data["session_id"]
        rec = sessions._sessions[sid]
        observation = {"mode": mode, "intended_error_raised": row["intended_error_raised"],
            "native_id": row["native_id"], "native_ident": row["native_ident"],
            "object_id": row["object_id"], "object_ident": listener.ident,
            "started_event": listener._started.is_set(), "worker_done": rec["flow"].worker_done,
            "listener_record_retained": rec.get("httpd") is capture.servers[0]}
        record_property("actual_listener_startup_observation", json.dumps(observation))
        assert row["intended_error_raised"] and row["original_start_invoked"]
        poll = rpc("poll", session_id=sid)["result"]
        assert poll["status"] == "error" and capture.cause in poll["error_message"]
        assert not poll.get("auth_url")
        foreign = rpc("poll", profile="other", session_id=sid)["result"]
        assert foreign["status"] == "error" and "session_id" not in foreign and not foreign.get("auth_url")
        assert not rec["flow"].worker_done, "A still-held acquired native listener must retain the reservation"
        assert rec.get("httpd") is capture.servers[0], "Actual listener ownership must survive the startup error"
        assert "already in progress" in rpc("start")["error"]["message"]
        assert len(capture.rows) == 1
        capture.release.set()
        capture.patch.undo()
        assert listener._started.wait(6)
        listener.join(timeout=6)
        assert not listener.is_alive()
        assert rec["flow"]._worker_done.wait(6), "Native listener exit must settle the reserved slot"
        assert rec["httpd"] is None
        assert not capture.thread_errors, capture.thread_errors
        refused(capture.servers[0].server_address[1])
    finally:
        capture.finish(record_property)
