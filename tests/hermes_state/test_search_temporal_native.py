"""Temporal discovery effects through existing native SQLite/public owners.

Bounds are the frozen U contract; construction doubles come from the existing
agent fixture. No reference-tree imports, inference, or SQL/search mocks.
"""

import json
import socket
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent.agent_runtime_helpers import invoke_tool
from agent.tool_executor import execute_tool_calls_sequential
from hermes_state import SessionDB
from hermes_state_common import FTS_STALE_KEY
from run_agent import AIAgent
from tests.run_agent.test_run_agent import agent  # noqa: F401
from tools import session_search_tool
from tools.registry import registry


def utc(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


LOWER = utc("2026-06-01")
UPPER = utc("2026-07-01")


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise OSError("F10a tests prohibit network connections")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.fixture
def recall_db(tmp_path: Path) -> Iterator[SessionDB]:
    db = SessionDB(tmp_path / "期間履歴" / "state.db")
    yield db
    db.close()


def seed(db: SessionDB, sid: str, started: int, text: str = "modpack temporal evidence", *,
         timestamp: int | None = None, parent: str | None = None, title: str | None = None) -> int:
    kwargs = {"parent_session_id": parent} if parent else {}
    db.create_session(sid, source="cli", **kwargs)
    mid = db.append_message(sid, role="user", content=text,
                            timestamp=timestamp if timestamp is not None else started)
    db._conn.execute("UPDATE sessions SET started_at=? WHERE id=?", (started, sid))
    db._conn.commit()
    if title:
        assert db.set_session_title(sid, title)
    return mid


def public(db: SessionDB, agent: AIAgent, path: str = "registry", **args: Any) -> dict:
    args = {"detail": "full", "limit": 10, **args}
    if path == "registry":
        raw = registry.dispatch("session_search", args, db=db,
                                current_session_id="current-unseeded")
    else:
        agent._session_db = db
        agent._owns_session_db = False
        agent.session_id = "current-unseeded"
        if path == "invoke":
            raw = invoke_tool(agent, "session_search", args, "f10a-owned")
        else:
            call = SimpleNamespace(id="temporal-1", type="function",
                                   function=SimpleNamespace(name="session_search",
                                                            arguments=json.dumps(args)))
            messages = []
            execute_tool_calls_sequential(agent, SimpleNamespace(tool_calls=[call]),
                                          messages, "f10a-owned", finalize=False)
            assert len(messages) == 1
            assert messages[0]["role"] == "tool"
            raw = messages[0]["content"]
    return json.loads(raw)


def ids(result: dict) -> set[str]:
    assert result["success"] is True, result
    return {row["session_id"] for row in result["results"]}


@pytest.mark.parametrize("path", ["registry", "invoke", "sequential"])
def test_public_bounds_use_session_start_with_exact_boundary_effect(recall_db: SessionDB, agent: AIAgent, path: str) -> None:
    # Message timestamps deliberately contradict the session start window.
    seed(recall_db, "too-early", LOWER - 1, timestamp=LOWER + 30)
    seed(recall_db, "at-lower", LOWER, timestamp=UPPER + 30)
    seed(recall_db, "inside", UPPER - 1, timestamp=LOWER - 30)
    seed(recall_db, "at-upper", UPPER, timestamp=LOWER + 30)
    result = public(recall_db, agent, path, query="modpack",
                    after="2026-06-01", before="2026-07-01")
    assert ids(result) == {"at-lower", "inside"}


@pytest.mark.parametrize("after", ["2026-06-01", "2026-06-01T00:00:00",
                                    "2026-06-01T00:00:00Z", "2026-06-01T09:00:00+09:00"])
def test_date_naive_z_and_offset_are_same_utc_effect(recall_db: SessionDB, agent: AIAgent, after: str) -> None:
    seed(recall_db, "before", LOWER - 1)
    seed(recall_db, "equal", LOWER)
    assert ids(public(recall_db, agent, query="modpack", after=after)) == {"equal"}


@pytest.mark.parametrize("bound, expected", [("after", {"equal", "later"}),
                                               ("before", {"older"})])
@pytest.mark.parametrize("value, seconds", [("24h", 86400), ("1d", 86400),
                                            ("2w", 1209600), ("7D", 604800),
                                            (" 3 d ", 259200), ("0h", 0)])
def test_relative_duration_effect_with_owned_clock(recall_db: SessionDB, agent: AIAgent,
                                                  monkeypatch: pytest.MonkeyPatch, bound: str,
                                                  expected: set[str], value: str, seconds: int) -> None:
    now = UPPER
    # Patch the shared standard-library clock, without requiring a new product
    # import merely to construct the RED fixture.
    monkeypatch.setattr(time, "time", lambda: now)
    seed(recall_db, "older", now - seconds - 1)
    seed(recall_db, "equal", now - seconds)
    seed(recall_db, "later", now - seconds + 1)
    assert ids(public(recall_db, agent, query="modpack", **{bound: value})) == expected


@pytest.mark.parametrize("value", ["not-a-date", "7x", "-1d", "1.5h", "2026-02-30"])
@pytest.mark.parametrize("bound", ["after", "before"])
def test_invalid_discovery_bound_returns_error_without_history(recall_db: SessionDB, agent: AIAgent,
                                                              bound: str, value: str) -> None:
    seed(recall_db, "must-not-leak", LOWER)
    result = public(recall_db, agent, query="modpack", **{bound: value})
    assert result["success"] is False
    assert not result.get("results")


def test_reversed_window_is_empty_not_unbounded(recall_db: SessionDB, agent: AIAgent) -> None:
    seed(recall_db, "inside", LOWER + 10)
    assert ids(public(recall_db, agent, query="modpack", after="2026-07-01",
                      before="2026-06-01")) == set()


@pytest.mark.parametrize("value", [None, "", "  "])
def test_blank_bounds_are_unbounded(recall_db: SessionDB, agent: AIAgent, value: str | None) -> None:
    seed(recall_db, "before", LOWER - 1)
    seed(recall_db, "after", UPPER)
    assert ids(public(recall_db, agent, query="modpack", after=value, before=value)) == {"before", "after"}


def test_public_sql_bounds_precede_scan_limit(recall_db: SessionDB, agent: AIAgent,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_search_tool, "_DISCOVER_SCAN_LIMIT", 2)
    for index in range(4):
        seed(recall_db, f"late-{index}", UPPER + index,
             text="modpack modpack modpack modpack", timestamp=UPPER + index)
    seed(recall_db, "eligible", LOWER + 1, text="modpack", timestamp=LOWER + 1)
    assert ids(public(recall_db, agent, query="modpack", sort="newest", limit=5,
                      after="2026-06-01", before="2026-07-01")) == {"eligible"}


@pytest.mark.parametrize("root_start, child_start, expected", [
    (LOWER - 1, LOWER + 1, set()), (LOWER + 1, UPPER + 1, {"child"}),
])
def test_title_window_uses_compression_lineage_root(recall_db: SessionDB, agent: AIAgent,
                                                   root_start: int, child_start: int,
                                                   expected: set[str]) -> None:
    seed(recall_db, "root", root_start, text="neutral ancestor")
    recall_db.end_session("root", "compression")
    seed(recall_db, "child", child_start, text="neutral continuation",
         parent="root", title="TemporalTitle")
    result = public(recall_db, agent, query="TemporalTitle", after="2026-06-01", before="2026-07-01")
    assert ids(result) == expected
    if expected:
        assert result["results"][0]["matched_role"] == "session_title"
        assert result["results"][0]["parent_session_id"] == "root"


@pytest.mark.parametrize("unknown_start", ["", "invalid-start"])
def test_bounded_title_rejects_unknown_real_start_metadata(recall_db: SessionDB, agent: AIAgent,
                                                          unknown_start: str) -> None:
    seed(recall_db, "unknown-start", LOWER, text="neutral history", title="UnknownStartTitle")
    # SQLite's REAL affinity permits nonnumeric legacy metadata. Discovery
    # must keep an unbounded title available and reject it when time-bounded.
    recall_db._conn.execute("UPDATE sessions SET started_at=? WHERE id=?", (unknown_start, "unknown-start"))
    recall_db._conn.commit()
    assert ids(public(recall_db, agent, query="UnknownStartTitle")) == {"unknown-start"}
    assert ids(public(recall_db, agent, query="UnknownStartTitle", after="2026-06-01")) == set()


@pytest.mark.parametrize("mode", ["read", "scroll", "browse"])
def test_read_scroll_browse_precede_invalid_discovery_bounds(recall_db: SessionDB, agent: AIAgent, mode: str) -> None:
    mid = seed(recall_db, "readable", LOWER)
    args = {"session_id": "readable", "query": "modpack"} if mode != "browse" else {}
    if mode == "scroll":
        args["around_message_id"] = mid
    result = public(recall_db, agent, after="invalid", before="invalid", **args)
    assert result["success"] is True, result
    assert result["mode"] == mode
    assert "readable" in json.dumps(result)


@pytest.mark.parametrize("route, query, text", [
    ("latin", "modpack", "modpack evidence"),
    ("or", "modpack missingtoken", "modpack evidence"),
    ("latin-substring", "youer", "修改youer服务端"),
    ("trigram", "cat", "concatenate"),
    ("cjk", "服务端", "修改服务端参数"),
    ("cjk-like", "服务端", "修改服务端参数"),
    ("stale-like", "modpack", "modpack evidence"),
    ("deferred-gap", "modpack", "modpack evidence"),
])
def test_real_search_routes_apply_db_window_before_limit(recall_db: SessionDB, route: str,
                                                        query: str, text: str) -> None:
    for index in range(3):
        seed(recall_db, f"outside-{index}", UPPER + index, text=text, timestamp=UPPER + index)
    eligible = seed(recall_db, "eligible", LOWER + 1, text=text, timestamp=LOWER + 1)
    if route in {"trigram", "cjk-like"}:
        # Select an existing capability fallback; actual SQLite still executes.
        recall_db._fts_cjk_available = False
    if route == "cjk-like":
        recall_db._trigram_available = False
    if route == "stale-like":
        recall_db._conn.execute("INSERT OR REPLACE INTO state_meta(key,value) VALUES (?,?)", (FTS_STALE_KEY, "1"))
        recall_db._conn.commit()
    if route == "deferred-gap":
        # Real derived-index repair state: remove indexed rows and expose the
        # documented pending range. Neither SQL executor nor search is mocked.
        for row in recall_db._conn.execute("SELECT id, content, tool_name, tool_calls FROM messages").fetchall():
            recall_db._conn.execute("INSERT INTO messages_fts(messages_fts,rowid,content,tool_name,tool_calls) VALUES ('delete',?,?,?,?)",
                                    tuple(row))
        for key, value in (("fts_rebuild_progress", "0"), ("fts_rebuild_high_water", str(eligible))):
            recall_db._conn.execute("INSERT OR REPLACE INTO state_meta(key,value) VALUES (?,?)", (key, value))
        recall_db._conn.commit()
    unbounded = recall_db.search_messages(query, sort="newest", limit=1)
    assert unbounded and unbounded[0]["session_id"].startswith("outside-"), (route, unbounded)
    rows = recall_db.search_messages(query, sort="newest", limit=1, after_ts=LOWER, before_ts=UPPER)
    assert [row["id"] for row in rows] == [eligible]
