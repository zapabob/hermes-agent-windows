"""Observe late actual callback exit through the acquired OAuth worker."""
import asyncio
import inspect
import json
import sys
import threading
from types import SimpleNamespace

from tests.fakes.mcp_oauth_gateway import homes, refused, scoped
from tui_gateway import mcp_oauth_sessions as sessions, server
from tools.mcp_dashboard_oauth import get_dashboard_oauth_flow


def test_normal_cleanup_pending_then_actual_late_exit_settles_owner(
    homes, monkeypatch, record_property,
):
    from hermes_cli import mcp_config

    cause = "Owned OAuth cleanup probe complete"
    entered, hook_release, pending = (threading.Event() for _ in range(3))
    probe_releases = [threading.Event(), threading.Event()]
    actual_thread = threading.Thread
    actual_server = sessions.http.server.HTTPServer
    original_shutdown = sessions._ListenerOwner.shutdown
    threads, servers, frames, probe_calls, thread_errors = [], [], [], [], []
    barrier_errors, cleanup_errors = [], []
    outcomes = {}

    def rpc(operation, **params):
        return server._methods[f"mcp.servers.oauth.{operation}"](
            19, {"name": "reports", "profile": "work", **params}
        )

    cfg = {"url": "http://127.0.0.1:1/mcp", "transport": "http", "auth": "oauth"}
    with scoped(homes / "profiles" / "work"):
        ok, issues = mcp_config._replace_mcp_servers({"reports": cfg})
        assert ok and not issues, issues

    def observed_probe(name, config, **kwargs):
        flow = get_dashboard_oauth_flow()
        assert flow is not None and name == "reports"
        index = len(probe_calls)
        assert index < len(probe_releases)
        probe_calls.append({"flow_id": flow.flow_id,
            "native_id": threading.get_native_id(), "index": index})
        asyncio.run(flow.publish_authorization_url(
            "http://127.0.0.1:1/authorize?state=owned-late-cleanup-" + str(index)
        ))
        if not probe_releases[index].wait(30):
            barrier_errors.append("Owned probe was not released")
        raise RuntimeError(cause)

    def observed_server(*args, **kwargs):
        httpd = actual_server(*args, **kwargs)
        servers.append(httpd)
        if len(servers) == 1:
            def held_service_actions():
                frame = inspect.currentframe().f_back
                while frame is not None and frame.f_code.co_name != "serve_forever":
                    frame = frame.f_back
                frames.append({"function": frame.f_code.co_name if frame else None,
                    "source": frame.f_code.co_filename if frame else None,
                    "native_id": threading.get_native_id()})
                del frame
                entered.set()
                if not hook_release.wait(30):
                    barrier_errors.append("Actual stdlib service hook was not released")
            httpd.service_actions = held_service_actions
        return httpd

    def observed_thread(*args, **kwargs):
        target = kwargs["target"]
        name = kwargs.get("name")
        assert name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"}
        def observed_target(*target_args, **target_kwargs):
            try:
                return target(*target_args, **target_kwargs)
            except BaseException as exc:
                thread_errors.append({"thread": name, "type": type(exc).__name__,
                    "message": str(exc), "cause": repr(exc.__cause__),
                    "notes": list(getattr(exc, "__notes__", []))})
                raise
        thread = actual_thread(*args, **{**kwargs, "target": observed_target})
        threads.append(thread)
        return thread

    def observed_shutdown(owner):
        try:
            return original_shutdown(owner)
        except sessions._ListenerCleanupPending:
            if servers and owner.httpd is servers[0]:
                pending.set()
            raise

    try:
        with monkeypatch.context() as local:
            local.setattr(mcp_config, "_probe_single_server", observed_probe)
            local.setattr(sessions, "threading", SimpleNamespace(Thread=observed_thread))
            local.setattr(sessions, "http", SimpleNamespace(server=SimpleNamespace(
                HTTPServer=observed_server,
                BaseHTTPRequestHandler=sessions.http.server.BaseHTTPRequestHandler)))
            local.setattr(sessions._ListenerOwner, "shutdown", observed_shutdown)
            response = rpc("start")
            assert "error" not in response, response
            result = response["result"]
            assert result["ok"] and result["auth_url"]
            sid = result["session_id"]
            rec = sessions._sessions[sid]
            flow = rec["flow"]
            owner = servers[0]._hermes_oauth_listener_owner
            worker = next(t for t in threads if t.name == "mcp-oauth-reports")
            listener = next(t for t in threads if t.name == "mcp-oauth-cb-reports")
            assert len(servers) == 1 and len(threads) == 2
            assert entered.wait(5) and len(frames) == 1
            assert frames[0]["function"] == "serve_forever"
            assert frames[0]["source"].endswith("socketserver.py")
            assert frames[0]["native_id"] == listener.native_id
            assert owner.rec is rec and owner.flow is flow and owner.listener is listener
            probe_releases[0].set()
            assert pending.wait(8), "Unchanged actual five-second cleanup bound was not reached"
            assert listener.is_alive() and not hook_release.is_set()
            assert rec["httpd"] is servers[0] and not flow.worker_done
            rec["created_at"] -= sessions._SESSION_TTL_SECONDS + 1
            sessions._gc_sessions()
            assert sessions._sessions.get(sid) is rec
            duplicate = rpc("start")
            assert "already in progress" in duplicate["error"]["message"]
            outcomes["before_release"] = {
                "pending_from_actual_shutdown": True, "callback_alive": listener.is_alive(),
                "worker_alive": worker.is_alive(), "worker_done": flow.worker_done,
                "record_retained": rec["httpd"] is servers[0],
                "same_registry_record": sessions._sessions.get(sid) is rec,
                "owner_completed": owner.completed.is_set(), "flow_error": flow.error,
                "frames": frames, "probe_calls": list(probe_calls), "duplicate": duplicate,
            }
            record_property("actual_normal_cleanup_pending", json.dumps(outcomes["before_release"]))
            hook_release.set()
            listener.join(timeout=6)
            worker.join(timeout=8)
            outcomes["after_release"] = {
                "callback_alive": listener.is_alive(), "worker_alive": worker.is_alive(),
                "worker_done": flow.worker_done, "record_retained": rec["httpd"] is servers[0],
                "owner_completed": owner.completed.is_set(), "socket_fd": servers[0].socket.fileno(),
                "flow_error": flow.error, "thread_errors": list(thread_errors),
                "callback_native_id": listener.native_id, "worker_native_id": worker.native_id,
            }
            record_property("actual_normal_cleanup_late_exit", json.dumps(outcomes["after_release"]))
            assert not listener.is_alive() and not worker.is_alive()
            assert owner.completed.is_set() and servers[0].socket.fileno() == -1
            assert flow.worker_done, "Actual late callback exit left the acquired OAuth worker unfinished"
            assert outcomes["before_release"]["worker_alive"]
            assert rec["httpd"] is None and flow.error == cause and not thread_errors
            refused(servers[0].server_address[1])
            replacement = rpc("start")
            assert "error" not in replacement, replacement
            replacement_id = replacement["result"]["session_id"]
            assert replacement_id != sid
            assert len(servers) == 2 and len(probe_calls) == 2
            probe_releases[1].set()
            for thread in threads[2:]:
                thread.join(timeout=8)
                assert not thread.is_alive()
            replacement_rec = sessions._sessions[replacement_id]
            assert replacement_rec["flow"].worker_done and replacement_rec["httpd"] is None
            record_property("actual_normal_cleanup_replacement", json.dumps({
                "distinct_session": True, "workers": len(threads), "servers": len(servers),
                "replacement_done": True, "SDK_authorization_proof": False,
            }))
    finally:
        primary = sys.exception()
        hook_release.set()
        for release in probe_releases:
            release.set()
        def attempt(label, action):
            try:
                return action()
            except BaseException as exc:
                cleanup_errors.append(label + ": " + repr(exc))
                return None
        def joined(thread):
            thread.join(timeout=10)
            assert not thread.is_alive(), thread.name
        for index, thread in enumerate(threads):
            attempt("actual_thread_join_" + str(index), lambda thread=thread: joined(thread))
        for index, httpd in enumerate(servers):
            attempt("actual_server_close_" + str(index), httpd.server_close)
            attempt("actual_socket_refusal_" + str(index), lambda httpd=httpd: refused(httpd.server_address[1]))
        payload = attempt("cleanup_serialization", lambda: json.dumps({
            "failures": cleanup_errors, "barrier_errors": barrier_errors,
            "thread_errors": thread_errors, "native_ids": [t.native_id for t in threads],
            "same_actual_threads_joined": len(threads), "fixture_cleanup_is_product_proof": False,
        }))
        if payload is not None:
            attempt("cleanup_property_recording", lambda: record_property("actual_normal_cleanup_fixture_cleanup", payload))
        if cleanup_errors or barrier_errors:
            if primary is not None:
                primary.add_note("Owned late cleanup fixture failures: " + repr(cleanup_errors + barrier_errors))
            else:
                raise AssertionError(cleanup_errors + barrier_errors)
