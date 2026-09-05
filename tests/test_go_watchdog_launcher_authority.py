"""Authority contracts for the Windows Go-watchdog launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "windows" / "Start-HermesGoWatchdog.ps1"
HAS_WINDOWS_POWERSHELL = os.name == "nt" and shutil.which("powershell.exe") is not None


def _launcher() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def _is_elevated() -> bool:
    powershell = shutil.which("powershell.exe")
    assert powershell is not None, "Windows PowerShell is required"
    probe = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-Command",
            "$i=[Security.Principal.WindowsIdentity]::GetCurrent();"
            "$p=New-Object Security.Principal.WindowsPrincipal($i);"
            "$p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    return probe.returncode == 0 and probe.stdout.strip().lower() == "true"


def test_launcher_source_is_windows_powershell_compatible_ascii() -> None:
    _launcher().encode("ascii")


def _run_stop(local_app_data: Path) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell.exe")
    assert powershell is not None, "Windows PowerShell is required"
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(local_app_data)
    return subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LAUNCHER),
            "-Stop",
            "-HermesRoot",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )


def test_launcher_requires_full_process_identity_before_claiming_a_lock() -> None:
    launcher = _launcher()

    assert "function Get-GoWatchdogLockState" in launcher
    assert "processCreated" in launcher
    assert "executablePath" in launcher
    assert "repoRoot" in launcher
    assert "ToFileTimeUtc()" in launcher
    assert 'Status = "owned"' in launcher
    assert 'Status = "foreign"' in launcher


def test_launcher_never_stops_watchdogs_by_image_name() -> None:
    launcher = _launcher()

    assert "Get-Process -Name hermes-watchdog" not in launcher
    assert "taskkill /IM hermes-watchdog" not in launcher
    assert "Stop-Process -Id $state.Pid" in launcher


def test_launcher_requires_an_elevated_operator_before_any_side_effect() -> None:
    launcher = _launcher()

    assert "function Test-IsElevatedOperator" in launcher
    assert "if (-not (Test-IsElevatedOperator))" in launcher
    assert "Operator-only Go watchdog launcher requires an elevated PowerShell session." in launcher
    authority_check = launcher.index("if (-not (Test-IsElevatedOperator))")
    stop_dispatch = launcher.index("if ($Stop) {")
    assert authority_check < stop_dispatch


@pytest.mark.skipif(not HAS_WINDOWS_POWERSHELL, reason="Windows PowerShell is required")
def test_non_elevated_agent_context_cannot_stop_or_remove_lock(tmp_path: Path) -> None:
    if _is_elevated():
        pytest.skip("negative authorization path requires a non-elevated runner")
    data_dir = tmp_path / "HermesWatchdog"
    data_dir.mkdir()
    lock_path = data_dir / "watchdog.lock"
    lock_path.write_text('{"pid":2147483647}', encoding="utf-8")

    result = _run_stop(tmp_path)

    assert result.returncode == 1
    assert lock_path.exists()
    assert "Operator-only Go watchdog launcher requires an elevated PowerShell session." in (
        result.stdout + result.stderr
    )


def test_explicit_stop_runs_before_binary_availability_checks() -> None:
    launcher = _launcher()

    assert "[switch]$Stop" in launcher
    stop_dispatch = launcher.index("if ($Stop) {")
    missing_binary = launcher.index("if (-not (Test-Path -LiteralPath $Exe)) {")
    assert stop_dispatch < missing_binary


def test_legacy_watchdog_stop_is_bound_to_the_exact_script_path() -> None:
    launcher = _launcher()

    assert "$LegacyWatchdogScript" in launcher
    assert "[regex]::Escape($LegacyWatchdogScript)" in launcher
    assert "-match $legacyScriptPattern" in launcher
    assert "-match 'Start-HermesDesktopBackendWatchdog\\.ps1'" not in launcher


def test_foreign_live_lock_is_preserved() -> None:
    launcher = _launcher()

    assert 'if ($state.Status -eq "stale")' in launcher
    assert 'elseif ($state.Status -eq "foreign")' in launcher
    assert "Remove-Item -LiteralPath $LockPath" in launcher
    assert "refusing to stop or remove its lock" in launcher
    assert 'if ($startupState.Status -eq "foreign")' in launcher
    assert "refusing to start a second owner" in launcher
    assert "if (-not (Stop-GoWatchdog))" in launcher


@pytest.mark.skipif(not HAS_WINDOWS_POWERSHELL, reason="Windows PowerShell is required")
def test_explicit_stop_preserves_a_foreign_live_process_and_lock(tmp_path: Path) -> None:
    if not _is_elevated():
        pytest.skip("operator identity test requires an elevated Windows runner")
    data_dir = tmp_path / "HermesWatchdog"
    data_dir.mkdir()
    lock_path = data_dir / "watchdog.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "processCreated": 1,
                "executablePath": sys.executable,
                "startedAt": "1970-01-01T00:00:00Z",
                "repoRoot": str(REPO_ROOT),
            }
        ),
        encoding="utf-8",
    )

    result = _run_stop(tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert lock_path.exists()
    assert "refusing to stop or remove its lock" in (result.stdout + result.stderr)


@pytest.mark.skipif(not HAS_WINDOWS_POWERSHELL, reason="Windows PowerShell is required")
def test_explicit_stop_removes_only_a_stale_lock(tmp_path: Path) -> None:
    if not _is_elevated():
        pytest.skip("operator identity test requires an elevated Windows runner")
    data_dir = tmp_path / "HermesWatchdog"
    data_dir.mkdir()
    lock_path = data_dir / "watchdog.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": 2_147_483_647,
                "processCreated": 1,
                "executablePath": "C:/missing/hermes-watchdog.exe",
                "startedAt": "1970-01-01T00:00:00Z",
                "repoRoot": str(REPO_ROOT),
            }
        ),
        encoding="utf-8",
    )

    result = _run_stop(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not lock_path.exists()
