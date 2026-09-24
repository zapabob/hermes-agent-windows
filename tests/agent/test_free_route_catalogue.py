"""Fail-closed route-cost classification and catalogue refresh contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from threading import Event
from typing import Any, Mapping

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
    observed_at: datetime = NOW,
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
