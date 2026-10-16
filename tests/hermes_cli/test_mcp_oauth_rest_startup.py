"""Unexecuted REST startup oracle; real native allocation and actual MCP SDK."""
import json
import sys
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tests.fakes.mcp_oauth_gateway import closed, homes as homes, registry_effect, scoped
from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.hermes_cli.test_mcp_oauth_rest_sdk_contract import (
    callback,
    running_rest,
    settled,
    without_dashboard_cookie,
)


class StartupBarrierError(RuntimeError):
    """Invalid experiment, distinct from the deliberately raised startup cause."""


@contextmanager
def manual_rest(owner, root, monkeypatch, record_property):
    manager = running_rest(owner, root, monkeypatch, manual_start=True, raise_server_exceptions=False)
    try:
        values = manager.__enter__()
    except BaseException as error:
        record_property("rest_fixture_cleanup", json.dumps({"completed": False, "failures": [repr(error)]}))
        raise
    body_error = body_traceback = cleanup_error = None
    try:
        yield values[0], values[4]
    except BaseException as error:
        body_error, body_traceback = error, error.__traceback__
    finally:
        try:
            manager.__exit__(type(body_error) if body_error else None, body_error, body_traceback)
        except BaseException as error:
            cleanup_error = error
        record_property("rest_fixture_cleanup", json.dumps({
            "completed": cleanup_error is None,
            "failures": [] if cleanup_error is None else [repr(cleanup_error)],
        }))
    if body_error is not None:
        if cleanup_error is not None:
            body_error.add_note("Owned REST fixture cleanup failed: " + repr(cleanup_error))
        raise body_error.with_traceback(body_traceback)
    if cleanup_error is not None:
        raise cleanup_error


