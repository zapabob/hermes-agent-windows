"""Mutable metadata and unscoped address prefixes never grant authority."""
import asyncio
import os
from unittest.mock import MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platform_registry import PlatformEntry, platform_registry
from gateway.session import SessionSource
from tests.gateway.test_unauthorized_dm_behavior import _clear_auth_env, _make_runner


@pytest.fixture
def principal_env(monkeypatch, tmp_path):
    _clear_auth_env(monkeypatch)
    for key in tuple(os.environ):
        if key.endswith(("_ALLOWED_USERS", "_ALLOW_ALL_USERS")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(platform_registry, "_entries", dict(platform_registry._entries))
    platform_registry.register(PlatformEntry(
        name="simplex", label="SimpleX", adapter_factory=lambda cfg: None,
        check_fn=lambda: True, allowed_users_env="SIMPLEX_ALLOWED_USERS",
        allow_all_env="SIMPLEX_ALLOW_ALL_USERS",
    ))
    return Platform("simplex")


def authorized(platform, user_id, display_name="Alice"):
    runner, _ = _make_runner(platform, GatewayConfig(platforms={platform: PlatformConfig(enabled=True)}))
    return runner._is_user_authorized(SessionSource(
        platform=platform, user_id=user_id, user_name=display_name,
        chat_id=user_id, chat_type="dm",
    ))


@pytest.mark.parametrize("name", ["Alice", "renamed", "4", ""])
def test_allowed_contact_survives_display_rename(principal_env, monkeypatch, name):
    monkeypatch.setenv("SIMPLEX_ALLOWED_USERS", "4")
    assert authorized(principal_env, "4", name)


@pytest.mark.parametrize("allowlist,name", [("Alice", "Alice"), ("4", "4"), ("4,Alice", "Alice")])
def test_colliding_display_name_does_not_authorize_contact(principal_env, monkeypatch, allowlist, name):
    monkeypatch.setenv("SIMPLEX_ALLOWED_USERS", allowlist)
    assert not authorized(principal_env, "99", name)


@pytest.mark.parametrize("platform,env,user_id", [
    (Platform.EMAIL, "EMAIL_ALLOWED_USERS", "alice@evil.example"),
    (Platform.SIGNAL, "SIGNAL_ALLOWED_USERS", "alice@evil.example"),
    (Platform.DISCORD, "DISCORD_ALLOWED_USERS", "alice@evil.example"),
])
def test_generic_bare_id_alias_does_not_grant_authority(principal_env, monkeypatch, platform, env, user_id):
    monkeypatch.setenv(env, "alice")
    assert not authorized(platform, user_id)
    monkeypatch.setenv(env, user_id)
    assert authorized(platform, user_id)


def test_simplex_contact_id_is_not_an_address_prefix(principal_env, monkeypatch):
    monkeypatch.setenv("SIMPLEX_ALLOWED_USERS", "4")
    assert not authorized(principal_env, "4@evil.example", "4")


@pytest.mark.parametrize("platform,env", [(Platform.WHATSAPP, "WHATSAPP_ALLOWED_USERS"),
                                          (Platform.WHATSAPP_CLOUD, "WHATSAPP_CLOUD_ALLOWED_USERS")])
def test_whatsapp_owned_jid_alias_remains_authorized(principal_env, monkeypatch, platform, env):
    monkeypatch.setenv(env, "15550000001")
    assert authorized(platform, "15550000001:7@s.whatsapp.net")
    assert not authorized(platform, "15550000002:7@s.whatsapp.net")


@pytest.mark.parametrize("contact,name,expected", [(4, "renamed", True), (99, "Alice", False), (99, "4", False)])
def test_native_simplex_event_to_principal_authority(principal_env, monkeypatch, contact, name, expected):
    from tests.gateway._plugin_adapter_loader import load_plugin_adapter
    monkeypatch.setenv("SIMPLEX_ALLOWED_USERS", "4,Alice")
    adapter = load_plugin_adapter("simplex").SimplexAdapter(
        PlatformConfig(enabled=True, extra={"ws_url": "ws://127.0.0.1:5225"})
    )
    events = []
    adapter._enqueue_text_event = events.append
    asyncio.run(adapter._handle_chat_item({
        "chatInfo": {"type": "direct", "contact": {"contactId": contact, "localDisplayName": name}},
        "chatItem": {"chatDir": {"type": "directRcv"}, "content": {
            "type": "rcvMsgContent", "msgContent": {"type": "text", "text": "Test-owned request"}
        }, "meta": {"itemId": 1}},
    }))
    assert len(events) == 1
    source = events[0].source
    assert source.user_id == str(contact)
    assert source.user_name == name
    runner, _ = _make_runner(principal_env, GatewayConfig(platforms={principal_env: PlatformConfig(enabled=True)}))
    assert runner._is_user_authorized(source) is expected


@pytest.mark.parametrize("contact,name,expected", [(4, "renamed", True), (99, "Alice", False), (99, "4", False)])
def test_native_direct_profile_display_name_fallback(principal_env, monkeypatch, contact, name, expected):
    from tests.gateway._plugin_adapter_loader import load_plugin_adapter
    monkeypatch.setenv("SIMPLEX_ALLOWED_USERS", "4,Alice")
    adapter = load_plugin_adapter("simplex").SimplexAdapter(PlatformConfig(enabled=True))
    events = []
    adapter._enqueue_text_event = events.append
    asyncio.run(adapter._handle_chat_item({
        "chatInfo": {"type": "direct", "contact": {"contactId": contact, "profile": {"displayName": name}}},
        "chatItem": {"chatDir": {"type": "directRcv"}, "content": {
            "type": "rcvMsgContent", "msgContent": {"type": "text", "text": "Test-owned fallback"}
        }},
    }))
    assert len(events) == 1
    assert events[0].source.user_id == str(contact)
    assert events[0].source.user_name == name
    runner, _ = _make_runner(principal_env, GatewayConfig(platforms={principal_env: PlatformConfig(enabled=True)}))
    assert runner._is_user_authorized(events[0].source) is expected


@pytest.mark.parametrize("member,name,fallback,expected", [(4, "renamed", False, True),
                                                         (99, "Alice", False, False),
                                                         (99, "4", True, False)])
def test_native_group_member_display_collision(principal_env, monkeypatch, member, name, fallback, expected):
    from tests.gateway._plugin_adapter_loader import load_plugin_adapter
    monkeypatch.setenv("SIMPLEX_ALLOWED_USERS", "4,Alice")
    monkeypatch.setenv("SIMPLEX_GROUP_ALLOWED", "23")
    adapter = load_plugin_adapter("simplex").SimplexAdapter(PlatformConfig(enabled=True))
    events = []
    adapter._enqueue_text_event = events.append
    member_data = {"memberId": member}
    member_data.update({"memberProfile": {"displayName": name}} if fallback else {"localDisplayName": name})
    asyncio.run(adapter._handle_chat_item({
        "chatInfo": {"type": "group", "groupInfo": {"groupId": 23, "localDisplayName": "Test group"}},
        "chatItem": {"chatDir": {"type": "groupRcv", "groupMember": member_data}, "content": {
            "type": "rcvMsgContent", "msgContent": {"type": "text", "text": "Test-owned group request"}
        }},
    }))
    assert len(events) == 1
    source = events[0].source
    assert source.user_id == str(member)
    assert source.user_name == name
    assert source.chat_id == "group:23"
    runner, _ = _make_runner(principal_env, GatewayConfig(platforms={principal_env: PlatformConfig(enabled=True)}))
    assert runner._is_user_authorized(source) is expected


def test_pairing_grant_is_bound_to_simplex_profile(principal_env):
    from agent import secret_scope
    runner, _ = _make_runner(principal_env, GatewayConfig(multiplex_profiles=True))
    paired = MagicMock()
    paired.is_approved.side_effect = lambda platform, user_id: platform == "simplex" and user_id == "4"
    unpaired = MagicMock()
    unpaired.is_approved.return_value = False
    runner.pairing_stores = {"A": paired, "B": unpaired}
    previous = secret_scope.is_multiplex_active()
    secret_scope.set_multiplex_active(True)
    token = secret_scope.set_secret_scope({})
    try:
        for profile, expected in (("A", True), ("B", False)):
            source = SessionSource(platform=principal_env, user_id="4", user_name="Alice",
                                   chat_id="4", chat_type="dm", profile=profile)
            assert runner._is_user_authorized(source) is expected
        paired.is_approved.assert_any_call("simplex", "4")
        unpaired.is_approved.assert_any_call("simplex", "4")
    finally:
        secret_scope.reset_secret_scope(token)
        secret_scope.set_multiplex_active(previous)


def test_scoped_simplex_allowlist_miss_does_not_inherit_launch_profile(principal_env, monkeypatch):
    from agent import secret_scope
    monkeypatch.setenv("SIMPLEX_ALLOWED_USERS", "4")
    monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "4")
    monkeypatch.setenv("SIMPLEX_ALLOW_ALL_USERS", "true")
    monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
    previous = secret_scope.is_multiplex_active()
    secret_scope.set_multiplex_active(True)
    try:
        for scoped, expected in (({"SIMPLEX_ALLOWED_USERS": "4"}, True), ({}, False)):
            token = secret_scope.set_secret_scope(scoped)
            try:
                assert authorized(principal_env, "4", "Alice") is expected
            finally:
                secret_scope.reset_secret_scope(token)
    finally:
        secret_scope.set_multiplex_active(previous)
