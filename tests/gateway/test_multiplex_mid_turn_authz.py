"""Routing/authorization invariants for a multiplexed gateway (SR-20260913-005).

Composes upstream mid-turn authz contracts (#104933 / 77180acc): admitting-bot
allowlist under a satellite turn, and shared-bot satellite transport resolution.
"""

from __future__ import annotations

import weakref
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.pairing import PairingStore
from gateway.platforms.base import BasePlatformAdapter
from gateway.profile_routing import parse_profile_routes
from gateway.session import SessionSource


class _Stub(BasePlatformAdapter):
    pass


_Stub.__abstractmethods__ = frozenset()


def _stub(platform, runner, label):
    adapter = _Stub.__new__(_Stub)
    adapter.platform, adapter.gateway_runner, adapter.label = platform, runner, label
    adapter._pending_messages, adapter._active_sessions = {}, {}
    return adapter


@pytest.fixture
def mux(tmp_path, monkeypatch):
    """Default home allows user 777; profile ``ops`` is a shared-bot satellite; ``team_b`` owns a bot."""
    from agent import secret_scope
    from gateway.run import GatewayRunner

    home = tmp_path / "hh"
    for name in ("ops", "team_b"):
        (home / "profiles" / name).mkdir(parents=True)
    (home / ".env").write_text("TELEGRAM_ALLOWED_USERS=777\n", encoding="utf-8")
    (home / "profiles" / "team_b" / ".env").write_text(
        "TELEGRAM_ALLOWED_USERS=72719239\n", encoding="utf-8"
    )
    (home / "profiles" / "ops" / ".env").write_text("", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    for key in ("TELEGRAM_ALLOWED_USERS", "GATEWAY_ALLOW_ALL_USERS", "GATEWAY_ALLOWED_USERS"):
        monkeypatch.delenv(key, raising=False)
    prev = secret_scope.is_multiplex_active()
    secret_scope.set_multiplex_active(True)

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)
    runner.config.platforms = {Platform.TELEGRAM: PlatformConfig(enabled=True, extra={})}
    runner.config.profile_routes = parse_profile_routes(
        [{"name": "admin-dm", "platform": "telegram", "profile": "ops", "chat_id": "72719239"}]
    )
    runner.pairing_store = PairingStore(profile="default")
    runner.pairing_stores = {}
    runner._primary_profile_name = "default"
    primary = _stub(Platform.TELEGRAM, runner, "PRIMARY")
    team_b = _stub(Platform.TELEGRAM, runner, "TEAM_B")
    runner.adapters = {Platform.TELEGRAM: primary}
    runner._profile_adapters = {"team_b": {Platform.TELEGRAM: team_b}, "ops": {}}
    served = [
        ("default", home),
        ("ops", home / "profiles" / "ops"),
        ("team_b", home / "profiles" / "team_b"),
    ]
    with (
        patch("hermes_cli.profiles.profiles_to_serve", return_value=served),
        patch(
            "hermes_cli.profiles.get_profile_dir",
            side_effect=lambda n: home / "profiles" / n,
        ),
        patch("hermes_cli.profiles.profile_exists", return_value=True),
    ):
        yield SimpleNamespace(runner=runner, home=home, primary=primary, team_b=team_b)
    secret_scope.set_multiplex_active(prev)


def test_mid_turn_authorization_reads_admitting_transport_allowlist(mux):
    """Inside a routed satellite's turn (no allowlist) for_source admits the shared bot's owner."""
    from gateway.run import _profile_runtime_scope

    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="777",
        chat_type="dm",
        user_id="777",
        profile="ops",
    )
    source._transport_adapter_ref = weakref.ref(mux.primary)
    with _profile_runtime_scope(mux.home / "profiles" / "ops"):
        assert mux.runner._is_user_authorized(source) is False
        assert mux.runner._is_user_authorized_for_source(source) is True
    stranger = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="1",
        chat_type="dm",
        user_id="1",
        profile="ops",
    )
    stranger._transport_adapter_ref = weakref.ref(mux.primary)
    with _profile_runtime_scope(mux.home / "profiles" / "ops"):
        assert mux.runner._is_user_authorized_for_source(stranger) is False


def test_shared_bot_satellite_resolves_primary_transport_for_restored_sources(mux):
    """Satellite with no bot drains through primary; disconnected secondary stays fail-closed."""
    restored = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="72719239",
        chat_type="dm",
        user_id="7",
        profile="ops",
    )
    assert mux.runner._authorization_adapter(Platform.TELEGRAM, "ops") is mux.primary
    assert mux.runner._adapter_for_source(restored) is mux.primary
    assert mux.runner._resolve_injection_adapter("telegram", restored) is mux.primary
    mux.runner._profile_adapters["team_b"] = {}
    assert mux.runner._authorization_adapter(Platform.TELEGRAM, "team_b") is None


def test_platform_gate_env_fail_closed_under_multiplex(monkeypatch):
    """Scoped miss must not fall through to os.environ under multiplex."""
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from gateway.authz_mixin import _platform_gate_env

    monkeypatch.setattr("agent.secret_scope._MULTIPLEX_ACTIVE", True)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "FROM-DEFAULT")
    token = set_secret_scope({})
    try:
        assert _platform_gate_env("TELEGRAM_ALLOWED_USERS", "") == ""
    finally:
        reset_secret_scope(token)
