"""Real SQLite recall effects through the candidate's existing public owners.

The imported agent fixture mocks only construction/provider/tool discovery.
Dispatch middleware, recall persistence gates, search, and hydration stay real.
"""

import json
import socket
from types import SimpleNamespace

import pytest

from agent.agent_runtime_helpers import invoke_tool
from agent.tool_executor import execute_tool_calls_sequential
from hermes_state import SessionDB
from tests.run_agent.test_run_agent import agent  # noqa: F401
from tools import session_search_tool  # noqa: F401 -- registers the public tool
from tools.registry import registry


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    """Provider construction must never connect outside test-owned SQLite."""
    def denied(*args, **kwargs):
        raise OSError("F10b tests prohibit network connections")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture
def recall_db(tmp_path):
    """Every test owns a native SQLite database and its lifetime."""
    db = SessionDB(tmp_path / "履歴" / "state.db")
    yield db
    db.close()


def seed(db: SessionDB, sid: str, text: str, *, role: str = "user",
         source: str = "cli", timestamp: int = 1700000000,
         active: int = 1, compacted: int = 0) -> int:
    db.create_session(sid, source=source)
    mid = db.append_message(sid, role=role, content=text, timestamp=timestamp)
    # Fixture state uses the real schema, never a fake SQL/search implementation.
    db._conn.execute("UPDATE messages SET active=?, compacted=? WHERE id=?",
                     (active, compacted, mid))
    db._conn.commit()
    return mid


def call_public(db: SessionDB, query: str, **args) -> dict:
    raw = registry.dispatch("session_search", {"query": query, **args},
                            db=db, current_session_id="current-unseeded")
    result = json.loads(raw)
    assert result["success"] is True, result
    return result


def ids(result: dict) -> list[str]:
    return [row["session_id"] for row in result["results"]]


@pytest.mark.parametrize("path", ["registry", "invoke", "sequential"])
def test_total_miss_recovers_through_public_entry(recall_db, agent, path):
    seed(recall_db, "meeting", "Sarah prefers standup scheduled Thursday mornings")
    query = "Sarah standup nonexistentword"
    args = {"query": query, "detail": "full", "limit": 3}
    if path == "registry":
        result = call_public(recall_db, query, detail="full")
    else:
        agent._session_db = recall_db
        agent._owns_session_db = False
        agent.session_id = "current-unseeded"
        if path == "invoke":
            raw = invoke_tool(agent, "session_search", args, "f10b-owned")
        else:
            tool = SimpleNamespace(id="recall-1", type="function",
                                   function=SimpleNamespace(name="session_search",
                                                            arguments=json.dumps(args)))
            messages = []
            execute_tool_calls_sequential(agent, SimpleNamespace(tool_calls=[tool]),
                                          messages, "f10b-owned", finalize=False)
            assert len(messages) == 1
            assert messages[0]["role"] == "tool"
            raw = messages[0]["content"]
        result = json.loads(raw)
        assert result["success"] is True, result
    assert ids(result) == ["meeting"]
    assert result["results"][0]["match_message_id"] > 0
    assert "Thursday" in json.dumps(result["results"], ensure_ascii=False)


def test_exact_hits_keep_ids_rank_and_exclude_partial_matches(recall_db):
    first = seed(recall_db, "dense", "cobalt cobalt cobalt amber")
    second = seed(recall_db, "sparse", "cobalt amber additional unrelated filler words")
    seed(recall_db, "partial", "cobalt only")
    before = recall_db.search_messages("cobalt AND amber")
    assert {r["id"] for r in before} == {first, second}
    result = call_public(recall_db, "cobalt amber", limit=10)
    assert [r["match_message_id"] for r in result["results"]] == [r["id"] for r in before]
    assert "partial" not in ids(result)


def test_explicit_and_relaxes_only_after_total_miss(recall_db):
    seed(recall_db, "cobalt", "cobalt schedule")
    assert ids(call_public(recall_db, "cobalt AND missingtoken")) == ["cobalt"]


