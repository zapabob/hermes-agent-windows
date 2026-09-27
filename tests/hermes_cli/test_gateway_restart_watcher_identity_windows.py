"""A restart watcher's future gateway argv is not its process identity."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

import hermes_cli.gateway as gateway_cli
import hermes_cli.gateway_windows as gateway_windows
from gateway.status import (
    _gateway_command_subcommand,
    _read_process_cmdline,
    looks_like_gateway_command_line,
)
from hermes_cli.update_cmd import _classify_concurrent_instance, _hermes_holder_subcommand


RUN = ["python", "-m", "hermes_cli.main", "gateway", "run"]


def test_actual_restart_watcher_argv_is_not_live_gateway(monkeypatch):
    captured = []
    monkeypatch.setattr(
        gateway_windows,
        "windowless_gateway_restart_spec",
        lambda argv: (argv, "", {}),
    )
    monkeypatch.setattr(
        gateway_cli.subprocess, "Popen", lambda argv, **_kw: captured.append(argv),
    )

    assert gateway_cli.launch_detached_gateway_restart_by_cmdline(14980, RUN)
    assert len(captured) == 1
    watcher = " ".join(captured[0])
    assert captured[0][1] == "-c"
    assert captured[0][-5:] == RUN
    assert _gateway_command_subcommand(watcher) is None
    assert looks_like_gateway_command_line(watcher) is False
    assert _hermes_holder_subcommand(watcher) is None

    actual_gateway = " ".join(RUN)
    assert _gateway_command_subcommand(actual_gateway) == "run"
    assert looks_like_gateway_command_line(actual_gateway) is True
    assert _hermes_holder_subcommand(actual_gateway) == "gateway"


@pytest.mark.parametrize(
    "prefix",
    [
        "python -c print(1)",
        "python -q -c print(1)",
        "python -X utf8 -c print(1)",
        "python -W ignore -c print(1)",
        "python -Q warn -c print(1)",
        "python --check-hash-based-pycs always -c print(1)",
        "python --jit no -c print(1)",
    ],
)
def test_inline_python_source_cannot_lend_its_future_argv_identity(prefix):
    watcher = f"{prefix} 14980 {' '.join(RUN)}"
    assert _gateway_command_subcommand(watcher) is None
    assert looks_like_gateway_command_line(watcher) is False
    assert _hermes_holder_subcommand(watcher) is None


def test_option_operand_named_c_is_not_inline_source():
    running = "python -Xc -m hermes_cli.main gateway run"
    assert _gateway_command_subcommand(running) == "run"
    assert _hermes_holder_subcommand(running) == "gateway"


@pytest.mark.parametrize(
    "executable",
    [
        r'"C:\Program Files\Python\python.exe"',
        r"C:\Program Files\Python\python.exe",
    ],
)
def test_windows_interpreter_path_with_spaces_is_still_inline_source(executable):
    watcher = f"{executable} -c print(1) 14980 {' '.join(RUN)}"
    assert _gateway_command_subcommand(watcher) is None
    assert _hermes_holder_subcommand(watcher) is None


def test_hermes_cli_c_option_is_not_python_inline_source():
    command = "hermes -c mysession gateway run"
    assert _gateway_command_subcommand(command) == "run"
    assert _hermes_holder_subcommand(command) == "gateway"


@pytest.mark.parametrize(
    "python_path",
    [
        r"C:\Hermes - Dev\venv\Scripts\python.exe",
        r"C:\Hermes One Two Three Four Five\venv\Scripts\python.exe",
    ],
)
def test_psutil_argv_with_complex_interpreter_path_is_not_gateway(
    python_path, monkeypatch
):
    argv = [python_path, "-c", "print(1)", "14980", *RUN]
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Process=lambda _pid: SimpleNamespace(cmdline=lambda: argv)),
    )
    # Status and update's process readers receive a real argv list here.
    assert _read_process_cmdline(31415) == subprocess.list2cmdline(argv)
    assert _classify_concurrent_instance(31415) == "non-gateway"


@pytest.mark.parametrize(
    "python_path",
    [
        r"C:\Hermes - Dev\venv\Scripts\python.exe",
        r"C:\Hermes One Two Three Four Five\venv\Scripts\python.exe",
    ],
)
def test_unquoted_windows_command_line_still_rejects_inline_source(python_path):
    argv = [python_path, "-c", "print(1)", "14980", *RUN]
    # Raw Win32_Process CommandLine may also arrive without exe quotes.
    joined = " ".join(argv)
    assert _gateway_command_subcommand(joined) is None
    assert _hermes_holder_subcommand(joined) is None
