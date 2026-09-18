"""Isolated validation only; never loaded by Hermes or included in the final patch."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

PR = "17d1c7671758265562c8522c3e15ee55677ce693"
MAIN = "d177b119e9c56c9ddc0b7379ffce52341ec06584"
BASE = "ad03f20dd61919ca2135d6904e787a94284aacaf"
TEST = "tests/tools/test_exec_code_guard_hermes_home.py"
SUITES = ["tests/tools/test_exec_code_guard.py", "tests/tools/test_exec_code_guard_adversarial.py", "tests/tools/test_approval.py"]
ROOT = Path.cwd()
OUT = Path(os.environ["RUNNER_TEMP"]) / "pr65592-evidence"
OUT.mkdir(exist_ok=True)
HARNESS = Path(__file__).resolve().parent
ENV = os.environ.copy()
ENV.update(GIT_AUTHOR_NAME="github-actions[bot]", GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com", GIT_COMMITTER_NAME="github-actions[bot]", GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")


def run(*args, check=True):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=ENV)
    print(result.stdout, flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args!r}")
    return result


def pytest(label, paths, selection=None):
    xml = OUT / f"{label}.xml"
    args = [sys.executable, "-m", "pytest", *paths, "-q", "--tb=short", f"--junitxml={xml}"]
    if selection:
        args.extend(["-k", selection])
    result = run(*args, check=False)
    (OUT / f"{label}.txt").write_text(result.stdout, encoding="utf-8")
    if not xml.exists():
        raise RuntimeError(f"{label}: no JUnit evidence")
    cases = list(ET.parse(xml).getroot().iter("testcase"))
    failures = sorted(f"{c.get('classname')}::{c.get('name')}" for c in cases if c.find("failure") is not None)
    errors = sorted(f"{c.get('classname')}::{c.get('name')}" for c in cases if c.find("error") is not None)
    skipped = sum(c.find("skipped") is not None for c in cases)
    stats = dict(exit_code=result.returncode, tests=len(cases), passed=len(cases)-len(failures)-len(errors)-skipped, failures=failures, errors=errors, skipped=skipped)
    (OUT / f"{label}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def main():
    # Keep inputs outside the checkout before composing the exact integration tree.
    new_test = (HARNESS / "test_exec_code_guard_hermes_home.py").read_text(encoding="utf-8")
    patch = (HARNESS / "production.patch").read_text(encoding="utf-8")
    (OUT / "production.patch").write_text(patch, encoding="utf-8")
    run("git", "remote", "add", "upstream", "https://github.com/NousResearch/hermes-agent.git")
    run("git", "fetch", "--no-tags", "--depth=1", "upstream", PR, MAIN, BASE)
    merge = run("git", "merge-tree", "--write-tree", f"--merge-base={BASE}", PR, MAIN, check=False)
    (OUT / "merge-tree.txt").write_text(merge.stdout, encoding="utf-8")
    if merge.returncode:
        raise RuntimeError("Current-main integration conflicts: do not resolve unrelated PR scope")
    tree = merge.stdout.splitlines()[0].strip()
    merged = run("git", "commit-tree", tree, "-p", PR, "-p", MAIN, "-m", "Merge pinned current main for isolated PR #65592 Windows-home validation").stdout.strip()
    run("git", "checkout", "--detach", merged)
    run(sys.executable, "-m", "pip", "install", "-e", ".[dev]")
    baseline = pytest("baseline", SUITES)
    if baseline["exit_code"] not in (0, 1) or baseline["errors"]:
        raise RuntimeError("Baseline could not execute; do not claim regression evidence")
    Path(TEST).write_text(new_test, encoding="utf-8")
    red = pytest("red", [TEST], "candidates")
    if red["exit_code"] != 1 or len(red["failures"]) != 7 or red["passed"] != 3 or red["errors"]:
        raise RuntimeError("RED did not reproduce the seven missing-root assertion failures")
    run("git", "apply", "--check", str(OUT / "production.patch"))
    run("git", "apply", str(OUT / "production.patch"))
    green = pytest("green", [TEST])
    if green["exit_code"] != 0 or green["passed"] != 34 or green["skipped"]:
        raise RuntimeError("The complete 34-case regression must pass without skips")
    regression = pytest("regression", SUITES)
    if regression["exit_code"] not in (0, 1) or regression["errors"] or regression["failures"] != baseline["failures"] or regression["tests"] != baseline["tests"]:
        raise RuntimeError("Existing-suite outcomes changed; do not publish")
    run("git", "add", "--", "tools/exec_code_policy.py", TEST)
    changed = run("git", "diff", "--cached", "--name-only").stdout.splitlines()
    if set(changed) != {"tools/exec_code_policy.py", TEST}:
        raise RuntimeError(f"Scope drift: {changed}")
    run("git", "diff", "--cached", "--check")
    run("git", "commit", "-m", "fix(approval): resolve native and active Hermes homes per call", "-m", "Address KeyArgo's Windows-default-home observation on NousResearch/hermes-agent#65592 only. Retain explicit and legacy roots, preserve boundary policy, and add 34 per-call/path/guard regressions. No runtime-computed-target or approval-policy expansion.")
    tip = run("git", "rev-parse", "HEAD").stdout.strip()
    (OUT / "tip.txt").write_text(tip+"\n", encoding="utf-8")
    (OUT / "integration.txt").write_text(merged+"\n", encoding="utf-8")
    diff = run("git", "show", "--format=fuller", "--binary", tip).stdout
    (OUT / "fix.patch").write_text(diff, encoding="utf-8")
    run("git", "bundle", "create", str(OUT / "candidate.bundle"), "HEAD", f"^{PR}", f"^{MAIN}")
    (OUT / "report.json").write_text(json.dumps(dict(pr=PR, main=MAIN, integration=merged, tip=tip, baseline=baseline, red=red, green=green, regression=regression), indent=2), encoding="utf-8")
    shutil.copy2(TEST, OUT / Path(TEST).name)


if __name__ == "__main__":
    main()
