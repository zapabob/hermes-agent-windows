"""Fail-closed model cost and eligibility projection for delegation."""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import math
import os
import socket
import ssl
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Collection, Literal, Mapping, cast
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
_FREE_ROUTE_MAX_PROVIDER_RESPONSE_BYTES = 4 * 1024 * 1024
_FREE_ROUTE_PROVIDER_CHUNK_BYTES = 64 * 1024
_FREE_ROUTE_PROVIDER_MAX_MODELS = 1000
_FREE_ROUTE_FILE_LOCK_WAIT_SECONDS = 30.0
_FREE_ROUTE_WAKE_CHECK_INTERVAL = timedelta(minutes=5)
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_MODELS_PATH = "/api/v1/models"
_OPENROUTER_REQUEST_BUDGET_SCOPE = "public:openrouter:catalogue"
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
    price_values: tuple[Decimal, ...] | None
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


def _header_value(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:
        value = None
    if isinstance(value, str):
        return value
    try:
        items = headers.items()
    except Exception:
        return None
    for key, candidate in items:
        if isinstance(key, str) and key.lower() == name.lower() and isinstance(candidate, str):
            return candidate
    return None


def _request_retry_after(value: str | None, now: datetime) -> float | None:
    if value is None or len(value) > 128:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        parsed_at = _free_route_utc(parsed)
        return max(0.0, (parsed_at - now).total_seconds()) if parsed_at is not None else None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _lease_timeout(lease: Any) -> float:
    values = (
        getattr(lease, "connect_timeout_seconds", None),
        getattr(lease, "read_idle_timeout_seconds", None),
        getattr(lease, "total_timeout_seconds", None),
        getattr(lease, "remaining_seconds", None),
    )
    bounded: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed) and parsed > 0:
            bounded.append(parsed)
    if len(bounded) != len(values):
        raise TimeoutError("catalogue request lease has no usable deadline")
    timeout = min(bounded)
    if timeout > 30.0:
        raise TimeoutError("catalogue request lease exceeds the host limit")
    return timeout


def _set_response_read_timeout(response: Any, timeout: float) -> None:
    """Clamp the provider response socket before each bounded body read."""
    try:
        sock = response.fp.raw._sock
    except AttributeError as exc:
        raise TimeoutError("provider response socket is unavailable") from exc
    sock.settimeout(timeout)


def _set_connection_read_timeout(connection: Any, timeout: float) -> None:
    """Clamp connect/header reads to the remaining request lease deadline."""
    sock = getattr(connection, "sock", None)
    if sock is None:
        raise TimeoutError("provider connection socket is unavailable")
    sock.settimeout(timeout)


def _lease_read_timeout(lease: Any) -> float:
    try:
        timeout = min(float(lease.read_idle_timeout_seconds), float(lease.remaining_seconds))
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise TimeoutError("catalogue read deadline is unavailable") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        check_active = getattr(lease, "check_active", None)
        if callable(check_active):
            check_active()
        raise TimeoutError("catalogue read deadline expired")
    return timeout


def _run_with_lease_deadline(lease: Any, operation: Callable[[], Any]) -> Any:
    """Recheck an absolute deadline when a socket timeout races its timer."""
    try:
        return operation()
    except TimeoutError:
        check_active = getattr(lease, "check_active", None)
        if callable(check_active):
            check_active()
        raise


def _abort_connection(connection: Any) -> None:
    """Interrupt the active HTTPS socket when the shared lease expires."""
    try:
        sock = getattr(connection, "sock", None)
        if sock is not None:
            sock.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError, ValueError):
        pass
    try:
        connection.close()
    except (AttributeError, OSError, ValueError):
        pass


