"""Daybreak is a per-request, account-catalog capability, never a model-name guess."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from agent import codex_service_tiers as tiers
from agent import model_metadata as metadata
from agent.chat_completion_helpers import build_api_kwargs
from agent.transports.codex import ResponsesApiTransport

BASE = "https://chatgpt.com/backend-api/codex"
CATALOGS = {
    "account-a": [
        {"slug": "gpt-5.4", "context_window": 272000,
         "service_tiers": [{"id": "priority"}],
         "available_access_programs": {"cyber": ["standard", "daybreak_blue"]}},
        {"slug": "gpt-5.4-mini", "context_window": 272000,
         "available_access_programs": {"cyber": ["standard"]}},
        {"slug": "gpt-unlisted-program", "context_window": 272000},
    ],
    "account-b": [
        {"slug": "gpt-5.4", "context_window": 272000,
         "available_access_programs": {"cyber": ["standard"]}},
    ],
}


def token(account: str) -> str:
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": account}}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"test.{encoded}.test"


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(metadata, "_codex_oauth_context_cache", {})
    monkeypatch.setattr(tiers, "_catalogs", {})
    calls = []

    def get(url, **kwargs):
        account = kwargs["headers"]["ChatGPT-Account-Id"]
        calls.append(account)
        return SimpleNamespace(status_code=200, json=lambda: {"models": CATALOGS[account]})

    monkeypatch.setattr(metadata, "requests", SimpleNamespace(get=get), raising=False)
    monkeypatch.setattr(metadata, "_ensure_requests", lambda: None)
    monkeypatch.setattr("agent.models_dev.get_model_capabilities", lambda *a, **kw: None)
    return calls


def agent(**changes):
    values = dict(
        api_mode="codex_responses", provider="openai-codex", base_url=BASE,
        _base_url_hostname="chatgpt.com", _base_url_lower=BASE.lower(),
        api_key=token("account-a"), model="gpt-5.4", daybreak=True,
        tools=[], reasoning_config={"enabled": True, "effort": "high"},
        request_overrides={}, session_id="daybreak-test", max_tokens=1024,
        _get_transport=ResponsesApiTransport,
        _prepare_messages_for_non_vision_model=lambda messages: messages,
        _resolved_api_call_timeout=lambda: 30,
        _github_models_reasoning_extra_body=lambda: None,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def wire(instance):
    return build_api_kwargs(instance, [{"role": "user", "content": "hello"}])


def test_empty_request_overrides_still_carry_the_enabled_program(catalog):
    instance = agent()
    assert wire(instance)["extra_body"]["access_programs"] == {"cyber": "daybreak_blue"}
    assert instance.request_overrides == {}
    assert catalog == ["account-a"]


@pytest.mark.parametrize("changes", [
    {"daybreak": False}, {"daybreak": "true"}, {"daybreak": 1},
    {"model": "gpt-5.4-mini"}, {"model": "gpt-unlisted-program"},
    {"model": "gpt-5.4-unadvertised-snapshot"},
    {"api_key": token("account-b")}, {"api_key": "sk-not-an-account-token"},
    {"provider": "openai-api", "base_url": "https://api.openai.com/v1"},
    {"provider": "custom:local", "base_url": "http://127.0.0.1:8080/v1"},
    {"base_url": "https://proxy.example/codex"},
])
def test_no_program_leaks_to_unconfirmed_models_accounts_or_routes(catalog, changes):
    assert "access_programs" not in (wire(agent(**changes)).get("extra_body") or {})


def test_model_and_account_switches_recheck_without_mutating_preferences(catalog):
    instance = agent(request_overrides={"extra_body": {"kept": 7}})
    assert wire(instance)["extra_body"]["access_programs"]["cyber"] == "daybreak_blue"
    instance.model = "gpt-5.4-mini"
    assert "access_programs" not in wire(instance)["extra_body"]
    instance.model = "gpt-5.4"
    instance.api_key = token("account-b")
    assert "access_programs" not in wire(instance)["extra_body"]
    instance.api_key = token("account-a")
    assert wire(instance)["extra_body"]["access_programs"]["cyber"] == "daybreak_blue"
    assert instance.request_overrides == {"extra_body": {"kept": 7}}
    assert catalog == ["account-a", "account-b"]


def test_daybreak_fast_and_reasoning_coexist_on_the_wire(catalog):
    saved = {"service_tier": "priority", "extra_body": {"access_programs": {"other": "kept"}}}
    instance = agent(request_overrides=saved)
    result = wire(instance)
    assert result["service_tier"] == "priority"
    assert result["reasoning"]["effort"] == "high"
    assert result["extra_body"]["access_programs"] == {"other": "kept", "cyber": "daybreak_blue"}
    assert saved == {"service_tier": "priority", "extra_body": {"access_programs": {"other": "kept"}}}


def test_context_variant_uses_its_exact_base_catalog_entry(catalog):
    assert wire(agent(model="gpt-5.4-900k"))["extra_body"]["access_programs"]["cyber"] == "daybreak_blue"


def test_effective_model_override_is_checked_instead_of_stale_agent_model(catalog):
    result = wire(agent(request_overrides={"model": "gpt-5.4-mini"}))
    assert "access_programs" not in (result.get("extra_body") or {})


def test_expired_entitlement_is_not_reused_when_refresh_fails(catalog, monkeypatch):
    instance = agent()
    assert wire(instance)["extra_body"]["access_programs"]["cyber"] == "daybreak_blue"
    now = tiers.time.time()
    monkeypatch.setattr(tiers.time, "time", lambda: now + 3601)
    monkeypatch.setattr(metadata.requests, "get", lambda *a, **kw: SimpleNamespace(status_code=503))
    assert "access_programs" not in (wire(instance).get("extra_body") or {})


def test_catalog_refresh_revokes_program_independently_of_speed(catalog):
    instance = agent(request_overrides={"service_tier": "priority"})
    assert "access_programs" in wire(instance)["extra_body"]
    key = metadata._codex_oauth_token_fingerprint(instance.api_key)
    tiers.remember_catalog(key, [{"slug": instance.model,
                                  "service_tiers": [{"id": "priority"}],
                                  "available_access_programs": {"cyber": ["standard"]}}])
    result = wire(instance)
    assert result["service_tier"] == "priority"
    assert "access_programs" not in (result.get("extra_body") or {})


@pytest.mark.parametrize("programs", [None, "daybreak_blue", {"cyber": "daybreak_blue"}, {"cyber": [True]}])
def test_malformed_catalog_never_grants_entitlement(catalog, programs):
    instance = agent()
    key = metadata._codex_oauth_token_fingerprint(instance.api_key)
    tiers.remember_catalog(key, [{"slug": instance.model, "available_access_programs": programs}])
    assert "access_programs" not in (wire(instance).get("extra_body") or {})


def test_catalog_without_context_window_can_offer_daybreak(catalog):
    instance = agent()
    key = metadata._codex_oauth_token_fingerprint(instance.api_key)
    tiers.remember_catalog(key, [{"slug": instance.model,
                                  "available_access_programs": {"cyber": ["daybreak_blue"]}}])
    assert wire(instance)["extra_body"]["access_programs"]["cyber"] == "daybreak_blue"


def test_inventory_capability_uses_the_same_confirmed_account_catalog(catalog, monkeypatch):
    from hermes_cli import auth
    from hermes_cli.inventory import _apply_capabilities

    monkeypatch.setattr(auth, "_load_auth_store", lambda: {"providers": {
        "openai-codex": {"tokens": {"access_token": token("account-a")}}}})
    rows = [
        {"slug": "openai-codex", "models": ["gpt-5.4", "gpt-5.4-mini", "gpt-unlisted-program"]},
        {"slug": "openai-api", "models": ["gpt-5.4"]},
        {"slug": "openai-codex", "api_url": "http://127.0.0.1:8080/v1", "models": ["gpt-5.4"]},
        {"slug": "openai-codex", "api_url": BASE, "is_user_defined": True, "models": ["gpt-5.4"]},
    ]
    _apply_capabilities(rows)
    assert rows[0]["capabilities"]["gpt-5.4"].get("daybreak") is True
    assert not rows[0]["capabilities"]["gpt-5.4-mini"].get("daybreak", False)
    assert not rows[0]["capabilities"]["gpt-unlisted-program"].get("daybreak", False)
    assert not rows[1]["capabilities"]["gpt-5.4"].get("daybreak", False)
    assert not rows[2]["capabilities"]["gpt-5.4"].get("daybreak", False)
    assert not rows[3]["capabilities"]["gpt-5.4"].get("daybreak", False)


def test_cold_inventory_remains_network_free_then_uses_a_warmed_catalog(catalog, monkeypatch):
    from hermes_cli import auth
    from hermes_cli.inventory import _apply_capabilities

    monkeypatch.setattr(auth, "_load_auth_store", lambda: {"providers": {
        "openai-codex": {"tokens": {"access_token": token("account-a")}}}})
    rows = [{"slug": "openai-codex", "models": ["gpt-5.4"]}]
    _apply_capabilities(rows, cache_only=True)
    assert not rows[0]["capabilities"]["gpt-5.4"].get("daybreak", False)
    assert catalog == []
    wire(agent())
    _apply_capabilities(rows, cache_only=True)
    assert rows[0]["capabilities"]["gpt-5.4"].get("daybreak") is True
    assert catalog == ["account-a"]


@pytest.mark.parametrize("bad_entries", [None, 7, "not-a-catalog"])
def test_malformed_catalog_is_unknown_and_does_not_break_a_turn(catalog, monkeypatch, bad_entries):
    monkeypatch.setattr(metadata.requests, "get", lambda *a, **kw: SimpleNamespace(
        status_code=200, json=lambda: {"models": bad_entries}))
    result = wire(agent(request_overrides={"service_tier": "priority"}))
    assert result["service_tier"] == "priority"
    assert "access_programs" not in (result.get("extra_body") or {})


def test_inventory_never_borrows_the_launch_profiles_entitlement(tmp_path, catalog, monkeypatch):
    from pathlib import Path

    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.inventory import _apply_capabilities

    launch = tmp_path / ".hermes"
    worker = launch / "profiles" / "work"
    worker.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(launch))
    store = {"providers": {"openai-codex": {"tokens": {
        "access_token": token("account-a"), "refresh_token": "test-refresh"}}}}
    (launch / "auth.json").write_text(json.dumps(store), encoding="utf-8")
    wire(agent())  # the launch account's catalog is warm
    scope = set_hermes_home_override(worker)
    try:
        rows = [{"slug": "openai-codex", "models": ["gpt-5.4"]}]
        _apply_capabilities(rows, cache_only=True)
        assert not rows[0]["capabilities"]["gpt-5.4"].get("daybreak", False)
    finally:
        reset_hermes_home_override(scope)
