"""Fresh public authorization retains the actual persistent MCP runtime."""
import json
import threading
import time
from urllib.parse import urlparse, parse_qs

import pytest

from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.fakes.mcp_oauth_gateway import closed, deliver, finish, homes as homes, refused, rpc, scoped


def observed_start():
    from tui_gateway import server
    from hermes_constants import get_hermes_home_override

    method = "mcp.servers.oauth.start"
    assert method in server._methods
    try:
        result = server._methods[method](81, {"profile": "work", "name": "reports"})
    except Exception as error:
        result = {"observed_exception": {"type": type(error).__name__, "message": str(error)}}
    assert get_hermes_home_override() is None
    return result


@pytest.mark.parametrize("cancel_first", [False, True], ids=["active-overlap-denied", "cancelled-fresh-retry"])
def test_public_fresh_retry_keeps_live_runtime_and_distinct_flow(homes, cancel_first, record_property):
    from hermes_cli.mcp_config import _replace_mcp_servers
    from tools import mcp_tool as core
    from tools.registry import registry
    from tui_gateway import mcp_oauth_sessions as sessions

    with serve_issuer() as owner:
        cfg = {"url": owner.mcp_url, "transport": "http", "auth": "oauth", "oauth": {"cimd": False}, "timeout": 5}
        work = homes / "profiles/work"
        token = work / "mcp-tokens/reports.json"
        resources = set()
        ports = set()
        loops = []
        before = set(threading.enumerate())
        observations = {}
        try:
            for profile in ("work", "other"):
                with scoped(homes / "profiles" / profile):
                    ok, issues = _replace_mcp_servers({"reports": cfg})
                    assert ok and not issues, issues
            with scoped(work):
                assert "mcp__reports__write_sentinel" not in core.discover_mcp_tools()
                registered = [item for item in core._servers.values() if item.name == "reports"]
                assert len(registered) == 1
                persistent = registered[0]
                loop, loop_thread = core._mcp_loop, core._mcp_thread
            loops.append((loop, loop_thread))
            assert loop.is_running() and loop_thread.is_alive()
            assert persistent._task is not None and not persistent._task.done()
            persistent_task = persistent._task
            observations["initial_runtime"] = {
                "parked": persistent._was_parked, "session_absent": persistent.session is None,
                "error": repr(persistent._error), "connect_errors": [
                    {"key": repr(key), "error": repr(value)} for key, value in core._server_connect_errors.items()
                ],
                "task_alive": not persistent_task.done(),
            }
            record_property("initial_parked_runtime", json.dumps(observations["initial_runtime"]))
            assert persistent._was_parked and persistent.session is None and persistent._error is not None
            first_observed = observed_start()
            observations["first_start"] = first_observed
            assert "error" not in first_observed and "observed_exception" not in first_observed, first_observed
            first = first_observed["result"]
            assert first["ok"] and first.get("auth_url"), first
            first_rec = sessions._sessions[first["session_id"]]
            first_url = urlparse(first["auth_url"])
            first_query = parse_qs(first_url.query)
            first_port = first_rec["httpd"].server_address[1]
            ports.add(first_port)
            resources.update(thread for thread in threading.enumerate() if thread not in before
                             and thread.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"})
            first_workers = [thread for thread in resources if thread.name == "mcp-oauth-reports"]
            first_listeners = [thread for thread in resources if thread.name == "mcp-oauth-cb-reports"]
            assert len(first_workers) == len(first_listeners) == 1
            if cancel_first:
                cancellation = rpc("cancel", session_id=first["session_id"])
                assert cancellation["cancelled"] is True, cancellation
                observations["cancel"] = cancellation
                observations["first_worker_done_before_retry"] = first_rec["flow"].worker_done
            second_observed = observed_start()
            observations["second_start"] = second_observed
            observations["first_after_second_start"] = first_rec["flow"].snapshot()
            record_property("retry_observations_before_assertion", json.dumps(observations))
            assert core._mcp_loop is loop and core._mcp_thread is loop_thread
            assert loop.is_running() and loop_thread.is_alive()
            assert persistent in core._servers.values() and not persistent._task.done()
            if not cancel_first:
                assert "already in progress" in json.dumps(second_observed), second_observed
                assert not first_rec["flow"]._callback_ready.is_set()
                completed = first
                completed_rec = first_rec
            else:
                assert "error" not in second_observed and "observed_exception" not in second_observed, second_observed
                completed = second_observed["result"]
                assert completed.get("ok") and completed.get("auth_url"), completed
                assert completed["session_id"] != first["session_id"]
                second_query = parse_qs(urlparse(completed["auth_url"]).query)
                assert second_query["state"] != first_query["state"]
                assert first_rec["flow"].snapshot()["error"] == "Cancelled by user"
                assert rpc("callback", session_id=first["session_id"], code="late", state=first_query["state"][0])["ok"] is False
                completed_rec = sessions._sessions[completed["session_id"]]
                # worker_done follows confirmed listener cleanup in the owner.
                # Rejected second-start RED remains above these cleanup waits.
                for thread in first_workers + first_listeners:
                    thread.join(timeout=12)
                    assert_exited(thread)
                assert first_rec["flow"].worker_done
                refused(first_port)
            completed_port = completed_rec["httpd"].server_address[1]
            ports.add(completed_port)
            resources.update(thread for thread in threading.enumerate() if thread not in before
                             and thread.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"})
            workers = [thread for thread in resources if thread.name == "mcp-oauth-reports" and thread.is_alive()]
            listeners = [thread for thread in resources if thread.name == "mcp-oauth-cb-reports" and thread.is_alive()]
            # The original cancelled worker must be finished before a replacement
            # can exchange tokens/configuration, preventing rollback overlap.
            if cancel_first:
                assert first_rec["flow"].worker_done
                refused(first_port)
            assert len(workers) == len(listeners) == 1
            deliver(owner, completed, "match")
            finish(completed_rec, workers[0], listeners[0], completed_port)
            assert rpc("poll", session_id=completed["session_id"])["status"] == "approved"
            assert json.loads(token.read_text(encoding="utf-8"))["access_token"] == owner.token
            assert not (homes / "profiles/other/mcp-tokens/reports.json").exists()
            assert len(owner.operations("token_redemption")) == 1
            with scoped(work):
                tool = "mcp__reports__write_sentinel"
                core.discover_mcp_tools()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if persistent.session is not None and registry.get_entry(tool) is not None:
                        break
                    time.sleep(0.05)
                assert persistent.session is not None and registry.get_entry(tool) is not None, core._server_connect_errors
                assert core._mcp_loop is loop and core._mcp_thread is loop_thread
                assert persistent in core._servers.values() and persistent._task is persistent_task
                assert not persistent_task.done() and loop.is_running() and loop_thread.is_alive()
                result = json.loads(registry.dispatch(tool, {"nonce": "persistent-fresh-retry"}))
                assert "error" not in result, result
            assert [row["nonce"] for row in owner.operations("sentinel")] == ["persistent-fresh-retry"]
            record_property("actual_issuer_ledger", json.dumps(owner.ledger))
        finally:
            failures = []
            def attempt(label, action):
                try:
                    action()
                except BaseException as error:
                    failures.append(label + ": " + repr(error))
            owner.token_release.set()
            resources.update(thread for thread in threading.enumerate() if thread not in before
                             and thread.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"})
            for rec in list(sessions._sessions.values()):
                if rec["hermes_home"] != str(work):
                    continue
                if rec.get("httpd") is not None:
                    ports.add(rec["httpd"].server_address[1])
                attempt("release_flow", lambda rec=rec: rec["flow"].mark_error("Owned retry fixture cleanup"))
                attempt("close_listener", lambda rec=rec: sessions._shutdown_listener(rec))
            for thread in resources:
                attempt("join_gateway", lambda thread=thread: thread.join(timeout=12))
                attempt("gateway_exit", lambda thread=thread: assert_exited(thread))
            if core._mcp_loop is not None and (core._mcp_loop, core._mcp_thread) not in loops:
                loops.append((core._mcp_loop, core._mcp_thread))
            attempt("core_shutdown", core.shutdown_mcp_servers)
            for loop, thread in loops:
                attempt("core_thread_join", lambda thread=thread: thread.join(timeout=3))
                attempt("core_thread_exit", lambda thread=thread: assert_exited(thread))
                attempt("core_loop_closed", lambda loop=loop: closed(loop))
            for port in ports:
                attempt("listener_refused", lambda port=port: refused(port))
            record_property("retry_cleanup", json.dumps({"observations": observations, "failures": failures}))
            assert failures == [], failures


def assert_exited(thread):
    assert not thread.is_alive(), thread.name
