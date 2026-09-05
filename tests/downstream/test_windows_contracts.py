from __future__ import annotations

from pathlib import Path

import pytest

from downstream.features import load_feature_manifest, validate_feature_manifest
from downstream.platform.windows.credentials import safe_child_environment
from downstream.platform.windows.filesystem import replace_with_retry
from downstream.platform.windows.gpu import visible_cuda_devices
from downstream.platform.windows.ipc import named_pipe_path
from downstream.platform.windows.paths import normalize_windows_path, windows_path_key
from downstream.platform.windows.power import resume_gap_detected
from downstream.platform.windows.process import (
    kill_process_tree,
    windows_creation_flags,
)
from downstream.platform.windows.terminal import (
    quote_powershell_literal,
    shell_path_kind,
)
from downstream.platform.windows.updater import handoff_locked_artifact
from downstream.services.desktop import DESKTOP_BACKEND_HEALTH
from downstream.services.embedding import EMBEDDING_HEALTH
from downstream.services.llama import LLAMA_HEALTH
from downstream.services.watchdog import (
    OUTER_RESTART_AUTHORITY,
    owns_automatic_restart,
    request_restart,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"C:\work\Hermes", r"C:\work\Hermes"),
        ("/c/work/Hermes", r"C:\work\Hermes"),
        ("/mnt/c/work/Hermes", r"C:\work\Hermes"),
    ],
)
def test_windows_path_aliases_normalize_to_native(raw: str, expected: str) -> None:
    assert normalize_windows_path(raw) == expected


def test_windows_path_comparison_is_case_insensitive() -> None:
    assert windows_path_key(r"C:\Work\Hermes") == windows_path_key("/c/work/hermes")


def test_ntfs_replace_retries_only_lock_errors() -> None:
    calls: list[tuple[object, object]] = []
    sleeps: list[float] = []

    def replace(source, destination) -> None:
        calls.append((source, destination))
        if len(calls) < 3:
            raise PermissionError("locked")

    replace_with_retry(
        "staged", "live", delays=(0.01, 0.02), replace=replace, sleep=sleeps.append
    )
    assert calls == [("staged", "live")] * 3
    assert sleeps == [0.01, 0.02]


def test_ntfs_replace_does_not_retry_unrelated_errors() -> None:
    calls = 0

    def replace(_source, _destination) -> None:
        nonlocal calls
        calls += 1
        raise FileNotFoundError("missing")

    with pytest.raises(FileNotFoundError):
        replace_with_retry("staged", "live", replace=replace, sleep=lambda _delay: None)
    assert calls == 1


def test_updater_handoff_uses_bounded_replace_contract() -> None:
    calls: list[tuple[object, object]] = []
    handoff_locked_artifact(
        "staged.exe",
        "live.exe",
        delays=(),
        replace=lambda source, live: calls.append((source, live)),
    )
    assert calls == [("staged.exe", "live.exe")]


def test_named_pipe_is_profile_scoped_and_sanitized() -> None:
    assert (
        named_pipe_path("gateway control", profile="Bot A")
        == r"\.\pipe\hermes-Bot-A-gateway-control"
    )


def test_child_environment_drops_ambient_credentials() -> None:
    source = {"PATH": "bin", "SYSTEMROOT": r"C:\Windows", "OPENAI_API_KEY": "secret"}
    assert safe_child_environment(source) == {
        "PATH": "bin",
        "SYSTEMROOT": r"C:\Windows",
    }


def test_child_environment_requires_explicit_secret_allowlist() -> None:
    with pytest.raises(ValueError, match="requires explicit allowlisting"):
        safe_child_environment({}, overrides={"SERVICE_TOKEN": "secret"})
    assert safe_child_environment(
        {},
        overrides={"SERVICE_TOKEN": "secret"},
        allowed_secret_names=frozenset({"SERVICE_TOKEN"}),
    ) == {"SERVICE_TOKEN": "secret"}


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        (r"C:\work", "native"),
        ("/c/work", "msys"),
        ("/mnt/c/work", "wsl"),
        ("relative/path", "relative"),
    ],
)
def test_shell_path_boundaries(path: str, kind: str) -> None:
    assert shell_path_kind(path) == kind


def test_powershell_literal_quoting() -> None:
    assert quote_powershell_literal("Bob's file") == "'Bob''s file'"


