"""Multiplexed profiles with the same MCP server name get separate connections.

COMPOSE contract from upstream ceaf622 / mcp_tool_scope: ledgers in
``tools.mcp_tool`` are keyed per owning profile scope under a multiplexer.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_constants import hermes_home_key, reset_hermes_home_override, set_hermes_home_override


def _tool():
    return SimpleNamespace(
        name="t",
        description="d",
        inputSchema={"type": "object", "properties": {}},
        annotations=None,
    )


def _server(name, cfg):
    return SimpleNamespace(
        name=name,
        session=object(),
        _config=cfg,
        _tools=[_tool()],
        tool_timeout=30,
        initialize_result=None,
        _registered_tool_names=[],
        _sampling=None,
        _is_recycled_stdio=lambda: False,
    )


@pytest.fixture
def two_profiles(tmp_path, monkeypatch):
    """Multiplex on, clean MCP ledgers, scope switcher for homes A and B."""
    import tools.mcp_tool as core

    homes = {k: tmp_path / "profiles" / k for k in ("a", "b")}
    for home in homes.values():
        home.mkdir(parents=True)
    monkeypatch.setattr("agent.secret_scope.is_multiplex_active", lambda: True)
    monkeypatch.setattr(core, "_ensure_mcp_sdk", lambda: True)

    ledgers = (
        "_servers",
        "_server_scope_keys",
        "_server_tool_scopes",
        "_server_connecting",
        "_server_connect_errors",
        "_server_connect_retry_after",
        "_server_connect_failures",
        "_server_error_counts",
        "_server_breaker_opened_at",
        "_lazy_server_configs",
        "_lazy_server_fingerprints",
        "_lazy_server_tool_names",
    )
    saved = {n: type(getattr(core, n))(getattr(core, n)) for n in ledgers}
    for n in ledgers:
        getattr(core, n).clear()
    tokens = []

    def enter(which):
        tokens.append(set_hermes_home_override(homes[which]))
        return hermes_home_key(homes[which])

    yield enter

    for token in reversed(tokens):
        reset_hermes_home_override(token)
    for n in ledgers:
        getattr(core, n).clear()
        getattr(core, n).update(saved[n])


def test_same_named_server_with_other_credentials_is_a_separate_connection(two_profiles):
    import tools.mcp_tool as core
    from tools.mcp_tool_scope import _server_key

    cfg_a = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer A"}}
    cfg_b = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer B"}}

    scope_a = two_profiles("a")
    srv_a = _server("x", cfg_a)
    with core._lock:
        core._adopt_server("x", srv_a)
    for _ in range(core._CIRCUIT_BREAKER_THRESHOLD):
        core._bump_server_error("x")
    core._record_connect_failure("y")

    two_profiles("b")
    # B must not see A's connection as "already connected".
    assert "x" in core._select_new_servers({"x": cfg_b})
    assert not core._connect_cooldown_active("y")
    assert core._server_error_counts.get(_server_key("x"), 0) == 0
    # A's breaker must remain under A's key.
    two_profiles("a")
    assert core._server_error_counts.get(_server_key("x"), 0) >= core._CIRCUIT_BREAKER_THRESHOLD
    assert scope_a in {core._server_scope_keys.get(k) for k in core._servers}


def test_order_independent_ab_ba(two_profiles):
    import tools.mcp_tool as core
    from tools.mcp_tool_scope import _resolve_server_key, _server_key

    cfg_a = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer A"}}
    cfg_b = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer B"}}

    two_profiles("a")
    with core._lock:
        core._adopt_server("x", _server("x", cfg_a))
    key_a = _server_key("x")

    two_profiles("b")
    with core._lock:
        core._adopt_server("x", _server("x", cfg_b))
    key_b = _server_key("x")

    assert key_a != key_b
    assert isinstance(key_a, tuple) and isinstance(key_b, tuple)

    two_profiles("a")
    assert _resolve_server_key("x") == key_a
    two_profiles("b")
    assert _resolve_server_key("x") == key_b


def test_same_credentials_can_adopt_sibling_connection(two_profiles):
    import tools.mcp_tool as core
    from tools.mcp_tool_scope import _resolve_server_key

    cfg = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer shared"}}

    two_profiles("a")
    with core._lock:
        core._adopt_server("x", _server("x", cfg))
    key_a = _resolve_server_key("x")

    two_profiles("b")
    assert core.register_connected_into_current_scope({"x": cfg}) == 1
    assert _resolve_server_key("x") == key_a
    # Different credentials must NOT adopt.
    cfg_other = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer other"}}
    assert core.register_connected_into_current_scope({"x": cfg_other}) == 0


def test_single_profile_keeps_bare_name_keys(monkeypatch, tmp_path):
    import tools.mcp_tool as core
    from tools.mcp_tool_scope import _server_key

    monkeypatch.setattr("agent.secret_scope.is_multiplex_active", lambda: False)
    token = set_hermes_home_override(tmp_path / "solo")
    try:
        (tmp_path / "solo").mkdir(parents=True, exist_ok=True)
        key = _server_key("filesystem")
        assert key == "filesystem"
        with core._lock:
            core._servers.clear()
            core._adopt_server("filesystem", _server("filesystem", {"command": "npx"}))
            assert "filesystem" in core._servers
    finally:
        reset_hermes_home_override(token)
        with core._lock:
            core._servers.pop("filesystem", None)
