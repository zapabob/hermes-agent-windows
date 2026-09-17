"""Unit tests for hermes_cli.explicit_routing."""

from __future__ import annotations

from hermes_cli.explicit_routing import (
    FallbackPolicy,
    ModelSelectionIntent,
    check_fallback_allowed,
    is_ambient_nous_active,
    model_unavailable_error,
    normalize_model_name,
    resolve_selection_intent,
)


def test_resolve_selection_intent_defaults() -> None:
    intent, policy = resolve_selection_intent(
        "openrouter",
        "gpt-4o",
        profile_id="default",
        session_id="sess-1",
        connection_id="conn-1",
    )
    assert intent.provider == "openrouter"
    assert intent.model == "gpt-4o"
    assert intent.profile_id == "default"
    assert intent.session_id == "sess-1"
    assert intent.connection_id == "conn-1"
    assert intent.persistence_scope == "session"
    assert intent.source == "user"
    assert policy.allow_cross_provider is False
    assert policy.same_provider_credential_rotation is True


def test_resolve_selection_intent_explicit_provider_override() -> None:
    intent, policy = resolve_selection_intent(
        "openai",
        "claude-3-5-sonnet",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
        explicit_provider="anthropic",
    )
    assert intent.provider == "anthropic"
    assert intent.source == "explicit"


def test_resolve_selection_intent_with_config_fallbacks() -> None:
    fallbacks = [
        {"provider": "openrouter", "model": "anthropic/claude-3-5-sonnet"},
        {"provider": "nvidia", "model": "nemotron"},
    ]
    intent, policy = resolve_selection_intent(
        "openai",
        "gpt-4o",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
        config_fallback_providers=fallbacks,
    )
    assert len(policy.explicit_routes) == 2
    assert policy.explicit_routes[0] == ("openrouter", "anthropic/claude-3-5-sonnet")
    assert policy.explicit_routes[1] == ("nvidia", "nemotron")


def test_check_fallback_allowed_same_provider() -> None:
    intent = ModelSelectionIntent(
        provider="openai",
        model="gpt-4o",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
    )
    policy = FallbackPolicy(same_provider_credential_rotation=True)
    assert check_fallback_allowed(
        intent, policy, effective_provider="openai", effective_model="gpt-4o-mini"
    )


def test_check_fallback_allowed_explicit_route() -> None:
    intent = ModelSelectionIntent(
        provider="openai",
        model="gpt-4o",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
    )
    policy = FallbackPolicy(
        explicit_routes=(("openrouter", "anthropic/claude-3-5-sonnet"),),
        allow_cross_provider=False,
    )
    assert check_fallback_allowed(
        intent,
        policy,
        effective_provider="openrouter",
        effective_model="anthropic/claude-3-5-sonnet",
    )
    assert not check_fallback_allowed(
        intent,
        policy,
        effective_provider="gemini",
        effective_model="gemini-2.5-flash",
    )


def test_model_unavailable_error() -> None:
    intent = ModelSelectionIntent(
        provider="nvidia",
        model="nemotron",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
    )
    err = model_unavailable_error(intent, reason="capacity exceeded")
    assert "capacity exceeded" in err["error"]
    assert err["selected_provider"] == "nvidia"
    assert err["selected_model"] == "nemotron"
    assert "Retry" in err["actions"]


def test_is_ambient_nous_active() -> None:
    nous_intent = ModelSelectionIntent(
        provider="nous",
        model="auto-free",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
    )
    openai_intent = ModelSelectionIntent(
        provider="openai",
        model="gpt-4o",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
    )
    assert is_ambient_nous_active(nous_intent) is True
    assert is_ambient_nous_active(openai_intent) is False


def test_normalize_model_name() -> None:
    assert normalize_model_name("gpt-4o", "openai") == "gpt-4o"
