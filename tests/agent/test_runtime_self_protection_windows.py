"""The agent cannot delete or overwrite the Python runtime that boots it."""

from __future__ import annotations

import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import file_safety
from tools import approval


@pytest.fixture
def runtime_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    venv = tmp_path / "active; runtime" / ".venv"
    exe_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    exe_dir.mkdir(parents=True)
    exe = exe_dir / ("python.exe" if sys.platform == "win32" else "python")
    exe.write_bytes(b"")

    uv_install = tmp_path / "uv" / "python" / "cpython-3.12.1-windows-x86_64-none"
    base_dir = uv_install / ("Scripts" if sys.platform == "win32" else "bin")
    base_dir.mkdir(parents=True)
    base_exe = base_dir / exe.name
    base_exe.write_bytes(b"")
    (venv / "pyvenv.cfg").write_text(f"home = {base_dir}\n", encoding="utf-8")

    unrelated = tmp_path / "other" / ".venv"
    unrelated.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(sys, "_base_executable", str(base_exe))
    monkeypatch.delenv("HERMES_WRITE_SAFE_ROOT", raising=False)
    return {
        "venv": venv,
        "exe": exe,
        "base_exe": base_exe,
        "uv_install": uv_install,
        "unrelated": unrelated,
    }


@pytest.mark.parametrize("command_name", ["rm", "Remove-Item", "rd", "uv"])
def test_own_runtime_delete_is_unconditionally_blocked(
    runtime_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch, command_name: str,
) -> None:
    venv = runtime_paths["venv"]
    commands = {
        "rm": f'rm -rf "{venv}"',
        "Remove-Item": f'Remove-Item -Recurse -Force "{runtime_paths["exe"]}"',
        "rd": f'rd /s /q "{venv}"',
        "uv": "uv python uninstall 3.12",
    }
    monkeypatch.setattr(approval, "is_current_session_yolo_enabled", lambda: True)
    monkeypatch.setattr(approval, "_get_approval_mode", lambda: "off")
    for guard in (approval.check_dangerous_command, approval.check_all_command_guards):
        decision = guard(commands[command_name], "local")
        assert decision["approved"] is False
        assert decision.get("hardline") is True


def test_file_write_classifier_denies_own_runtime_but_not_other_venv(
    runtime_paths: dict[str, Path],
) -> None:
    for path in (
        runtime_paths["exe"],
        runtime_paths["venv"] / "pyvenv.cfg",
        runtime_paths["base_exe"],
        runtime_paths["uv_install"],
    ):
        assert file_safety.get_write_denied_error(str(path), verb="Delete") is not None
    assert file_safety.get_write_denied_error(str(runtime_paths["unrelated"])) is None


