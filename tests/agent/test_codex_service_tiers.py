"""Selected Codex account service-tier negotiation at request construction."""
import base64
import json
from types import SimpleNamespace

import pytest

from agent import codex_service_tiers
from agent import model_metadata
from agent.chat_completion_helpers import build_api_kwargs
from agent.transports.codex import ResponsesApiTransport

BASE = "https://chatgpt.com/backend-api/codex"


def _token(account_id: str) -> str:
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def _agent(*, account_id: str, model: str = "gpt-5.4", tier: str = "priority"):
    return SimpleNamespace(
        api_mode="codex_responses",
        provider="openai-codex",
        base_url=BASE,
        _base_url_hostname="chatgpt.com",
        _base_url_lower=BASE.lower(),
        api_key=_token(account_id),
        model=model,
        tools=[],
        reasoning_config=None,
        request_overrides={"service_tier": tier},
        session_id="test-session",
        max_tokens=1024,
        _get_transport=ResponsesApiTransport,
        _prepare_messages_for_non_vision_model=lambda messages: messages,
        _resolved_api_call_timeout=lambda: 30,
        _github_models_reasoning_extra_body=lambda: None,
    )


def _build(agent):
    return build_api_kwargs(agent, [{"role": "user", "content": "hello"}])


def _patch_catalogs(monkeypatch, catalogs_by_account):
    calls = []

    def get(url, **kwargs):
        account_id = kwargs["headers"]["ChatGPT-Account-Id"]
        calls.append((url, account_id))
        response = catalogs_by_account[account_id]
        return SimpleNamespace(
            status_code=response[0],
            json=lambda: response[1],
        )

    monkeypatch.setattr(model_metadata, "requests", SimpleNamespace(get=get), raising=False)
    monkeypatch.setattr(model_metadata, "_ensure_requests", lambda: None)
    monkeypatch.setattr(model_metadata, "_codex_oauth_context_cache", {})
    monkeypatch.setattr(codex_service_tiers, "_catalogs", {})
    return calls


def test_request_builder_omits_priority_when_selected_account_does_not_advertise_it(monkeypatch):
    """The wire tier must respect the active OAuth account's model catalog."""
    calls = _patch_catalogs(monkeypatch, {
        "account-a": (200, {"models": [{"slug": "gpt-5.4", "context_window": 272000, "service_tiers": []}]}),
    })
    agent = _agent(account_id="account-a")

    kwargs = _build(agent)

    assert "service_tier" not in kwargs
    assert agent.request_overrides == {"service_tier": "priority"}
    assert len(calls) == 1
    assert calls[0][1] == "account-a"


def test_request_builder_keeps_tier_catalogs_separate_after_account_rotation(monkeypatch):
    calls = _patch_catalogs(monkeypatch, {
        "account-a": (200, {"models": [{"slug": "gpt-5.4", "service_tiers": [{"id": "priority"}]}]}),
        "account-b": (200, {"models": [{"slug": "gpt-5.4", "service_tiers": []}]}),
    })
    first = _agent(account_id="account-a")
    second = _agent(account_id="account-b")

    first_kwargs = _build(first)
    second_kwargs = _build(second)

    assert first_kwargs["service_tier"] == "priority"
    assert "service_tier" not in second_kwargs
    assert first.request_overrides == second.request_overrides == {"service_tier": "priority"}
    assert [account for _, account in calls] == ["account-a", "account-b"]


def test_request_builder_uses_selected_model_and_only_falls_back_from_ultrafast(monkeypatch):
    calls = _patch_catalogs(monkeypatch, {
        "account-a": (200, {"models": [
            {"slug": "gpt-5.4", "service_tiers": [{"id": "priority"}]},
            {"slug": "gpt-5.4-mini", "service_tiers": [{"id": "priority"}, {"id": "ultrafast"}]},
        ]}),
    })
    agent = _agent(account_id="account-a", model="gpt-5.4", tier="ultrafast")

    fallback_kwargs = _build(agent)
    agent.model = "gpt-5.4-mini"
    agent.request_overrides = {"service_tier": "priority"}
    priority_kwargs = _build(agent)

    assert fallback_kwargs["service_tier"] == "priority"
    assert priority_kwargs["service_tier"] == "priority"
    assert len(calls) == 1
    assert agent.request_overrides == {"service_tier": "priority"}


