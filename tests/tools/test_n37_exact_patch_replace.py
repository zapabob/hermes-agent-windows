"""Replace-mode patches must not treat terminal transport noise as file bytes."""

import re
import subprocess

import pytest

from tests.tools.test_n36_exact_patch_source import _GIT_BASH, _NoisyGitBash
from tools.file_operations import ShellFileOperations


class _PatchReadNoise(_NoisyGitBash):
    """Disturb patch reads only; transmit stdin bytes without Windows LF translation."""

    def execute(self, command, *, cwd, **kwargs):
        stdin = kwargs.get("stdin_data")
        result = subprocess.run(
            [str(_GIT_BASH), "-c", command], cwd=cwd,
            capture_output=True,
            input=stdin.encode("utf-8", "surrogateescape") if stdin is not None else None,
            timeout=10, check=False,
        )
        output = (result.stdout + result.stderr).decode("utf-8", "replace")
        patch_read = command.startswith("cat ") or "__HERMES_EXACT_" in command
        if patch_read and self.noise == "outside":
            output = "TERM\n" + output + "TERM\n"
        elif patch_read and self.noise == "inside":
            marker = re.search(r"(?m)^(__HERMES_EXACT_[a-f0-9]+__)\r?$", output)
            output = output.replace(marker.group(0) + "\n", marker.group(0) + "\nTERM", 1) if marker else "TERM\n" + output
        return {"output": output, "returncode": result.returncode}


class _VerifyReadNoise(_PatchReadNoise):
    def __init__(self, cwd, verify_noise):
        super().__init__(cwd, "none")
        self.verify_noise = verify_noise
        self.read_count = 0

    def execute(self, command, *, cwd, **kwargs):
        if command.startswith("cat ") or "__HERMES_EXACT_" in command:
            self.read_count += 1
            self.noise = self.verify_noise if self.read_count >= 2 else "none"
        return super().execute(command, cwd=cwd, **kwargs)


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_replace_excludes_noise_outside_the_source_and_verify_frames(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"anchor\n")
    ops = ShellFileOperations(_PatchReadNoise(tmp_path, "outside"))

    result = ops.patch_replace("source.txt", "anchor", "replacement")

    assert result.error is None
    assert source.read_bytes().replace(b"\r\n", b"\n") == b"replacement\n"


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_replace_refuses_decodable_in_band_noise_before_writing(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"anchor\n")
    ops = ShellFileOperations(_PatchReadNoise(tmp_path, "inside"))

    result = ops.patch_replace("source.txt", "anchor", "replacement")

    assert result.error is not None
    assert source.read_bytes() == b"anchor\n"


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_replace_verifies_bytes_without_transport_noise_after_write(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"anchor\n")

    ops = ShellFileOperations(_VerifyReadNoise(tmp_path, "outside"))

    result = ops.patch_replace("source.txt", "anchor", "replacement")

    assert result.error is None
    assert source.read_bytes().replace(b"\r\n", b"\n") == b"replacement\n"


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_replace_rejects_in_band_noise_in_postwrite_verification(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"anchor\n")
    ops = ShellFileOperations(_VerifyReadNoise(tmp_path, "inside"))

    result = ops.patch_replace("source.txt", "anchor", "replacement")

    assert result.error is not None
    assert "verification failed" in result.error.lower()
    assert source.read_bytes().replace(b"\r\n", b"\n") == b"replacement\n"


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_replace_preserves_untouched_bom_crlf_and_undecodable_byte(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"\xef\xbb\xbfhead\xff\r\nanchor\r\n")
    ops = ShellFileOperations(_PatchReadNoise(tmp_path, "none"))

    result = ops.patch_replace("source.txt", "anchor", "replacement")

    assert result.error is None
    assert source.read_bytes() == b"\xef\xbb\xbfhead\xff\r\nreplacement\r\n"
