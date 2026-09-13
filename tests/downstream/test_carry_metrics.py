from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/downstream/carry_metrics.py"
SPEC = importlib.util.spec_from_file_location("carry_metrics", MODULE_PATH)
assert SPEC and SPEC.loader
carry_metrics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = carry_metrics
SPEC.loader.exec_module(carry_metrics)


def test_semantic_coupling_is_policy_driven() -> None:
    carry = {"agent/system_prompt.py"}
    assert carry_metrics.semantic_coupling("agent/system_prompt.py", carry) == 3
    assert carry_metrics.semantic_coupling("agent/runtime.py", carry) == 2
    assert carry_metrics.semantic_coupling("tests/test_runtime.py", carry) == 1
    assert carry_metrics.semantic_coupling(".github/workflows/ci.yml", carry) == 1


def test_generated_reports_are_excluded_from_their_own_totals() -> None:
    assert "_docs/carry-surface-20260826.json" in carry_metrics.EXCLUDED
    assert "_docs/carry-surface-20260826.md" in carry_metrics.EXCLUDED
    assert carry_metrics.is_excluded("_docs/carry-surface-20260826.json")
    assert carry_metrics.is_excluded("_docs/2026-09-13_impl-log_Cursor.md")
    assert not carry_metrics.is_excluded("agent/system_prompt.py")


def test_definitions_document_committed_head_and_docs_exclusion() -> None:
    """HEAD-based diff + `_docs/` exclusion without needing upstream objects.

    The Python tests CI job checks out with default depth=1, so calculate()'s
    `git ls-tree <upstream_sha>` exits 128. Tier-1 fork-cicd (fetch-depth: 0)
    already exercises calculate() / --check; this unit test pins the contracts
    that keep those checks CI-stable.
    """
    definitions = carry_metrics.report_definitions()
    assert "committed HEAD" in definitions["loc"]
    assert "_docs/" in definitions["excluded_prefixes"]
    # calculate() drops excluded paths before totals; assert the same filter.
    assert carry_metrics.is_excluded("_docs/2026-09-13_impl-log_Cursor.md")
    assert not carry_metrics.is_excluded("agent/system_prompt.py")
