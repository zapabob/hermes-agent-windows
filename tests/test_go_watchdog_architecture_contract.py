"""Source-level contract for the operator-approved Go watchdog topology."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WINDOWS = REPO_ROOT / "scripts" / "windows"
GO = WINDOWS / "watchdog-go"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_watchdog_uses_the_documented_single_startup_and_probe_defaults() -> None:
    launcher = _read(WINDOWS / "Start-HermesGoWatchdog.ps1")
    main = _read(GO / "main.go")
    autostart = _read(WINDOWS / "repair-hermes-autostart.ps1")

    assert '[int]$IntervalSec = 20' in launcher
    assert '[int]$FailThreshold = 2' in launcher
    assert '[int]$ManagedBackendPort = 9119' in launcher
    assert '[string]$Listen = "127.0.0.1:9920"' in launcher
    assert 'flag.Int("interval", 20,' in main
    assert 'flag.Int("fail-threshold", 2,' in main
    assert '"HermesGoWatchdogBootAutoStart"' in autostart
    assert "-WindowStyle Hidden" in autostart


def test_watchdog_backend_probe_requires_status_and_session_token() -> None:
    process = _read(GO / "process_windows.go")
    backend = _read(GO / "backend.go")

    assert "/api/status" in process
    assert "/api/sessions" in process
    assert 'req.Header.Set("Authorization", "Bearer "+tok)' in process
    assert 'req.Header.Set("X-Hermes-Session-Token", tok)' in process
    assert "const DefaultManagedBackendPort = 9119" in backend


def test_a2a_sidecars_are_outside_direct_watchdog_management() -> None:
    process = _read(GO / "process_windows.go")

    assert "9123: {}" in process
    assert "9124: {}" in process
    assert "go-a2a-hub" not in process
    assert "go-a2a-roundrobin" not in process