def test_unknown_tier_metadata_preserves_explicit_preference(monkeypatch):
    calls = _patch_catalogs(monkeypatch, {
        "account-a": (200, {"models": [{"slug": "gpt-5.4", "context_window": 272000}]}),
    })
    agent = _agent(account_id="account-a")

    kwargs = _build(agent)

    assert kwargs["service_tier"] == "priority"
    assert agent.request_overrides == {"service_tier": "priority"}
    assert [account for _, account in calls] == ["account-a"]


def test_expired_catalog_probe_failure_does_not_reuse_stale_tiers(monkeypatch):
    calls = _patch_catalogs(monkeypatch, {"account-a": (503, {})})
    cache_key = model_metadata._codex_oauth_token_fingerprint(_token("account-a"))
    monkeypatch.setattr(codex_service_tiers.time, "time", lambda: 5000.0)
    codex_service_tiers._catalogs[cache_key] = (
        {"gpt-5.4": frozenset({"ultrafast"})},
        0.0,
    )
    agent = _agent(account_id="account-a", tier="priority")

    kwargs = _build(agent)

    assert kwargs["service_tier"] == "priority"
    assert agent.request_overrides == {"service_tier": "priority"}
    assert [account for _, account in calls] == ["account-a"]


def test_missing_tier_cache_refreshes_catalog_despite_fresh_context_cache(monkeypatch):
    calls = _patch_catalogs(monkeypatch, {
        "account-a": (200, {"models": [{"slug": "gpt-5.4", "context_window": 272000, "service_tiers": []}]}),
    })
    agent = _agent(account_id="account-a")
    cache_key = model_metadata._codex_oauth_token_fingerprint(agent.api_key)
    context_rows = {"gpt-5.4": 272000}
    cached_at = model_metadata.time.time()
    model_metadata._codex_oauth_context_cache[cache_key] = (context_rows, cached_at)

    kwargs = _build(agent)

    assert "service_tier" not in kwargs
    assert [account for _, account in calls] == ["account-a"]
    assert model_metadata._codex_oauth_context_cache[cache_key] == (context_rows, cached_at)


def test_missing_tier_cache_probe_failure_preserves_fresh_context_and_preference(monkeypatch):
    calls = _patch_catalogs(monkeypatch, {"account-a": (503, {})})
    agent = _agent(account_id="account-a")
    cache_key = model_metadata._codex_oauth_token_fingerprint(agent.api_key)
    context_rows = {"gpt-5.4": 272000}
    cached_at = model_metadata.time.time()
    model_metadata._codex_oauth_context_cache[cache_key] = (context_rows, cached_at)

    kwargs = _build(agent)

    assert kwargs["service_tier"] == "priority"
    assert agent.request_overrides == {"service_tier": "priority"}
    assert [account for _, account in calls] == ["account-a"]
    assert model_metadata._codex_oauth_context_cache[cache_key] == (context_rows, cached_at)


@pytest.mark.parametrize(
    ("provider", "base_url", "hostname", "api_key"),
    [
        ("openai-codex", "https://proxy.example/v1", "proxy.example", _token("account-a")),
        ("openrouter", "https://openrouter.ai/api/v1", "openrouter.ai", _token("account-a")),
        ("openai-codex", BASE, "chatgpt.com", "sk-test-key"),
    ],
)
def test_non_oauth_or_non_official_routes_keep_existing_override(monkeypatch, provider, base_url, hostname, api_key):
    calls = []

    def unexpected_get(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("tier lookup must not run for this route")

    monkeypatch.setattr(model_metadata, "requests", SimpleNamespace(get=unexpected_get), raising=False)
    monkeypatch.setattr(model_metadata, "_ensure_requests", lambda: None)
    monkeypatch.setattr(model_metadata, "_codex_oauth_context_cache", {})
    monkeypatch.setattr(codex_service_tiers, "_catalogs", {})
    agent = _agent(account_id="account-a")
    agent.provider = provider
    agent.base_url = base_url
    agent._base_url_hostname = hostname
    agent._base_url_lower = base_url.lower()
    agent.api_key = api_key

    kwargs = _build(agent)

    assert kwargs["service_tier"] == "priority"
    assert agent.request_overrides == {"service_tier": "priority"}
    assert calls == []
