from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GO_ROOT = ROOT / "scripts" / "windows" / "watchdog-go"
LAUNCHER = ROOT / "scripts" / "windows" / "Start-HermesGoWatchdog.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_go_watchdog_has_no_desktop_backend_lifecycle_authority() -> None:
    production = "\n".join(
        _read(path)
        for path in (
            GO_ROOT / "main.go",
            GO_ROOT / "config.go",
            GO_ROOT / "watchdog.go",
            GO_ROOT / "process_windows.go",
        )
    )
    launcher = _read(LAUNCHER)

    for forbidden in (
        "PrewarmBackend",
        "EnsureHealthy()",
        "NewBackendManager",
        "desktop-backend.json",
        "HERMES_WATCHDOG_MANAGED",
        "managed-backend-port",
        "prewarm-backend",
    ):
        assert forbidden not in production + launcher


def test_go_watchdog_backend_file_cannot_spawn_desktop_backend() -> None:
    backend = GO_ROOT / "backend.go"
    assert not backend.exists(), "legacy watchdog-owned Desktop backend manager must be removed"


def test_go_watchdog_relaunches_desktop_without_managed_backend_injection() -> None:
    process = _read(GO_ROOT / "process_windows.go")

    assert "func startPackagedDesktop(cfg Config, logger *Logger, mutationAllowed func() bool) bool" in process
    assert "desktopLaunchEnv(cfg)" in process
    assert "BackendManager" not in process
    assert "readLaunchManifest" not in process
    assert "stopOrphanDesktopBackends" not in process
    assert "restartPackagedDesktop" not in process
