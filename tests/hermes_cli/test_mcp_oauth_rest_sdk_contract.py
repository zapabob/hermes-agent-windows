"""Authenticated REST ownership and cookie-free callback with the actual SDK."""

import json
import threading
from contextlib import contextmanager
from urllib.parse import urlencode

import pytest
from starlette.testclient import TestClient

from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.fakes.mcp_oauth_gateway import closed, homes as homes, registry_effect, scoped


@contextmanager
def without_dashboard_cookie(client):
    saved = dict(client.cookies)
    client.cookies.clear()
    try:
        yield
    finally:
        client.cookies.update(saved)


@contextmanager
def running_rest(owner, root, monkeypatch, *, manual_start=False, raise_server_exceptions=True):
    from hermes_cli import web_server
    from hermes_cli.mcp_config import _replace_mcp_servers
    from tools import mcp_tool as core
    from hermes_constants import hermes_home_key
    from hermes_cli.dashboard_auth.cookies import SESSION_AT_COOKIE, SESSION_PROVIDER_COOKIE
    from hermes_cli.dashboard_auth.registry import register_provider, restore_registration, snapshot_registration
    from tests.hermes_cli.test_dashboard_auth_password_login import PasswordProvider

    assert not web_server._mcp_oauth_flows
    monkeypatch.setattr(web_server.app.state, "auth_required", True, raising=False)
    for profile in ("work", "other"):
        with scoped(root / "profiles" / profile):
            ok, issues = _replace_mcp_servers({"reports": {"url": owner.mcp_url, "transport": "http", "auth": "oauth", "oauth": {"cimd": False}, "timeout": 5}})
            assert ok and not issues
    client = None
    before = set(threading.enumerate())
    threads = set()
    loops = []
    auth_provider = PasswordProvider()
    auth_scope = hermes_home_key(root)
    previous_provider = snapshot_registration(auth_provider.name, scope=auth_scope)
    assert previous_provider is None
    registered = False
    try:
        register_provider(auth_provider, scope=auth_scope)
        registered = True
        client = TestClient(web_server.app, base_url="http://127.0.0.1:18888", raise_server_exceptions=raise_server_exceptions)
        assert client.post("/api/mcp/servers/reports/auth?profile=work").status_code == 401
        # Existing signed in-memory identity-provider fixture; the real gate
        # verifies the cookie. No public login/provider integration is claimed.
        signed = auth_provider.complete_password_login(username="admin", password="hunter2")
        client.cookies.set(SESSION_AT_COOKIE, signed.access_token)
        client.cookies.set(SESSION_PROVIDER_COOKIE, auth_provider.name)
        if manual_start:
            yield client, None, None, None, loops
            return
        started = client.post("/api/mcp/servers/reports/auth?profile=work")
        assert started.status_code == 200, started.text
        data = started.json()
        flow = web_server._mcp_oauth_flows[data["flow_id"]]
        actual = [thread for thread in threading.enumerate() if thread not in before and thread.name == "mcp-oauth-reports"]
        threads.update(actual)
        assert len(actual) == 1
        if core._mcp_loop is not None:
            loops.append((core._mcp_loop, core._mcp_thread))
        assert owner.operations("registration") and owner.operations("get")
        with without_dashboard_cookie(client):
            status_url = f"/api/mcp/oauth/flows/{flow.flow_id}?profile=work"
            assert client.get(status_url).status_code == 401
            assert client.delete(status_url).status_code == 401
            assert actual[0].is_alive() and not flow._callback_ready.is_set()
        yield client, data, flow, actual[0], loops
    finally:
        errors = []

        def attempt(label, action):
            try:
                action()
            except BaseException as error:
                errors.append(label + ": " + repr(error))

        def joined(thread):
            thread.join(timeout=12)
            assert not thread.is_alive()

        owner.token_release.set()
        threads.update(thread for thread in threading.enumerate() if thread not in before and thread.name == "mcp-oauth-reports")
        for flow in web_server._mcp_oauth_flows.values():
            attempt("flow_release", lambda flow=flow: flow.mark_error("Owned REST fixture cleanup"))
        for thread in threads:
            attempt("worker_exit", lambda thread=thread: joined(thread))
        if core._mcp_loop is not None:
            loops.append((core._mcp_loop, core._mcp_thread))
        attempt("mcp_shutdown", core.shutdown_mcp_servers)
        for loop, thread in loops:
            attempt("loop_closed", lambda loop=loop: closed(loop))
            attempt("loop_thread_exit", lambda thread=thread: joined(thread))
        if client is not None:
            attempt("client_close", client.close)
        if registered:
            def restore_auth():
                assert restore_registration(auth_provider.name, auth_provider, previous_provider, scope=auth_scope)
                assert snapshot_registration(auth_provider.name, scope=auth_scope) is previous_provider
            attempt("owned_auth_provider_restore", restore_auth)
        web_server._mcp_oauth_flows.clear()
        assert not errors, errors


