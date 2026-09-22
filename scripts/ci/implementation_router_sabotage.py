"""Apply bounded source mutations in disposable copies; never alter the checkout."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path("downstream/implementation_router/kernel.py")
TEST = Path("tests/implementation_router/test_kernel.py")
MUTATIONS = {
    "false_green": ("if not failures:", "if True:"),
    "unbounded_reentry": ("if reentries >= self.policy.planner_reentry_limit:", "if False:"),
    "ignore_total_budget": ("if calls >= self.policy.max_stage_calls:", "if False:"),
    "cross_run_receipt": ("or receipt.run_id != request.binding.run_id", "or False"),
    "cross_workspace_receipt": ("or receipt.workspace_id != request.binding.workspace_id", "or False"),
    "coerce_exit_code": ("or receipt.approved is not True or type(receipt.exit_code) is not int", "or receipt.approved is not True"),
    "ignore_timeout": ("receipt.completed is not True or receipt.timed_out is not False", "receipt.completed is not True"),
    "ignore_writer_completion": ("if response.completed is not True or response.state != \"SUCCEEDED\":", "if response.state != \"SUCCEEDED\":"),
    "skip_checkpoint": ("host.checkpoint(binding, event)", "pass  # sabotage: omit durable checkpoint"),
    "allow_duplicate_json_keys": ("raise _Hold(\"duplicate_json_key\")", "pass  # sabotage: accept overwritten key"),
}


def execute(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/implementation_router", "-q"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )


def main() -> int:
    baseline = execute(ROOT)
    if baseline.returncode != 0:
        print(baseline.stdout + baseline.stderr)
        print("Refusing mutation testing because the unmodified component suite is not green.")
        return 2
    original = (ROOT / MODULE).read_text(encoding="utf-8")
    records = []
    for name, (before, after) in MUTATIONS.items():
        if original.count(before) != 1:
            raise RuntimeError(f"Mutation {name} must match exactly one source location")
        with tempfile.TemporaryDirectory(prefix="hermes-router-sabotage-") as temporary:
            root = Path(temporary)
            (root / MODULE).parent.mkdir(parents=True)
            (root / TEST).parent.mkdir(parents=True)
            (root / MODULE).write_text(original.replace(before, after, 1), encoding="utf-8")
            shutil.copyfile(ROOT / TEST, root / TEST)
            outcome = execute(root)
            # Syntax/import failures do not demonstrate behavioural detection.
            text = outcome.stdout + outcome.stderr
            detected = outcome.returncode == 1 and "FAILED (failures=" in text and "errors=" not in text
            records.append({"mutation": name, "detected": detected, "exit_code": outcome.returncode})
    print(json.dumps({"baseline_passed": True, "mutations": records}, indent=2))
    return 0 if all(row["detected"] for row in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
