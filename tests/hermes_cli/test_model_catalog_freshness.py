"""Catalog freshness contract for every model-picker surface.

The picker must never present an unexamined catalog as fresh, and must never
declare a selected model retired based on stale data. These tests pin the
shared substrate in ``hermes_cli.models`` / ``hermes_cli.inventory``:

- cache rows carry a schema version, so a fetch-contract fix takes effect
  instead of being masked by yesterday's rows;
- provenance distinguishes live / stale / curated / fallback / unknown;
- only authoritative (fresh live) catalogs may report a model as not listed;
- in-repo static catalogs age out of "fresh" but stay usable.
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

import hermes_cli.models as models_mod
from hermes_cli.models import (
    CuratedFallbackModels,
    StaticCatalogModels,
    _PROVIDER_MODELS_CACHE_SCHEMA,
    _PROVIDER_MODELS_CURATED_TTL,
    _PROVIDER_MODELS_CACHE_TTL,
    _load_provider_models_cache,
    _provider_result_entry,
    _save_provider_models_cache,
    cached_provider_model_ids,
    current_model_catalog_status,
    provider_catalog_provenance,
)


def _entry(models, *, age_seconds=0.0, fp="fp", **extra):
    return {"fp": fp, "at": time.time() - age_seconds, "models": list(models), **extra}


class TestCacheSchema:
    def test_rows_from_an_older_schema_are_a_miss(self, tmp_path):
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / "provider_models_cache.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"openrouter": _entry(["stale-model"])}), encoding="utf-8"
        )
        # No `_schema`: written by a build that predates the freshness contract.
        assert _load_provider_models_cache() == {}

    def test_save_stamps_the_current_schema_and_round_trips(self):
        _save_provider_models_cache({"openrouter": _entry(["m1"])})
        loaded = _load_provider_models_cache()
        assert loaded["_schema"] == _PROVIDER_MODELS_CACHE_SCHEMA
        assert loaded["openrouter"]["models"] == ["m1"]

    def test_unknown_schema_is_also_a_miss(self):
        _save_provider_models_cache({"openrouter": _entry(["m1"])})
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / "provider_models_cache.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_schema"] = _PROVIDER_MODELS_CACHE_SCHEMA + 1
        path.write_text(json.dumps(data), encoding="utf-8")
        assert _load_provider_models_cache() == {}

    def test_targeted_clear_removes_a_row_from_an_older_schema(self):
        """An explicit clear must work on legacy files, not be gated away."""
        from hermes_cli.models import clear_provider_models_cache
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / "provider_models_cache.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"legacy": {"models": ["m1"]}}), encoding="utf-8")

        clear_provider_models_cache("legacy")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "legacy" not in data
        assert data["_schema"] == _PROVIDER_MODELS_CACHE_SCHEMA


class TestAutomaticExpiry:
    """Every cached row is written with the trust window it was fetched under."""

    @pytest.fixture(autouse=True)
    def _stable_fingerprint(self):
        with patch.object(models_mod, "_credential_fingerprint", return_value="fp"):
            yield

    def test_live_entry_gets_a_one_hour_expiry(self):
        with patch.object(models_mod.time, "time", return_value=1_000.0):
            entry = models_mod._provider_result_entry("fp", ["m1"])
        assert entry["expires_at"] == pytest.approx(1_000.0 + _PROVIDER_MODELS_CACHE_TTL)
        assert "fallback" not in entry
        assert "source" not in entry

    def test_curated_entry_keeps_the_longer_trust_window(self):
        with patch.object(models_mod.time, "time", return_value=1_000.0):
            entry = models_mod._provider_result_entry(
                "fp", StaticCatalogModels(["m1"])
            )
        assert entry["source"] == "curated"
        assert entry["expires_at"] == pytest.approx(1_000.0 + _PROVIDER_MODELS_CURATED_TTL)

    def test_fallback_entry_gets_the_short_retry_window(self):
        with patch.object(models_mod.time, "time", return_value=1_000.0):
            entry = models_mod._provider_result_entry(
                "fp", CuratedFallbackModels(["m1"])
            )
        assert entry["fallback"] is True
        assert entry["expires_at"] == pytest.approx(
            1_000.0 + models_mod._PROVIDER_MODELS_FALLBACK_TTL
        )

    def test_provenance_honours_a_stamped_expiry(self):
        # A curated row must not be downgraded to the 1h live TTL just because
        # the TTL constant changed after it was written.
        cache = {
            "openrouter": _entry(
                ["m1"], age_seconds=10, source="curated",
                expires_at=time.time() + 123_456,
            )
        }
        prov = provider_catalog_provenance("openrouter", cache=cache, now=time.time())
        assert prov["trust_expires_at"] == pytest.approx(cache["openrouter"]["expires_at"])

    def test_legacy_row_still_derives_its_expiry(self):
        cache = {"openrouter": _entry(["m1"], age_seconds=10)}
        prov = provider_catalog_provenance("openrouter", cache=cache, now=time.time())
        assert prov["trust_expires_at"] == pytest.approx(
            cache["openrouter"]["at"] + _PROVIDER_MODELS_CACHE_TTL
        )

    def test_catalog_meta_announces_expiry_stamping(self):
        from hermes_cli.models import catalog_freshness_meta

        assert catalog_freshness_meta()["stamps_expiry"] is True


class TestProvenance:
    @pytest.fixture(autouse=True)
    def _stable_fingerprint(self):
        with patch.object(models_mod, "_credential_fingerprint", return_value="fp"):
            yield

    def test_fresh_live_row_is_authoritative(self):
        now = time.time()
        cache = {"openrouter": _entry(["m1"], age_seconds=10)}
        prov = provider_catalog_provenance("openrouter", cache=cache, now=now)
        assert prov["source"] == "live"
        assert prov["authoritative"] is True
        assert prov["stale"] is False
        assert prov["model_count"] == 1

    def test_expired_but_servable_row_is_stale_not_authoritative(self):
        now = time.time()
        cache = {"openrouter": _entry(["m1"], age_seconds=_PROVIDER_MODELS_CACHE_TTL + 60)}
        prov = provider_catalog_provenance("openrouter", cache=cache, now=now)
        assert prov["source"] == "stale"
        assert prov["authoritative"] is False
        assert prov["stale"] is True

    def test_static_catalog_row_is_curated_with_its_own_trust_window(self):
        now = time.time()
        cache = {"openrouter": _entry(["m1"], age_seconds=10, source="curated")}
        prov = provider_catalog_provenance("openrouter", cache=cache, now=now)
        assert prov["source"] == "curated"
        assert prov["authoritative"] is False
        assert prov["ttl_seconds"] == _PROVIDER_MODELS_CURATED_TTL
        assert prov["trust_expires_at"] == pytest.approx(now - 10 + _PROVIDER_MODELS_CURATED_TTL)

    def test_live_failure_fallback_is_flagged(self):
        cache = {"openrouter": _entry(["m1"], age_seconds=5, fallback=True)}
        prov = provider_catalog_provenance("openrouter", cache=cache, now=time.time())
        assert prov["source"] == "fallback"
        assert prov["fallback"] is True
        assert prov["authoritative"] is False

    def test_foreign_credential_row_is_unknown(self):
        cache = {"openrouter": _entry(["m1"], fp="someone-elses-key")}
        prov = provider_catalog_provenance("openrouter", cache=cache, now=time.time())
        assert prov["source"] == "unknown"
        assert prov["authoritative"] is False


class TestCurrentModelStatus:
    @pytest.fixture(autouse=True)
    def _stable_fingerprint(self):
        with patch.object(models_mod, "_credential_fingerprint", return_value="fp"):
            yield

    def test_model_in_fresh_live_catalog_is_listed(self):
        cache = {"openrouter": _entry(["alpha", "beta"])}
        status = current_model_catalog_status("openrouter", "beta", cache=cache, now=time.time())
        assert status["state"] == "listed"
        assert status["reason"] == "in_live_catalog"

    def test_model_missing_from_fresh_live_catalog_is_not_listed(self):
        cache = {"openrouter": _entry(["alpha"])}
        status = current_model_catalog_status("openrouter", "retired", cache=cache, now=time.time())
        assert status["state"] == "not_listed"
        assert status["reason"] == "missing_from_live_catalog"

    def test_alias_equivalent_ids_count_as_listed(self):
        cache = {"openrouter": _entry(["Kimi-K3"])}
        status = current_model_catalog_status("openrouter", "kimi-k3", cache=cache, now=time.time())
        assert status["state"] == "listed"

    def test_stale_catalog_never_claims_a_model_is_gone(self):
        cache = {
            "openrouter": _entry(["alpha"], age_seconds=_PROVIDER_MODELS_CACHE_TTL + 60)
        }
        status = current_model_catalog_status("openrouter", "retired", cache=cache, now=time.time())
        assert status["state"] == "unverified"
        assert status["reason"] == "catalog_not_authoritative"

    def test_curated_catalog_never_claims_a_model_is_gone(self):
        cache = {"openrouter": _entry(["alpha"], source="curated")}
        status = current_model_catalog_status("openrouter", "retired", cache=cache, now=time.time())
        assert status["state"] == "unverified"


class TestStaticCatalogTagging:
    def test_static_catalog_is_tagged_curated_not_a_failure(self):
        entry = _provider_result_entry("fp", StaticCatalogModels(["m1"]))
        assert entry["source"] == "curated"
        assert "fallback" not in entry

    def test_live_failure_fallback_keeps_its_short_retry_tag(self):
        entry = _provider_result_entry("fp", CuratedFallbackModels(["m1"]))
        assert entry["fallback"] is True
        assert "source" not in entry

    def test_ordinary_live_list_has_neither_tag(self):
        entry = _provider_result_entry("fp", ["m1"])
        assert "source" not in entry
        assert "fallback" not in entry

    def test_expired_curated_row_is_served_and_revalidated(self):
        cache = {
            "openrouter": _entry(
                ["m1"], age_seconds=_PROVIDER_MODELS_CURATED_TTL + 60, source="curated"
            )
        }
        with patch.object(models_mod, "_load_provider_models_cache", return_value=cache), \
             patch.object(models_mod, "_credential_fingerprint", return_value="fp"), \
             patch.object(models_mod, "_spawn_swr_refresh") as spawn, \
             patch.object(models_mod, "provider_model_ids") as live:
            out = cached_provider_model_ids("openrouter")
        assert out == ["m1"]
        spawn.assert_called_once_with("openrouter")
        live.assert_not_called()

    def test_fresh_curated_row_is_not_revalidated(self):
        cache = {"openrouter": _entry(["m1"], age_seconds=60, source="curated")}
        with patch.object(models_mod, "_load_provider_models_cache", return_value=cache), \
             patch.object(models_mod, "_credential_fingerprint", return_value="fp"), \
             patch.object(models_mod, "_spawn_swr_refresh") as spawn:
            out = cached_provider_model_ids("openrouter")
        assert out == ["m1"]
        spawn.assert_not_called()


class TestPayloadContract:
    @pytest.fixture(autouse=True)
    def _stable_fingerprint(self):
        with patch.object(models_mod, "_credential_fingerprint", return_value="fp"):
            yield

    def test_payload_exposes_freshness_and_model_status(self):
        from hermes_cli.inventory import build_models_payload, load_picker_context

        row = {
            "slug": "openrouter",
            "name": "OpenRouter",
            "models": ["alpha"],
            "total_models": 1,
            "is_current": True,
            "is_user_defined": False,
            "source": "built-in",
        }
        ctx = load_picker_context().with_overrides(
            current_provider="openrouter", current_model="retired"
        )
        _save_provider_models_cache({"openrouter": _entry(["alpha"])})
        with patch(
            "hermes_cli.model_switch.list_authenticated_providers", return_value=[row]
        ):
            payload = build_models_payload(ctx)

        assert payload["providers"][0]["slug"] == "moa"
        row_payload = next(
            provider for provider in payload["providers"] if provider["slug"] == "openrouter"
        )
        assert row_payload["catalog"]["source"] == "live"
        assert row_payload["catalog"]["authoritative"] is True
        assert payload["current_model_status"]["state"] == "not_listed"
        assert payload["current_model_status"]["model"] == "retired"
        assert payload["catalog_meta"]["cache_schema"] == _PROVIDER_MODELS_CACHE_SCHEMA

    def test_payload_reports_unverified_without_a_catalog_row(self):
        from hermes_cli.inventory import build_models_payload, load_picker_context

        row = {
            "slug": "openrouter",
            "name": "OpenRouter",
            "models": ["alpha"],
            "total_models": 1,
            "is_current": True,
            "is_user_defined": False,
            "source": "built-in",
        }
        ctx = load_picker_context().with_overrides(
            current_provider="openrouter", current_model="alpha"
        )
        with patch(
            "hermes_cli.model_switch.list_authenticated_providers", return_value=[row]
        ):
            payload = build_models_payload(ctx)

        row_payload = next(
            provider for provider in payload["providers"] if provider["slug"] == "openrouter"
        )
        assert row_payload["catalog"]["source"] == "unknown"
        assert payload["current_model_status"]["state"] == "unverified"

    def test_row_provided_catalog_is_preserved_and_feeds_the_status(self):
        """A custom endpoint row must keep the provenance its builder resolved.

        ``build_models_payload`` cannot re-derive it (no api_key/headers), so
        overwriting would silently downgrade a live custom catalog to unknown.
        """
        from hermes_cli.inventory import build_models_payload, load_picker_context

        row = {
            "slug": "custom:my-proxy",
            "name": "My proxy",
            "models": ["alpha"],
            "total_models": 1,
            "is_current": True,
            "is_user_defined": True,
            "source": "user-config",
            "api_url": "https://proxy.example/v1",
            "catalog": {
                "provider": "custom:my-proxy",
                "cache_key": "custom:https://proxy.example/v1",
                "source": "live",
                "fetched_at": time.time(),
                "age_seconds": 5.0,
                "stale": False,
                "fallback": False,
                "authoritative": True,
                "model_count": 1,
                "ttl_seconds": _PROVIDER_MODELS_CACHE_TTL,
                "trust_expires_at": time.time() + _PROVIDER_MODELS_CACHE_TTL,
                "cache_schema": _PROVIDER_MODELS_CACHE_SCHEMA,
            },
        }
        ctx = load_picker_context().with_overrides(
            current_provider="custom:my-proxy", current_model="retired"
        )
        cache = {"custom:https://proxy.example/v1": _entry(["alpha"])}
        with patch(
            "hermes_cli.model_switch.list_authenticated_providers", return_value=[row]
        ), patch.object(models_mod, "_load_provider_models_cache", return_value=cache):
            payload = build_models_payload(ctx)

        row_payload = next(
            provider
            for provider in payload["providers"]
            if provider["slug"] == "custom:my-proxy"
        )
        assert row_payload["catalog"]["source"] == "live"
        assert row_payload["catalog"]["cache_key"] == "custom:https://proxy.example/v1"
        # The URL-keyed cache row is what makes absence provable here.
        assert payload["current_model_status"]["state"] == "not_listed"


class TestCustomEndpointProvenance:
    def test_fingerprint_and_cache_key_describe_a_custom_row(self):
        cache = {"custom:https://proxy.example/v1": _entry(["m1"], fp="probe-fp")}
        prov = provider_catalog_provenance(
            "custom:my-proxy",
            cache=cache,
            cache_key="custom:https://proxy.example/v1",
            fingerprint="probe-fp",
            now=time.time(),
        )
        assert prov["source"] == "live"
        assert prov["provider"] == "custom:my-proxy"
        assert prov["cache_key"] == "custom:https://proxy.example/v1"
        assert prov["authoritative"] is True

    def test_custom_row_without_a_fingerprint_stays_unknown(self):
        cache = {"custom:https://proxy.example/v1": _entry(["m1"], fp="probe-fp")}
        prov = provider_catalog_provenance(
            "custom:my-proxy",
            cache=cache,
            cache_key="custom:https://proxy.example/v1",
            now=time.time(),
        )
        assert prov["source"] == "unknown"
        assert prov["authoritative"] is False

    def test_another_credential_does_not_borrow_the_custom_row(self):
        cache = {"custom:https://proxy.example/v1": _entry(["m1"], fp="probe-fp")}
        prov = provider_catalog_provenance(
            "custom:my-proxy",
            cache=cache,
            cache_key="custom:https://proxy.example/v1",
            fingerprint="someone-elses-key",
            now=time.time(),
        )
        assert prov["source"] == "unknown"

    def test_status_reads_the_cache_key_from_a_supplied_catalog(self):
        cache = {"custom:https://proxy.example/v1": _entry(["alpha"], fp="probe-fp")}
        catalog = provider_catalog_provenance(
            "custom:my-proxy",
            cache=cache,
            cache_key="custom:https://proxy.example/v1",
            fingerprint="probe-fp",
            now=time.time(),
        )
        status = current_model_catalog_status(
            "custom:my-proxy", "alpha", cache=cache, now=time.time(), catalog=catalog
        )
        assert status["state"] == "listed"
        assert status["catalog_source"] == "live"