@pytest.mark.parametrize("query, expected", [
    ("cobalt OR amber", {"cobalt", "amber", "both"}),
    ("cobalt NOT amber", {"cobalt"}),
    ("cobalt", {"cobalt", "both"}),
    ('"cobalt amber"', {"both"}),
    ('"cobalt missingtoken"', set()),
    ("不存在 萌芽", set()),
    ("站会", {"cjk"}),
    ("zebra xylophone quantum", set()),
])
def test_explicit_boolean_single_phrase_cjk_and_absent_controls(recall_db, query, expected):
    seed(recall_db, "cobalt", "cobalt schedule")
    seed(recall_db, "amber", "amber schedule")
    seed(recall_db, "both", "cobalt amber schedule")
    seed(recall_db, "cjk", "站会 周四")
    assert set(ids(call_public(recall_db, query, limit=10))) == expected


def test_quoted_phrase_is_indivisible_on_relaxation(recall_db):
    seed(recall_db, "phrase", "docker networking verified")
    seed(recall_db, "separated", "docker only then networking")
    assert ids(call_public(recall_db, '"docker networking" missingtoken')) == ["phrase"]


def test_retry_preserves_role_source_withdrawal_and_compaction(recall_db):
    kept = seed(recall_db, "kept", "cobalt retained", role="assistant")
    archived = seed(recall_db, "archived", "cobalt compacted", role="assistant",
                    active=0, compacted=1)
    seed(recall_db, "withdrawn", "cobalt SECRET_WITHDRAWN", role="assistant", active=0)
    seed(recall_db, "other-role", "cobalt wrongrole", role="user")
    seed(recall_db, "other-source", "cobalt wrongsource", role="assistant", source="telegram")
    rows = recall_db.search_messages("cobalt missingtoken", role_filter=["assistant"],
                                     source_filter=["cli"], exclude_sources=["telegram"], limit=20)
    assert {r["id"] for r in rows} == {kept, archived}
    result = call_public(recall_db, "cobalt missingtoken", role_filter="assistant", limit=10)
    assert {"kept", "archived", "other-source"} == set(ids(result))
    assert "SECRET_WITHDRAWN" not in json.dumps(result)
    assert "other-role" not in ids(result)


@pytest.mark.parametrize("sort, expected", [
    ("oldest", ["early", "middle", "late"]),
    ("newest", ["late", "middle", "early"]),
])
def test_relaxed_order_limit_and_offset_are_sql_effects(recall_db, sort, expected):
    mids = {}
    for index, sid in enumerate(["early", "middle", "late"]):
        mids[sid] = seed(recall_db, sid, "cobalt schedule", timestamp=1700000000 + index * 100)
    rows = recall_db.search_messages("cobalt missingtoken", sort=sort, limit=1, offset=1)
    assert [row["id"] for row in rows] == [mids[expected[1]]]
    assert ids(call_public(recall_db, "cobalt missingtoken", sort=sort, limit=2)) == expected[:2]


def test_default_rank_prefers_more_matched_terms_on_total_miss(recall_db):
    seed(recall_db, "coverage", "cobalt amber schedule")
    seed(recall_db, "partial", "cobalt other schedule")
    result = call_public(recall_db, "cobalt amber missingtoken", limit=10)
    assert ids(result) == ["coverage", "partial"]


def test_explicit_tool_role_keeps_exact_search_semantics(recall_db):
    seed(recall_db, "tool", "cobalt machine output", role="tool")
    assert recall_db.search_messages("cobalt", role_filter=["tool"])
    assert recall_db.search_messages("cobalt missingtoken", role_filter=["tool"]) == []


def test_stale_fts_keeps_existing_canonical_like_route(recall_db):
    from hermes_state_common import FTS_STALE_KEY

    seed(recall_db, "canonical", "cobalt retained")
    recall_db._conn.execute("INSERT OR REPLACE INTO state_meta(key, value) VALUES (?, ?)",
                            (FTS_STALE_KEY, "1"))
    recall_db._conn.commit()
    assert recall_db.search_messages("cobalt")
    assert recall_db.search_messages("cobalt missingtoken") == []
