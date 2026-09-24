"""Read-only resource observations and admission for delegated work.

This module stays outside the default agent tool surface. It distinguishes
observed host capacity from a caller's explicit resource estimate and keeps
admission pure; the reservation book only accounts for host-owned claims.
"""

from __future__ import annotations

import ctypes
import importlib
import math
import sys
import threading
import time
from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Any, Callable, Literal

from downstream.platform.windows.gpu import (
    NvidiaGpuProbeResult,
    query_nvidia_gpu_telemetry,
)


Route = Literal["local", "remote"]
Workload = Literal["read", "inference", "embedding"]

_SAFE_ERROR_CODES = frozenset(
    {
        "ram_probe_failed",
        "ram_telemetry_unavailable",
        "commit_probe_failed",
        "commit_telemetry_unsupported",
        "commit_telemetry_unavailable",
        "cpu_probe_failed",
        "cpu_telemetry_unavailable",
        "cpu_first_sample",
        "cpu_sample_window_too_wide",
        "cpu_sample_clock_invalid",
        "gpu_probe_failed",
        "gpu_probe_unavailable",
        "gpu_probe_timeout",
        "gpu_probe_output_invalid",
        "gpu_probe_data_unavailable",
        "gpu_local_residency_unavailable",
        "gpu_local_process_ids_invalid",
        "local_residency_source_unavailable",
        "telemetry_error",
    }
)


