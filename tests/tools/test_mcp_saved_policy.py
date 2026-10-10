"""M02 initial bounded fixture: real saved config, real cached MCP handlers.

The session is a fake effect counter, the connection/trust ledgers are
isolated, and the loop scheduler runs coroutines directly. The lock-entry
fixture replaces the lock and does not prove real concurrent waiting.
Config persistence, registry factory/dispatch and handler result processing
are production owners. Native E2E and real-lock barrier tests are separate.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest


OPERATIONS = (
    ("tool", "_make_tool_handler", {"nonce": "owned-nonce"}),
    ("list_resources", "_make_list_resources_handler", {}),
    ("read_resource", "_make_read_resource_handler", {"uri": "owned://sentinel"}),
    ("list_prompts", "_make_list_prompts_handler", {}),
    ("get_prompt", "_make_get_prompt_handler", {"name": "owned-prompt"}),
)


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "owned-hermes"))
    monkeypatch.delenv("HERMES_SAFE_MODE", raising=False)
    from hermes_cli.mcp_config import _replace_mcp_servers
    import tools.mcp_tool as core

    calls = []

    class Session:
        async def call_tool(self, name, arguments):
            calls.append(("tool", arguments["nonce"]))
            return SimpleNamespace(content=[SimpleNamespace(text="owned-effect")], is_error=False)

        async def list_resources(self, **kwargs):
            calls.append(("list_resources", None))
            return SimpleNamespace(resources=[], next_cursor=None)

        async def read_resource(self, uri):
            calls.append(("read_resource", uri))
            return SimpleNamespace(contents=[SimpleNamespace(text="owned-resource")])

        async def list_prompts(self, **kwargs):
            calls.append(("list_prompts", None))
            return SimpleNamespace(prompts=[], next_cursor=None)

        async def get_prompt(self, name, arguments):
            calls.append(("get_prompt", name))
            return SimpleNamespace(messages=[])

    name = "owned_m02"
    cfg = {"url": "http://127.0.0.1:1/mcp", "enabled": True}
    server = core.MCPServerTask(name)
    server.session = Session()
    monkeypatch.setattr(core, "_servers", {name: server})
    monkeypatch.setattr(core, "_lazy_server_configs", {})
    monkeypatch.setattr(core, "_server_error_counts", {})
    monkeypatch.setattr(core, "_server_breaker_opened_at", {})
    monkeypatch.setattr(core, "_server_scope_keys", {})
    monkeypatch.setattr(core, "_server_tool_scopes", {})
    monkeypatch.setattr(core, "_server_trust_levels", {})
    monkeypatch.setattr(core, "_tool_read_only_hints", {})
    monkeypatch.setattr(core, "_server_errors_all_application", {})
    monkeypatch.setattr(core, "_run_on_mcp_loop", lambda factory, timeout=30: asyncio.run(factory()))

    def save(enabled):
        ok, issues = _replace_mcp_servers({name: {**cfg, "enabled": enabled}})
        assert ok and issues == [], issues

    save(True)
    return SimpleNamespace(core=core, server=server, calls=calls, name=name, save=save)


def handler_for(owner, factory):
    make = getattr(owner.core, factory)
    return make(owner.name, "write_sentinel", 2) if factory == "_make_tool_handler" else make(owner.name, 2)


@pytest.mark.parametrize("operation,factory,args", OPERATIONS)
def test_saved_disable_blocks_same_handler_and_reenable_restores(owner, operation, factory, args):
    handler = handler_for(owner, factory)
    enabled = json.loads(handler(args))
    assert "error" not in enabled
    assert len(owner.calls) == 1 and owner.calls[0][0] == operation
    owner.save(False)
    denied = json.loads(handler(args))
    assert len(owner.calls) == 1, "Saved disable allowed another cached-handler effect"
    assert "error" in denied and "disabled" in denied["error"].lower()
    assert owner.core._server_error_counts.get(owner.name, 0) == 0
    owner.save(True)
    restored = json.loads(handler(args))
    assert "error" not in restored
    assert len(owner.calls) == 2 and owner.calls[-1][0] == operation


@pytest.mark.parametrize("operation,factory,args", OPERATIONS)
def test_disable_at_rpc_lock_entry_prevents_admission(owner, operation, factory, args):
    class PolicyChangingLock:
        async def __aenter__(self):
            owner.save(False)

        async def __aexit__(self, *exc):
            return False

    owner.server._rpc_lock = PolicyChangingLock()
    denied = json.loads(handler_for(owner, factory)(args))
    assert owner.calls == [], "RPC crossed lock-entry seam after its policy became disabled"
    assert "error" in denied and "disabled" in denied["error"].lower()
    assert owner.core._server_error_counts.get(owner.name, 0) == 0


def test_registered_dispatch_and_retained_handle_preserve_schema(owner, monkeypatch):
    import tools.registry as registry_module

    registry = registry_module.ToolRegistry()
    monkeypatch.setattr(registry_module, "registry", registry)
    owner.server._tools = [SimpleNamespace(
        name="write_sentinel", description="Write an owned nonce.",
        inputSchema={"type": "object", "properties": {"nonce": {"type": "string"}}},
    )]
    names = owner.core._register_server_tools(
        owner.name, owner.server, {"url": "http://127.0.0.1:1/mcp", "enabled": True}
    )
    name = "mcp__owned_m02__write_sentinel"
    assert name in names
    retained = registry.get_entry(name).handler
    schema = json.dumps(registry.get_schema(name), sort_keys=True)
    assert json.loads(registry.dispatch(name, {"nonce": "first"}))["result"] == "owned-effect"
    assert owner.calls == [("tool", "first")]
    owner.save(False)
    for invoke in (lambda: registry.dispatch(name, {"nonce": "second"}),
                   lambda: retained({"nonce": "third"})):
        denied = json.loads(invoke())
        assert "error" in denied and "disabled" in denied["error"].lower()
        assert owner.calls == [("tool", "first")], "Registry or retained handler bypassed disable"
    assert json.dumps(registry.get_schema(name), sort_keys=True) == schema
    assert registry.get_entry(name).handler is retained
    owner.save(True)
    assert json.loads(registry.dispatch(name, {"nonce": "restored"}))["result"] == "owned-effect"
    assert owner.calls == [("tool", "first"), ("tool", "restored")]
