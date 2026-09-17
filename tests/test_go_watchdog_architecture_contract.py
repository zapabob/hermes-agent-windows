"""Source-level contract for the operator-approved Go watchdog topology."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WINDOWS = REPO_ROOT / "scripts" / "windows"
GO = WINDOWS / "watchdog-go"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_watchdog_uses_single_owner_startup_and_probe_defaults() -> None:
    launcher = _read(WINDOWS / "Start-HermesGoWatchdog.ps1")
    main = _read(GO / "main.go")
    autostart = _read(WINDOWS / "repair-hermes-autostart.ps1")

    assert '[int]$IntervalSec = 20' in launcher
    assert '[string]$Listen = "127.0.0.1:9920"' in launcher
    assert '$FailThreshold' not in launcher
    assert '$ManagedBackendPort' not in launcher
    assert '$NoPrewarm' not in launcher
    assert 'flag.Int("interval", 20,' in main
    assert 'fail-threshold' not in main
    assert 'managed-backend-port' not in main
    assert 'prewarm-backend' not in main
    assert '"HermesGoWatchdogBootAutoStart"' in autostart
    assert '"HermesGoWatchdogLogonAutoStart"' in autostart
    assert "-WindowStyle Hidden" in autostart


def test_watchdog_backend_probe_is_observation_only() -> None:
    probe = _read(GO / "probe.go")
    process = _read(GO / "process_windows.go")

    assert "/api/status" in probe
    assert "findHealthyDesktopBackend" in process
    assert "PROCESS_TERMINATE" not in process
    assert "TerminateProcess(" not in process
    assert "restartPackagedDesktop" not in process
    assert "stopOrphanDesktopBackends" not in process
    assert not (GO / "backend.go").exists()
    assert not (GO / "health.go").exists()


def test_a2a_sidecars_are_outside_direct_watchdog_management() -> None:
    process = _read(GO / "process_windows.go")

    assert "9123: {}" in process
    assert "9124: {}" in process
    assert "go-a2a-hub" not in process
    assert "go-a2a-roundrobin" not in process


def test_session0_watchdog_relaunches_without_desktop_kill_authority() -> None:
    process = _read(GO / "process_windows.go")
    launcher = _read(WINDOWS / "Start-HermesGoWatchdog.ps1")

    assert "isNonInteractiveSession" in process
    assert "HermesDesktopAutoStart" in process
    assert "startDesktopInInteractiveSession" in process
    assert "PROCESS_TERMINATE" not in process
    assert "restartPackagedDesktop" not in process
    assert "Replacing Session 0 Go watchdog" in launcher
    assert "Get-GoWatchdogSessionId" in launcher
    assert '$state.Status -ne "owned"' in launcher
    assert "OpenProcessForAuthority" in launcher
    assert "process identity is unverified" in launcher
    assert "$replaceSession0Owner" in launcher
