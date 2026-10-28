"""Atomic delegation draft validation / merge contracts (T03)."""

from __future__ import annotations

import pytest

from hermes_cli.delegation_config import (
    DelegationConfigError,
    merge_delegation_config,
    schema_affecting_changes,
    validate_delegation_draft,
)


def test_provider_alone_is_valid_partial_but_merge_keeps_other_keys() -> None:
    cleaned = validate_delegation_draft({"provider": "openai", "model": "gpt-test"})
    assert cleaned["provider"] == "openai"
    merged = merge_delegation_config(
        {"delegation": {"max_iterations": 50, "api_key": "secret-on-disk"}, "timezone": "UTC"},
        cleaned,
    )
    assert merged["timezone"] == "UTC"
    assert merged["delegation"]["max_iterations"] == 50
    assert merged["delegation"]["api_key"] == "secret-on-disk"
    assert merged["delegation"]["model"] == "gpt-test"


def test_rejects_api_key_from_draft() -> None:
    with pytest.raises(DelegationConfigError, match="api_key"):
        validate_delegation_draft({"api_key": "sk-leak"})


def test_rejects_unknown_fields_atomically() -> None:
    with pytest.raises(DelegationConfigError, match="unknown"):
        validate_delegation_draft({"model": "ok", "not_a_real_key": 1})


def test_rejects_invalid_limits_without_partial_apply() -> None:
    with pytest.raises(DelegationConfigError, match="max_concurrent_children"):
        validate_delegation_draft({"max_concurrent_children": 0})
    with pytest.raises(DelegationConfigError, match="max_spawn_depth"):
        validate_delegation_draft({"max_spawn_depth": 0})


def test_empty_fallback_disables_inherit_null_omits() -> None:
    disabled = validate_delegation_draft({"fallback_providers": []})
    assert disabled["fallback_providers"] == []
    merged_disabled = merge_delegation_config(
        {"delegation": {"fallback_providers": [{"provider": "a", "model": "b"}]}},
        disabled,
    )
    assert merged_disabled["delegation"]["fallback_providers"] == []

    inherit = validate_delegation_draft({"fallback_providers": None})
    assert inherit["fallback_providers"] is None
    merged_inherit = merge_delegation_config(
        {"delegation": {"fallback_providers": [{"provider": "a", "model": "b"}]}},
        inherit,
    )
    assert "fallback_providers" not in merged_inherit["delegation"]


def test_fallback_chain_normalized() -> None:
    cleaned = validate_delegation_draft(
        {
            "fallback_providers": [
                {"provider": "openai", "model": "gpt-4o"},
                "anthropic/claude-sonnet",
            ]
        }
    )
    assert cleaned["fallback_providers"] == [
        {"provider": "openai", "model": "gpt-4o"},
        {"provider": "anthropic", "model": "claude-sonnet"},
    ]


def test_incomplete_fallback_row_rejected() -> None:
    with pytest.raises(DelegationConfigError):
        validate_delegation_draft({"fallback_providers": [{"provider": "openai", "model": ""}]})


def test_schema_affecting_change_detection() -> None:
    before = {"max_spawn_depth": 1, "model": "a"}
    after = {"max_spawn_depth": 2, "model": "a"}
    assert schema_affecting_changes(before, after) == ["max_spawn_depth"]


def test_unknown_backend_rejected_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.delegation_registry.backend_status",
        lambda name: (None, f"Delegation backend '{name}' is not installed"),
    )
    with pytest.raises(DelegationConfigError, match="not installed"):
        validate_delegation_draft({"backend": "totally-missing"})


def test_available_backend_accepted(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.delegation_registry.backend_status",
        lambda name: (object(), ""),
    )
    cleaned = validate_delegation_draft({"backend": "Model_Map"})
    assert cleaned["backend"] == "model_map"


def test_backend_change_is_schema_affecting() -> None:
    assert schema_affecting_changes({"backend": "default"}, {"backend": "model_map"}) == [
        "backend"
    ]