class StartupOwner:
    """Capture the exact router worker without patching global Thread/Event APIs."""

    def __init__(self, mode, owner, loops, monkeypatch):
        from hermes_cli import mcp_config
        from hermes_cli.web_routers import mcp as router
        from tools import mcp_tool as core

        self.mode = mode
        self.owner = owner
        self.loops = loops
        self.cause = "Owned REST startup failure: " + mode
        self.rows = []
        self.barrier_failures = []
        self.native_acquired = threading.Event()
        self.bootstrap_release = threading.Event()
        self.cleanup_entered = threading.Event()
        self.cleanup_release = threading.Event()
        self.fault_patch = pytest.MonkeyPatch()
        self.trace_patch = pytest.MonkeyPatch()
        self.removed = False
        self.original_target = router._run_dashboard_mcp_oauth
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
                row = {"flow": kwargs["args"][0], "thread": worker,
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
            flow = kwargs["args"][0]
            row = {"flow": flow, "thread": None, "original_start_invoked": False,
                   "native_acquired": False, "native_id": None, "native_ident": None,
                   "native_thread_object_id": None, "intended_error_raised": False}
            self.rows.append(row)
            if self.mode == "constructor":
                row["intended_error_raised"] = True
                raise RuntimeError(self.cause)
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
                    raise RuntimeError(self.cause)

                self.set_attr(self.fault_patch, worker, "_bootstrap_inner", held_bootstrap)
                self.set_attr(self.fault_patch, worker._started, "wait", failed_start_wait)

            def failing_start():
                if self.mode == "unresolved_start":
                    # Test-only absence proof: original native start is never called.
                    # The product has no equivalent observation and must retain ownership.
                    row["intended_error_raised"] = True
                    raise RuntimeError(self.cause)
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
                    raise RuntimeError(self.cause)

            self.set_attr(self.fault_patch, worker, "start", failing_start)
            return worker

        # Module-local proxy: every other subsystem retains original Thread APIs.
        self.set_attr(self.fault_patch, router, "threading", SimpleNamespace(Thread=factory))

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
        record_property("captured_owner_cleanup", json.dumps({"completed": not failures, "failures": failures}))
        record_property("startup_native_observations", json.dumps({
            "mode": self.mode, "intended_cause": self.cause,
            "barrier_failures": self.barrier_failures,
            "rows": [{**{key: value for key, value in row.items() if key not in {"flow", "thread"}},
                      "flow_id": row["flow"].flow_id, "snapshot": row["flow"].snapshot(),
                      "worker_done": row["flow"].worker_done,
                      "worker_alive": row["thread"].is_alive() if row["thread"] is not None and row["original_start_invoked"] and row["thread"]._started.is_set() else None}
                     for row in self.rows],
            "probe_loops": [{"closed": loop.is_closed(), "thread_alive": thread.is_alive()} for loop, thread in self.loops],
            "sdk_ledger": self.owner.ledger,
        }))
        if failures:
            if first_error is not None:
                first_error.add_note("Captured startup cleanup failed: " + repr(failures))
            else:
                raise AssertionError(failures)

    @staticmethod
    def require_done(flow):
        assert flow.worker_done, flow.snapshot()


def legitimate_retry(client, owner, homes, captured, record_property):
    from hermes_cli import web_server
    from hermes_cli.mcp_config import _get_mcp_servers

    before = set(threading.enumerate())
    started = client.post("/api/mcp/servers/reports/auth?profile=work")
    record_property("retry_http_status", started.status_code)
    assert started.status_code == 200, started.text
    data = started.json()
    assert data["status"] == "authorization_required", data
    flow = web_server._mcp_oauth_flows[data["flow_id"]]
    workers = [thread for thread in threading.enumerate() if thread not in before and thread.name == "mcp-oauth-reports"]
    assert len(workers) == 1
    worker = workers[0]
    captured.capture_retry(flow, worker)
    callback(owner, data, client)
    settled(flow, worker, captured.loops)
    assert client.get(f"/api/mcp/oauth/flows/{flow.flow_id}?profile=work").json()["status"] == "approved"
    token = homes / "profiles/work/mcp-tokens/reports.json"
    assert json.loads(token.read_text(encoding="utf-8"))["access_token"] == owner.token
    assert len(owner.operations("token_redemption")) == 1
    with scoped(homes / "profiles/work"):
        cfg = _get_mcp_servers()["reports"]
        assert cfg["url"] == owner.mcp_url and cfg["auth"] == "oauth"
    nonce = "rest-startup-retry-" + captured.mode
    registry_effect(owner, homes / "profiles/work", nonce)
    assert [row["nonce"] for row in owner.operations("sentinel")] == [nonce]
    assert not (homes / "profiles/other/mcp-tokens/reports.json").exists()


@pytest.mark.parametrize("mode", ["constructor", "bootstrap_held", "after_sdk_start", "unresolved_start"])
def test_rest_startup_public_error_ownership_and_actual_recovery(homes, monkeypatch, mode, record_property):
    from hermes_cli import web_server

    with serve_issuer() as owner:
        with manual_rest(owner, homes, monkeypatch, record_property) as (client, loops):
            foreign_config = (homes / "profiles/other/config.yaml").read_bytes()
            captured = StartupOwner(mode, owner, loops, monkeypatch)
            try:
                started = client.post("/api/mcp/servers/reports/auth?profile=work")
                record_property("startup_http_status", started.status_code)
                record_property("startup_http_body", started.text)
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
                }))
                # Original product's actual public500 is the intended RED here.
                assert started.status_code == 200, started.text
                data = started.json()
                assert data["flow_id"] == flow.flow_id and data["server_name"] == "reports"
                assert data["status"] == "error" and data["error"] == captured.cause
                if mode != "after_sdk_start":
                    assert data["authorization_url"] is None
                else:
                    assert data["authorization_url"] == flow.authorization_url and flow.authorization_url
                    assert captured.cleanup_entered.wait(8), "Actual failed probe did not enter cleanup hold"
                url = f"/api/mcp/oauth/flows/{data['flow_id']}?profile=work"
                with without_dashboard_cookie(client):
                    assert client.get(url).status_code == 401
                    assert client.delete(url).status_code == 401
                foreign = url.replace("profile=work", "profile=other")
                assert client.get(foreign).status_code == 404
                assert client.delete(foreign).status_code == 404
                status = client.get(url)
                assert status.status_code == 200
                assert status.json()["flow_id"] == data["flow_id"] and status.json()["error"] == captured.cause
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
                    created = flow.created_at
                    flow.created_at = time.time() - web_server._MCP_DASHBOARD_OAUTH_TTL - 1
                    retained = client.get(url)
                    assert retained.status_code == 200 and retained.json()["error"] == captured.cause
                    assert web_server._mcp_oauth_flows[data["flow_id"]] is flow
                    record_property("retained_before_duplicate", json.dumps({
                        "status_code": retained.status_code, "snapshot": retained.json(),
                        "worker_done": flow.worker_done, "native_acquired": row["native_acquired"],
                        "native_id": row["native_id"], "actual_started_event": worker._started.is_set(),
                        "bootstrap_released": captured.bootstrap_release.is_set(),
                        "sdk_cleanup_hold_entered": captured.cleanup_entered.is_set(),
                    }))
                    registrations = len(owner.operations("registration"))
                    duplicate = client.post("/api/mcp/servers/reports/auth?profile=work")
                    assert duplicate.status_code == 409, duplicate.text
                    assert len(owner.operations("registration")) == registrations and not flow.worker_done
                    flow.created_at = created
                    if mode == "unresolved_start":
                        cancelled = client.delete(url)
                        assert cancelled.status_code == 200 and cancelled.json()["status"] == "error"
                        assert not flow.worker_done and client.post("/api/mcp/servers/reports/auth?profile=work").status_code == 409
                        assert not owner.operations("registration") and not owner.operations("get")
                    else:
                        captured.release_and_finish(flow, worker)
                        assert client.get(url).json()["error"] == captured.cause
                        assert not (homes / "profiles/work/mcp-tokens/reports.json").exists()
                        assert not owner.operations("token_request") and not owner.operations("sentinel")
                if mode != "unresolved_start":
                    legitimate_retry(client, owner, homes, captured, record_property)
                assert (homes / "profiles/other/config.yaml").read_bytes() == foreign_config
                assert flow.snapshot()["status"] == "error" and flow.snapshot()["error"] == captured.cause
            finally:
                captured.finish(record_property)
