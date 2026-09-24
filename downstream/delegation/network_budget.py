"""Host-owned deadlines and concurrency accounting for delegated requests.

Callers must pass the opaque account scope captured by trusted host admission.
This module never derives scope from provider names, URLs, or credentials.
"""

from __future__ import annotations

import contextvars
import hashlib
import math
import secrets
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Literal, Mapping


Operation = Literal["inference", "catalogue", "embedding", "control"]
_OPERATIONS = frozenset({"inference", "catalogue", "embedding", "control"})
_MAINTENANCE = frozenset({"catalogue", "embedding"})
_OUTCOMES = frozenset({"success", "error", "cancelled", "timeout", "unknown"})
_CANCEL_REASONS = frozenset({"user_cancel", "interrupt", "deadline", "shutdown"})
_MAX_SCOPE_LENGTH = 256
_MAX_ACTIVE_REQUESTS = 64
_MAX_COOLDOWN_ENTRIES = 1024
_MAX_RETRY_AFTER_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class RequestTimeouts:
    """Transport bounds; activity never extends the total deadline."""

    connect_seconds: float
    read_idle_seconds: float
    total_seconds: float

    def __post_init__(self) -> None:
        for name in ("connect_seconds", "read_idle_seconds", "total_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        if self.connect_seconds > self.total_seconds:
            raise ValueError("connect deadline cannot exceed total deadline")
        if self.read_idle_seconds > self.total_seconds:
            raise ValueError("read-idle deadline cannot exceed total deadline")


_DEFAULT_TIMEOUTS: Mapping[str, RequestTimeouts] = {
    "inference": RequestTimeouts(10.0, 180.0, 900.0),
    "catalogue": RequestTimeouts(5.0, 15.0, 30.0),
    "embedding": RequestTimeouts(5.0, 30.0, 60.0),
    "control": RequestTimeouts(5.0, 15.0, 30.0),
}


class RequestBudgetError(RuntimeError):
    """A request could not be admitted under the host's bounded policy."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class RequestDeadlineExceeded(TimeoutError):
    """A lease exceeded its read-idle or total deadline."""

    def __init__(self, *, code: str) -> None:
        super().__init__("Delegated network request deadline exceeded.")
        self.code = code


class RequestCancelled(InterruptedError):
    """A host-owned cancellation was delivered to a request lease."""


class RequestBudget:
    """Shared host request accounting, keyed only by trusted account scope.

    Admission is non-blocking. Status and cancellation acquire only a short
    in-memory lock, so a stalled provider cannot hold up local control
    operations. Status and cancellation do not consume network-control slots.
    One global slot is kept available for control traffic; maintenance also
    leaves one non-control slot available for inference. Use one instance
    across provider aliases that share an account scope within one process.
    Separate OS processes do not share these limits.
    Active leases are capped, and each lease owns a deadline timer canceled
    when that lease is released.
    """

    def __init__(
        self,
        *,
        max_in_flight: int = 64,
        per_account_limit: int = 4,
        reserved_interactive_slots: int = 1,
        reserved_control_slots: int = 1,
        timeouts: Mapping[str, RequestTimeouts] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        random_token: Callable[[], str] | None = None,
    ) -> None:
        for name, value in (
            ("max_in_flight", max_in_flight),
            ("per_account_limit", per_account_limit),
            ("reserved_interactive_slots", reserved_interactive_slots),
            ("reserved_control_slots", reserved_control_slots),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if max_in_flight < 1 or per_account_limit < 1:
            raise ValueError("request limits must be positive")
        if reserved_control_slots >= min(max_in_flight, _MAX_ACTIVE_REQUESTS):
            raise ValueError("control reservation must be below global request capacity")
        if reserved_interactive_slots >= per_account_limit:
            raise ValueError("reserved interactive slots must be below account limit")
        if not callable(monotonic_clock):
            raise TypeError("monotonic_clock must be callable")
        if random_token is not None and not callable(random_token):
            raise TypeError("random_token must be callable")

        selected_timeouts = dict(_DEFAULT_TIMEOUTS)
        if timeouts is not None:
            if not isinstance(timeouts, Mapping):
                raise TypeError("timeouts must be a mapping")
            for operation, value in timeouts.items():
                if operation not in _OPERATIONS or not isinstance(value, RequestTimeouts):
                    raise ValueError("timeout policy is invalid")
                if operation == "catalogue" and value.total_seconds > 30:
                    raise ValueError("catalogue total deadline cannot exceed 30 seconds")
                selected_timeouts[operation] = value

        self._max_in_flight = max_in_flight
        self._per_account_limit = per_account_limit
        self._reserved_interactive_slots = reserved_interactive_slots
        self._reserved_control_slots = reserved_control_slots
        self._timeouts = selected_timeouts
        self._clock = monotonic_clock
        self._token = random_token or (lambda: secrets.token_urlsafe(18))
        self._lock = threading.RLock()
        self._leases: dict[str, RequestLease] = {}
        self._account_counts: dict[str, int] = {}
        self._unknown_accounts: dict[str, int] = {}
        self._cooldowns: OrderedDict[str, float] = OrderedDict()
        self._overflow_cooldown_until = 0.0

    def reserve(self, account_scope: str, operation: Operation = "inference") -> RequestLease:
        """Reserve capacity for one provider request using an explicit scope."""
        account_key = _account_key(account_scope)
        if operation not in _OPERATIONS:
            raise ValueError("operation is unsupported")
        request_id = self._token()
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise RuntimeError("request id provider returned an invalid value")
        now = self._clock()
        with self._lock:
            if request_id in self._leases:
                raise RequestBudgetError(
                    "Request id collision; request was not admitted.",
                    code="request_id_collision",
                )
            if self._unknown_accounts.get(account_key, 0):
                raise RequestBudgetError(
                    "An earlier account request is still running.",
                    code="request_outcome_unknown",
                )
            global_capacity = min(self._max_in_flight, _MAX_ACTIVE_REQUESTS)
            active_count = len(self._leases)
            if active_count >= global_capacity:
                raise RequestBudgetError("Request capacity is full.", code="capacity_full")
            active_non_control = sum(
                lease.operation != "control" for lease in self._leases.values()
            )
            non_control_capacity = global_capacity - self._reserved_control_slots
            if operation != "control" and active_non_control >= non_control_capacity:
                raise RequestBudgetError(
                    "Request capacity is reserved for control traffic.",
                    code="capacity_reserved",
                )
            maintenance_capacity = (
                non_control_capacity - self._reserved_interactive_slots
            )
            if (
                operation in _MAINTENANCE
                and active_non_control >= maintenance_capacity
            ):
                raise RequestBudgetError(
                    "Request capacity is reserved for inference traffic.",
                    code="maintenance_capacity_reserved",
                )
            if self._overflow_cooldown_until > now:
                raise RequestBudgetError(
                    "Request cooldown capacity is saturated.",
                    code="cooldown_capacity_full",
                )
            if self._overflow_cooldown_until:
                self._overflow_cooldown_until = 0.0
            active = self._account_counts.get(account_key, 0)
            account_limit = self._per_account_limit
            if operation in _MAINTENANCE:
                account_limit -= self._reserved_interactive_slots
            if active >= account_limit:
                raise RequestBudgetError("Account request capacity is full.", code="account_capacity_full")
            retry_at = self._cooldowns.get(account_key, 0.0)
            if retry_at > now:
                raise RequestBudgetError("Account request is in cooldown.", code="account_cooldown")
            if retry_at:
                self._cooldowns.pop(account_key, None)

            lease = RequestLease(
                budget=self,
                request_id=request_id,
                account_key=account_key,
                operation=operation,
                timeouts=self._timeouts[operation],
                created_at=now,
            )
            self._leases[request_id] = lease
            self._account_counts[account_key] = active + 1
        lease._start_deadline_timer()
        return lease

    def status(self) -> dict[str, Any]:
        """Return bounded, redacted status for active requests."""
        now = self._clock()
        with self._lock:
            requests = [lease._status_unlocked(now) for lease in self._leases.values()]
            return {"active": len(requests), "requests": requests[:_MAX_ACTIVE_REQUESTS]}

    def cancel(self, request_id: str, *, reason: str = "user_cancel") -> bool:
        """Cancel one active lease; callbacks run after releasing the budget lock."""
        safe_reason = reason if reason in _CANCEL_REASONS else "user_cancel"
        with self._lock:
            lease = self._leases.get(request_id)
            if lease is None:
                return False
            callback = lease._cancel_unlocked(safe_reason)
        if callback is not None:
            try:
                callback(safe_reason)
            except Exception:
                # Cancellation remains recorded even when a transport cannot abort.
                pass
        return True

    def _release_unlocked(self, lease: RequestLease) -> tuple[Callable[[], Any], ...]:
        if self._leases.get(lease.request_id) is not lease:
            return ()
        self._leases.pop(lease.request_id, None)
        active = self._account_counts.get(lease._account_key, 0) - 1
        if active > 0:
            self._account_counts[lease._account_key] = active
        else:
            self._account_counts.pop(lease._account_key, None)
        lease._released = True
        deadline_timer, lease._deadline_timer = lease._deadline_timer, None
        if deadline_timer is not None:
            deadline_timer.cancel()
        callbacks, lease._release_callbacks = lease._release_callbacks, []
        return tuple(callbacks)

    @staticmethod
    def _run_release_callbacks(callbacks: tuple[Callable[[], Any], ...]) -> None:
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def _unknown_started_unlocked(self, account_key: str) -> None:
        self._unknown_accounts[account_key] = self._unknown_accounts.get(account_key, 0) + 1

    def _unknown_finished_unlocked(self, account_key: str) -> None:
        remaining = self._unknown_accounts.get(account_key, 0) - 1
        if remaining > 0:
            self._unknown_accounts[account_key] = remaining
        else:
            self._unknown_accounts.pop(account_key, None)

    def _record_retry_after(self, account_key: str, seconds: float) -> float:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(float(seconds))
            or seconds < 0
        ):
            raise ValueError("retry-after must be finite and non-negative")
        bounded = min(float(seconds), _MAX_RETRY_AFTER_SECONDS)
        now = self._clock()
        retry_at = now + bounded
        with self._lock:
            for expired_key, expired_at in tuple(self._cooldowns.items()):
                if expired_at <= now:
                    self._cooldowns.pop(expired_key, None)
            existing = self._cooldowns.get(account_key, 0.0)
            if existing:
                self._cooldowns[account_key] = max(existing, retry_at)
                self._cooldowns.move_to_end(account_key)
            elif len(self._cooldowns) < _MAX_COOLDOWN_ENTRIES:
                self._cooldowns[account_key] = retry_at
            else:
                # Do not evict a live Retry-After and accidentally relaunch
                # that account. A bounded global cooldown fails closed until
                # the longest known/new cooldown has elapsed.
                self._overflow_cooldown_until = max(
                    self._overflow_cooldown_until,
                    retry_at,
                    max(self._cooldowns.values(), default=0.0),
                )
        return bounded


class RequestLease:
    """One bounded request reservation with separate worker/caller lifetimes."""

    def __init__(
        self,
        *,
        budget: RequestBudget,
        request_id: str,
        account_key: str,
        operation: Operation,
        timeouts: RequestTimeouts,
        created_at: float,
    ) -> None:
        self.request_id = request_id
        self.operation = operation
        self.account_scope_hash = account_key
        self.connect_timeout_seconds = timeouts.connect_seconds
        self.read_idle_timeout_seconds = timeouts.read_idle_seconds
        self.total_timeout_seconds = timeouts.total_seconds
        self.cancel_generation = 0
        self._budget = budget
        self._account_key = account_key
        self._timeouts = timeouts
        self._created_at = created_at
        self._deadline = created_at + timeouts.total_seconds
        self._last_progress_at = created_at
        self._last_heartbeat_at = created_at
        self._progress_count = 0
        self._heartbeat_count = 0
        self._active_workers = 0
        self._caller_finished = False
        self._released = False
        self._outcome = "active"
        self._unknown_counted = False
        self._cancelled = threading.Event()
        self._cancel_reason = None
        self._abort_callback: Callable[[str], Any] | None = None
        self._release_callbacks: list[Callable[[], Any]] = []
        self._deadline_timer: threading.Timer | None = None

    def _start_deadline_timer(self) -> None:
        """Schedule an abort owned and canceled by this bounded lease."""
        timer = threading.Timer(self.remaining_seconds, self._expire_deadline)
        timer.daemon = True
        timer.name = f"delegated-request-deadline-{self.request_id[:8]}"
        with self._budget._lock:
            if self._released or self._cancelled.is_set():
                return
            self._deadline_timer = timer
        try:
            timer.start()
        except Exception:
            with self._budget._lock:
                if self._deadline_timer is timer:
                    self._deadline_timer = None
            self.finish(outcome="error")
            raise RequestBudgetError(
                "Request deadline monitor could not start.",
                code="deadline_monitor_unavailable",
            ) from None

    def _expire_deadline(self) -> None:
        self._budget.cancel(self.request_id, reason="deadline")

    def __enter__(self) -> RequestLease:
        self.check_active()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        outcome = "success" if exc_type is None else "error"
        if exc_type is not None and issubclass(exc_type, (TimeoutError, RequestDeadlineExceeded)):
            outcome = "timeout"
        elif exc_type is not None and issubclass(exc_type, (InterruptedError, RequestCancelled)):
            outcome = "cancelled"
        if outcome in {"timeout", "cancelled"} and self.active_workers:
            outcome = "unknown"
        self.finish(outcome=outcome)

    @property
    def deadline_monotonic(self) -> float:
        return self._deadline

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - self._budget._clock())

    @property
    def active_workers(self) -> int:
        with self._budget._lock:
            return self._active_workers

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def cancel_reason(self) -> str | None:
        with self._budget._lock:
            return self._cancel_reason

    def mark_progress(self) -> None:
        """Record actual response progress; this resets read-idle only."""
        now = self._budget._clock()
        with self._budget._lock:
            self._last_progress_at = now
            self._progress_count += 1

    def heartbeat(self) -> None:
        """Record caller liveness without extending read-idle or total bounds."""
        with self._budget._lock:
            self._last_heartbeat_at = self._budget._clock()
            self._heartbeat_count += 1

    def check_active(self, cancel_generation: int | None = None) -> None:
        if self._cancelled.is_set():
            if self.cancel_reason == "deadline":
                raise RequestDeadlineExceeded(code="total_deadline")
            raise RequestCancelled("Delegated network request was cancelled.")
        if cancel_generation is not None and cancel_generation != self.cancel_generation:
            raise RequestCancelled("Delegated network request generation changed.")
        now = self._budget._clock()
        if now >= self._deadline:
            self._budget.cancel(self.request_id, reason="deadline")
            raise RequestDeadlineExceeded(code="total_deadline")
        if now - self._last_progress_at >= self.read_idle_timeout_seconds:
            self._budget.cancel(self.request_id, reason="deadline")
            raise RequestDeadlineExceeded(code="read_idle_deadline")

    def set_abort_callback(self, callback: Callable[[str], Any] | None) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("abort callback must be callable or None")
        if callback is None:
            with self._budget._lock:
                self._abort_callback = None
            return
        run_reason: str | None = None
        expire_now = False
        with self._budget._lock:
            self._abort_callback = callback
            if not self._released:
                if self._cancelled.is_set():
                    run_reason = self._cancel_reason or "user_cancel"
                elif self._budget._clock() >= self._deadline:
                    expire_now = True
        if expire_now:
            self._budget.cancel(self.request_id, reason="deadline")
        elif run_reason is not None:
            try:
                callback(run_reason)
            except Exception:
                pass

    def add_release_callback(self, callback: Callable[[], Any]) -> None:
        """Run non-blocking cleanup after the last caller/worker exits.

        If the lease has already been released, the callback runs synchronously
        on this caller after the lock is dropped; callbacks must therefore be
        small, non-blocking cleanup operations.
        """
        if not callable(callback):
            raise TypeError("release callback must be callable")
        run_now = False
        with self._budget._lock:
            if self._released:
                run_now = True
            else:
                self._release_callbacks.append(callback)
        if run_now:
            callback()

    def worker_started(self) -> None:
        with self._budget._lock:
            if self._caller_finished or self._budget._leases.get(self.request_id) is not self:
                raise RequestBudgetError("Request lease is no longer active.", code="lease_closed")
            self._active_workers += 1

    def worker_finished(self) -> None:
        callbacks: tuple[Callable[[], Any], ...] = ()
        with self._budget._lock:
            if self._active_workers <= 0:
                return
            self._active_workers -= 1
            if self._active_workers == 0 and self._unknown_counted:
                self._budget._unknown_finished_unlocked(self._account_key)
                self._unknown_counted = False
            if self._caller_finished and self._active_workers == 0:
                callbacks = self._budget._release_unlocked(self)
        self._budget._run_release_callbacks(callbacks)

    def finish(self, *, outcome: str = "success") -> None:
        """Finish the caller; retain capacity until outstanding workers exit."""
        safe_outcome = outcome if outcome in _OUTCOMES else "error"
        callbacks: tuple[Callable[[], Any], ...] = ()
        with self._budget._lock:
            if self._caller_finished:
                return
            self._caller_finished = True
            self._outcome = safe_outcome
            if safe_outcome == "unknown" and self._active_workers:
                self._budget._unknown_started_unlocked(self._account_key)
                self._unknown_counted = True
            if self._active_workers == 0:
                callbacks = self._budget._release_unlocked(self)
        self._budget._run_release_callbacks(callbacks)

    def record_retry_after(self, seconds: float) -> float:
        """Record a bounded account-wide cooldown from a trusted HTTP result."""
        return self._budget._record_retry_after(self._account_key, seconds)

    def can_retry(self) -> bool:
        """Return false while a same-account transport outcome is unresolved."""
        with self._budget._lock:
            return (
                self._budget._unknown_accounts.get(self._account_key, 0) == 0
                and self.remaining_seconds > 0
                and not self._cancelled.is_set()
            )

    def _cancel_unlocked(self, reason: str) -> Callable[[str], Any] | None:
        if self._released or (self._caller_finished and not self._active_workers):
            return None
        self._cancel_reason = reason
        if not self._cancelled.is_set():
            self.cancel_generation += 1
            self._cancelled.set()
        return self._abort_callback

    def note_cancelled(self, reason: str) -> None:
        """Record an external abort without invoking the transport callback again."""
        safe_reason = reason if reason in _CANCEL_REASONS else "interrupt"
        with self._budget._lock:
            if not self._cancelled.is_set():
                self.cancel_generation += 1
                self._cancelled.set()
            self._cancel_reason = safe_reason

    def _status_unlocked(self, now: float) -> dict[str, Any]:
        if self._caller_finished and self._active_workers:
            state = "outcome_unknown" if self._unknown_counted else "worker_finishing"
        elif self._cancelled.is_set():
            state = "cancelled"
        else:
            state = "active"
        return {
            "request_id": self.request_id,
            "operation": self.operation,
            "state": state,
            "elapsed_seconds": max(0.0, now - self._created_at),
            "remaining_seconds": max(0.0, self._deadline - now),
            "read_idle_seconds": max(0.0, now - self._last_progress_at),
            "progress_count": self._progress_count,
            "heartbeat_count": self._heartbeat_count,
            "active_workers": self._active_workers,
            "cancel_generation": self.cancel_generation,
            "outcome": self._outcome,
        }


def _account_key(account_scope: str) -> str:
    if (
        not isinstance(account_scope, str)
        or not account_scope.strip()
        or len(account_scope) > _MAX_SCOPE_LENGTH
    ):
        raise ValueError("account_scope must be a non-empty bounded host scope")
    return hashlib.sha256(account_scope.encode("utf-8")).hexdigest()


_CURRENT_REQUEST_LEASE: contextvars.ContextVar[RequestLease | None] = contextvars.ContextVar(
    "hermes_delegated_request_lease", default=None
)


@contextmanager
def bind_request_lease(lease: RequestLease | None) -> Iterator[None]:
    """Expose an optional lease to existing request transport seams."""
    token = _CURRENT_REQUEST_LEASE.set(lease)
    try:
        yield
    finally:
        _CURRENT_REQUEST_LEASE.reset(token)


def current_request_lease() -> RequestLease | None:
    """Return the request lease bound to this context, if any."""
    return _CURRENT_REQUEST_LEASE.get()


DEFAULT_NETWORK_REQUEST_BUDGET = RequestBudget()
