from __future__ import annotations

import subprocess

import pytest

from hermes_cli import main as hermes_main
from hermes_cli import update_cmd


DOWNSTREAM_HTTPS = "https://github.com/zapabob/hermes-agent-windows.git"
DOWNSTREAM_SSH = "git@github.com:zapabob/hermes-agent-windows.git"


def test_downstream_origin_is_a_managed_distribution_not_a_generic_fork() -> None:
    assert update_cmd._is_fork(DOWNSTREAM_HTTPS) is False
    assert update_cmd._is_fork(DOWNSTREAM_SSH) is False
    assert update_cmd._is_fork("https://github.com/example/hermes-agent.git") is True


def test_downstream_zip_fallback_uses_distribution_archive() -> None:
    assert update_cmd._distribution_archive_url("main") == (
        "https://github.com/zapabob/hermes-agent-windows/archive/refs/heads/main.zip"
    )


def test_downstream_zip_fallback_fails_closed_without_distribution_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "downstream.distribution.update_archive_url",
        lambda _branch: (_ for _ in ()).throw(OSError("missing metadata")),
    )

    with pytest.raises(RuntimeError, match="downstream distribution metadata"):
        update_cmd._distribution_archive_url("main")


def test_downstream_update_check_never_fetches_upstream(
    tmp_path, monkeypatch, capsys
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("hermes_cli.config.detect_install_method", lambda _root: "git")
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(command)
        joined = " ".join(command)
        if "remote get-url origin" in joined:
            return subprocess.CompletedProcess(command, 0, DOWNSTREAM_HTTPS + "\n", "")
        if "remote get-url upstream" in joined or "fetch upstream" in joined:
            raise AssertionError(
                f"downstream update check consulted upstream: {joined}"
            )
        if "rev-parse --is-shallow-repository" in joined:
            return subprocess.CompletedProcess(command, 0, "false\n", "")
        if "rev-list" in joined:
            return subprocess.CompletedProcess(command, 0, "0\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(update_cmd, "_run_update_git", run)
    update_cmd._cmd_update_check()

    assert any("fetch origin main" in " ".join(command) for command in commands)
    assert "Already up to date" in capsys.readouterr().out
