"""Keep real acquired-worker cleanup honest under uncertain callback ownership."""
import asyncio
import inspect
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from tests.fakes.mcp_oauth_gateway import homes, refused, scoped
from tools.mcp_dashboard_oauth import DashboardOAuthFlow, get_dashboard_oauth_flow
from tui_gateway import mcp_oauth_sessions as sessions, server


@pytest.mark.parametrize("mode", ["close_cause", "event_before_exit", "changed_identity", "withheld_completion"])
def test_normal_cleanup_requires_truthful_owned_completion(homes, monkeypatch, record_property, mode):
    from hermes_cli import mcp_config

    entered, hook_release, probe_release, pending, wrapper_entered, wrapper_release = (
        threading.Event() for _ in range(6)
    )
    actual_thread, actual_server = threading.Thread, sessions.http.server.HTTPServer
    original_shutdown = sessions._ListenerOwner.shutdown
    threads, servers, errors, barrier_errors, cleanup_errors, frames = [], [], [], [], [], []
    close_attempts, observations = [], {}
    rec = flow = owner = changed_flow = original_close = None
    sid = None
    cause = "Owned OAuth negative cleanup probe complete"

    def rpc(operation):
        return server._methods[f"mcp.servers.oauth.{operation}"](
            23, {"name": "reports", "profile": "work"}
        )

    with scoped(homes / "profiles" / "work"):
        ok, issues = mcp_config._replace_mcp_servers({"reports": {
            "url": "http://127.0.0.1:1/mcp", "transport": "http", "auth": "oauth",
        }})
        assert ok and not issues, issues

    def held_probe(name, config, **kwargs):
        bridge = get_dashboard_oauth_flow()
        assert bridge is not None and name == "reports"
        asyncio.run(bridge.publish_authorization_url(
            "http://127.0.0.1:1/authorize?state=owned-negative-" + mode
        ))
        if not probe_release.wait(30):
            barrier_errors.append("Owned probe hold exceeded bound")
        raise RuntimeError(cause)

    def observed_server(*args, **kwargs):
        httpd = actual_server(*args, **kwargs)
        servers.append(httpd)
        def service_actions():
            frame = inspect.currentframe().f_back
            while frame is not None and frame.f_code.co_name != "serve_forever":
                frame = frame.f_back
            frames.append({"function": frame.f_code.co_name if frame else None,
                "source": frame.f_code.co_filename if frame else None,
                "native_id": threading.get_native_id()})
            del frame
            entered.set()
            if not hook_release.wait(30):
                barrier_errors.append("Actual callback service hold exceeded bound")
        httpd.service_actions = service_actions
        return httpd

    def observed_thread(*args, **kwargs):
        target, name = kwargs["target"], kwargs["name"]
        assert name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"}
        def invoke(*args, **kwargs):
            try:
                value = target(*args, **kwargs)
                if mode == "event_before_exit" and name == "mcp-oauth-cb-reports":
                    wrapper_entered.set()
                    if not wrapper_release.wait(30):
                        barrier_errors.append("Actual native callback exit hold exceeded bound")
                return value
            except BaseException as exc:
                errors.append({"thread": name, "type": type(exc).__name__,
                    "message": str(exc), "cause_type": type(exc.__cause__).__name__ if exc.__cause__ else None,
                    "cause": str(exc.__cause__) if exc.__cause__ else None})
                raise
        thread = actual_thread(*args, **{**kwargs, "target": invoke})
        threads.append(thread)
        return thread

    def observed_shutdown(current_owner):
        try:
            return original_shutdown(current_owner)
        except sessions._ListenerCleanupPending:
            if servers and current_owner.httpd is servers[0]:
                pending.set()
            raise

    def worker_stack(worker):
        frame = sys._current_frames().get(worker.ident)
        result = []
        try:
            while frame is not None:
                result.append({"function": frame.f_code.co_name,
                    "file": frame.f_code.co_filename, "line": frame.f_lineno,
                    "owned_event_wait": frame.f_code.co_name == "wait"
                        and frame.f_locals.get("self") is owner.completed,
                    "owned_callback_join": frame.f_code.co_name == "join"
                        and frame.f_locals.get("self") is owner.listener})
                frame = frame.f_back
        finally:
            del frame
        return result

    def await_worker_phase(worker, phase):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            stack = worker_stack(worker)
            if any(row["function"] == "_worker" and row["file"] == sessions.__file__
                   for row in stack) and any(row[phase] for row in stack):
                return stack
            time.sleep(0.01)
        raise AssertionError(("Worker did not reach owned wait/join", phase, worker_stack(worker)))

    def snapshot(worker, listener):
        return {"mode": mode, "worker_alive": worker.is_alive(), "callback_alive": listener.is_alive(),
            "worker_done": flow.worker_done, "event_set": owner.completed.is_set(),
            "record_retained": rec.get("httpd") is servers[0],
            "registry_identity": sessions._sessions.get(sid) is rec,
            "flow_identity": rec.get("flow") is flow, "original_error": flow.error,
            "native_ids": [thread.native_id for thread in threads], "errors": list(errors),
            "close_attempts": list(close_attempts), "socket_fd": servers[0].socket.fileno()}

    try:
        with monkeypatch.context() as local:
            local.setattr(mcp_config, "_probe_single_server", held_probe)
            local.setattr(sessions, "threading", SimpleNamespace(Thread=observed_thread))
            local.setattr(sessions, "http", SimpleNamespace(server=SimpleNamespace(
                HTTPServer=observed_server, BaseHTTPRequestHandler=sessions.http.server.BaseHTTPRequestHandler)))
            local.setattr(sessions._ListenerOwner, "shutdown", observed_shutdown)
            response = rpc("start")
            assert "error" not in response, response
            sid = response["result"]["session_id"]
            rec = sessions._sessions[sid]
            flow, owner = rec["flow"], servers[0]._hermes_oauth_listener_owner
            worker = next(thread for thread in threads if thread.name == "mcp-oauth-reports")
            listener = next(thread for thread in threads if thread.name == "mcp-oauth-cb-reports")
            assert len(threads) == 2 and len(servers) == 1 and entered.wait(5)
            assert len(frames) == 1 and frames[0]["function"] == "serve_forever"
            assert frames[0]["source"].endswith("socketserver.py")
            assert frames[0]["native_id"] == listener.native_id
            assert owner.rec is rec and owner.flow is flow and owner.listener is listener
            if mode == "close_cause":
                original_close = servers[0].server_close
                def failing_close():
                    close_attempts.append(threading.get_native_id())
                    raise OSError("Owned deterministic callback close fault")
                local.setattr(servers[0], "server_close", failing_close)
                owner.request_stop()
                hook_release.set()
                listener.join(timeout=6)
                assert not listener.is_alive() and owner.target_completed and not owner.completed.is_set()
            probe_release.set()
            assert pending.wait(8), "Actual cleanup must produce typed pending"
            if mode == "close_cause":
                worker.join(timeout=6)
                observations["after"] = snapshot(worker, listener)
                record_property("actual_negative_cleanup_observation", json.dumps(observations))
                assert not worker.is_alive() and not flow.worker_done
                assert rec["httpd"] is servers[0] and not owner.completed.is_set()
                assert len(close_attempts) == 2 and len(errors) == 1
                assert errors[0]["type"] == "_ListenerCleanupPending" and errors[0]["cause_type"] == "OSError"
                assert errors[0]["cause"] == "Owned deterministic callback close fault"
            else:
                observations["waiting_stack"] = await_worker_phase(worker, "owned_event_wait")
                observations["before"] = snapshot(worker, listener)
                assert worker.is_alive() and listener.is_alive() and not flow.worker_done
                assert not owner.completed.is_set() and rec["httpd"] is servers[0]
                if mode == "event_before_exit":
                    hook_release.set()
                    assert wrapper_entered.wait(6) and owner.completed.is_set()
                    observations["join_stack"] = await_worker_phase(worker, "owned_callback_join")
                    observations["event_before_native_exit"] = snapshot(worker, listener)
                    assert any(row["function"] == "join" for row in observations["join_stack"])
                    assert listener.is_alive() and worker.is_alive() and not flow.worker_done
                    assert rec["httpd"] is servers[0] and servers[0].socket.fileno() == -1
                    wrapper_release.set()
                elif mode == "changed_identity":
                    changed_flow = DashboardOAuthFlow(flow_id=flow.flow_id, server_name="reports",
                        profile="work", hermes_home=flow.hermes_home, redirect_uri=flow.redirect_uri)
                    with sessions._sessions_lock:
                        assert sessions._sessions.get(sid) is rec and rec["flow"] is flow
                        rec["flow"] = changed_flow
                    hook_release.set()
                else:
                    time.sleep(0.2)
                    observations["withheld"] = snapshot(worker, listener)
                    duplicate = rpc("start")
                    observations["duplicate"] = duplicate
                    assert "already in progress" in duplicate["error"]["message"]
                    assert worker.is_alive() and listener.is_alive() and not flow.worker_done
                    assert not owner.completed.is_set() and rec["httpd"] is servers[0]
                    hook_release.set()
                listener.join(timeout=6)
                worker.join(timeout=8)
                observations["after"] = snapshot(worker, listener)
                record_property("actual_negative_cleanup_observation", json.dumps(observations))
                assert not listener.is_alive() and not worker.is_alive() and owner.completed.is_set()
                if mode == "changed_identity":
                    assert rec["httpd"] is servers[0] and rec["flow"] is changed_flow
                    assert not flow.worker_done and not changed_flow.worker_done
                    assert len(errors) == 1 and errors[0]["type"] == "_ListenerCleanupPending"
                    assert errors[0]["cause_type"] is None
                else:
                    assert flow.worker_done and rec["httpd"] is None and errors == []
                refused(servers[0].server_address[1])
            assert flow.error == cause and barrier_errors == []
    finally:
        primary = sys.exception()
        hook_release.set()
        probe_release.set()
        wrapper_release.set()
        def attempt(label, action):
            try:
                return action()
            except BaseException as exc:
                cleanup_errors.append(label + ": " + repr(exc))
        if original_close is not None:
            attempt("restore_owned_close", lambda: setattr(servers[0], "server_close", original_close))
        if changed_flow is not None:
            def restore_owned_flow():
                with sessions._sessions_lock:
                    assert sessions._sessions.get(sid) is rec
                    assert rec["flow"] is changed_flow and rec["httpd"] is servers[0]
                    rec["flow"] = flow
            attempt("restore_owned_flow", restore_owned_flow)
        if owner is not None:
            attempt("release_owned_completion", owner.request_stop)
        def joined(thread):
            thread.join(timeout=10)
            assert not thread.is_alive(), thread.name
        for index, thread in enumerate(threads):
            attempt("actual_thread_join_" + str(index), lambda thread=thread: joined(thread))
        if rec is not None:
            attempt("owned_fixture_shutdown", lambda: sessions._shutdown_listener(rec))
        for index, httpd in enumerate(servers):
            attempt("actual_socket_close_" + str(index), httpd.server_close)
            attempt("actual_socket_refusal_" + str(index), lambda httpd=httpd: refused(httpd.server_address[1]))
        payload = attempt("cleanup_serialization", lambda: json.dumps({
            "mode": mode, "failures": cleanup_errors, "barrier_errors": barrier_errors,
            "errors": errors, "threads": len(threads), "native_ids": [thread.native_id for thread in threads],
            "fixture_cleanup_is_product_proof": False,
        }))
        if payload is not None:
            attempt("cleanup_property", lambda: record_property("actual_negative_cleanup_fixture", payload))
        if cleanup_errors or barrier_errors:
            if primary is not None:
                primary.add_note("Owned negative cleanup failures: " + repr(cleanup_errors + barrier_errors))
            else:
                raise AssertionError(cleanup_errors + barrier_errors)
