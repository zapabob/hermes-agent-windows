"""Native path-keyed SessionDB sharing (SR-20260913-003a)."""
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
    # Fail-closed after final release (RuntimeError or None-conn AttributeError).
    with pytest.raises((RuntimeError, AttributeError)):
        db.create_session(session_id="x", source="cli", model="m")
