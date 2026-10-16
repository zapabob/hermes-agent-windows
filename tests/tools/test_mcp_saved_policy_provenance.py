"""Additional owner regressions: real adoption and portable single unload.

Sessions count effects without native transport. Plugin manifests, discovery,
unload, saved native config and shared-connection resolution are real owners.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from tests.tools.test_mcp_saved_policy import owner, handler_for
from hermes_constants import get_hermes_home, hermes_home_key, set_hermes_home_override, reset_hermes_home_override
from hermes_cli.mcp_config import _replace_mcp_servers


def test_public_adoption_removal_before_first_call_preserves_caller_boundary(owner, monkeypatch, tmp_path):
    import tools.registry as registry_module
    monkeypatch.setattr(registry_module, "registry", registry_module.ToolRegistry())
    monkeypatch.setattr("agent.secret_scope.is_multiplex_active", lambda: True)
    home_a = get_hermes_home()
    key_a = (hermes_home_key(home_a), owner.name)
    owner.core._servers.clear()
    owner.core._servers[key_a] = owner.server
    owner.core._server_scope_keys[key_a] = key_a[0]
    owner.core._server_tool_scopes[key_a] = {key_a[0]}
    cfg = {"url": "http://127.0.0.1:1/mcp", "enabled": True}
    owner.server._config = cfg
    home_b = tmp_path / "profiles" / "owned-b"
    home_b.mkdir(parents=True)
    token = set_hermes_home_override(home_b)
    try:
        owner.save(True)
        assert owner.core.register_connected_into_current_scope({owner.name: cfg}) == 1
        assert owner.core._resolve_server_key(owner.name) == key_a
        assert owner.calls == []
        ok, issues = _replace_mcp_servers({})
        assert ok and issues == []
        denied = json.loads(handler_for(owner, "_make_tool_handler")({"nonce": "b-denied"}))
        assert denied.get("mcp_policy") == "native_removed", "Direct adoption forgot B native origin before its first call"
        assert owner.calls == []
    finally:
        reset_hermes_home_override(token)
    assert json.loads(handler_for(owner, "_make_tool_handler")({"nonce": "a-allowed"}))["result"] == "owned-effect"
    assert owner.calls == [("tool", "a-allowed")]


def test_public_single_portable_unload_revokes_retained_handler_only_for_its_owner(owner, monkeypatch, tmp_path):
    from hermes_cli import plugins as plugins_module
    from hermes_cli.agent_plugins import PLUGIN_SCHEMA_V1, MCP_SCHEMA_V1
    import tools.registry as registry_module
    import yaml

    registry = registry_module.ToolRegistry()
    monkeypatch.setattr(registry_module, "registry", registry)
    empty_bundled = tmp_path / "owned-empty-bundled"
    empty_bundled.mkdir()
    monkeypatch.setattr(plugins_module, "get_bundled_plugins_dir", lambda: empty_bundled)
    monkeypatch.setattr(plugins_module, "discover_entrypoint_manifests", lambda: [])
    for name in ("portable.one", "portable.two"):
        folder = get_hermes_home() / "plugins" / name
        folder.mkdir(parents=True)
        (folder / "plugin.json").write_text(json.dumps({"$schema": PLUGIN_SCHEMA_V1, "name": name}), encoding="utf-8")
        (folder / "mcp.json").write_text(json.dumps({"$schema": MCP_SCHEMA_V1, "mcpServers": {"worker": {"type": "stdio", "command": "owned-command"}}}), encoding="utf-8")
    (get_hermes_home() / "config.yaml").write_text(yaml.safe_dump({"plugins": {"enabled": ["portable.one", "portable.two"]}}), encoding="utf-8")
    manager = plugins_module.PluginManager()
    monkeypatch.setattr(plugins_module, "_plugin_manager", manager)
    manager.discover_and_load()
    assert manager._plugins["portable.one"].enabled
    assert manager._plugins["portable.two"].enabled
    names = {key: manager._plugins[key].manifest.skill_namespace + "__worker" for key in ("portable.one", "portable.two")}
    owner.server._tools = [SimpleNamespace(name="write_sentinel", description="Owned sentinel.", inputSchema={"type": "object"})]
    handles = {}
    for key, name in names.items():
        owner.core._servers[name] = owner.server
        registered = owner.core._register_server_tools(name, owner.server, manager.get_portable_mcp_servers()[name])
        [tool_name] = [tool for tool in registered if tool.endswith("__write_sentinel")]
        handles[key] = registry.get_entry(tool_name).handler
    try:
        assert json.loads(handles["portable.one"]({"nonce": "one-before"}))["result"] == "owned-effect"
        assert json.loads(handles["portable.two"]({"nonce": "two-before"}))["result"] == "owned-effect"
        assert manager.unload("portable.one") is True
        assert "portable.one" not in manager._plugins
        denied = json.loads(handles["portable.one"]({"nonce": "one-after"}))
        assert denied.get("mcp_policy") == "portable_removed", "Public single unload left its cached MCP handler admitted"
        assert owner.calls == [("tool", "one-before"), ("tool", "two-before")]
        assert json.loads(handles["portable.two"]({"nonce": "two-after"}))["result"] == "owned-effect"
        assert owner.calls[-1] == ("tool", "two-after")
    finally:
        manager.unload()
