"""Host-owned admission reservations for free-route delegated work.

This coordinator only reserves capacity and binds immutable evidence. It does
not construct, launch, retry, or schedule children. A host lifecycle owner must
supply trusted T05 lineage/tool scope, fresh T08 resource observations, and a
T09 catalogue snapshot before calling it.
"""

from __future__ import annotations

import math
import threading
import time
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Callable, Literal, TypeGuard

from downstream.delegation.free_routes import (
    FreeRoute,
    FreeRoutePolicy,
    FreeRouteSnapshot,
    eligible_routes,
)
from downstream.delegation.resources import (
    ResourceRequest,
    ResourceReservationBook,
    ResourceSnapshot,
)

_MAX_ACTIVE_TOP_LEVEL = 2
_MAX_ACTIVE_NESTED = 1
_MAX_ACTIVE_TOTAL = 3
_MAX_WAITERS = 8
_MAX_QUEUE_WAIT_SECONDS = 30.0
_MAX_RETRY_AFTER_SECONDS = 7 * 24 * 60 * 60.0
_RETRY_AFTER_FALLBACK_SECONDS = 60.0
_MAX_RETAINED_REQUEST_IDS = 4096
_MAX_TOOL_SCOPE_SIZE = 128
_MAX_IDENTIFIER_LENGTH = 256
_SOFT_DEADLINE_SECONDS = 180.0
_HARD_DEADLINE_SECONDS = 240.0
_IDLE_DEADLINE_SECONDS = 60.0
_READ_ONLY_TOOL_NAMES = frozenset(
    {
        "read_file",
        "search_files",
        "session_search",
        "skill_view",
        "skills_list",
        "web_extract",
        "web_search",
        "vision_analyze",
        "browser_snapshot",
        "browser_get_images",
    }
)

WriterOutcome = Literal["started", "not_started", "unknown"]
UnknownResolution = Literal["not_started", "completed"]


def _finite_number(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _valid_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= _MAX_IDENTIFIER_LENGTH
        and value == value.strip()
        and all(
            not char.isspace() and ord(char) >= 33 and ord(char) != 127
            for char in value
        )
    )


