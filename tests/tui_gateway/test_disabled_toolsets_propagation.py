"""Desktop/TUI disabled toolsets reach every agent and discovery caller."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import tui_gateway.server as server


def test_disabled_loader_parses_config_and_preserves_desktop_control(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {
        "agent": {"disabled_toolsets": '["browser", "project", "desktop_ui"]'}
    })

    assert server._load_disabled_toolsets("desktop") == ["browser", "project"]
    assert server._load_disabled_toolsets("tui") == ["browser", "project", "desktop_ui"]


@pytest.mark.parametrize("platform", ["desktop", "tui"])
def test_new_agent_receives_composite_exclusions(monkeypatch, platform):
    cfg = {"agent": {"disabled_toolsets": '["browser"]'}}
    runtime = {"provider": "custom", "model": "local", "base_url": "http://localhost",
               "api_key": "local", "api_mode": "chat_completions"}
    monkeypatch.setattr(server, "_load_cfg", lambda: cfg)
    monkeypatch.setattr(server, "_get_db", lambda: MagicMock())
    monkeypatch.setattr(server, "_load_enabled_toolsets", lambda *_: ["hermes-cli"])
    monkeypatch.setattr(server, "_resolve_startup_runtime", lambda: ("local", "custom"))
    monkeypatch.setattr(server, "_resolve_runtime_with_fallback", lambda *_: (
        server._RuntimeFallbackResolution(runtime, None, False)
    ))
    monkeypatch.setattr(server, "_load_provider_routing", lambda: {})
    monkeypatch.setattr(server, "_parse_tui_skills_env", lambda: [])
    monkeypatch.setattr(server, "_agent_cbs", lambda _sid: {})
    with patch("run_agent.AIAgent") as constructor:
        server._make_agent("sid", "key", platform_override=platform)

    kwargs = constructor.call_args.kwargs
    assert kwargs["enabled_toolsets"] == ["hermes-cli"]
    assert kwargs["disabled_toolsets"] == ["browser"]
    assert kwargs["platform"] == platform


def test_background_agent_keeps_parent_exclusions(monkeypatch):
    parent = SimpleNamespace(
        model="local", platform="desktop", enabled_toolsets=["hermes-cli"],
        disabled_toolsets=["browser"],
    )
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    monkeypatch.setattr(server, "_get_db", lambda: object())
    monkeypatch.setattr(server, "_agent_fallback_model", lambda _agent: None)

    kwargs = server._background_agent_kwargs(parent, "background-task")

    assert kwargs["enabled_toolsets"] == ["hermes-cli"]
    assert kwargs["disabled_toolsets"] == ["browser"]
    assert kwargs["platform"] == "tui"


def test_background_agent_keeps_an_explicit_empty_parent_snapshot(monkeypatch):
    parent = SimpleNamespace(model="local", platform="desktop",
                             enabled_toolsets=["hermes-cli"], disabled_toolsets=[])
    monkeypatch.setattr(server, "_load_cfg", lambda: {
        "agent": {"disabled_toolsets": ["browser"]}
    })
    monkeypatch.setattr(server, "_get_db", lambda: object())
    monkeypatch.setattr(server, "_agent_fallback_model", lambda _agent: None)

    kwargs = server._background_agent_kwargs(parent, "background-task")

    assert kwargs["disabled_toolsets"] == []


@pytest.mark.parametrize(
    ("configured", "expected"),
    [('["browser", "desktop_ui"]', ["browser"]), (None, [])],
)
def test_explicit_mcp_reload_rebuilds_with_latest_exclusions(monkeypatch, configured, expected):
    import tools.mcp_tool as mcp_tool

    agent = SimpleNamespace(platform="desktop", enabled_toolsets=["hermes-cli"],
                            disabled_toolsets=["browser"])
    monkeypatch.setattr(server, "_sessions", {"sid": {"agent": agent}})
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda _session: False)
    monkeypatch.setattr(server, "_load_cfg", lambda: {
        "agent": {"disabled_toolsets": configured}
    })
    monkeypatch.setattr(server, "_load_enabled_toolsets", lambda *_: ["hermes-cli", "desktop_ui"])
    monkeypatch.setattr(server, "_compute_mcp_rev", lambda: "stable")
    monkeypatch.setattr(server, "_session_info", lambda *_: {})
    monkeypatch.setattr(server, "_emit", lambda *_: None)
    monkeypatch.setattr(mcp_tool, "shutdown_mcp_servers", lambda: None)
    monkeypatch.setattr(mcp_tool, "discover_mcp_tools", lambda: None)
    calls = []
    monkeypatch.setattr(mcp_tool, "refresh_agent_mcp_tools", lambda *a, **kw: calls.append((a, kw)))

    result = server._methods["reload.mcp"](1, {"session_id": "sid", "confirm": True})

    assert result["result"]["status"] == "reloaded"
    assert len(calls) == 1
    assert calls[0][0] == (agent,)
    assert calls[0][1]["disabled_override"] == expected


def test_mcp_reload_uses_the_target_sessions_profile_home(monkeypatch, tmp_path):
    import tools.mcp_tool as mcp_tool
    from hermes_constants import (get_hermes_home_override, reset_hermes_home_override,
                                  set_hermes_home_override)

    launch_home = tmp_path / "launch"
    session_home = tmp_path / "session"
    launch_home.mkdir()
    session_home.mkdir()
    agent = SimpleNamespace(platform="desktop", enabled_toolsets=["hermes-cli"],
                            disabled_toolsets=["browser"])
    monkeypatch.setattr(server, "_sessions", {
        "sid": {"agent": agent, "profile_home": str(session_home)}
    })
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda _session: False)
    monkeypatch.setattr(server, "_load_enabled_toolsets", lambda *_: (
        ["hermes-cli"] if get_hermes_home_override() == str(session_home) else ["web"]
    ))
    monkeypatch.setattr(server, "_load_disabled_toolsets", lambda *_: (
        ["browser"] if get_hermes_home_override() == str(session_home) else None
    ), raising=False)
    monkeypatch.setattr(server, "_compute_mcp_rev", lambda: "stable")
    monkeypatch.setattr(server, "_session_info", lambda *_: {})
    monkeypatch.setattr(server, "_emit", lambda *_: None)
    monkeypatch.setattr(mcp_tool, "shutdown_mcp_servers", lambda: None)
    monkeypatch.setattr(mcp_tool, "discover_mcp_tools", lambda: None)
    calls = []
    monkeypatch.setattr(mcp_tool, "refresh_agent_mcp_tools", lambda *a, **kw: calls.append(kw))

    launch_token = set_hermes_home_override(launch_home)
    try:
        result = server._methods["reload.mcp"](1, {"session_id": "sid", "confirm": True})
        assert get_hermes_home_override() == str(launch_home)
    finally:
        reset_hermes_home_override(launch_token)

    assert result["result"]["status"] == "reloaded"
    assert len(calls) == 1
    assert calls[0]["enabled_override"] == ["hermes-cli"]
    assert calls[0]["disabled_override"] == ["browser"]


def test_tools_show_uses_the_session_exclusions(monkeypatch):
    import model_tools

    agent = SimpleNamespace(enabled_toolsets=["hermes-cli"], disabled_toolsets=["browser"])
    monkeypatch.setattr(server, "_sessions", {"sid": {"agent": agent}})
    calls = []

    def definitions(**kwargs):
        calls.append(kwargs)
        names = ["terminal", "browser_exec"]
        if "browser" in (kwargs.get("disabled_toolsets") or []):
            names.remove("browser_exec")
        return [{"function": {"name": name, "description": name}} for name in names]

    monkeypatch.setattr(model_tools, "get_tool_definitions", definitions)
    monkeypatch.setattr(model_tools, "get_toolset_for_tool", lambda name: name.split("_")[0])

    result = server._methods["tools.show"](1, {"session_id": "sid"})

    assert result["result"]["total"] == 1
    assert calls[0]["enabled_toolsets"] == ["hermes-cli"]
    assert calls[0]["disabled_toolsets"] == ["browser"]
