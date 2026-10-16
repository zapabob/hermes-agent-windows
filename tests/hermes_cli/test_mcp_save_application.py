"""Actual authenticated config routes acknowledge policy/catalogue separately.

Transport effects are counted by the existing bounded owner fixture. This
does not establish native HTTP MCP or native Desktop qualification.
"""
import json

import pytest
from starlette.testclient import TestClient

from tests.tools.test_mcp_saved_policy import owner, handler_for


@pytest.mark.parametrize("route", ("replace", "enabled"))
def test_public_save_ack_separates_policy_catalogue_and_admitted_work(owner, route):
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    retained = handler_for(owner, "_make_tool_handler")
    assert "error" not in json.loads(retained({"nonce": "before-public-save"}))
    before = list(owner.calls)
    if route == "replace":
        response = client.put("/api/mcp/servers", json={"servers": {
            owner.name: {"url": "http://127.0.0.1:1/mcp", "enabled": False}}})
    else:
        response = client.put(f"/api/mcp/servers/{owner.name}/enabled", json={"enabled": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("ok") is True
    assert json.loads(retained({"nonce": "after-public-save"})).get("mcp_policy") == "disabled"
    assert owner.calls == before
    assert body.get("application") == {
        "policy_check": "rpc_admission",
        "catalogue": "new_session_or_explicit_reload",
        "admitted_calls": "may_complete",
    }, "A successful save must describe policy admission independently of catalogue discovery and prior work"
