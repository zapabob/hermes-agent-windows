"""Multiplexed profiles with the same MCP server name get separate connections.

COMPOSE contracts from upstream ceaf622 / e609efb / 9d39267 / bbe4089 / 399238f
into the Windows monolithic ``tools.mcp_tool`` owner (no module split).
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
        "_mcp_tool_server_names",
        "_parallel_safe_servers",
        "_server_trust_levels",
        "_tool_read_only_hints",
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
    assert "x" in core._select_new_servers({"x": cfg_b})
    assert not core._connect_cooldown_active("y")
    assert core._server_error_counts.get(_server_key("x"), 0) == 0
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
    cfg_other = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer other"}}
    assert core.register_connected_into_current_scope({"x": cfg_other}) == 0


def test_oauth_server_is_not_adopted_across_profiles(two_profiles):
    import tools.mcp_tool as core

    cfg = {"url": "https://mcp.example/x", "auth": "oauth"}

    two_profiles("a")
    with core._lock:
        core._adopt_server("x", _server("x", cfg))
    assert core.register_connected_into_current_scope({"x": dict(cfg)}) == 0

    two_profiles("b")
    assert core.register_connected_into_current_scope({"x": dict(cfg)}) == 0
    assert "x" in core._select_new_servers({"x": dict(cfg)})


def test_same_named_server_with_other_mtls_identity_is_a_separate_connection(two_profiles):
    import tools.mcp_tool as core

    cfg_a = {
        "url": "https://mcp.example/x",
        "client_cert": "/certs/profile-a.pem",
        "client_key": "/certs/profile-a.key",
    }
    cfg_b = {
        "url": "https://mcp.example/x",
        "client_cert": "/certs/profile-b.pem",
        "client_key": "/certs/profile-b.key",
    }

    two_profiles("a")
    with core._lock:
        core._adopt_server("x", _server("x", cfg_a))

    two_profiles("b")
    assert core.register_connected_into_current_scope({"x": cfg_b}) == 0
    assert "x" in core._select_new_servers({"x": cfg_b})


def test_untrusted_adopter_of_a_full_profiles_connection_keeps_its_own_trust_gate(
    two_profiles, monkeypatch
):
    """Trust is the consuming profile's policy under shared connections."""
    import tools.mcp_tool as core
    import tools.approval as approval

    route = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer shared"}}
    cfg_a, cfg_b = dict(route, trust="full"), dict(route, trust="untrusted")
    asked = []
    monkeypatch.setattr(
        approval,
        "request_elicitation_consent",
        lambda *a, **k: asked.append(a) or "deny",
    )

    two_profiles("a")
    srv_a = _server("x", cfg_a)
    with core._lock:
        core._adopt_server("x", srv_a)
    srv_a._registered_tool_names = core._register_server_tools("x", srv_a, cfg_a)

    two_profiles("b")
    assert core.register_connected_into_current_scope({"x": cfg_b}) == 1
    assert core._trust_gate_check("x", "t") is not None and asked

    two_profiles("a")
    assert core._trust_gate_check("x", "t") is None and len(asked) == 1


def test_parallel_safe_opt_in_is_per_profile(two_profiles):
    """B's parallel opt-in must not make A's same-named serial server parallel-safe."""
    import tools.mcp_tool as core

    cfg_a = {"url": "https://mcp.example/x", "headers": {"Authorization": "Bearer A"}}
    cfg_b = dict(
        cfg_a,
        headers={"Authorization": "Bearer B"},
        supports_parallel_tool_calls=True,
    )

    two_profiles("a")
    core._select_new_servers({"x": cfg_a})
    srv_a = _server("x", cfg_a)
    with core._lock:
        core._adopt_server("x", srv_a)
    srv_a._registered_tool_names = core._register_server_tools("x", srv_a, cfg_a)

    two_profiles("b")
    core._select_new_servers({"x": cfg_b})
    # B has no tool provenance yet; register a stub provenance under B's key path
    # by adopting its own connection for the parallel-safe check on B's config.
    with core._lock:
        core._adopt_server("x", _server("x", cfg_b))
        core._mcp_tool_server_names["mcp__x__t"] = "x"
    assert core.is_mcp_tool_parallel_safe("mcp__x__t") is True

    two_profiles("a")
    with core._lock:
        core._mcp_tool_server_names["mcp__x__t"] = "x"
    assert core.is_mcp_tool_parallel_safe("mcp__x__t") is False


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
