"""Benchmark the local GGUF scorer on the upstream 324-example holdout.

Reuses upstream nimble's own ``adapt_input``/``assess`` so the numbers are
directly comparable to the README's "90.1% vs 66.4% vs 93.2%" claim, and adds
expected calibration error so probability quality is compared, not just the
top-1 pick.

Run:  NIMBLE_BENCH=1 .venv/Scripts/python.exe -m pytest tests/plugins/test_nimble_benchmark.py -q -s
"""
from __future__ import annotations

import collections
import json
import math
import os
import sys
from pathlib import Path

import pytest

if os.environ.get("NIMBLE_BENCH") != "1":
    pytest.skip("set NIMBLE_BENCH=1 to run the upstream holdout", allow_module_level=True)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from plugins.nimble_scorer import core  # noqa: E402

EVAL_PATH = Path(r"C:\Users\downl\Documents\nimble-src\nimble\data\eval.jsonl")
BASE_URL = os.environ.get("NIMBLE_TEST_BASE_URL", "http://127.0.0.1:8080")

sys.path.insert(0, r"C:\Users\downl\Documents\nimble-src\nimble")
from nimble.evaluation.evaluate_pilot import adapt_input, assess, target_key  # noqa: E402


def _load_rows():
    if not EVAL_PATH.is_file():
        pytest.skip(f"upstream holdout not present at {EVAL_PATH}")
    return [json.loads(line) for line in EVAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _gold_key(probabilities, target, kind):
    """Resolve the gold key the way upstream ``assess`` does.

    ``assess`` compares ``target_key(target, kind)`` against the probability
    keys. For ``noul`` the reference is a Python ``bool`` and ``target_key``
    returns ``str(target).lower()`` = ``"true"``, while a dict keyed by the raw
    choice would produce ``"True"``. Keying our probability map with
    ``choice_key`` (which lowercases bools) makes the two agree.
    """
    gold = target_key(target, kind)
    if gold in probabilities:
        return gold
    for candidate in probabilities:
        if str(candidate).lower() == str(gold).lower():
            return candidate
    raise AssertionError(f"gold {gold!r} absent from {sorted(probabilities)}")


def _renormalized(probabilities):
    """Rescale rounded probabilities so they sum to exactly 1.

    ``score_field`` rounds to 6 decimals for readability; upstream ``assess``
    demands ``isclose(sum, 1, abs_tol=1e-6)``, which rounding can break by
    1e-6. Renormalizing here keeps the grader honest instead of loosening the
    tolerance.
    """
    total = sum(probabilities.values())
    if total <= 0:
        return probabilities
    return {k: v / total for k, v in probabilities.items()}


def _expected_calibration_error(pairs, bins=10):
    """Upstream's ECE: ten equal-width bins over top probability vs correctness."""
    buckets = [[] for _ in range(bins)]
    for top, correct in pairs:
        buckets[min(int(top * bins), bins - 1)].append(correct)
    total = len(pairs)
    if not total:
        return float("nan")
    error = 0.0
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        confidence = sum(bucket) / len(bucket)
        error += (len(bucket) / total) * abs(confidence - _bin_center(index, bins))
    return error


def _bin_center(index, bins):
    return (index + 0.5) / bins


@pytest.mark.skipif(os.environ.get("NIMBLE_BENCH") != "1",
                    reason="set NIMBLE_BENCH=1 to run the 324-example holdout")
def test_holdout_accuracy_and_calibration():
    rows = _load_rows()
    scorer = core.LlamaScorer(BASE_URL)

    per_kind = collections.defaultdict(lambda: {"n": 0, "correct": 0, "nll": 0.0, "brier": 0.0})
    by_domain = collections.defaultdict(lambda: {"n": 0, "correct": 0})
    by_variant = collections.defaultdict(lambda: {"n": 0, "correct": 0})
    ece_pairs = []
    failures = []

    for row in rows:
        context, schema = adapt_input(row["input"])
        decision = row["input"]["questions"]["decision"]
        kind = decision["type"]
        target = row["reference"]["target"]

        result = core.score_field(scorer, context, "decision", schema["decision"])
        graded = assess(_renormalized(result["probabilities"]), target, kind)
        gold = _gold_key(result["probabilities"], target, kind)
        bucket = per_kind[kind]
        bucket["n"] += 1
        bucket["correct"] += int(graded["correct"])
        bucket["nll"] += graded["negative_log_likelihood"]
        bucket["brier"] += graded["multiclass_brier"]
        by_domain[row["domain"]]["n"] += 1
        by_domain[row["domain"]]["correct"] += int(graded["correct"])
        by_variant[row["variant"]]["n"] += 1
        by_variant[row["variant"]]["correct"] += int(graded["correct"])
        ece_pairs.append((graded["top_probability"], int(graded["correct"])))

        if not graded["correct"]:
            failures.append({
                "id": row["id"], "kind": kind, "domain": row["domain"],
                "variant": row["variant"],
                "gold": gold, "pred": str(graded["prediction"]),
                "probs": result["probabilities"],
            })

    total = len(rows)
    correct = sum(b["correct"] for b in per_kind.values())
    report = {
        "model": core.status(BASE_URL).get("model_alias"),
        "n": total,
        "accuracy": round(100 * correct / total, 1),
        "ece": round(_expected_calibration_error(ece_pairs), 4),
        "mean_top_probability": round(sum(p for p, _ in ece_pairs) / total, 4),
        "by_kind": {
            k: {"n": v["n"], "accuracy": round(100 * v["correct"] / v["n"], 1),
                "nll": round(v["nll"] / v["n"], 4), "brier": round(v["brier"] / v["n"], 4)}
            for k, v in sorted(per_kind.items())
        },
        "by_domain": {k: {"n": v["n"], "accuracy": round(100 * v["correct"] / v["n"], 1)}
                      for k, v in sorted(by_domain.items())},
        "by_variant": {k: {"n": v["n"], "accuracy": round(100 * v["correct"] / v["n"], 1)}
                       for k, v in sorted(by_variant.items())},
        "n_failures": len(failures),
        "failures_sample": failures[:12],
    }
    print("\n=== NIMBLE-SCORER / TERNARY-BONSAI-2-27B HOLDOUT ===")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    Path(REPO / "output" / "reports").mkdir(parents=True, exist_ok=True)
    (REPO / "output" / "reports" / "nimble_scorer_holdout.json").write_text(
        json.dumps({**report, "failures": failures}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    assert 0 <= report["accuracy"] <= 100
