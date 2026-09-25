"""Structural SQLite schema identity for the Ebbinghaus memory database.

The builtin store (``store._BASE_SCHEMA`` + ``store._migrate`` +
``migrations.apply_experience_migrations``) is the single canonical schema
definition. An alternative store implementation may share a database only if
it produces exactly the same identity; see ``open_shared_store``.

The fingerprint is structural (``PRAGMA table_xinfo`` / ``index_list`` /
``index_xinfo``) rather than raw ``sqlite_master`` text, because
``ALTER TABLE ADD COLUMN`` rewrites the stored CREATE TABLE text: a legacy
database migrated in place and a freshly created one hold different DDL
strings for the same readable schema.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import logging
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

MIGRATIONS_TABLE = "ebbinghaus_schema_migrations"


class SchemaIdentityMismatch(RuntimeError):
    """Raised when two store implementations disagree on the database schema."""


@dataclass(frozen=True)
class SchemaIdentity:
    user_version: int
    migrations: tuple[tuple[int, str], ...]
    digest: str


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def schema_identity(conn: sqlite3.Connection) -> SchemaIdentity:
    """Return the structural schema identity of an open connection."""
    user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    objects: list[Any] = []
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    for obj_type, name, tbl_name, sql in rows:
        if obj_type == "table":
            columns = sorted(
                (str(c[1]), str(c[2] or "").upper(), int(c[3]), c[4], int(c[5]), int(c[6]))
                for c in conn.execute(f"PRAGMA table_xinfo({_quote(name)})").fetchall()
            )
            indexes = []
            for idx in conn.execute(f"PRAGMA index_list({_quote(name)})").fetchall():
                idx_name = str(idx[1])
                idx_columns = [
                    (int(k[0]), None if k[2] is None else str(k[2]), int(k[3]), int(k[5]))
                    for k in conn.execute(f"PRAGMA index_xinfo({_quote(idx_name)})").fetchall()
                ]
                indexes.append((idx_name, int(idx[2]), str(idx[3]), int(idx[4]), idx_columns))
            objects.append(("table", name, columns, sorted(indexes)))
        elif obj_type in {"view", "trigger"}:
            objects.append((obj_type, name, tbl_name, " ".join(str(sql or "").split())))
        # Indexes are covered through each table's index_list above.

    migrations: tuple[tuple[int, str], ...] = ()
    has_migrations = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (MIGRATIONS_TABLE,),
    ).fetchone()
    if has_migrations:
        migrations = tuple(
            (int(v), str(n))
            for v, n in conn.execute(
                f"SELECT version, name FROM {MIGRATIONS_TABLE} ORDER BY version"
            ).fetchall()
        )

    payload = json.dumps(
        {"user_version": user_version, "migrations": migrations, "objects": objects},
        sort_keys=True,
        default=str,
    )
    return SchemaIdentity(
        user_version=user_version,
        migrations=migrations,
        digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


def read_schema_identity(db_path: str | Path) -> SchemaIdentity | None:
    """Read the identity of a database file without writing to it."""
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        return None
    with contextlib.closing(
        sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10.0)
    ) as conn:
        return schema_identity(conn)


def probe_schema_identity(store_factory: Callable[[Path], Any]) -> SchemaIdentity:
    """Create a store on a scratch database and return the schema it produces."""
    with tempfile.TemporaryDirectory(
        prefix="ebbinghaus-schema-probe-", ignore_cleanup_errors=True
    ) as tmp:
        db_path = Path(tmp) / "probe.db"
        store = store_factory(db_path)
        store.close()
        identity = read_schema_identity(db_path)
    if identity is None:
        raise SchemaIdentityMismatch("schema probe did not create a database")
    return identity


@functools.lru_cache(maxsize=None)
def store_class_schema_identity(store_cls: type) -> SchemaIdentity:
    """Probe (once per process) the schema a store class creates."""
    return probe_schema_identity(lambda path: store_cls(path))


def canonical_schema_identity() -> SchemaIdentity:
    """Schema identity produced by the builtin (canonical) store."""
    from .store import EbbinghausMemoryStore

    return store_class_schema_identity(EbbinghausMemoryStore)


def open_shared_store(
    db_path: str | Path,
    *,
    store_cls: type,
    store_kwargs: dict[str, Any],
    canonical_kwargs: dict[str, Any],
) -> Any:
    """Open ``store_cls`` on ``db_path`` only if it cannot diverge from builtin.

    1. ``store_cls`` must create exactly the canonical schema on a scratch DB,
       so its own copy of the migrations is provably identical. The real
       database is not touched when this fails.
    2. The builtin store opens ``db_path`` first, so only the canonical
       migrations ever change the real database's schema.
    3. The migrated database must match the canonical identity (a database
       from a newer or foreign schema is refused), and must still match after
       ``store_cls`` has opened it.
    """
    from .store import EbbinghausMemoryStore

    canonical = canonical_schema_identity()
    candidate = store_class_schema_identity(store_cls)
    if candidate != canonical:
        raise SchemaIdentityMismatch(
            f"{store_cls.__module__} creates schema {candidate.digest[:12]} "
            f"(migrations {candidate.migrations}), builtin creates "
            f"{canonical.digest[:12]} (migrations {canonical.migrations})"
        )

    EbbinghausMemoryStore(db_path, **canonical_kwargs).close()
    current = read_schema_identity(db_path)
    if current != canonical:
        raise SchemaIdentityMismatch(
            f"database {db_path} has schema "
            f"{current.digest[:12] if current else None} (migrations "
            f"{current.migrations if current else None}); expected "
            f"{canonical.digest[:12]}"
        )

    store = store_cls(db_path, **store_kwargs)
    after = read_schema_identity(db_path)
    if after != canonical:
        store.close()
        logger.error(
            "Ebbinghaus shared store changed the schema of %s after passing the "
            "probe (%s -> %s)",
            db_path,
            canonical.digest[:12],
            after.digest[:12] if after else None,
        )
        raise SchemaIdentityMismatch(f"{store_cls.__module__} altered the schema of {db_path}")
    return store