def _nonnegative_int(value: Any, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer or None")


def _finite_nonnegative(value: Any, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise ValueError(f"{field_name} must be finite and non-negative")


def _safe_error_code(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in _SAFE_ERROR_CODES else "telemetry_error"


def _valid_gpu_uuid(value: str) -> bool:
    return bool(value) and len(value) <= 96 and all(
        char.isascii() and (char.isalnum() or char in "_-") for char in value
    )


@dataclass(frozen=True, slots=True)
class GpuResourceSnapshot:
    """Observed GPU capacity and known local residency, without process IDs."""

    uuid: str
    free_vram_bytes: int | None
    local_resident_bytes: int | None
    observed_at_monotonic: float
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.uuid, str) or not _valid_gpu_uuid(self.uuid):
            raise ValueError("GPU UUID must be a non-empty bounded string")
        _nonnegative_int(self.free_vram_bytes, "free_vram_bytes")
        _nonnegative_int(self.local_resident_bytes, "local_resident_bytes")
        _finite_nonnegative(self.observed_at_monotonic, "observed_at_monotonic")
        object.__setattr__(self, "error", _safe_error_code(self.error))

    def telemetry_age_seconds(self, now_monotonic: float) -> float | None:
        """Return the observed age, or None when clocks cannot be compared."""
        _finite_nonnegative(now_monotonic, "now_monotonic")
        age = now_monotonic - self.observed_at_monotonic
        return age if age >= 0 else None


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """Bounded host readings; ``None`` means unavailable, never zero."""

    observed_at_monotonic: float
    ram_total_bytes: int | None
    ram_available_bytes: int | None
    commit_limit_bytes: int | None
    commit_available_bytes: int | None
    cpu_busy_percent: float | None
    gpus: tuple[GpuResourceSnapshot, ...] | None
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _finite_nonnegative(self.observed_at_monotonic, "observed_at_monotonic")
        for name in (
            "ram_total_bytes",
            "ram_available_bytes",
            "commit_limit_bytes",
            "commit_available_bytes",
        ):
            _nonnegative_int(getattr(self, name), name)
        if self.cpu_busy_percent is not None:
            _finite_nonnegative(self.cpu_busy_percent, "cpu_busy_percent")
            if self.cpu_busy_percent > 100:
                raise ValueError("cpu_busy_percent must not exceed 100")
        if self.gpus is not None:
            if len(self.gpus) > 16:
                raise ValueError("at most 16 GPU observations are supported")
            uuids = [gpu.uuid for gpu in self.gpus]
            if len(set(uuids)) != len(uuids):
                raise ValueError("GPU UUIDs must be unique in one snapshot")
        sanitized = tuple(
            sorted(
                {
                    safe
                    for item in self.errors[:32]
                    if isinstance(item, str)
                    if (safe := _safe_error_code(item)) is not None
                }
            )
        )
        object.__setattr__(self, "errors", sanitized)


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    """Explicit resource estimate for one host-owned operation."""

    route: Route
    workload: Workload
    ram_bytes: int = 0
    commit_bytes: int = 0
    cpu_percent: float = 0.0
    gpu_uuid: str | None = None
    vram_bytes: int = 0

    def __post_init__(self) -> None:
        if self.route not in ("local", "remote"):
            raise ValueError("route must be local or remote")
        if self.workload not in ("read", "inference", "embedding"):
            raise ValueError("unsupported resource workload")
        _nonnegative_int(self.ram_bytes, "ram_bytes")
        _nonnegative_int(self.commit_bytes, "commit_bytes")
        _finite_nonnegative(self.cpu_percent, "cpu_percent")
        _nonnegative_int(self.vram_bytes, "vram_bytes")
        if self.cpu_percent > 100:
            raise ValueError("cpu_percent must not exceed 100")
        if self.gpu_uuid is not None and (
            not isinstance(self.gpu_uuid, str) or not _valid_gpu_uuid(self.gpu_uuid)
        ):
            raise ValueError("gpu_uuid must be a non-empty bounded string")
        if self.vram_bytes and self.gpu_uuid is None:
            raise ValueError("a VRAM estimate requires a GPU UUID")
        if self.route == "remote" and (self.gpu_uuid is not None or self.vram_bytes):
            raise ValueError("remote work cannot claim local GPU resources")
        if self.workload == "read" and self.has_claims:
            raise ValueError("read-only requests cannot claim compute resources")
        if self.route == "local" and self.workload in ("inference", "embedding"):
            if self.ram_bytes == 0 or self.commit_bytes == 0 or self.cpu_percent == 0:
                raise ValueError(
                    "local compute requires explicit RAM, commit, and CPU estimates"
                )

    @property
    def has_claims(self) -> bool:
        return bool(
            self.ram_bytes
            or self.commit_bytes
            or self.cpu_percent
            or self.vram_bytes
        )

    def claims(self) -> ResourceClaims:
        gpu_claims = (
            ((self.gpu_uuid, self.vram_bytes),)
            if self.gpu_uuid is not None and self.vram_bytes
            else ()
        )
        return ResourceClaims(
            ram_bytes=self.ram_bytes,
            commit_bytes=self.commit_bytes,
            cpu_percent=float(self.cpu_percent),
            gpu_vram_bytes=gpu_claims,
        )


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """Proposed conservative guardrails; calibrate before production use."""

    max_snapshot_age_seconds: float = 5.0
    max_gpu_age_seconds: float = 5.0
    min_ram_available_bytes: int = 2 * 1024**3
    min_commit_available_bytes: int = 2 * 1024**3
    min_gpu_free_vram_bytes: int = 512 * 1024**2
    max_cpu_busy_percent: float = 90.0
    resume_cpu_busy_percent: float = 75.0
    ram_hysteresis_bytes: int = 512 * 1024**2
    commit_hysteresis_bytes: int = 512 * 1024**2
    gpu_hysteresis_bytes: int = 256 * 1024**2
    max_active_reservations: int = 256

    def __post_init__(self) -> None:
        for name in (
            "max_snapshot_age_seconds",
            "max_gpu_age_seconds",
            "max_cpu_busy_percent",
            "resume_cpu_busy_percent",
        ):
            _finite_nonnegative(getattr(self, name), name)
        for name in (
            "min_ram_available_bytes",
            "min_commit_available_bytes",
            "min_gpu_free_vram_bytes",
            "ram_hysteresis_bytes",
            "commit_hysteresis_bytes",
            "gpu_hysteresis_bytes",
            "max_active_reservations",
        ):
            _nonnegative_int(getattr(self, name), name)
        if self.max_active_reservations == 0:
            raise ValueError("max_active_reservations must be positive")
        if self.max_snapshot_age_seconds == 0 or self.max_gpu_age_seconds == 0:
            raise ValueError("telemetry age limits must be positive")
        if self.max_cpu_busy_percent > 100 or self.resume_cpu_busy_percent > 100:
            raise ValueError("CPU thresholds must not exceed 100 percent")
        if self.resume_cpu_busy_percent >= self.max_cpu_busy_percent:
            raise ValueError("CPU resume threshold must be below pressure threshold")


@dataclass(frozen=True, slots=True)
class ResourceClaims:
    """Currently reserved host resources, aggregated without owner identity."""

    ram_bytes: int = 0
    commit_bytes: int = 0
    cpu_percent: float = 0.0
    gpu_vram_bytes: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        _nonnegative_int(self.ram_bytes, "ram_bytes")
        _nonnegative_int(self.commit_bytes, "commit_bytes")
        _finite_nonnegative(self.cpu_percent, "cpu_percent")
        _validate_gpu_claims(self.gpu_vram_bytes)

    @property
    def vram_bytes(self) -> int:
        return sum(amount for _uuid, amount in self.gpu_vram_bytes)

    def vram_for(self, gpu_uuid: str) -> int:
        return next(
            (amount for uuid, amount in self.gpu_vram_bytes if uuid == gpu_uuid),
            0,
        )


def _validate_gpu_claims(claims: tuple[tuple[str, int], ...]) -> None:
    if len(claims) > 16:
        raise ValueError("at most 16 GPU reservations are supported")
    seen: set[str] = set()
    for uuid, amount in claims:
        if not isinstance(uuid, str) or not _valid_gpu_uuid(uuid) or uuid in seen:
            raise ValueError("GPU reservation ids must be unique bounded strings")
        _nonnegative_int(amount, "GPU reservation bytes")
        seen.add(uuid)


@dataclass(frozen=True, slots=True)
class ResourceReflection:
    """Fresh per-reservation usage already represented in host counters.

    None means the producer could not establish that dimension. A complete
    GPU tuple includes a zero entry by omission for any claimed GPU not listed.
    The observation must come from the host lifecycle owner and correspond to
    this reservation, rather than from a caller supplied estimate.
    """

    ram_bytes: int | None
    commit_bytes: int | None
    cpu_percent: float | None
    gpu_vram_bytes: tuple[tuple[str, int], ...] | None
    observed_at_monotonic: float
    gpu_observed_at_monotonic: float | None = None

    def __post_init__(self) -> None:
        _nonnegative_int(self.ram_bytes, "reflected RAM bytes")
        _nonnegative_int(self.commit_bytes, "reflected commit bytes")
        if self.cpu_percent is not None:
            _finite_nonnegative(self.cpu_percent, "reflected CPU percent")
            if self.cpu_percent > 100:
                raise ValueError("reflected CPU percent must not exceed 100")
        if self.gpu_vram_bytes is not None:
            _validate_gpu_claims(self.gpu_vram_bytes)
        if self.gpu_observed_at_monotonic is not None:
            _finite_nonnegative(
                self.gpu_observed_at_monotonic, "GPU reflection timestamp"
            )
        _finite_nonnegative(self.observed_at_monotonic, "reflection timestamp")


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    admitted: bool
    reasons: tuple[str, ...]
    active_pressure_reasons: frozenset[str]


def _gpu_pressure_key(uuid: str) -> str:
    # Keep device identities out of decision and pressure reason strings.
    import hashlib

    return f"gpu_pressure:{hashlib.sha256(uuid.encode('utf-8')).hexdigest()[:16]}"


def _advance_pressure(
    snapshot: ResourceSnapshot,
    policy: ResourcePolicy,
    *,
    reserved: ResourceClaims,
    now_monotonic: float,
    active_pressure_reasons: frozenset[str],
) -> frozenset[str]:
    age = now_monotonic - snapshot.observed_at_monotonic
    if age < 0 or age > policy.max_snapshot_age_seconds:
        return active_pressure_reasons
    next_reasons: set[str] = set()

    def below_threshold(
        key: str,
        available: int | None,
        reserved_bytes: int,
        enter_bytes: int,
        hysteresis_bytes: int,
    ) -> None:
        if available is None:
            if key in active_pressure_reasons:
                next_reasons.add(key)
            return
        headroom = available - reserved_bytes
        threshold = enter_bytes + (
            hysteresis_bytes if key in active_pressure_reasons else 0
        )
        if headroom < threshold:
            next_reasons.add(key)

    below_threshold(
        "ram_pressure",
        snapshot.ram_available_bytes,
        reserved.ram_bytes,
        policy.min_ram_available_bytes,
        policy.ram_hysteresis_bytes,
    )
    below_threshold(
        "commit_pressure",
        snapshot.commit_available_bytes,
        reserved.commit_bytes,
        policy.min_commit_available_bytes,
        policy.commit_hysteresis_bytes,
    )

    if snapshot.cpu_busy_percent is None:
        if "cpu_pressure" in active_pressure_reasons:
            next_reasons.add("cpu_pressure")
    else:
        cpu_busy = snapshot.cpu_busy_percent + reserved.cpu_percent
        threshold = (
            policy.resume_cpu_busy_percent
            if "cpu_pressure" in active_pressure_reasons
            else policy.max_cpu_busy_percent
        )
        if cpu_busy > threshold:
            next_reasons.add("cpu_pressure")

    observed_gpu_keys: set[str] = set()
    if snapshot.gpus is not None:
        for gpu in snapshot.gpus:
            key = _gpu_pressure_key(gpu.uuid)
            observed_gpu_keys.add(key)
            gpu_age = gpu.telemetry_age_seconds(now_monotonic)
            if gpu_age is None or gpu_age > policy.max_gpu_age_seconds:
                if key in active_pressure_reasons:
                    next_reasons.add(key)
                continue
            if gpu.free_vram_bytes is None:
                if key in active_pressure_reasons:
                    next_reasons.add(key)
                continue
            free_after_reservations = gpu.free_vram_bytes - reserved.vram_for(gpu.uuid)
            threshold = policy.min_gpu_free_vram_bytes + (
                policy.gpu_hysteresis_bytes if key in active_pressure_reasons else 0
            )
            if free_after_reservations < threshold:
                next_reasons.add(key)
    for key in active_pressure_reasons:
        if key.startswith("gpu_pressure:") and key not in observed_gpu_keys:
            next_reasons.add(key)

    return frozenset(next_reasons)


def admit_resources(
    snapshot: ResourceSnapshot,
    request: ResourceRequest,
    policy: ResourcePolicy = ResourcePolicy(),
    *,
    now_monotonic: float | None = None,
    reserved: ResourceClaims = ResourceClaims(),
    active_pressure_reasons: frozenset[str] = frozenset(),
) -> AdmissionDecision:
    """Make a pure, fail-closed decision from observations and explicit claims."""
    now = time.monotonic() if now_monotonic is None else now_monotonic
    _finite_nonnegative(now, "now_monotonic")

    if request.workload == "read" and not request.has_claims:
        return AdmissionDecision(True, (), active_pressure_reasons)
    if request.route == "remote" and not request.has_claims:
        return AdmissionDecision(True, (), active_pressure_reasons)

    reasons: set[str] = set()
    snapshot_age = now - snapshot.observed_at_monotonic
    if snapshot_age < 0:
        reasons.add("snapshot_clock_invalid")
    elif snapshot_age > policy.max_snapshot_age_seconds:
        reasons.add("snapshot_stale")

    next_pressure = _advance_pressure(
        snapshot,
        policy,
        reserved=reserved,
        now_monotonic=now,
        active_pressure_reasons=active_pressure_reasons,
    )
    if snapshot.ram_available_bytes is None:
        reasons.add("ram_telemetry_missing")
    elif (
        snapshot.ram_available_bytes - reserved.ram_bytes - request.ram_bytes
        < policy.min_ram_available_bytes
    ):
        reasons.add("ram_capacity_low")
    if snapshot.commit_available_bytes is None:
        reasons.add("commit_telemetry_missing")
    elif (
        snapshot.commit_available_bytes - reserved.commit_bytes - request.commit_bytes
        < policy.min_commit_available_bytes
    ):
        reasons.add("commit_capacity_low")

    if request.route == "local" or request.cpu_percent > 0:
        if snapshot.cpu_busy_percent is None:
            reasons.add("cpu_telemetry_missing")
        elif (
            snapshot.cpu_busy_percent + reserved.cpu_percent + request.cpu_percent
            > policy.max_cpu_busy_percent
        ):
            reasons.add("cpu_capacity_high")

    if "ram_pressure" in next_pressure:
        reasons.add("ram_pressure")
    if "commit_pressure" in next_pressure:
        reasons.add("commit_pressure")
    if "cpu_pressure" in next_pressure and (
        request.route == "local" or request.cpu_percent > 0
    ):
        reasons.add("cpu_pressure")

    if request.gpu_uuid is not None:
        if snapshot.gpus is None:
            reasons.add("gpu_telemetry_missing")
        else:
            gpu = next((item for item in snapshot.gpus if item.uuid == request.gpu_uuid), None)
            if gpu is None:
                reasons.add("gpu_not_found")
            else:
                gpu_age = gpu.telemetry_age_seconds(now)
                if gpu_age is None:
                    reasons.add("gpu_telemetry_clock_invalid")
                elif gpu_age > policy.max_gpu_age_seconds:
                    reasons.add("gpu_telemetry_stale")
                if gpu.error is not None:
                    reasons.add(gpu.error)
                if gpu.free_vram_bytes is None:
                    reasons.add("gpu_vram_telemetry_missing")
                elif (
                    gpu.free_vram_bytes
                    - reserved.vram_for(request.gpu_uuid)
                    - request.vram_bytes
                    < policy.min_gpu_free_vram_bytes
                ):
                    reasons.add("gpu_vram_low")
                if gpu.local_resident_bytes is None:
                    reasons.add("gpu_local_residency_unknown")
                key = _gpu_pressure_key(request.gpu_uuid)
                if key in next_pressure:
                    reasons.add("gpu_pressure")

    return AdmissionDecision(
        admitted=not reasons,
        reasons=tuple(sorted(reasons)),
        active_pressure_reasons=next_pressure,
    )


@dataclass(frozen=True, slots=True)
class ReservationResult:
    decision: AdmissionDecision
    reservation_id: str | None


@dataclass(slots=True)
class _ReservationRecord:
    claims: ResourceClaims
    started: bool = False
    reflection: ResourceReflection | None = None


class ResourceReservationBook:
    """Atomic, in-process host reservation ledger.

    Pending reservations are charged until observed usage is reflected in host
    counters. Started reservations need a fresh, per-reservation reflection;
    missing or stale reflection remains explicitly unknown and blocks admission
    for the affected resource. A sleeping or suspended child is not presumed
    complete: its current usage must be reconciled again, and it stays reserved
    until the host explicitly releases its opaque handle.
    """

    def __init__(self, policy: ResourcePolicy = ResourcePolicy()) -> None:
        self._policy = policy
        self._lock = threading.RLock()
        self._reservations: dict[str, _ReservationRecord] = {}
        self._active_pressure_reasons: frozenset[str] = frozenset()

    def _aggregate(
        self, *, now_monotonic: float
    ) -> tuple[ResourceClaims, frozenset[str], frozenset[str]]:
        ram_bytes = 0
        commit_bytes = 0
        cpu_percent = 0.0
        gpu_totals: dict[str, int] = {}
        unknown_kinds: set[str] = set()
        unknown_gpu_uuids: set[str] = set()

        for record in self._reservations.values():
            claims = record.claims
            reflection = record.reflection
            reflection_is_fresh = (
                record.started
                and reflection is not None
                and 0 <= now_monotonic - reflection.observed_at_monotonic
                <= self._policy.max_snapshot_age_seconds
            )
            if not record.started:
                reflected_ram = reflected_commit = 0
                reflected_cpu = 0.0
                reflected_gpu: dict[str, int] | None = {}
            elif not reflection_is_fresh:
                reflected_ram = None
                reflected_commit = None
                reflected_cpu = None
                reflected_gpu = None
            else:
                assert reflection is not None
                reflected_ram = reflection.ram_bytes
                reflected_commit = reflection.commit_bytes
                reflected_cpu = reflection.cpu_percent
                gpu_age = (
                    now_monotonic - reflection.gpu_observed_at_monotonic
                    if reflection.gpu_observed_at_monotonic is not None
                    else None
                )
                reflected_gpu = None
                if (
                    reflection.gpu_vram_bytes is not None
                    and gpu_age is not None
                    and 0 <= gpu_age <= self._policy.max_gpu_age_seconds
                ):
                    reflected_gpu = dict(reflection.gpu_vram_bytes)

            def add_unreflected(
                claim: int | float,
                observed: int | float | None,
                kind: str,
            ) -> int | float:
                if claim <= 0:
                    return 0
                if observed is None:
                    unknown_kinds.add(kind)
                    return 0
                return max(0, claim - observed)

            ram_bytes += int(add_unreflected(claims.ram_bytes, reflected_ram, "ram"))
            commit_bytes += int(
                add_unreflected(claims.commit_bytes, reflected_commit, "commit")
            )
            cpu_percent += float(
                add_unreflected(claims.cpu_percent, reflected_cpu, "cpu")
            )
            for uuid, amount in claims.gpu_vram_bytes:
                if reflected_gpu is None:
                    unknown_gpu_uuids.add(uuid)
                    continue
                remaining = max(0, amount - reflected_gpu.get(uuid, 0))
                if remaining:
                    gpu_totals[uuid] = gpu_totals.get(uuid, 0) + remaining

        claims = ResourceClaims(
            ram_bytes=ram_bytes,
            commit_bytes=commit_bytes,
            cpu_percent=cpu_percent,
            gpu_vram_bytes=tuple(sorted(gpu_totals.items())),
        )
        return claims, frozenset(unknown_kinds), frozenset(unknown_gpu_uuids)

    def reserve(
        self,
        snapshot: ResourceSnapshot,
        request: ResourceRequest,
        *,
        now_monotonic: float | None = None,
    ) -> ReservationResult:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        _finite_nonnegative(now, "now_monotonic")
        with self._lock:
            current, unknown_kinds, unknown_gpu_uuids = self._aggregate(
                now_monotonic=now
            )
            if request.has_claims and len(self._reservations) >= self._policy.max_active_reservations:
                return ReservationResult(
                    AdmissionDecision(
                        admitted=False,
                        reasons=("reservation_limit",),
                        active_pressure_reasons=self._active_pressure_reasons,
                    ),
                    None,
                )
            required_unknown = set()
            if request.ram_bytes:
                required_unknown.add("ram")
            if request.commit_bytes:
                required_unknown.add("commit")
            if request.cpu_percent:
                required_unknown.add("cpu")
            if request.gpu_uuid is not None and request.gpu_uuid in unknown_gpu_uuids:
                required_unknown.add("gpu")
            unknown_kinds_for_request = set(unknown_kinds)
            if unknown_gpu_uuids:
                unknown_kinds_for_request.add("gpu")
            if required_unknown.intersection(unknown_kinds_for_request):
                decision = AdmissionDecision(
                    admitted=False,
                    reasons=("reservation_reconciliation_unknown",),
                    active_pressure_reasons=self._active_pressure_reasons,
                )
                return ReservationResult(decision, None)
            decision = admit_resources(
                snapshot,
                request,
                self._policy,
                now_monotonic=now,
                reserved=current,
                active_pressure_reasons=self._active_pressure_reasons,
            )
            self._active_pressure_reasons = decision.active_pressure_reasons
            if not decision.admitted or not request.has_claims:
                return ReservationResult(decision, None)
            reservation_id = token_urlsafe(24)
            self._reservations[reservation_id] = _ReservationRecord(request.claims())
            return ReservationResult(decision, reservation_id)

    def release(self, reservation_id: str) -> bool:
        if not isinstance(reservation_id, str) or not reservation_id:
            return False
        with self._lock:
            return self._reservations.pop(reservation_id, None) is not None

    def mark_started(self, reservation_id: str) -> bool:
        """Mark that a reserved child started and now needs reconciliation."""
        if not isinstance(reservation_id, str) or not reservation_id:
            return False
        with self._lock:
            record = self._reservations.get(reservation_id)
            if record is None or record.started:
                return False
            record.started = True
            record.reflection = None
            return True

    def reconcile(
        self,
        reservation_id: str,
        reflection: ResourceReflection | None,
    ) -> bool:
        """Record fresh per-reservation usage already included in host counters."""
        if not isinstance(reservation_id, str) or not reservation_id:
            return False
        with self._lock:
            record = self._reservations.get(reservation_id)
            if record is None or not record.started:
                return False
            record.reflection = reflection
            return True

    def reserved_claims(
        self, *, now_monotonic: float | None = None
    ) -> ResourceClaims:
        """Return known pending/unreflected claims, excluding measured usage.

        Use reserve for an atomic admission decision. Callers combining these
        claims with admit_resources directly must also check
        unreconciled_resource_kinds, because unknown dimensions are not totals.
        """
        now = time.monotonic() if now_monotonic is None else now_monotonic
        _finite_nonnegative(now, "now_monotonic")
        with self._lock:
            claims, _unknown_kinds, _unknown_gpu_uuids = self._aggregate(
                now_monotonic=now
            )
            return claims

    def unreconciled_resource_kinds(
        self, *, now_monotonic: float | None = None
    ) -> tuple[str, ...]:
        """Expose bounded, non-identifying reconciliation state for status."""
        now = time.monotonic() if now_monotonic is None else now_monotonic
        _finite_nonnegative(now, "now_monotonic")
        with self._lock:
            _claims, unknown_kinds, unknown_gpu_uuids = self._aggregate(
                now_monotonic=now
            )
            kinds = set(unknown_kinds)
            if unknown_gpu_uuids:
                kinds.add("gpu")
            return tuple(sorted(kinds))


def query_windows_commit_memory() -> tuple[int | None, int | None]:
    """Read the Windows system commit limit/headroom without changing it."""
    if sys.platform != "win32":
        return None, None

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        global_memory_status_ex = kernel32.GlobalMemoryStatusEx
        global_memory_status_ex.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
        global_memory_status_ex.restype = ctypes.c_bool
        if not global_memory_status_ex(ctypes.byref(status)):
            return None, None
        return int(status.ullTotalPageFile), int(status.ullAvailPageFile)
    except (AttributeError, OSError, TypeError, ValueError):
        return None, None


class ResourceSnapshotCollector:
    """Collect passive OS counters and optional bounded GPU observations.

    The collector reads no Hermes configuration, DB, credential store, model
    endpoint, or container runtime. ``local_process_ids`` must come from the
    existing host-owned local-runtime lifecycle source; absent that source,
    GPU residency stays unknown.
    """

    def __init__(
        self,
        *,
        psutil_module: Any | None = None,
        commit_provider: Callable[[], tuple[int | None, int | None]] | None = None,
        gpu_provider: Callable[..., NvidiaGpuProbeResult] = query_nvidia_gpu_telemetry,
        local_pid_provider: Callable[[], tuple[int, ...] | list[int]] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        platform_name: str = sys.platform,
        max_cpu_sample_window_seconds: float = 5.0,
    ) -> None:
        _finite_nonnegative(
            max_cpu_sample_window_seconds, "max_cpu_sample_window_seconds"
        )
        if max_cpu_sample_window_seconds == 0:
            raise ValueError("max_cpu_sample_window_seconds must be positive")
        self._psutil = psutil_module
        self._commit_provider = commit_provider
        self._gpu_provider = gpu_provider
        self._local_pid_provider = local_pid_provider
        self._clock = monotonic_clock
        self._platform_name = platform_name
        self._cpu_sample_seen = False
        self._last_cpu_sample_at: float | None = None
        self._max_cpu_sample_window_seconds = max_cpu_sample_window_seconds

    def _load_psutil(self) -> Any:
        if self._psutil is None:
            self._psutil = importlib.import_module("psutil")
        return self._psutil

    def collect(self) -> ResourceSnapshot:
        errors: set[str] = set()
        ram_total: int | None = None
        ram_available: int | None = None
        commit_limit: int | None = None
        commit_available: int | None = None
        cpu_busy: float | None = None
        psutil_module: Any | None = None

        try:
            psutil_module = self._load_psutil()
            vm = psutil_module.virtual_memory()
            for value in (getattr(vm, "total", None), getattr(vm, "available", None)):
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError
            ram_total = int(vm.total)
            ram_available = int(vm.available)
        except Exception:
            errors.add("ram_probe_failed")

        try:
            if self._commit_provider is not None:
                commit_limit, commit_available = self._commit_provider()
            elif self._platform_name == "win32":
                commit_limit, commit_available = query_windows_commit_memory()
            else:
                errors.add("commit_telemetry_unsupported")
            _nonnegative_int(commit_limit, "commit_limit_bytes")
            _nonnegative_int(commit_available, "commit_available_bytes")
            if commit_limit is None or commit_available is None:
                errors.add("commit_telemetry_unavailable")
        except Exception:
            commit_limit, commit_available = None, None
            errors.add("commit_probe_failed")

        if psutil_module is not None:
            try:
                sample_at = self._clock()
                raw_cpu = psutil_module.cpu_percent(interval=None)
                if isinstance(raw_cpu, bool) or not isinstance(raw_cpu, (int, float)):
                    raise ValueError
                if not math.isfinite(float(raw_cpu)) or not 0 <= raw_cpu <= 100:
                    raise ValueError
                if self._cpu_sample_seen:
                    assert self._last_cpu_sample_at is not None
                    sample_window = sample_at - self._last_cpu_sample_at
                    if sample_window <= 0:
                        errors.add("cpu_sample_clock_invalid")
                    elif sample_window > self._max_cpu_sample_window_seconds:
                        errors.add("cpu_sample_window_too_wide")
                    else:
                        cpu_busy = float(raw_cpu)
                else:
                    errors.add("cpu_first_sample")
                self._cpu_sample_seen = True
                self._last_cpu_sample_at = sample_at
            except Exception:
                errors.add("cpu_probe_failed")
        else:
            errors.add("cpu_telemetry_unavailable")

        local_pids: tuple[int, ...] | None = None
        if self._local_pid_provider is not None:
            try:
                raw_pids = self._local_pid_provider()
                if not isinstance(raw_pids, (tuple, list)) or len(raw_pids) > 4096:
                    errors.add("gpu_local_process_ids_invalid")
                elif any(
                    isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
                    for pid in raw_pids
                ):
                    errors.add("gpu_local_process_ids_invalid")
                else:
                    local_pids = tuple(raw_pids)
            except Exception:
                errors.add("local_residency_source_unavailable")

        gpu_snapshots: tuple[GpuResourceSnapshot, ...] | None = None
        try:
            probe = self._gpu_provider(local_process_ids=local_pids)
            if probe.error is not None:
                safe_error = _safe_error_code(probe.error)
                if safe_error is not None:
                    errors.add(safe_error)
            if probe.residency_error is not None:
                safe_error = _safe_error_code(probe.residency_error)
                if safe_error is not None:
                    errors.add(safe_error)
            if probe.devices is not None:
                gpu_snapshots = tuple(
                    GpuResourceSnapshot(
                        uuid=device.uuid,
                        free_vram_bytes=device.free_vram_bytes,
                        local_resident_bytes=device.local_resident_bytes,
                        observed_at_monotonic=device.observed_at_monotonic,
                        error=(
                            probe.residency_error
                            if device.local_resident_bytes is None
                            else None
                        ),
                    )
                    for device in probe.devices[:16]
                )
        except Exception:
            errors.add("gpu_probe_failed")

        observed_at = self._clock()
        return ResourceSnapshot(
            observed_at_monotonic=observed_at,
            ram_total_bytes=ram_total,
            ram_available_bytes=ram_available,
            commit_limit_bytes=commit_limit,
            commit_available_bytes=commit_available,
            cpu_busy_percent=cpu_busy,
            gpus=gpu_snapshots,
            errors=tuple(sorted(errors)),
        )


__all__ = [
    "AdmissionDecision",
    "GpuResourceSnapshot",
    "ResourceClaims",
    "ResourcePolicy",
    "ResourceReflection",
    "ResourceRequest",
    "ResourceReservationBook",
    "ResourceSnapshot",
    "ResourceSnapshotCollector",
    "ReservationResult",
    "admit_resources",
    "query_windows_commit_memory",
]
