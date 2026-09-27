"""Byte-exact V4A source reads must not persist terminal transport noise."""

import re
import subprocess
from pathlib import Path

import pytest

from tools.file_operations import ShellFileOperations


_GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")


class _NoisyGitBash:
    uses_msys_paths = True

    def __init__(self, cwd: Path, noise: str, *, no_base64: bool = False):
        self.cwd = str(cwd)
        self.noise = noise
        self.no_base64 = no_base64

    def execute(self, command, *, cwd, **_kwargs):
        if self.no_base64:
            command = "base64() { return 127; }; " + command
        result = subprocess.run(
            [str(_GIT_BASH), "-c", command], cwd=cwd,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            input=_kwargs.get("stdin_data"), timeout=10, check=False,
        )
        output = result.stdout + result.stderr
        if command.startswith("cat ") or "base64 <" in command or "od -An" in command:
            if self.noise == "outside":
                output = "TERM\n" + output + "TERM\n"
            elif self.noise == "inside":
                marker = re.search(r"(?m)^(__HERMES_EXACT_[a-f0-9]+__)\r?$", output)
                if marker:
                    first = marker.group(0) + "\n"
                    output = output.replace(first, first + "TERM", 1)
                else:
                    output = "TERM\n" + output
        return {"output": output, "returncode": result.returncode}


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_raw_source_excludes_transport_noise_outside_a_byte_fence(tmp_path):
    (tmp_path / "source.txt").write_bytes(b"anchor\n")
    ops = ShellFileOperations(_NoisyGitBash(tmp_path, "outside"))

    result = ops.read_file_raw("source.txt")

    assert result.error is None
    assert result.content == "anchor\n"


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_v4a_refuses_in_band_decodable_noise_before_a_write(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"anchor\n")
    ops = ShellFileOperations(_NoisyGitBash(tmp_path, "inside"))
    patch = (
        "*** Begin Patch\n"
        "*** Update File: source.txt\n"
        "@@\n"
        "-anchor\n"
        "+replacement\n"
        "*** End Patch"
    )

    result = ops.patch_v4a(patch)

    assert not result.success
    assert source.read_bytes() == b"anchor\n"


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_literal_terminal_marker_bytes_survive_raw_read(tmp_path):
    content = b"before\n__HERMES_FENCE_a9f7b3__\nafter\n"
    (tmp_path / "source.txt").write_bytes(content)
    ops = ShellFileOperations(_NoisyGitBash(tmp_path, "none"))

    result = ops.read_file_raw("source.txt")

    assert result.error is None
    assert result.content.encode("utf-8") == content


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_raw_source_uses_verified_hex_when_base64_is_unavailable(tmp_path):
    content = b"first\nsecond\n"
    (tmp_path / "source.txt").write_bytes(content)
    ops = ShellFileOperations(_NoisyGitBash(tmp_path, "outside", no_base64=True))

    result = ops.read_file_raw("source.txt")

    assert result.error is None
    assert result.content.encode("utf-8") == content
