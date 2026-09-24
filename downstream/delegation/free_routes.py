"""Fail-closed model cost and eligibility projection for delegation."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Literal, Mapping, cast
from urllib.parse import urlsplit

from agent.usage_pricing import CostSource, PricingEntry

logger = logging.getLogger(__name__)
_ZERO = Decimal("0")
_UTC_NOW = lambda: datetime.now(timezone.utc)
# The free-route view deliberately has a narrower contract than the usage
# estimator above. A missing price component, expired observation, or unknown
# source is UNKNOWN; display helpers that render a missing number as `$0.00`
# must never be reused as admission evidence.
FreeRouteCostClass = Literal[
    "VERIFIED_ZERO_PRICE",
    "VERIFIED_FREE_QUOTA",
    "SUBSCRIPTION_INCLUDED",
    "PAID",
    "LOCAL_CONFIGURED",
    "UNKNOWN",
]
_FREE_ROUTE_EVIDENCE_MAX_AGE = timedelta(hours=12)
_FREE_ROUTE_REFRESH_INTERVAL = timedelta(hours=12)
_FREE_ROUTE_MANUAL_DEBOUNCE = timedelta(seconds=60)
_FREE_ROUTE_RETRY_BACKOFF = timedelta(seconds=60)
_FREE_ROUTE_MAX_RETRY_AFTER = timedelta(days=7)
_FREE_ROUTE_SINGLE_FLIGHT_WAIT_SECONDS = 30.0
_FREE_ROUTE_MAX_ROWS = 20_000
_FREE_ROUTE_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_FREE_ROUTE_PRICE_SOURCES = frozenset(
    {
        "provider_cost_api",
        "provider_generation_api",
        "provider_models_api",
        "official_docs_snapshot",
        "user_override",
        "custom_contract",
    }
)


@dataclass(frozen=True)
class FreeRoute:
    """One immutable, scoped model row with its price/capability evidence."""

    provider: str
    provider_scope: str
    account_scope: str
    model_id: str
    cost_class: FreeRouteCostClass
    price_source: CostSource | None
    price_source_url: str | None
    price_version: str | None
    price_fetched_at: datetime | None
    supported_tools: frozenset[str] | None
    entitlement_expires_at: datetime | None
    entitlement_observed_at: datetime | None
    observed_at: datetime | None
    observation_age_seconds: float | None
    availability: str = "available"


@dataclass(frozen=True)
class FreeRouteSnapshot:
    """Immutable route catalogue snapshot safe to pass across host boundaries."""

    revision: str
    provider_scope: str
    account_scope: str
    created_at: datetime
    routes: tuple[FreeRoute, ...]
    validated_in_process: bool = False


@dataclass(frozen=True)
class FreeRoutePolicy:
    """Eligibility constraints; account/provider scope is always exact-match."""

    provider_scope: str
    account_scope: str
    required_tools: frozenset[str] = frozenset()
    allow_subscription_included: bool = False
    max_evidence_age: timedelta = _FREE_ROUTE_EVIDENCE_MAX_AGE


@dataclass(frozen=True)
class FreeRouteFetchResult:
    """Result supplied by a host-approved, bounded catalogue fetch adapter.

    The adapter owns network policy, response-byte and parse limits, and its
    request timeout. This authority owns validation, replacement, backoff,
    freshness, and single-flight behavior; it stores no credentials.
    """

    status_code: int
    rows: tuple[Mapping[str, Any], ...] = ()
    etag: str | None = None
    retry_after_seconds: float | None = None


def _free_route_utc(value: Any) -> datetime | None:
    """Parse only timezone-aware timestamps for evidence decisions."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _free_route_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _free_route_scope_matches(row: Mapping[str, Any]) -> bool:
    provider = row.get("provider")
    model_id = row.get("model_id")
    provider_scope = row.get("provider_scope")
    account_scope = row.get("account_scope")
    return (
        isinstance(provider, str)
        and bool(provider.strip())
        and isinstance(model_id, str)
        and bool(model_id.strip())
        and len(model_id) <= 512
        and isinstance(provider_scope, str)
        and bool(provider_scope.strip())
        and provider_scope == provider_scope.strip()
        and isinstance(account_scope, str)
        and bool(account_scope.strip())
        and account_scope == account_scope.strip()
    )


