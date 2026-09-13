"""Process-wide path-keyed SessionDB sharing (Windows REIMPLEMENT_NATIVE).

Upstream carries the same observable contract in ``hermes_state_registry``
(#90837): one writable SessionDB per resolved ``state.db`` path per process,
refcount acquire/release, ``close()`` on a shared handle releasing rather than
tearing down under other holders, and generation retirement when the on-disk
file identity changes (snapshot restore / recovery swap).

This module intentionally does **not** port U's registry file layout, POSIX
fd-close fault machinery, or multi-barrier teardown tables. Gateway
``RecoverableHandleCache`` remains the recovery/backoff layer and must open
through :func:`acquire` so Goals and gateway do not mint competing writers.

Slices: SR-20260913-003a (refcount share) + 003b (identity generation).
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from hermes_state import SessionDB

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_entries: Dict[Path, "_Entry"] = {}
# Retired generations stay alive for their holders; keyed by id(db) so releases
# after a path remap still find the correct generation (SR-003b).
_retired: Dict[int, "_Entry"] = {}


class _Entry:
    __slots__ = ("path", "db", "refcount", "identity", "retired")

    def __init__(
        self,
        path: Path,
        db: "SessionDB",
        identity: Optional[Tuple[int, int]],
    ) -> None:
        self.path = path
        self.db = db
        self.refcount = 1
        self.identity = identity
        self.retired = False


def stat_db_file_identity(path: Path | str) -> Optional[Tuple[int, int]]:
    """``(st_dev, st_ino)`` for *path*, or None when unknown.

    ``st_ino=0`` (common on some Windows / network FS) would false-positive
    every replaced-file check, so it counts as unknown — same contract as
    upstream ``hermes_state_common.stat_db_file_identity``.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino) if st.st_dev and st.st_ino else None


def _resolve_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        raw = Path(db_path)
    else:
        from hermes_state import _default_db_path

        raw = Path(_default_db_path())
    try:
        return raw.resolve()
    except OSError:
        return raw


def _open_session_db(path: Path) -> "SessionDB":
    """Construct SessionDB for *path* (tests may patch this)."""
    from hermes_state import SessionDB

    return SessionDB(db_path=path)


def _retire_locked(entry: "_Entry") -> None:
    """Move *entry* out of the live path map (caller holds ``_lock``)."""
    entry.retired = True
    if _entries.get(entry.path) is entry:
        _entries.pop(entry.path, None)
    _retired[id(entry.db)] = entry


def acquire(db_path: Optional[Path] = None) -> "SessionDB":
    """Return the shared SessionDB for *db_path*, incrementing its refcount.

    When the on-disk file identity differs from the live generation's (and both
    identities are known), that generation is RETIRED but stays alive for its
    holders; a fresh generation is opened for new callers.
    """
    path = _resolve_path(db_path)
    with _lock:
        entry = _entries.get(path)
        if entry is not None and entry.db._conn is not None:
            current = stat_db_file_identity(path)
            if (
                current is not None
                and entry.identity is not None
                and current != entry.identity
            ):
                _retire_locked(entry)
            else:
                entry.refcount += 1
                return entry.db
        elif entry is not None:
            # Stale closed live entry: drop before reopen.
            _entries.pop(path, None)

    db = _open_session_db(path)
    db._shared_owned = True
    identity = stat_db_file_identity(path)
    with _lock:
        existing = _entries.get(path)
        if existing is not None and existing.db._conn is not None:
            # Lost the race — keep the winner, discard our extra writer.
            existing.refcount += 1
            loser = db
            db = existing.db
        else:
            _entries[path] = _Entry(path, db, identity)
            return db

    loser._shared_owned = False
    try:
        loser.close()
    except Exception:
        logger.debug("Discarding raced SessionDB open failed", exc_info=True)
    return db


def release(db: "SessionDB") -> bool:
    """Drop one shared refcount. Final release tears the connection down.

    Lookup is object-keyed for retired generations so an inode replacement
    cannot strand a still-owned generation on the wrong path entry.
    """
    if not getattr(db, "_shared_owned", False):
        return False

    teardown = False
    with _lock:
        entry = _retired.get(id(db))
        if entry is None:
            path = getattr(db, "db_path", None)
            try:
                key = None if path is None else Path(path)
                if key is not None:
                    try:
                        key = key.resolve()
                    except OSError:
                        pass
            except (TypeError, ValueError):
                key = None
            entry = _entries.get(key) if key is not None else None
            if entry is None or entry.db is not db:
                db._shared_owned = False
                return True
        entry.refcount -= 1
        if entry.refcount > 0:
            return True
        if entry.retired:
            _retired.pop(id(db), None)
        elif _entries.get(entry.path) is entry:
            _entries.pop(entry.path, None)
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
    """Tear down every live and retired shared entry (tests / shutdown)."""
    with _lock:
        entries = list(_entries.values()) + list(_retired.values())
        _entries.clear()
        _retired.clear()
    closed = 0
    seen: set[int] = set()
    for entry in entries:
        if id(entry.db) in seen:
            continue
        seen.add(id(entry.db))
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
            "retired_generations": len(_retired),
            "total_refcounts": sum(e.refcount for e in _entries.values())
            + sum(e.refcount for e in _retired.values()),
        }
