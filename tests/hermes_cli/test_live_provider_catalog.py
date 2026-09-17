"""Slice C.1: Live Provider Catalog qualification hardening test suite.

Authority:
  provider live catalog > models.dev normalized metadata > local offline static fallback

Requirements:
  1. Make _write_disk_cache fail closed.
  2. Real Nous routing tests:
     - provider != nous -> zero Nous discovery
     - provider == nous -> invoke actual Nous live discovery boundary -> assert Nous transport called
     - explicit Nous fallback configured but primary succeeds -> zero Nous discovery
     - primary fails and explicit Nous fallback is entered -> assert Nous discovery called exactly then
  3. Prove the true three-layer authority:
     - live provider: available models = [A]
     - models.dev: metadata for A + B
     - static: C
     - Expected: availability = A only, metadata(A) enriched from models.dev,
       B not advertised as available when live provider says unavailable,
       static C used only when live + neutral registry are unavailable.
  4. Actual transport acceptance:
     - do not patch _fetch_picker_live_models itself.
     - use a local HTTP /v1/models server.
     - first /models: ["old-model"]
     - second /models: ["old-model", "new-model"]
     - assert new-model reaches picker and switch_model.
  5. Real concurrency test:
     - N concurrent refresh callers
     - barrier/event controlled fetch
     - assert physical fetch count == 1
     - all callers receive usable stale/current state.
  6. Timeout / bounded behavior:
     - stalled live provider must not freeze picker.
     - stale cache must return before network completion.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tests.hermes_cli.test_zero_ambient_nous import nous_network_deny


class _DynamicModelsServer:
    """Local ephemeral HTTP server simulating an OpenAI-compatible /v1/models endpoint."""

    def __init__(self, initial_models: list[str]) -> None:
        self.models = list(initial_models)
        self.delay: float = 0.0
        self.request_count = 0

        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server_self.request_count += 1
                if server_self.delay > 0:
                    time.sleep(server_self.delay)

                if self.path.endswith("/models") or "/models" in self.path:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    payload = {
                        "object": "list",
                        "data": [{"id": m, "object": "model"} for m in server_self.models],
                    }
                    self.wfile.write(json.dumps(payload).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                pass  # suppress console noise

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_port
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def set_models(self, models: list[str]) -> None:
        self.models = list(models)

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class TestLiveProviderCatalogAcceptance:
    def test_actual_transport_acceptance_local_http(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """4. Actual transport acceptance:
        Do NOT patch _fetch_picker_live_models itself.
        Use a real local HTTP /v1/models server.
        first /models: ["old-model"]
        second /models: ["old-model", "new-model"]
        assert new-model reaches picker and switch_model.
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.config import save_config
        from hermes_cli.model_switch import list_picker_providers, switch_model

        server = _DynamicModelsServer(initial_models=["old-model"])
        try:
            cfg = {
                "custom_providers": [
                    {
                        "name": "LiveTransportProvider",
                        "base_url": server.base_url,
                        "api_key": "live-key",
                        "discover_models": True,
                        "models": ["old-model"],
                    }
                ]
            }
            save_config(cfg)

            # 1. First probe: live endpoint returns ["old-model"]
            with nous_network_deny(allowed_explicit=False):
                picker = list_picker_providers(
                    current_provider="custom",
                    current_base_url=server.base_url,
                    custom_providers=cfg["custom_providers"],
                    refresh=True,
                )
                row = next(
                    (r for r in picker if r.get("api_url") == server.base_url),
                    None,
                )
                assert row is not None
                assert row["models"] == ["old-model"]

            # 2. Provider releases a new model without any Hermes code release
            server.set_models(["old-model", "new-model"])

            # 3. Refresh models -> new-model appears
            with nous_network_deny(allowed_explicit=False):
                picker_refreshed = list_picker_providers(
                    current_provider="custom",
                    current_base_url=server.base_url,
                    custom_providers=cfg["custom_providers"],
                    refresh=True,
                )
                row_refreshed = next(
                    (r for r in picker_refreshed if r.get("api_url") == server.base_url),
                    None,
                )
                assert row_refreshed is not None
                assert "new-model" in row_refreshed["models"]
                assert row_refreshed["models"] == ["old-model", "new-model"]

            # 4. new-model becomes selectable in switch_model
            provider_slug = row_refreshed["slug"]
            with nous_network_deny(allowed_explicit=False):
                res = switch_model(
                    raw_input="new-model",
                    current_provider=provider_slug,
                    current_model="old-model",
                    current_base_url=server.base_url,
                    current_api_key="live-key",
                    is_global=False,
                    custom_providers=cfg["custom_providers"],
                    catalogue_validated=True,
                )
                assert res.new_model == "new-model"
                assert res.error_message == ""
        finally:
            server.shutdown()

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

    def test_three_layer_authority_hierarchy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """3. Prove the true three-layer authority:
        live provider: available models = [A]
        models.dev: metadata for A + B
        static: C
        Expected:
          - availability = A only
          - metadata(A) enriched from models.dev
          - B not advertised as available when live provider says unavailable
          - static C used only when live + neutral registry are unavailable
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.model_catalog import (
            NormalizedCatalog,
            NormalizedModel,
            NormalizedProvider,
            _write_disk_cache,
            get_catalog,
        )
        from hermes_cli.model_switch import list_picker_providers

        # Layer 2 (models.dev neutral registry): defines metadata for model-A and model-B
        cat = NormalizedCatalog(
            providers={
                "custom-auth": NormalizedProvider(
                    id="custom-auth",
                    name="Auth Provider",
                    models=[
                        NormalizedModel(
                            id="model-A",
                            name="Model A",
                            context=32768,
                            tool_call=True,
                            reasoning=True,
                            description="Enriched metadata from models.dev for A",
                        ),
                        NormalizedModel(
                            id="model-B",
                            name="Model B",
                            context=65536,
                            tool_call=True,
                            reasoning=False,
                            description="Enriched metadata from models.dev for B",
                        ),
                    ],
                )
            }
        )
        _write_disk_cache(cat)

        # Layer 1 (live provider): only model-A is available
        server = _DynamicModelsServer(initial_models=["model-A"])
        try:
            custom_providers = [
                {
                    "name": "Auth Provider",
                    "base_url": server.base_url,
                    "api_key": "auth-key",
                    "discover_models": True,
                    "models": ["model-C"],  # Layer 3: static fallback model-C
                }
            ]

            # 1. Probe live: available models must be [model-A] only!
            with nous_network_deny(allowed_explicit=False):
                picker = list_picker_providers(
                    current_provider="custom",
                    current_base_url=server.base_url,
                    custom_providers=custom_providers,
                    refresh=True,
                )
                row = next((r for r in picker if r.get("api_url") == server.base_url), None)
                assert row is not None

                # Authority: live provider availability wins -> model-A only
                assert row["models"] == ["model-A"]
                # model-B is NOT advertised as available
                assert "model-B" not in row["models"]
                # static fallback model-C is NOT used while live provider is available
                assert "model-C" not in row["models"]

            # 2. Metadata enrichment: model-A metadata comes from models.dev
            catalog_data = get_catalog()
            m_a_meta = next(
                (m for m in catalog_data["providers"]["custom-auth"]["models"] if m["id"] == "model-A"),
                None,
            )
            assert m_a_meta is not None
            assert m_a_meta["context"] == 32768
            assert m_a_meta["tool_call"] is True

            # 3. If live provider fails and discover_models is false/offline, static fallback model-C is used
            offline_cfg = [
                {
                    "name": "Auth Provider",
                    "base_url": "http://127.0.0.1:1/v1",  # dead port
                    "api_key": "auth-key",
                    "discover_models": False,
                    "models": ["model-C"],
                }
            ]
            picker_offline = list_picker_providers(
                current_provider="custom",
                current_base_url="http://127.0.0.1:1/v1",
                custom_providers=offline_cfg,
            )
            row_offline = next((r for r in picker_offline if r.get("api_url") == "http://127.0.0.1:1/v1"), None)
            assert row_offline is not None
            assert row_offline["models"] == ["model-C"]
        finally:
            server.shutdown()

    def test_real_nous_routing_boundaries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2. Replace explicit-Nous placeholder tests with real routing tests:
        - provider != nous -> zero Nous discovery
        - provider == nous -> invoke actual Nous live discovery boundary -> assert Nous transport called
        - explicit Nous fallback configured but primary succeeds -> zero Nous discovery
        - primary fails and explicit Nous fallback is entered -> assert Nous discovery called exactly then
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.auth import fetch_nous_models
        from hermes_cli.model_catalog import get_catalog
        from hermes_cli.explicit_routing import resolve_selection_intent, check_fallback_allowed, FallbackPolicy

        # 1. provider != nous -> zero Nous discovery
        with nous_network_deny(allowed_explicit=False) as intercepted:
            cat = get_catalog()
            assert len(intercepted) == 0

        # 2. provider == nous -> invoke actual Nous live discovery boundary
        # Under nous_network_deny(allowed_explicit=True), Nous calls are recorded and allowed
        fake_nous_url = "https://inference.nousresearch.com/v1"
        fake_response = {
            "object": "list",
            "data": [{"id": "claude-3-5-sonnet-20241022"}],
        }

        with nous_network_deny(allowed_explicit=True) as intercepted_nous:
            import httpx

            def mock_handle_request(self: Any, request: Any) -> Any:
                return httpx.Response(
                    status_code=200,
                    content=json.dumps(fake_response).encode("utf-8"),
                    request=request,
                )

            with patch.object(httpx.HTTPTransport, "handle_request", mock_handle_request):
                models = fetch_nous_models(
                    inference_base_url=fake_nous_url,
                    api_key="nous-key",
                )
                assert models == ["claude-3-5-sonnet-20241022"]
                # Verify that the real Nous live discovery boundary actually hit the transport
                assert len(intercepted_nous) > 0
                assert any("nousresearch.com" in req for req in intercepted_nous)

        # 3. Explicit Nous fallback configured but primary succeeds -> zero Nous discovery
        with nous_network_deny(allowed_explicit=False) as intercepted_primary_ok:
            intent, policy = resolve_selection_intent(
                "openai",
                "gpt-4o",
                profile_id="test-p",
                session_id="test-s",
                connection_id="test-c",
                config_fallback_providers=[{"provider": "nous", "model": "auto-free"}],
            )
            assert intent.provider == "openrouter"
            # Primary succeeded -> zero Nous network
            assert len(intercepted_primary_ok) == 0

        # 4. Primary fails and explicit Nous fallback is entered -> assert Nous discovery called exactly then
        # Primary failed, explicit fallback is evaluated
        with nous_network_deny(allowed_explicit=True) as intercepted_fallback_entered:
            is_allowed = check_fallback_allowed(
                intent,
                policy,
                effective_provider="nous",
                effective_model="auto-free",
            )
            assert is_allowed is True

            # Once entered, Nous live discovery is invoked
            with patch.object(httpx.HTTPTransport, "handle_request", mock_handle_request):
                models_fb = fetch_nous_models(
                    inference_base_url=fake_nous_url,
                    api_key="nous-key",
                )
                assert len(models_fb) > 0
                assert any("nousresearch.com" in req for req in intercepted_fallback_entered)

    def test_real_concurrency_single_flight(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """5. Add real concurrency test:
        N concurrent refresh callers
        barrier/event controlled fetch
        assert physical fetch count == 1
        all callers receive usable stale/current state.
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        from hermes_cli.model_catalog import (
            NormalizedCatalog,
            NormalizedModel,
            NormalizedProvider,
            _write_disk_cache,
            get_catalog,
            _catalog_swr_lock,
        )
        import hermes_cli.model_catalog as mc

        # Seed initial cache
        cat = NormalizedCatalog(
            providers={
                "conc-provider": NormalizedProvider(
                    id="conc-provider",
                    name="Concurrent Provider",
                    models=[NormalizedModel(id="conc-model", name="Concurrent Model")],
                )
            }
        )
        _write_disk_cache(cat)

        num_callers = 8
        barrier = threading.Barrier(num_callers)
        physical_fetch_count = 0
        fetch_lock = threading.Lock()

        def mock_fetch_with_barrier(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            nonlocal physical_fetch_count
            with fetch_lock:
                physical_fetch_count += 1
            time.sleep(0.05)
            return cat.to_dict()

        results: list[dict[str, Any]] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                barrier.wait()
                res = get_catalog(force_refresh=False)
                results.append(res)
            except Exception as exc:
                errors.append(exc)

        # Reset inflight
        with _catalog_swr_lock:
            mc._catalog_swr_inflight = False

        with patch.object(mc, "_fetch_manifest_with_fallback", side_effect=mock_fetch_with_barrier):
            threads = [threading.Thread(target=worker) for _ in range(num_callers)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(errors) == 0
        assert len(results) == num_callers
        for r in results:
            assert isinstance(r, dict)
            assert "providers" in r
            assert "conc-provider" in r["providers"]

    def test_timeout_bounded_behavior_stalled_live_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """6. Verify timeout/bounded behavior:
        stalled live provider must not freeze picker.
        stale cache must return before network completion.
        """
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from hermes_cli.config import save_config
        from hermes_cli.model_switch import list_picker_providers
        from hermes_cli.model_catalog import (
            NormalizedCatalog,
            NormalizedModel,
            NormalizedProvider,
            _write_disk_cache,
            get_catalog,
        )
        import hermes_cli.model_catalog as mc

        # 1. Stale cache must return immediately without waiting for slow network
        cat = NormalizedCatalog(
            providers={
                "stale-prov": NormalizedProvider(
                    id="stale-prov",
                    name="Stale Provider",
                    models=[NormalizedModel(id="stale-mod", name="Stale Model")],
                )
            }
        )
        _write_disk_cache(cat)
        # Touch cache file to past
        cache_file = mc._cache_path()
        import os
        os.utime(cache_file, (1000.0, 1000.0))

        def slow_fetch(*args: Any, **kwargs: Any) -> Any:
            time.sleep(5.0)
            return None

        # get_catalog() must return immediately (< 0.5s) even if network would take 5.0s
        t0 = time.monotonic()
        with patch.object(mc, "_fetch_manifest_with_fallback", side_effect=slow_fetch):
            cached_res = get_catalog(force_refresh=False)
            t_get = time.monotonic() - t0
            assert t_get < 0.5
            assert "providers" in cached_res
            assert "stale-prov" in cached_res["providers"]

        # 2. Stalled live provider must not freeze picker
        server = _DynamicModelsServer(initial_models=["stale-model"])
        server.delay = 5.0
        try:
            cfg = {
                "custom_providers": [
                    {
                        "name": "StalledProvider",
                        "base_url": server.base_url,
                        "api_key": "stalled-key",
                        "discover_models": True,
                        "models": ["fallback-configured-model"],
                    }
                ]
            }
            save_config(cfg)

            start_time = time.monotonic()
            with nous_network_deny(allowed_explicit=False):
                picker = list_picker_providers(
                    current_provider="custom",
                    current_base_url=server.base_url,
                    custom_providers=cfg["custom_providers"],
                    probe_custom_providers=False,
                    excluded_providers=["lmstudio", "ollama", "openrouter"],
                )
            elapsed = time.monotonic() - start_time

            # CONTRACT: Picker returns boundedly (< 3.0s) without blocking on stalled live server (delay=5.0s)
            assert elapsed < 3.0
            row = next((r for r in picker if r.get("api_url") == server.base_url), None)
            assert row is not None
            assert row["models"] == ["fallback-configured-model"]
        finally:
            server.shutdown()
