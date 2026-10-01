"""F10c discovery exclusion effects with owned native SQLite/public tools.

Expected normalization and lineage behavior are frozen from U_TARGET
1a269fcd3b61971bd05e841f80154279dd0a7e65. No reference runtime imports,
search doubles, inference, or network are used.
"""

import inspect
import json
from typing import Any

import pytest

from hermes_state import SessionDB
from run_agent import AIAgent
from tests.hermes_state.test_search_temporal_native import (
    LOWER,
    UPPER,
    agent,  # noqa: F401
    deny_network,  # noqa: F401
    ids,
    public,
    recall_db,  # noqa: F401
    seed,
)
from tools import session_search_tool
from tools.registry import registry


def test_public_optional_exclusion_api_is_present() -> None:
    """Separate missing API evidence from behavioral discovery failures."""
    parameter = inspect.signature(session_search_tool.session_search).parameters.get(
        "exclude_session_ids"
    )
    assert parameter is not None, "missing public exclude_session_ids parameter"
    assert parameter.default is None


@pytest.mark.parametrize("path", ["registry", "invoke", "sequential"])
def test_public_exclusion_removes_only_requested_session(
    recall_db: SessionDB, agent: AIAgent, path: str
) -> None:
    seed(recall_db, "除外済み", LOWER)
    seed(recall_db, "保持する", LOWER + 1)
    assert ids(public(recall_db, agent, path, query="modpack")) == {
        "除外済み", "保持する"
    }
    result = public(recall_db, agent, path, query="modpack",
                    exclude_session_ids=["除外済み"])
    assert ids(result) == {"保持する"}
    assert "除外済み" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("raw", [
    "  除外済み  ", ["", "  除外済み  ", "除外済み", None, 23, False],
    ("\t除外済み\n", "除外済み", " ", 23),
])
def test_string_list_tuple_trim_valid_strings_and_deduplicate(
    recall_db: SessionDB, agent: AIAgent, raw: Any
) -> None:
    seed(recall_db, "除外済み", LOWER)
    seed(recall_db, "23", LOWER + 1)
    assert ids(public(recall_db, agent, query="modpack",
                      exclude_session_ids=raw)) == {"23"}


@pytest.mark.parametrize("raw", [None, "", " ", [], (), 23, False,
                                    {"session_id": "保持する"}, [None, 23, False]])
def test_empty_or_unsupported_exclusion_is_harmless(
    recall_db: SessionDB, agent: AIAgent, raw: Any
) -> None:
    seed(recall_db, "保持する", LOWER)
    assert ids(public(recall_db, agent, query="modpack",
                      exclude_session_ids=raw)) == {"保持する"}


def test_unknown_ids_and_comma_string_do_not_expand_exclusion(
    recall_db: SessionDB, agent: AIAgent
) -> None:
    seed(recall_db, "first", LOWER)
    seed(recall_db, "second", LOWER + 1)
    assert ids(public(recall_db, agent, query="modpack",
                      exclude_session_ids=["missing", "first,second"])) == {
        "first", "second"
    }


@pytest.mark.parametrize("raw_kind", ["list", "tuple"])
def test_cap_is_twenty_unique_valid_ids_not_twenty_raw_items(
    recall_db: SessionDB, agent: AIAgent, raw_kind: str
) -> None:
    # Unknown valid ids count toward the cap. Blank, invalid, and duplicate
    # values do not. The twenty-first unique id must remain discoverable.
    seed(recall_db, "twentieth", LOWER)
    seed(recall_db, "twenty-first", LOWER + 1)
    raw = [None, "", 7, " ", "unknown-0", "unknown-0"]
    raw += [f"unknown-{i}" for i in range(1, 19)]
    raw += [" twentieth ", "twenty-first"]
    if raw_kind == "tuple":
        raw = tuple(raw)
    assert ids(public(recall_db, agent, query="modpack",
                      exclude_session_ids=raw)) == {"twenty-first"}


@pytest.mark.parametrize("exclude", ["root", "middle", "leaf"])
def test_any_compression_lineage_id_excludes_ancestor_and_continuation(
    recall_db: SessionDB, agent: AIAgent, exclude: str
) -> None:
    seed(recall_db, "root", LOWER)
    recall_db.end_session("root", "compression")
    seed(recall_db, "middle", LOWER + 1, parent="root")
    recall_db.end_session("middle", "compression")
    seed(recall_db, "leaf", LOWER + 2, parent="middle")
    seed(recall_db, "independent", LOWER + 3)
    baseline = public(recall_db, agent, query="modpack", sort="oldest")
    assert "root" in ids(baseline), baseline
    assert ids(public(recall_db, agent, query="modpack", sort="oldest",
                      exclude_session_ids=[exclude])) == {"independent"}


