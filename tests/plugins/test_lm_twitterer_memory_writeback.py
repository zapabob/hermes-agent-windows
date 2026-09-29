"""lm-twitterer must not copy generated posts into the memory store unless config.yaml opts in."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[2] / "plugins" / "lm-twitterer" / "core.py"


@pytest.fixture
def core(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for name in ("LM_TWITTERER_MEMORY_WRITEBACK", "LM_TWITTERER_MEMORY_BRIDGE", "LM_TWITTERER_MEMORY_DB"):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("lm_twitterer_core_writeback_test", _CORE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_env_value", None, raising=False)
    yield module
    sys.modules.pop(spec.name, None)


def _memory_db(path: Path) -> Path:
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE memories (memory_id INTEGER PRIMARY KEY, content TEXT UNIQUE, encoded TEXT, "
            "cues TEXT, tags TEXT, salience REAL, valence REAL, strength REAL, source TEXT, "
            "session_id TEXT, created_at REAL, updated_at REAL)"
        )
    return path


def _rows(path: Path) -> int:
    with sqlite3.connect(path) as con:
        return con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]


def _write_config(home: Path, body: str) -> None:
    (home / "config.yaml").write_text(body, encoding="utf-8")


def test_writeback_is_off_by_default_but_recall_bridge_stays_on(core, tmp_path, monkeypatch):
    db = _memory_db(tmp_path / "ebbinghaus_memory.db")
    monkeypatch.setenv("LM_TWITTERER_MEMORY_DB", str(db))
    _write_config(tmp_path, "plugins:\n  entries:\n    lm-twitterer:\n      allow_tool_override: true\n")
    cfg = core.settings()

    assert cfg.memory_writeback_enabled is False
    assert core._memory_db_path(cfg) == db

    core._remember_generated_post("hello world", cfg, dry_run=False, topic="t")
    assert _rows(db) == 0


def test_writeback_opt_in_via_config_records_the_post(core, tmp_path, monkeypatch):
    db = _memory_db(tmp_path / "ebbinghaus_memory.db")
    monkeypatch.setenv("LM_TWITTERER_MEMORY_DB", str(db))
    _write_config(tmp_path, "plugins:\n  entries:\n    lm-twitterer:\n      memory_writeback: true\n")
    cfg = core.settings()

    assert cfg.memory_writeback_enabled is True
    core._remember_generated_post("hello world", cfg, dry_run=False, topic="t")
    assert _rows(db) == 1


def test_legacy_env_var_does_not_enable_writeback(core, tmp_path, monkeypatch):
    db = _memory_db(tmp_path / "ebbinghaus_memory.db")
    monkeypatch.setenv("LM_TWITTERER_MEMORY_DB", str(db))
    monkeypatch.setenv("LM_TWITTERER_MEMORY_WRITEBACK", "true")
    cfg = core.settings()

    assert cfg.memory_writeback_enabled is False
    core._remember_generated_post("hello world", cfg, dry_run=False, topic="t")
    assert _rows(db) == 0
