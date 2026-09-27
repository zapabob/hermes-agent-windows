"""Binary-admission samples must come from file bytes, not terminal noise."""

import re

import pytest

from tests.tools.test_n36_exact_patch_source import _GIT_BASH
from tests.tools.test_n37_exact_patch_replace import _PatchReadNoise
from tools.file_operations import ShellFileOperations, _SampleIntegrityError


class _SampleNoiseGitBash(_PatchReadNoise):
    def __init__(self, cwd, sample_noise):
        super().__init__(cwd, "none")
        self.sample_noise = sample_noise

    def execute(self, command, *, cwd, **kwargs):
        if self.sample_noise == "missing_base64" and "head -c " in command and "| base64" in command:
            command = "base64() { return 127; }; " + command
        result = super().execute(command, cwd=cwd, **kwargs)
        if "head -c " not in command or "| base64" not in command:
            return result
        output = result["output"]
        if self.sample_noise == "outside":
            result["output"] = "AAAA\n" + output
        elif self.sample_noise == "inside":
            marker = re.search(r"(?m)^(__HERMES_EXACT_[a-f0-9]+__)\r?$", output)
            result["output"] = (
                output.replace(marker.group(0) + "\n", marker.group(0) + "\nAAAA\n", 1)
                if marker else "AAAA\n" + output
            )
        return result


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_raw_reader_does_not_reclassify_text_from_noise_outside_sample(tmp_path):
    (tmp_path / "source.txt").write_bytes(b"anchor\n")
    ops = ShellFileOperations(_SampleNoiseGitBash(tmp_path, "outside"))

    assert ops._sample_file_bytes("source.txt") == b"anchor\n"
    result = ops.read_file_raw("source.txt")

    assert result.error is None
    assert not result.is_binary
    assert result.content == "anchor\n"


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_in_band_decodable_sample_noise_is_not_accepted_as_file_bytes(tmp_path):
    (tmp_path / "source.txt").write_bytes(b"anchor\n")
    ops = ShellFileOperations(_SampleNoiseGitBash(tmp_path, "inside"))

    with pytest.raises(_SampleIntegrityError):
        ops._sample_file_bytes("source.txt")


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_real_nul_sample_still_blocks_text_read(tmp_path):
    (tmp_path / "source.txt").write_bytes(b"header\x00binary\n")
    ops = ShellFileOperations(_SampleNoiseGitBash(tmp_path, "none"))

    result = ops.read_file_raw("source.txt")

    assert result.is_binary
    assert result.error is not None


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
@pytest.mark.parametrize("read_method", ["read_file", "read_file_raw"])
def test_integrity_failure_never_admits_sparse_nul_binary(tmp_path, read_method):
    (tmp_path / "source.txt").write_bytes(b"readable prefix\x00readable suffix\n")
    ops = ShellFileOperations(_SampleNoiseGitBash(tmp_path, "inside"))

    result = getattr(ops, read_method)("source.txt")

    assert result.error is not None
    assert "sample" in result.error.lower()


@pytest.mark.skipif(not _GIT_BASH.is_file(), reason="native Git Bash unavailable")
def test_missing_base64_keeps_legacy_text_sample_fallback(tmp_path):
    (tmp_path / "source.txt").write_bytes(b"anchor\n")
    ops = ShellFileOperations(_SampleNoiseGitBash(tmp_path, "missing_base64"))

    assert ops._sample_file_bytes("source.txt") is None
    result = ops.read_file_raw("source.txt")

    assert result.error is None
    assert result.content == "anchor\n"
