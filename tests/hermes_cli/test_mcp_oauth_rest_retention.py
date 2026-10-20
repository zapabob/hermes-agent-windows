"""Real SDK REST ownership across expiry and observed worker cleanup."""
import asyncio
import json
import sys
import threading
import time
from contextlib import contextmanager

import pytest

from tests.fakes.mcp_oauth_gateway import homes as homes, registry_effect
from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.hermes_cli.test_mcp_oauth_rest_sdk_contract import (
    callback,
    running_rest,
    settled,
    without_dashboard_cookie,
)


@contextmanager
def preserved_rest(owner, root, monkeypatch, record_property):
    """Keep the body exception across the complete existing fixture cleanup."""
    manager = running_rest(owner, root, monkeypatch)
    try:
        values = manager.__enter__()
    except BaseException as setup_error:
        record_property("rest_fixture_cleanup", json.dumps({
            "completed": False,
            "failures": ["Fixture setup did not yield: " + repr(setup_error)],
        }))
        raise
    body_error = None
    body_traceback = None
    cleanup_error = None
    try:
        yield values
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


def finish_captured(flow, worker, owner, loops, record_property):
    """Release the captured owner even if a broken registry forgot it."""
    original_error = sys.exception()
    failures = []
    try:
        owner.token_release.set()
        flow.mark_error("Owned REST expiry oracle cleanup")
        settled(flow, worker, loops)
    except BaseException as cleanup_error:
        failures.append(repr(cleanup_error))
        record_property("owned_cleanup_error", repr(cleanup_error))
        if original_error is None:
            raise
        original_error.add_note("Owned REST cleanup failed: " + repr(cleanup_error))
    finally:
        record_property("captured_owner_cleanup", json.dumps({"completed": not failures, "failures": failures}))
        with owner.lock:
            ledger = [
                {key: value for key, value in row.items() if key in {"operation", "path", "nonce"}}
                for row in owner.ledger
            ]
        record_property("owned_sdk_observations", json.dumps({
            "ledger": ledger,
            "worker_done": flow.worker_done,
            "worker_alive": worker.is_alive(),
            "probe_loops": [{"closed": loop.is_closed(), "thread_alive": thread.is_alive()} for loop, thread in loops],
        }))


@pytest.mark.parametrize("stage", ["authorization_wait", "token_response_hold"])
def test_rest_expiry_retains_active_owner_until_real_cleanup(homes, monkeypatch, stage, record_property):
    from hermes_cli import web_server

    with serve_issuer() as owner:
        if stage == "token_response_hold":
            owner.token_release.clear()
        with preserved_rest(owner, homes, monkeypatch, record_property) as (client, data, flow, worker, loops):
            try:
                if stage == "token_response_hold":
                    callback(owner, data, client)
                    assert owner.token_started.wait(5)
                    assert not owner.operations("token_redemption")
                assert worker.is_alive() and not flow.worker_done
                flow.created_at = time.time() - web_server._MCP_DASHBOARD_OAUTH_TTL - 1
                status_url = f"/api/mcp/oauth/flows/{flow.flow_id}?profile=work"
                with without_dashboard_cookie(client):
                    assert client.get(status_url).status_code == 401
                assert client.get(status_url.replace("profile=work", "profile=other")).status_code == 404
                status = client.get(status_url)
                assert status.status_code == 200, status.text
                assert web_server._mcp_oauth_flows[flow.flow_id] is flow
                assert worker.is_alive() and not flow.worker_done
                registrations = len(owner.operations("registration"))
                duplicate = client.post("/api/mcp/servers/reports/auth?profile=work")
                assert duplicate.status_code == 409, duplicate.text
                assert len(owner.operations("registration")) == registrations
                if stage == "authorization_wait":
                    callback(owner, data, client)
                owner.token_release.set()
                settled(flow, worker, loops)
                assert flow.snapshot()["status"] == "approved"
                assert len(owner.operations("token_redemption")) == 1
                token_path = homes / "profiles/work/mcp-tokens/reports.json"
                assert json.loads(token_path.read_text(encoding="utf-8"))["access_token"] == owner.token
                assert not (homes / "profiles/other/mcp-tokens/reports.json").exists()
                registry_effect(owner, homes / "profiles/work", "rest-expiry-" + stage)
                expired = client.get(status_url)
                assert expired.status_code == 404, expired.text
                assert flow.flow_id not in web_server._mcp_oauth_flows
            finally:
                finish_captured(flow, worker, owner, loops, record_property)


