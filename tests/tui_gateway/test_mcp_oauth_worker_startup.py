"""Unexecuted Gateway worker oracle; real native acquisition and MCP SDK."""
import json
import re
import sys
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tests.fakes.mcp_oauth_gateway import (
    closed,
    deliver,
    finish,
    homes as homes,
    registry_effect,
    running_flow,
    scoped,
)
from tests.fakes.mcp_oauth_issuer import serve_issuer
from tui_gateway import mcp_oauth_sessions as sessions
from tui_gateway import server


class StartupBarrierError(RuntimeError):
    """Invalid experiment, distinct from the deliberately raised startup cause."""


def raw_rpc(operation, *, profile="work", name="reports", **params):
    method = f"mcp.servers.oauth.{operation}"
    assert method in server._methods
    return server._methods[method](29, {"name": name, "profile": profile, **params})


def settled(flow, worker, loops):
    assert flow._worker_done.wait(12), flow.snapshot()
    worker.join(timeout=3)
    assert not worker.is_alive()
    for loop, thread in loops:
        closed(loop)
        thread.join(timeout=3)
        assert not thread.is_alive()


@contextmanager
def manual_gateway(owner, root, record_property):
    manager = running_flow(owner, root, manual_start=True)
    try:
        values = manager.__enter__()
    except BaseException as error:
        try:
            record_property("gateway_fixture_cleanup", json.dumps({"completed": False, "failures": [repr(error)]}))
        except BaseException as recording_error:
            error.add_note("Gateway setup cleanup recording failed: " + repr(recording_error))
        raise
    body_error = body_traceback = None
    failures = []
    try:
        yield values[5]
    except BaseException as error:
        body_error, body_traceback = error, error.__traceback__
    finally:
        try:
            manager.__exit__(type(body_error) if body_error else None, body_error, body_traceback)
        except BaseException as error:
            failures.append("fixture_cleanup: " + repr(error))
        try:
            record_property("gateway_fixture_cleanup", json.dumps({
                "completed": not failures, "failures": list(failures),
            }))
        except BaseException as error:
            failures.append("fixture_cleanup_recording: " + repr(error))
    if body_error is not None:
        if failures:
            body_error.add_note("Owned Gateway fixture cleanup failed: " + repr(failures))
        raise body_error.with_traceback(body_traceback)
    if failures:
        raise AssertionError(failures)


