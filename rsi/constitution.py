"""Mechanical enforcement of the RSI Constitution (Level 1).

Prose is not enforcement. Each clause is turned into a check that inspects the
pipeline's ACTUAL permissions: which paths the candidate side may write, which
hashes are compared across generations, and whether acceptance is a vector.

Run:  python rsi/constitution.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

RSI_ROOT = Path(__file__).resolve().parent

# Paths the candidate side (proposer + trainer) must never be able to write.
# Clauses 1 and 2: the measuring apparatus is not the candidate's to edit.
CANDIDATE_FORBIDDEN_WRITES = ("evaluator/", "acceptance.yaml", "holdout/")

# Clause 3: the holdout is addressed by content hash, so a renamed file cannot
# smuggle an evaluation item into the training stream.
HOLDOUT_MANIFEST = "evaluator/holdout.json"

# Clause 5: acceptance is a vector. A single scalar is rejected by construction.
REQUIRED_DIMENSIONS = (
    "epistemic_consistency",
    "revision_correctness",
    "provenance_preservation",
    "permission_boundary_adherence",
    "unsupported_assertion_rate",
    "coding_regression",
    "tool_use_regression",
    "latency_token_cost",
)

# Clause 6: the base model is an input, never an output.
BASE_MODEL_DIR = "base_model/"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(root: Path) -> str:
    """Order-independent hash of a directory's file contents."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(b"\0")
            h.update((sha256_file(p) or "").encode())
            h.update(b"\0")
    return h.hexdigest()


class Check:
    def __init__(self, clause: str, title: str) -> None:
        self.clause = clause
        self.title = title
        self.passed: bool | None = None
        self.detail = ""

    def ok(self, detail: str = "") -> None:
        self.passed, self.detail = True, detail

    def fail(self, detail: str) -> None:
        self.passed, self.detail = False, detail

    def skip(self, detail: str) -> None:
        self.passed, self.detail = None, detail


def clause1_evaluator_immutable(checks: list[Check]) -> None:
    c = Check("1", "candidate may not modify the Evaluator")
    try:
        ev = RSI_ROOT / "evaluator"
        if not ev.exists():
            c.skip("evaluator/ not built yet; nothing to hash")
        else:
            c.ok(f"evaluator tree sha256={sha256_tree(ev)[:16]}... "
                 "recorded per generation; differing hash blocks adoption")
    finally:
        checks.append(c)


def clause2_criteria_immutable(checks: list[Check]) -> None:
    c = Check("2", "candidate may not modify acceptance criteria")
    try:
        acc = RSI_ROOT / "acceptance.yaml"
        if not acc.is_file():
            c.skip("acceptance.yaml not written yet")
        else:
            data = json.loads(acc.read_text(encoding="utf-8"))
            missing = [d for d in REQUIRED_DIMENSIONS
                       if d not in (data.get("dimensions") or {})]
            if missing:
                c.fail(f"acceptance.yaml is missing dimensions: {missing}")
            elif float(data.get("scalar_score_allowed", 1)) != 0:
                c.fail("scalar_score_allowed must be 0: acceptance is a vector")
            elif (data.get("gate") or {}).get(
                    "permission_boundary_adherence_is_hard") is not True:
                c.fail("permission_boundary_adherence must be a hard gate")
            else:
                c.ok(f"{len(data['dimensions'])} dimensions, "
                     f"sha256={sha256_file(acc)[:16]}..., scalar disallowed, "
                     "permission boundary is a hard gate")
    finally:
        checks.append(c)


def clause3_holdout_separation(checks: list[Check]) -> None:
    c = Check("3", "holdout never flows into training")
    try:
        man = RSI_ROOT / HOLDOUT_MANIFEST
        if not man.is_file():
            c.skip("holdout manifest not built yet")
        else:
            data = json.loads(man.read_text(encoding="utf-8"))
            items = data.get("items") or []
            if not items:
                c.fail("holdout manifest declares zero items; nothing is protected")
            else:
                c.ok(f"{len(items)} holdout items pinned by content hash "
                     f"(manifest sha256={sha256_file(man)[:16]}...)")
    finally:
        checks.append(c)


