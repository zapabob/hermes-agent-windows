"""Behavioral assertions for saved-policy mutation qualification.

These supplement frozen earlier oracles. Session effects remain bounded fake
effects; the separate Windows transport/process tests exercise the real SDK.
"""
import builtins
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient
import yaml

from hermes_cli import config
from hermes_cli.mcp_config import _replace_mcp_servers
from hermes_constants import get_hermes_home
from tests.hermes_cli.test_config_readonly_validity import owned_config
from tests.tools.test_mcp_saved_policy import handler_for, owner
from tests.tools.test_mcp_saved_policy_boundaries import register_owned


def test_native_origin_removal_has_no_effect_and_typed_denial(owner, monkeypatch):
    registry = register_owned(owner, monkeypatch)
    assert owner.calls == []
    ok, issues = _replace_mcp_servers({})
    assert ok and issues == []
    result = json.loads(registry.dispatch("mcp__owned_m02__write_sentinel", {"nonce": "removed-origin"}))
    assert owner.calls == [], "A removed native origin performed a cached-handler effect"
    assert result.get("mcp_policy") == "native_removed", result


@pytest.mark.parametrize("layer", [0, 1], ids=["user", "managed"])
def test_strict_current_unreadable_file_is_asserted_typed_refusal(owned_config, monkeypatch, layer):
    for file in owned_config:
        file.write_text("mcp_servers: {}\n", encoding="utf-8")
    config.load_config_readonly()
    original = builtins.open

    def denied_open(file, *args, **kwargs):
        if Path(file) == owned_config[layer]:
            raise PermissionError("owned-secret must not reach result")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denied_open)
    observed = None
    try:
        config.load_config_readonly(require_valid=True)
    except config.ConfigReadError as error:
        observed = error
    assert isinstance(observed, config.ConfigReadError), "Strict reader accepted a currently unreadable file"
    assert observed.category == "unreadable" and "owned-secret" not in str(observed)


def test_strict_current_malformed_file_refuses_last_known_good_with_assertion(owned_config):
    file = owned_config[0]
    file.write_text("mcp_servers:\n  owned:\n    enabled: false\n", encoding="utf-8")
    assert config.load_config()["mcp_servers"]["owned"]["enabled"] is False
    file.write_text("mcp_servers: [", encoding="utf-8")
    assert config.load_config()["mcp_servers"]["owned"]["enabled"] is False
    observed = None
    try:
        config.load_config_readonly(require_valid=True)
    except config.ConfigReadError as error:
        observed = error
    assert isinstance(observed, config.ConfigReadError), "Strict reader used last-known-good after current parse failure"


@pytest.mark.parametrize("route", ["replace", "enabled"])
def test_public_save_applies_runtime_and_persists_same_policy(owner, route, record_property):
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    handler = handler_for(owner, "_make_tool_handler")
    assert "error" not in json.loads(handler({"nonce": "before-save"}))
    assert owner.calls == [("tool", "before-save")]
    client = TestClient(app)
    try:
        client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        if route == "replace":
            response = client.put("/api/mcp/servers", json={"servers": {
                owner.name: {"url": "http://127.0.0.1:1/mcp", "enabled": False}}})
        else:
            response = client.put(f"/api/mcp/servers/{owner.name}/enabled", json={"enabled": False})
        assert response.status_code == 200 and response.json().get("ok") is True
    finally:
        client.close()
    denied = json.loads(handler({"nonce": "after-save"}))
    assert denied.get("mcp_policy") == "disabled" and owner.calls == [("tool", "before-save")]
    # Record runtime application before the independent persisted-byte assertion.
    record_property("public_save_runtime_applied", route)
    raw = yaml.safe_load((get_hermes_home() / "config.yaml").read_text(encoding="utf-8"))
    assert raw["mcp_servers"][owner.name].get("enabled") is False, "Runtime policy was acknowledged without persistence"
