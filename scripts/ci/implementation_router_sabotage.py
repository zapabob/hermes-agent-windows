"""Mutate disposable component copies; behavioural failures must detect each change."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = Path("downstream/implementation_router")
KERNEL = COMPONENT / "kernel.py"
MUTATIONS = {
    "false_green": (KERNEL, "if not failures:", "if True:"),
    "unbounded_reentry": (KERNEL, "if reentries >= self.policy.planner_reentry_limit:", "if False:"),
    "ignore_total_budget": (KERNEL, "if calls >= self.policy.max_stage_calls:", "if False:"),
    "cross_run_receipt": (KERNEL, "or receipt.run_id != request.binding.run_id", "or False"),
    "cross_workspace_receipt": (KERNEL, "or receipt.workspace_id != request.binding.workspace_id", "or False"),
    "coerce_exit_code": (KERNEL, "or receipt.approved is not True or type(receipt.exit_code) is not int", "or receipt.approved is not True"),
    "ignore_timeout": (KERNEL, "receipt.completed is not True or receipt.timed_out is not False", "receipt.completed is not True"),
    "ignore_writer_completion": (KERNEL, 'if response.completed is not True or response.state != "SUCCEEDED":', 'if response.state != "SUCCEEDED":'),
    "skip_checkpoint": (KERNEL, "host.checkpoint(binding, event)", "pass  # mutation"),
    "allow_duplicate_json_keys": (KERNEL, 'raise _Hold("duplicate_json_key")', "pass  # mutation"),
    "bypass_security_admission": (KERNEL, "validate_admission(receipt, binding.run_id, binding.workspace_id, self.routing)", "pass  # mutation"),
    "skip_stage_revalidation": (KERNEL, "            security_gate()\n            calls += 1", "            calls += 1"),
    "inherit_ambient_credentials": (COMPONENT / "security.py", "    env = {", "    env = {**os.environ,"),
    "ignore_route_binding": (COMPONENT / "security.py", "or receipt.route_fingerprint != routes.fingerprint()", "or False"),
    "truthy_string_enable": (COMPONENT / "routes.py", "if type(enabled) is not bool:", "if False:"),
    "english_only_results": (COMPONENT / "i18n.py", "language = normalise_locale(locale)", 'language = "en"'),
}


def execute(root: Path, pattern: str = "test*.py") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/implementation_router", "-p", pattern, "-q"],
        cwd=root, capture_output=True, text=True, timeout=45,
    )


def main() -> int:
    baseline = execute(ROOT)
    if baseline.returncode != 0:
        print("The unmodified component suite failed; mutation results would be invalid.")
        return 2
    records = []
    for name, (module, before, after) in MUTATIONS.items():
        original = (ROOT / module).read_text(encoding="utf-8")
        if original.count(before) != 1:
            raise RuntimeError(f"Mutation {name} must match exactly one source location")
        with tempfile.TemporaryDirectory(prefix="hermes-router-sabotage-") as temporary:
            root = Path(temporary)
            for path in (COMPONENT, Path("tests/implementation_router"), Path("docs/implementation-router")):
                shutil.copytree(ROOT / path, root / path,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (root / module).write_text(original.replace(before, after, 1), encoding="utf-8")
            pattern = "test_kernel.py"
            if module.name in {"security.py", "routes.py"}:
                pattern = "test_security_contract.py"
            elif module.name == "i18n.py":
                pattern = "test_i18n_docs.py"
            elif name in {"bypass_security_admission", "skip_stage_revalidation"}:
                pattern = "test_route_admission.py"
            try:
                outcome = execute(root, pattern)
            except subprocess.TimeoutExpired:
                records.append({"mutation": name, "detected": False, "failure": "timeout"})
                continue
            # No syntax/import failure counts as detection. Do not print raw
            # output from credential-inheritance mutants, even in CI logs.
            text = outcome.stdout + outcome.stderr
            detected = outcome.returncode == 1 and "FAILED (failures=" in text and "errors=" not in text
            records.append({"mutation": name, "detected": detected, "exit_code": outcome.returncode, "suite": pattern})
    print(json.dumps({"baseline_passed": True, "mutations": records}, indent=2))
    return 0 if all(row["detected"] for row in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
