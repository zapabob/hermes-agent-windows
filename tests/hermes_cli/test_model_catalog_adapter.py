"""RED tests for Slice B.1: models.dev neutral catalog source adapter.

Validates that models.dev serves as a neutral catalog source via explicit
adapter boundaries, internal NormalizedCatalog shape, and robust zero-Nous
invariants.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.hermes_cli.test_zero_ambient_nous import nous_network_deny


SAMPLE_MODELS_DEV_FIXTURE: dict[str, Any] = {
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic",
        "models": {
            "claude-opus-4-6": {
                "id": "claude-opus-4-6",
                "name": "Claude Opus 4.6",
                "reasoning": True,
                "tool_call": True,
                "modalities": {"input": ["text", "image"], "output": ["text"]},
                "limit": {"context": 1000000, "output": 128000},
                "release_date": "2026-04-20",
            },
            "claude-sonnet-4-6": {
                "id": "claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "reasoning": False,
                "tool_call": True,
                "modalities": {"input": ["text"], "output": ["text"]},
                "limit": {"context": 200000, "output": 64000},
                "release_date": "2026-03-15",
            },
        },
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "models": {
            "gpt-5": {
                "id": "gpt-5",
                "name": "GPT-5",
                "reasoning": True,
                "tool_call": True,
                "modalities": {"input": ["text", "image"], "output": ["text"]},
                "limit": {"context": 256000, "output": 32000},
                "release_date": "2026-02-10",
            },
            "gpt-4o": {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "reasoning": False,
                "tool_call": True,
                "modalities": {"input": ["text", "image"], "output": ["text"]},
                "limit": {"context": 128000, "output": 16384},
                "release_date": "2024-05-13",
            },
        },
    },
    "openrouter": {
        "id": "openrouter",
        "name": "OpenRouter",
        "models": {
            "anthropic/claude-sonnet-4-6": {
                "id": "anthropic/claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6 (OpenRouter)",
                "reasoning": False,
                "tool_call": True,
                "limit": {"context": 200000, "output": 64000},
            },
        },
    },
}

SAMPLE_LEGACY_HERMES_FIXTURE: dict[str, Any] = {
    "version": 1,
    "updated_at": "2026-08-29T02:38:32Z",
    "metadata": {
        "source": "hermes-agent legacy repo",
    },
    "providers": {
        "openrouter": {
            "metadata": {
                "display_name": "OpenRouter",
            },
            "models": [
                {
                    "id": "anthropic/claude-sonnet-4.6",
                    "description": "fast and capable",
                    "default": True,
                },
                {
                    "id": "openai/gpt-5",
                    "description": "flagship model",
                },
            ],
        },
    },
}


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_1_models_dev_fetch_parse_validation() -> None:
    """1. Fetch/parse a representative models.dev fixture succeeds after adapter normalization."""
    from hermes_cli.model_catalog import parse_models_dev, NormalizedCatalog

    with nous_network_deny(allowed_explicit=False):
        normalized = parse_models_dev(SAMPLE_MODELS_DEV_FIXTURE)
        assert normalized is not None
        assert isinstance(normalized, NormalizedCatalog)
        assert len(normalized.providers) >= 2


def test_2_at_least_two_providers_and_multiple_models_survive() -> None:
    """2. At least two providers and multiple models survive normalization."""
    from hermes_cli.model_catalog import parse_models_dev

    with nous_network_deny(allowed_explicit=False):
        catalog = parse_models_dev(SAMPLE_MODELS_DEV_FIXTURE)
        assert catalog is not None
        assert "anthropic" in catalog.providers
        assert "openai" in catalog.providers

        anthropic_models = catalog.providers["anthropic"].models
        assert len(anthropic_models) >= 2
        model_ids = {m.id for m in anthropic_models}
        assert "claude-opus-4-6" in model_ids
        assert "claude-sonnet-4-6" in model_ids


def test_3_metadata_survives_normalization() -> None:
    """3. Metadata survives where available: reasoning, tool_call, modalities, context, release_date."""
    from hermes_cli.model_catalog import parse_models_dev

    with nous_network_deny(allowed_explicit=False):
        catalog = parse_models_dev(SAMPLE_MODELS_DEV_FIXTURE)
        assert catalog is not None
        anthropic = catalog.providers["anthropic"]
        opus = next(m for m in anthropic.models if m.id == "claude-opus-4-6")

        assert opus.reasoning is True
        assert opus.tool_call is True
        assert opus.context == 1000000
        assert opus.release_date == "2026-04-20"
        assert "image" in opus.modalities.get("input", []) or "image" in opus.modalities


def test_4_malformed_models_dev_payload_fails_closed() -> None:
    """4. Malformed models.dev payload fails closed (returns None, not partial garbage)."""
    from hermes_cli.model_catalog import parse_models_dev

    with nous_network_deny(allowed_explicit=False):
        assert parse_models_dev({}) is None
        assert parse_models_dev([]) is None
        assert parse_models_dev("not a dict") is None
        assert parse_models_dev({"broken": "not a provider dict"}) is None
        assert parse_models_dev({"anthropic": {"models": "not a dict or list"}}) is None


def test_5_legacy_hermes_catalog_fixture_parseable() -> None:
    """5. Legacy Hermes catalog fixture remains parseable for operator configured compatibility."""
    from hermes_cli.model_catalog import parse_legacy_hermes_catalog, NormalizedCatalog

    with nous_network_deny(allowed_explicit=False):
        catalog = parse_legacy_hermes_catalog(SAMPLE_LEGACY_HERMES_FIXTURE)
        assert catalog is not None
        assert isinstance(catalog, NormalizedCatalog)
        assert "openrouter" in catalog.providers
        models = catalog.providers["openrouter"].models
        assert len(models) == 2
        assert models[0].id == "anthropic/claude-sonnet-4.6"
        assert models[0].default is True


def test_6_models_dev_unavailable_stale_disk_cache_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """6. When models.dev is unavailable, stale normalized disk cache remains usable."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import model_catalog

    model_catalog.reset_cache()
    # Populate disk cache with normalized payload
    normalized = model_catalog.parse_models_dev(SAMPLE_MODELS_DEV_FIXTURE)
    assert normalized is not None
    model_catalog._write_disk_cache(normalized.to_dict())

    # Simulate network failure on fetch
    with nous_network_deny(allowed_explicit=False):
        with patch.object(model_catalog, "_fetch_manifest", return_value=None):
            catalog = model_catalog.get_catalog(force_refresh=True)
            assert catalog is not None
            providers = catalog.get("providers", {})
            assert "anthropic" in providers or "openrouter" in providers


