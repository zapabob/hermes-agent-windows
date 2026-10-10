"""Saved policy boundaries; fake session effects are not native transport proof."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tests.tools.test_mcp_saved_policy import OPERATIONS, owner, handler_for
from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
from hermes_cli.mcp_config import _replace_mcp_servers

CASES = json.loads((Path(__file__).resolve().parents[2] / "apps/desktop/src/lib/mcp-enabled-cases.json").read_text(encoding="utf-8"))


def write_config(value):
    (get_hermes_home() / "config.yaml").write_text(yaml.safe_dump(value), encoding="utf-8")


@pytest.mark.parametrize("operation,factory,args", OPERATIONS)
@pytest.mark.parametrize("case", [c for c in CASES if not c["on"]], ids=lambda c: repr(c["enabled"]))
def test_canonical_disabled_values_block_before_any_transport(owner, monkeypatch, operation, factory, args, case):
    write_config({"mcp_servers": {owner.name: {"url": "http://127.0.0.1:1/mcp", "enabled": case["enabled"]}}})
    attempts = []
    monkeypatch.setattr(owner.core, "_get_connected_server_for_call", lambda name: attempts.append(name))
    result = json.loads(handler_for(owner, factory)(args))
    assert result["mcp_policy"] == "disabled" and attempts == [] and owner.calls == []


@pytest.mark.parametrize("operation,factory,args", OPERATIONS)
@pytest.mark.parametrize("bad", [[], "owned-invalid", {"owned_m02": []}, {"owned_m02": False}])
def test_malformed_native_entries_fail_closed(owner, operation, factory, args, bad):
    write_config({"mcp_servers": bad})
    result = json.loads(handler_for(owner, factory)(args))
    assert result["mcp_policy"] == "native_malformed" and owner.calls == []


@pytest.mark.parametrize("operation,factory,args", OPERATIONS)
def test_safe_mode_no_transport_or_breaker(owner, monkeypatch, operation, factory, args):
    monkeypatch.setenv("HERMES_SAFE_MODE", "1")
    result = json.loads(handler_for(owner, factory)(args))
    assert result["mcp_policy"] == "safe_mode" and owner.calls == []
    assert owner.core._server_error_counts == {}


@pytest.mark.parametrize("operation,factory,args", OPERATIONS)
@pytest.mark.parametrize("mode", ["lazy", "recycled"])
def test_lazy_and_recycled_paths_not_started_when_disabled(owner, monkeypatch, operation, factory, args, mode):
    attempts = []
    if mode == "lazy":
        owner.core._lazy_server_configs[owner.name] = {"command": "owned-command"}
    owner.server.session = None
    monkeypatch.setattr(type(owner.server), "_is_recycled_stdio", lambda self: True)
    monkeypatch.setattr(owner.core, "_ensure_lazy_server_connected", lambda name: attempts.append("spawn"))
    monkeypatch.setattr(owner.core, "_request_lazy_reconnect", lambda *args: attempts.append("reconnect"))
    owner.save(False)
    result = json.loads(handler_for(owner, factory)(args))
    assert result["mcp_policy"] == "disabled" and attempts == []


def register_owned(owner, monkeypatch):
    import tools.registry as registry_module
    registry = registry_module.ToolRegistry()
    monkeypatch.setattr(registry_module, "registry", registry)
    owner.server._tools = [SimpleNamespace(name="write_sentinel", description="Owned sentinel.", inputSchema={"type": "object"})]
    owner.core._register_server_tools(owner.name, owner.server, {"url": "http://127.0.0.1:1/mcp"})
    return registry


def test_native_removed_before_first_registered_invocation_is_denied(owner, monkeypatch):
    registry = register_owned(owner, monkeypatch)
    assert owner.calls == []
    ok, issues = _replace_mcp_servers({})
    assert ok and issues == []
    result = json.loads(registry.dispatch("mcp__owned_m02__write_sentinel", {"nonce": "never"}))
    assert result["mcp_policy"] == "native_removed" and owner.calls == []


def test_never_native_explicit_handler_is_legitimate(owner, monkeypatch):
    ok, issues = _replace_mcp_servers({})
    assert ok and issues == []
    monkeypatch.setattr(owner.core, "_native_mcp_names_by_home", {})
    registry = register_owned(owner, monkeypatch)
    result = json.loads(registry.dispatch("mcp__owned_m02__write_sentinel", {"nonce": "explicit"}))
    assert result["result"] == "owned-effect" and owner.calls == [("tool", "explicit")]


def test_captured_caller_home_survives_scheduler_context_change(owner, monkeypatch, tmp_path):
    other = tmp_path / "other-owned-home"
    other.mkdir()
    (other / "config.yaml").write_text("mcp_servers: {}\n", encoding="utf-8")

    def run(factory, timeout=30):
        owner.save(False)
        token = set_hermes_home_override(other)
        try:
            return asyncio.run(factory())
        finally:
            reset_hermes_home_override(token)

    monkeypatch.setattr(owner.core, "_run_on_mcp_loop", run)
    result = json.loads(handler_for(owner, "_make_tool_handler")({"nonce": "never"}))
    assert result["mcp_policy"] == "disabled" and owner.calls == []


def test_long_approval_disable_prevents_lazy_acquisition(owner, monkeypatch):
    def approval(*args):
        owner.save(False)
        return None

    attempts = []
    monkeypatch.setattr(owner.core, "_trust_gate_check", approval)
    monkeypatch.setattr(owner.core, "_get_connected_server_for_call", lambda name: attempts.append(name))
    result = json.loads(handler_for(owner, "_make_tool_handler")({"nonce": "never"}))
    assert result["mcp_policy"] == "disabled" and attempts == [] and owner.calls == []


@pytest.mark.parametrize("factory,method,attribute", [
    ("_make_list_resources_handler", "list_resources", "resources"),
    ("_make_list_prompts_handler", "list_prompts", "prompts"),
])
def test_admitted_pagination_completes_then_next_invocation_is_denied(owner, factory, method, attribute):
    cursors = []

    async def paged(**kwargs):
        cursor = kwargs.get("cursor") or getattr(kwargs.get("params"), "cursor", None)
        cursors.append(cursor)
        if cursor is None:
            owner.save(False)
            return SimpleNamespace(**{attribute: [], "next_cursor": "owned-next"})
        return SimpleNamespace(**{attribute: [], "next_cursor": None})

    setattr(owner.server.session, method, paged)
    handler = handler_for(owner, factory)
    assert "error" not in json.loads(handler({}))
    assert cursors == [None, "owned-next"]
    assert json.loads(handler({}))["mcp_policy"] == "disabled"
    assert cursors == [None, "owned-next"]


@pytest.mark.parametrize("operation,factory,args", OPERATIONS)
@pytest.mark.parametrize("failure", ["auth", "expired"])
def test_disable_after_failed_rpc_prevents_recovery_work(owner, monkeypatch, operation, factory, args, failure):
    from mcp.client.auth import OAuthFlowError
    from tools.mcp_oauth_manager import get_manager
    attempts = []

    async def failed(*a, **kw):
        owner.save(False)
        raise OAuthFlowError("owned expiry") if failure == "auth" else RuntimeError("session expired")

    methods = {"tool": "call_tool", "list_resources": "list_resources", "read_resource": "read_resource", "list_prompts": "list_prompts", "get_prompt": "get_prompt"}
    setattr(owner.server.session, methods[operation], failed)

    async def recovery(*a, **kw):
        attempts.append("oauth")
        return True

    monkeypatch.setattr(get_manager(), "handle_401", recovery)
    monkeypatch.setattr(owner.core, "_signal_reconnect_and_wait", lambda *a, **kw: attempts.append("reconnect"))
    result = json.loads(handler_for(owner, factory)(args))
    assert result["mcp_policy"] == "disabled" and attempts == [] and owner.calls == []
    assert owner.core._server_error_counts == {}
