"""Public admission reservation uses real flows/listeners, isolated worker seam.

The worker seam publishes an authorization URL and awaits actual cancellation;
this oracle qualifies admission/cap effects, never token or SDK success.
"""
import asyncio
import json
import threading

import pytest

from tests.fakes.mcp_oauth_gateway import homes as homes, refused, scoped


@pytest.mark.parametrize("kind,second_name,expected", [
    ("same-owner-overlap", "reports", 1),
    ("global-cap", "alternate", 1),
    ("independent-servers", "alternate", 2),
])
def test_public_start_reserves_one_slot_before_listener_setup(homes, monkeypatch, kind, second_name, expected, record_property):
    from hermes_cli.mcp_config import _replace_mcp_servers
    from hermes_constants import get_hermes_home_override
    from tui_gateway import mcp_oauth_sessions as sessions
    from tui_gateway import server

    with scoped(homes / "profiles/work"):
        cfg = {"url": "http://127.0.0.1:1/mcp", "transport": "http", "auth": "oauth"}
        ok, issues = _replace_mcp_servers({"reports": cfg, "alternate": cfg})
        assert ok and not issues, issues
    if kind == "global-cap":
        monkeypatch.setattr(sessions, "_MAX_PENDING", 1)
    gate_entered = threading.Event()
    release_gate = threading.Event()
    second_finished = threading.Event()
    guard = threading.Lock()
    responses = {}
    setup_entries = []
    worker_errors = []
    listener_factory = sessions._start_loopback_listener
    before = set(threading.enumerate())
    owned = set()
    ports = set()

    def gated_listener(flow):
        with guard:
            setup_entries.append(flow.flow_id)
            first = len(setup_entries) == 1
        if first:
            gate_entered.set()
            if not release_gate.wait(8):
                raise RuntimeError("Owned admission fixture gate was not released")
        return listener_factory(flow)

    def worker(session_id, home, name, cfg, reconnect_live):
        rec = sessions._sessions[session_id]
        flow = rec["flow"]
        try:
            asyncio.run(flow.publish_authorization_url(
                "http://127.0.0.1:1/authorize?state=" + session_id
            ))
            if not flow._callback_ready.wait(10):
                raise RuntimeError("Owned admission worker cancellation did not arrive")
        except BaseException as error:
            worker_errors.append(repr(error))
            flow.mark_error(str(error))
        finally:
            sessions._shutdown_listener(rec)
            flow.mark_worker_done()

    def invoke(index, name):
        try:
            responses[index] = server._methods["mcp.servers.oauth.start"](
                91 + index, {"profile": "work", "name": name}
            )
            if get_hermes_home_override() is not None:
                raise RuntimeError("Public start did not restore HOME")
        except BaseException as error:
            responses[index] = {"observed_exception": repr(error)}
        finally:
            if index == 2:
                second_finished.set()

    monkeypatch.setattr(sessions, "_start_loopback_listener", gated_listener)
    monkeypatch.setattr(sessions, "_worker", worker)
    first = threading.Thread(target=invoke, args=(1, "reports"), name="owned-admission-first")
    second = threading.Thread(target=invoke, args=(2, second_name), name="owned-admission-second")
    started = []
    try:
        first.start()
        started.append(first)
        assert gate_entered.wait(6), "First public start must reach its listener setup"
        second.start()
        started.append(second)
        # An unreserved baseline can complete the second listener/flow; a
        # reserved candidate rejects the overlap before invoking the factory.
        assert second_finished.wait(6), responses
        release_gate.set()
        for thread in started:
            thread.join(timeout=6)
            assert not thread.is_alive(), thread.name
        owned.update(thread for thread in threading.enumerate() if thread not in before
                     and thread.name.startswith(("mcp-oauth-", "mcp-oauth-cb-")))
        for rec in sessions._sessions.values():
            if rec.get("httpd") is not None:
                ports.add(rec["httpd"].server_address[1])
        record_property("actual_public_admission", json.dumps({
            "kind": kind, "responses": responses, "setup_entries": setup_entries,
            "active_flows": len(sessions._sessions), "listener_ports": sorted(ports),
        }))
        assert all("observed_exception" not in response for response in responses.values()), responses
        successful = [row["result"] for row in responses.values() if "result" in row and row["result"].get("ok")]
        assert len(successful) == expected, responses
        assert len(sessions._sessions) == expected
        assert len(setup_entries) == len(ports) == expected
        assert len({row["session_id"] for row in successful}) == expected
        if expected == 1:
            assert "error" in responses[2], responses
    finally:
        release_gate.set()
        failures = []
        for thread in started:
            thread.join(timeout=8)
            if thread.is_alive():
                failures.append("public_start_still_alive:" + thread.name)
        owned.update(thread for thread in threading.enumerate() if thread not in before
                     and thread.name.startswith(("mcp-oauth-", "mcp-oauth-cb-")))
        for sid, rec in list(sessions._sessions.items()):
            if rec.get("httpd") is not None:
                ports.add(rec["httpd"].server_address[1])
            try:
                result = server._methods["mcp.servers.oauth.cancel"](
                    99, {"profile": "work", "name": rec["server_name"], "session_id": sid}
                )
                if "error" in result or not result.get("result", {}).get("cancelled"):
                    failures.append("owned_cancel_failed:" + repr(result))
                    rec["flow"].mark_error("Owned failed cancel cleanup")
            except BaseException as error:
                failures.append("owned_cancel_exception:" + repr(error))
                rec["flow"].mark_error("Owned failed cancel cleanup")
        for thread in owned:
            thread.join(timeout=6)
            if thread.is_alive():
                failures.append("worker_or_listener_alive:" + thread.name)
        for port in ports:
            try:
                refused(port)
            except BaseException as error:
                failures.append("listener_refusal:" + repr(error))
        record_property("actual_admission_cleanup", json.dumps({"failures": failures, "worker_errors": worker_errors}))
        assert not failures and not worker_errors, (failures, worker_errors)
