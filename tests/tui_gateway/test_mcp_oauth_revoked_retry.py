"""Real revoked-token denial and explicit fresh authorization on a retained task."""
import hashlib
import inspect
import json
from pathlib import Path
import sys
import threading
import time
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

from tests.fakes.mcp_oauth_gateway import (
    deliver, finish, homes as homes, refused, rpc, running_flow, scoped,
)
from tests.fakes.mcp_oauth_issuer import serve_issuer


def public_start_observation():
    from hermes_constants import get_hermes_home_override
    from tui_gateway import server

    result = server._methods["mcp.servers.oauth.start"](
        91, {"name": "reports", "profile": "work"},
    )
    assert get_hermes_home_override() is None
    return result


def actual_flow_resources(rec):
    workers = [thread for thread in threading.enumerate()
               if thread.name == "mcp-oauth-reports" and thread.is_alive()]
    listeners = [thread for thread in threading.enumerate()
                 if thread.name == "mcp-oauth-cb-reports" and thread.is_alive()]
    assert len(workers) == len(listeners) == 1, (workers, listeners)
    return workers[0], listeners[0], rec["httpd"].server_address[1]


@contextmanager
def preserve_body_cause(manager, label, secondary):
    """Keep an actual behavioral exception when owned fixture cleanup also fails."""
    value = manager.__enter__()
    cause = None
    try:
        yield value
    except BaseException:
        cause = sys.exc_info()
    finally:
        try:
            manager.__exit__(*(cause or (None, None, None)))
        except BaseException as error:
            if cause is None:
                raise
            secondary.append({"operation": label, "type": type(error).__name__, "message": str(error)})
        if cause is not None:
            raise cause[1].with_traceback(cause[2])


