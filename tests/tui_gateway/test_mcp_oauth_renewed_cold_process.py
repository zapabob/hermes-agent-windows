"""Renewed OAuth survives a real Windows process boundary without profile leakage."""
import hashlib
import inspect
import json
from pathlib import Path
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import psutil
import pytest

from tests.fakes.mcp_oauth_cold_process import cold, exited, identity, preserve_body_cause
from tests.fakes.mcp_oauth_gateway import (
    deliver, finish, homes as homes, refused, rpc, running_flow, scoped,
)
from tests.fakes.mcp_oauth_issuer import serve_issuer


@pytest.mark.windows_only
def test_renewed_token_survives_new_process_and_foreign_profile_stays_denied(
        homes, monkeypatch, record_property):
    from hermes_cli.mcp_config import _replace_mcp_servers
    from tools import mcp_tool as core
    from tools.registry import registry
    from tui_gateway import mcp_oauth_sessions as sessions

    work, other = homes / "profiles/work", homes / "profiles/other"
    token_path = work / "mcp-tokens/reports.json"
    transport = core.sdk_httpx()
    from mcp.client import streamable_http as sdk_transport
    assert transport is (getattr(sdk_transport, "httpx2", None)
                         or getattr(sdk_transport, "httpx", None))
    original_send = transport.AsyncClient._send_single_request
    original_browser = __import__("webbrowser").open
    original_hook = threading.excepthook
    responses, clients, browser_calls, thread_errors, secondary = [], {}, [], [], []
    resources, issuers, children = [], [], []
    observations = {"parent_birth": identity(psutil.Process())}
    body_error = None

    def attempt(label, action):
        try:
            return action()
        except BaseException as error:
            secondary.append({"operation": label, "type": type(error).__name__, "message": str(error)})

    def property_attempt(label, value):
        attempt("property_" + label, lambda: record_property(label, json.dumps(value)))

    async def observe_send(client, request, *args, **kwargs):
        clients[id(client)] = client
        response = await original_send(client, request, *args, **kwargs)
        responses.append({"method": request.method, "url": str(request.url),
                          "status": response.status_code, "_response": response})
        return response

    def forbidden_browser(url, *args, **kwargs):
        browser_calls.append(str(url))
        raise AssertionError("Noninteractive renewed/cold call attempted browser authorization")

    def observe_thread_error(args):
        thread_errors.append({"type": args.exc_type.__name__, "message": str(args.exc_value),
                              "thread": args.thread.name, "ident": args.thread.ident})
        original_hook(args)

    def joined(thread):
        if thread.ident is not None:
            thread.join(timeout=4)
        assert not thread.is_alive(), thread.name

    def resource_check(resource):
        for thread in resource["threads"]:
            joined(thread)
        loop = resource.get("loop")
        if loop is not None:
            assert loop.is_closed() and not loop.is_running()
        if resource.get("port") is not None:
            refused(resource["port"])

    def resource_row(resource):
        loop = resource.get("loop")
        return {"label": resource["label"], "port": resource.get("port"),
                "loop_closed": loop.is_closed() if loop is not None else None,
                "threads": [{"name": t.name, "ident": t.ident, "native_id": t.native_id,
                             "alive": t.is_alive()} for t in resource["threads"]]}

    def inventory():
        result = {}
        for name, home in (("work", work), ("other", other)):
            selected = [home / "config.yaml"]
            directory = home / "mcp-tokens"
            if directory.exists():
                selected += sorted(p for p in directory.rglob("*") if p.is_file())
            for path in selected:
                assert path.resolve() == path and not path.is_symlink()
                assert not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                               for p in [path, *path.parents] if p.is_relative_to(homes))
                result[name + "/" + str(path.relative_to(home))] = path.read_bytes()
        return result

    def ledger(peer):
        with peer.lock:
            return [dict(row) for row in peer.ledger]

    def settle_requests(peer):
        with peer.lock:
            threads = list(peer.request_threads)
        for thread in threads:
            joined(thread)

    def inspect_child(child, home):
        assert child["pid"] != observations["parent_birth"]["pid"]
        assert child["created"] >= observations["parent_birth"]["created"]
        assert Path(child["home"]) == home
        assert child["browser_calls"] == [] and child["unexpected_thread_errors"] == []
        assert child["original_body_failure"] is None and child["secondary_cleanup_failures"] == []
        assert all(child["observers_restored"].values()), child
        cleanup = child["cleanup"]
        assert cleanup["loop_observed"] and cleanup["loop_closed"] and not cleanup["loop_running"]
        assert cleanup["threads"] and all(not row["alive"] for row in cleanup["threads"])
        assert all(row["is_closed"] for row in cleanup["clients"])
        assert all(row["is_closed"] for row in child["responses"])
        assert child["runtime"]["prefix"] == sys.prefix
        assert child["runtime"]["base_prefix"] == sys.base_prefix
        assert child["runtime"]["transport_module"] == transport.__name__
        assert Path(child["runtime"]["environment"]["HERMES_HOME"]) == home
        for row in child["imports"]:
            module = sys.modules[row["module"]]
            source = Path(inspect.getsourcefile(module) or module.__file__).resolve()
            assert Path(row["physical_path"]) == source
            raw = source.read_bytes()
            assert row["sha256"] == hashlib.sha256(raw).hexdigest() and row["bytes"] == len(raw)
        assert {row["module"] for row in child["imports"]} == {
            "tools.mcp_tool", "tools.registry", "tools.mcp_oauth", "hermes_constants",
            "hermes_cli.config", "mcp.client.streamable_http", transport.__name__,
            original_send.__module__, "threading",
        }
        send = child["observed_send_binding"]
        send_source = Path(inspect.getsourcefile(original_send)).resolve()
        assert send["module"] == original_send.__module__
        assert send["qualname"] == original_send.__qualname__
        assert Path(send["raw_path"]).resolve() == send_source
        assert Path(send["physical_path"]) == send_source
        send_raw = send_source.read_bytes()
        assert send["sha256"] == hashlib.sha256(send_raw).hexdigest()
        assert send["bytes"] == len(send_raw)
        exited({key: child[key] for key in ("pid", "created", "exe", "argv")})

    try:
        with preserve_body_cause(monkeypatch.context(), "observer_undo", secondary) as observers:
            observers.setattr(transport.AsyncClient, "_send_single_request", observe_send)
            observers.setattr("webbrowser.open", forbidden_browser)
            observers.setattr(threading, "excepthook", observe_thread_error)
            before_listeners = set(threading.enumerate())
            with preserve_body_cause(serve_issuer(), "owner_issuer_cleanup", secondary) as owner:
                issuers.append(("owner", owner))
                listeners = set(threading.enumerate()) - before_listeners
                actual = [t for t in listeners if t.name == "owned-m03-issuer"]
                assert len(actual) == 1
                resources.append({"label": "owner_issuer", "threads": actual,
                                  "port": urlparse(owner.base).port})
                before_foreign = set(threading.enumerate())
                with preserve_body_cause(serve_issuer(), "foreign_issuer_cleanup", secondary) as foreign:
                    issuers.append(("foreign", foreign))
                    actual = [t for t in set(threading.enumerate()) - before_foreign
                              if t.name == "owned-m03-issuer"]
                    assert len(actual) == 1
                    resources.append({"label": "foreign_issuer", "threads": actual,
                                      "port": urlparse(foreign.base).port})
                    with preserve_body_cause(running_flow(owner, homes, manual_start=True),
                                             "warm_gateway_cleanup", secondary):
                        tool = "mcp__reports__write_sentinel"
                        with scoped(work):
                            assert tool not in core.discover_mcp_tools()
                            servers = [item for item in core._servers.values() if item.name == "reports"]
                            assert len(servers) == 1
                            persistent = servers[0]
                            task, loop, loop_thread = persistent._task, core._mcp_loop, core._mcp_thread
                        assert task is not None and not task.done()
                        warm = {"label": "warm_mcp", "threads": [loop_thread], "loop": loop}
                        resources.append(warm)

                        def retained_ready():
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

                        def authorize():
                            before = set(threading.enumerate())
                            flow = rpc("start")
                            assert flow["ok"] and flow.get("auth_url"), flow
                            rec = sessions._sessions[flow["session_id"]]
                            threads = set(threading.enumerate()) - before
                            workers = [t for t in threads if t.name == "mcp-oauth-reports"]
                            listeners = [t for t in threads if t.name == "mcp-oauth-cb-reports"]
                            assert len(workers) == len(listeners) == 1
                            port = rec["httpd"].server_address[1]
                            resources.append({"label": "oauth_" + flow["session_id"],
                                              "threads": workers + listeners, "port": port})
                            deliver(owner, flow, "match")
                            finish(rec, workers[0], listeners[0], port)
                            assert rpc("poll", session_id=flow["session_id"])["status"] == "approved"
                            return flow

                        def dispatch(nonce):
                            with scoped(work):
                                return json.loads(registry.dispatch(tool, {"nonce": nonce}))

                        first = authorize()
                        retained_ready()
                        assert "error" not in dispatch("renewed-cold-before")
                        assert [r["nonce"] for r in owner.operations("sentinel")] == ["renewed-cold-before"]
                        old_token = owner.token
                        owner.token = "owned-synthetic-renewed-cold-token"
                        response_start = len(responses)
                        request_start = len(owner.operations("mcp_request"))
                        denied = dispatch("renewed-cold-denied")
                        assert any(r["status"] == 401 for r in responses[response_start:])
                        assert any(r["method"] == "tools/call" and r["authorization"] == f"Bearer {old_token}"
                                   for r in owner.operations("mcp_request")[request_start:])
                        assert denied.get("error") and denied.get("needs_reauth") is True, denied
                        assert denied.get("server") == "reports"
                        assert [r["nonce"] for r in owner.operations("sentinel")] == ["renewed-cold-before"]
                        second = authorize()
                        assert second["session_id"] != first["session_id"]
                        states = [parse_qs(urlparse(flow["auth_url"]).query)["state"][0]
                                  for flow in (first, second)]
                        assert states[0] != states[1]
                        assert json.loads(token_path.read_text(encoding="utf-8"))["access_token"] == owner.token
                        assert len(owner.operations("token_redemption")) == 2
                        retained_ready()
                        assert "error" not in dispatch("renewed-cold-after")
                        assert [r["nonce"] for r in owner.operations("sentinel")] == [
                            "renewed-cold-before", "renewed-cold-after"]
                        assert browser_calls == []
                        observations["warm"] = {
                            "same_server": persistent in core._servers.values(),
                            "same_task": persistent._task is task, "same_loop": core._mcp_loop is loop,
                            "same_thread": core._mcp_thread is loop_thread,
                            "task_alive": not task.done(), "thread_ident": loop_thread.ident,
                            "states": states, "first_flow": first["session_id"],
                            "second_flow": second["session_id"],
                        }
                        assert all(observations["warm"][key] for key in (
                            "same_server", "same_task", "same_loop", "same_thread", "task_alive"))
                    for resource in resources[2:]:
                        resource_check(resource)
                    observations["warm_closed_before_cold"] = [resource_row(r) for r in resources[2:]]
                    with scoped(other):
                        ok, issues = _replace_mcp_servers({"reports": {
                            "url": foreign.mcp_url, "transport": "http", "auth": "oauth",
                            "oauth": {"cimd": False}, "timeout": 5}})
                        assert ok and not issues
                    anonymous = Request(foreign.mcp_url, data=json.dumps({
                        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
                    }).encode("utf-8"), headers={"Content-Type": "application/json"})
                    with pytest.raises(HTTPError) as refusal:
                        urlopen(anonymous, timeout=3)
                    assert refusal.value.code == 401
                    refusal.value.close()
                    settle_requests(owner)
                    settle_requests(foreign)
                    before_files = inventory()
                    assert not (other / "mcp-tokens/reports.json").exists()
                    owner_start = len(owner.operations("mcp_request"))
                    renewed = cold(work, "renewed-cold-third", True, homes.parent)
                    children.append(renewed)
                    inspect_child(renewed, work)
                    assert renewed["configured_url"] == owner.mcp_url
                    assert any(r["url"] == owner.mcp_url and 200 <= r["status"] < 300
                               for r in renewed["responses"])
                    actual_cold_requests = owner.operations("mcp_request")[owner_start:]
                    assert any(r["method"] == "tools/call" for r in actual_cold_requests)
                    assert all(r["authorization"] == f"Bearer {owner.token}" for r in actual_cold_requests)
                    assert [r["nonce"] for r in owner.operations("sentinel")] == [
                        "renewed-cold-before", "renewed-cold-after", "renewed-cold-third"]
                    assert len(owner.operations("token_redemption")) == 2
                    settle_requests(owner)
                    settle_requests(foreign)
                    before_owner, before_foreign = ledger(owner), ledger(foreign)
                    foreign_child = cold(other, "foreign-renewed-must-not-run", False, homes.parent)
                    children.append(foreign_child)
                    inspect_child(foreign_child, other)
                    assert (renewed["pid"], renewed["created"]) != (
                        foreign_child["pid"], foreign_child["created"])
                    assert foreign_child["configured_url"] == foreign.mcp_url
                    assert foreign_child["responses"] == []
                    assert ledger(owner) == before_owner and ledger(foreign) == before_foreign
                    assert foreign.operations("token_request") == [] and foreign.operations("sentinel") == []
                    assert all(r["authorization"] is None for r in foreign.operations("mcp_request"))
                    assert inventory() == before_files
                    observations["file_inventory"] = {
                        key: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                        for key, raw in before_files.items()}
                    observations["cold_owner_requests"] = actual_cold_requests
                    assert browser_calls == []
    except BaseException:
        body_error = sys.exc_info()
    finally:
        def final_resources():
            for name, peer in issuers:
                with peer.lock:
                    request_threads = list(peer.request_threads)
                resources.append({"label": name + "_requests", "threads": request_threads})
            for resource in resources:
                attempt(resource["label"] + "_cleanup", lambda resource=resource: resource_check(resource))
            return [resource_row(resource) for resource in resources]

        def final_transport():
            for row in responses:
                response = row.pop("_response")
                row["is_closed"] = response.is_closed
            assert all(c.is_closed for c in clients.values())
            assert all(r["is_closed"] for r in responses)
            return responses

        cleanup = attempt("resource_observation", final_resources)
        attempt("transport_cleanup", final_transport)
        def restore_send():
            transport.AsyncClient._send_single_request = original_send

        def restore_browser():
            __import__("webbrowser").open = original_browser

        def restore_hook():
            threading.excepthook = original_hook

        attempt("restore_send", restore_send)
        attempt("restore_browser", restore_browser)
        attempt("restore_thread_hook", restore_hook)

        def final_receipts():
            restored = {
                "send": transport.AsyncClient._send_single_request is original_send,
                "browser": __import__("webbrowser").open is original_browser,
                "thread_hook": threading.excepthook is original_hook,
            }
            if not all(restored.values()):
                secondary.append({"operation": "observer_restoration", "restored": restored})
            if thread_errors:
                secondary.append({"operation": "owned_thread_error", "errors": thread_errors})
            property_attempt("original_body_failure", (
                {"type": body_error[0].__name__, "message": str(body_error[1])} if body_error else None))
            property_attempt("renewed_cold_observations", observations)
            property_attempt("actual_issuer_ledgers", {name: ledger(peer) for name, peer in issuers})
            property_attempt("actual_owned_children", children)
            property_attempt("actual_resource_cleanup", cleanup)
            property_attempt("actual_transport_responses", responses)
            property_attempt("transparent_observers_restored", restored)
            property_attempt("unexpected_owned_thread_errors", thread_errors)
            property_attempt("automatic_browser_calls", browser_calls)

        attempt("final_receipts", final_receipts)
        property_attempt("secondary_cleanup_failures", secondary.copy())
    if body_error is not None:
        if secondary:
            body_error[1].add_note("Independent renewed/cold cleanup failures: " + repr(secondary))
        raise body_error[1].with_traceback(body_error[2])
    assert secondary == [], secondary
