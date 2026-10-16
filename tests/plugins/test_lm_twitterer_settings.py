"""Configured memory gates must apply before touching the recall database."""
from __future__ import annotations

import sqlite3
import time
from unittest.mock import Mock

import pytest

from tests.plugins.test_lm_twitterer_plugin import create_ebbinghaus_db, load_plugin, make_settings


@pytest.mark.parametrize("overrides", [{"memory_bridge_enabled": False}, {"memory_recall_limit": 0}])
def test_disabled_recall_does_not_open_existing_database(tmp_path, monkeypatch, overrides):
    core = load_plugin().core
    database = tmp_path / "ebbinghaus_memory.db"
    create_ebbinghaus_db(database)
    # Also make the scoped fallback exist: discarding the supplied settings
    # must not escape detection merely because a different DB is absent.
    monkeypatch.setattr(core, "get_hermes_home", lambda: tmp_path)
    cfg = make_settings(core, tmp_path, memory_db=database, **{
        "memory_bridge_enabled": True, "memory_recall_limit": 5, **overrides,
    })
    connect = Mock(side_effect=AssertionError("disabled recall must not access storage"))
    monkeypatch.setattr(core.sqlite3, "connect", connect)
    assert core._recall_memory_snippets("owned fixture", cfg) == []
    connect.assert_not_called()


def test_configured_recall_limit_applies_to_actual_database_results(tmp_path):
    core = load_plugin().core
    database = tmp_path / "owned.db"
    create_ebbinghaus_db(database)
    now = time.time()
    with sqlite3.connect(database) as connection:
        for n in range(3):
            connection.execute(
                "INSERT INTO memories (content, encoded, cues, tags, salience, strength, source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 0.9, 1.0, 'owned-test', ?, ?)",
                (f"owned fixture note {n}", "owned fixture", "owned,fixture", "test", now, now),
            )
    cfg = make_settings(core, tmp_path, memory_bridge_enabled=True, memory_db=database, memory_recall_limit=1)
    snippets = core._recall_memory_snippets("owned fixture", cfg)
    assert len(snippets) == 1 and "owned fixture note" in snippets[0]
