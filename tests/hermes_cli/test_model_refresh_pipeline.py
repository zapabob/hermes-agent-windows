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


def test_helper_swallows_network_failures(monkeypatch):
    import agent.models_dev as models_dev

    def boom(**kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(models_dev, "fetch_models_dev", boom)
    assert models_mod.refresh_models_dev_catalog() is False
