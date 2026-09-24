from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_cli._subprocess_compat import split_command_line
from hermes_cli.config import load_config

from .models import ExecutionDecision, ScanResult, Verdict
from .service import FileIdentity, SecurityService, hash_stable_file


_SCANNED_SUFFIXES = {
    ".bat", ".cmd", ".com", ".cpl", ".dll", ".exe", ".hta", ".jar", ".js",
    ".jse", ".lnk", ".msi", ".ps1", ".py", ".scr", ".vbe", ".vbs", ".whl",
    ".wsf", ".zip",
}
_MAX_COMMAND_LENGTH = 64 * 1024
_MAX_CANDIDATE_REFERENCES = 32
_MAX_CANDIDATE_REFERENCE_LENGTH = 2048


CandidateSnapshot = dict[str, tuple[str, int, FileIdentity | None]]


class CommandGateResult(dict[str, Any]):
    """Public dictionary projection with private terminal revalidation data."""

    def __init__(
        self,
        projection: dict[str, Any],
        *,
        enforced: bool,
        candidate_snapshot: CandidateSnapshot,
    ) -> None:
        super().__init__(projection)
        self.enforced = enforced
        self.candidate_snapshot = candidate_snapshot


def _candidate_references(command: str) -> tuple[list[str] | None, str | None]:
    """Return literal script-like argv values and a fixed refusal reason.

    Shell interpolation and command substitution without a literal recognized
    suffix remain outside this userspace parser's boundary.
    """
    if len(command) > _MAX_COMMAND_LENGTH:
        return None, "candidate_limit_exceeded"
    try:
        tokens = split_command_line(command)
    except ValueError:
        return None, "candidate_parse_failed"
    references: list[str] = []
    for raw in tokens:
        token = raw.strip("\"';&|()")
        if not token or "://" in token:
            continue
        candidate = token
        if token.startswith("-"):
            _option, separator, value = token.partition("=")
            if not separator:
                _option, separator, value = token.partition(":")
            if not separator:
                continue
            candidate = value
        if Path(candidate).suffix.lower() in _SCANNED_SUFFIXES:
            if len(candidate) > _MAX_CANDIDATE_REFERENCE_LENGTH:
                return None, "candidate_reference_too_long"
            references.append(candidate)
            if len(references) > _MAX_CANDIDATE_REFERENCES:
                return None, "candidate_limit_exceeded"
    return references, None


def _resolve_references(references: list[str], cwd: Path) -> tuple[list[Path], list[str]]:
    found: list[Path] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for token in references:
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_file():
                unresolved.append(token)
                continue
        except (OSError, RuntimeError, ValueError):
            unresolved.append(token)
            continue
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        found.append(resolved)
    return found, unresolved


def _candidates(command: str, cwd: Path) -> list[Path]:
    references, error = _candidate_references(command)
    if error is not None or references is None:
        return []
    candidates, _unresolved = _resolve_references(references, cwd)
    return candidates


def _refusal_results(reason: str) -> list[ScanResult]:
    """Build one bounded refusal without reflecting command-supplied paths."""
    return [
        ScanResult(
            "execution candidate unavailable",
            "",
            0,
            Verdict.SCAN_ERROR,
            0,
            "blocked_pending_review",
            (),
            {},
            error=reason,
        )
    ]


def preflight_command(command: str, cwd: str) -> dict[str, Any]:
    references, parse_error = _candidate_references(command)
    if references == [] and parse_error is None:
        return {"allowed": True, "blocked": [], "warnings": [], "results": []}
    config = load_config()
    malware = dict((config.get("security") or {}).get("malware") or {})
    if not malware.get("enabled", True) or not malware.get("execution_gate", True):
        return {"allowed": True, "blocked": [], "warnings": [], "results": []}
    if parse_error is not None or references is None:
        blocked = _refusal_results(parse_error or "candidate_parse_failed")
        projection = [result.to_dict() for result in blocked]
        return CommandGateResult(
            {"allowed": False, "blocked": projection, "warnings": [], "results": projection},
            enforced=True,
            candidate_snapshot={},
        )
    candidates, unresolved = _resolve_references(references, Path(cwd))
    if unresolved:
        blocked = _refusal_results("candidate_unresolved")
        projection = [result.to_dict() for result in blocked]
        return CommandGateResult(
            {"allowed": False, "blocked": projection, "warnings": [], "results": projection},
            enforced=True,
            candidate_snapshot={},
        )
    if not candidates:
        return CommandGateResult(
            {"allowed": True, "blocked": [], "warnings": [], "results": []},
            enforced=True,
            candidate_snapshot={},
        )
    service = SecurityService(config=config)
    results = [service.scan_file(path) for path in candidates]
    blocked = [
        result
        for result in results
        if result.execution_decision in {ExecutionDecision.BLOCK, ExecutionDecision.REVIEW}
    ]
    warnings = [result for result in results if result.execution_decision == ExecutionDecision.WARN]
    snapshot = {
        result.path: (result.sha256, result.size, result.file_identity)
        for result in results
    }
    return CommandGateResult(
        {
            "allowed": not blocked,
            "blocked": [result.to_dict() for result in blocked],
            "warnings": [result.to_dict() for result in warnings],
            "results": [result.to_dict() for result in results],
        },
        enforced=True,
        candidate_snapshot=snapshot,
    )


def revalidate_command(command: str, cwd: str, expected: CandidateSnapshot) -> bool:
    """Fail closed when a candidate path, file identity, or content changed.

    This narrows the userspace check-to-use interval; it cannot pin the later
    shell open, so a replacement after this function returns remains possible.
    """
    references, error = _candidate_references(command)
    if error is not None or references is None:
        return False
    current_paths, unresolved = _resolve_references(references, Path(cwd))
    if unresolved:
        return False
    current = {str(path): path for path in current_paths}
    if set(current) != set(expected):
        return False
    for candidate, path in current.items():
        expected_sha256, expected_size, expected_identity = expected[candidate]
        if expected_identity is None:
            return False
        try:
            sha256, size, identity = hash_stable_file(path)
        except (OSError, RuntimeError, ValueError):
            return False
        if (sha256, size, identity) != (expected_sha256, expected_size, expected_identity):
            return False
    return True
