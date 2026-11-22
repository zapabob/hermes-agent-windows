"""A manual model refresh must reach the upstream registry, not just the wrapper cache.

The per-provider disk cache is only the outer layer: models.dev keeps its own
4-hour snapshot. Refreshing only the outer layer re-wraps stale model ids and
new provider models never appear in the picker.
"""

from __future__ import annotations

from unittest.mock import patch

import hermes_cli.models as models_mod
from hermes_cli.inventory import build_models_payload, load_picker_context


def test_force_refresh_helper_is_called_once_per_payload():
    ctx = load_picker_context().with_overrides(current_provider="openrouter", current_model="m1")
    row = {
        "slug": "openrouter",
        "name": "OpenRouter",
        "models": ["m1"],
        "total_models": 1,
        "is_current": True,
        "source": "built-in",
    }
    with patch(
        "hermes_cli.models.refresh_models_dev_catalog", return_value=True
    ) as refresh_catalog, patch(
        "hermes_cli.model_switch.list_authenticated_providers", return_value=[row]
    ):
        build_models_payload(ctx, refresh=True)

    refresh_catalog.assert_called_once_with()


def test_normal_picker_open_does_not_force_a_registry_fetch():
    ctx = load_picker_context().with_overrides(current_provider="openrouter", current_model="m1")
    row = {
        "slug": "openrouter",
        "name": "OpenRouter",
        "models": ["m1"],
        "total_models": 1,
        "is_current": True,
        "source": "built-in",
    }
    with patch(
        "hermes_cli.models.refresh_models_dev_catalog", return_value=True
    ) as refresh_catalog, patch(
        "hermes_cli.model_switch.list_authenticated_providers", return_value=[row]
    ):
        build_models_payload(ctx)

    refresh_catalog.assert_not_called()


def _nous_payload_rows():
    return [
        {
            "slug": "nous",
            "name": "Nous Portal",
            "models": ["anthropic/claude-fable-5.2", "upstage/solar-mini4:free"],
            "total_models": 2,
            "is_current": True,
            "source": "built-in",
        },
        {
            "slug": "openrouter",
            "name": "OpenRouter",
            "models": ["a"],
            "total_models": 1,
            "is_current": False,
            "source": "built-in",
        },
    ]


def test_nous_free_only_hides_paid_models(monkeypatch):
    import hermes_cli.config as config_mod
    import hermes_cli.models as models_mod
    from hermes_cli.inventory import build_models_payload, load_picker_context

    monkeypatch.setattr(
        config_mod,
        "load_config",
        lambda: {"model_catalog": {"providers": {"nous": {"free_only": True}}}},
    )
    monkeypatch.setattr(
        models_mod,
        "nous_free_model_ids",
        lambda: ["upstage/solar-mini4:free", "tencent/hy4-flash:free"],
    )
    ctx = load_picker_context().with_overrides(current_provider="openrouter", current_model="a")
    with patch(
        "hermes_cli.model_switch.list_authenticated_providers",
        return_value=_nous_payload_rows(),
    ):
        payload = build_models_payload(ctx)

    nous = next(r for r in payload["providers"] if r["slug"] == "nous")
    openrouter = next(r for r in payload["providers"] if r["slug"] == "openrouter")
    assert nous["models"] == ["upstage/solar-mini4:free", "tencent/hy4-flash:free"]
    assert nous["unavailable_models"] == []
    assert nous["free_tier"] is True
    assert "anthropic/claude-fable-5.2" not in nous["pricing"]
    assert openrouter["models"] == ["a"]


def test_nous_free_only_is_opt_in(monkeypatch):
    import hermes_cli.config as config_mod
    import hermes_cli.models as models_mod
    from hermes_cli.inventory import build_models_payload, load_picker_context

    monkeypatch.setattr(config_mod, "load_config", lambda: {})
    monkeypatch.setattr(
        models_mod,
        "nous_free_model_ids",
        lambda: ["upstage/solar-mini4:free"],
    )
    ctx = load_picker_context().with_overrides(current_provider="openrouter", current_model="a")
    with patch(
        "hermes_cli.model_switch.list_authenticated_providers",
        return_value=_nous_payload_rows(),
    ):
        payload = build_models_payload(ctx)

    nous = next(r for r in payload["providers"] if r["slug"] == "nous")
    assert "anthropic/claude-fable-5.2" in nous["models"]


def test_forced_refresh_also_updates_the_nous_manifest(monkeypatch):
    import hermes_cli.model_catalog as model_catalog

    calls = []

    def fake_nous_refresh():
        calls.append("nous")
        return True

    monkeypatch.setattr(model_catalog, "refresh_nous_catalog", fake_nous_refresh)
    models_mod.refresh_models_dev_catalog()
    assert calls == ["nous"]


def test_nous_curated_models_prefer_the_vendor_manifest(monkeypatch):
    import hermes_cli.model_catalog as model_catalog

    official = {
        "providers": {
            "nous": {
                "models": [
                    {"id": "anthropic/claude-fable-5.2"},
                    {"id": "openai/gpt-6.2-astra"},
                ]
            }
        }
    }
    monkeypatch.setattr(model_catalog, "get_nous_catalog", lambda **kwargs: official)
    monkeypatch.setattr(
        model_catalog,
        "_get_provider_block",
        lambda provider, **kwargs: {"models": [{"id": "anthropic/claude-fable-5"}]},
    )

    ids = model_catalog.get_curated_nous_models()
    assert ids == ["anthropic/claude-fable-5.2", "openai/gpt-6.2-astra"]


def test_helper_swallows_network_failures(monkeypatch):
    import agent.models_dev as models_dev
    import hermes_cli.model_catalog as model_catalog

    def boom(**kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(models_dev, "fetch_models_dev", boom)
    monkeypatch.setattr(model_catalog, "refresh_nous_catalog", boom)
    assert models_mod.refresh_models_dev_catalog() is False