class GatewayStartupOwner:
    """Capture the exact Gateway worker without patching global Thread/Event APIs."""

    def __init__(self, mode, owner, loops, monkeypatch, *, failure_class=RuntimeError):
        from hermes_cli import mcp_config
        from tui_gateway import mcp_oauth_sessions as sessions
        from tools import mcp_dashboard_oauth as dashboard
        from tools import mcp_tool as core

        self.mode = mode
        self.failure_class = failure_class
        self.owner = owner
        self.loops = loops
        self.cause = "Owned Gateway startup failure: " + mode
        self.rows = []
        self.barrier_failures = []
        self.native_acquired = threading.Event()
        self.bootstrap_release = threading.Event()
        self.cleanup_entered = threading.Event()
        self.cleanup_release = threading.Event()
        self.fault_patch = pytest.MonkeyPatch()
        self.trace_patch = pytest.MonkeyPatch()
        self.removed = False
        self.original_target = sessions._worker
        self.created_flows = {}
        original_flow = dashboard.DashboardOAuthFlow

        def observed_flow(*args, **kwargs):
            flow = original_flow(*args, **kwargs)
            self.created_flows[flow.flow_id] = flow
            return flow

        self.set_attr(self.fault_patch, dashboard, "DashboardOAuthFlow", observed_flow)
        original_thread = threading.Thread
        original_probe = mcp_config._probe_single_server
        original_loop = core._ensure_mcp_loop

        def observed_loop(*args, **kwargs):
            result = original_loop(*args, **kwargs)
            pair = (core._mcp_loop, core._mcp_thread)
            if pair[0] is not None and pair not in self.loops:
                self.loops.append(pair)
            return result

        self.set_attr(self.trace_patch, core, "_ensure_mcp_loop", observed_loop)

        def real_probe(*args, **kwargs):
            try:
                return original_probe(*args, **kwargs)
            finally:
                if self.mode == "after_sdk_start" and self.rows and threading.current_thread() is self.rows[0]["thread"]:
                    self.cleanup_entered.set()
                    if not self.cleanup_release.wait(20):
                        self.barrier_failures.append("Actual SDK cleanup barrier timed out")

        self.set_attr(self.fault_patch, mcp_config, "_probe_single_server", real_probe)

        def factory(*args, **kwargs):
            if kwargs.get("target") is not self.original_target or kwargs.get("name") != "mcp-oauth-reports":
                return original_thread(*args, **kwargs)
            if self.rows:
                # An admission mutant must be observed through a real second
                # worker, not converted into an invalid fake-start failure.
                worker = original_thread(*args, **kwargs)
                row = {"flow": self.created_flows[kwargs["args"][0]], "thread": worker,
                       "original_start_invoked": False, "native_acquired": False,
                       "native_id": None, "native_ident": None,
                       "native_thread_object_id": None, "intended_error_raised": False}
                self.rows.append(row)
                original_start = worker.start

                def overlapping_start():
                    row["original_start_invoked"] = True
                    original_start()
                    row.update(native_acquired=True, native_id=worker.native_id,
                               native_ident=worker.ident, native_thread_object_id=id(worker))

                self.set_attr(self.fault_patch, worker, "start", overlapping_start)
                return worker
            flow = self.created_flows[kwargs["args"][0]]
            row = {"flow": flow, "thread": None, "original_start_invoked": False,
                   "native_acquired": False, "native_id": None, "native_ident": None,
                   "native_thread_object_id": None, "intended_error_raised": False}
            self.rows.append(row)
            if self.mode == "constructor":
                row["intended_error_raised"] = True
                raise self.failure_class(self.cause)
            worker = original_thread(*args, **kwargs)
            row["thread"] = worker
            original_start = worker.start
            original_bootstrap = worker._bootstrap_inner

            if self.mode == "bootstrap_held":
                def held_bootstrap():
                    # Executed by the acquired native thread before ident assignment.
                    # Calling current_thread here would create a DummyThread artifact.
                    row.update(native_acquired=True, native_id=threading.get_native_id(),
                               native_ident=threading.get_ident(), native_thread_object_id=id(worker))
                    self.native_acquired.set()
                    try:
                        if not self.bootstrap_release.wait(20):
                            self.barrier_failures.append("Native bootstrap release barrier timed out")
                    finally:
                        # Even a failed experiment must bootstrap the exact acquired
                        # object so that its actual started event and exit are observable.
                        original_bootstrap()

                def failed_start_wait(*_args, **_kwargs):
                    if not self.native_acquired.wait(8):
                        self.barrier_failures.append("Native acquisition barrier timed out")
                        raise StartupBarrierError("No native acquisition confirmation")
                    row["intended_error_raised"] = True
                    raise self.failure_class(self.cause)

                self.set_attr(self.fault_patch, worker, "_bootstrap_inner", held_bootstrap)
                self.set_attr(self.fault_patch, worker._started, "wait", failed_start_wait)

            def failing_start():
                if self.mode == "unresolved_start":
                    # Test-only absence proof: original native start is never called.
                    # The product has no equivalent observation and must retain ownership.
                    row["intended_error_raised"] = True
                    raise self.failure_class(self.cause)
                row["original_start_invoked"] = True
                try:
                    original_start()
                except Exception:
                    if not row["intended_error_raised"]:
                        self.barrier_failures.append("Original Thread.start raised an unintended exception")
                    raise
                if self.mode == "after_sdk_start":
                    row.update(native_acquired=True, native_id=worker.native_id,
                               native_ident=worker.ident, native_thread_object_id=id(worker))
                    if not flow._authorization_ready.wait(8) or not self.owner.operations("registration"):
                        self.barrier_failures.append("Actual SDK authorization publication was not observed")
                        raise StartupBarrierError("Actual SDK startup barrier failed")
                    row["intended_error_raised"] = True
                    raise self.failure_class(self.cause)

            self.set_attr(self.fault_patch, worker, "start", failing_start)
            return worker

        # Module-local proxy: every other subsystem retains original Thread APIs.
        self.set_attr(self.fault_patch, sessions, "threading", SimpleNamespace(Thread=factory))

    def set_attr(self, patch, obj, name, value):
        try:
            patch.setattr(obj, name, value)
        except BaseException:
            self.barrier_failures.append("Owned startup seam installation failed")
            try:
                self.fault_patch.undo()
            finally:
                self.trace_patch.undo()
            raise

    def remove_fault(self):
        if not self.removed:
            self.fault_patch.undo()
            self.removed = True

    def release_and_finish(self, flow, worker):
        self.bootstrap_release.set()
        self.cleanup_release.set()
        self.remove_fault()
        assert worker._started.wait(12), "Actual captured worker did not bootstrap"
        settled(flow, worker, self.loops)

    def capture_retry(self, flow, worker):
        self.rows.append({"flow": flow, "thread": worker, "original_start_invoked": True,
                          "native_acquired": True, "native_id": worker.native_id,
                          "native_ident": worker.ident, "native_thread_object_id": id(worker),
                          "intended_error_raised": False})

    def finish(self, record_property):
        from tools import mcp_tool as core

        first_error = sys.exception()
        failures = list(self.barrier_failures)

        def attempt(label, action):
            try:
                action()
            except BaseException as error:
                failures.append(label + ": " + repr(error))

        # Release every captured barrier before any wait/join, even on original RED.
        self.owner.token_release.set()
        self.bootstrap_release.set()
        self.cleanup_release.set()
        attempt("fault_seams_restore", self.remove_fault)
        for index, row in enumerate(self.rows):
            flow, worker = row["flow"], row["thread"]
            attempt("flow_release", lambda flow=flow, index=index: flow.mark_error(self.cause if index == 0 else "Owned retry cleanup"))
            if worker is not None and row["original_start_invoked"]:
                def joined(worker=worker):
                    assert worker._started.wait(12), "Acquired worker start is unconfirmed"
                    worker.join(timeout=12)
                    assert not worker.is_alive(), "Captured real worker did not exit"
                attempt("captured_worker_exit", joined)
                attempt("captured_flow_done", lambda flow=flow: self.require_done(flow))
            # No Thread object, or explicitly no original start invocation, is
            # recorded separately; no join/is_alive inference qualifies absence.
        attempt("owned_core_shutdown", core.shutdown_mcp_servers)
        for loop, thread in self.loops:
            attempt("captured_loop_closed", lambda loop=loop: closed(loop))
            def loop_exit(thread=thread):
                thread.join(timeout=3)
                assert not thread.is_alive()
            attempt("captured_loop_thread_exit", loop_exit)
        attempt("trace_seam_restore", self.trace_patch.undo)
        failures.extend(error for error in self.barrier_failures if error not in failures)
        attempt("native_observations_recording", lambda: record_property("startup_native_observations", json.dumps({
            "mode": self.mode, "intended_cause": self.cause,
            "barrier_failures": self.barrier_failures,
            "rows": [{**{key: value for key, value in row.items() if key not in {"flow", "thread"}},
                      "flow_id": row["flow"].flow_id, "snapshot": row["flow"].snapshot(),
                      "worker_done": row["flow"].worker_done,
                      "worker_alive": row["thread"].is_alive() if row["thread"] is not None and row["original_start_invoked"] and row["thread"]._started.is_set() else None}
                     for row in self.rows],
            "probe_loops": [{"closed": loop.is_closed(), "thread_alive": thread.is_alive()} for loop, thread in self.loops],
            "sdk_ledger": self.owner.ledger,
        })))
        attempt("captured_cleanup_recording", lambda: record_property("captured_owner_cleanup", json.dumps({
            "completed": not failures, "failures": list(failures),
        })))
        if failures:
            if first_error is not None:
                first_error.add_note("Captured startup cleanup failed: " + repr(failures))
            else:
                raise AssertionError(failures)

    @staticmethod
    def require_done(flow):
        assert flow.worker_done, flow.snapshot()


