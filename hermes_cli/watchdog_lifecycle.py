"""Operator-approved lifecycle bridge for the independent Windows watchdog.

The agent-facing watchdog surface is intentionally read-only.  Planned
installation removal is the exceptional lifecycle path: it must already own
the maintenance lease and it must cross a Windows elevation prompt before it
can stop the watchdog or remove its startup task.
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

from hermes_cli.watchdog_maintenance import WatchdogMaintenanceLease


def _powershell_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _encoded_operator_command(
    *,
    script: Path,
    lease: WatchdogMaintenanceLease,
    project_root: Path,
    hermes_home: Path,
) -> str:
    command = " ".join(
        (
            "&",
            _powershell_literal(script),
            "-Action",
            _powershell_literal("Uninstall"),
            "-MaintenanceFile",
            _powershell_literal(lease.path),
            "-MaintenanceNonce",
            _powershell_literal(lease.nonce),
            "-HermesRoot",
            _powershell_literal(project_root.resolve()),
            "-HermesHome",
            _powershell_literal(hermes_home.resolve()),
        )
    )
    command += "; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
    return base64.b64encode(command.encode("utf-16-le")).decode("ascii")


def decommission_for_uninstall(
    *,
    project_root: Path,
    hermes_home: Path,
    lease: WatchdogMaintenanceLease,
) -> None:
    """Stop and unregister the watchdog through an elevated, fenced path."""
    if sys.platform != "win32":
        return

    script = (
        project_root
        / "scripts"
        / "windows"
        / "Invoke-HermesGoWatchdogLifecycle.ps1"
    ).resolve()
    if not script.is_file():
        raise RuntimeError(f"Missing operator watchdog lifecycle script: {script}")
    if not lease.path.is_file():
        raise RuntimeError("Watchdog maintenance state disappeared before uninstall")

    encoded = _encoded_operator_command(
        script=script,
        lease=lease,
        project_root=project_root,
        hermes_home=hermes_home,
    )
    elevate = (
        "$process = Start-Process -FilePath 'powershell.exe' "
        "-ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy',"
        "'Bypass','-EncodedCommand','"
        + encoded
        + "') -Verb RunAs -Wait -PassThru -WindowStyle Hidden; "
        "if ($null -eq $process) { exit 1 }; exit [int]$process.ExitCode"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            elevate,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "operator approval was denied").strip()
        raise RuntimeError(
            "Could not decommission the Go watchdog for uninstall "
            f"(exit {result.returncode}): {detail}"
        )
