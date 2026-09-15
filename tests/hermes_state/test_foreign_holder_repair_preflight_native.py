"""NC-0213-B: repair preflight refuses when foreign holders are known.

COMPOSE from upstream 12173db / 9b419a2 into the SessionDB owner without
adopting ``hermes_state_holders.py`` as a second lifecycle authority.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hermes_state as hs


def test_live_writer_holds_db_fails_closed_when_foreign_holders_reported(tmp_path, monkeypatch):
    """Holder scan is authoritative: any reported foreign holder blocks repair."""
    db = tmp_path / "state.db"
    db.write_bytes(b"")
    monkeypatch.setattr(hs, "foreign_state_db_holders", lambda _p: [(4242, "other")])
    assert hs._live_writer_holds_db(db) is True


def test_live_writer_holds_db_falls_through_to_lock_probe_when_scan_empty(tmp_path, monkeypatch):
    """Empty scan (Windows default) still uses the EXCLUSIVE lock probe."""
    db = tmp_path / "state.db"
    conn = hs.sqlite3.connect(db)
    conn.execute("CREATE TABLE t(x)")
    conn.commit()
    monkeypatch.setattr(hs, "foreign_state_db_holders", lambda _p: [])
    # Exclusive holder in this process → probe must see busy/locked.
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    conn.execute("BEGIN IMMEDIATE")
    try:
        assert hs._live_writer_holds_db(db) is True
    finally:
        conn.execute("ROLLBACK")
        conn.close()


@pytest.mark.skipif(not hs._IS_WINDOWS, reason="Windows-only empty-scan contract")
def test_windows_foreign_state_db_holders_is_empty(tmp_path):
    assert hs.foreign_state_db_holders(tmp_path / "state.db") == []


def test_canonical_holder_path_uses_realpath(tmp_path):
    """Symlink aliases must compare equal after realpath normalization."""
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink not available: {exc}")
    left = hs._canonical_sqlite_holder_path(str(alias / "state.db"))
    right = hs._canonical_sqlite_holder_path(str(real / "state.db"))
    assert left == right
