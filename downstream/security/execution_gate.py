from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_cli._subprocess_compat import split_command_line
from hermes_cli.config import load_config

from .models import ExecutionDecision
from .service import SecurityService


_SCANNED_SUFFIXES = {
    ".bat", ".cmd", ".com", ".cpl", ".dll", ".exe", ".hta", ".jar", ".js",
    ".jse", ".lnk", ".msi", ".ps1", ".py", ".scr", ".vbe", ".vbs", ".whl",
    ".wsf", ".zip",
}


def _candidates(command: str, cwd: Path) -> list[Path]:
    try:
        tokens = split_command_line(command)
    except ValueError:
        return []
    found: list[Path] = []
    seen: set[str] = set()
    for raw in tokens:
        token = raw.strip("\"';&|()")
        if not token or token.startswith("-") or "://" in token:
            continue
        path = Path(token)
        if path.suffix.lower() not in _SCANNED_SUFFIXES:
            continue
        candidate = path if path.is_absolute() else cwd / path
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_file() or str(resolved) in seen:
            continue
        seen.add(str(resolved))
        found.append(resolved)
    return found


def preflight_command(command: str, cwd: str) -> dict[str, Any]:
    candidates = _candidates(command, Path(cwd))
    if not candidates:
        return {"allowed": True, "blocked": [], "warnings": [], "results": []}
    config = load_config()
    malware = dict((config.get("security") or {}).get("malware") or {})
    if not malware.get("enabled", True) or not malware.get("execution_gate", True):
        return {"allowed": True, "blocked": [], "warnings": [], "results": []}
    service = SecurityService(config=config)
    results = [service.scan_file(path) for path in candidates]
    blocked = [
        result
        for result in results
        if result.execution_decision in {ExecutionDecision.BLOCK, ExecutionDecision.REVIEW}
    ]
    warnings = [result for result in results if result.execution_decision == ExecutionDecision.WARN]
    return {
        "allowed": not blocked,
        "blocked": [result.to_dict() for result in blocked],
        "warnings": [result.to_dict() for result in warnings],
        "results": [result.to_dict() for result in results],
    }
