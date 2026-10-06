"""Adapt existing updater scenario transports to the shared Git owner.

Scenario tests already script subprocess.run, including npm/uv work. Git now
has a separate bounded owner, so explicitly connect that scenario transport to
its call boundary. Unmocked calls retain the real production owner. Policy and
process lifetime tests exercise the real owner separately.
"""
from __future__ import annotations

import subprocess

import pytest

_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def mock_legacy_git_transport(monkeypatch):
    from hermes_cli import banner, update_cmd
    from hermes_cli._subprocess_compat import noninteractive_git_env

    real_update = update_cmd._run_update_git
    real_eol = update_cmd._run_update_eol_git
    real_recovery = update_cmd._run_update_recovery_git
    real_banner = banner._git_run

    def scenario(command, *, cwd=None, check=False, timeout=30, **kwargs):
        kwargs.setdefault("capture_output", True)
        kwargs.setdefault("text", True)
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "replace")
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        kwargs.setdefault("env", noninteractive_git_env())
        result = subprocess.run(command, cwd=cwd, check=check, timeout=timeout, **kwargs)
        if result.returncode in (124, 127) or (check and result.returncode):
            raise update_cmd._UpdateGitExecutionError(
                result.returncode, command, output=result.stdout, stderr=result.stderr)
        return result

    def update(command, **kwargs):
        if subprocess.run is _REAL_RUN:
            return real_update(command, **kwargs)
        return scenario(command, **kwargs)

    def eol(command, **kwargs):
        if subprocess.run is _REAL_RUN:
            return real_eol(command, **kwargs)
        return scenario(command, **kwargs)

    def recovery(command, **kwargs):
        if subprocess.run is _REAL_RUN:
            return real_recovery(command, **kwargs)
        return scenario(command, **kwargs)

    def probe(args, *, cwd=None, timeout=5, text=True, network=False):
        if subprocess.run is _REAL_RUN:
            return real_banner(args, cwd=cwd, timeout=timeout, text=text, network=network)
        return scenario(["git", *args], cwd=cwd, timeout=timeout, text=text)

    monkeypatch.setattr(update_cmd, "_run_update_git", update)
    monkeypatch.setattr(update_cmd, "_run_update_eol_git", eol)
    monkeypatch.setattr(update_cmd, "_run_update_recovery_git", recovery)
    monkeypatch.setattr(banner, "_git_run", probe)