def startup_error_id(response, captured):
    assert "result" not in response and response["error"]["code"] == 5024, response
    assert response["error"]["message"] == captured.cause, response
    data = response["error"].get("data")
    # Only these three typed public fields supply the subsequent caller ID; extra metadata is ignored.
    assert isinstance(data, dict) and data.get("kind") == "mcp_oauth_startup_failure", response
    assert data.get("server_name") == "reports", response
    sid = data.get("session_id")
    assert isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9_-]+", sid), response
    assert sid == captured.rows[0]["flow"].flow_id, response
    return sid


def legitimate_retry(owner, root, captured, record_property):
    from hermes_cli.mcp_config import _get_mcp_servers

    before = set(threading.enumerate())
    response = raw_rpc("start")
    record_property("retry_public_response", json.dumps(response))
    assert "error" not in response and response["result"]["ok"], response
    data = response["result"]
    rec = sessions._sessions[data["session_id"]]
    workers = [thread for thread in threading.enumerate() if thread not in before and thread.name == "mcp-oauth-reports"]
    listeners = [thread for thread in threading.enumerate() if thread not in before and thread.name == "mcp-oauth-cb-reports"]
    assert len(workers) == len(listeners) == 1
    captured.capture_retry(rec["flow"], workers[0])
    port = rec["httpd"].server_address[1]
    deliver(owner, data, "match")
    finish(rec, workers[0], listeners[0], port)
    assert raw_rpc("poll", session_id=data["session_id"])["result"]["status"] == "approved"
    assert json.loads((root / "profiles/work/mcp-tokens/reports.json").read_text(encoding="utf-8"))["access_token"] == owner.token
    assert len(owner.operations("token_redemption")) == 1
    with scoped(root / "profiles/work"):
        cfg = _get_mcp_servers()["reports"]
        assert cfg["url"] == owner.mcp_url and cfg["auth"] == "oauth"
    nonce = "gateway-startup-retry-" + captured.mode
    registry_effect(owner, root / "profiles/work", nonce)
    assert [row["nonce"] for row in owner.operations("sentinel")] == [nonce]
    assert not (root / "profiles/other/mcp-tokens/reports.json").exists()