@pytest.mark.parametrize("hold_retry", [False, True], ids=["normal", "retry_held"])
def test_rest_expired_cancelled_owner_collects_after_actual_cleanup(homes, monkeypatch, record_property, hold_retry):
    from hermes_cli import web_server
    from hermes_cli import mcp_config
    from tools.mcp_dashboard_oauth import get_dashboard_oauth_flow

    cleanup_entered = threading.Event()
    cleanup_release = threading.Event()
    retry_entered = threading.Event()
    retry_release = threading.Event()
    captured_flows = []
    callback_errors = []
    original_probe = mcp_config._probe_single_server

    if hold_retry:
        from tools import mcp_tool as core

        original_jittered = core._jittered

        def held_retry(seconds):
            retry_entered.set()
            assert retry_release.wait(20), "Owned retry barrier was not released"
            return original_jittered(seconds)

        monkeypatch.setattr(core, "_jittered", held_retry)

    def probe_with_callback_hold(*args, **kwargs):
        owned_flow = get_dashboard_oauth_flow()
        assert owned_flow is not None, "Actual probe has no dashboard flow owner"
        captured_flows.append(owned_flow)
        original_callback = owned_flow.wait_for_callback

        async def held_callback(*args, **kwargs):
            try:
                return await original_callback(*args, **kwargs)
            except RuntimeError as error:
                if str(error) != "OAuth authorization failed: Cancelled by user":
                    raise
                # Hold the exact owner's real cancellation before the probe
                # unwinds; explicit cancellation must not enter a retry.
                callback_errors.append(str(error))
                cleanup_entered.set()
                assert await asyncio.to_thread(cleanup_release.wait, 8), "Owned REST worker cleanup barrier was not released"
                raise

        monkeypatch.setattr(owned_flow, "wait_for_callback", held_callback)
        return original_probe(*args, **kwargs)

    monkeypatch.setattr(mcp_config, "_probe_single_server", probe_with_callback_hold)

    with serve_issuer() as owner:
        with preserved_rest(owner, homes, monkeypatch, record_property) as (client, data, flow, worker, loops):
            try:
                assert len(captured_flows) == 1 and captured_flows[0] is flow
                flow.created_at = time.time() - web_server._MCP_DASHBOARD_OAUTH_TTL - 1
                status_url = f"/api/mcp/oauth/flows/{flow.flow_id}?profile=work"
                assert client.get(status_url).status_code == 200
                cancelled = client.delete(status_url)
                assert cancelled.status_code == 200 and cancelled.json()["cancelled"] is True
                assert cleanup_entered.wait(8), "Actual callback cancellation did not enter unwind hold"
                assert callback_errors == ["OAuth authorization failed: Cancelled by user"]
                if hold_retry:
                    assert not retry_entered.is_set(), "Ownership observation ran after SDK retries"
                assert worker.is_alive() and not flow.worker_done
                retained = client.get(status_url)
                assert retained.status_code == 200, retained.text
                assert retained.json()["status"] == "error"
                assert web_server._mcp_oauth_flows[flow.flow_id] is flow
                duplicate = client.post("/api/mcp/servers/reports/auth?profile=work")
                assert duplicate.status_code == 409, duplicate.text
                assert worker.is_alive() and not flow.worker_done
                cleanup_release.set()
                retry_release.set()
                settled(flow, worker, loops)
                if hold_retry:
                    assert not retry_entered.is_set(), "Explicitly cancelled SDK connection retried"
                assert client.get(status_url).status_code == 404
                assert flow.flow_id not in web_server._mcp_oauth_flows
                assert not owner.operations("token_request") and not owner.operations("sentinel")
                assert not (homes / "profiles/work/mcp-tokens/reports.json").exists()
            finally:
                cleanup_release.set()
                retry_release.set()
                finish_captured(flow, worker, owner, loops, record_property)
                record_property("retry_schedule", json.dumps({
                    "held": hold_retry, "entered": retry_entered.is_set(),
                    "flow_id": flow.flow_id, "callback_errors": callback_errors,
                }))
