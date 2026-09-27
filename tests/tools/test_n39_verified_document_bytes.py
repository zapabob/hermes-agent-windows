"""Document byte reads must return verified file bytes across the terminal."""

import base64
import re
from pathlib import Path

import pytest

from tests.tools.test_n36_exact_patch_source import _GIT_BASH
from tests.tools.test_n37_exact_patch_replace import _PatchReadNoise
from tools.file_operations import ShellFileOperations


class _DocumentBytesGitBash(_PatchReadNoise):
    def __init__(self, cwd: Path, disturbance: str):
        super().__init__(cwd, "none")
        self.disturbance = disturbance
        self.source = cwd / "source.bin"
        self.grew = False

    def execute(self, command, *, cwd, **kwargs):
        is_binary_read = "base64 <" in command
        if is_binary_read and self.disturbance in {"grow", "shrink"} and not self.grew:
            self.source.write_bytes(b"ABCD" if self.disturbance == "grow" else b"ABC")
            self.grew = True
        if is_binary_read and self.disturbance == "missing_base64":
            command = "base64() { return 127; }; " + command
        result = super().execute(command, cwd=cwd, **kwargs)
        if not is_binary_read:
            return result
        output = result["output"]
        if self.disturbance == "outside":
            result["output"] = "AAAA\n" + output
        elif self.disturbance == "inside":
            marker = re.search(r"(?m)^(__HERMES_EXACT_[a-f0-9]+__)\r?$", output)
            result["output"] = (
                output.replace(marker.group(0) + "\n", marker.group(0) + "\nAAAA\n", 1)
                if marker else "AAAA\n" + output
            )
        return result


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_document_bytes_exclude_decodable_noise_outside_frame(tmp_path):
    (tmp_path / "source.bin").write_bytes(b"\x00\x01\x02")
    ops = ShellFileOperations(_DocumentBytesGitBash(tmp_path, "outside"))

    result = ops.read_file_bytes("source.bin")

    assert result.error is None
    assert base64.b64decode(result.base64_content, validate=True) == b"\x00\x01\x02"
    assert result.file_size == 3


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_document_bytes_refuse_decodable_noise_inside_frame(tmp_path):
    (tmp_path / "source.bin").write_bytes(b"\x00\x01\x02")
    ops = ShellFileOperations(_DocumentBytesGitBash(tmp_path, "inside"))

    result = ops.read_file_bytes("source.bin")

    assert result.error is not None
    assert result.base64_content is None


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_document_byte_cap_is_rechecked_after_the_actual_read(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"ABC")
    ops = ShellFileOperations(_DocumentBytesGitBash(tmp_path, "grow"))

    result = ops.read_file_bytes("source.bin", max_bytes=3)

    assert source.read_bytes() == b"ABCD"
    assert result.error is not None
    assert result.base64_content is None


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_document_bytes_report_the_actual_read_size_after_shrink(tmp_path):
    (tmp_path / "source.bin").write_bytes(b"ABCD")
    ops = ShellFileOperations(_DocumentBytesGitBash(tmp_path, "shrink"))

    result = ops.read_file_bytes("source.bin", max_bytes=4)

    assert result.error is None
    assert base64.b64decode(result.base64_content, validate=True) == b"ABC"
    assert result.file_size == 3


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_document_bytes_use_verified_hex_if_base64_is_absent(tmp_path):
    (tmp_path / "source.bin").write_bytes(b"\x00\x01\x02")
    ops = ShellFileOperations(_DocumentBytesGitBash(tmp_path, "missing_base64"))

    result = ops.read_file_bytes("source.bin")

    assert result.error is None
    assert base64.b64decode(result.base64_content, validate=True) == b"\x00\x01\x02"
