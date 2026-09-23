"""Regression coverage for CI subprocess credential containment."""
import json
import os
import subprocess
import sys

from scripts.ci.isolated_subprocess_env import isolated_subprocess_env


def test_ci_child_and_grandchild_do_not_receive_parent_secret(monkeypatch):
    monkeypatch.setenv("HERMES_TEST_SECRET", "synthetic-secret")
    probe = (
        "import json, os, subprocess, sys; "
        "child = os.environ.get('HERMES_TEST_SECRET'); "
        "grandchild = subprocess.check_output("
        "[sys.executable, '-c', "
        "'import os; print(os.environ.get(\\'HERMES_TEST_SECRET\\', \\'absent\\'))'], "
        "text=True).strip(); "
        "print(json.dumps({'child': child, 'grandchild': grandchild}))"
    )
    with isolated_subprocess_env() as env:
        assert "HERMES_TEST_SECRET" not in env
        result = subprocess.run(
            [sys.executable, "-c", probe], env=env, close_fds=True,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", check=True,
        )
    assert json.loads(result.stdout) == {"child": None, "grandchild": "absent"}
    assert os.environ["HERMES_TEST_SECRET"] == "synthetic-secret"