class OpenRouterFreeRouteAdapter:
    """Bounded, unauthenticated adapter for the approved OpenRouter catalogue.

    ``allowed_model_ids`` comes from Hermes' existing cache-only curated model
    authority. This adapter has no configurable URL and never attaches account
    credentials. The public request-budget scope is intentionally independent
    from the profile-local scope applied to returned rows.
    """

    def __init__(
        self,
        *,
        account_scope: str,
        allowed_model_ids: Collection[str],
        budget: Any | None = None,
        connection_factory: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] = _UTC_NOW,
    ) -> None:
        if not isinstance(account_scope, str) or not account_scope.strip() or len(account_scope) > 256:
            raise ValueError("account_scope must be a bounded opaque scope")
        if isinstance(allowed_model_ids, (str, bytes)):
            raise TypeError("allowed_model_ids must be a collection of model ids")
        allowed: set[str] = set()
        for model_id in allowed_model_ids:
            if isinstance(model_id, str) and model_id.strip() == model_id and 0 < len(model_id) <= 512:
                allowed.add(model_id)
        self.account_scope = account_scope
        self.allowed_model_ids = frozenset(allowed)
        self._budget = budget
        self._connection_factory = connection_factory or self._open
        self._clock = clock

    @staticmethod
    def _open(*, timeout: float):
        # A direct HTTPSConnection keeps the approved origin fixed and exposes
        # its socket before response headers are read, allowing the budget
        # lease's deadline callback to interrupt a slow header stream.
        return http.client.HTTPSConnection(
            "openrouter.ai",
            timeout=timeout,
            context=ssl.create_default_context(),
        )

    def _resolve_budget(self) -> Any:
        if self._budget is not None:
            return self._budget
        # The budgeting layer is a required security boundary. Import failure
        # is handled by __call__ as a closed request; there is no urllib-only
        # fallback that could bypass the host's shared request controls.
        from downstream.delegation.network_budget import DEFAULT_NETWORK_REQUEST_BUDGET

        return DEFAULT_NETWORK_REQUEST_BUDGET

    def __call__(self, etag: str | None) -> FreeRouteFetchResult:
        if not self.allowed_model_ids:
            return FreeRouteFetchResult(status_code=503)
        try:
            budget = self._resolve_budget()
            with budget.reserve(_OPENROUTER_REQUEST_BUDGET_SCOPE, "catalogue") as lease:
                check_active = getattr(lease, "check_active", None)
                mark_progress = getattr(lease, "mark_progress", None)
                record_retry_after = getattr(lease, "record_retry_after", None)
                if (
                    not callable(check_active)
                    or not callable(mark_progress)
                    or not callable(record_retry_after)
                ):
                    raise TypeError("catalogue request lease is incomplete")
                check_active()
                timeout = _lease_timeout(lease)
                headers = {
                    "Accept": "application/json",
                    "User-Agent": "hermes-free-route-catalogue",
                }
                validated_etag = _free_route_etag(etag)
                if validated_etag:
                    headers["If-None-Match"] = validated_etag
                connection = self._connection_factory(timeout=timeout)
                set_abort_callback = getattr(lease, "set_abort_callback", None)
                if not callable(set_abort_callback):
                    connection.close()
                    raise TypeError("catalogue request lease cannot abort a blocked transport")
                set_abort_callback(lambda _reason: _abort_connection(connection))
                try:
                    _run_with_lease_deadline(lease, connection.connect)
                    check_active()
                    _set_connection_read_timeout(connection, _lease_read_timeout(lease))
                    _run_with_lease_deadline(
                        lease,
                        lambda: connection.request(
                            "GET", _OPENROUTER_MODELS_PATH, headers=headers
                        ),
                    )
                    check_active()
                    _set_connection_read_timeout(connection, _lease_read_timeout(lease))
                    response = _run_with_lease_deadline(lease, connection.getresponse)
                    with response:
                        status = getattr(response, "status", None)
                        if isinstance(status, bool) or not isinstance(status, int):
                            raise ValueError("provider response status is invalid")
                        response_etag = _free_route_etag(_header_value(getattr(response, "headers", None), "ETag"))
                        if status == 304:
                            return FreeRouteFetchResult(status_code=304, etag=response_etag)
                        if status == 429:
                            now = _free_route_utc(self._clock())
                            retry_after = _request_retry_after(
                                _header_value(getattr(response, "headers", None), "Retry-After"),
                                now or datetime.now(timezone.utc),
                            )
                            if retry_after is not None:
                                record_retry_after(retry_after)
                            return FreeRouteFetchResult(
                                status_code=429,
                                etag=response_etag,
                                retry_after_seconds=retry_after,
                            )
                        if status != 200:
                            return FreeRouteFetchResult(status_code=status)

                        raw_length = _header_value(getattr(response, "headers", None), "Content-Length")
                        if raw_length is not None:
                            try:
                                length = int(raw_length)
                            except (TypeError, ValueError, OverflowError) as exc:
                                raise ValueError("provider response length is invalid") from exc
                            if length < 0 or length > _FREE_ROUTE_MAX_PROVIDER_RESPONSE_BYTES:
                                raise ValueError("provider response exceeds byte limit")

                        body = bytearray()
                        while True:
                            check_active()
                            read_timeout = _lease_read_timeout(lease)
                            _set_response_read_timeout(response, read_timeout)
                            size = min(
                                _FREE_ROUTE_PROVIDER_CHUNK_BYTES,
                                _FREE_ROUTE_MAX_PROVIDER_RESPONSE_BYTES - len(body) + 1,
                            )
                            read_chunk = getattr(response, "read1", None)
                            if not callable(read_chunk):
                                raise TypeError("provider response has no single-read operation")
                            # HTTPResponse.read1 performs at most one underlying
                            # buffered read. The shared lease timer also closes
                            # the socket at the total deadline, including while
                            # HTTPResponse parses trickled headers.
                            chunk = _run_with_lease_deadline(
                                lease, lambda: read_chunk(size)
                            )
                            mark_progress()
                            if not isinstance(chunk, (bytes, bytearray)):
                                raise ValueError("provider response body is not bytes")
                            if not chunk:
                                break
                            body.extend(chunk)
                            if len(body) > _FREE_ROUTE_MAX_PROVIDER_RESPONSE_BYTES:
                                raise ValueError("provider response exceeds byte limit")
                        if raw_length is not None and len(body) != length:
                            raise ValueError("provider response length does not match its header")
                        check_active()
                        payload = json.loads(
                            bytes(body).decode("utf-8"),
                            parse_float=Decimal,
                            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid JSON number")),
                        )
                        pricing_version = (
                            response_etag
                            if response_etag is not None and len(response_etag) <= 256
                            else hashlib.sha256(body).hexdigest()
                        )
                        rows = self._normalize_payload(payload, pricing_version)
                        check_active()
                        return FreeRouteFetchResult(status_code=200, rows=rows, etag=response_etag)
                finally:
                    connection.close()
        except Exception:
            # Provider, lease and decoder exceptions may carry headers or
            # endpoint details. Preserve the last-good snapshot without logging
            # exception text or retrying through another transport.
            return FreeRouteFetchResult(status_code=503)

    def _normalize_payload(
        self, payload: Any, pricing_version: str
    ) -> tuple[Mapping[str, Any], ...]:
        if not isinstance(payload, Mapping):
            raise ValueError("provider catalogue root must be an object")
        items = payload.get("data")
        if not isinstance(items, list) or len(items) > _FREE_ROUTE_PROVIDER_MAX_MODELS:
            raise ValueError("provider catalogue rows exceed the limit")
        total_count = payload.get("total_count")
        if total_count is not None:
            if (
                isinstance(total_count, bool)
                or not isinstance(total_count, int)
                or total_count < len(items)
                or total_count > _FREE_ROUTE_PROVIDER_MAX_MODELS
            ):
                raise ValueError("provider catalogue response is incomplete or inconsistent")
        observed_at = _free_route_utc(self._clock())
        if observed_at is None:
            raise ValueError("catalogue clock must be timezone-aware")
        rows: list[Mapping[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            model_id = item.get("id")
            if (
                not isinstance(model_id, str)
                or model_id not in self.allowed_model_ids
                or len(model_id) > 512
            ):
                continue
            architecture = item.get("architecture")
            if not isinstance(architecture, Mapping):
                continue
            input_modalities = architecture.get("input_modalities")
            output_modalities = architecture.get("output_modalities")
            if (
                not isinstance(input_modalities, list)
                or "text" not in input_modalities
                or not isinstance(output_modalities, list)
                or "text" not in output_modalities
            ):
                continue
            supported_parameters = item.get("supported_parameters")
            if not isinstance(supported_parameters, list) or "tools" not in supported_parameters:
                continue
            pricing = item.get("pricing")
            if not isinstance(pricing, Mapping):
                continue
            normalized_prices: dict[str, str | None] = {}
            for key, target in (
                ("prompt", "input_cost_per_million"),
                ("completion", "output_cost_per_million"),
                ("input_cache_read", "cache_read_cost_per_million"),
                ("input_cache_write", "cache_write_cost_per_million"),
            ):
                amount = _free_route_decimal(pricing.get(key))
                normalized_prices[target] = (
                    str(amount * Decimal(1_000_000))
                    if amount is not None and amount >= _ZERO
                    else None
                )
            request_price = _free_route_decimal(pricing.get("request"))
            normalized_prices["request_cost"] = (
                str(request_price)
                if request_price is not None and request_price >= _ZERO
                else None
            )
            # OpenRouter reports some modality-specific prices independently.
            # Since the route is limited to text modalities, a nonzero or
            # malformed extra charge remains an unknown price rather than
            # being silently treated as free.
            for key, value in pricing.items():
                if key in {"prompt", "completion", "request", "input_cache_read", "input_cache_write"}:
                    continue
                amount = _free_route_decimal(value)
                if amount is None or amount < _ZERO or amount != _ZERO:
                    normalized_prices["request_cost"] = None
                    break
            expiry_raw = item.get("expiration_date")
            availability = "available"
            if expiry_raw is not None:
                expiry = _free_route_utc(expiry_raw)
                if expiry is None:
                    availability = "unknown"
                elif expiry <= observed_at:
                    availability = "unavailable"
            rows.append(
                {
                    "provider": "openrouter",
                    "provider_scope": "openrouter:public",
                    "account_scope": self.account_scope,
                    "model_id": model_id,
                    "billing_mode": "provider_models_api",
                    "pricing": {
                        **normalized_prices,
                        "source": "provider_models_api",
                        "source_url": _OPENROUTER_MODELS_URL,
                        "pricing_version": pricing_version,
                        "fetched_at": observed_at.isoformat(),
                    },
                    "supported_tools": ["text"],
                    "observed_at": observed_at.isoformat(),
                    "availability": availability,
                }
            )
        return tuple(rows)


_free_route_local_locks_guard = threading.Lock()
_free_route_local_locks: dict[str, threading.Lock] = {}


@contextmanager
def _free_route_file_lock(path: Path | None):
    """Hold a bounded OS file lock so separate host processes coalesce refreshes."""
    if path is None:
        yield True
        return
    lock_key = os.path.normcase(str(path.resolve()))
    with _free_route_local_locks_guard:
        local_lock = _free_route_local_locks.setdefault(lock_key, threading.Lock())
    if not local_lock.acquire(timeout=_FREE_ROUTE_FILE_LOCK_WAIT_SECONDS):
        yield False
        return
    lock_path = path.with_suffix(path.suffix + ".lock")
    handle = None
    acquired = False
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + _FREE_ROUTE_FILE_LOCK_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (ImportError, OSError):
                time.sleep(0.05)
        yield acquired
    finally:
        if acquired and handle is not None:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
        if handle is not None:
            handle.close()
        local_lock.release()


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
    row: Mapping[str, Any],
    entitlement: Mapping[str, Any] | None,
    now: datetime,
    max_age: timedelta,
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
    if not _free_route_current(observed_at, now, max_age):
        return None
    if expires_at is None or expires_at <= now:
        return None
    return observed_at, expires_at


def _matching_subscription_entitlement(
    row: Mapping[str, Any],
    entitlement: Mapping[str, Any] | None,
    now: datetime,
    max_age: timedelta,
) -> tuple[datetime, datetime] | None:
    if (
        not isinstance(entitlement, Mapping)
        or entitlement.get("kind") != "subscription_included"
        or entitlement.get("provider_scope") != row.get("provider_scope")
        or entitlement.get("account_scope") != row.get("account_scope")
        or entitlement.get("included") is not True
        or entitlement.get("active") is not True
    ):
        return None
    model_ids = entitlement.get("model_ids")
    model_id = row.get("model_id")
    if (
        not isinstance(model_ids, (list, tuple, set, frozenset))
        or not isinstance(model_id, str)
        or model_id not in model_ids
    ):
        return None
    observed_at = _free_route_utc(entitlement.get("observed_at"))
    expires_at = _free_route_utc(entitlement.get("expires_at"))
    if (
        observed_at is None
        or expires_at is None
        or not _free_route_current(observed_at, now, max_age)
        or expires_at <= now
    ):
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
        if _matching_subscription_entitlement(row, entitlement, as_of, max_age) is not None:
            return "SUBSCRIPTION_INCLUDED"
        return "UNKNOWN"
    if billing_mode in {"local", "local_configured"} and row.get("configured") is True:
        return "LOCAL_CONFIGURED"

    quota = _matching_free_quota(row, entitlement, as_of, max_age)
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

    def decimal_text(value: Decimal) -> str:
        if value.is_zero():
            return "0"
        sign, raw_digits, exponent = value.as_tuple()
        if not isinstance(exponent, int):
            return str(value)
        digits = list(raw_digits)
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        coefficient = "".join(str(digit) for digit in digits)
        return f"{'-' if sign else ''}{coefficient}" + (f"e{exponent}" if exponent else "")

    return {
        "provider": route.provider,
        "provider_scope": route.provider_scope,
        "account_scope": route.account_scope,
        "model_id": route.model_id,
        "cost_class": route.cost_class,
        "price_source": route.price_source,
        "price_source_url": route.price_source_url,
        "price_version": route.price_version,
        "price_values": (
            [decimal_text(value) for value in route.price_values]
            if route.price_values is not None
            else None
        ),
        "price_fetched_at": stamp(route.price_fetched_at),
        "supported_tools": sorted(route.supported_tools) if route.supported_tools is not None else None,
        "entitlement_expires_at": stamp(route.entitlement_expires_at),
        "entitlement_observed_at": stamp(route.entitlement_observed_at),
        "observed_at": stamp(route.observed_at),
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
    max_age: timedelta = _FREE_ROUTE_EVIDENCE_MAX_AGE,
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
    if not isinstance(max_age, timedelta) or max_age < timedelta(0):
        raise ValueError("max_age must be a non-negative timedelta")
    max_age = min(max_age, _FREE_ROUTE_EVIDENCE_MAX_AGE)
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
            _matching_free_quota(row, entitlement, as_of, max_age)
            if isinstance(entitlement, Mapping)
            else None
        )
        if entitlement_match is None and isinstance(entitlement, Mapping):
            entitlement_match = _matching_subscription_entitlement(
                row, entitlement, as_of, max_age
            )
        prices, source, source_url, version, price_fetched_at = _free_route_price_fields(row)

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
                cost_class=classify_cost(row, entitlement, now=as_of, max_age=max_age),
                price_source=source,
                price_source_url=source_url,
                price_version=version,
                price_values=prices,
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
            if not _free_route_current(route.entitlement_observed_at, as_of, max_age):
                continue
            if route.entitlement_expires_at is None or route.entitlement_expires_at <= as_of:
                continue
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
        cache_path: Path | str | None = None,
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
        self._cache_path = Path(cache_path) if cache_path is not None else None
        self._refresh_interval = _FREE_ROUTE_REFRESH_INTERVAL
        self._manual_debounce = _FREE_ROUTE_MANUAL_DEBOUNCE
        self._condition = threading.Condition()
        self._snapshot: FreeRouteSnapshot | None = None
        self._raw_rows: tuple[Mapping[str, Any], ...] = ()
        self._etag: str | None = None
        self._last_successful_refresh_at: datetime | None = None
        self._last_manual_refresh_at: datetime | None = None
        self._retry_after_at: datetime | None = None
        self._inflight = False
        self._load_persisted_state()

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
            self._inflight = True

        started_at = _free_route_utc(self._clock())
        if started_at is None:
            self._finish_inflight()
            return self.get_snapshot()
        try:
            with _free_route_file_lock(self._cache_path) as locked:
                if not locked:
                    return self.get_snapshot()
                if self._cache_path is not None:
                    self._load_persisted_state()
                with self._condition:
                    if self._refresh_is_suppressed(started_at, manual=manual):
                        return self._snapshot
                    if manual:
                        self._last_manual_refresh_at = started_at
                    etag = self._etag

                try:
                    result = self._fetch(etag)
                except Exception:
                    # Adapter exceptions may include credential-bearing URLs or headers.
                    logger.debug("free-route catalogue refresh failed")
                    result = None

                completed_at = _free_route_utc(self._clock()) or started_at
                with self._condition:
                    self._apply_fetch_result(result, completed_at)
                    self._persist_state()
                    return self._snapshot
        except Exception:
            logger.debug("free-route catalogue state update failed")
            return self.get_snapshot()
        finally:
            self._finish_inflight()

    def _finish_inflight(self) -> None:
        with self._condition:
            self._inflight = False
            self._condition.notify_all()

    def _refresh_is_suppressed(self, now: datetime, *, manual: bool) -> bool:
        if self._retry_after_at is not None and now < self._retry_after_at:
            return True
        if manual:
            return (
                self._last_manual_refresh_at is not None
                and now - self._last_manual_refresh_at < self._manual_debounce
            )
        return (
            self._last_successful_refresh_at is not None
            and self._snapshot is not None
            and self._snapshot.validated_in_process
            and now - self._last_successful_refresh_at < self._refresh_interval
        )

    def _apply_fetch_result(self, result: Any, completed_at: datetime) -> None:
        if isinstance(result, FreeRouteFetchResult) and result.status_code == 200:
            try:
                raw_rows = tuple(dict(row) for row in result.rows)
                new_snapshot = build_free_route_snapshot(
                    raw_rows,
                    provider_scope=self.provider_scope,
                    account_scope=self.account_scope,
                    now=completed_at,
                )
            except (TypeError, ValueError):
                new_snapshot = None
            if new_snapshot is not None and new_snapshot.routes:
                self._snapshot = new_snapshot
                self._raw_rows = raw_rows
                self._etag = _free_route_etag(result.etag)
                self._last_successful_refresh_at = completed_at
                self._retry_after_at = None
            else:
                self._retry_after_at = completed_at + _FREE_ROUTE_RETRY_BACKOFF
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

    def _load_persisted_state(self) -> None:
        path = self._cache_path
        if path is None:
            return
        try:
            if path.stat().st_size > _FREE_ROUTE_MAX_SNAPSHOT_BYTES:
                return
            with open(path, "r", encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
        except (OSError, ValueError, TypeError):
            return
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or payload.get("provider_scope") != self.provider_scope
            or payload.get("account_scope") != self.account_scope
        ):
            return
        raw_rows = payload.get("rows")
        if not isinstance(raw_rows, list) or len(raw_rows) > _FREE_ROUTE_MAX_ROWS:
            return
        if any(not isinstance(row, dict) for row in raw_rows):
            return
        snapshot: FreeRouteSnapshot | None = None
        created_at = _free_route_utc(payload.get("snapshot_created_at"))
        if raw_rows:
            if created_at is None:
                return
            try:
                snapshot = build_free_route_snapshot(
                    raw_rows,
                    provider_scope=self.provider_scope,
                    account_scope=self.account_scope,
                    now=created_at,
                )
            except (TypeError, ValueError):
                return
            if not snapshot.routes or snapshot.revision != payload.get("revision"):
                return
        last_success = _free_route_utc(payload.get("last_successful_refresh_at"))
        last_manual = _free_route_utc(payload.get("last_manual_refresh_at"))
        retry_after = _free_route_utc(payload.get("retry_after_at"))
        now = _free_route_utc(self._clock())
        if now is None:
            return
        if last_success is not None and last_success > now:
            last_success = None
        if last_manual is not None and last_manual > now:
            last_manual = None
        etag = _free_route_etag(payload.get("etag"))
        with self._condition:
            self._snapshot = snapshot
            self._raw_rows = tuple(raw_rows)
            self._etag = etag
            self._last_successful_refresh_at = last_success
            self._last_manual_refresh_at = last_manual
            self._retry_after_at = retry_after

    def _persist_state(self) -> None:
        path = self._cache_path
        if path is None:
            return
        snapshot = self._snapshot
        payload = {
            "version": 1,
            "provider_scope": self.provider_scope,
            "account_scope": self.account_scope,
            "revision": snapshot.revision if snapshot is not None else None,
            "snapshot_created_at": snapshot.created_at.isoformat() if snapshot is not None else None,
            "rows": list(self._raw_rows) if snapshot is not None else [],
            "etag": self._etag,
            "last_successful_refresh_at": (
                self._last_successful_refresh_at.isoformat()
                if self._last_successful_refresh_at is not None
                else None
            ),
            "last_manual_refresh_at": (
                self._last_manual_refresh_at.isoformat()
                if self._last_manual_refresh_at is not None
                else None
            ),
            "retry_after_at": self._retry_after_at.isoformat() if self._retry_after_at is not None else None,
        }
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if len(encoded) > _FREE_ROUTE_MAX_SNAPSHOT_BYTES:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(
                path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp"
            )
            with open(temporary, "wb") as cache_file:
                cache_file.write(encoded)
                cache_file.flush()
                os.fsync(cache_file.fileno())
            os.replace(temporary, path)
        except (OSError, TypeError, ValueError):
            logger.debug("free-route last-good snapshot persistence failed")


class FreeRouteCatalogueRefreshHost:
    """Run due checks on host startup, wake notification, and a local 5m tick.

    The five-minute timer only checks the persisted twelve-hour deadline; it
    does not create a second network cadence. It lets a sleeping Windows host
    refresh shortly after its worker resumes even when no power callback is
    available in the hosting process.
    """

    def __init__(
        self,
        owner: FreeRouteCatalogueOwner,
        *,
        check_interval: timedelta = _FREE_ROUTE_WAKE_CHECK_INTERVAL,
    ) -> None:
        if not isinstance(owner, FreeRouteCatalogueOwner):
            raise TypeError("owner must be a FreeRouteCatalogueOwner")
        if not isinstance(check_interval, timedelta) or check_interval <= timedelta(0):
            raise ValueError("check_interval must be positive")
        self.owner = owner
        self._check_interval = check_interval.total_seconds()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._restart_requested = False

    def _start_thread_locked(self) -> None:
        self._stop_event.clear()
        self._wake_event.set()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="free-route-catalogue-refresh",
        )
        self._thread.start()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop_event.is_set():
                    self._restart_requested = True
                else:
                    self._wake_event.set()
                return
            self._start_thread_locked()

    def notify_wake(self) -> None:
        """Coalesce an overdue refresh when the host reports or detects wake."""
        self._wake_event.set()

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive() and not self._stop_event.is_set()

    def request_stop(self) -> None:
        """Signal shutdown without waiting for a bounded in-flight fetch."""
        self._stop_event.set()
        self._wake_event.set()

    def stop(self, *, timeout: float = 0.25) -> None:
        self.request_stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._wake_event.wait(timeout=self._check_interval)
                self._wake_event.clear()
                if self._stop_event.is_set():
                    return
                try:
                    self.owner.refresh_if_due()
                except Exception:
                    logger.debug("free-route scheduled refresh failed")
        finally:
            with self._lock:
                if self._restart_requested:
                    self._restart_requested = False
                    self._start_thread_locked()


@dataclass(eq=False)
class _FreeRouteCatalogueHostRegistration:
    host: FreeRouteCatalogueRefreshHost
    owners: set["FreeRouteCatalogueHostLease"]


@dataclass(eq=False)
class FreeRouteCatalogueHostLease:
    """One lifecycle owner's idempotent claim on a shared profile host."""

    host: FreeRouteCatalogueRefreshHost
    _released: bool = False


_refresh_hosts_lock = threading.Lock()
_refresh_hosts: dict[Path, _FreeRouteCatalogueHostRegistration] = {}


def start_free_route_catalogue_refresh_host() -> FreeRouteCatalogueHostLease | None:
    """Start one profile-local, opt-in OpenRouter metadata refresher.

    A provider-scoped explicit setting gates this request independently of
    the model picker's default-on manifest. Model ids come from a cache-only
    read of the existing picker catalogue; no key or account endpoint is used.
    """
    try:
        from hermes_cli.model_catalog import (
            free_route_cache_path,
            get_cached_curated_openrouter_model_ids,
            openrouter_free_route_refresh_enabled,
        )
        from hermes_constants import get_hermes_home

        if not openrouter_free_route_refresh_enabled():
            return None
        allowed_model_ids = get_cached_curated_openrouter_model_ids()
        if not allowed_model_ids:
            return None
        cache_path = free_route_cache_path()
        cache_key = cache_path.resolve()
        profile_key = os.path.normcase(str(get_hermes_home().resolve()))
        account_scope = "profile:" + hashlib.sha256(profile_key.encode("utf-8")).hexdigest()[:24]
        with _refresh_hosts_lock:
            registration = _refresh_hosts.get(cache_key)
            if registration is None:
                adapter = OpenRouterFreeRouteAdapter(
                    account_scope=account_scope,
                    allowed_model_ids=allowed_model_ids,
                )
                owner = FreeRouteCatalogueOwner(
                    adapter,
                    provider_scope="openrouter:public",
                    account_scope=account_scope,
                    cache_path=cache_path,
                )
                host = FreeRouteCatalogueRefreshHost(owner)
                registration = _FreeRouteCatalogueHostRegistration(host=host, owners=set())
                _refresh_hosts[cache_key] = registration
            lease = FreeRouteCatalogueHostLease(registration.host)
            registration.owners.add(lease)
            try:
                registration.host.start()
            except Exception:
                registration.owners.discard(lease)
                if not registration.owners:
                    _refresh_hosts.pop(cache_key, None)
                raise
            return lease
    except Exception:
        # A model-catalogue background task must not affect host startup.
        logger.debug("free-route refresh host could not start")
        return None


def notify_free_route_catalogue_wake(
    host: FreeRouteCatalogueRefreshHost | FreeRouteCatalogueHostLease | None = None,
) -> None:
    """Notify a profile owner that the host has resumed and should check due time."""
    if host is not None:
        (host.host if isinstance(host, FreeRouteCatalogueHostLease) else host).notify_wake()
        return
    try:
        from hermes_cli.model_catalog import free_route_cache_path

        with _refresh_hosts_lock:
            registration = _refresh_hosts.get(free_route_cache_path().resolve())
        if registration is not None:
            registration.host.notify_wake()
    except Exception:
        logger.debug("free-route wake notification failed")


def stop_free_route_catalogue_refresh_host(
    host: FreeRouteCatalogueHostLease | FreeRouteCatalogueRefreshHost | None,
) -> None:
    """Release one host lifecycle claim; stop only after the last owner leaves."""
    if host is None:
        return
    if isinstance(host, FreeRouteCatalogueHostLease):
        host_to_stop = None
        with _refresh_hosts_lock:
            if host._released:
                return
            host._released = True
            for cache_key, registration in tuple(_refresh_hosts.items()):
                if registration.host is host.host:
                    registration.owners.discard(host)
                    if not registration.owners:
                        _refresh_hosts.pop(cache_key, None)
                        registration.host.request_stop()
                        host_to_stop = registration.host
                    break
        if host_to_stop is not None:
            host_to_stop.stop()
        return
    host.stop()
