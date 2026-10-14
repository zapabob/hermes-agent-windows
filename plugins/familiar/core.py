"""Strict explicit-intent launch boundary for the vendored Familiar body."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

REQUIRED_PHRASE = "VRChat起動"
TRUSTED_SOURCE = "user"
TRUSTED_PLATFORM = "desktop"
_VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "familiar"
_LAUNCH_LOCK = threading.Lock()

StatusProbe = Callable[[str, Path], bool]
Spawn = Callable[[str, Path], object]


def allows_launch(*, raw_text: object, source: str, platform: str) -> bool:
    """Return true only for the trusted Desktop user's stripped exact phrase."""
    return (
        isinstance(raw_text, str)
        and source == TRUSTED_SOURCE
        and platform == TRUSTED_PLATFORM
        and raw_text.strip() == REQUIRED_PHRASE
    )


def _familiar_is_running(uv_executable: str, vendor_dir: Path) -> bool:
    """Probe Familiar's own control API through its documented status command."""
    completed = subprocess.run(
        [uv_executable, "run", "familiar", "status"],
        cwd=vendor_dir,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=15,
    )
    return completed.returncode == 0


def _spawn_familiar(
    uv_executable: str,
    vendor_dir: Path,
    *,
    popen: Callable[..., object] = subprocess.Popen,
    log_path: Path | None = None,
) -> object:
    """Start Familiar from its official clone entrypoint without launching a shell."""
    target_log = log_path or (get_hermes_home() / "logs" / "familiar.log")
    target_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_handle = target_log.open("a", encoding="utf-8")
    try:
        return popen(
            [uv_executable, "run", "familiar", "run", "--print", "none"],
            cwd=vendor_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            creationflags=(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ),
        )
    finally:
        stderr_handle.close()


def request_launch(
    *,
    raw_text: object,
    source: str,
    platform: str,
    vendor_dir: Path = _VENDOR_DIR,
    uv_executable: str | None = None,
    status_probe: StatusProbe = _familiar_is_running,
    spawn: Spawn = _spawn_familiar,
    **_: Any,
) -> dict[str, str]:
    """Launch Familiar only after the exact trusted user-message gate passes."""
    if not allows_launch(raw_text=raw_text, source=source, platform=platform):
        return {"status": "ignored"}

    vendor_dir = Path(vendor_dir)
    if not (vendor_dir / "pyproject.toml").is_file():
        return {"status": "unavailable", "reason": "vendor_missing"}

    uv = uv_executable or shutil.which("uv.exe") or shutil.which("uv")
    if not uv:
        return {"status": "unavailable", "reason": "uv_missing"}

    with _LAUNCH_LOCK:
        try:
            if status_probe(uv, vendor_dir):
                return {"status": "already_running"}
            spawn(uv, vendor_dir)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error("Familiar launch failed: %s", exc)
            return {"status": "error", "reason": type(exc).__name__}

    return {"status": "started"}
