"""Regression coverage for observation-only Go-watchdog task registration."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
GO_START = REPO_ROOT / "scripts" / "windows" / "Start-HermesGoWatchdog.ps1"
GO_MAIN = REPO_ROOT / "scripts" / "windows" / "watchdog-go" / "main.go"
LEGACY_START = (
    REPO_ROOT / "scripts" / "windows" / "Start-HermesDesktopBackendWatchdog.ps1"
)
AUTOSTART = REPO_ROOT / "scripts" / "windows" / "restart-hermes-autostart-admin.ps1"
REPAIR = REPO_ROOT / "scripts" / "windows" / "repair-hermes-autostart.ps1"
README = REPO_ROOT / "scripts" / "windows" / "watchdog-go" / "README.md"


def test_watchdog_task_registration_omits_managed_backend_port() -> None:
    """Boot/logon tasks must not pin the removed managed-backend port path."""
    go_start = GO_START.read_text(encoding="utf-8")
    go_main = GO_MAIN.read_text(encoding="utf-8")
    legacy_start = LEGACY_START.read_text(encoding="utf-8")
    autostart = AUTOSTART.read_text(encoding="utf-8")
    repair = REPAIR.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "$ManagedBackendPort" not in go_start
    assert "managed-backend-port" not in go_main
    assert "prewarm-backend" not in go_main
    assert "-ManagedBackendPort" not in autostart
    assert "-ManagedBackendPort" not in repair
    assert "HermesGoWatchdogBootAutoStart" in autostart
    assert "HermesGoWatchdogLogonAutoStart" in autostart
    assert "HermesGoWatchdogBootAutoStart" in repair
    assert "HermesGoWatchdogLogonAutoStart" in repair
    # Legacy shim may accept the flag for BC but must not forward it.
    assert "ManagedBackendPort = $ManagedBackendPort" not in legacy_start
    assert "FailThreshold      = $FailThreshold" not in legacy_start
    assert "obsolete managed-backend args ignored" in legacy_start
    assert "desktop-backend.json" in readme
    assert "生成" in readme or "adopt" in readme.lower() or "採用" in readme
    assert not (REPO_ROOT / "scripts" / "windows" / "watchdog-go" / "backend.go").exists()


def test_watchdog_build_quotes_script_paths_with_spaces() -> None:
    go_start = GO_START.read_text(encoding="utf-8")

    assert "$quotedBuildScript" in go_start
    assert '-ArgumentList ($processArgs -join " ")' in go_start
    assert '-File", $BuildScript' not in go_start