def _free_route_price_fields(
    row: Mapping[str, Any],
) -> tuple[
    tuple[Decimal, ...] | None,
    CostSource | None,
    str | None,
    str | None,
    datetime | None,
]:
    pricing = row.get("pricing")
    if isinstance(pricing, PricingEntry):
        values = (
            pricing.input_cost_per_million,
            pricing.output_cost_per_million,
            pricing.cache_read_cost_per_million,
            pricing.cache_write_cost_per_million,
            pricing.request_cost,
        )
        source = pricing.source
        source_url = _free_route_safe_source_url(pricing.source_url)
        version = pricing.pricing_version
        fetched_at = _free_route_utc(pricing.fetched_at)
    elif isinstance(pricing, Mapping):
        values = tuple(
            pricing.get(name)
            for name in (
                "input_cost_per_million",
                "output_cost_per_million",
                "cache_read_cost_per_million",
                "cache_write_cost_per_million",
                "request_cost",
            )
        )
        source = pricing.get("source") or row.get("price_source")
        source_url = _free_route_safe_source_url(
            pricing.get("source_url") or row.get("price_source_url")
        )
        version = pricing.get("pricing_version") or row.get("price_version")
        fetched_at = _free_route_utc(
            pricing.get("fetched_at") or row.get("price_fetched_at")
        )
    else:
        return None, None, None, None, None

    parsed_values = tuple(_free_route_decimal(value) for value in values)
    if any(value is None or value < _ZERO for value in parsed_values):
        return None, _free_route_cost_source(source), _free_route_text(source_url), _free_route_text(version), fetched_at

    # Context-tiered rates can supersede a zero base rate; account for every
    # field the current PricingEntry can represent before claiming zero cost.
    if isinstance(pricing, PricingEntry):
        above = (
            pricing.input_cost_per_million_above,
            pricing.output_cost_per_million_above,
            pricing.cache_read_cost_per_million_above,
        )
    elif isinstance(pricing, Mapping):
        above = tuple(
            pricing.get(name)
            for name in (
                "input_cost_per_million_above",
                "output_cost_per_million_above",
                "cache_read_cost_per_million_above",
            )
        )
    else:
        above = ()
    for value in above:
        if value is not None:
            parsed = _free_route_decimal(value)
            if parsed is None or parsed < _ZERO:
                return None, _free_route_cost_source(source), _free_route_text(source_url), _free_route_text(version), fetched_at
    if above:
        parsed_values = parsed_values + tuple(
            _free_route_decimal(value) if value is not None else parsed_values[index]
            for index, value in enumerate(above)
        )

    version_text = _free_route_text(version)
    if version_text is not None and len(version_text) > 256:
        version_text = None
    return (
        tuple(value for value in parsed_values if value is not None),
        _free_route_cost_source(source),
        source_url,
        version_text,
        fetched_at,
    )


def _free_route_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _free_route_cost_source(value: Any) -> CostSource | None:
    source = _free_route_text(value)
    return cast(CostSource, source) if source in {*_FREE_ROUTE_PRICE_SOURCES, "none"} else None


def _free_route_etag(value: Any) -> str | None:
    etag = _free_route_text(value)
    if etag is None or len(etag) > 512 or any(ord(char) < 32 for char in etag):
        return None
    return etag


def _free_route_safe_source_url(value: Any) -> str | None:
    source_url = _free_route_text(value)
    if source_url is None or len(source_url) > 2048:
        return None
    try:
        parts = urlsplit(source_url)
    except ValueError:
        return None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        return None
    return source_url


def _free_route_current(timestamp: datetime | None, now: datetime, max_age: timedelta) -> bool:
    if timestamp is None:
        return False
    age = now - timestamp
    return timedelta(0) <= age <= max_age


