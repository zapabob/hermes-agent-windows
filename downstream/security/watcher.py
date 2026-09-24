from __future__ import annotations

import argparse
import os
import signal
import time
from pathlib import Path
from typing import Any, Protocol

import psutil

from hermes_constants import get_hermes_home

from .service import SecurityService, is_reparse_point
from .bounded_walk import (
    DirectoryWalkReport,
    MAX_SCAN_ROOTS,
    MAX_WALK_DEPTH,
    MAX_WALK_DIRECTORIES,
    MAX_WALK_ENTRIES,
    MAX_WATCH_FILES,
    iter_regular_files,
)
from .watch_state import claim_watch_owner, clear_watch_owner, runtime_lock


class _WatchStore(Protocol):
    root: Path

    def event(
        self,
        event_type: str,
        subject: str,
        verdict: str | None,
        action: str,
        details: dict[str, Any],
    ) -> None: ...


class _ReconcileService(Protocol):
    store: _WatchStore

    def quick_paths(self) -> list[Path]: ...

    def scan_file(self, candidate: Path | str, quarantine: bool = True, use_cache: bool = True) -> object: ...


def reconcile_once(
    service: _ReconcileService,
    seen: dict[str, tuple[int, int]],
    *,
    scan_changes: bool = True,
    inventory_event_state: dict[str, float | str] | None = None,
) -> dict[str, tuple[int, int]]:
    current: dict[str, tuple[int, int]] = {}
    event_state = inventory_event_state if inventory_event_state is not None else {}
    inventory_incomplete = False
    roots = service.quick_paths()
    for root_index, root in enumerate(roots):
        if root_index >= MAX_SCAN_ROOTS:
            inventory_incomplete = True
            _record_inventory_incomplete(service, "<root-limit>", "root_limit", event_state)
            break
        report = DirectoryWalkReport()
        remaining = max(0, MAX_WATCH_FILES - len(current))
        files = iter_regular_files(
            root,
            report,
            max_files=remaining,
            max_entries=MAX_WALK_ENTRIES,
            max_directories=MAX_WALK_DIRECTORIES,
            max_depth=MAX_WALK_DEPTH,
        )
        for path in files:
            try:
                stat_result = path.stat(follow_symlinks=False)
            except OSError:
                report.mark("entry_stat_error", error=True)
                continue
            identity = (stat_result.st_size, stat_result.st_mtime_ns)
            key = str(path)
            current[key] = identity
            if scan_changes and seen.get(key) != identity:
                try:
                    service.scan_file(path)
                except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                    service.store.event("watch_scan_error", key, None, "scan_failed", {"error": str(exc)})
        if not report.complete:
            inventory_incomplete = True
            _record_inventory_incomplete(
                service,
                str(root),
                report.truncated_reason or "inventory_error",
                event_state,
            )
    if not inventory_incomplete:
        event_state.clear()
    return current


def _record_inventory_incomplete(
    service: _ReconcileService,
    key: str,
    reason: str,
    state: dict[str, float | str],
) -> None:
    if state.get(key) == reason:
        return
    service.store.event(
        "watch_inventory_incomplete",
        key,
        None,
        "review",
        {"reason": reason},
    )
    if key not in state and len(state) >= MAX_SCAN_ROOTS:
        state.pop(next(iter(state)))
    state[key] = reason


def run(interval: float, request_nonce: str, owner_nonce: str) -> int:
    root = get_hermes_home() / "security"
    with runtime_lock(root) as acquired:
        if not acquired:
            return 0
        service = SecurityService()
        stopping = False
        if os.name == "nt":
            try:
                psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            except (OSError, psutil.Error):
                pass

        def request_stop(_signum, _frame) -> None:
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, request_stop)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, request_stop)
        if claim_watch_owner(root, request_nonce, owner_nonce) is None:
            return 0
        try:
            inventory_event_state: dict[str, float | str] = {}
            seen = reconcile_once(service, {}, scan_changes=False, inventory_event_state=inventory_event_state)
            while not stopping:
                seen = reconcile_once(service, seen, inventory_event_state=inventory_event_state)
                deadline = time.monotonic() + max(2.0, interval)
                while not stopping and time.monotonic() < deadline:
                    time.sleep(min(0.5, deadline - time.monotonic()))
        finally:
            clear_watch_owner(root, request_nonce, owner_nonce)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--request-nonce", required=True)
    parser.add_argument("--owner-nonce", required=True)
    args = parser.parse_args()
    return run(args.interval, args.request_nonce, args.owner_nonce)


if __name__ == "__main__":
    raise SystemExit(main())