def test_7_no_cache_static_fallback_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """7. When no cache and network fails, local static fallback remains usable."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import model_catalog

    model_catalog.reset_cache()

    with nous_network_deny(allowed_explicit=False):
        with patch.object(model_catalog, "_fetch_manifest", return_value=None):
            # Test get_catalog with fallback_to_static=True
            catalog = model_catalog.get_catalog(force_refresh=True, fallback_to_static=True)
            assert isinstance(catalog, dict)
            assert "providers" in catalog
            assert len(catalog["providers"]) >= 2

            # Test direct accessor
            static_cat = model_catalog.get_static_fallback_catalog()
            assert isinstance(static_cat, dict)
            assert "providers" in static_cat


def test_8_no_request_to_nous_in_any_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """8. Under NO circumstances does any operation hit Nous unless explicitly selected."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import model_catalog

    model_catalog.reset_cache()

    with nous_network_deny(allowed_explicit=False) as intercepted:
        # 1. Parse models.dev
        model_catalog.parse_models_dev(SAMPLE_MODELS_DEV_FIXTURE)
        # 2. Parse legacy catalog
        model_catalog.parse_legacy_hermes_catalog(SAMPLE_LEGACY_HERMES_FIXTURE)
        # 3. Access curated openrouter models
        model_catalog.get_curated_openrouter_models()
        # 4. Verify default fallback URLs contain zero Nous domains
        for url in model_catalog.DEFAULT_CATALOG_FALLBACK_URLS:
            assert "nousresearch.com" not in url.lower()
        assert len(intercepted) == 0
