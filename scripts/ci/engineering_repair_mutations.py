"""Execute deliberate behavioural mutations in a disposable copy, never the checkout.

Only the named regression files are run. This is not a whole-suite mutation score.
Syntax, import, collection failures and timeouts never count as detection.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MUTATIONS = [('drop_frozen_effort',
  'plugins/implementation_router/configuration.py',
  'ModelRoute(provider.strip(), model.strip(), selected_effort)',
  'ModelRoute(provider.strip(), model.strip())',
  1,
  'tests/plugins/test_engineering_reasoning.py'),
 ('force_all_roles_medium',
  'plugins/implementation_router/actors.py',
  'parse_reasoning_effort(route.reasoning_effort)',
  'parse_reasoning_effort("medium")',
  1,
  'tests/plugins/test_engineering_reasoning.py'),
 ('ignore_effort_only_change',
  'plugins/implementation_router/host.py',
  'if picker_routes(load_config_readonly()).fingerprint() != self.routes.fingerprint():',
  'if False:',
  1,
  'tests/plugins/test_engineering_reasoning.py'),
 ('drop_facade_forwarding',
  'agent/plugin_llm.py',
  '**({"reasoning_config": dict(reasoning_config)} if reasoning_config is not None else {})',
  '**{}',
  8,
  'tests/agent/test_plugin_llm_reasoning.py'),
 ('hide_failed_boundary',
  'agent/engineering_diagnostics.py',
  'report(boundary, failure_code(error))',
  'pass',
  1,
  'tests/plugins/test_engineering_diagnostics.py'),
 ('leak_unknown_error',
  'agent/engineering_diagnostics.py',
  'return "host_error"',
  'return str(error)',
  2,
  'tests/plugins/test_engineering_diagnostics.py'),
 ('lose_durable_error_event',
  'plugins/implementation_router/host.py',
  '"stage_failed", request.attempt_id',
  '"not_a_failure", request.attempt_id',
  1,
  'tests/plugins/test_engineering_diagnostics.py'),
 ('false_success_after_exception',
  'downstream/implementation_router/kernel.py',
  'return result("BLOCKED", "host_boundary_error_no_replay")',
  'return result("SUCCEEDED", "host_boundary_error_no_replay")',
  1,
  'tests/plugins/test_engineering_diagnostics.py')]


def isolated_environment(home: Path, git: str) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    paths = [str(Path(sys.executable).parent), str(Path(git).parent)]
    env = {
        "HOME": str(home), "USERPROFILE": str(home), "HERMES_HOME": str(home / "hermes"),
        "TMP": str(home), "TEMP": str(home), "TMPDIR": str(home),
        "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    if os.name == "nt":
        windows = os.environ["SystemRoot"]
        env["SystemRoot"] = windows
        paths.append(str(Path(windows) / "System32"))
    else:
        paths += ["/usr/bin", "/bin"]
    env["PATH"] = os.pathsep.join(dict.fromkeys(paths))
    return env


def run_tests(root: Path, tests: list[str], env: dict[str, str]):
    launch = (
        "import importlib.util,pathlib,sys; root=pathlib.Path(sys.argv[1]).resolve(); "
        "sys.path.insert(0,str(root)); "
        "spec=importlib.util.find_spec('agent.engineering_diagnostics'); "
        "assert pathlib.Path(spec.origin).resolve().is_relative_to(root), 'foreign source import'; "
        "import pytest; sys.exit(pytest.main(['--noconftest','-q','--tb=short','-o','addopts=']+sys.argv[2:]))"
    )
    return subprocess.run(
        [sys.executable, "-B", "-I", "-c", launch, str(root), *tests],
        cwd=root, env=env, close_fds=True, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )


def main() -> int:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to snapshot the tested source files")
    with tempfile.TemporaryDirectory(prefix="hermes-repair-mutations-") as temporary:
        top = Path(temporary)
        env = isolated_environment(top / "runtime", git)
        tests = sorted({row[5] for row in MUTATIONS})
        baseline = run_tests(ROOT, tests, env)
        if baseline.returncode:
            print(json.dumps({"baseline_passed": False, "exit_code": baseline.returncode}))
            return 2
        files = subprocess.run(
            [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, env=env, close_fds=True, stdin=subprocess.DEVNULL,
            capture_output=True, check=True,
        ).stdout.decode("utf-8").split("\0")
        clone = top / "source"
        clone.mkdir()
        for name in files:
            if not name:
                continue
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError("Unexpected source path")
            source = ROOT / path
            if source.suffix not in {".py", ".yaml", ".yml", ".json", ".toml", ".md", ".txt"}:
                continue
            if source.is_symlink() or not source.is_file():
                continue
            target = clone / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        copy_baseline = run_tests(clone, tests, env)
        if copy_baseline.returncode:
            print(json.dumps({"baseline_passed": True, "copy_baseline_passed": False,
                              "exit_code": copy_baseline.returncode}))
            return 2
        results = []
        for name, relative, before, after, expected_count, test in MUTATIONS:
            target = clone / relative
            original = target.read_text(encoding="utf-8")
            if original.count(before) != expected_count:
                raise RuntimeError(f"Mutation {name} no longer matches its reviewed source")
            changed = original.replace(before, after)
            compile(changed, relative, "exec")
            try:
                target.write_text(changed, encoding="utf-8")
                result = run_tests(clone, [test], env)
                output = result.stdout + result.stderr
                detected = (result.returncode == 1 and " failed" in output
                            and not any(word in output for word in (
                                "ERROR collecting", "SyntaxError", "ModuleNotFoundError",
                                "ImportError while importing", "errors during collection")))
                results.append({"mutation": name, "detected": detected,
                                "exit_code": result.returncode, "test": test})
            except subprocess.TimeoutExpired:
                results.append({"mutation": name, "detected": False, "failure": "timeout"})
            finally:
                target.write_text(original, encoding="utf-8")
        print(json.dumps({"baseline_passed": True, "copy_baseline_passed": True,
                          "mutations": results}, indent=2))
        return 0 if all(item["detected"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