@pytest.mark.parametrize("mode", ["constructor", "bootstrap_held", "after_sdk_start", "unresolved_start"])
def test_gateway_startup_public_error_ownership_and_actual_recovery(homes, monkeypatch, mode, record_property):
    with serve_issuer() as owner:
        with manual_gateway(owner, homes, record_property) as loops:
            foreign_config = (homes / "profiles/other/config.yaml").read_bytes()
            captured = GatewayStartupOwner(mode, owner, loops, monkeypatch)
            try:
                response = raw_rpc("start", client_redirect_uri=owner.base + "/callback")
                record_property("startup_public_response", json.dumps(response))
                assert len(captured.rows) == 1 and captured.rows[0]["intended_error_raised"]
                assert not captured.barrier_failures, captured.barrier_failures
                row = captured.rows[0]
                flow, worker = row["flow"], row["thread"]
                record_property("startup_before_cleanup", json.dumps({
                    **{key: value for key, value in row.items() if key not in {"flow", "thread"}},
                    "flow_id": flow.flow_id, "snapshot": flow.snapshot(), "worker_done": flow.worker_done,
                    "object_id": id(worker) if worker is not None else None,
                    "thread_ident": worker.ident if worker is not None else None,
                    "actual_started_event": worker._started.is_set() if worker is not None else None,
                    "bootstrap_released": captured.bootstrap_release.is_set(),
                    "sdk_cleanup_hold_entered": captured.cleanup_entered.is_set(),
                    "gateway_listener_present": any(rec.get("httpd") is not None for rec in sessions._sessions.values()),
                }))
                sid = startup_error_id(response, captured)
                assert sessions._sessions[sid]["httpd"] is None
                status = raw_rpc("poll", session_id=sid)["result"]
                assert status["session_id"] == sid and status["status"] == "error" and status["error_message"] == captured.cause
                if mode == "after_sdk_start":
                    assert status["auth_url"] == flow.authorization_url and flow.authorization_url
                    assert captured.cleanup_entered.wait(8), "Actual failed probe did not enter cleanup hold"
                else:
                    assert status["auth_url"] is None
                foreign = raw_rpc("poll", profile="other", session_id=sid)["result"]
                assert "session_id" not in foreign and "auth_url" not in foreign and foreign["status"] == "error"
                assert not raw_rpc("cancel", profile="other", session_id=sid)["result"]["ok"]
                foreign_callback = raw_rpc("callback", profile="other", session_id=sid, code="owned-rejected", state="owned-rejected")["result"]
                assert not foreign_callback["ok"] and foreign_callback["error_message"] == foreign["error_message"]
                assert "session_id" not in foreign_callback
                wrong_server = raw_rpc("poll", name="wrong-server", session_id=sid)["result"]
                assert "session_id" not in wrong_server and "auth_url" not in wrong_server
                assert not raw_rpc("cancel", name="wrong-server", session_id=sid)["result"]["ok"]
                wrong_callback = raw_rpc("callback", name="wrong-server", session_id=sid, code="owned-rejected", state="owned-rejected")["result"]
                assert not wrong_callback["ok"] and wrong_callback["error_message"] == wrong_server["error_message"]
                assert "session_id" not in wrong_callback
                assert not owner.operations("token_request") and not owner.operations("sentinel")
                assert not (homes / "profiles/work/mcp-tokens/reports.json").exists()
                if mode == "constructor":
                    assert worker is None and flow.worker_done
                    assert not owner.operations("registration") and not owner.operations("get")
                    captured.remove_fault()
                else:
                    assert not flow.worker_done
                    if mode == "bootstrap_held":
                        assert row["native_acquired"] and row["native_id"] and row["native_thread_object_id"] == id(worker)
                        assert worker.ident is None and not captured.bootstrap_release.is_set()
                        assert not owner.operations("registration")
                    elif mode == "after_sdk_start":
                        assert row["native_acquired"] and worker.is_alive() and owner.operations("registration")
                    else:
                        assert not row["original_start_invoked"] and not row["native_acquired"]
                    rec = sessions._sessions[sid]
                    created = rec["created_at"]
                    rec["created_at"] = time.time() - sessions._SESSION_TTL_SECONDS - 1
                    sessions._gc_sessions()
                    retained = raw_rpc("poll", session_id=sid)["result"]
                    assert retained["session_id"] == sid and retained["error_message"] == captured.cause
                    assert sessions._sessions[sid] is rec and not flow.worker_done
                    registrations = len(owner.operations("registration"))
                    duplicate = raw_rpc("start", client_redirect_uri=owner.base + "/callback")
                    record_property("unfinished_duplicate_response", json.dumps(duplicate))
                    assert duplicate.get("error", {}).get("code") == 5024 and "already in progress" in duplicate["error"]["message"]
                    assert "data" not in duplicate["error"]
                    assert len(owner.operations("registration")) == registrations and not flow.worker_done
                    rec["created_at"] = created
                    if mode == "unresolved_start":
                        assert raw_rpc("cancel", session_id=sid)["result"]["ok"]
                        assert not flow.worker_done
                        duplicate = raw_rpc("start", client_redirect_uri=owner.base + "/callback")
                        assert duplicate.get("error", {}).get("code") == 5024 and "data" not in duplicate["error"]
                        assert not owner.operations("registration") and not owner.operations("get")
                    else:
                        captured.release_and_finish(flow, worker)
                        assert raw_rpc("poll", session_id=sid)["result"]["error_message"] == captured.cause
                        assert not (homes / "profiles/work/mcp-tokens/reports.json").exists()
                        assert not owner.operations("token_request") and not owner.operations("sentinel")
                if mode != "unresolved_start":
                    legitimate_retry(owner, homes, captured, record_property)
                assert (homes / "profiles/other/config.yaml").read_bytes() == foreign_config
                assert flow.snapshot()["status"] == "error" and flow.snapshot()["error"] == captured.cause
            finally:
                captured.finish(record_property)


