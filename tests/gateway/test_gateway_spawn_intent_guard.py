"""The test guard must distinguish a gateway process from a future spawn."""

from __future__ import annotations

import subprocess
import sys

import pytest

from gateway.status import (
    _gateway_command_subcommand,
    gateway_spawn_intent_subcommand,
)


def test_inline_restart_watcher_spawn_is_blocked():
    # The inline source is inert. If the guard misses this argv, RED only runs
    # ``pass``; it cannot launch the gateway named in its trailing arguments.
    argv = [
        sys.executable,
        "-c",
        "pass",
        "4242",
        sys.executable,
        "-m",
        "hermes_cli.main",
        "gateway",
        "run",
    ]
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(argv, check=True)


def test_direct_gateway_spawn_is_blocked_before_lookup(tmp_path):
    missing_launcher = tmp_path / "hermes.exe"
    assert not missing_launcher.exists()
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen([str(missing_launcher), "gateway", "run"])


def test_inline_watcher_with_python_option_operand_is_blocked():
    # The separate -X operand must not hide the later -c wrapper.
    argv = [
        sys.executable,
        "-X",
        "utf8",
        "-c",
        "pass",
        "4242",
        sys.executable,
        "-m",
        "hermes_cli.main",
        "gateway",
        "run",
    ]
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(argv, check=True)


def test_spawn_intent_preserves_identity_and_read_only_commands():
    watcher = (
        "python -c pass 4242 python -m hermes_cli.main gateway run"
    )
    assert _gateway_command_subcommand(watcher) is None
    assert gateway_spawn_intent_subcommand(watcher) == "run"
    assert gateway_spawn_intent_subcommand(
        "python -c pass 4242 python -m hermes_cli.main gateway status"
    ) == "status"
    assert gateway_spawn_intent_subcommand("python -c 'gateway run'") is None
    assert gateway_spawn_intent_subcommand(
        "python -c pass 4242 python -m other.main gateway run"
    ) is None
    assert gateway_spawn_intent_subcommand(
        "python stand_in.py -m hermes_cli.main gateway run"
    ) is None
    assert gateway_spawn_intent_subcommand(
        "python -m other.main hermes gateway run"
    ) is None


def test_read_only_gateway_tail_remains_spawnable():
    subprocess.run(
        [sys.executable, "-c", "pass", "4242", sys.executable,
         "-m", "hermes_cli.main", "gateway", "status"],
        check=True,
    )


def test_inline_source_argv_element_is_not_a_future_gateway_command():
    # This is only a Python comment. Joining argv before parsing would split
    # the source into tokens and misread its text as a future gateway argv.
    source = "# hermes_cli.main gateway run"
    subprocess.run([sys.executable, "-c", source], check=True)
    assert gateway_spawn_intent_subcommand([sys.executable, "-c", source]) is None


@pytest.mark.parametrize(
    "command",
    [
        'bash -c "python -c \'pass\' 4242 python -m hermes_cli.main gateway run"',
        'powershell.exe -NoProfile -Command "& python -c \'pass\' 4242 python -m hermes_cli.main gateway run"',
        'bash -c "exec python -c \'pass\' 4242 python -m hermes_cli.main gateway run"',
        'bash -c "timeout 5 python -c \'pass\' 4242 python -m hermes_cli.main gateway run"',
    ],
)
def test_quoted_shell_watcher_spawn_intent_is_visible(command):
    assert gateway_spawn_intent_subcommand(command) == "run"


@pytest.mark.parametrize(
    "shell_name, option, payload",
    [
        ("bash.exe", "-c", "python -c pass 4242 python -m hermes_cli.main gateway run"),
        ("pwsh.exe", "-Command", "python -c pass 4242 python -m hermes_cli.main gateway run"),
        ("bash.exe", "-c", "exec python -c pass 4242 python -m hermes_cli.main gateway run"),
    ],
)
def test_shell_watcher_is_blocked_before_launcher_lookup(tmp_path, shell_name, option, payload):
    missing_shell = tmp_path / shell_name
    assert not missing_shell.exists()
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen([
            str(missing_shell), option,
            payload,
        ])


def test_shell_read_only_remains_allowed_but_ambiguous_runtime_tokens_block():
    assert gateway_spawn_intent_subcommand(
        'bash -c "python -c pass 4242 python -m hermes_cli.main gateway status"'
    ) == "status"
    # The guard cannot prove that an arbitrary shell payload only displays
    # these tokens, so the lifecycle form is conservatively blocked.
    assert gateway_spawn_intent_subcommand(
        'bash -c "echo hermes gateway run"'
    ) == "run"


def test_container_prefix_does_not_exempt_host_shell_tail(tmp_path):
    missing_docker = tmp_path / "docker.exe"
    assert not missing_docker.exists()
    command = (
        f'"{missing_docker}" ps && '
        f'"{sys.executable}" -c pass 4242 python -m hermes_cli.main gateway run'
    )
    # RED cannot reach the later inert Python command: the missing Docker
    # executable fails before ``&&``. GREEN must reject before any shell runs.
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(command, shell=True, check=False)


def test_direct_container_argv_keeps_its_existing_exemption(tmp_path):
    missing_docker = tmp_path / "docker.exe"
    assert not missing_docker.exists()
    with pytest.raises(FileNotFoundError):
        subprocess.Popen([str(missing_docker), "exec", "ci", "hermes", "gateway", "run"])


def test_direct_display_argv_cannot_spawn_a_gateway(tmp_path):
    missing_echo = tmp_path / "echo.exe"
    assert not missing_echo.exists()
    with pytest.raises(FileNotFoundError):
        subprocess.Popen([str(missing_echo), "hermes", "gateway", "run"])


@pytest.mark.parametrize("argv_name", ["echo", "docker"])
def test_executable_override_cannot_borrow_direct_argv_exemption(tmp_path, argv_name):
    missing_launcher = tmp_path / "hermes.exe"
    assert not missing_launcher.exists()
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen([argv_name, "gateway", "run"], executable=str(missing_launcher))


@pytest.mark.parametrize("argv_name", ["echo", "docker"])
def test_positional_executable_override_cannot_borrow_exemption(tmp_path, argv_name):
    missing_launcher = tmp_path / "hermes.exe"
    assert not missing_launcher.exists()
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen([argv_name, "gateway", "run"], -1, str(missing_launcher))


def test_positional_shell_flag_cannot_borrow_direct_container_exemption(tmp_path):
    missing_docker = tmp_path / "docker.exe"
    assert not missing_docker.exists()
    argv = [
        str(missing_docker), "ps", "&&", sys.executable, "-c", "pass",
        "4242", "python", "-m", "hermes_cli.main", "gateway", "run",
    ]
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen(argv, -1, None, None, None, None, None, True, True)