@pytest.mark.parametrize("exclude", ["title-root", "title-child"])
def test_title_exclusion_does_not_consume_dedup_limit(
    recall_db: SessionDB, agent: AIAgent, exclude: str
) -> None:
    seed(recall_db, "title-root", LOWER, text="neutral ancestor")
    recall_db.end_session("title-root", "compression")
    seed(recall_db, "title-child", LOWER + 1, text="neutral continuation",
         parent="title-root", title="ExclusionTitle")
    seed(recall_db, "text-hit", LOWER + 2, text="ExclusionTitle real body")
    baseline = public(recall_db, agent, query="ExclusionTitle", limit=1)
    assert ids(baseline) == {"title-child"}
    assert baseline["results"][0]["matched_role"] == "session_title"
    result = public(recall_db, agent, query="ExclusionTitle", limit=1,
                    exclude_session_ids=[exclude])
    assert ids(result) == {"text-hit"}
    assert result["results"][0]["matched_role"] == "user"


def test_fts_exclusion_precedes_result_limit_without_shrinking_scan(
    recall_db: SessionDB, agent: AIAgent
) -> None:
    seed(recall_db, "excluded-newest", UPPER + 10)
    seed(recall_db, "eligible-next", LOWER + 10)
    assert ids(public(recall_db, agent, query="modpack", sort="newest",
                      limit=1)) == {"excluded-newest"}
    assert ids(public(recall_db, agent, query="modpack", sort="newest", limit=1,
                      exclude_session_ids=["excluded-newest"])) == {"eligible-next"}


def test_exclusion_conjoins_existing_time_bounds_and_or_retry(
    recall_db: SessionDB, agent: AIAgent
) -> None:
    seed(recall_db, "outside", UPPER + 1)
    seed(recall_db, "excluded-inside", LOWER + 1)
    seed(recall_db, "eligible-inside", LOWER + 2)
    result = public(recall_db, agent, query="modpack absenttoken",
                    after="2026-06-01", before="2026-07-01",
                    exclude_session_ids=["excluded-inside"])
    assert ids(result) == {"eligible-inside"}


@pytest.mark.parametrize("excluded", [False, True])
def test_current_live_guard_and_compacted_visibility_are_preserved(
    recall_db: SessionDB, agent: AIAgent, excluded: bool
) -> None:
    current = "current-unseeded"
    seed(recall_db, current, LOWER, text="modpack live context")
    archived = recall_db.append_message(current, role="user",
                                        content="modpack compacted evidence")
    recall_db._conn.execute("UPDATE messages SET active=0, compacted=1 WHERE id=?",
                            (archived,))
    recall_db._conn.commit()
    seed(recall_db, "independent", LOWER + 1)
    result = public(recall_db, agent, query="modpack",
                    exclude_session_ids=[current] if excluded else ["unknown"])
    assert ids(result) == ({"independent"} if excluded else {current, "independent"})
    if not excluded:
        row = next(row for row in result["results"] if row["session_id"] == current)
        assert row["match_message_id"] == archived


def test_exclusion_keeps_current_live_and_withdrawn_rows_hidden(
    recall_db: SessionDB, agent: AIAgent
) -> None:
    seed(recall_db, "current-unseeded", LOWER)
    withdrawn = seed(recall_db, "withdrawn", LOWER + 1)
    recall_db._conn.execute("UPDATE messages SET active=0, compacted=0 WHERE id=?",
                            (withdrawn,))
    recall_db._conn.commit()
    seed(recall_db, "independent", LOWER + 2)
    assert ids(public(recall_db, agent, query="modpack",
                      exclude_session_ids=["unknown"])) == {"independent"}


@pytest.mark.parametrize("path", ["registry", "invoke", "sequential"])
@pytest.mark.parametrize("mode", ["read", "scroll", "browse"])
def test_read_scroll_browse_ignore_exclusion_even_of_requested_id(
    recall_db: SessionDB, agent: AIAgent, path: str, mode: str
) -> None:
    mid = seed(recall_db, "readable", LOWER)
    args = {"session_id": "readable", "query": "modpack"} if mode != "browse" else {}
    if mode == "scroll":
        args["around_message_id"] = mid
    result = public(recall_db, agent, path, exclude_session_ids=["readable"], **args)
    assert result["success"] is True, result
    assert result["mode"] == mode
    assert "readable" in json.dumps(result)
