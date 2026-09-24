from __future__ import annotations

import threading


class SnapshotReservation:
    """A process-local reservation for one active scan snapshot."""

    def __init__(self, size: int, release_callback) -> None:
        self.size = size
        self._release_callback = release_callback
        self._released = False
        self._release_lock = threading.Lock()

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._release_callback(self.size)

    def __enter__(self) -> SnapshotReservation:
        return self

    def __exit__(self, *_args) -> None:
        self.release()


class _ProcessSnapshotBudget:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reserved_bytes = 0

    def reserve(self, size: int, limit: int) -> SnapshotReservation | None:
        if size < 0 or limit < 0:
            return None
        with self._lock:
            if size > limit - self._reserved_bytes:
                return None
            self._reserved_bytes += size
        return SnapshotReservation(size, self.release)

    def release(self, size: int) -> None:
        with self._lock:
            self._reserved_bytes = max(0, self._reserved_bytes - size)


_PROCESS_SNAPSHOT_BUDGET = _ProcessSnapshotBudget()


def reserve_snapshot_bytes(size: int, limit: int) -> SnapshotReservation | None:
    """Reserve bounded in-flight bytes across all SecurityService instances."""
    return _PROCESS_SNAPSHOT_BUDGET.reserve(size, limit)


def active_snapshot_bytes() -> int:
    """Expose the current reservation total for deterministic invariant tests."""
    with _PROCESS_SNAPSHOT_BUDGET._lock:
        return _PROCESS_SNAPSHOT_BUDGET._reserved_bytes
