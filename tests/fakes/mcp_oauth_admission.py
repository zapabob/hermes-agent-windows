"""Owned public admission fixture; authorization work is an explicit seam."""
import asyncio
import json
import threading
import pytest
from tests.fakes.mcp_oauth_gateway import homes as homes, refused, scoped


@pytest.fixture
def admission(homes, monkeypatch, record_property):
    from hermes_cli.mcp_config import _replace_mcp_servers
    from hermes_constants import get_hermes_home_override
    from tui_gateway import mcp_oauth_sessions as sessions
    from tui_gateway import server

    for profile in ("work", "other"):
        with scoped(homes / "profiles" / profile):
            ok, issues = _replace_mcp_servers({"reports": {
                "url": "http://127.0.0.1:1/mcp", "transport": "http", "auth": "oauth",
            }})
            assert ok and not issues, issues
    release = threading.Event()
    release.set()
    authorization_release = threading.Event()
    authorization_release.set()
    authorization_held = threading.Event()
    guard = threading.RLock()
    errors = []
    before = set(threading.enumerate())
    resources = set()
    ports = set()
    callers = []
    ledger = []

    def records():
        with sessions._sessions_lock:
            return list(sessions._sessions.items())

    def capture():
        observed = [thread for thread in threading.enumerate() if thread not in before
                    and thread.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"}]
        observed_ports = set()
        for sid, rec in records():
            if rec.get("httpd") is not None:
                httpd = rec["httpd"]
                if httpd is not None:
                    observed_ports.add(httpd.server_address[1])
        with guard:
            resources.update(observed)
            ports.update(observed_ports)

    def worker(sid, home, name, cfg, reconnect_live):
        rec = sessions._sessions[sid]
        flow = rec["flow"]
        try:
            if not authorization_release.is_set():
                authorization_held.set()
                if not authorization_release.wait(8):
                    raise RuntimeError("Owned authorization gate was not released")
                if flow.snapshot()["status"] == "error":
                    return
            asyncio.run(flow.publish_authorization_url("http://127.0.0.1:1/authorize?state=" + sid))
            if not flow._callback_ready.wait(10):
                raise RuntimeError("Owned edge worker was not released")
            if not release.wait(8):
                raise RuntimeError("Owned edge cleanup gate was not released")
        except BaseException as error:
            with guard:
                errors.append(repr(error))
            flow.mark_error(str(error))
        finally:
            sessions._shutdown_listener(rec)
            flow.mark_worker_done()

    def rpc(operation, profile="work", **params):
        result = server._methods["mcp.servers.oauth." + operation](101, {
            "name": "reports", "profile": profile, **params,
        })
        assert get_hermes_home_override() is None
        with guard:
            ledger.append({"operation": operation, "profile": profile, "response": result})
        capture()
        return result

    monkeypatch.setattr(sessions, "_worker", worker)
    try:
        yield rpc, release, callers, sessions, ledger, guard, authorization_release, authorization_held
    finally:
        failures = []
        release.set()
        authorization_release.set()
        for thread in callers:
            thread.join(timeout=8)
            if thread.is_alive():
                failures.append("caller_alive:" + thread.name)
        try:
            capture()
        except BaseException as error:
            failures.append("capture_exception:" + repr(error))
        for sid, rec in records():
            try:
                rpc("cancel", profile="work", session_id=sid)
            except BaseException as error:
                failures.append("cancel_exception:" + repr(error))
            rec["flow"].mark_error("Owned edge cleanup")
            try:
                sessions._shutdown_listener(rec)
            except BaseException as error:
                failures.append("listener_close:" + repr(error))
        with guard:
            owned_threads, owned_ports = list(resources), list(ports)
        for thread in owned_threads:
            thread.join(timeout=6)
            if thread.is_alive():
                failures.append("gateway_thread_alive:" + thread.name)
        for port in owned_ports:
            try:
                refused(port)
            except BaseException as error:
                failures.append("port_refusal:" + repr(error))
        with guard:
            worker_errors = list(errors)
        record_property("actual_admission_edge_cleanup", json.dumps({"failures": failures, "worker_errors": worker_errors}))
        assert failures == [] and worker_errors == [], (failures, worker_errors)
