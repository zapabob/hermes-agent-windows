from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from scripts.ci.evaluate_required_checks import evaluate_results, main


def test_success_and_conditional_skips_emit_only_result_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("NEEDS", json.dumps({
        "native": {"result": "success", "outputs": {"private": "output-canary"}},
        "conditional": {"result": "skipped"},
    }))
    caplog.set_level(logging.INFO)

    assert main() == 0
    key, payload = output.read_text(encoding="utf-8").strip().split("=", 1)
    assert key == "needs-json"
    assert json.loads(payload) == {"native": "success", "conditional": "skipped"}
    assert "output-canary" not in caplog.text
    assert "output-canary" not in payload


@pytest.mark.parametrize("result", [
    "failure", "cancelled", "abandoned", "timed_out", "action_required", "in_progress",
])
def test_nonpassing_jobs_cannot_make_the_aggregate_green(
    result: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github-output"))
    monkeypatch.setenv("NEEDS", json.dumps({
        "passing": {"result": "success"},
        "required": {"result": result},
    }))

    assert main() == 1


@pytest.mark.parametrize("needs", [{}, [], None, {"required": {}}, {"required": {"result": None}}])
def test_missing_or_malformed_results_fail_closed(needs: object) -> None:
    with pytest.raises(ValueError):
        evaluate_results(needs)


def test_invalid_json_does_not_write_an_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("NEEDS", "not-json")

    assert main() == 1
    assert not output.exists()
