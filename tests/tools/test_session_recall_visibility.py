"""Model-facing recall excludes withdrawn rows while retaining archived history."""
import json

import pytest

from hermes_state import SessionDB
from tools import session_search_tool  # noqa: F401 -- public registry owner
from tools.registry import registry


@pytest.fixture
def db(tmp_path):
    owned = SessionDB(tmp_path / "日本語履歴" / "state.db")
    owned.create_session("history", source="cli")
    yield owned
    owned.close()


def append(db, content, *, active=1, compacted=0):
    mid = db.append_message("history", role="user", content=content)
    db._conn.execute("UPDATE messages SET active=?, compacted=? WHERE id=?",
                     (active, compacted, mid))
    db._conn.commit()
    return mid


def public(db, **args):
    return json.loads(registry.dispatch("session_search", args, db=db,
                                       current_session_id="unseeded-current"))


def test_exact_discovery_hydration_excludes_withdrawn_window_and_bookends(db):
    head = append(db, "Permitted archived opening", active=0, compacted=1)
    append(db, "SECRET_WITHDRAWN_HEAD", active=0)
    for index in range(10):
        append(db, f"Permitted before {index}")
        append(db, f"SECRET_WITHDRAWN_BEFORE_{index}", active=0)
    anchor = append(db, "visibleanchor archived fact", active=0, compacted=1)
    for index in range(10):
        append(db, f"SECRET_WITHDRAWN_AFTER_{index}", active=0)
        append(db, f"Permitted after {index}")
    append(db, "SECRET_WITHDRAWN_TAIL", active=0)
    tail = append(db, "Permitted archived closing", active=0, compacted=1)

    result = public(db, query="visibleanchor", detail="full")
    assert result["success"] and result["count"] == 1
    row = result["results"][0]
    assert row["match_message_id"] == anchor
    assert any(message["id"] == head for message in row["bookend_start"])
    assert any(message["id"] == tail for message in row["bookend_end"])
    assert "SECRET_WITHDRAWN" not in json.dumps(result["results"])
    assert row["messages_before"] == row["messages_after"] == 5


def test_scroll_filters_before_limit_and_preserves_archived_rows(db):
    earlier = append(db, "Earlier archived fact", active=0, compacted=1)
    for index in range(6):
        append(db, f"SECRET_WITHDRAWN_PRE_{index}", active=0)
    anchor = append(db, "Visible middle")
    for index in range(6):
        append(db, f"SECRET_WITHDRAWN_POST_{index}", active=0)
    later = append(db, "Later active fact")

    result = public(db, session_id="history", around_message_id=anchor, window=1)
    assert result["success"], result
    assert [message["id"] for message in result["messages"]] == [earlier, anchor, later]
    assert "SECRET_WITHDRAWN" not in json.dumps(result)
    assert result["messages_before"] == result["messages_after"] == 1


def test_scroll_rejects_withdrawn_anchor(db):
    anchor = append(db, "SECRET_WITHDRAWN_ANCHOR", active=0)
    append(db, "Visible neighbor")
    result = public(db, session_id="history", around_message_id=anchor)
    assert result["success"] is False
    assert "SECRET_WITHDRAWN_ANCHOR" not in json.dumps(result)


def test_default_primitive_retains_explicit_audit_history(db):
    before = append(db, "SECRET_WITHDRAWN_AUDIT", active=0)
    anchor = append(db, "Visible anchor")
    raw = db.get_messages_around("history", anchor, window=1)
    assert [message["id"] for message in raw["window"]] == [before, anchor]
    assert "SECRET_WITHDRAWN_AUDIT" in json.dumps(raw)
