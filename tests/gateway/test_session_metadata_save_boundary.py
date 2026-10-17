"""Failed metadata persistence must leave the live session unchanged."""

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionSource, SessionStore


def _store(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions", config=GatewayConfig())
    store._db = None
    entry = store.get_or_create_session(
        SessionSource(platform=Platform.TELEGRAM, chat_id="owned-chat", user_id="owned-user")
    )
    return store, entry


@pytest.mark.parametrize("existing", [False, True], ids=["new-key", "replacement"])
@pytest.mark.parametrize("failure", ["write", "serialization"])
def test_failed_metadata_write_preserves_live_and_durable_state(
    tmp_path, monkeypatch, existing, failure
):
    store, entry = _store(tmp_path)
    if existing:
        assert store.set_session_metadata(entry.session_key, "busy_input_mode", "queue")
    before = dict(entry.metadata)
    activity_before = entry.updated_at
    durable_before = (store.sessions_dir / "sessions.json").read_bytes()
    save_mirror = store._save_sessions_json
    if failure == "write":
        def fail_write(_data):
            raise OSError("simulated owned-store write failure")

        monkeypatch.setattr(store, "_save_sessions_json", fail_write)
        value, error = "steer", OSError
    else:
        value, error = object(), TypeError

    with pytest.raises(error):
        store.set_session_metadata(entry.session_key, "busy_input_mode", value)

    assert entry.metadata == before
    assert store.get_session_metadata(entry.session_key, "busy_input_mode") == before.get("busy_input_mode")
    assert entry.updated_at == activity_before
    assert (store.sessions_dir / "sessions.json").read_bytes() == durable_before
    # Unrelated later saves must not resurrect the rejected update.
    monkeypatch.setattr(store, "_save_sessions_json", save_mirror)
    assert store.set_session_metadata(entry.session_key, "unrelated", "retained")
    fresh = SessionStore(sessions_dir=store.sessions_dir, config=GatewayConfig())
    fresh._db = None
    assert fresh.get_session_metadata(entry.session_key, "busy_input_mode") == before.get("busy_input_mode")
    assert fresh.get_session_metadata(entry.session_key, "unrelated") == "retained"


def test_primary_commit_survives_failed_legacy_mirror(tmp_path, monkeypatch):
    from hermes_state import SessionDB

    store, entry = _store(tmp_path)
    database = SessionDB(db_path=tmp_path / "owned-state.db")
    store._db = database
    activity_before = entry.updated_at

    def fail_mirror(_data):
        raise OSError("simulated legacy mirror failure")

    monkeypatch.setattr(store, "_save_sessions_json", fail_mirror)
    try:
        assert store.set_session_metadata(entry.session_key, "busy_input_mode", "queue")
        assert entry.updated_at == activity_before
        fresh = SessionStore(sessions_dir=store.sessions_dir, config=GatewayConfig())
        fresh._db = database
        assert fresh.get_session_metadata(entry.session_key, "busy_input_mode") == "queue"
        assert entry.metadata == {"busy_input_mode": "queue"}
    finally:
        database.close()
