"""Contract tests for local terminal environment persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import sys

import pytest

from tools import terminal_tool
from tools.environments.base import BaseEnvironment
from tools.environments import base as base_module
from tools.environments import local as local_module


class _ConcreteBaseEnvironment(BaseEnvironment):
    def _run_bash(self, cmd_string, *, login=False, timeout=120, stdin_data=None):
        raise AssertionError("wrapper-only test must not start a process")

    def cleanup(self):
        pass


def test_direct_constructors_keep_persistent_snapshot_wrapper_default(monkeypatch, tmp_path):
    env = _ConcreteBaseEnvironment(cwd=".", timeout=30)
    env._snapshot_ready = True

    wrapped = env._wrap_command(":", env.cwd)

    assert "mktemp" in wrapped
    assert "mv -f" in wrapped
    assert env._cwd_marker in wrapped

    monkeypatch.setattr(local_module.LocalEnvironment, "init_session", lambda self: None)
    direct_local = local_module.LocalEnvironment(cwd=str(tmp_path), timeout=30)
    direct_local._snapshot_ready = True
    try:
        local_wrapped = direct_local._wrap_command(":", direct_local.cwd)
        assert "mktemp" in local_wrapped
        assert "mv -f" in local_wrapped
        assert direct_local._cwd_marker in local_wrapped
    finally:
        direct_local.cleanup()


def test_local_factory_defaults_off_and_forwards_explicit_persistence(monkeypatch):
    observed = []

    class CaptureEnvironment:
        def __init__(self, *, cwd, timeout, persist_env=False):
            observed.append((cwd, timeout, persist_env))

    monkeypatch.setattr(terminal_tool, "_LocalEnvironment", CaptureEnvironment)
    configurations = (None, {}, {"persistent": False}, {"persistent": True})
    for local_config in configurations:
        terminal_tool._create_environment(
            "local", "unused", "C:/work", 30, local_config=local_config
        )

    assert observed == [
        ("C:/work", 30, False),
        ("C:/work", 30, False),
        ("C:/work", 30, False),
        ("C:/work", 30, True),
    ]


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows Git Bash")
def test_native_local_persistence_changes_exports_but_keeps_cwd(monkeypatch, tmp_path):
    canary = "U07-FAKE-CREDENTIAL-CANARY"
    monkeypatch.setenv("OPENAI_API_KEY", canary)

    root = Path(__file__).resolve().parents[2]
    assert Path(sys.executable).resolve() == root / ".venv" / "Scripts" / "python.exe"
    modules = {
        "base": Path(base_module.__file__).resolve(),
        "local": Path(local_module.__file__).resolve(),
        "terminal_tool": Path(terminal_tool.__file__).resolve(),
    }
    assert modules["base"] == root / "tools" / "environments" / "base.py"
    assert modules["local"] == root / "tools" / "environments" / "local.py"
    assert modules["terminal_tool"] == root / "tools" / "terminal_tool.py"

    bash = local_module._find_bash()
    assert bash and Path(bash).is_file(), "validated Git Bash executable is unavailable"

    workdir = tmp_path / "日本語 spaced parent"
    child = workdir / "子 cwd"
    child.mkdir(parents=True)
    owned_processes = []
    environments = []
    results = {}
    original_run_bash = local_module.LocalEnvironment._run_bash

    def track_owned_processes(env, *args, **kwargs):
        process = original_run_bash(env, *args, **kwargs)
        owned_processes.append(process)
        return process

    monkeypatch.setattr(
        local_module.LocalEnvironment, "_run_bash", track_owned_processes
    )

    proof_path = tmp_path / "u07-native-proof.json"
    cleanup_errors = []
    try:
        for persist in (False, True):
            env = terminal_tool._create_environment(
                "local",
                "unused",
                str(workdir),
                60,
                local_config={"persistent": persist},
            )
            environments.append(env)
            snapshot = Path(env._snapshot_path)
            assert snapshot.is_file()
            assert canary.encode("utf-8") not in snapshot.read_bytes()

            first = env.execute(
                f"cd -- {shlex.quote(child.name)} && "
                "export U07_PERSISTENCE_MARKER=visible"
            )
            assert first["returncode"] == 0, first
            assert snapshot.is_file()
            assert canary.encode("utf-8") not in snapshot.read_bytes()

            second = env.execute(
                "printf 'U07|%s|%s\\n' "
                '"${U07_PERSISTENCE_MARKER-unset}" "$(pwd -W)"'
            )
            assert second["returncode"] == 0, second
            assert snapshot.is_file()
            assert canary.encode("utf-8") not in snapshot.read_bytes()
            line = next(
                (row.strip() for row in second["output"].splitlines()
                 if row.startswith("U07|")),
                None,
            )
            assert line is not None, second["output"]
            _, marker, actual_cwd = line.split("|", 2)
            assert marker == ("visible" if persist else "unset")
            assert os.path.normcase(os.path.normpath(actual_cwd)) == os.path.normcase(
                os.path.normpath(str(child))
            )
            results[str(persist).lower()] = {
                "marker": marker,
                "cwd": actual_cwd,
                "snapshot_excludes_canary": True,
            }
    finally:
        for env in reversed(environments):
            try:
                env.cleanup()
            except Exception as exc:  # preserve cleanup evidence on RED
                cleanup_errors.append(f"{type(exc).__name__}: {exc}")
        process_states = [
            {
                "pid": process.pid,
                "start_time": getattr(process, "_hermes_start_time", None),
                "returncode": process.poll(),
            }
            for process in owned_processes
        ]
        proof_path.write_text(
            json.dumps(
                {
                    "python": sys.executable,
                    "modules": {name: str(path) for name, path in modules.items()},
                    "bash": bash,
                    "results": results,
                    "owned_processes": process_states,
                    "cleanup_errors": cleanup_errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        assert not cleanup_errors, cleanup_errors
        assert all(state["returncode"] is not None for state in process_states), (
            "fixture-owned terminal process did not complete", process_states
        )