def _valid_tool_scope(value: object) -> bool:
    return (
        isinstance(value, frozenset)
        and len(value) <= _MAX_TOOL_SCOPE_SIZE
        and all(
            isinstance(tool, str)
            and 0 < len(tool) <= 128
            and tool.isascii()
            and all(char.isalnum() or char in "_.-" for char in tool)
            for tool in value
        )
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class AdmissionIntent:
    """Bounded host request to reserve one child slot and eligible route.

    ``parent_tool_scope`` is trusted T05 data and is required only for a
    top-level child. A nested child inherits its capabilities from the active
    parent grant. Scope identifiers are opaque, non-secret host identifiers.
    """

    request_id: str
    profile_scope: str
    account_scope: str
    tree_id: str
    parent_grant_id: str | None
    parent_tool_scope: frozenset[str]
    tool_scope: frozenset[str]
    route_snapshot: FreeRouteSnapshot
    route_policy: FreeRoutePolicy
    resource_snapshot: ResourceSnapshot
    resource_request: ResourceRequest
    queue_timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        for name in ("request_id", "profile_scope", "account_scope", "tree_id"):
            if not _valid_identifier(getattr(self, name)):
                raise ValueError(f"{name} must be a bounded opaque identifier")
        if self.parent_grant_id is not None and not _valid_identifier(self.parent_grant_id):
            raise ValueError("parent_grant_id must be a bounded opaque identifier")
        if not _valid_tool_scope(self.parent_tool_scope) or not _valid_tool_scope(
            self.tool_scope
        ):
            raise ValueError("tool scopes must be bounded immutable tool-name sets")
        if self.parent_grant_id is not None and self.parent_tool_scope:
            raise ValueError("nested requests inherit tools from their parent grant")
        if not isinstance(self.route_snapshot, FreeRouteSnapshot):
            raise TypeError("route_snapshot must be a FreeRouteSnapshot")
        if not isinstance(self.route_policy, FreeRoutePolicy):
            raise TypeError("route_policy must be a FreeRoutePolicy")
        if not isinstance(self.resource_snapshot, ResourceSnapshot):
            raise TypeError("resource_snapshot must be a ResourceSnapshot")
        if not isinstance(self.resource_request, ResourceRequest):
            raise TypeError("resource_request must be a ResourceRequest")
        if self.resource_request.route != "remote":
            raise ValueError("free-route admission only accepts remote resource requests")
        if self.account_scope != self.route_policy.account_scope:
            raise ValueError("account scope must match the route policy")
        if self.route_snapshot.provider_scope != self.route_policy.provider_scope:
            raise ValueError("provider scope must match the route policy")
        if self.route_snapshot.account_scope != self.account_scope:
            raise ValueError("account scope must match the route snapshot")
        if self.route_policy.required_tools != self.tool_scope:
            raise ValueError("route requirements must exactly match the granted tool scope")
        revision = self.route_snapshot.revision
        if (
            not isinstance(revision, str)
            or len(revision) != 64
            or any(char not in "0123456789abcdef" for char in revision)
        ):
            raise ValueError("route revision must be a SHA-256 identifier")
        if (
            not _finite_number(self.queue_timeout_seconds)
            or not 0 <= self.queue_timeout_seconds <= _MAX_QUEUE_WAIT_SECONDS
        ):
            raise ValueError("queue timeout must be between zero and thirty seconds")


@dataclass(frozen=True, slots=True)
class AdmissionGrant:
    """Immutable host-only route, lineage, capability, and deadline binding."""

    grant_id: str
    request_id: str
    profile_scope: str
    account_scope: str
    provider_scope: str
    tree_id: str
    parent_grant_id: str | None
    depth: int
    provider: str
    model_id: str
    route_revision: str
    cost_class: str
    tool_scope: frozenset[str]
    read_only: bool
    created_at_monotonic: float
    soft_deadline_monotonic: float
    idle_deadline_monotonic: float
    hard_deadline_monotonic: float


@dataclass(frozen=True, slots=True)
class AdmissionRejection:
    """Fixed-code refusal safe for status surfaces and callers."""

    code: str
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code or len(self.code) > 64:
            raise ValueError("rejection code must be a bounded safe identifier")
        if self.retry_after_seconds is not None and (
            not _finite_number(self.retry_after_seconds)
            or self.retry_after_seconds < 0
        ):
            raise ValueError("retry delay must be finite and non-negative")


@dataclass(slots=True)
class _GrantRecord:
    grant: AdmissionGrant
    resource_reservation_id: str | None
    state: Literal["pending", "running", "unknown"] = "pending"


@dataclass(slots=True)
class _AdmissionState:
    """Shared host admission ledger for owners using the same resource book."""

    monotonic_clock: Callable[[], float]
    utc_clock: Callable[[], datetime]
    condition: threading.Condition
    grants: dict[str, _GrantRecord]
    seen_request_ids: set[tuple[str, str, str]]
    blocked_trees: set[tuple[str, str, str]]
    last_route: dict[tuple[str, str, str], tuple[str, str]]
    cooldowns: dict[tuple[str, str, str], datetime]
    waiters: int = 0


_ADMISSION_STATES_LOCK = threading.Lock()
_ADMISSION_STATES: weakref.WeakKeyDictionary[
    ResourceReservationBook, _AdmissionState
] = weakref.WeakKeyDictionary()


def _admission_state_for(
    resource_book: ResourceReservationBook,
    monotonic_clock: Callable[[], float],
    utc_clock: Callable[[], datetime],
) -> _AdmissionState:
    with _ADMISSION_STATES_LOCK:
        state = _ADMISSION_STATES.get(resource_book)
        if state is None:
            state = _AdmissionState(
                monotonic_clock=monotonic_clock,
                utc_clock=utc_clock,
                condition=threading.Condition(threading.RLock()),
                grants={},
                seen_request_ids=set(),
                blocked_trees=set(),
                last_route={},
                cooldowns={},
            )
            _ADMISSION_STATES[resource_book] = state
        return state


class DelegationAdmission:
    """Serialize host reservations without taking over child execution.

    Admission limits are host-wide as well as per tree: at most two depth-one
    children and one depth-two read-only grandchild may hold reservations at
    once. Capacity waiters are counted and bounded; ``Condition.wait`` releases
    this owner lock, and no resource or database lock is held while waiting.
    Unknown writer outcomes retain their reservation and quarantine the tree
    until a host lifecycle owner explicitly resolves the terminal state.
    """

    def __init__(
        self,
        resource_book: ResourceReservationBook,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(resource_book, ResourceReservationBook):
            raise TypeError("resource_book must be a ResourceReservationBook")
        if not callable(monotonic_clock) or not callable(utc_clock):
            raise TypeError("clocks must be callable")
        self._resource_book = resource_book
        state = _admission_state_for(resource_book, monotonic_clock, utc_clock)
        self._monotonic_clock = state.monotonic_clock
        self._utc_clock = state.utc_clock
        self._condition = state.condition
        self._grants = state.grants
        self._seen_request_ids = state.seen_request_ids
        self._blocked_trees = state.blocked_trees
        self._last_route = state.last_route
        self._cooldowns = state.cooldowns
        self._state = state

    @property
    def waiting_count(self) -> int:
        """Return bounded in-memory waiter count for host status and tests."""
        with self._condition:
            return self._state.waiters

    def active_grants(self) -> tuple[AdmissionGrant, ...]:
        """Return immutable summaries of pending, running, and uncertain grants."""
        with self._condition:
            return tuple(record.grant for record in self._grants.values())

    def reserve(self, intent: AdmissionIntent) -> AdmissionGrant | AdmissionRejection:
        """Atomically reserve one eligible free route and execution slot.

        Waiting is opt-in through ``queue_timeout_seconds`` and is bounded to
        thirty seconds. The route and resource observations are revalidated
        after every wake; stale inputs fail closed through their existing T08
        and T09 authorities.
        """
        if not isinstance(intent, AdmissionIntent):
            return AdmissionRejection("invalid_intent")
        started_waiting = False
        try:
            with self._condition:
                start = self._monotonic_clock()
                if not self._finite_clock(start):
                    return AdmissionRejection("invalid_clock")
                queue_deadline = start + float(intent.queue_timeout_seconds)
                request_key = (
                    intent.profile_scope,
                    intent.account_scope,
                    intent.request_id,
                )
                tree_key = (intent.profile_scope, intent.account_scope, intent.tree_id)

                while True:
                    now_monotonic = self._monotonic_clock()
                    if not self._finite_clock(now_monotonic):
                        return AdmissionRejection("invalid_clock")
                    now_utc = self._utc_clock()
                    if (
                        not isinstance(now_utc, datetime)
                        or now_utc.tzinfo is None
                        or now_utc.utcoffset() is None
                    ):
                        return AdmissionRejection("invalid_clock")
                    now_utc = now_utc.astimezone(timezone.utc)

                    if started_waiting and now_monotonic >= queue_deadline:
                        return AdmissionRejection("queue_deadline")
                    if tree_key in self._blocked_trees:
                        return AdmissionRejection("writer_outcome_unknown")
                    if request_key in self._seen_request_ids:
                        return AdmissionRejection("duplicate_request")
                    if len(self._seen_request_ids) >= _MAX_RETAINED_REQUEST_IDS:
                        return AdmissionRejection("request_ledger_full")

                    parent_result = self._validate_parent_locked(intent)
                    if isinstance(parent_result, AdmissionRejection):
                        return parent_result
                    depth, parent_tools = parent_result
                    if not intent.tool_scope.issubset(parent_tools):
                        return AdmissionRejection("tool_scope_exceeds_parent")
                    if depth == 2 and not intent.tool_scope.issubset(
                        _READ_ONLY_TOOL_NAMES
                    ):
                        return AdmissionRejection("grandchild_tool_not_read_only")

                    routes = eligible_routes(
                        intent.route_snapshot,
                        intent.route_policy,
                        now=now_utc,
                    )
                    if not routes:
                        return AdmissionRejection("no_eligible_free_route")
                    routes, retry_after = self._exclude_cooled_routes_locked(
                        routes, now_utc
                    )
                    if not routes:
                        return AdmissionRejection(
                            "provider_cooldown", retry_after_seconds=retry_after
                        )

                    capacity = self._capacity_rejection_locked(intent, depth)
                    if capacity is not None:
                        if intent.queue_timeout_seconds <= 0:
                            return capacity
                        if not started_waiting:
                            if self._state.waiters >= _MAX_WAITERS:
                                return AdmissionRejection("waiting_queue_full")
                            self._state.waiters += 1
                            started_waiting = True
                        remaining = queue_deadline - self._monotonic_clock()
                        if remaining <= 0:
                            return AdmissionRejection("queue_deadline")
                        self._condition.wait(timeout=min(remaining, _MAX_QUEUE_WAIT_SECONDS))
                        continue

                    selected = self._select_route_locked(routes, intent)
                    try:
                        reservation = self._resource_book.reserve(
                            intent.resource_snapshot,
                            intent.resource_request,
                            now_monotonic=now_monotonic,
                        )
                    except (TypeError, ValueError, OverflowError):
                        return AdmissionRejection("invalid_resource_observation")
                    if not reservation.decision.admitted:
                        return AdmissionRejection("resource_pressure")
                    if intent.resource_request.has_claims and reservation.reservation_id is None:
                        return AdmissionRejection("resource_reservation_missing")

                    resource_reservation_id = reservation.reservation_id
                    grant_id: str | None = None
                    try:
                        grant_id = token_urlsafe(24)
                        created = self._monotonic_clock()
                        if not self._finite_clock(created):
                            if resource_reservation_id is not None:
                                self._resource_book.release(resource_reservation_id)
                                resource_reservation_id = None
                            return AdmissionRejection("invalid_clock")
                        grant = AdmissionGrant(
                            grant_id=grant_id,
                            request_id=intent.request_id,
                            profile_scope=intent.profile_scope,
                            account_scope=intent.account_scope,
                            provider_scope=selected.provider_scope,
                            tree_id=intent.tree_id,
                            parent_grant_id=intent.parent_grant_id,
                            depth=depth,
                            provider=selected.provider,
                            model_id=selected.model_id,
                            route_revision=intent.route_snapshot.revision,
                            cost_class=selected.cost_class,
                            tool_scope=intent.tool_scope,
                            read_only=intent.tool_scope.issubset(_READ_ONLY_TOOL_NAMES),
                            created_at_monotonic=created,
                            soft_deadline_monotonic=created + _SOFT_DEADLINE_SECONDS,
                            idle_deadline_monotonic=created + _IDLE_DEADLINE_SECONDS,
                            hard_deadline_monotonic=created + _HARD_DEADLINE_SECONDS,
                        )
                        self._grants[grant_id] = _GrantRecord(
                            grant=grant,
                            resource_reservation_id=resource_reservation_id,
                        )
                        self._seen_request_ids.add(request_key)
                    except Exception:
                        if grant_id is not None:
                            self._grants.pop(grant_id, None)
                        self._seen_request_ids.discard(request_key)
                        if resource_reservation_id is not None:
                            self._resource_book.release(resource_reservation_id)
                        raise
                    route_key = (selected.provider, selected.model_id)
                    rotation_key = (
                        intent.route_policy.provider_scope,
                        intent.route_policy.account_scope,
                        intent.profile_scope,
                    )
                    self._last_route[rotation_key] = route_key
                    self._condition.notify_all()
                    return grant
        finally:
            if started_waiting:
                with self._condition:
                    self._state.waiters = max(0, self._state.waiters - 1)
                    self._condition.notify_all()

    def record_writer_outcome(
        self,
        grant_id: str,
        outcome: WriterOutcome,
    ) -> bool:
        """Record a host writer result; uncertainty never frees capacity."""
        if not _valid_identifier(grant_id) or outcome not in (
            "started",
            "not_started",
            "unknown",
        ):
            return False
        with self._condition:
            record = self._grants.get(grant_id)
            if record is None:
                return False
            if outcome == "unknown":
                if record.state not in ("pending", "running"):
                    return False
                record.state = "unknown"
                self._blocked_trees.add(self._tree_key(record.grant))
                self._condition.notify_all()
                return True
            if record.state != "pending":
                return False
            if outcome == "started":
                if record.resource_reservation_id is not None and not self._resource_book.mark_started(
                    record.resource_reservation_id
                ):
                    record.state = "unknown"
                    self._blocked_trees.add(self._tree_key(record.grant))
                    self._condition.notify_all()
                    return False
                record.state = "running"
                self._condition.notify_all()
                return True
            if not self._release_resource_locked(record):
                record.state = "unknown"
                self._blocked_trees.add(self._tree_key(record.grant))
                self._condition.notify_all()
                return False
            del self._grants[grant_id]
            self._condition.notify_all()
            return True

    def complete(self, grant_id: str) -> bool:
        """Release a known-running grant after host-confirmed completion."""
        if not _valid_identifier(grant_id):
            return False
        with self._condition:
            record = self._grants.get(grant_id)
            if record is None or record.state != "running":
                return False
            if not self._release_resource_locked(record):
                record.state = "unknown"
                self._blocked_trees.add(self._tree_key(record.grant))
                return False
            del self._grants[grant_id]
            self._condition.notify_all()
            return True

    def resolve_unknown(
        self,
        grant_id: str,
        *,
        terminal_outcome: UnknownResolution,
    ) -> bool:
        """Release uncertainty only after trusted host terminal reconciliation."""
        if not _valid_identifier(grant_id) or terminal_outcome not in (
            "not_started",
            "completed",
        ):
            return False
        with self._condition:
            record = self._grants.get(grant_id)
            if record is None or record.state != "unknown":
                return False
            if not self._release_resource_locked(record):
                return False
            tree_key = self._tree_key(record.grant)
            del self._grants[grant_id]
            if not any(
                item.state == "unknown" and self._tree_key(item.grant) == tree_key
                for item in self._grants.values()
            ):
                self._blocked_trees.discard(tree_key)
            self._condition.notify_all()
            return True

    def report_rate_limit(
        self,
        grant_id: str,
        *,
        retry_after_seconds: float | None,
    ) -> AdmissionRejection:
        """Cool every model alias for one provider/account after a definite 429."""
        if not _valid_identifier(grant_id):
            return AdmissionRejection("grant_not_pending")
        with self._condition:
            record = self._grants.get(grant_id)
            if record is None or record.state not in ("pending", "running"):
                return AdmissionRejection("grant_not_pending")
            try:
                seconds = (
                    float(retry_after_seconds)
                    if retry_after_seconds is not None
                    and not isinstance(retry_after_seconds, bool)
                    else math.nan
                )
            except (TypeError, ValueError, OverflowError):
                seconds = math.nan
            delay = (
                min(max(1.0, seconds), _MAX_RETRY_AFTER_SECONDS)
                if math.isfinite(seconds) and seconds >= 0
                else _RETRY_AFTER_FALLBACK_SECONDS
            )
            now = self._utc_clock()
            if (
                not isinstance(now, datetime)
                or now.tzinfo is None
                or now.utcoffset() is None
            ):
                return AdmissionRejection("invalid_clock")
            route = record.grant
            cooldown_key = (route.provider_scope, route.account_scope, route.provider)
            self._cooldowns[cooldown_key] = now.astimezone(timezone.utc) + timedelta(
                seconds=delay
            )
            if not self._release_resource_locked(record):
                record.state = "unknown"
                self._blocked_trees.add(self._tree_key(record.grant))
                return AdmissionRejection("writer_outcome_unknown")
            del self._grants[grant_id]
            self._condition.notify_all()
            return AdmissionRejection("rate_limited", retry_after_seconds=delay)

    def _validate_parent_locked(
        self,
        intent: AdmissionIntent,
    ) -> tuple[int, frozenset[str]] | AdmissionRejection:
        if intent.parent_grant_id is None:
            return 1, intent.parent_tool_scope
        parent = self._grants.get(intent.parent_grant_id)
        if parent is None:
            return AdmissionRejection("parent_grant_unknown")
        if parent.state != "running":
            return AdmissionRejection("parent_not_running")
        grant = parent.grant
        if grant.depth != 1:
            return AdmissionRejection("maximum_depth")
        if (
            intent.profile_scope != grant.profile_scope
            or intent.account_scope != grant.account_scope
            or intent.tree_id != grant.tree_id
            or intent.route_policy.provider_scope != grant.provider_scope
        ):
            return AdmissionRejection("parent_scope_mismatch")
        return 2, grant.tool_scope

    def _capacity_rejection_locked(
        self,
        intent: AdmissionIntent,
        depth: int,
    ) -> AdmissionRejection | None:
        grants = tuple(record.grant for record in self._grants.values())
        if len(grants) >= _MAX_ACTIVE_TOTAL:
            return AdmissionRejection("execution_capacity")
        tree_grants = tuple(
            grant
            for grant in grants
            if self._tree_key(grant)
            == (intent.profile_scope, intent.account_scope, intent.tree_id)
        )
        if depth == 1:
            if sum(grant.depth == 1 for grant in grants) >= _MAX_ACTIVE_TOP_LEVEL:
                return AdmissionRejection("top_level_capacity")
            if sum(grant.depth == 1 for grant in tree_grants) >= _MAX_ACTIVE_TOP_LEVEL:
                return AdmissionRejection("tree_capacity")
        else:
            if sum(grant.depth == 2 for grant in grants) >= _MAX_ACTIVE_NESTED:
                return AdmissionRejection("nested_capacity")
            if sum(grant.depth == 2 for grant in tree_grants) >= _MAX_ACTIVE_NESTED:
                return AdmissionRejection("tree_capacity")
            if any(
                grant.depth == 2 and grant.parent_grant_id == intent.parent_grant_id
                for grant in grants
            ):
                return AdmissionRejection("parent_nested_capacity")
        return None

    def _exclude_cooled_routes_locked(
        self,
        routes: tuple[FreeRoute, ...],
        now: datetime,
    ) -> tuple[tuple[FreeRoute, ...], float | None]:
        eligible: list[FreeRoute] = []
        cooldowns: list[datetime] = []
        for route in routes:
            until = self._cooldowns.get(
                (route.provider_scope, route.account_scope, route.provider)
            )
            if until is not None and until > now:
                cooldowns.append(until)
            else:
                eligible.append(route)
        if eligible:
            return tuple(eligible), None
        if not cooldowns:
            return (), None
        return (), max(0.0, (min(cooldowns) - now).total_seconds())

    def _select_route_locked(
        self,
        routes: tuple[FreeRoute, ...],
        intent: AdmissionIntent,
    ) -> FreeRoute:
        ordered = tuple(sorted(routes, key=lambda route: (route.provider, route.model_id)))
        rotation_key = (
            intent.route_policy.provider_scope,
            intent.route_policy.account_scope,
            intent.profile_scope,
        )
        previous = self._last_route.get(rotation_key)
        if previous is None:
            return ordered[0]
        return next(
            (
                route
                for route in ordered
                if (route.provider, route.model_id) > previous
            ),
            ordered[0],
        )

    def _release_resource_locked(self, record: _GrantRecord) -> bool:
        return (
            record.resource_reservation_id is None
            or self._resource_book.release(record.resource_reservation_id)
        )

    @staticmethod
    def _tree_key(grant: AdmissionGrant) -> tuple[str, str, str]:
        return grant.profile_scope, grant.account_scope, grant.tree_id

    @staticmethod
    def _finite_clock(value: object) -> bool:
        return _finite_number(value) and value >= 0


__all__ = [
    "AdmissionGrant",
    "AdmissionIntent",
    "AdmissionRejection",
    "DelegationAdmission",
]
