"""The Windows Git Bash / ASLR probes must not inherit the caller's stdin (#78820).

``local._find_bash`` runs these probes on the first ``LocalEnvironment`` of a
process. Inside the TUI that process is the stdio gateway, whose stdin is the
pipe tui-parent reads JSON-RPC from. A probe started with ``capture_output``
alone inherits that pipe; the MSYS2 runtime then switches the shared pipe to
``PIPE_NOWAIT`` and the gateway's next ``sys.stdin.readline()`` fails with
``OSError: [Errno 22]``. Passing ``stdin=subprocess.DEVNULL`` keeps the
gateway's pipe out of the child entirely.
"""

import subprocess

import pytest

from tools.environments import local as local_mod


@pytest.fixture
def run_calls(monkeypatch):
    """Record every ``subprocess.run`` kwargs dict instead of spawning."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="OFF\n", stderr="")

    monkeypatch.setattr(local_mod.subprocess, "run", fake_run)
    return calls


def test_bash_starts_detaches_stdin(run_calls):
    local_mod._bash_starts_cache.clear()
    local_mod._bash_probe_details_cache.clear()

    assert local_mod._bash_starts(r"C:\Git\bin\bash.exe") is True
    assert len(run_calls) == 1
    argv, kwargs = run_calls[0]
    assert kwargs.get("stdin") is subprocess.DEVNULL


def test_mandatory_aslr_probe_detaches_stdin(run_calls, monkeypatch):
    monkeypatch.setattr(local_mod, "_mandatory_aslr_enabled_cache", None)
    monkeypatch.setattr(local_mod.shutil, "which", lambda _name: "powershell.exe")

    assert local_mod._mandatory_aslr_enabled() is False
    assert len(run_calls) == 1
    argv, kwargs = run_calls[0]
    assert kwargs.get("stdin") is subprocess.DEVNULL