def _matching_free_quota(
    row: Mapping[str, Any], entitlement: Mapping[str, Any] | None, now: datetime
) -> tuple[datetime | None, datetime | None] | None:
    if not isinstance(entitlement, Mapping) or entitlement.get("kind") != "free_quota":
        return None
    if entitlement.get("provider_scope") != row.get("provider_scope"):
        return None
    if entitlement.get("account_scope") != row.get("account_scope"):
        return None
    model_ids = entitlement.get("model_ids")
    if not isinstance(model_ids, (list, tuple, set, frozenset)):
        return None
    model_id = row.get("model_id")
    if not isinstance(model_id, str) or model_id not in model_ids:
        return None
    remaining = _free_route_decimal(entitlement.get("remaining"))
    if remaining is None or remaining <= _ZERO:
        return None
    observed_at = _free_route_utc(entitlement.get("observed_at"))
    expires_at = _free_route_utc(entitlement.get("expires_at"))
    if not _free_route_current(observed_at, now, _FREE_ROUTE_EVIDENCE_MAX_AGE):
        return None
    if expires_at is None or expires_at <= now:
        return None
    return observed_at, expires_at


def classify_cost(
    row: Mapping[str, Any],
    entitlement: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
    max_age: timedelta = _FREE_ROUTE_EVIDENCE_MAX_AGE,
) -> FreeRouteCostClass:
    """Classify route cost without treating absent or stale data as zero.

    `provider_scope` and `account_scope` are opaque non-secret identifiers
    supplied by the host. Do not pass API keys, refresh tokens, or other
    credentials as scope values.
    """
    if not isinstance(row, Mapping) or not isinstance(max_age, timedelta) or max_age < timedelta(0):
        return "UNKNOWN"
    max_age = min(max_age, _FREE_ROUTE_EVIDENCE_MAX_AGE)
    as_of = _free_route_utc(now) if now is not None else _UTC_NOW()
    observed_at = _free_route_utc(row.get("observed_at"))
    if (
        as_of is None
        or not _free_route_scope_matches(row)
        or not _free_route_current(observed_at, as_of, max_age)
    ):
        return "UNKNOWN"

    billing_mode = str(row.get("billing_mode") or "").strip().lower()
    if billing_mode in {"subscription", "subscription_included"}:
        return "SUBSCRIPTION_INCLUDED"
    if billing_mode in {"local", "local_configured"} and row.get("configured") is True:
        return "LOCAL_CONFIGURED"

    quota = _matching_free_quota(row, entitlement, as_of)
    if quota is not None:
        return "VERIFIED_FREE_QUOTA"

    prices, source, source_url, version, fetched_at = _free_route_price_fields(row)
    if (
        prices is None
        or source not in _FREE_ROUTE_PRICE_SOURCES
        or not version
        or (source not in {"user_override", "custom_contract"} and not source_url)
        or not _free_route_current(fetched_at, as_of, max_age)
    ):
        return "UNKNOWN"

    if all(price == _ZERO for price in prices):
        return "VERIFIED_ZERO_PRICE"
    return "PAID"


