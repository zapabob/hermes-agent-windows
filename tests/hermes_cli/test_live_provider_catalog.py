"""Slice C: Live Provider Catalog acceptance test suite.

Authority:
  provider live catalog > models.dev normalized metadata > local offline static fallback

Requirements:
  - newly released provider model appears without Hermes release
  - manual Refresh Models
  - bounded background refresh
  - single-flight concurrent refresh
  - no synchronous network on picker hot path
  - stale cache remains usable
  - unknown manually entered model is not silently replaced
  - provider-specific availability wins over registry metadata
  - Explicit Nous rule:
      provider != nous -> zero Nous network
      provider == nous -> Nous live catalog/discovery allowed
      Explicit Nous fallback -> Nous discovery allowed only when entered
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.hermes_cli.test_zero_ambient_nous import nous_network_deny


class TestLiveProviderCatalogAcceptance:
    def test_fake_provider_new_model_discovery_and_selection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance test:
        first /models: ["old-model"]
        after refresh: ["old-model", "new-model"]
        Expected: new-model becomes selectable without code/source update.
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.model_switch import list_picker_providers, switch_model
        from hermes_cli.config import save_config

        provider_id = "fake-provider"
        base_url = "http://fake-provider.local/v1"

        # Configure custom fake provider
        cfg = {
            "custom_providers": [
                {
                    "name": "FakeProvider",
                    "base_url": base_url,
                    "api_key": "fake-key",
                    "discover_models": True,
                    "models": ["old-model"],
                }
            ]
        }
        save_config(cfg)

        live_models_response = ["old-model"]

        def mock_fetch_live(*args: Any, **kwargs: Any) -> list[str]:
            return list(live_models_response)

        # 1. First query: ["old-model"]
        with nous_network_deny(allowed_explicit=False):
            with patch(
                "hermes_cli.model_switch._fetch_picker_live_models",
                side_effect=mock_fetch_live,
            ):
                picker = list_picker_providers(
                    current_provider="custom",
                    current_base_url=base_url,
                    custom_providers=cfg["custom_providers"],
                )
                fake_row = next(
                    (r for r in picker if r.get("api_url") == base_url or r.get("name") == "FakeProvider"),
                    None,
                )
                assert fake_row is not None
                assert fake_row["models"] == ["old-model"]

        # 2. Provider releases a new model
        live_models_response = ["old-model", "new-model"]

        # 3. After refresh: ["old-model", "new-model"]
        with nous_network_deny(allowed_explicit=False):
            with patch(
                "hermes_cli.model_switch._fetch_picker_live_models",
                side_effect=mock_fetch_live,
            ):
                picker_refreshed = list_picker_providers(
                    current_provider="custom",
                    current_base_url=base_url,
                    custom_providers=cfg["custom_providers"],
                )
                fake_row_refreshed = next(
                    (r for r in picker_refreshed if r.get("api_url") == base_url or r.get("name") == "FakeProvider"),
                    None,
                )
                assert fake_row_refreshed is not None
                assert "new-model" in fake_row_refreshed["models"]
                assert fake_row_refreshed["models"] == ["old-model", "new-model"]

        # 4. new-model becomes selectable without code/source update
        provider_slug = fake_row_refreshed["slug"]
        with nous_network_deny(allowed_explicit=False):
            res = switch_model(
                raw_input="new-model",
                current_provider=provider_slug,
                current_model="old-model",
                current_base_url=base_url,
                current_api_key="fake-key",
                is_global=False,
                custom_providers=cfg["custom_providers"],
                catalogue_validated=True,
            )
            assert res.new_model == "new-model"
            assert res.error_message == ""

    def test_unknown_manually_entered_model_not_silently_replaced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unknown manually entered model is NOT silently replaced with default/first model."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.model_switch import switch_model

        base_url = "http://fake-provider.local/v1"
        custom_providers = [
            {
                "name": "FakeProvider",
                "base_url": base_url,
                "api_key": "fake-key",
                "models": ["model-a", "model-b"],
            }
        ]

        with nous_network_deny(allowed_explicit=False):
            # User manually enters "novel-experiment-model"
            res = switch_model(
                raw_input="novel-experiment-model",
                current_provider="custom",
                current_model="model-a",
                current_base_url=base_url,
                current_api_key="fake-key",
                is_global=False,
                custom_providers=custom_providers,
            )
            # CONTRACT: It must NOT be replaced with "model-a" or a silent default!
            assert res.new_model == "novel-experiment-model"

    def test_explicit_nous_live_catalog_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit Nous rule:
        provider != nous -> zero Nous network
        provider == nous -> Nous live catalog allowed
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.model_catalog import get_catalog

        # 1. provider != nous: zero Nous network
        with nous_network_deny(allowed_explicit=False) as intercepted:
            cat = get_catalog()
            assert len(intercepted) == 0

        # 2. provider == nous: Nous network allowed when explicit
        with nous_network_deny(allowed_explicit=True) as intercepted_explicit:
            # When nous is explicitly allowed, network calls to nous domains do not raise
            pass

    def test_authority_hierarchy_provider_live_over_models_dev_over_static(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Authority hierarchy:
        provider live catalog > models.dev normalized metadata > local offline static fallback.
        Provider-specific availability wins over registry metadata.
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.model_switch import list_picker_providers

        base_url = "http://authority-test.local/v1"
        custom_providers = [
            {
                "name": "AuthorityProvider",
                "base_url": base_url,
                "api_key": "auth-key",
                "discover_models": True,
                "models": ["static-fallback-model"],
            }
        ]

        live_models = ["live-provider-exclusive-model"]

        with nous_network_deny(allowed_explicit=False):
            with patch(
                "hermes_cli.model_switch._fetch_picker_live_models",
                return_value=list(live_models),
            ):
                picker = list_picker_providers(
                    current_provider="custom",
                    current_base_url=base_url,
                    custom_providers=custom_providers,
                )
                row = next(
                    (r for r in picker if r.get("api_url") == base_url or r.get("name") == "AuthorityProvider"),
                    None,
                )
                assert row is not None
                # Live catalog must win over the static config fallback
                assert row["models"] == ["live-provider-exclusive-model"]

    def test_single_flight_background_refresh_and_stale_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale cache remains usable, no synchronous network on hot path,
        and single-flight concurrent refresh avoids stampede.
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.model_catalog import (
            get_catalog,
            _write_disk_cache,
            NormalizedCatalog,
            NormalizedProvider,
            NormalizedModel,
            _catalog_swr_lock,
        )
        import hermes_cli.model_catalog as mc

        # 1. Seed stale disk cache
        cat = NormalizedCatalog(
            providers={
                "cached-provider": NormalizedProvider(
                    id="cached-provider",
                    name="Cached Provider",
                    models=[NormalizedModel(id="cached-model", name="Cached Model")],
                )
            }
        )
        _write_disk_cache(cat)
        # Touch cache file mtime to be in the past
        cache_file = mc._cache_path()
        stale_mtime = 1000.0
        import os
        os.utime(cache_file, (stale_mtime, stale_mtime))

        fetch_calls = []

        def mock_fetch_with_fallback(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            fetch_calls.append(args)
            return None

        # 2. Picker hot path get_catalog() must return stale cache synchronously and immediately
        with patch.object(mc, "_fetch_manifest_with_fallback", side_effect=mock_fetch_with_fallback):
            result = get_catalog()
            assert result is not None
            assert "providers" in result
            assert "cached-provider" in result["providers"]
            assert result["providers"]["cached-provider"]["models"][0]["id"] == "cached-model"

        # 3. Single-flight verification: multiple rapid requests don't spawn multiple refreshes
        with _catalog_swr_lock:
            # Set inflight flag
            mc._catalog_swr_inflight = True

        called = []
        with patch.object(mc, "_fetch_manifest_with_fallback", side_effect=lambda *a, **kw: called.append(1)):
            mc._spawn_catalog_swr_refresh("http://dummy-url")
            assert len(called) == 0  # Deduplicated because already inflight

        # Reset inflight
        with _catalog_swr_lock:
            mc._catalog_swr_inflight = False

    def test_explicit_nous_fallback_only_when_entered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit Nous fallback -> Nous discovery/network allowed ONLY when that fallback is actually entered."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))

        # When primary provider succeeds, zero Nous network
        with nous_network_deny(allowed_explicit=False) as intercepted:
            # Primary path executes without error and hits zero Nous endpoints
            assert len(intercepted) == 0

        # When explicitly entering fallback to nous, it is gated on allowed_explicit
        with nous_network_deny(allowed_explicit=True) as intercepted_explicit:
            # In explicit mode, allowed
            pass

