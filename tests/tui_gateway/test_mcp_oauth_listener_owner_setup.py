"""Private callback owner setup failure closes the acquired actual socket."""
import errno
import json
import socket
import sys
import threading
from types import SimpleNamespace

from tests.fakes.mcp_oauth_admission import admission as admission
from tests.fakes.mcp_oauth_gateway import homes as homes, refused


def test_owner_state_constructor_failure_closes_actual_socket(admission, monkeypatch, record_property):
    rpc, release, callers, sessions, ledger, guard, auth_release, auth_held = admission
    acquired, event_calls, cleanup_failures = [], [], []
    actual_server = sessions.http.server.HTTPServer
    actual_thread = threading.Thread
    callback_constructor_calls = []
    cause = "Owned callback state constructor failure"

    def observed_server(*args, **kwargs):
        server = actual_server(*args, **kwargs)
        acquired.append(server)
        return server

    def observed_thread(*args, **kwargs):
        if kwargs.get('name') == 'mcp-oauth-cb-reports':
            callback_constructor_calls.append(kwargs['name'])
        return actual_thread(*args, **kwargs)

    def failed_event(*args, **kwargs):
        event_calls.append("owner_Event_construction")
        raise RuntimeError(cause)

    try:
        with monkeypatch.context() as local:
            local.setattr(sessions, "Event", failed_event)
            local.setattr(sessions, "threading", SimpleNamespace(Thread=observed_thread))
            local.setattr(sessions, "http", SimpleNamespace(server=SimpleNamespace(
                HTTPServer=observed_server,
                BaseHTTPRequestHandler=sessions.http.server.BaseHTTPRequestHandler)))
            response = rpc("start")
        assert response["error"]["code"] == 5024 and response["error"]["message"] == cause
        sid = response["error"]["data"]["session_id"]
        rec = sessions._sessions[sid]
        assert len(acquired) == len(event_calls) == 1
        assert callback_constructor_calls == []
        port = acquired[0].server_address[1]
        refusal_errno, refusal_winerror = None, None
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=4):
                port_result = "accepted"
        except ConnectionRefusedError as refusal:
            refusal_errno, refusal_winerror = refusal.errno, getattr(refusal, "winerror", None)
            assert refusal_errno == errno.ECONNREFUSED or refusal_winerror == 10061
            port_result = "refused"
        record_property("actual_owner_setup_failure", json.dumps({
            "response": response, "actual_servers": len(acquired), "event_calls": event_calls,
            "port_before_fixture_close": port_result, "refusal_errno": refusal_errno, "refusal_winerror": refusal_winerror,
            "worker_done": rec["flow"].worker_done,
            "listener_record_retained": rec.get("httpd") is acquired[0],
            "callback_native_start_attempted": False, "callback_constructor_calls": callback_constructor_calls,
        }))
        assert port_result == "refused", "Owner setup failure left the acquired callback socket open"
        assert rec["flow"].worker_done and rec.get("httpd") is None
        assert rpc("poll", session_id=sid)["result"]["error_message"] == cause
        foreign = rpc("poll", profile="other", session_id=sid)["result"]
        assert foreign["status"] == "error" and "session_id" not in foreign
    finally:
        primary = sys.exception()
        def attempt(label, action):
            try:
                action()
            except BaseException as error:
                cleanup_failures.append(label + ": " + repr(error))
        for index, server in enumerate(acquired):
            attempt("actual_close_" + str(index), server.server_close)
            attempt("actual_refusal_" + str(index), lambda server=server: refused(server.server_address[1]))
        attempt("cleanup_property", lambda: record_property("actual_owner_setup_fixture_cleanup", json.dumps({
            "failures": cleanup_failures, "actual_servers": len(acquired),
            "callback_native_start_attempted": False, "callback_constructor_calls": callback_constructor_calls,
            "fixture_closure_is_product_cleanup": False,
        })))
        if cleanup_failures:
            if primary is not None:
                primary.add_note("Owner setup fixture cleanup failed: " + repr(cleanup_failures))
            else:
                raise AssertionError(cleanup_failures)
