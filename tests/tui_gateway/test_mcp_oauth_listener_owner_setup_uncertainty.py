"""Preserve primary setup cause and acquired socket when closure is uncertain."""
import json
import socket
import sys
import threading
from types import SimpleNamespace

from tests.fakes.mcp_oauth_admission import admission as admission
from tests.fakes.mcp_oauth_gateway import homes as homes, refused


def test_owner_setup_and_close_failure_retains_socket_and_primary_cause(admission, monkeypatch, record_property):
    rpc, release, callers, sessions, ledger, guard, auth_release, auth_held = admission
    servers, original_closes, close_calls, constructors, startup_errors, cleanup_failures = [], [], [], [], [], []
    actual_server, actual_thread = sessions.http.server.HTTPServer, threading.Thread
    actual_startup_error = sessions.McpOAuthStartupError
    primary = RuntimeError("Owned private listener owner setup failure")
    secondary = OSError("Owned acquired listener socket close uncertainty")

    def observed_server(*args, **kwargs):
        server = actual_server(*args, **kwargs)
        servers.append(server)
        original_closes.append(server.server_close)
        def failed_close():
            close_calls.append(server.server_address[1])
            raise secondary
        server.server_close = failed_close
        return server

    def observed_thread(*args, **kwargs):
        if kwargs.get("name") == "mcp-oauth-cb-reports":
            constructors.append(kwargs["name"])
        return actual_thread(*args, **kwargs)

    def failed_event(*args, **kwargs):
        raise primary

    class ObservedStartupError(actual_startup_error):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            startup_errors.append(self)

    try:
        with monkeypatch.context() as local:
            local.setattr(sessions, "Event", failed_event)
            local.setattr(sessions, "threading", SimpleNamespace(Thread=observed_thread))
            local.setattr(sessions, "McpOAuthStartupError", ObservedStartupError)
            local.setattr(sessions, "http", SimpleNamespace(server=SimpleNamespace(
                HTTPServer=observed_server,
                BaseHTTPRequestHandler=sessions.http.server.BaseHTTPRequestHandler)))
            response = rpc("start")
        assert response["error"]["code"] == 5024
        assert response["error"]["message"] == str(primary)
        assert len(servers) == len(startup_errors) == 1 and constructors == []
        wrapper = startup_errors[0].__cause__
        assert isinstance(wrapper, sessions._ListenerSetupCleanupError)
        assert wrapper.__cause__ is primary and str(wrapper) == str(primary)
        assert wrapper.httpd is servers[0] and not wrapper.started
        assert any(repr(secondary) in note for note in wrapper.__notes__)
        sid = response["error"]["data"]["session_id"]
        rec = sessions._sessions[sid]
        assert rec["httpd"] is servers[0] and not rec["flow"].worker_done
        assert not rec["listener_started"] and len(close_calls) == 2
        with socket.create_connection(("127.0.0.1", servers[0].server_address[1]), timeout=2):
            actual_port = "accepted"
        assert rpc("poll", session_id=sid)["result"]["error_message"] == str(primary)
        foreign = rpc("poll", profile="other", session_id=sid)["result"]
        assert foreign["status"] == "error" and "session_id" not in foreign
        duplicate = rpc("start")
        assert "already in progress" in duplicate["error"]["message"]
        assert list(sessions._sessions) == [sid]
        record_property("actual_owner_setup_close_uncertainty", json.dumps({
            "response": response, "duplicate": duplicate, "port_before_fixture_close": actual_port,
            "actual_servers": len(servers), "close_attempts": len(close_calls),
            "callback_constructor_calls": constructors, "callback_native_start_attempted": False,
            "primary_explicit_cause_retained": wrapper.__cause__ is primary,
            "secondary_closure_note_retained": any(repr(secondary) in note for note in wrapper.__notes__),
            "reservation_retained": rec["httpd"] is servers[0], "worker_done": rec["flow"].worker_done,
        }))
    finally:
        body_error = sys.exception()
        def attempt(label, action):
            try:
                action()
            except BaseException as error:
                cleanup_failures.append(label + ": " + repr(error))
        for index, (server, close) in enumerate(zip(servers, original_closes, strict=True)):
            server.server_close = close
            attempt("actual_close_" + str(index), close)
            attempt("actual_refusal_" + str(index), lambda server=server: refused(server.server_address[1]))
        attempt("cleanup_property", lambda: record_property("actual_owner_setup_close_uncertainty_cleanup", json.dumps({
            "failures": cleanup_failures, "actual_servers": len(servers),
            "callback_constructor_calls": constructors, "fixture_close_is_product_cleanup": False,
        })))
        if cleanup_failures:
            if body_error is not None:
                body_error.add_note("Owner setup close uncertainty fixture cleanup failed: " + repr(cleanup_failures))
            else:
                raise AssertionError(cleanup_failures)