def test_unrelated_venv_delete_stays_manageable(
    runtime_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(approval, "is_current_session_yolo_enabled", lambda: True)
    command = f'rm -rf "{runtime_paths["unrelated"]}"'
    assert approval.check_all_command_guards(command, "local")["approved"] is True


@pytest.mark.parametrize("command", [
    "cmd.exe /c rd /s /q .venv",
    'bash.exe -c "rm -rf .venv"',
    'bash.exe -lc "rm -rf .venv"',
    'sh.exe -c "rm -rf .venv"',
    'powershell.exe -NoProfile -Command "& { Remove-Item -Recurse -Force .venv }"',
    'powershell.exe -NoProfile -Command "&{ Remove-Item -Recurse -Force .venv }"',
    'pwsh.exe -Command ". { Remove-Item -Recurse -Force .venv }"',
    'powershell.exe -NoProfile -Command "& { & { & { Remove-Item -Recurse -Force .venv } } }"',
    "rm -rf .v*",
    'rm -rf ".v"*',
    "rm -rf .v{env,unused}",
])
def test_force_cannot_bypass_runtime_floor_with_session_relative_path(
    runtime_paths: dict[str, Path], command: str,
) -> None:
    from agent.runtime_self_protection import command_deletes_runtime
    from tools.terminal_tool import terminal_tool

    assert command_deletes_runtime(
        command, cwd=str(runtime_paths["venv"].parent)
    ) is not None

    config = {
        "env_type": "local",
        "timeout": 180,
        "cwd": str(runtime_paths["venv"].parent),
        "host_cwd": None,
        "modal_mode": "auto",
        "docker_image": "",
        "singularity_image": "",
        "modal_image": "",
        "daytona_image": "",
    }
    env = MagicMock()
    env.cwd = config["cwd"]
    env.execute.return_value = {"output": "ok", "returncode": 0}
    with ExitStack() as stack:
        stack.enter_context(patch("tools.terminal_tool._get_env_config", return_value=config))
        stack.enter_context(patch("tools.terminal_tool._start_cleanup_thread"))
        stack.enter_context(patch("tools.terminal_tool._active_environments", {"default": env}))
        stack.enter_context(patch("tools.terminal_tool._last_activity", {"default": 0}))
        stack.enter_context(patch("tools.terminal_tool._session_cwd", {}))
        stack.enter_context(patch("tools.terminal_tool._check_all_guards", return_value={"approved": True}))
        stack.enter_context(patch("tools.terminal_tool.get_session_cwd", return_value=None))
        stack.enter_context(patch(
            "downstream.security.execution_gate.preflight_command",
            return_value={"allowed": True, "blocked": [], "warnings": []},
        ))
        result = json.loads(terminal_tool(command=command, force=True))
    assert result.get("status") == "blocked", result
    env.execute.assert_not_called()


@pytest.mark.parametrize("operation", ["delete", "write", "patch", "move"])
def test_file_tools_use_live_terminal_cwd_for_runtime_floor(
    runtime_paths: dict[str, Path], operation: str,
) -> None:
    from tools.file_operations import ShellFileOperations

    env = MagicMock()
    env.cwd = str(runtime_paths["venv"].parent)
    env.execute.return_value = {"output": "", "returncode": 0}
    files = ShellFileOperations(env)
    if operation == "delete":
        result = files.delete_path(".venv", recursive=True)
    elif operation == "write":
        result = files.write_file(".venv/pyvenv.cfg", "replacement")
    elif operation == "patch":
        result = files.patch_replace(".venv/pyvenv.cfg", "home", "other")
    else:
        result = files.move_file(".venv", "elsewhere")
    assert result.error is not None
    env.execute.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows path spellings")
def test_native_windows_and_git_bash_spellings(runtime_paths: dict[str, Path]) -> None:
    from agent.runtime_self_protection import command_deletes_runtime

    exe = runtime_paths["exe"]
    base_exe = runtime_paths["base_exe"]
    drive, tail = os.path.splitdrive(str(exe))
    msys_tail = tail.lstrip("\\").replace("\\", "/")
    msys = f"/{drive[0].lower()}/{msys_tail}"
    commands = (
        f'Remove-Item -LiteralPath "{exe}"',
        f'del {base_exe}',
        f'rm -f "{msys}"',
        f'pwsh.exe -NoProfile -Command "Remove-Item -LiteralPath \'{exe}\'"',
        "uv.exe python uninstall --all",
    )
    for command in commands:
        assert command_deletes_runtime(command) is not None, command
    assert command_deletes_runtime("uv.exe python uninstall 3.9") is None
    assert command_deletes_runtime(f'rm -rf "{runtime_paths["unrelated"]}"') is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive-root spelling")
def test_deleting_runtime_drive_root_counts_as_ancestor(
    runtime_paths: dict[str, Path],
) -> None:
    from agent.runtime_self_protection import is_protected_path

    assert is_protected_path(runtime_paths["exe"].anchor) is not None


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell variable syntax")
def test_powershell_environment_reference_respects_quote_kind(
    runtime_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.runtime_self_protection import command_deletes_runtime

    monkeypatch.setenv("N51_RUNTIME_PARENT", str(runtime_paths["venv"].parent))
    double_quoted = 'Remove-Item -Recurse -Force "$env:N51_RUNTIME_PARENT\\.venv"'
    single_quoted = "Remove-Item -Recurse -Force '$env:N51_RUNTIME_PARENT\\.venv'"
    assert command_deletes_runtime(double_quoted) is not None
    assert command_deletes_runtime(single_quoted) is None


def test_wrapper_and_find_deletes_but_dry_runs_and_other_uv_stay_outside_floor(
    runtime_paths: dict[str, Path],
) -> None:
    from agent.runtime_self_protection import command_deletes_runtime

    venv = runtime_paths["venv"]
    assert command_deletes_runtime(f'env -i rm -rf "{venv}"') is not None
    assert command_deletes_runtime(f'find "{venv}" -exec rm -rf {{}} +') is not None
    assert command_deletes_runtime(f'Remove-Item -WhatIf -LiteralPath "{venv}"') is None
    assert command_deletes_runtime("uv run python uninstall --all") is None


def test_bang_approval_resolves_runtime_relative_to_execution_cwd(
    runtime_paths: dict[str, Path],
) -> None:
    from hermes_cli.bang_shell import check_bang_approval

    with patch("tools.terminal_tool._check_all_guards", return_value={"approved": True}):
        decision = check_bang_approval(
            "rd /s /q .venv", cwd=str(runtime_paths["venv"].parent)
        )
    assert decision["approved"] is False
    assert decision.get("hardline") is True


def test_relative_other_venv_is_not_reclassified_from_process_cwd(
    runtime_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hermes_cli.bang_shell import check_bang_approval
    from tools.file_operations import ShellFileOperations

    monkeypatch.chdir(runtime_paths["venv"].parent)
    monkeypatch.setattr(approval, "is_current_session_yolo_enabled", lambda: True)
    other_cwd = str(runtime_paths["unrelated"].parent)
    command = "rd /s /q .venv"
    assert approval.check_all_command_guards(command, "local", cwd=other_cwd)["approved"] is True
    assert check_bang_approval(command, cwd=other_cwd)["approved"] is True

    env = MagicMock()
    env.cwd = other_cwd
    env.execute.return_value = {"output": "", "returncode": 0}
    result = ShellFileOperations(env).delete_path(".venv", recursive=True)
    assert result.error is None
    env.execute.assert_called()


def test_runtime_glob_does_not_block_an_unrelated_venv(
    runtime_paths: dict[str, Path],
) -> None:
    from agent.runtime_self_protection import command_deletes_runtime

    assert command_deletes_runtime(
        "rm -rf .v*", cwd=str(runtime_paths["unrelated"].parent)
    ) is None
    assert command_deletes_runtime(
        'rm -rf ".v"*', cwd=str(runtime_paths["unrelated"].parent)
    ) is None
    assert command_deletes_runtime(
        "rm -rf .v{env,unused}", cwd=str(runtime_paths["unrelated"].parent)
    ) is None


def test_deep_benign_powershell_block_is_not_classified_as_deletion(
    runtime_paths: dict[str, Path],
) -> None:
    from agent.runtime_self_protection import command_deletes_runtime

    command = 'powershell.exe -Command "& { & { & { Write-Output ready } } }"'
    assert command_deletes_runtime(command, cwd=str(runtime_paths["venv"].parent)) is None


def test_missing_bang_cwd_uses_process_cwd_for_guard_and_never_runs(
    runtime_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli import HermesCLI

    monkeypatch.chdir(runtime_paths["venv"].parent)
    monkeypatch.setattr(approval, "is_current_session_yolo_enabled", lambda: True)
    cli = HermesCLI.__new__(HermesCLI)
    cli.config = {}
    cli.console = MagicMock()
    cli.agent = None
    cli.session_id = "n51-test"
    cli.conversation_history = []
    cli._app = None
    missing_cwd = runtime_paths["venv"].parent / "gone"
    with patch("hermes_cli.bang_shell.resolve_bang_cwd", return_value=str(missing_cwd)), \
         patch("hermes_cli.bang_shell.run_bang_command") as runner:
        assert cli.handle_bang_shell("!rd /s /q .venv") is True
    runner.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell environment syntax")
def test_powershell_inline_environment_assignment_overrides_process_value(
    runtime_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.runtime_self_protection import command_deletes_runtime

    active_parent = runtime_paths["venv"].parent
    other_parent = runtime_paths["unrelated"].parent
    monkeypatch.setenv("N51_RUNTIME_PARENT", str(other_parent))
    delete_active = (
        f'$env:N51_RUNTIME_PARENT = "{active_parent}"; '
        'Remove-Item -Recurse -Force "$env:N51_RUNTIME_PARENT\\.venv"'
    )
    assert command_deletes_runtime(delete_active) is not None

    compact_assignment = (
        f'$env:N51_RUNTIME_PARENT="{active_parent}"; '
        'Remove-Item -Recurse -Force "$env:N51_RUNTIME_PARENT\\.venv"'
    )
    assert command_deletes_runtime(compact_assignment) is not None

    monkeypatch.setenv("N51_RUNTIME_PARENT", str(active_parent))
    delete_other = (
        f'$env:N51_RUNTIME_PARENT = "{other_parent}"; '
        'Remove-Item -Recurse -Force "$env:N51_RUNTIME_PARENT\\.venv"'
    )
    assert command_deletes_runtime(delete_other) is None
