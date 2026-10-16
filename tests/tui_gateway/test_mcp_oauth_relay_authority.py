"""Fixed pre-edit public relay oracles; token/effect qualification is separate."""

import asyncio
import errno
import socket
import threading
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from hermes_constants import get_hermes_home, get_hermes_home_override
from tools.mcp_dashboard_oauth import DashboardOAuthFlow, dashboard_oauth_flow
from tools.mcp_oauth import _make_callback_waiter
from tui_gateway import mcp_oauth_sessions as sessions
from tui_gateway import server


@pytest.fixture
def owned(tmp_path, monkeypatch):
    root = tmp_path / "home"
    for name in ("work", "other"):
        (root / "profiles" / name).mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(root))
    assert get_hermes_home_override() is None
    from hermes_cli import web_server

    assert not sessions._sessions
    assert not web_server._mcp_oauth_flows
    yield root
    for rec in list(sessions._sessions.values()):
        rec["flow"].mark_error("test cleanup")
        sessions._shutdown_listener(rec)
    sessions._sessions.clear()
    web_server._mcp_oauth_flows.clear()
    assert get_hermes_home_override() is None


def flow_for(root):
    flow = DashboardOAuthFlow(
        flow_id="owned-flow", server_name="reports", profile="work",
        hermes_home=str(root / "profiles" / "work"),
        redirect_uri="http://127.0.0.1:1/callback",
    )
    asyncio.run(flow.publish_authorization_url("http://127.0.0.1:1/authorize?state=bound-state"))
    sessions._sessions[flow.flow_id] = {
        "flow": flow, "server_name": flow.server_name,
        "hermes_home": flow.hermes_home, "created_at": flow.created_at, "httpd": None,
    }
    return flow


def rpc(method, profile="work", **params):
    assert method in server._methods, f"Missing public OAuth method: {method}"
    response = server._methods[method](71, {
        "profile": profile, "name": "reports", "session_id": "owned-flow", **params,
    })
    assert get_hermes_home_override() is None
    return response.get("result", response)


def sdk_callback(flow):
    assert flow._callback_ready.is_set(), "Accepted callback must release the real waiter"
    with dashboard_oauth_flow(flow):
        return asyncio.run(_make_callback_waiter(0)())


def rest_client():
    from hermes_cli import web_server
    from starlette.testclient import TestClient

    client = TestClient(web_server.app)
    client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return client


def test_rpc_owner_positive_state_replay_and_home_restoration(owned):
    flow = flow_for(owned)
    assert rpc("mcp.servers.oauth.poll")["auth_url"] == flow.authorization_url
    assert rpc("mcp.servers.oauth.callback", code="synthetic", state="wrong")["ok"] is False
    assert not flow._callback_ready.is_set()
    assert rpc("mcp.servers.oauth.callback", code="synthetic", state="bound-state")["ok"] is True
    result = sdk_callback(flow)
    assert (result.code, result.state) == ("synthetic", "bound-state")
    assert rpc("mcp.servers.oauth.callback", code="replay", state="bound-state")["ok"] is False
    assert str(get_hermes_home()) == str(owned)


def test_rpc_foreign_poll_exposes_no_auth_url_or_tools(owned):
    flow = flow_for(owned)
    flow.tools = [{"name": "private-tool"}]
    result = rpc("mcp.servers.oauth.poll", profile="other")
    assert not result.get("auth_url"), result
    assert not result.get("tools"), result
    assert result.get("status") == "error" or "error" in result
    assert rpc("mcp.servers.oauth.poll")["auth_url"] == flow.authorization_url


def test_rpc_foreign_approved_tools_are_denied_while_owner_observes_them(owned):
    flow = flow_for(owned)
    flow.tools = [{"name": "private-tool"}]
    flow.mark_approved()
    assert rpc("mcp.servers.oauth.poll")["tools"] == flow.tools
    result = rpc("mcp.servers.oauth.poll", profile="other")
    assert not result.get("tools"), result
    assert not result.get("auth_url"), result


def test_rpc_foreign_callback_does_not_consume_owner_waiter(owned):
    flow = flow_for(owned)
    result = rpc("mcp.servers.oauth.callback", profile="other", code="foreign", state="bound-state")
    assert result.get("ok") is not True, result
    assert not flow._callback_ready.is_set()
    assert rpc("mcp.servers.oauth.callback", code="owner", state="bound-state")["ok"] is True
    assert sdk_callback(flow).code == "owner"


@pytest.mark.parametrize("issuer", ["http://issuer.invalid", "", "http://issuer.invalid/"])
def test_rpc_issuer_exactly_reaches_real_sdk_result(owned, issuer):
    flow = flow_for(owned)
    assert rpc("mcp.servers.oauth.callback", code="synthetic", state="bound-state", iss=issuer)["ok"]
    result = sdk_callback(flow)
    assert result.iss == issuer


