"""Ebbinghaus LLM-as-judge: opt-in, read-only on memories, flags go to a separate DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_repo_root = str(Path(__file__).resolve().parents[2])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from plugins.memory.ebbinghaus import EbbinghausMemoryProvider  # noqa: E402
from plugins.memory.ebbinghaus import cli as judge_cli  # noqa: E402
from plugins.memory.ebbinghaus.judge import (  # noqa: E402
    FindingsStore,
    JudgeSettings,
    MemoryJudge,
    goal_status,
    is_goal_like,
)

GOAL = "Goal: ship the uv migration for the Python tooling before Friday."
DONE = "The uv migration for the Python tooling shipped on Thursday."
FACT = "The user prefers uv for Python dependency management and tooling."
CLAIM = "The user prefers pip over uv for Python dependency management."


@pytest.fixture
def provider(tmp_path):
    prov = EbbinghausMemoryProvider({"db_path": str(tmp_path / "memory.db")})
    prov.initialize("judge-test", hermes_home=str(tmp_path))
    ids = {}
    for key, text in {"goal": GOAL, "done": DONE, "fact": FACT, "claim": CLAIM}.items():
        ids[key] = prov._store.remember(text, salience=0.8)["memory_id"]  # noqa: SLF001
    prov.ids = ids
    yield prov
    prov.shutdown()


@pytest.fixture
def findings(tmp_path):
    store = FindingsStore(sqlite3.connect(tmp_path / "judge_findings.db"))
    yield store
    store.close()


def _memories_digest(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM memories ORDER BY memory_id").fetchall()
    finally:
        conn.close()
    return hashlib.sha256(json.dumps(rows, default=repr).encode("utf-8")).hexdigest()


class FakeEvaluator:
    """Stands in for the model: contradicts every reference it is shown plus a bogus id."""

    def __init__(self):
        self.calls = []

    def __call__(self, text, *, criteria, reference_nodes):
        self.calls.append({"text": text, "criteria": criteria, "refs": [r["id"] for r in reference_nodes]})
        support = "supported" if text == GOAL else "contradicted"
        return {
            "verdict": "revise",
            "overall_score": 0.4,
            "criteria": [],
            "claims": [
                {
                    "claim_text": text,
                    "support": support,
                    "evidence_ids": [r["id"] for r in reference_nodes] + ["memory:999999"],
                    "notes": "mock",
                }
            ],
            "suggested_revision": "",
            "confidence": 0.7,
        }


def _judge(provider, findings, *, enabled=True, evaluator=None, max_calls=20):
    return MemoryJudge(
        provider._store,  # noqa: SLF001
        findings,
        JudgeSettings(enabled=enabled, max_calls=max_calls, reference_limit=5, scan_limit=50),
        evaluator=evaluator,
        store_backend=provider.store_backend,
    )


def test_settings_default_to_disabled():
    settings = JudgeSettings.from_plugin_config({})
    assert settings.enabled is False
    assert JudgeSettings.from_plugin_config({"judge_enabled": "true", "judge_max_calls": "3"}).max_calls == 3
    assert JudgeSettings.from_plugin_config({"judge_max_calls": "0"}).max_calls >= 1


def test_goal_detection_and_status_mapping():
    assert is_goal_like({"content": GOAL, "tags": []})
    assert is_goal_like({"content": "misc", "tags": ["todo"]})
    assert not is_goal_like({"content": FACT, "tags": []})
    assert goal_status([{"support": "supported"}]) == "achieved"
    assert goal_status([{"support": "unsupported"}]) == "unachieved"
    assert goal_status([{"support": "supported"}, {"support": "contradicted"}]) == "unachieved"
    assert goal_status([{"support": "uncertain"}]) == "unknown"


def test_estimate_makes_no_model_calls_and_records_nothing(provider, findings, tmp_path):
    evaluator = FakeEvaluator()
    report = _judge(provider, findings, enabled=False, evaluator=evaluator).run(dry_run=True)
    data = report.as_dict()
    assert evaluator.calls == []
    assert data["llm_calls"] == 0
    assert data["candidates"] >= 1
    assert 1 <= data["goal_like_candidates"] <= data["candidates"]
    assert data["planned_calls"] == min(data["candidates"], data["call_budget"])
    assert findings.list_findings() == []


def test_run_refuses_when_disabled(provider, findings):
    with pytest.raises(PermissionError):
        _judge(provider, findings, enabled=False, evaluator=FakeEvaluator()).run(dry_run=False)


def test_run_records_flags_without_touching_memories(provider, findings, tmp_path):
    db_path = tmp_path / "memory.db"
    before = _memories_digest(db_path)
    evaluator = FakeEvaluator()

    report = _judge(provider, findings, evaluator=evaluator).run(dry_run=False)

    assert _memories_digest(db_path) == before
    assert report.calls == len(evaluator.calls) >= 1
    flags = findings.list_findings(limit=200)
    contradictions = [f for f in flags if f["kind"] == "contradiction"]
    assert contradictions, flags
    known_ids = set(provider.ids.values())
    for flag in contradictions:
        assert flag["related_memory_id"] in known_ids
        assert flag["related_memory_id"] != flag["memory_id"]
        assert flag["review_state"] == "open"
    goal_flags = {f["memory_id"]: f["status"] for f in flags if f["kind"] == "goal_status"}
    assert goal_flags.get(provider.ids["goal"]) == "achieved"


def test_budget_caps_model_calls(provider, findings):
    evaluator = FakeEvaluator()
    report = _judge(provider, findings, evaluator=evaluator, max_calls=1).run(dry_run=False)
    assert len(evaluator.calls) == 1
    assert report.candidates >= report.calls == 1


def test_second_run_skips_unchanged_reviewed_memories(provider, findings):
    first = FakeEvaluator()
    _judge(provider, findings, evaluator=first).run(dry_run=False)
    second = FakeEvaluator()
    report = _judge(provider, findings, evaluator=second).run(dry_run=False)
    assert second.calls == []
    assert report.skipped_already_reviewed == len(first.calls)


def test_default_evaluator_uses_hakua_structured_judge(provider, findings):
    pytest.importorskip("hakua_memory.semantic_graph.inference")
    seen = {}

    class _Result:
        def __init__(self, parsed):
            self.parsed = parsed

    class FakeLlm:
        def complete_structured(self, **kwargs):
            seen.update(kwargs)
            return _Result(FakeEvaluator()(GOAL, criteria=[], reference_nodes=[]))

    MemoryJudge(
        provider._store,  # noqa: SLF001
        findings,
        JudgeSettings(enabled=True, max_calls=1),
        llm=FakeLlm(),
    ).run(dry_run=False, memory_ids=[provider.ids["goal"]])

    assert seen["schema_name"] == "semantic_graph.evaluation.v1"
    assert seen["temperature"] == 0.0
    assert "provider" not in seen and "model" not in seen


def test_cli_run_is_blocked_unless_enabled(monkeypatch, capsys):
    monkeypatch.setattr("plugins.memory.ebbinghaus._load_plugin_config", lambda: {"judge_enabled": False})
    args = argparse.Namespace(ebbinghaus_command="judge", run=True, estimate=False, max_calls=None, memory_id=None)
    with pytest.raises(SystemExit) as exc:
        judge_cli.ebbinghaus_command(args)
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)["error"] == "judge disabled"


def test_cli_estimate_reports_counts_only(monkeypatch, capsys, tmp_path):
    db = tmp_path / "cli-memory.db"
    seed = EbbinghausMemoryProvider({"db_path": str(db)})
    seed.initialize("seed", hermes_home=str(tmp_path))
    for text in (GOAL, DONE, FACT):
        seed._store.remember(text)  # noqa: SLF001
    seed.shutdown()
    monkeypatch.setattr("plugins.memory.ebbinghaus._load_plugin_config", lambda: {"db_path": str(db)})
    args = argparse.Namespace(ebbinghaus_command="judge", run=False, estimate=True, max_calls=None, memory_id=None)
    with pytest.raises(SystemExit) as exc:
        judge_cli.ebbinghaus_command(args)
    assert exc.value.code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["dry_run"] is True and payload["llm_calls"] == 0
    for text in (GOAL, DONE, FACT):
        assert text not in out
