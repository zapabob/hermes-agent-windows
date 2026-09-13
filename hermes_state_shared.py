"""Process-wide path-keyed SessionDB sharing (Windows REIMPLEMENT_NATIVE).

Upstream carries the same observable contract in ``hermes_state_registry``
(#90837): one writable SessionDB per resolved ``state.db`` path per process,
refcount acquire/release, and ``close()`` on a shared handle releasing rather
than tearing down under other holders.

This module intentionally does **not** port U's registry file layout, inode
generation retire/drain tables, or POSIX fd-close fault machinery. Gateway
``RecoverableHandleCache`` remains the recovery/backoff layer and must open
through :func:`acquire` so Goals and gateway do not mint competing writers.

Slice SR-20260913-003a. Inode-replacement generations → 003b.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:  # pragma: no cover
    from hermes_state import SessionDB

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_entries: Dict[Path, "_Entry"] = {}


class _Entry:
    __slots__ = ("path", "db", "refcount")

    def __init__(self, path: Path, db: "SessionDB") -> None:
        self.path = path
        self.db = db
        self.refcount = 1


def _resolve_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    from hermes_state import _default_db_path

    return Path(_default_db_path())


def _open_session_db(path: Path) -> "SessionDB":
    """Construct SessionDB for *path* (tests may patch this)."""
    from hermes_state import SessionDB

    return SessionDB(db_path=path)


def acquire(db_path: Optional[Path] = None) -> "SessionDB":
    """Return the shared SessionDB for *db_path*, incrementing its refcount."""
    path = _resolve_path(db_path)
    with _lock:
        entry = _entries.get(path)
        if entry is not None and entry.db._conn is not None:
            entry.refcount += 1
            return entry.db
        # Stale closed entry (should be rare): drop and reopen.
        if entry is not None:
            _entries.pop(path, None)

    db = _open_session_db(path)
    db._shared_owned = True
    with _lock:
        existing = _entries.get(path)
        if existing is not None and existing.db._conn is not None:
            # Lost the race — keep the winner, close our extra writer.
            existing.refcount += 1
            loser = db
            db = existing.db
        else:
            _entries[path] = _Entry(path, db)
            return db

    loser._shared_owned = False
    try:
        loser.close()
    except Exception:
        logger.debug("Discarding raced SessionDB open failed", exc_info=True)
    return db


def release(db: "SessionDB") -> bool:
    """Drop one shared refcount. Final release tears the connection down.

    Returns True when *db* was shared-managed, False when the caller should
    fall through to a plain ``close()``.
    """
    if not getattr(db, "_shared_owned", False):
        return False

    path = getattr(db, "db_path", None)
    try:
        key = None if path is None else Path(path)
    except (TypeError, ValueError):
        key = None

    teardown = False
    with _lock:
        entry = None
        if key is not None:
            entry = _entries.get(key)
        if entry is None or entry.db is not db:
            # Object not in the table (already released / replaced).
            db._shared_owned = False
            return True
        entry.refcount -= 1
        if entry.refcount > 0:
            return True
        _entries.pop(key, None)
        db._shared_owned = False
        teardown = True

    if teardown:
        try:
            db.close()
        except Exception:
            logger.debug("Shared SessionDB final close failed", exc_info=True)
    return True


def release_or_close(db: "SessionDB") -> None:
    """Release a shared instance, else close a bare one."""
    if not release(db):
        try:
            db.close()
        except Exception:
            logger.debug("release_or_close fallback close failed", exc_info=True)


def close_all() -> int:
    """Tear down every shared entry (tests / process shutdown)."""
    with _lock:
        entries = list(_entries.values())
        _entries.clear()
    closed = 0
    for entry in entries:
        entry.db._shared_owned = False
        try:
            entry.db.close()
            closed += 1
        except Exception:
            logger.debug("close_all SessionDB failed", exc_info=True)
    return closed


def stats() -> Dict[str, int]:
    with _lock:
        return {
            "live_paths": len(_entries),
            "total_refcounts": sum(e.refcount for e in _entries.values()),
        }