def test_reserved_value_error_retains_typed_startup_identity(homes, monkeypatch, record_property):
    with serve_issuer() as owner:
        with manual_gateway(owner, homes, record_property) as loops:
            captured = GatewayStartupOwner("constructor", owner, loops, monkeypatch, failure_class=ValueError)
            try:
                response = raw_rpc("start", client_redirect_uri=owner.base + "/callback")
                record_property("reserved_value_error_response", json.dumps(response))
                sid = startup_error_id(response, captured)
                assert captured.rows[0]["thread"] is None and captured.rows[0]["flow"].worker_done
                assert raw_rpc("poll", session_id=sid)["result"]["error_message"] == captured.cause
                assert not owner.ledger
            finally:
                captured.finish(record_property)


@pytest.mark.parametrize("kind,code", [("invalid_redirect", 4001), ("missing_name", 4063), ("missing_server", 4064), ("missing_profile", 4064), ("stdio_config", 4001), ("header_config", 4001), ("deadline", 5024)])
def test_pre_reservation_errors_do_not_invent_startup_identity(homes, monkeypatch, kind, code, record_property):
    with serve_issuer() as owner:
        with manual_gateway(owner, homes, record_property):
            from tools import mcp_dashboard_oauth as dashboard

            constructions = {"flow": 0, "worker": 0, "listener": 0}
            original_thread = threading.Thread
            original_flow = dashboard.DashboardOAuthFlow

            def observed_thread(*args, **kwargs):
                if kwargs.get("name") == "mcp-oauth-reports":
                    constructions["worker"] += 1
                elif kwargs.get("name") == "mcp-oauth-cb-reports":
                    constructions["listener"] += 1
                return original_thread(*args, **kwargs)

            def observed_flow(*args, **kwargs):
                constructions["flow"] += 1
                return original_flow(*args, **kwargs)

            monkeypatch.setattr(sessions, "threading", SimpleNamespace(Thread=observed_thread))
            monkeypatch.setattr(dashboard, "DashboardOAuthFlow", observed_flow)
            params = {"client_redirect_uri": owner.base + "/callback"}
            if kind == "invalid_redirect":
                params["client_redirect_uri"] = "https://127.0.0.1:12345/callback"
            elif kind == "missing_name":
                params["name"] = ""
            elif kind == "missing_server":
                params["name"] = "owned-missing-server"
            elif kind == "missing_profile":
                params["profile"] = "owned-missing-profile"
            elif kind in {"stdio_config", "header_config"}:
                from hermes_cli.mcp_config import _replace_mcp_servers

                cfg = ({"command": sys.executable, "args": ["-c", "pass"]}
                       if kind == "stdio_config" else
                       {"url": owner.mcp_url, "transport": "http", "headers": {"X-Owned-Auth": "owned-test-key"}})
                with scoped(homes / "profiles/work"):
                    ok, issues = _replace_mcp_servers({"reports": cfg})
                    assert ok and not issues, issues
            elif kind == "deadline":
                original_start = sessions.start_flow
                def expired_start(*args, **kwargs):
                    return original_start(*args, **kwargs, url_timeout=0)
                monkeypatch.setattr(sessions, "start_flow", expired_start)
            response = raw_rpc("start", **params)
            record_property("pre_reservation_response", json.dumps(response))
            record_property("pre_reservation_observations", json.dumps({
                "reserved_sessions": len(sessions._sessions), "sdk_ledger": list(owner.ledger),
                "case": kind, "constructions": dict(constructions),
            }))
            assert response.get("error", {}).get("code") == code, response
            assert "data" not in response["error"] and not sessions._sessions
            assert constructions == {"flow": 0, "worker": 0, "listener": 0}
            assert not owner.ledger