def _free_route_revision_payload(route: FreeRoute) -> dict[str, Any]:
    def stamp(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    return {
        "provider": route.provider,
        "provider_scope": route.provider_scope,
        "account_scope": route.account_scope,
        "model_id": route.model_id,
        "cost_class": route.cost_class,
        "price_source": route.price_source,
        "price_source_url": route.price_source_url,
        "price_version": route.price_version,
        "supported_tools": sorted(route.supported_tools) if route.supported_tools is not None else None,
        "entitlement_expires_at": stamp(route.entitlement_expires_at),
        "availability": route.availability,
    }


def _free_route_revision(
    routes: tuple[FreeRoute, ...], provider_scope: str, account_scope: str
) -> str:
    payload = {
        "provider_scope": provider_scope,
        "account_scope": account_scope,
        "routes": [_free_route_revision_payload(route) for route in routes],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _FREE_ROUTE_MAX_SNAPSHOT_BYTES:
        raise ValueError("free-route catalogue exceeds the snapshot size limit")
    return hashlib.sha256(encoded).hexdigest()


def build_free_route_snapshot(
    rows: Any,
    *,
    provider_scope: str,
    account_scope: str,
    now: datetime | None = None,
    entitlements: Mapping[str, Mapping[str, Any]] | None = None,
) -> FreeRouteSnapshot:
    """Build a validated immutable replacement from already approved data.

    Rows outside the exact provider/account scope and malformed model rows are
    omitted. Duplicate model IDs are omitted entirely to avoid an ambiguous
    route choice. The caller owns source approval and bounded network parsing.
    """
    if not isinstance(provider_scope, str) or not provider_scope.strip():
        raise ValueError("provider_scope must be a non-empty opaque scope")
    if not isinstance(account_scope, str) or not account_scope.strip():
        raise ValueError("account_scope must be a non-empty opaque scope")
    as_of = _free_route_utc(now) if now is not None else _UTC_NOW()
    if as_of is None:
        raise ValueError("now must be a timezone-aware datetime")
    if isinstance(rows, (str, bytes, Mapping)):
        raise ValueError("rows must be an iterable of model mappings")
    try:
        source_rows = []
        for row in rows:
            if len(source_rows) >= _FREE_ROUTE_MAX_ROWS:
                raise ValueError("free-route catalogue exceeds the row limit")
            source_rows.append(row)
    except TypeError as exc:
        raise ValueError("rows must be an iterable of model mappings") from exc

    scoped: list[Mapping[str, Any]] = []
    counts: dict[str, int] = {}
    for row in source_rows:
        if not isinstance(row, Mapping):
            continue
        model_id = row.get("model_id")
        row_provider_scope = row.get("provider_scope")
        row_account_scope = row.get("account_scope")
        if (
            not isinstance(model_id, str)
            or not model_id.strip()
            or model_id != model_id.strip()
            or len(model_id) > 512
            or row_provider_scope != provider_scope
            or row_account_scope != account_scope
            or not isinstance(row.get("provider"), str)
            or not row["provider"].strip()
            or len(row["provider"]) > 128
        ):
            continue
        counts[model_id] = counts.get(model_id, 0) + 1
        scoped.append(row)

    routes: list[FreeRoute] = []
    for row in scoped:
        model_id = row["model_id"].strip()
        if counts[model_id] != 1:
            continue
        entitlement = row.get("entitlement")
        if not isinstance(entitlement, Mapping) and entitlements is not None:
            entitlement = entitlements.get(model_id)
        entitlement_match = (
            _matching_free_quota(row, entitlement, as_of)
            if isinstance(entitlement, Mapping)
            else None
        )
        prices, source, source_url, version, price_fetched_at = _free_route_price_fields(row)
        del prices

        raw_tools = row.get("supported_tools")
        if isinstance(raw_tools, (list, tuple, set, frozenset)) and len(raw_tools) <= 128 and all(
            isinstance(tool, str) and tool.strip() and len(tool) <= 128 for tool in raw_tools
        ):
            supported_tools: frozenset[str] | None = frozenset(
                tool.strip() for tool in raw_tools
            )
        else:
            supported_tools = None
        observed_at = _free_route_utc(row.get("observed_at"))
        age = (as_of - observed_at).total_seconds() if observed_at is not None else None
        availability_raw = row.get("availability") or row.get("status") or "available"
        availability = (
            availability_raw.strip().lower()
            if isinstance(availability_raw, str) and len(availability_raw) <= 32
            else "unknown"
        )
        if availability not in {"available", "active", "deprecated", "unavailable", "disabled"}:
            availability = "unknown"
        routes.append(
            FreeRoute(
                provider=row["provider"].strip(),
                provider_scope=provider_scope,
                account_scope=account_scope,
                model_id=model_id,
                cost_class=classify_cost(row, entitlement, now=as_of),
                price_source=source,
                price_source_url=source_url,
                price_version=version,
                price_fetched_at=price_fetched_at,
                supported_tools=supported_tools,
                entitlement_expires_at=entitlement_match[1] if entitlement_match else None,
                entitlement_observed_at=entitlement_match[0] if entitlement_match else None,
                observed_at=observed_at,
                observation_age_seconds=age if age is not None and age >= 0 else None,
                availability=availability,
            )
        )

    routes.sort(key=lambda route: (route.provider, route.model_id))
    frozen_routes = tuple(routes)
    revision = _free_route_revision(frozen_routes, provider_scope, account_scope)
    return FreeRouteSnapshot(
        revision=revision,
        provider_scope=provider_scope,
        account_scope=account_scope,
        created_at=as_of,
        routes=frozen_routes,
        validated_in_process=True,
    )


def eligible_routes(
    snapshot: FreeRouteSnapshot,
    policy: FreeRoutePolicy,
    *,
    now: datetime | None = None,
) -> tuple[FreeRoute, ...]:
    """Return only fresh, exact-scope, tool-supported no-charge routes.

    Paid, unknown, and local rows are never fallback candidates. Subscription
    inclusion is a separate explicit policy choice and remains disabled by
    default.
    """
    if not isinstance(snapshot, FreeRouteSnapshot) or not isinstance(policy, FreeRoutePolicy):
        return ()
    as_of = _free_route_utc(now) if now is not None else _UTC_NOW()
    if (
        as_of is None
        or not isinstance(policy.max_evidence_age, timedelta)
        or policy.max_evidence_age < timedelta(0)
    ):
        return ()
    max_age = min(policy.max_evidence_age, _FREE_ROUTE_EVIDENCE_MAX_AGE)
    if (
        snapshot.provider_scope != policy.provider_scope
        or snapshot.account_scope != policy.account_scope
        or not snapshot.validated_in_process
    ):
        return ()
    eligible: list[FreeRoute] = []
    for route in snapshot.routes:
        if route.provider_scope != policy.provider_scope or route.account_scope != policy.account_scope:
            continue
        if route.availability not in {"available", "active"}:
            continue
        if route.supported_tools is None or not policy.required_tools.issubset(route.supported_tools):
            continue
        if not _free_route_current(route.observed_at, as_of, max_age):
            continue
        if route.cost_class == "VERIFIED_ZERO_PRICE":
            if not _free_route_current(route.price_fetched_at, as_of, max_age):
                continue
        elif route.cost_class == "VERIFIED_FREE_QUOTA":
            if not _free_route_current(route.entitlement_observed_at, as_of, max_age):
                continue
            if route.entitlement_expires_at is None or route.entitlement_expires_at <= as_of:
                continue
        elif route.cost_class == "SUBSCRIPTION_INCLUDED" and policy.allow_subscription_included:
            pass
        else:
            continue
        eligible.append(route)
    return tuple(eligible)


class FreeRouteCatalogueOwner:
    """Host-owned, cache-only-reader catalogue with 12h single-flight refresh.

    The host supplies one approved fetch adapter per provider/account scope and
    calls :meth:`refresh_if_due` at startup and after wake. Reads through
    :meth:`get_snapshot` never perform network I/O. The adapter must enforce
    provider-specific request timeouts of at most 30 seconds and response-byte
    limits before parsing. Joining callers wait at most 30 seconds for an
    in-flight refresh; a timed-out caller receives the current last-good view.
    """

    def __init__(
        self,
        fetch: Callable[[str | None], FreeRouteFetchResult],
        *,
        provider_scope: str,
        account_scope: str,
        clock: Callable[[], datetime] = _UTC_NOW,
    ) -> None:
        if not callable(fetch):
            raise TypeError("fetch must be callable")
        if not isinstance(provider_scope, str) or not provider_scope.strip():
            raise ValueError("provider_scope must be a non-empty opaque scope")
        if not isinstance(account_scope, str) or not account_scope.strip():
            raise ValueError("account_scope must be a non-empty opaque scope")
        self._fetch = fetch
        self.provider_scope = provider_scope
        self.account_scope = account_scope
        self._clock = clock
        self._refresh_interval = _FREE_ROUTE_REFRESH_INTERVAL
        self._manual_debounce = _FREE_ROUTE_MANUAL_DEBOUNCE
        self._condition = threading.Condition()
        self._snapshot: FreeRouteSnapshot | None = None
        self._etag: str | None = None
        self._last_successful_refresh_at: datetime | None = None
        self._last_manual_refresh_at: datetime | None = None
        self._retry_after_at: datetime | None = None
        self._inflight = False

    def get_snapshot(self) -> FreeRouteSnapshot | None:
        """Return the current immutable snapshot without fetching."""
        with self._condition:
            return self._snapshot

    def refresh_if_due(self) -> FreeRouteSnapshot | None:
        """Refresh when cold or at least twelve hours past success."""
        return self._refresh(manual=False)

    def manual_refresh(self) -> FreeRouteSnapshot | None:
        """Refresh on explicit request, debounced and subject to 429 backoff."""
        return self._refresh(manual=True)

    def _refresh(self, *, manual: bool) -> FreeRouteSnapshot | None:
        with self._condition:
            if self._inflight:
                deadline = time.monotonic() + _FREE_ROUTE_SINGLE_FLIGHT_WAIT_SECONDS
                while self._inflight:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return self._snapshot
                    self._condition.wait(timeout=remaining)
                return self._snapshot

            started_at = _free_route_utc(self._clock())
            if started_at is None:
                return self._snapshot
            if self._retry_after_at is not None and started_at < self._retry_after_at:
                return self._snapshot
            if manual:
                if (
                    self._last_manual_refresh_at is not None
                    and started_at - self._last_manual_refresh_at < self._manual_debounce
                ):
                    return self._snapshot
                self._last_manual_refresh_at = started_at
            elif (
                self._last_successful_refresh_at is not None
                and self._snapshot is not None
                and self._snapshot.validated_in_process
                and started_at - self._last_successful_refresh_at < self._refresh_interval
            ):
                return self._snapshot
            self._inflight = True
            etag = self._etag

        result: FreeRouteFetchResult | None = None
        try:
            result = self._fetch(etag)
        except Exception:
            # Adapter exceptions may include credential-bearing URLs or headers.
            logger.debug("free-route catalogue refresh failed")

        completed_at = _free_route_utc(self._clock()) or started_at
        with self._condition:
            try:
                if isinstance(result, FreeRouteFetchResult) and result.status_code == 200:
                    try:
                        new_snapshot = build_free_route_snapshot(
                            result.rows,
                            provider_scope=self.provider_scope,
                            account_scope=self.account_scope,
                            now=completed_at,
                        )
                    except (TypeError, ValueError):
                        new_snapshot = None
                    if new_snapshot is not None:
                        self._snapshot = new_snapshot
                        self._etag = _free_route_etag(result.etag)
                        self._last_successful_refresh_at = completed_at
                        self._retry_after_at = None
                elif isinstance(result, FreeRouteFetchResult) and result.status_code == 304:
                    # A catalogue 304 does not refresh embedded price or grant evidence.
                    if self._snapshot is not None:
                        self._etag = _free_route_etag(result.etag) or self._etag
                        self._last_successful_refresh_at = completed_at
                        self._retry_after_at = None
                    else:
                        self._retry_after_at = completed_at + _FREE_ROUTE_RETRY_BACKOFF
                elif isinstance(result, FreeRouteFetchResult) and result.status_code == 429:
                    try:
                        seconds = (
                            math.nan
                            if result.retry_after_seconds is None
                            or isinstance(result.retry_after_seconds, bool)
                            else float(result.retry_after_seconds)
                        )
                    except (TypeError, ValueError, OverflowError):
                        seconds = math.nan
                    if math.isfinite(seconds) and seconds >= 0:
                        capped_seconds = min(
                            max(1.0, seconds),
                            _FREE_ROUTE_MAX_RETRY_AFTER.total_seconds(),
                        )
                        delay = timedelta(seconds=capped_seconds)
                    else:
                        delay = _FREE_ROUTE_RETRY_BACKOFF
                    self._retry_after_at = completed_at + delay
                else:
                    self._retry_after_at = completed_at + _FREE_ROUTE_RETRY_BACKOFF

                return self._snapshot
            finally:
                self._inflight = False
                self._condition.notify_all()
