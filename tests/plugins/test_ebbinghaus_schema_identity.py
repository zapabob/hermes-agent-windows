"""Shared-database schema guard for the Ebbinghaus builtin and hakua stores."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_repo_root = str(Path(__file__).resolve().parents[2])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import plugins.memory.ebbinghaus as ebbinghaus_plugin  # noqa: E402
from plugins.memory.ebbinghaus import (  # noqa: E402
    CapacityError,
    EbbinghausMemoryProvider,
    EbbinghausMemoryStore,
    EbbinghausPolicies,
)
from plugins.memory.ebbinghaus.schema_identity import (  # noqa: E402
    canonical_schema_identity,
    read_schema_identity,
    store_class_schema_identity,
)

_LEGACY_MEMORIES_DDL = """
CREATE TABLE memories (
    memory_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content            TEXT NOT NULL UNIQUE,
    encoded            TEXT NOT NULL,
    cues               TEXT DEFAULT '',
    tags               TEXT DEFAULT '',
    salience           REAL DEFAULT 0.6,
    valence            REAL DEFAULT 0.0,
    strength           REAL DEFAULT 1.0,
    rehearsal_count    INTEGER DEFAULT 0,
    retrieval_count    INTEGER DEFAULT 0,
    source             TEXT DEFAULT '',
    session_id         TEXT DEFAULT '',
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL,
    last_rehearsed_at  REAL,
    last_retrieved_at  REAL
);
"""


class _RecordingStore(EbbinghausMemoryStore):
    """Builtin-identical stand-in for hakua that records where it was opened."""

    opened: list[Path] = []

    def __init__(self, db_path, **kwargs):
        type(self).opened.append(Path(db_path).resolve())
        super().__init__(db_path, **kwargs)


class _DivergentStore(_RecordingStore):
    """Simulates a hakua release that ships an extra migration."""

    opened: list[Path] = []

    def _init_db(self) -> None:
        super()._init_db()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS future_feature (id INTEGER PRIMARY KEY)"
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO ebbinghaus_schema_migrations"
            "(version, name, applied_at, backup_path) VALUES (2, 'future_v2', 0, '')"
        )
        self._conn.commit()


def _use_fake_hakua(monkeypatch, store_cls):
    monkeypatch.setattr(
        ebbinghaus_plugin,
        "_load_hakua_store_backend",
        lambda: (store_cls, EbbinghausPolicies, CapacityError),
    )


def _open(tmp_path, db_path, backend):
    provider = EbbinghausMemoryProvider({"db_path": str(db_path), "store_backend": backend})
    provider.initialize("session", hermes_home=str(tmp_path))
    return provider


def _remember(provider, content):
    result = json.loads(
        provider.handle_tool_call("ebbinghaus_memory", {"action": "remember", "content": content})
    )
    assert result.get("memory_id") is not None, result


def _contents(provider):
    listed = json.loads(provider.handle_tool_call("ebbinghaus_memory", {"action": "list"}))
    return {item["content"] for item in listed["memories"]}


def test_builtin_identity_is_stable_across_reopen(tmp_path):
    db_path = tmp_path / "memory.db"
    EbbinghausMemoryStore(db_path).close()
    first = read_schema_identity(db_path)
    EbbinghausMemoryStore(db_path).close()
    assert first == read_schema_identity(db_path) == canonical_schema_identity()
    assert first.migrations, "experience migration must be recorded"


def test_legacy_database_migrated_in_place_matches_canonical_identity(tmp_path):
    db_path = tmp_path / "legacy.db"
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(_LEGACY_MEMORIES_DDL)
        conn.execute(
            "INSERT INTO memories(content, encoded, created_at, updated_at) "
            "VALUES ('legacy trace', 'legacy', 1.0, 1.0)"
        )
        conn.commit()

    EbbinghausMemoryStore(db_path).close()

    assert read_schema_identity(db_path) == canonical_schema_identity()


def test_identical_backend_shares_database_both_ways(tmp_path, monkeypatch):
    _RecordingStore.opened = []
    _use_fake_hakua(monkeypatch, _RecordingStore)
    db_path = tmp_path / "memory.db"

    provider = _open(tmp_path, db_path, "hakua")
    assert provider.store_backend == "hakua"
    _remember(provider, "written through the shared backend")
    provider.shutdown()

    provider = _open(tmp_path, db_path, "builtin")
    assert "written through the shared backend" in _contents(provider)
    _remember(provider, "written through builtin")
    provider.shutdown()

    provider = _open(tmp_path, db_path, "hakua")
    assert provider.store_backend == "hakua"
    assert "written through builtin" in _contents(provider)
    provider.shutdown()
    assert read_schema_identity(db_path) == canonical_schema_identity()


def test_divergent_backend_schema_falls_back_without_touching_database(tmp_path, monkeypatch):
    _DivergentStore.opened = []
    _use_fake_hakua(monkeypatch, _DivergentStore)
    db_path = tmp_path / "memory.db"
    EbbinghausMemoryStore(db_path).close()
    before = read_schema_identity(db_path)

    provider = _open(tmp_path, db_path, "hakua")
    try:
        assert provider.store_backend == "builtin"
        assert db_path.resolve() not in _DivergentStore.opened
        assert store_class_schema_identity(_DivergentStore) != canonical_schema_identity()
    finally:
        provider.shutdown()
    assert read_schema_identity(db_path) == before


def test_database_with_foreign_schema_is_not_shared(tmp_path, monkeypatch):
    _RecordingStore.opened = []
    _use_fake_hakua(monkeypatch, _RecordingStore)
    db_path = tmp_path / "memory.db"
    EbbinghausMemoryStore(db_path).close()
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO ebbinghaus_schema_migrations(version, name, applied_at, backup_path) "
            "VALUES (99, 'from_a_newer_release', 0, '')"
        )
        conn.commit()
    before = read_schema_identity(db_path)

    provider = _open(tmp_path, db_path, "hakua")
    try:
        assert provider.store_backend == "builtin"
        assert db_path.resolve() not in _RecordingStore.opened
    finally:
        provider.shutdown()
    assert read_schema_identity(db_path) == before


def test_pypi_hakua_store_matches_builtin_schema_and_shares_database(tmp_path, monkeypatch):
    hakua_store = pytest.importorskip("hakua_memory.ebbinghaus.store")
    monkeypatch.setattr("tools.lazy_deps.ensure", lambda feature, prompt=True: None)

    assert (
        store_class_schema_identity(hakua_store.EbbinghausMemoryStore)
        == canonical_schema_identity()
    )

    db_path = tmp_path / "memory.db"
    provider = _open(tmp_path, db_path, "hakua")
    assert provider.store_backend == "hakua"
    assert type(provider._store) is hakua_store.EbbinghausMemoryStore  # noqa: SLF001
    _remember(provider, "hakua wrote this")
    provider.shutdown()

    provider = _open(tmp_path, db_path, "builtin")
    assert "hakua wrote this" in _contents(provider)
    _remember(provider, "builtin wrote this")
    provider.shutdown()

    provider = _open(tmp_path, db_path, "hakua")
    assert provider.store_backend == "hakua"
    assert {"hakua wrote this", "builtin wrote this"} <= _contents(provider)
    provider.shutdown()
    assert read_schema_identity(db_path) == canonical_schema_identity()