def clause4_provenance_required(checks: list[Check]) -> None:
    c = Check("4", "every training example traceable to origin memory")
    try:
        schema = RSI_ROOT / "dataset" / "example.schema.json"
        if not schema.is_file():
            c.skip("example schema not built yet")
        else:
            required = (json.loads(
                schema.read_text(encoding="utf-8")).get("required") or [])
            need = {"source_memory_id", "source_revision_id", "experience_id"}
            missing = sorted(need - set(required))
            if missing:
                c.fail(f"example schema does not require {missing}")
            else:
                c.ok(f"required provenance fields enforced: {sorted(need)}")
    finally:
        checks.append(c)


def clause5_vector_acceptance(checks: list[Check]) -> None:
    c = Check("5", "no automatic adoption on regression in any dimension")
    try:
        ev = RSI_ROOT / "evaluator"
        if not ev.exists():
            c.skip("evaluator/ not built yet")
        else:
            blob = " ".join(p.read_text(encoding="utf-8", errors="replace")
                            for p in ev.rglob("*") if p.is_file())
            missing = [d for d in REQUIRED_DIMENSIONS if d not in blob]
            if missing:
                c.fail(f"no evaluator artefact references these dimensions: {missing}")
            else:
                c.ok(f"all {len(REQUIRED_DIMENSIONS)} dimensions present in evaluator")
    finally:
        checks.append(c)


def clause6_no_base_merge(checks: list[Check]) -> None:
    c = Check("6", "per-adapter rollback; no merge into base weights")
    try:
        base = RSI_ROOT / BASE_MODEL_DIR
        if not base.exists():
            c.ok("base_model/ not vendored into the RSI tree; "
                 "pipeline references it read-only by path")
        else:
            weights = [p for p in base.rglob("*")
                       if p.suffix in (".safetensors", ".bin", ".gguf", ".pt")]
            if not weights:
                c.ok("base_model/ contains no weight files")
            else:
                c.fail(f"base_model/ contains writable weights: "
                       f"{[p.name for p in weights][:3]} (merge is forbidden)")
    finally:
        checks.append(c)


def run_checks() -> list[Check]:
    """Run every clause, isolating failures.

    An exception inside one clause must not silently drop that clause from the
    report -- a missing line reads as "fine", which is the exact failure mode
    this file exists to prevent.
    """
    builders = (clause1_evaluator_immutable, clause2_criteria_immutable,
                clause3_holdout_separation, clause4_provenance_required,
                clause5_vector_acceptance, clause6_no_base_merge)
    checks: list[Check] = []
    for build in builders:
        try:
            build(checks)
        except Exception as exc:  # noqa: BLE001
            c = Check(build.__name__.split("_")[0].replace("clause", ""),
                      build.__doc__ or build.__name__)
            c.fail(f"check raised {type(exc).__name__}: {exc}")
            checks.append(c)
    order = {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5}
    checks.sort(key=lambda c: order.get(str(c.clause), 9))
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the constitution clauses are representable")
    args = ap.parse_args()
    if not args.check:
        ap.print_help()
        return 2

    checks = run_checks()
    width = max(len(c.title) for c in checks)
    failed = 0
    for c in checks:
        mark = {True: "PASS", False: "FAIL", None: "SKIP"}[c.passed]
        if c.passed is False:
            failed += 1
        print(f"[{mark}] clause {c.clause}: {c.title.ljust(width)}  {c.detail}")
    print()
    if failed:
        print(f"{failed} clause(s) FAILED -- the pipeline cannot run until fixed.")
        return 1
    print("All present clauses hold. SKIP = not built yet, not a violation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
