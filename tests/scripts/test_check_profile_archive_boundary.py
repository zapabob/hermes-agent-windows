"""Behavioral tests for the profile archive CI guard."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ci"
    / "check_profile_archive_boundary.py"
)


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_clean_root_passes(tmp_path):
    result = _run(tmp_path)

    assert result.returncode == 0
    assert "No profile export archives" in result.stdout


def test_root_profile_archive_fails_without_printing_contents(tmp_path):
    default_archive = tmp_path / "default.tar.gz"
    alternate_archive = tmp_path / "backup.TGZ"
    default_archive.write_bytes(b"profile webhook secret must never be printed")
    alternate_archive.write_bytes(b"another archive")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "default.tar.gz" in result.stdout
    assert "backup.TGZ" in result.stdout
    assert "profile webhook secret" not in result.stdout
    assert "another archive" not in result.stdout


def test_nested_profile_archive_is_also_rejected(tmp_path):
    nested = tmp_path / "fixtures"
    nested.mkdir()
    (nested / "fixture.tar.gz").write_bytes(b"test fixture")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "fixtures/fixture.tar.gz" in result.stdout


def _vendor_fixture(root: Path) -> Path:
    relative = Path("website/vendor/hermes-agent-minimatch-compat-1.0.0.tgz")
    target = root / relative
    target.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT.parents[2] / relative, target)
    return target


def test_exact_reviewed_public_source_archive_passes(tmp_path):
    _vendor_fixture(tmp_path)
    assert _run(tmp_path).returncode == 0


def test_tampered_archive_at_reviewed_path_still_fails(tmp_path):
    target = _vendor_fixture(tmp_path)
    data = bytearray(target.read_bytes())
    data[-1] ^= 1
    target.write_bytes(data)
    result = _run(tmp_path)
    assert result.returncode == 1
    assert target.relative_to(tmp_path).as_posix() in result.stdout


def test_identical_archive_outside_reviewed_path_is_rejected(tmp_path):
    source = _vendor_fixture(tmp_path)
    shutil.copyfile(source, tmp_path / "profile.tgz")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "profile.tgz" in result.stdout


def test_directory_at_reviewed_archive_path_is_rejected(tmp_path):
    target = _vendor_fixture(tmp_path)
    target.unlink()
    target.mkdir()
    assert _run(tmp_path).returncode == 1


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs Windows elevation"
)
def test_symlink_at_reviewed_archive_path_is_rejected(tmp_path):
    target = _vendor_fixture(tmp_path)
    data = target.read_bytes()
    target.unlink()
    source = tmp_path / "source"
    source.write_bytes(data)
    target.symlink_to(source)
    assert _run(tmp_path).returncode == 1