def callback(owner, data, client, mode="match"):
    code, state, _ = owner.issue_code(data["authorization_url"])
    params = {"code": code, "state": state, "iss": owner.issuer if mode == "match" else "", "profile": "other"}
    with without_dashboard_cookie(client):
        result = client.get("/api/mcp/oauth/callback/reports?" + urlencode(params))
        assert result.status_code == 200, result.text


def settled(flow, worker, loops):
    assert flow._worker_done.wait(12), flow.snapshot()
    worker.join(timeout=3)
    assert not worker.is_alive()
    for loop, thread in loops:
        closed(loop)
        assert not thread.is_alive()


@pytest.mark.parametrize("mode,allowed", [("match", True), ("empty", False)])
def test_rest_callback_actual_sdk_token_and_effect(homes, monkeypatch, mode, allowed):
    with serve_issuer(required=False) as owner:
        with running_rest(owner, homes, monkeypatch) as (client, data, flow, worker, loops):
            callback(owner, data, client, mode)
            settled(flow, worker, loops)
            status = client.get(f"/api/mcp/oauth/flows/{flow.flow_id}?profile=work")
            assert status.status_code == 200
            assert status.json()["status"] == ("approved" if allowed else "error")
            token = homes / "profiles" / "work" / "mcp-tokens" / "reports.json"
            if allowed:
                assert json.loads(token.read_text(encoding="utf-8"))["access_token"] == owner.token
                assert len(owner.operations("token_redemption")) == 1
                registry_effect(owner, homes / "profiles" / "work", "rest-owned-effect")
            else:
                assert not token.exists()
                assert owner.operations("token_request") == []
                assert owner.operations("sentinel") == []
            assert not (homes / "profiles" / "other" / "mcp-tokens" / "reports.json").exists()


def test_rest_foreign_status_and_cancel_leave_actual_worker_usable(homes, monkeypatch):
    with serve_issuer() as owner:
        with running_rest(owner, homes, monkeypatch) as (client, data, flow, worker, loops):
            url = f"/api/mcp/oauth/flows/{flow.flow_id}?profile=other"
            assert client.get(url).status_code == 404
            assert client.delete(url).status_code == 404
            assert worker.is_alive() and not flow._callback_ready.is_set()
            callback(owner, data, client)
            settled(flow, worker, loops)
            assert flow.snapshot()["status"] == "approved"
            registry_effect(owner, homes / "profiles" / "work", "rest-after-foreign-cancel")


def test_rest_cancel_during_token_response_hold_preserves_admitted_success(homes, monkeypatch):
    with serve_issuer() as owner:
        owner.token_release.clear()
        with running_rest(owner, homes, monkeypatch) as (client, data, flow, worker, loops):
            try:
                callback(owner, data, client)
                assert owner.token_started.wait(5)
                assert owner.operations("token_redemption") == []
                cancelled = client.delete(f"/api/mcp/oauth/flows/{flow.flow_id}?profile=work")
                assert cancelled.status_code == 200
                assert cancelled.json()["cancelled"] is False
                assert flow.snapshot()["status"] != "error"
                assert worker.is_alive() and not flow._worker_done.is_set()
            finally:
                owner.token_release.set()
            settled(flow, worker, loops)
            assert flow.snapshot()["status"] == "approved"
            registry_effect(owner, homes / "profiles" / "work", "rest-admitted-result")