@pytest.mark.parametrize("issuer", ["http://issuer.invalid", ""])
def test_gateway_real_loopback_issuer_reaches_sdk_result(owned, issuer):
    flow = flow_for(owned)
    before = set(threading.enumerate())
    httpd = sessions._start_loopback_listener(flow)
    listener = []
    rec = {"httpd": httpd}
    try:
        listener = [thread for thread in threading.enumerate() if thread not in before
                    and thread.name == "mcp-oauth-cb-reports"]
        assert len(listener) == 1
        port = httpd.server_address[1]
        query = urlencode({"code": "synthetic", "state": "bound-state", "iss": issuer})
        with urlopen(f"http://127.0.0.1:{port}/callback?{query}", timeout=3) as response:
            assert response.status == 200
        assert sdk_callback(flow).iss == issuer
    finally:
        sessions._shutdown_listener(rec)
        for thread in listener:
            thread.join(timeout=3)
            assert not thread.is_alive()
        with pytest.raises(ConnectionRefusedError) as refusal:
            socket.create_connection(("127.0.0.1", httpd.server_address[1]), timeout=4)
        assert refusal.value.errno == errno.ECONNREFUSED or refusal.value.winerror == 10061


def test_rest_foreign_poll_leaves_owner_usable(owned):
    from hermes_cli import web_server

    flow = flow_for(owned)
    web_server._mcp_oauth_flows[flow.flow_id] = flow
    client = rest_client()
    try:
        foreign = client.get(f"/api/mcp/oauth/flows/{flow.flow_id}?profile=other")
        assert foreign.status_code == 404, foreign.text
        assert not flow._callback_ready.is_set()
        owner = client.get(f"/api/mcp/oauth/flows/{flow.flow_id}?profile=work")
        assert owner.status_code == 200
        assert owner.json()["authorization_url"] == flow.authorization_url
    finally:
        client.close()


def test_rest_foreign_cancel_leaves_owner_callback_usable(owned):
    from hermes_cli import web_server

    flow = flow_for(owned)
    web_server._mcp_oauth_flows[flow.flow_id] = flow
    client = rest_client()
    try:
        foreign = client.delete(f"/api/mcp/oauth/flows/{flow.flow_id}?profile=other")
        assert foreign.status_code == 404, foreign.text
        assert not flow._callback_ready.is_set()
        assert rpc("mcp.servers.oauth.callback", code="owner", state="bound-state")["ok"]
        assert sdk_callback(flow).code == "owner"
    finally:
        client.close()


def test_rest_cookie_free_callback_preserves_issuer_and_rejects_replay(owned, monkeypatch):
    from hermes_cli import web_server
    from starlette.testclient import TestClient

    flow = flow_for(owned)
    web_server._mcp_oauth_flows[flow.flow_id] = flow
    monkeypatch.setattr(web_server.app.state, "auth_required", True, raising=False)
    client = TestClient(web_server.app)
    try:
        wrong = client.get("/api/mcp/oauth/callback/reports?code=x&state=wrong")
        assert wrong.status_code in (400, 404)
        assert not flow._callback_ready.is_set()
        query = urlencode({"code": "owner", "state": "bound-state", "iss": "", "profile": "other"})
        callback = client.get(f"/api/mcp/oauth/callback/reports?{query}")
        assert callback.status_code == 200, callback.text
        assert sdk_callback(flow).iss == ""
        replay = client.get(f"/api/mcp/oauth/callback/reports?{query}")
        assert replay.status_code in (400, 404, 409)
    finally:
        client.close()


def test_rpc_cancel_registered_and_foreign_cannot_cancel(owned):
    flow = flow_for(owned)
    foreign = rpc("mcp.servers.oauth.cancel", profile="other")
    assert foreign.get("ok") is not True, foreign
    assert not flow._callback_ready.is_set()
    own = rpc("mcp.servers.oauth.cancel")
    assert own["cancelled"] is True
    assert flow.snapshot()["status"] == "error"
    with pytest.raises(RuntimeError, match="Cancelled"):
        sdk_callback(flow)
    assert rpc("mcp.servers.oauth.callback", code="late", state="bound-state")["ok"] is False


def test_rest_cancel_after_callback_preserves_admitted_result(owned):
    from hermes_cli import web_server

    flow = flow_for(owned)
    web_server._mcp_oauth_flows[flow.flow_id] = flow
    assert rpc("mcp.servers.oauth.callback", code="admitted", state="bound-state")["ok"]
    client = rest_client()
    try:
        response = client.delete(f"/api/mcp/oauth/flows/{flow.flow_id}?profile=work")
        assert response.status_code == 200
        body = response.json()
        assert body.get("cancelled") is False, body
        assert body["status"] != "error", body
    finally:
        client.close()
    assert sdk_callback(flow).code == "admitted"
    flow.mark_approved()
    assert flow.snapshot()["status"] == "approved"


def test_first_failure_cause_survives_repeated_worker_errors(owned):
    flow = flow_for(owned)
    flow.mark_error("first failure")
    flow.mark_error("later cleanup")
    assert flow.snapshot()["error"] == "first failure"
    with pytest.raises(RuntimeError, match="first failure"):
        sdk_callback(flow)
