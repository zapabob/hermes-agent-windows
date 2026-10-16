"""Actual SDK worker/listener settlement with independent owned cleanup."""
import json
import socket
import threading
from contextlib import contextmanager

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tests.fakes.mcp_oauth_issuer import serve_issuer
from tui_gateway import mcp_oauth_sessions as sessions
from tui_gateway import server


@contextmanager
def scoped(home):
    token = set_hermes_home_override(str(home))
    try:
        yield
    finally:
        reset_hermes_home_override(token)


def rpc(operation, *, profile="work", **params):
    method = "mcp.servers.oauth." + operation
    assert method in server._methods
    response = server._methods[method](97, {"name": "reports", "profile": profile, **params})
    assert "error" not in response, response
    return response["result"]


def refused(port):
    with pytest.raises(ConnectionRefusedError) as failure:
        socket.create_connection(("127.0.0.1", port), timeout=4)
    assert failure.value.errno == 111 or getattr(failure.value, "winerror", None) == 10061


def exited(thread):
    assert not thread.is_alive(), thread.name


@pytest.mark.parametrize("hold_cleanup", [False, True], ids=["actual-resource-exit", "done-after-listener-close"])
def test_actual_cancel_settles_worker_and_listener_before_done(tmp_path, monkeypatch, record_property, hold_cleanup):
    from hermes_cli.mcp_config import _replace_mcp_servers
    from tools import mcp_tool as core
    from tools.mcp_oauth_manager import reset_manager_for_tests

    root = tmp_path / "owned-resource-home"
    work = root / "profiles/work"
    for profile in ("work", "other"):
        (root / "profiles" / profile).mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(root))
    assert not sessions._sessions and not core._servers
    reset_manager_for_tests()
    before = set(threading.enumerate())
    resources = set()
    listeners = []
    loops = []
    thread_errors = []
    cleanup_entered = threading.Event()
    cleanup_release = threading.Event()
    original_shutdown = sessions._shutdown_listener
    original_constructor = sessions.http.server.HTTPServer
    original_hook = threading.excepthook
    observations = {}

    def captured_constructor(*args, **kwargs):
        actual = original_constructor(*args, **kwargs)
        listeners.append((actual, actual.server_address[1]))
        return actual

    def capture_exception(args):
        if args.thread not in before and args.thread.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"}:
            thread_errors.append({"thread": args.thread.name, "type": args.exc_type.__name__, "message": str(args.exc_value)})
        else:
            original_hook(args)

    def gated_shutdown(rec):
        cleanup_entered.set()
        if not cleanup_release.wait(8):
            raise AssertionError("Owned cleanup gate was not released")
        original_shutdown(rec)

    monkeypatch.setattr(sessions.http.server, "HTTPServer", captured_constructor)
    monkeypatch.setattr(threading, "excepthook", capture_exception)
    if hold_cleanup:
        monkeypatch.setattr(sessions, "_shutdown_listener", gated_shutdown)

    with serve_issuer() as owner:
        cfg = {"url": owner.mcp_url, "transport": "http", "auth": "oauth", "oauth": {"cimd": False}, "timeout": 5}
        try:
            for profile in ("work", "other"):
                with scoped(root / "profiles" / profile):
                    ok, issues = _replace_mcp_servers({"reports": cfg})
                    assert ok and not issues, issues
            started = rpc("start")
            assert started.get("ok") and started.get("auth_url"), started
            rec = sessions._sessions[started["session_id"]]
            resources.update(thread for thread in threading.enumerate() if thread not in before
                             and thread.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"})
            workers = [thread for thread in resources if thread.name == "mcp-oauth-reports"]
            callback_threads = [thread for thread in resources if thread.name == "mcp-oauth-cb-reports"]
            assert len(workers) == len(callback_threads) == len(listeners) == 1
            actual_server, port = listeners[0]
            assert rec["httpd"] is actual_server
            if core._mcp_loop is not None:
                loops.append((core._mcp_loop, core._mcp_thread))
            assert owner.operations("registration") and owner.operations("get")
            with socket.create_connection(("127.0.0.1", port), timeout=4):
                pass
            foreign = rpc("cancel", profile="other", session_id=started["session_id"])
            assert foreign["ok"] is False, foreign
            assert not rec["flow"]._callback_ready.is_set()
            assert all(thread.is_alive() for thread in resources)
            cancelled = rpc("cancel", session_id=started["session_id"])
            assert cancelled["cancelled"] is True, cancelled
            if hold_cleanup:
                assert cleanup_entered.wait(8), "Actual SDK worker did not reach cleanup"
                observations["held_cleanup"] = {
                    "worker_done": rec["flow"].worker_done,
                    "worker_alive": workers[0].is_alive(),
                    "listener_alive": callback_threads[0].is_alive(),
                    "socket_fileno": actual_server.socket.fileno(),
                }
                record_property("resource_held_before_assertion", json.dumps(observations["held_cleanup"]))
                assert observations["held_cleanup"]["worker_alive"] and observations["held_cleanup"]["listener_alive"]
                assert observations["held_cleanup"]["socket_fileno"] != -1
                with socket.create_connection(("127.0.0.1", port), timeout=4):
                    pass
                assert rec["flow"].worker_done is False
                cleanup_release.set()
            assert rec["flow"].wait_worker_done(12), rec["flow"].snapshot()
            for thread in resources:
                thread.join(timeout=3)
            observations["settled"] = {
                "worker_done": rec["flow"].worker_done,
                "threads": [{"name": thread.name, "alive": thread.is_alive()} for thread in resources],
                "socket_fileno": actual_server.socket.fileno(), "record_listener_absent": rec["httpd"] is None,
            }
            record_property("resource_settled_before_fixture", json.dumps(observations["settled"]))
            assert all(not thread.is_alive() for thread in resources)
            assert rec["httpd"] is None and actual_server.socket.fileno() == -1
            refused(port)
            assert owner.operations("token_request") == owner.operations("token_redemption") == owner.operations("sentinel") == []
            assert not (work / "mcp-tokens/reports.json").exists()
            assert not (root / "profiles/other/mcp-tokens/reports.json").exists()
            assert rpc("poll", session_id=started["session_id"])["status"] == "error"
            assert rec["flow"].snapshot()["error"] == "Cancelled by user"
            record_property("resource_issuer_ledger", json.dumps(owner.ledger))
        finally:
            failures = []

            def attempt(label, action):
                try:
                    action()
                except BaseException as error:
                    failures.append({"label": label, "type": type(error).__name__, "message": str(error)})

            owner.token_release.set()
            cleanup_release.set()
            resources.update(thread for thread in threading.enumerate() if thread not in before
                             and thread.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"})
            for rec in list(sessions._sessions.values()):
                if rec["hermes_home"] == str(work):
                    attempt("release_callback_wait", lambda rec=rec: rec["flow"].mark_error("Owned resource fixture cleanup"))
            for thread in resources:
                if thread.name == "mcp-oauth-reports":
                    attempt("worker_join", lambda thread=thread: thread.join(timeout=12))
                    attempt("worker_exited", lambda thread=thread: exited(thread))
            # Constructor-retained server objects remain available even when
            # a mutant drops rec.httpd or skips the product shutdown routine.
            for actual_server, port in listeners:
                live_callback = [thread for thread in resources if thread.name == "mcp-oauth-cb-reports" and thread.is_alive()]
                if live_callback:
                    attempt("independent_stdlib_shutdown", actual_server.shutdown)
                attempt("independent_socket_close", actual_server.server_close)
                attempt("independent_port_refused", lambda port=port: refused(port))
            for thread in resources:
                attempt("gateway_join", lambda thread=thread: thread.join(timeout=4))
                attempt("gateway_exited", lambda thread=thread: exited(thread))
            if core._mcp_loop is not None and (core._mcp_loop, core._mcp_thread) not in loops:
                loops.append((core._mcp_loop, core._mcp_thread))
            attempt("core_shutdown", core.shutdown_mcp_servers)
            for loop, thread in loops:
                attempt("core_thread_join", lambda thread=thread: thread.join(timeout=4))
                attempt("core_thread_exited", lambda thread=thread: exited(thread))
                attempt("core_loop_closed", lambda loop=loop: assert_closed(loop))
            sessions._sessions.clear()
            reset_manager_for_tests()
            record_property("actual_resource_cleanup", json.dumps({"failures": failures, "thread_errors": thread_errors, "observations": observations}))
            assert failures == [] and thread_errors == [], (failures, thread_errors)


def assert_closed(loop):
    assert loop.is_closed() and not loop.is_running()