def test_revoked_auth_recovers_through_fresh_public_flow(homes, monkeypatch, record_property):
    from tools import mcp_tool as core
    from tools.mcp_dashboard_oauth import DashboardOAuthFlow
    from tools.registry import registry
    from tui_gateway import mcp_oauth_sessions as sessions

    work = homes / "profiles/work"
    other = homes / "profiles/other"
    token_path = work / "mcp-tokens/reports.json"
    config_path = work / "config.yaml"
    transport = core.sdk_httpx()
    from mcp.client import streamable_http as sdk_transport
    assert transport is (getattr(sdk_transport, "httpx2", None)
                         or getattr(sdk_transport, "httpx", None))
    original_send = transport.AsyncClient._send_single_request
    original_done = DashboardOAuthFlow.mark_worker_done
    original_browser = __import__("webbrowser").open
    binding_path = Path(inspect.getsourcefile(original_send))
    record_property("installed_transport_observer_binding", json.dumps({
        "module": original_send.__module__, "qualname": original_send.__qualname__,
        "source": str(binding_path), "sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
    }))
    entered, release = threading.Event(), threading.Event()
    captured = {"flow": None, "completion_calls": 0}
    responses, browser_calls = [], []
    observations, body_failure = {}, None
    secondary, worker_errors, resources = [], [], []
    original_thread_hook = threading.excepthook

    def attempt(label, action):
        try:
            return action()
        except BaseException as error:
            secondary.append({"operation": label, "type": type(error).__name__, "message": str(error)})

    def property_attempt(label, value):
        attempt("property_" + label, lambda: record_property(label, json.dumps(value)))

    def observe_thread_error(args):
        worker_errors.append({"type": args.exc_type.__name__, "message": str(args.exc_value),
                              "thread": args.thread.name, "ident": args.thread.ident})
        original_thread_hook(args)

    def verify_cleanup():
        outcomes = []
        for label, threads, loop_resource, port in resources:
            for thread in threads:
                def joined(thread=thread):
                    thread.join(timeout=4)
                    assert not thread.is_alive(), thread.name
                attempt(label + "_join_" + thread.name, joined)
            if loop_resource is not None:
                def closed(loop_resource=loop_resource):
                    assert loop_resource.is_closed() and not loop_resource.is_running()
                attempt(label + "_loop_closed", closed)
            if port is not None:
                attempt(label + "_socket_refusal", lambda port=port: refused(port))
            outcomes.append({"resource": label, "threads": [{"name": t.name, "ident": t.ident,
                "alive": t.is_alive()} for t in threads], "port": port,
                "loop_closed": loop_resource.is_closed() if loop_resource is not None else None})
        return outcomes

    try:
        with preserve_body_cause(serve_issuer(), "issuer_cleanup", secondary) as owner:
            issuer_threads = [t for t in threading.enumerate() if t.name == "owned-m03-issuer"]
            assert len(issuer_threads) == 1
            resources.append(("issuer", issuer_threads, None, urlparse(owner.base).port))
            async def observe_send(client, request, *args, **kwargs):
                response = await original_send(client, request, *args, **kwargs)
                if str(request.url) == owner.mcp_url:
                    responses.append({"method": request.method, "url": str(request.url),
                                      "status": response.status_code,
                                      "response_identity": id(response)})
                return response

            def hold_first_completion(flow):
                if flow is captured["flow"]:
                    captured["completion_calls"] += 1
                    observations["completion_worker"] = {
                        "name": threading.current_thread().name,
                        "ident": threading.get_ident(), "flow_id": flow.flow_id,
                    }
                    entered.set()
                    if not release.wait(20):
                        raise AssertionError("Owned first completion barrier was not released")
                original_done(flow)

            def forbidden_browser(url, *args, **kwargs):
                browser_calls.append(str(url))
                raise AssertionError("Noninteractive revoked call attempted browser authorization")


            with preserve_body_cause(monkeypatch.context(), "observer_undo", secondary) as observers:
                observers.setattr(transport.AsyncClient, "_send_single_request", observe_send)
                observers.setattr(DashboardOAuthFlow, "mark_worker_done", hold_first_completion)
                observers.setattr("webbrowser.open", forbidden_browser)
                observers.setattr(threading, "excepthook", observe_thread_error)
                with preserve_body_cause(running_flow(owner, homes, manual_start=True),
                                         "gateway_fixture_cleanup", secondary):
                    try:
                        with scoped(work):
                            tool = "mcp__reports__write_sentinel"
                            assert tool not in core.discover_mcp_tools()
                            servers = [item for item in core._servers.values() if item.name == "reports"]
                            assert len(servers) == 1
                            persistent = servers[0]
                            task, loop, loop_thread = persistent._task, core._mcp_loop, core._mcp_thread
                            resources.append(("persistent_mcp", [loop_thread], loop, None))
                        assert task is not None and not task.done()
                        assert loop.is_running() and loop_thread.is_alive()

                        def retained_runtime_ready():
                            with scoped(work):
                                core.discover_mcp_tools()
                                deadline = time.monotonic() + 15
                                while time.monotonic() < deadline:
                                    if persistent.session is not None and registry.get_entry(tool) is not None:
                                        break
                                    time.sleep(0.05)
                                assert persistent.session is not None and registry.get_entry(tool) is not None
                            assert persistent in core._servers.values() and persistent._task is task
                            assert core._mcp_loop is loop and core._mcp_thread is loop_thread
                            assert not task.done() and loop.is_running() and loop_thread.is_alive()

                        def dispatch(nonce):
                            with scoped(work):
                                return json.loads(registry.dispatch(tool, {"nonce": nonce}))

                        first = rpc("start")
                        assert first["ok"] and first.get("auth_url"), first
                        first_rec = sessions._sessions[first["session_id"]]
                        captured["flow"] = first_rec["flow"]
                        first_worker, first_listener, first_port = actual_flow_resources(first_rec)
                        resources.append(("first_oauth", [first_worker, first_listener], None, first_port))
                        first_state = parse_qs(urlparse(first["auth_url"]).query)["state"][0]
                        deliver(owner, first, "match")
                        assert entered.wait(12), first_rec["flow"].snapshot()
                        assert first_worker.is_alive() and not first_rec["flow"].worker_done
                        assert observations["completion_worker"]["ident"] == first_worker.ident
                        assert first_rec["httpd"] is None
                        first_listener.join(timeout=3)
                        assert not first_listener.is_alive()
                        refused(first_port)
                        assert rpc("poll", session_id=first["session_id"])["status"] == "approved"
                        prior_token, prior_config = token_path.read_bytes(), config_path.read_bytes()
                        other_config = (other / "config.yaml").read_bytes()
                        assert json.loads(prior_token)["access_token"] == owner.token
                        first_snapshot = first_rec["flow"].snapshot()
                        session_ids = set(sessions._sessions)
                        before_threads = set(threading.enumerate())
                        rejected_start = public_start_observation()
                        observations["held_first_admission"] = rejected_start
                        assert "already in progress" in json.dumps(rejected_start), rejected_start
                        assert set(sessions._sessions) == session_ids
                        assert sessions._sessions[first["session_id"]] is first_rec
                        assert first_rec["flow"].snapshot() == first_snapshot
                        assert not first_rec["flow"].worker_done and first_worker.is_alive()
                        assert not [thread for thread in threading.enumerate()
                                    if thread not in before_threads and thread.name in
                                    {"mcp-oauth-reports", "mcp-oauth-cb-reports"}]
                        assert token_path.read_bytes() == prior_token and config_path.read_bytes() == prior_config
                        assert (other / "config.yaml").read_bytes() == other_config
                        assert not (other / "mcp-tokens/reports.json").exists()
                        release.set()
                        finish(first_rec, first_worker, first_listener, first_port)
                        assert captured["completion_calls"] == 1
                        retained_runtime_ready()
                        assert "error" not in dispatch("revoked-recovery-before")
                        assert [row["nonce"] for row in owner.operations("sentinel")] == ["revoked-recovery-before"]
                        assert any(200 <= row["status"] < 300 for row in responses), responses

                        old_token = owner.token
                        owner.token = "owned-synthetic-reauthorized-token"
                        response_start = len(responses)
                        request_start = len(owner.operations("mcp_request"))
                        denied = dispatch("revoked-recovery-denied")
                        observations["revoked_dispatch"] = denied
                        assert any(row["status"] == 401 for row in responses[response_start:]), responses[response_start:]
                        revoked_requests = owner.operations("mcp_request")[request_start:]
                        assert any(row["method"] == "tools/call" and row["authorization"] == f"Bearer {old_token}"
                                   for row in revoked_requests), revoked_requests
                        assert denied.get("error") and denied.get("needs_reauth") is True, denied
                        assert denied.get("server") == "reports", denied
                        assert browser_calls == []
                        assert [row["nonce"] for row in owner.operations("sentinel")] == ["revoked-recovery-before"]
                        assert persistent._task is task and not task.done()

                        second = rpc("start")
                        assert second["ok"] and second.get("auth_url"), second
                        assert second["session_id"] != first["session_id"]
                        second_state = parse_qs(urlparse(second["auth_url"]).query)["state"][0]
                        assert second_state != first_state
                        second_rec = sessions._sessions[second["session_id"]]
                        second_worker, second_listener, second_port = actual_flow_resources(second_rec)
                        resources.append(("second_oauth", [second_worker, second_listener], None, second_port))
                        assert second_rec["flow"] is not first_rec["flow"]
                        assert rpc("callback", session_id=first["session_id"], code="late-old", state=first_state)["ok"] is False
                        assert rpc("callback", session_id=second["session_id"], code="wrong-state", state=first_state)["ok"] is False
                        assert rpc("callback", profile="other", session_id=second["session_id"],
                                   code="foreign", state=second_state)["ok"] is False
                        assert not second_rec["flow"]._callback_ready.is_set()
                        deliver(owner, second, "match")
                        finish(second_rec, second_worker, second_listener, second_port)
                        assert rpc("poll", session_id=second["session_id"])["status"] == "approved"
                        assert json.loads(token_path.read_text(encoding="utf-8"))["access_token"] == owner.token
                        assert owner.token != old_token and len(owner.operations("token_redemption")) == 2
                        assert not (other / "mcp-tokens/reports.json").exists()
                        assert (other / "config.yaml").read_bytes() == other_config
                        retained_runtime_ready()
                        recovered = dispatch("revoked-recovery-after")
                        observations["recovered_dispatch"] = recovered
                        assert "error" not in recovered, recovered
                        assert [row["nonce"] for row in owner.operations("sentinel")] == [
                            "revoked-recovery-before", "revoked-recovery-after",
                        ]
                        assert browser_calls == []
                        assert persistent._task is task and not task.done()
                        assert core._mcp_loop is loop and core._mcp_thread is loop_thread
                        observations["retained_runtime"] = {
                            "server": persistent.name, "same_server": persistent in core._servers.values(),
                            "same_task": persistent._task is task, "same_loop": core._mcp_loop is loop,
                            "same_thread": core._mcp_thread is loop_thread, "thread_ident": loop_thread.ident,
                            "task_alive": not task.done(),
                        }
                    except BaseException as error:
                        body_failure = {"type": type(error).__name__, "message": str(error)}
                        raise
                    finally:
                        attempt("completion_barrier_release", release.set)
                        property_attempt("original_body_failure", body_failure)
                        property_attempt("revoked_recovery_observations", observations)
                        property_attempt("actual_issuer_ledger", owner.ledger)
                        property_attempt("actual_transport_responses", responses)
                        property_attempt("automatic_browser_calls", browser_calls)
    finally:
        original_error = sys.exc_info()[1]
        if "owner" in locals():
            with owner.lock:
                resources.append(("issuer_requests", list(owner.request_threads), None, None))
        cleanup = attempt("resource_cleanup_receipt", verify_cleanup)
        restored = {
            "send": transport.AsyncClient._send_single_request is original_send,
            "completion": DashboardOAuthFlow.mark_worker_done is original_done,
            "browser": __import__("webbrowser").open is original_browser,
            "thread_hook": threading.excepthook is original_thread_hook,
        }
        property_attempt("actual_resource_cleanup", cleanup)
        property_attempt("unexpected_thread_errors", worker_errors)
        property_attempt("transparent_observers_restored", restored)
        if not all(restored.values()):
            secondary.append({"operation": "observer_restoration", "restored": restored})
        if worker_errors:
            secondary.append({"operation": "unexpected_worker_exception", "errors": worker_errors})
        property_attempt("secondary_cleanup_failures", secondary.copy())
        if secondary:
            if original_error is not None:
                original_error.add_note("Independent cleanup failures: " + repr(secondary))
            else:
                raise AssertionError("Independent cleanup failures: " + repr(secondary))
