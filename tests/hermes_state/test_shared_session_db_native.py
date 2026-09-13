"""Native path-keyed SessionDB sharing (SR-20260913-003a + 003b)."""
from __future__ import annotations

import pytest

import hermes_state_shared as shared


@pytest.fixture(autouse=True)
def _clean_shared():
    shared.close_all()
    yield
    shared.close_all()


def test_same_path_returns_same_instance(tmp_path):
    path = tmp_path / "state.db"
    a = shared.acquire(path)
    b = shared.acquire(path)
    assert a is b
    assert shared.stats()["total_refcounts"] == 2
    a.close()
    assert a._conn is not None
    assert shared.release(b) is True
    assert a._conn is None


def test_close_releases_not_teardown_under_sibling(tmp_path):
    path = tmp_path / "state.db"
    a = shared.acquire(path)
    b = shared.acquire(path)
    a.close()
    assert b._conn is not None
    b.create_session(session_id="s1", source="cli", model="m")
    assert b.get_session("s1") is not None
    b.close()


def test_profile_paths_are_independent(tmp_path):
    a_path = tmp_path / "profiles" / "a" / "state.db"
    b_path = tmp_path / "profiles" / "b" / "state.db"
    a_path.parent.mkdir(parents=True)
    b_path.parent.mkdir(parents=True)
    a = shared.acquire(a_path)
    b = shared.acquire(b_path)
    assert a is not b
    a.create_session(session_id="only-a", source="cli", model="m")
    assert b.get_session("only-a") is None
    shared.close_all()


def test_release_or_close_bare_handle(tmp_path):
    from hermes_state import SessionDB

    bare = SessionDB(db_path=tmp_path / "bare.db")
    assert bare._shared_owned is False
    shared.release_or_close(bare)
    assert bare._conn is None


def test_closed_handle_raises_on_use(tmp_path):
    path = tmp_path / "state.db"
    db = shared.acquire(path)
    shared.release(db)
    assert db._conn is None
    with pytest.raises((RuntimeError, AttributeError)):
        db.create_session(session_id="x", source="cli", model="m")


def test_identity_change_retires_generation_keeps_holders(tmp_path, monkeypatch):
    """SR-003b: known identity change → new callers get a fresh generation;
    prior holders keep a live connection until they release."""
    path = tmp_path / "state.db"
    identities = {(1, 100): True}

    def _fake_identity(p):
        # Stable key so Path resolve differences do not matter.
        return next(iter(identities.keys()))

    monkeypatch.setattr(shared, "stat_db_file_identity", _fake_identity)

    a = shared.acquire(path)
    b = shared.acquire(path)
    assert a is b
    assert shared.stats()["retired_generations"] == 0

    # Simulate snapshot restore / recovery swap.
    identities.clear()
    identities[(1, 200)] = True

    c = shared.acquire(path)
    assert c is not a
    assert shared.stats()["retired_generations"] == 1
    assert shared.stats()["live_paths"] == 1

    # Old holders still have a usable connection object (not closed under them).
    assert a._conn is not None
    assert b._conn is not None
    a.create_session(session_id="old-gen", source="cli", model="m")
    assert a.get_session("old-gen") is not None

    # New generation is a distinct SessionDB instance and accepts writes.
    assert c._conn is not None
    c.create_session(session_id="new-gen", source="cli", model="m")
    assert c.get_session("new-gen") is not None

    assert shared.release(a) is True
    assert a._conn is not None  # b still holds retired gen
    assert shared.release(b) is True
    assert a._conn is None
    assert shared.stats()["retired_generations"] == 0

    assert shared.release(c) is True
    assert c._conn is None
    assert shared.stats()["live_paths"] == 0


def test_unknown_identity_does_not_false_retire(tmp_path, monkeypatch):
    """Windows/network FS often report st_ino=0 → identity None; must not
    retire on every acquire (upstream false-positive guard)."""
    path = tmp_path / "state.db"
    monkeypatch.setattr(shared, "stat_db_file_identity", lambda _p: None)
    a = shared.acquire(path)
    b = shared.acquire(path)
    assert a is b
    assert shared.stats()["retired_generations"] == 0
    shared.close_all()
