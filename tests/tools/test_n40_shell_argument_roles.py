"""Search patterns are non-path values across Windows shell transports."""

import json
import os
import shlex
import subprocess
import sys

import pytest

from tools.environments.local import LocalEnvironment, _find_bash, _windows_to_msys_path
from tools.file_operations import ShellFileOperations


class _SerializedShell:
    is_local = False

    def __init__(self, bash, cwd, env):
        self.bash, self.cwd, self.env = bash, str(cwd), env

    def execute(self, command, *, cwd=None, timeout=30, **kwargs):
        script = json.loads(json.dumps({"command": command}))["command"]
        result = subprocess.run(
            [self.bash, "--noprofile", "--norc", "-s"],
            input=script, cwd=cwd or self.cwd, env=self.env,
            capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )
        return {"output": result.stdout, "returncode": result.returncode}


@pytest.fixture(params=[False, True], ids=["local", "serialized"])
def shell_ops(request, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("HOME", str(home))
    shell_env = {**os.environ, "BASH_ENV": "", "ENV": ""}
    bash = _find_bash()
    backend = (
        _SerializedShell(bash, tmp_path, shell_env)
        if request.param else LocalEnvironment(cwd=str(tmp_path), timeout=30, env=shell_env)
    )
    try:
        yield ShellFileOperations(backend), tmp_path
    finally:
        if isinstance(backend, LocalEnvironment):
            backend.cleanup()


def test_non_path_backslashes_survive_real_shell_transport(shell_ops):
    ops, _ = shell_ops
    values = (
        "", "two words", "quote'and\"quote", "$() ` : ;", "line\nbreak",
        *("a" + "\\" * length + ".b" for length in (1, 2, 3, 4, 8)),
        "a\\'b",
    )
    for value in values:
        quoted = ops._escape_shell_arg(value, translate_path=False)
        result = ops._exec(f"printf '%s' {quoted} | od -An -v -tx1")
        assert result.exit_code == 0, result.stdout
        assert bytes.fromhex(result.stdout) == value.encode("utf-8")


def test_public_grep_search_keeps_literal_regex_escape(shell_ops, monkeypatch):
    ops, root = shell_ops
    (root / "sample.txt").write_text("alpha.beta\nalphaXbeta\n", encoding="utf-8")
    monkeypatch.setattr(ops, "_has_command", lambda command: command == "grep")

    result = ops.search(r"alpha\.beta", path=str(root), target="content")

    assert result.error is None
    assert result.total_count == 1
    assert result.matches[0].content == "alpha.beta"


def test_utf16_rescue_program_keeps_bom_and_newline_escapes(shell_ops):
    ops, root = shell_ops
    source = root / "utf16.txt"
    raw = b"\xfe\xff" + "漢字\r\n".encode("utf-16-be")
    source.write_bytes(raw)
    executed = []
    original_exec = ops._exec

    def capture(command, *args, **kwargs):
        # This PC's python3 resolves to an inert WindowsApps alias. Execute
        # the generated program with the real interpreter through Git Bash.
        if command.startswith("python3 -c "):
            python = shlex.quote(_windows_to_msys_path(sys.executable))
            command = python + command[len("python3"):]
        reply = original_exec(command, *args, **kwargs)
        executed.append((reply.exit_code, reply.stdout))
        return reply

    ops._exec = capture

    result = ops._try_read_utf16(str(source), offset=1, limit=10, file_size=len(raw))

    assert result is not None, executed
    assert "漢字" in result.content
    assert "\ufeff" not in result.content
    assert "\r" not in result.content
    assert result.total_lines == 2