def test_resume_gap_detection() -> None:
    assert resume_gap_detected(10.0, 75.0, threshold_seconds=60.0) is True
    assert resume_gap_detected(10.0, 20.0, threshold_seconds=60.0) is False
    assert resume_gap_detected(20.0, 10.0, threshold_seconds=60.0) is True


def test_cuda_device_selection_is_strict() -> None:
    assert visible_cuda_devices("0, 2") == (0, 2)
    assert visible_cuda_devices("-1") == ()
    with pytest.raises(ValueError):
        visible_cuda_devices("1,1")


def test_process_contract_rejects_invalid_pid_without_side_effect() -> None:
    assert kill_process_tree(0) is False
    assert isinstance(windows_creation_flags(detached=True), int)


def test_only_go_watchdog_owns_automatic_restart() -> None:
    assert OUTER_RESTART_AUTHORITY == "scripts/windows/watchdog-go"
    assert owns_automatic_restart(OUTER_RESTART_AUTHORITY) is True
    assert owns_automatic_restart("apps/desktop") is False
    assert request_restart("embedding", "health probe failed").service == "embedding"


def test_go_watchdog_http_surface_is_read_only() -> None:
    root = Path(__file__).resolve().parents[2]
    go_root = root / "scripts" / "windows" / "watchdog-go"
    server = (go_root / "server.go").read_text(encoding="utf-8")
    config = (go_root / "config.go").read_text(encoding="utf-8")

    assert server.count("mux.HandleFunc(") == 3
    assert 'mux.HandleFunc("/health", s.handleHealth)' in server
    assert 'mux.HandleFunc("/api/status", s.handleStatus)' in server
    assert 'mux.HandleFunc("/api/v1/status", s.handleStatus)' in server
    for mutation in ("pause", "resume", "cycle", "stop", "restart", "force-restart"):
        assert f'/api/v1/{mutation}' not in server
    assert "requireAdmin" not in server
    assert "AdminToken" not in server + config
    assert "HERMES_WATCHDOG_ADMIN_TOKEN" not in server + config


def test_local_service_health_endpoints_are_loopback_only() -> None:
    assert LLAMA_HEALTH.url() == "http://127.0.0.1:8080/health"
    assert EMBEDDING_HEALTH.url() == "http://127.0.0.1:8082/health"
    assert DESKTOP_BACKEND_HEALTH.url() == "http://127.0.0.1:9119/api/status"


def test_feature_manifest_is_schema_valid_and_has_real_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = load_feature_manifest(root / "FEATURES.yaml")
    assert validate_feature_manifest(manifest) == []
    for feature in manifest["features"]:
        assert (root / feature["owner_path"]).exists()
        assert all((root / test).exists() for test in feature["tests"])


def test_no_top_level_platform_package_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / "platform").exists()


@pytest.mark.parametrize(
    "script_name",
    ["Restart-HermesFullStack.ps1", "Restart-HermesDesktopAndLlama.ps1"],
)
def test_windows_restart_scripts_build_packaged_desktop(script_name: str) -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "windows" / script_name).read_text(encoding="utf-8")

    assert "pnpm run pack" in script
    assert "npm run pack" in script
    assert "@hermes/desktop" not in script


@pytest.mark.parametrize(
    "script_name",
    ["Restart-HermesFullStack.ps1", "restart-hermes-stack.ps1"],
)
def test_windows_restart_scripts_fall_back_to_netstat_for_listener_discovery(
    script_name: str,
) -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "windows" / script_name).read_text(encoding="utf-8")

    assert "Get-NetTCPConnection" in script
    assert "-ErrorAction Stop" in script
    assert "netstat.exe -ano -p tcp" in script
    assert "[int]::TryParse" in script
    assert "memory-graph" in script


@pytest.mark.parametrize(
    ("script_name", "root_variable"),
    [
        ("start-hermes-desktop.ps1", "$HermesRoot"),
        ("Start-HermesDesktopBackendWatchdog.ps1", "$RepoRoot"),
    ],
)
def test_windows_desktop_launchers_prefer_canonical_repo_package(
    script_name: str,
    root_variable: str,
) -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "windows" / script_name).read_text(encoding="utf-8")
    repo_candidate = (
        f'Join-Path {root_variable} "apps\\desktop\\release\\win-unpacked\\Hermes.exe"'
    )
    managed_candidate = (
        'Join-Path $env:LOCALAPPDATA "hermes\\hermes-agent\\apps\\desktop\\release\\'
        'win-unpacked\\Hermes.exe"'
    )

    assert script.index(repo_candidate) < script.index(managed_candidate)
