"""Qualify the component in real linked worktrees at two explicit revisions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def command(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[-3000:]}")
    return result


def git(*args: str) -> str:
    return command(["git", *args], ROOT).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.base_sha):
        parser.error("--base-sha must be an immutable full commit SHA")
    head = git("rev-parse", "HEAD")
    git("cat-file", "-e", f"{args.base_sha}^{{commit}}")
    initial_status = git("status", "--porcelain", "--untracked-files=no")
    temporary = Path(tempfile.mkdtemp(prefix="hermes-router-worktrees-"))
    created: list[Path] = []
    report = {"base_sha": args.base_sha, "candidate_sha": head,
              "platform": platform.platform(), "python": sys.version,
              "scope": "component only; not live-host or whole-repository qualification"}
    try:
        baseline = temporary / "baseline"
        candidate = temporary / "candidate"
        for path, sha in ((baseline, args.base_sha), (candidate, head)):
            git("worktree", "add", "--detach", str(path), sha)
            created.append(path)
            actual = command(["git", "rev-parse", "HEAD"], path).stdout.strip()
            if actual != sha:
                raise RuntimeError("Worktree revision mismatch")
        if (baseline / "downstream/implementation_router/kernel.py").exists():
            raise RuntimeError("RED base already contains the proposed kernel")
        shutil.copytree(ROOT / "tests/implementation_router", baseline / "tests/implementation_router",
                        dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        run_tests = [sys.executable, "-m", "unittest", "discover", "-s", "tests/implementation_router", "-v"]
        red = command(run_tests, baseline, check=False)
        print("=== RED ON FROZEN BASE ===\n" + red.stdout + red.stderr)
        report["red_exit_code"] = red.returncode
        if red.returncode != 1 or "ImplementationRouter contract is not implemented on this base" not in red.stderr or "errors=" in red.stderr:
            raise RuntimeError("RED was not the intended missing-feature failure")
        green = command(run_tests, candidate, check=False)
        print("=== GREEN ON CANDIDATE ===\n" + green.stdout + green.stderr)
        report["green_exit_code"] = green.returncode
        if green.returncode != 0:
            raise RuntimeError("Candidate component tests failed")
        mutations = command([sys.executable, "scripts/ci/implementation_router_sabotage.py"], candidate, check=False)
        print("=== MUTATION RESULTS ===\n" + mutations.stdout + mutations.stderr)
        report["mutation_exit_code"] = mutations.returncode
        if mutations.returncode != 0:
            raise RuntimeError("A selected mutation survived or the mutation run was invalid")
        for relative in ("downstream/implementation_router/kernel.py", "tests/implementation_router/test_kernel.py",
                         "scripts/ci/implementation_router_sabotage.py"):
            report[relative + ":sha256"] = hashlib.sha256((candidate / relative).read_bytes()).hexdigest()
        if git("status", "--porcelain", "--untracked-files=no") != initial_status:
            raise RuntimeError("Primary checkout tracked state changed")
        report["component_passed"] = True
        print("=== QUALIFICATION RECEIPT ===\n" + json.dumps(report, indent=2))
        return 0
    finally:
        for path in reversed(created):
            git("worktree", "remove", "--force", str(path))
        shutil.rmtree(temporary)


if __name__ == "__main__":
    raise SystemExit(main())
