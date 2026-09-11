"""Regression coverage for the Windows Go-watchdog task registration port."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
GO_START = REPO_ROOT / "scripts" / "windows" / "Start-HermesGoWatchdog.ps1"
GO_BACKEND = REPO_ROOT / "scripts" / "windows" / "watchdog-go" / "backend.go"
LEGACY_START = (
    REPO_ROOT / "scripts" / "windows" / "Start-HermesDesktopBackendWatchdog.ps1"
)
AUTOSTART = REPO_ROOT / "scripts" / "windows" / "restart-hermes-autostart-admin.ps1"
README = REPO_ROOT / "scripts" / "windows" / "watchdog-go" / "README.md"


def _go_default_port() -> int:
    text = GO_BACKEND.read_text(encoding="utf-8")
    match = re.search(r"const\s+DefaultManagedBackendPort\s*=\s*(\d+)", text)
    assert match is not None, "the Go watchdog default port declaration is missing"
    return int(match.group(1))


def _single_port(pattern: str, text: str, description: str) -> int:
    matches = re.findall(pattern, text)
    assert len(matches) == 1, f"expected one {description}, found {len(matches)}"
    return int(matches[0])


def test_watchdog_task_registration_matches_the_go_default_backend_port() -> None:
    expected = _go_default_port()
    go_start = GO_START.read_text(encoding="utf-8")
    legacy_start = LEGACY_START.read_text(encoding="utf-8")
    autostart = AUTOSTART.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    go_default = _single_port(
        r"\[int\]\$ManagedBackendPort\s*=\s*(\d+)",
        go_start,
        "Go PowerShell default",
    )
    legacy_default = _single_port(
        r"\[int\]\$ManagedBackendPort\s*=\s*(\d+)",
        legacy_start,
        "legacy PowerShell default",
    )
    registered_ports = [
        int(match)
        for match in re.findall(r"-ManagedBackendPort\s+(\d+)", autostart)
    ]
    assert registered_ports, "scheduled-task port registrations are missing"
    assert set(registered_ports) == {expected}, (
        f"scheduled-task ports {registered_ports} must all equal {expected}"
    )
    assert len(registered_ports) >= 2, (
        "boot and logon Go watchdog tasks must both pin the managed port"
    )
    documented_default = _single_port(
        r"\|\s*`-managed-backend-port`\s*\|\s*(\d+)\s*\|",
        readme,
        "README default",
    )

    assert {
        go_default,
        legacy_default,
        documented_default,
    } == {expected}


def test_watchdog_task_registration_still_forwards_explicit_port_overrides() -> None:
    go_start = GO_START.read_text(encoding="utf-8")

    templates = re.findall(
        r'if\s*\(\$ManagedBackendPort\s*-gt\s*0\)\s*\{\s*'
        r'\$\w+\s*\+=\s*"([^"]+)"\s*\}',
        go_start,
    )
    assert len(templates) == 2, (
        "both detached-launch argument paths must forward the port"
    )

    expected = _go_default_port()
    override = expected + 1
    for port in (expected, override):
        rendered = [
            template.replace("$ManagedBackendPort", str(port)) for template in templates
        ]
        assert rendered == [f"-managed-backend-port={port}"] * 2


def test_watchdog_build_quotes_script_paths_with_spaces() -> None:
    go_start = GO_START.read_text(encoding="utf-8")

    assert "$quotedBuildScript" in go_start
    assert '-ArgumentList ($processArgs -join " ")' in go_start
    assert '-File", $BuildScript' not in go_start
