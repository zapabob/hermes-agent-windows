"""Fail-closed route-cost classification and catalogue refresh contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
import http.client
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from threading import Event
from typing import Any, Mapping, cast

import pytest

from agent.usage_pricing import PricingEntry
from downstream.delegation import free_routes


NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
PROVIDER_SCOPE = "openrouter:public"
ACCOUNT_SCOPE = "account-hash-7d9c"


def _api(name: str):
    value = getattr(free_routes, name, None)
    assert callable(value), f"T09 pricing authority must expose {name}"
    return value


def _price(
    *,
    input_cost: str = "0",
    output_cost: str = "0",
    cache_read_cost: str = "0",
    cache_write_cost: str = "0",
    request_cost: str = "0",
    fetched_at: datetime = NOW,
) -> PricingEntry:
    return PricingEntry(
        input_cost_per_million=Decimal(input_cost),
        output_cost_per_million=Decimal(output_cost),
        cache_read_cost_per_million=Decimal(cache_read_cost),
        cache_write_cost_per_million=Decimal(cache_write_cost),
        request_cost=Decimal(request_cost),
        source="provider_models_api",
        source_url="https://openrouter.ai/api/v1/models",
        pricing_version="models-api-v1",
        fetched_at=fetched_at,
    )


def _route_row(
    model_id: str = "vendor/free-model",
    *,
    pricing: PricingEntry | Mapping[str, Any] | None = None,
    billing_mode: str = "provider_models_api",
    supported_tools: list[str] | None = None,
    observed_at: datetime | str = NOW,
) -> dict:
    return {
        "provider": "openrouter",
        "provider_scope": PROVIDER_SCOPE,
        "account_scope": ACCOUNT_SCOPE,
        "model_id": model_id,
        "billing_mode": billing_mode,
        "pricing": pricing,
        "supported_tools": supported_tools,
        "observed_at": observed_at,
    }


def _free_quota(*, model_id: str = "vendor/quota-model", **overrides) -> dict:
    return {
        "kind": "free_quota",
        "provider_scope": PROVIDER_SCOPE,
        "account_scope": ACCOUNT_SCOPE,
        "model_ids": [model_id],
        "remaining": "1",
        "observed_at": NOW,
        "expires_at": NOW + timedelta(hours=4),
        **overrides,
    }


def _subscription_entitlement(*, model_id: str = "vendor/free-model", **overrides) -> dict:
    return {
        "kind": "subscription_included",
        "provider_scope": PROVIDER_SCOPE,
        "account_scope": ACCOUNT_SCOPE,
        "model_ids": [model_id],
        "included": True,
        "active": True,
        "observed_at": NOW,
        "expires_at": NOW + timedelta(hours=4),
        **overrides,
    }


def test_unknown_price_stays_unknown_and_free_suffix_is_not_evidence():
    classify_cost = _api("classify_cost")

    assert classify_cost({"model_id": "vendor/unknown", "pricing": {}}, now=NOW) == "UNKNOWN"
    assert classify_cost({"model_id": "vendor/model:free", "pricing": {}}, now=NOW) == "UNKNOWN"


def test_classifies_stale_zero_price_as_unknown_and_subscription_separately():
    classify_cost = _api("classify_cost")

    stale = _route_row(
        pricing=_price(fetched_at=NOW - timedelta(hours=12, seconds=1))
    )
    subscription = _route_row(pricing=None, billing_mode="subscription_included")
    entitlement = _subscription_entitlement()

    assert classify_cost(stale, now=NOW) == "UNKNOWN"
    assert classify_cost(subscription, now=NOW) == "UNKNOWN"
    assert classify_cost(subscription, entitlement, now=NOW) == "SUBSCRIPTION_INCLUDED"
    assert (
        classify_cost(
            subscription,
            _subscription_entitlement(account_scope="different-account"),
            now=NOW,
        )
        == "UNKNOWN"
    )
    assert (
        classify_cost(
            subscription,
            _subscription_entitlement(expires_at=NOW - timedelta(seconds=1)),
            now=NOW,
        )
        == "UNKNOWN"
    )


def test_missing_model_and_extended_age_override_cannot_promote_stale_price():
    classify_cost = _api("classify_cost")
    missing_model = _route_row(pricing=_price())
    missing_model.pop("model_id")
    stale = _route_row(
        pricing=_price(fetched_at=NOW - timedelta(hours=12, seconds=1))
    )

    assert classify_cost(missing_model, now=NOW) == "UNKNOWN"
    assert classify_cost(stale, now=NOW, max_age=timedelta(days=3)) == "UNKNOWN"


def test_zero_and_paid_costs_require_complete_provenance_and_all_billable_components():
    classify_cost = _api("classify_cost")
    free = _route_row(pricing=_price())
    paid = _route_row(pricing=_price(input_cost="0.01"))
    incomplete = _route_row(
        pricing=PricingEntry(
            input_cost_per_million=Decimal("0"),
            output_cost_per_million=Decimal("0"),
            source="provider_models_api",
            source_url="https://openrouter.ai/api/v1/models",
            pricing_version="models-api-v1",
            fetched_at=NOW,
        )
    )
    missing_provenance = _route_row(
        pricing=PricingEntry(
            input_cost_per_million=Decimal("0"),
            output_cost_per_million=Decimal("0"),
            cache_read_cost_per_million=Decimal("0"),
            cache_write_cost_per_million=Decimal("0"),
            request_cost=Decimal("0"),
            fetched_at=NOW,
        )
    )
    tiered_mapping = _route_row(
        pricing={
            "input_cost_per_million": "0",
            "output_cost_per_million": "0",
            "cache_read_cost_per_million": "0",
            "cache_write_cost_per_million": "0",
            "request_cost": "0",
            "input_cost_per_million_above": "0.01",
            "source": "provider_models_api",
            "source_url": "https://openrouter.ai/api/v1/models",
            "pricing_version": "models-api-v1",
            "fetched_at": NOW,
        }
    )

    assert classify_cost(free, now=NOW) == "VERIFIED_ZERO_PRICE"
    assert classify_cost(paid, now=NOW) == "PAID"
    assert classify_cost(incomplete, now=NOW) == "UNKNOWN"
    assert classify_cost(missing_provenance, now=NOW) == "UNKNOWN"
    assert classify_cost(tiered_mapping, now=NOW) == "PAID"


def test_free_quota_requires_exact_provider_account_model_and_current_grant():
    classify_cost = _api("classify_cost")
    row = _route_row("vendor/quota-model")

    assert classify_cost(row, _free_quota(), now=NOW) == "VERIFIED_FREE_QUOTA"
    assert (
        classify_cost(
            row,
            _free_quota(account_scope="different-account"),
            now=NOW,
        )
        == "UNKNOWN"
    )
    assert (
        classify_cost(
            row,
            _free_quota(expires_at=NOW - timedelta(seconds=1)),
            now=NOW,
        )
        == "UNKNOWN"
    )


@pytest.mark.parametrize("entitlement_kind", ["free_quota", "subscription_included"])
def test_classify_cost_max_age_applies_to_entitlement_evidence(entitlement_kind):
    classify_cost = _api("classify_cost")
    if entitlement_kind == "free_quota":
        row = _route_row("vendor/quota-model")
        entitlement = _free_quota(observed_at=NOW - timedelta(hours=2))
    else:
        row = _route_row(pricing=None, billing_mode="subscription_included")
        entitlement = _subscription_entitlement(observed_at=NOW - timedelta(hours=2))

    assert (
        classify_cost(
            row,
            entitlement,
            now=NOW,
            max_age=timedelta(hours=1),
        )
        == "UNKNOWN"
    )


@pytest.mark.parametrize("entitlement_kind", ["free_quota", "subscription_included"])
def test_snapshot_max_age_applies_to_entitlement_evidence(entitlement_kind):
    build_snapshot = _api("build_free_route_snapshot")
    eligible_routes = _api("eligible_routes")
    policy_type = getattr(free_routes, "FreeRoutePolicy", None)
    assert policy_type is not None

    if entitlement_kind == "free_quota":
        model_id = "vendor/quota-model"
        row = _route_row(model_id, pricing=None, supported_tools=["text"])
        entitlement = _free_quota(
            model_id=model_id,
            observed_at=NOW - timedelta(hours=2),
        )
    else:
        model_id = "vendor/free-model"
        row = _route_row(
            model_id,
            pricing=None,
            billing_mode="subscription_included",
            supported_tools=["text"],
        )
        entitlement = _subscription_entitlement(
            model_id=model_id,
            observed_at=NOW - timedelta(hours=2),
        )

    snapshot = build_snapshot(
        [row],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
        entitlements={model_id: entitlement},
        max_age=timedelta(hours=1),
    )
    route = snapshot.routes[0]
    policy = policy_type(
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        required_tools=frozenset({"text"}),
        allow_subscription_included=True,
    )

    assert route.cost_class == "UNKNOWN"
    assert route.entitlement_observed_at is None
    assert route.entitlement_expires_at is None
    assert eligible_routes(snapshot, policy, now=NOW) == ()


def test_snapshot_is_immutable_scoped_and_revisioned_from_evidence():
    build_snapshot = _api("build_free_route_snapshot")
    row = _route_row(pricing=_price(), supported_tools=["text", "vision"])
    snapshot = build_snapshot(
        [row],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    rebuilt = build_snapshot(
        [row],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )

    assert snapshot.revision == rebuilt.revision
    assert snapshot.provider_scope == PROVIDER_SCOPE
    assert snapshot.account_scope == ACCOUNT_SCOPE
    assert snapshot.routes[0].price_source == "provider_models_api"
    assert snapshot.routes[0].supported_tools == frozenset({"text", "vision"})
    with pytest.raises(FrozenInstanceError):
        snapshot.revision = "changed"


def test_snapshot_revision_changes_when_price_and_freshness_evidence_changes():
    build_snapshot = _api("build_free_route_snapshot")
    base = build_snapshot(
        [_route_row(pricing=_price(input_cost="0.01"))],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )

    changed_price = build_snapshot(
        [_route_row(pricing=_price(input_cost="0.02"))],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    changed_price_age = build_snapshot(
        [
            _route_row(
                pricing=_price(input_cost="0.01", fetched_at=NOW - timedelta(minutes=30))
            )
        ],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    changed_catalogue_age = build_snapshot(
        [
            _route_row(
                pricing=_price(input_cost="0.01"),
                observed_at=NOW - timedelta(minutes=30),
            )
        ],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    high_precision_price = build_snapshot(
        [
            _route_row(
                pricing=_price(input_cost="0.12345678901234567890123456789")
            )
        ],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    equivalent_high_precision_price = build_snapshot(
        [
            _route_row(
                pricing=_price(input_cost="0.123456789012345678901234567890")
            )
        ],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    different_high_precision_price = build_snapshot(
        [
            _route_row(
                pricing=_price(input_cost="0.12345678901234567890123456788")
            )
        ],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )

    assert changed_price.routes[0].cost_class == base.routes[0].cost_class == "PAID"
    assert changed_price.revision != base.revision
    assert changed_price_age.revision != base.revision
    assert changed_catalogue_age.revision != base.revision
    assert high_precision_price.revision == equivalent_high_precision_price.revision
    assert high_precision_price.revision != different_high_precision_price.revision

    entitlement = _free_quota()
    quota_row = _route_row("vendor/quota-model")
    quota_base = build_snapshot(
        [quota_row],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
        entitlements={"vendor/quota-model": entitlement},
    )
    changed_entitlement_time = build_snapshot(
        [quota_row],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
        entitlements={
            "vendor/quota-model": {
                **entitlement,
                "observed_at": NOW - timedelta(minutes=30),
            }
        },
    )
    assert quota_base.routes[0].cost_class == "VERIFIED_FREE_QUOTA"
    assert changed_entitlement_time.revision != quota_base.revision


def test_subscription_route_requires_current_exact_entitlement_to_be_eligible():
    build_snapshot = _api("build_free_route_snapshot")
    eligible_routes = _api("eligible_routes")
    policy_type = getattr(free_routes, "FreeRoutePolicy", None)
    assert policy_type is not None
    row = _route_row(pricing=None, billing_mode="subscription_included")
    policy = policy_type(
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        required_tools=frozenset({"text"}),
        allow_subscription_included=True,
    )

    missing = build_snapshot(
        [{**row, "supported_tools": ["text"]}],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    included = build_snapshot(
        [{**row, "supported_tools": ["text"]}],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
        entitlements={"vendor/free-model": _subscription_entitlement()},
    )
    expired = build_snapshot(
        [{**row, "supported_tools": ["text"]}],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
        entitlements={
            "vendor/free-model": _subscription_entitlement(
                expires_at=NOW - timedelta(seconds=1)
            )
        },
    )

    assert eligible_routes(missing, policy, now=NOW) == ()
    assert [route.model_id for route in eligible_routes(included, policy, now=NOW)] == [
        "vendor/free-model"
    ]
    assert eligible_routes(expired, policy, now=NOW) == ()


def test_eligible_routes_require_current_scope_price_and_tool_support():
    build_snapshot = _api("build_free_route_snapshot")
    eligible_routes = _api("eligible_routes")
    policy_type = getattr(free_routes, "FreeRoutePolicy", None)
    assert policy_type is not None, "T09 pricing authority must expose FreeRoutePolicy"

    snapshot = build_snapshot(
        [
            _route_row(
                "vendor/verified-free",
                pricing=_price(),
                supported_tools=["text", "vision"],
            ),
            _route_row(
                "vendor/unknown-tools",
                pricing=_price(),
                supported_tools=None,
            ),
            _route_row(
                "vendor/paid-tool-compatible",
                pricing=_price(input_cost="0.01"),
                supported_tools=["vision"],
            ),
        ],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    policy = policy_type(
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        required_tools=frozenset({"vision"}),
    )

    assert [route.model_id for route in eligible_routes(snapshot, policy, now=NOW)] == [
        "vendor/verified-free"
    ]
    wrong_scope = policy_type(
        provider_scope=PROVIDER_SCOPE,
        account_scope="another-account",
        required_tools=frozenset({"vision"}),
    )
    assert eligible_routes(snapshot, wrong_scope, now=NOW) == ()


def test_all_free_routes_exhausted_by_missing_tool_support_has_no_paid_fallback():
    build_snapshot = _api("build_free_route_snapshot")
    eligible_routes = _api("eligible_routes")
    policy_type = getattr(free_routes, "FreeRoutePolicy", None)
    assert policy_type is not None, "T09 pricing authority must expose FreeRoutePolicy"

    snapshot = build_snapshot(
        [
            _route_row(
                "vendor/free-but-no-vision",
                pricing=_price(),
                supported_tools=["text"],
            ),
            _route_row(
                "vendor/paid-with-vision",
                pricing=_price(input_cost="0.01"),
                supported_tools=["vision"],
            ),
        ],
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        now=NOW,
    )
    policy = policy_type(
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        required_tools=frozenset({"vision"}),
    )

    assert eligible_routes(snapshot, policy, now=NOW) == ()


def test_refresh_is_single_flight_and_uses_twelve_hour_window():
    owner_type = getattr(free_routes, "FreeRouteCatalogueOwner", None)
    response_type = getattr(free_routes, "FreeRouteFetchResult", None)
    assert owner_type is not None, "T09 pricing authority must expose FreeRouteCatalogueOwner"
    assert response_type is not None, "T09 pricing authority must expose FreeRouteFetchResult"

    current = [NOW]
    entered_fetch = Event()
    release_fetch = Event()
    calls: list[str | None] = []

    def fetch(etag):
        calls.append(etag)
        if len(calls) == 2:
            entered_fetch.set()
            assert release_fetch.wait(2)
        return response_type(
            status_code=200,
            rows=(
                _route_row(
                    "vendor/model-v2" if len(calls) == 2 else "vendor/model-v1",
                    pricing=_price(fetched_at=current[0]),
                    supported_tools=["text"],
                    observed_at=current[0],
                ),
            ),
            etag=f'catalog-{len(calls)}',
        )

    owner = owner_type(
        fetch,
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: current[0],
    )
    first = owner.refresh_if_due()
    assert first is not None
    current[0] += timedelta(hours=12)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(owner.refresh_if_due)
        assert entered_fetch.wait(2)
        two = pool.submit(owner.refresh_if_due)
        release_fetch.set()
        refreshed_one = one.result(timeout=2)
        refreshed_two = two.result(timeout=2)

    assert calls == [None, "catalog-1"]
    assert refreshed_one is refreshed_two
    assert refreshed_one is not first
    assert refreshed_one.routes[0].model_id == "vendor/model-v2"


def test_etag_not_modified_retains_last_good_snapshot_and_429_honors_retry_after():
    owner_type = getattr(free_routes, "FreeRouteCatalogueOwner", None)
    response_type = getattr(free_routes, "FreeRouteFetchResult", None)
    assert owner_type is not None, "T09 pricing authority must expose FreeRouteCatalogueOwner"
    assert response_type is not None, "T09 pricing authority must expose FreeRouteFetchResult"

    current = [NOW]
    calls: list[str | None] = []
    results = [
        response_type(
            status_code=200,
            rows=(_route_row(pricing=_price(), supported_tools=["text"]),),
            etag="etag-1",
        ),
        response_type(status_code=304, etag="etag-1"),
        response_type(status_code=429, retry_after_seconds=3600),
        response_type(
            status_code=200,
            rows=(
                _route_row(
                    "vendor/refreshed",
                    pricing=_price(fetched_at=current[0]),
                    supported_tools=["text"],
                    observed_at=current[0],
                ),
            ),
            etag="etag-2",
        ),
    ]

    def fetch(etag):
        calls.append(etag)
        return results.pop(0)

    owner = owner_type(
        fetch,
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: current[0],
    )
    first = owner.refresh_if_due()
    current[0] += timedelta(hours=12)
    not_modified = owner.refresh_if_due()
    assert not_modified is first
    assert not_modified.revision == first.revision
    assert not_modified.routes[0].price_fetched_at == NOW

    current[0] += timedelta(hours=12)
    after_429 = owner.refresh_if_due()
    assert after_429 is not_modified
    current[0] += timedelta(minutes=30)
    assert owner.refresh_if_due() is not_modified
    current[0] += timedelta(minutes=30)
    refreshed = owner.refresh_if_due()

    assert calls == [None, "etag-1", "etag-1", "etag-1"]
    assert refreshed is not first
    assert refreshed.routes[0].model_id == "vendor/refreshed"


@pytest.mark.parametrize(
    ("retry_after", "expected_delay"),
    [
        (1e300, timedelta(days=7)),
        (-5, timedelta(seconds=60)),
        (float("nan"), timedelta(seconds=60)),
        (None, timedelta(seconds=60)),
    ],
)
def test_retry_after_is_bounded_and_refresh_owner_recovers(retry_after, expected_delay):
    owner_type = free_routes.FreeRouteCatalogueOwner
    response_type = free_routes.FreeRouteFetchResult
    current = [NOW]
    calls = 0

    def fetch(_etag):
        nonlocal calls
        calls += 1
        if calls == 2:
            return response_type(status_code=429, retry_after_seconds=retry_after)
        return response_type(
            status_code=200,
            rows=(
                _route_row(
                    f"vendor/model-v{calls}",
                    pricing=_price(fetched_at=current[0]),
                    supported_tools=["text"],
                    observed_at=current[0],
                ),
            ),
        )

    owner = owner_type(
        fetch,
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: current[0],
    )
    first = owner.refresh_if_due()
    current[0] += timedelta(hours=12)
    assert owner.refresh_if_due() is first
    assert calls == 2
    assert owner.refresh_if_due() is first
    assert calls == 2

    current[0] += expected_delay - timedelta(seconds=1)
    assert owner.refresh_if_due() is first
    assert calls == 2
    current[0] += timedelta(seconds=1)
    refreshed = owner.refresh_if_due()
    assert calls == 3
    assert refreshed is not first
    assert refreshed.routes[0].model_id == "vendor/model-v3"


def test_single_flight_waiter_is_bounded_while_fetcher_is_hung(monkeypatch):
    entered_fetch = Event()
    release_fetch = Event()

    def fetch(_etag):
        entered_fetch.set()
        assert release_fetch.wait(2)
        return free_routes.FreeRouteFetchResult(
            status_code=200,
            rows=(_route_row(pricing=_price(), supported_tools=["text"]),),
        )

    owner = free_routes.FreeRouteCatalogueOwner(
        fetch,
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: NOW,
    )
    monkeypatch.setattr(free_routes, "_FREE_ROUTE_SINGLE_FLIGHT_WAIT_SECONDS", 0.05)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(owner.refresh_if_due)
        assert entered_fetch.wait(1)
        waiter = pool.submit(owner.refresh_if_due)
        try:
            waiter_result = waiter.result(timeout=0.5)
        except TimeoutError:
            waiter_result = "timed out"
        finally:
            release_fetch.set()
        assert first.result(timeout=2) is not None
    assert waiter_result is None


def test_fetch_exception_text_is_not_written_to_logs(caplog):
    owner_type = free_routes.FreeRouteCatalogueOwner
    response_type = free_routes.FreeRouteFetchResult
    calls = 0

    def fetch(_etag):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Authorization: Bearer synthetic-secret-value")
        return response_type(
            status_code=200,
            rows=(_route_row(pricing=_price(), supported_tools=["text"]),),
        )

    current = [NOW]
    owner = owner_type(
        fetch,
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: current[0],
    )
    snapshot = owner.manual_refresh()
    caplog.set_level(logging.DEBUG, logger=free_routes.__name__)
    current[0] += timedelta(hours=12)
    assert owner.refresh_if_due() is snapshot
    assert "synthetic-secret-value" not in caplog.text


def test_cold_owner_read_is_cache_only_until_explicit_refresh():
    owner_type = getattr(free_routes, "FreeRouteCatalogueOwner", None)
    response_type = getattr(free_routes, "FreeRouteFetchResult", None)
    assert owner_type is not None, "T09 pricing authority must expose FreeRouteCatalogueOwner"
    assert response_type is not None, "T09 pricing authority must expose FreeRouteFetchResult"
    calls = 0

    def fetch(_etag):
        nonlocal calls
        calls += 1
        return response_type(
            status_code=200,
            rows=(_route_row(pricing=_price(), supported_tools=["text"]),),
        )

    owner = owner_type(
        fetch,
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: NOW,
    )
    assert owner.get_snapshot() is None
    assert calls == 0
    snapshot = owner.refresh_if_due()
    assert snapshot is not None
    assert calls == 1


def test_manual_refresh_is_debounced_and_failed_refresh_keeps_last_good():
    owner_type = getattr(free_routes, "FreeRouteCatalogueOwner", None)
    response_type = getattr(free_routes, "FreeRouteFetchResult", None)
    assert owner_type is not None, "T09 pricing authority must expose FreeRouteCatalogueOwner"
    assert response_type is not None, "T09 pricing authority must expose FreeRouteFetchResult"

    current = [NOW]
    calls = 0

    def fetch(_etag):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated source failure")
        return response_type(
            status_code=200,
            rows=(_route_row(pricing=_price(fetched_at=current[0]), supported_tools=["text"]),),
            etag="etag-1",
        )

    owner = owner_type(
        fetch,
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: current[0],
    )
    first = owner.manual_refresh()
    current[0] += timedelta(seconds=30)
    assert owner.manual_refresh() is first
    assert calls == 1

    current[0] += timedelta(seconds=31)
    assert owner.manual_refresh() is first
    assert calls == 2


def test_openrouter_adapter_uses_catalogue_budget_and_bounded_conditional_fetch():
    adapter_type = _api("OpenRouterFreeRouteAdapter")
    body = json.dumps(
        {
            "data": [
                {
                    "id": "vendor/free-tools",
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": ["tools"],
                    "pricing": {
                        "prompt": "0",
                        "completion": "0",
                        "input_cache_read": "0",
                        "input_cache_write": "0",
                        "request": "0",
                    },
                    "expiration_date": None,
                }
            ],
            "total_count": 1,
        }
    ).encode("utf-8")

    class Lease:
        connect_timeout_seconds = 5.0
        read_idle_timeout_seconds = 5.0
        total_timeout_seconds = 12.0
        remaining_seconds = 12.0

        def __init__(self):
            self.progress_count = 0
            self.abort_callback = None

        def mark_progress(self):
            self.progress_count += 1

        def record_retry_after(self, seconds):
            raise AssertionError(f"unexpected Retry-After: {seconds}")

        def check_active(self):
            return None

        def set_abort_callback(self, callback):
            self.abort_callback = callback

    lease = Lease()
    budget_calls: list[tuple[str, str]] = []

    class Budget:
        def reserve(self, account_scope, operation="catalogue"):
            budget_calls.append((account_scope, operation))
            return nullcontext(lease)

    class Response:
        status = 200
        headers = {"ETag": '"models-v1"', "Content-Length": str(len(body))}

        def __init__(self):
            self.offset = 0
            self.read_sizes: list[int] = []
            self.fp = cast(Any, type("File", (), {})())
            self.fp.raw = cast(Any, type("Raw", (), {})())
            self.fp.raw._sock = type("Socket", (), {"settimeout": lambda _self, _value: None})()

        def read(self, size=-1):
            assert size >= 0, "provider response must be read with a byte bound"
            self.read_sizes.append(size)
            chunk = body[self.offset : self.offset + min(size, 17)]
            self.offset += len(chunk)
            return chunk

        read1 = read

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    response = Response()
    requests: list[tuple[Any, float]] = []

    class Connection:
        def __init__(self, *, timeout):
            requests.append((self, timeout))
            self.sock = type("Socket", (), {"settimeout": lambda _self, _value: None})()
            cast(Any, response.fp).raw._sock = self.sock
            self.request_args = None

        def connect(self):
            return None

        def request(self, method, target, *, headers):
            self.request_args = (method, target, headers)

        def getresponse(self):
            return response

        def close(self):
            return None

    adapter = adapter_type(
        account_scope=ACCOUNT_SCOPE,
        allowed_model_ids={"vendor/free-tools"},
        budget=Budget(),
        connection_factory=Connection,
        clock=lambda: NOW,
    )
    result = adapter('"models-v0"')

    assert budget_calls == [("public:openrouter:catalogue", "catalogue")]
    assert len(requests) == 1
    connection, timeout = requests[0]
    method, target, headers = connection.request_args
    assert method == "GET"
    assert target == "/api/v1/models"
    assert headers["If-None-Match"] == '"models-v0"'
    assert "Authorization" not in headers
    assert connection.sock is not None
    assert 0 < timeout <= lease.total_timeout_seconds
    assert response.read_sizes and all(size > 0 for size in response.read_sizes)
    assert lease.progress_count > 0
    assert result.status_code == 200
    assert result.etag == '"models-v1"'
    assert result.rows[0]["model_id"] == "vendor/free-tools"
    assert result.rows[0]["supported_tools"] == ["text"]
    assert free_routes.classify_cost(result.rows[0], now=NOW) == "VERIFIED_ZERO_PRICE"


def test_openrouter_adapter_records_provider_retry_after_with_shared_budget():
    adapter_type = _api("OpenRouterFreeRouteAdapter")

    class Lease:
        connect_timeout_seconds = 5.0
        read_idle_timeout_seconds = 5.0
        total_timeout_seconds = 12.0
        remaining_seconds = 12.0

        def __init__(self):
            self.retry_after = []

        def check_active(self):
            return None

        def mark_progress(self):
            return None

        def record_retry_after(self, seconds):
            self.retry_after.append(seconds)

        def set_abort_callback(self, _callback):
            return None

    lease = Lease()

    class Budget:
        def reserve(self, _account_scope, _operation="catalogue"):
            return nullcontext(lease)

    class Response:
        status = 429
        headers = {"ETag": '"throttled-v1"', "Retry-After": "30"}

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    class Connection:
        sock = type("Socket", (), {"settimeout": lambda _self, _value: None})()

        def __init__(self, *, timeout):
            assert 0 < timeout <= lease.total_timeout_seconds

        def connect(self):
            return None

        def request(self, method, target, *, headers):
            assert (method, target) == ("GET", "/api/v1/models")
            assert "Authorization" not in headers

        def getresponse(self):
            return Response()

        def close(self):
            return None

    adapter = adapter_type(
        account_scope=ACCOUNT_SCOPE,
        allowed_model_ids={"vendor/approved"},
        budget=Budget(),
        connection_factory=Connection,
        clock=lambda: NOW,
    )

    result = adapter(None)

    assert result.status_code == 429
    assert result.etag == '"throttled-v1"'
    assert result.retry_after_seconds == 30
    assert lease.retry_after == [30]


def test_openrouter_adapter_does_not_infer_missing_cache_prices_are_free():
    adapter_type = _api("OpenRouterFreeRouteAdapter")
    adapter = adapter_type(
        account_scope=ACCOUNT_SCOPE,
        allowed_model_ids={"vendor/incomplete-price"},
        budget=object(),
        clock=lambda: NOW,
    )
    rows = adapter._normalize_payload(
        {
            "data": [
                {
                    "id": "vendor/incomplete-price",
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    "supported_parameters": ["tools"],
                    "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                }
            ]
        },
        "etag-1",
    )

    assert rows[0]["pricing"]["cache_read_cost_per_million"] is None
    assert rows[0]["pricing"]["cache_write_cost_per_million"] is None
    assert free_routes.classify_cost(rows[0], now=NOW) == "UNKNOWN"


def test_openrouter_adapter_rejects_a_truncated_paged_catalogue():
    adapter = _api("OpenRouterFreeRouteAdapter")(
        account_scope=ACCOUNT_SCOPE,
        allowed_model_ids={"vendor/approved"},
        budget=object(),
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError, match="incomplete"):
        adapter._normalize_payload(
            {"data": [], "total_count": 1001},
            "etag-1",
        )


def test_openrouter_adapter_stops_a_trickling_response_at_the_total_lease_deadline():
    adapter_type = _api("OpenRouterFreeRouteAdapter")
    server_socket, client_socket = socket.socketpair()
    stop_server = Event()
    aborts = 0

    class Lease:
        connect_timeout_seconds = 0.3
        read_idle_timeout_seconds = 0.5
        total_timeout_seconds = 0.25

        def __init__(self):
            self.deadline = None
            self.abort = None
            self.expired = False
            self.abort_timer = None

        @property
        def remaining_seconds(self):
            if self.deadline is None:
                return self.total_timeout_seconds
            return self.deadline - time.monotonic()

        def set_abort_callback(self, callback):
            self.abort = callback
            self.deadline = time.monotonic() + self.total_timeout_seconds
            self.abort_timer = threading.Timer(self.total_timeout_seconds, self._expire)
            self.abort_timer.daemon = True
            self.abort_timer.start()

        def _expire(self):
            nonlocal aborts
            if self.expired:
                return
            self.expired = True
            if self.abort is not None:
                aborts += 1
                self.abort("deadline")

        def check_active(self):
            if self.remaining_seconds <= 0:
                self._expire()
                raise TimeoutError("request budget expired")

        def mark_progress(self):
            return None

        def record_retry_after(self, _seconds):
            return None

    lease = Lease()
    response = http.client.HTTPResponse(client_socket)

    def serve_trickles():
        try:
            server_socket.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2048\r\nETag: slow-v1\r\n\r\n"
            )
            while not stop_server.is_set():
                server_socket.sendall(b" ")
                time.sleep(0.02)
        except OSError:
            return

    server_thread = threading.Thread(target=serve_trickles, daemon=True)
    server_thread.start()

    class Connection:
        def __init__(self, *, timeout):
            assert 0 < timeout <= lease.total_timeout_seconds
            self.sock = client_socket

        def connect(self):
            return None

        def request(self, _method, _target, *, headers):
            assert "Authorization" not in headers

        def getresponse(self):
            response.begin()
            return response

        def close(self):
            try:
                client_socket.close()
            except OSError:
                pass

    def connection_factory(*, timeout):
        assert 0 < timeout <= lease.total_timeout_seconds
        return Connection(timeout=timeout)

    class Budget:
        def reserve(self, _scope, _operation):
            return nullcontext(lease)

    adapter = adapter_type(
        account_scope=ACCOUNT_SCOPE,
        allowed_model_ids={"vendor/slow"},
        budget=Budget(),
        connection_factory=connection_factory,
        clock=lambda: NOW,
    )
    started = time.monotonic()
    try:
        result = adapter(None)
    finally:
        stop_server.set()
        if lease.abort_timer is not None:
            lease.abort_timer.cancel()
        try:
            server_socket.close()
            client_socket.close()
        except OSError:
            pass
        server_thread.join(timeout=0.5)

    assert result.status_code == 503
    assert aborts == 1
    assert time.monotonic() - started < 1.0


def test_openrouter_adapter_abort_callback_covers_trickled_response_headers():
    adapter_type = _api("OpenRouterFreeRouteAdapter")
    server_socket, client_socket = socket.socketpair()
    stop_server = Event()
    aborts = []

    class Lease:
        connect_timeout_seconds = 0.3
        read_idle_timeout_seconds = 0.1
        total_timeout_seconds = 0.25

        def __init__(self):
            self.deadline = time.monotonic() + self.total_timeout_seconds
            self.abort = None
            self.timer = threading.Timer(self.total_timeout_seconds, self.expire)
            self.timer.daemon = True
            self.timer.start()

        @property
        def remaining_seconds(self):
            return self.deadline - time.monotonic()

        def set_abort_callback(self, callback):
            self.abort = callback
            if self.remaining_seconds <= 0:
                self.expire()

        def expire(self):
            if self.abort is not None:
                aborts.append("deadline")
                self.abort("deadline")

        def check_active(self):
            if self.remaining_seconds <= 0:
                raise TimeoutError("request budget expired")

        def mark_progress(self):
            return None

        def record_retry_after(self, _seconds):
            return None

    lease = Lease()
    response = http.client.HTTPResponse(client_socket)

    def trickle_header_bytes():
        try:
            for value in b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n":
                if stop_server.is_set():
                    return
                server_socket.sendall(bytes([value]))
                time.sleep(0.02)
        except OSError:
            return

    server_thread = threading.Thread(target=trickle_header_bytes, daemon=True)
    server_thread.start()

    class Connection:
        def __init__(self, *, timeout):
            assert 0 < timeout <= lease.total_timeout_seconds
            self.sock = client_socket

        def connect(self):
            return None

        def request(self, _method, _target, *, headers):
            assert "Authorization" not in headers

        def getresponse(self):
            response.begin()
            return response

        def close(self):
            try:
                client_socket.close()
            except OSError:
                pass

    class Budget:
        def reserve(self, _scope, _operation):
            return nullcontext(lease)

    adapter = adapter_type(
        account_scope=ACCOUNT_SCOPE,
        allowed_model_ids={"vendor/slow-header"},
        budget=Budget(),
        connection_factory=Connection,
        clock=lambda: NOW,
    )
    started = time.monotonic()
    try:
        result = adapter(None)
    finally:
        lease.timer.cancel()
        stop_server.set()
        server_socket.close()
        client_socket.close()
        server_thread.join(timeout=0.5)

    assert result.status_code == 503
    assert aborts == ["deadline"]
    assert time.monotonic() - started < 1.0


def test_last_good_catalogue_persists_and_separate_owners_coalesce(tmp_path):
    owner_type = free_routes.FreeRouteCatalogueOwner
    response_type = free_routes.FreeRouteFetchResult
    cache_path = tmp_path / "cache" / "free-routes.json"
    current = [NOW]
    entered = Event()
    release = Event()
    fetch_calls: list[str | None] = []
    row = _route_row(
        pricing={
            "input_cost_per_million": "0",
            "output_cost_per_million": "0",
            "cache_read_cost_per_million": "0",
            "cache_write_cost_per_million": "0",
            "request_cost": "0",
            "source": "provider_models_api",
            "source_url": "https://openrouter.ai/api/v1/models",
            "pricing_version": "etag-1",
            "fetched_at": NOW.isoformat(),
        },
        supported_tools=["text"],
        observed_at=NOW.isoformat(),
    )

    def first_fetch(etag):
        fetch_calls.append(etag)
        entered.set()
        assert release.wait(2)
        return response_type(status_code=200, rows=(row,), etag="etag-1")

    first_owner = owner_type(
        first_fetch,
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: current[0],
        cache_path=cache_path,
    )
    second_owner = owner_type(
        lambda _etag: pytest.fail("second owner must observe the persisted first refresh"),
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: current[0],
        cache_path=cache_path,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_owner.refresh_if_due)
        assert entered.wait(1)
        second = pool.submit(second_owner.refresh_if_due)
        time.sleep(0.05)
        release.set()
        first_snapshot = first.result(timeout=2)
        second_snapshot = second.result(timeout=2)

    assert fetch_calls == [None]
    assert first_snapshot is not None
    assert second_snapshot is not None
    assert second_snapshot.revision == first_snapshot.revision
    second_loaded = second_owner.get_snapshot()
    assert second_loaded is not None
    assert second_loaded.revision == first_snapshot.revision

    current[0] += timedelta(hours=12)
    reloaded_calls: list[str | None] = []
    reloaded = owner_type(
        lambda etag: (
            reloaded_calls.append(etag)
            or response_type(status_code=304, etag="etag-1")
        ),
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: current[0],
        cache_path=cache_path,
    )
    assert reloaded.get_snapshot() is not None
    assert reloaded_calls == []
    assert reloaded.refresh_if_due() is reloaded.get_snapshot()
    assert reloaded_calls == ["etag-1"]


def test_separate_processes_share_profile_refresh_lock_and_last_good_snapshot(tmp_path):
    cache_path = tmp_path / "cache" / "free-routes.json"
    entered_path = tmp_path / "fetch-entered"
    calls_path = tmp_path / "fetch-calls"
    child_source = "\n".join(
        (
            "import sys, time",
            "from datetime import datetime",
            "from pathlib import Path",
            "from downstream.delegation.free_routes import FreeRouteCatalogueOwner, FreeRouteFetchResult",
            "cache_path, entered_path, calls_path, now_text = sys.argv[1:]",
            "now = datetime.fromisoformat(now_text)",
            "def fetch(_etag):",
            "    Path(calls_path).write_text('1', encoding='utf-8')",
            "    Path(entered_path).write_text('1', encoding='utf-8')",
            "    time.sleep(0.3)",
            "    row = {",
            "        'provider': 'openrouter',",
            "        'provider_scope': 'openrouter:public',",
            "        'account_scope': 'account-hash-7d9c',",
            "        'model_id': 'vendor/cross-process',",
            "        'billing_mode': 'provider_models_api',",
            "        'pricing': None,",
            "        'supported_tools': ['text'],",
            "        'observed_at': now.isoformat(),",
            "    }",
            "    return FreeRouteFetchResult(status_code=200, rows=(row,))",
            "owner = FreeRouteCatalogueOwner(",
            "    fetch, provider_scope='openrouter:public', account_scope='account-hash-7d9c',",
            "    clock=lambda: now, cache_path=cache_path,",
            ")",
            "owner.refresh_if_due()",
        )
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_source,
            str(cache_path),
            str(entered_path),
            str(calls_path),
            NOW.isoformat(),
        ],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not entered_path.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert entered_path.exists(), "child process did not enter its fetch callback"

        parent_fetches: list[str | None] = []
        parent_owner = free_routes.FreeRouteCatalogueOwner(
            lambda etag: (
                parent_fetches.append(etag)
                or pytest.fail("second process must load the first process last-good snapshot")
            ),
            provider_scope=PROVIDER_SCOPE,
            account_scope=ACCOUNT_SCOPE,
            clock=lambda: NOW,
            cache_path=cache_path,
        )
        snapshot = parent_owner.refresh_if_due()
        stdout, stderr = child.communicate(timeout=10)

        assert child.returncode == 0, f"child exited with {child.returncode}: {stdout} {stderr}"
        assert calls_path.read_text(encoding="utf-8") == "1"
        assert parent_fetches == []
        assert snapshot is not None
        assert [route.model_id for route in snapshot.routes] == ["vendor/cross-process"]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)


def test_model_catalogue_allowlist_is_profile_cache_only_and_isolated(tmp_path, monkeypatch):
    from hermes_cli import model_catalog

    active_home = [tmp_path / "profile-a"]
    monkeypatch.setattr(
        model_catalog,
        "_cache_path",
        lambda: active_home[0] / "cache" / "model_catalog.json",
    )
    monkeypatch.setattr(model_catalog, "_load_catalog_config", lambda: {"enabled": True})

    def write_catalog(model_id):
        model_catalog._write_disk_cache(
            {
                "version": 1,
                "updated_at": NOW.isoformat(),
                "metadata": {},
                "providers": {
                    "openrouter": {
                        "id": "openrouter",
                        "name": "OpenRouter",
                        "metadata": {},
                        "models": [{"id": model_id, "description": "curated"}],
                    }
                },
            }
        )

    model_catalog.reset_cache()
    write_catalog("vendor/profile-a")
    model_catalog._catalog_cache = {"providers": {"openrouter": {"models": [{"id": "vendor/stale"}]}}}
    assert model_catalog.get_cached_curated_openrouter_model_ids() == {"vendor/profile-a"}

    active_home[0] = tmp_path / "profile-b"
    write_catalog("vendor/profile-b")
    assert model_catalog.get_cached_curated_openrouter_model_ids() == {"vendor/profile-b"}

    active_home[0] = tmp_path / "profile-a"
    assert model_catalog.get_cached_curated_openrouter_model_ids() == {"vendor/profile-a"}


def test_default_model_catalogue_setting_does_not_opt_in_to_background_openrouter_fetch(tmp_path, monkeypatch):
    from hermes_cli import model_catalog
    import hermes_constants

    monkeypatch.setattr(model_catalog, "_load_catalog_config", lambda: {"enabled": True, "providers": {}})
    monkeypatch.setattr(
        model_catalog,
        "get_cached_curated_openrouter_model_ids",
        lambda: frozenset({"vendor/approved"}),
    )
    monkeypatch.setattr(model_catalog, "free_route_cache_path", lambda: tmp_path / "cache" / "routes.json")
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        free_routes,
        "OpenRouterFreeRouteAdapter",
        lambda **_kwargs: pytest.fail("no fetch is allowed without provider-scoped opt-in"),
    )

    assert model_catalog.openrouter_free_route_refresh_enabled() is False
    assert _api("start_free_route_catalogue_refresh_host")() is None


def test_refresh_host_checks_startup_and_coalesces_wake_notifications():
    owner = free_routes.FreeRouteCatalogueOwner(
        lambda _etag: pytest.fail("host test replaces refresh before starting"),
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: NOW,
    )
    calls: list[None] = []
    called = Event()

    def fake_refresh() -> None:
        calls.append(None)
        called.set()
        return None

    setattr(owner, "refresh_if_due", fake_refresh)
    host = free_routes.FreeRouteCatalogueRefreshHost(owner, check_interval=timedelta(seconds=30))
    try:
        host.start()
        assert called.wait(1)
        called.clear()
        host.notify_wake()
        assert called.wait(1)
        host.notify_wake()
        host.notify_wake()
        assert called.wait(1)
    finally:
        host.stop()

    assert len(calls) == 2


def test_serve_and_gateway_startups_share_one_host_per_profile(tmp_path, monkeypatch):
    from hermes_cli import model_catalog
    import hermes_constants

    active_home = [tmp_path / "profile-a"]
    monkeypatch.setattr(
        model_catalog,
        "_load_catalog_config",
        lambda: {
            "enabled": True,
            "providers": {"openrouter": {"free_route_catalogue_enabled": True}},
        },
    )
    monkeypatch.setattr(
        model_catalog,
        "get_cached_curated_openrouter_model_ids",
        lambda: frozenset({"vendor/approved"}),
    )
    monkeypatch.setattr(
        model_catalog,
        "free_route_cache_path",
        lambda: active_home[0] / "cache" / "model_catalog_free_routes.json",
    )
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: active_home[0])

    class Adapter:
        def __init__(self, *, account_scope, allowed_model_ids):
            self.account_scope = account_scope
            self.allowed_model_ids = allowed_model_ids

        def __call__(self, _etag):
            return free_routes.FreeRouteFetchResult(status_code=503)

    monkeypatch.setattr(free_routes, "OpenRouterFreeRouteAdapter", Adapter)
    start_host = _api("start_free_route_catalogue_refresh_host")
    stop_host = _api("stop_free_route_catalogue_refresh_host")

    first_profile_lease = start_host()
    desktop_lease = start_host()
    assert first_profile_lease.host is desktop_lease.host
    first_profile_host = first_profile_lease.host
    assert first_profile_host.owner.account_scope.startswith("profile:")

    active_home[0] = tmp_path / "profile-b"
    second_profile_lease = start_host()
    second_profile_host = second_profile_lease.host
    assert second_profile_host is not first_profile_host
    assert second_profile_host.owner.account_scope != first_profile_host.owner.account_scope

    stop_host(first_profile_lease)
    assert first_profile_host.is_running
    refreshed = Event()

    def observe_shared_host_refresh():
        refreshed.set()

    first_profile_host.owner.refresh_if_due = observe_shared_host_refresh
    first_profile_host.notify_wake()
    assert refreshed.wait(1)
    stop_host(desktop_lease)
    stop_host(second_profile_lease)


def test_refresh_host_restarts_after_stop_during_bounded_fetch():
    entered_fetch = Event()
    release_fetch = Event()
    resumed_fetch = Event()
    calls = []
    owner = free_routes.FreeRouteCatalogueOwner(
        lambda _etag: pytest.fail("direct host test replaces refresh before starting"),
        provider_scope=PROVIDER_SCOPE,
        account_scope=ACCOUNT_SCOPE,
        clock=lambda: NOW,
    )

    def block_first_refresh() -> None:
        calls.append(None)
        if len(calls) == 1:
            entered_fetch.set()
            assert release_fetch.wait(2)
        else:
            resumed_fetch.set()
        return None

    setattr(owner, "refresh_if_due", block_first_refresh)
    host = free_routes.FreeRouteCatalogueRefreshHost(owner, check_interval=timedelta(seconds=30))
    host.start()
    assert entered_fetch.wait(1)
    host.stop(timeout=0.01)
    host.start()
    release_fetch.set()
    try:
        assert resumed_fetch.wait(1)
    finally:
        host.stop()


def test_desktop_serve_lifespan_acquires_and_releases_host_lease(monkeypatch):
    import asyncio
    from hermes_cli import web_server

    async def _done():
        return None

    sentinel = object()
    lifecycle_calls = []
    monkeypatch.setattr(web_server, "_prepare_control_mcp_host", lambda _app: None)
    monkeypatch.setattr(web_server, "_eager_reconcile_own_session_db", lambda: None)
    monkeypatch.setattr(web_server, "_resume_security_watch_on_startup", lambda: None)
    monkeypatch.setattr(web_server, "_auto_update_security_definitions_on_startup", lambda: None)
    monkeypatch.setattr(web_server, "_warm_gateway_module", lambda: None)
    monkeypatch.setattr(web_server, "run_reaper", lambda _registry: _done())
    monkeypatch.setattr(web_server, "_dashboard_selftest_loop", lambda: _done())
    monkeypatch.setattr(web_server, "_auto_archive_ticker_loop", lambda: _done())
    monkeypatch.setattr(web_server.PTY_REGISTRY, "close_all", _done)
    monkeypatch.setattr(web_server.os, "getenv", lambda name, default=None: default)

    from gateway import code_skew
    monkeypatch.setattr(code_skew, "record_boot_fingerprint", lambda: None)
    monkeypatch.setattr(
        free_routes,
        "start_free_route_catalogue_refresh_host",
        lambda: (lifecycle_calls.append("start") or sentinel),
    )
    monkeypatch.setattr(
        free_routes,
        "stop_free_route_catalogue_refresh_host",
        lambda lease: lifecycle_calls.append(("stop", lease)),
    )

    async def exercise_lifespan():
        async with web_server._lifespan(web_server.app):
            await asyncio.sleep(0)

    asyncio.run(exercise_lifespan())
    assert lifecycle_calls == ["start", ("stop", sentinel)]


def test_gateway_runner_lifecycle_acquires_and_releases_host_lease(monkeypatch):
    from gateway.run import GatewayRunner

    sentinel = object()
    calls = []
    monkeypatch.setattr(
        free_routes,
        "start_free_route_catalogue_refresh_host",
        lambda: (calls.append("start") or sentinel),
    )
    monkeypatch.setattr(
        free_routes,
        "stop_free_route_catalogue_refresh_host",
        lambda lease: calls.append(("stop", lease)),
    )

    runner = object.__new__(GatewayRunner)
    runner._start_free_route_catalogue_refresh_host()
    runner._start_free_route_catalogue_refresh_host()
    assert calls == ["start"]
    runner._stop_free_route_catalogue_refresh_host()

    assert calls == ["start", ("stop", sentinel)]
    assert runner._free_route_catalogue_host is None


@pytest.mark.asyncio
async def test_gateway_runner_start_and_stop_call_catalogue_host_lifecycle(monkeypatch, tmp_path):
    from gateway.config import GatewayConfig
    from gateway.run import GatewayRunner

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    sentinel = object()
    calls = []
    monkeypatch.setattr(
        free_routes,
        "start_free_route_catalogue_refresh_host",
        lambda: (calls.append("start") or sentinel),
    )
    monkeypatch.setattr(
        free_routes,
        "stop_free_route_catalogue_refresh_host",
        lambda lease: calls.append(("stop", lease)),
    )
    runner = GatewayRunner(GatewayConfig(sessions_dir=tmp_path / "sessions"))

    await runner.start()
    assert calls == ["start"]

    await runner.stop()
    assert calls == ["start", ("stop", sentinel)]
