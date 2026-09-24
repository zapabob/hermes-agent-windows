from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


_MAX_PUBLIC_FINDINGS = 64


class Verdict(StrEnum):
    CLEAN = "CLEAN"
    UNKNOWN = "UNKNOWN"
    SUSPICIOUS = "SUSPICIOUS"
    MALICIOUS = "MALICIOUS"
    SCAN_ERROR = "SCAN_ERROR"


class FileVerdict(StrEnum):
    CLEAN = "CLEAN"
    UNKNOWN = "UNKNOWN"
    SUSPICIOUS = "SUSPICIOUS"
    MALICIOUS = "MALICIOUS"


class EngineHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class ExecutionDecision(StrEnum):
    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


class EngineState(StrEnum):
    AVAILABLE = "available"
    SCANNER_UNAVAILABLE = "scanner_unavailable"
    SCAN_TIMEOUT = "scan_timeout"
    DATABASE_STALE = "database_stale"
    DATABASE_ERROR = "database_error"
    ENGINE_ERROR = "engine_error"


@dataclass(frozen=True)
class Finding:
    source: str
    name: str
    score: int
    state: EngineState = EngineState.AVAILABLE
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if self.state == EngineState.AVAILABLE:
            tier = self.details.get("tier")
            if isinstance(tier, str):
                details["tier"] = tier[:32]
            tags = self.details.get("tags")
            if isinstance(tags, (list, tuple)):
                details["tags"] = [tag[:64] for tag in tags[:16] if isinstance(tag, str)]
            confidence = self.details.get("confidence")
            if isinstance(confidence, int) and not isinstance(confidence, bool):
                details["confidence"] = max(0, min(confidence, 100))
            source = self.details.get("source")
            if isinstance(source, str):
                details["source"] = source[:80]
        return {
            "source": self.source[:80],
            "name": self.name[:160],
            "score": max(0, min(int(self.score), 100)),
            "state": self.state.value,
            "details": details,
        }


@dataclass(frozen=True)
class ScanResult:
    path: str
    sha256: str
    size: int
    verdict: Verdict
    score: int
    action: str
    findings: tuple[Finding, ...]
    engine_versions: dict[str, str]
    cached: bool = False
    quarantine_id: str | None = None
    error: str | None = None
    file_identity: tuple[int, int, int, int, int] | None = field(default=None, repr=False, compare=False)

    @property
    def file_verdict(self) -> FileVerdict:
        if self.score >= 80 or self.verdict == Verdict.MALICIOUS:
            return FileVerdict.MALICIOUS
        if self.score >= 20 or self.verdict == Verdict.SUSPICIOUS:
            return FileVerdict.SUSPICIOUS
        if self.verdict == Verdict.CLEAN:
            return FileVerdict.CLEAN
        return FileVerdict.UNKNOWN

    @property
    def engine_health(self) -> EngineHealth:
        failing_states = {
            EngineState.SCAN_TIMEOUT,
            EngineState.DATABASE_STALE,
            EngineState.DATABASE_ERROR,
            EngineState.ENGINE_ERROR,
        }
        authoritative_available = any(
            item.source in {"clamav", "yara"} and item.state == EngineState.AVAILABLE
            for item in self.findings
        )
        authoritative_unavailable = any(
            item.source in {"clamav", "yara"} and item.state == EngineState.SCANNER_UNAVAILABLE
            for item in self.findings
        )
        has_errors = any(item.state in failing_states for item in self.findings)
        if has_errors:
            return EngineHealth.DEGRADED if authoritative_available else EngineHealth.ERROR
        if authoritative_unavailable:
            return EngineHealth.DEGRADED if authoritative_available else EngineHealth.UNAVAILABLE
        if authoritative_available:
            return EngineHealth.HEALTHY
        return EngineHealth.ERROR if self.verdict == Verdict.SCAN_ERROR else EngineHealth.UNAVAILABLE

    @property
    def execution_decision(self) -> ExecutionDecision:
        if self.file_verdict == FileVerdict.MALICIOUS:
            return ExecutionDecision.ALLOW if self.action == "allowlisted" else ExecutionDecision.BLOCK
        if self.action == "blocked_pending_review":
            return ExecutionDecision.REVIEW
        if self.action == "allow":
            return ExecutionDecision.ALLOW
        if self.file_verdict == FileVerdict.SUSPICIOUS:
            return ExecutionDecision.WARN
        return ExecutionDecision.REVIEW

    def to_dict(self) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "path": self.path[:255] + "…" if len(self.path) > 256 else self.path,
            "sha256": self.sha256,
            "size": self.size,
            "verdict": self.verdict,
            "score": self.score,
            "action": self.action,
            "findings": [item.to_public_dict() for item in self.findings[:_MAX_PUBLIC_FINDINGS]],
            "finding_count": len(self.findings),
            "findings_truncated": len(self.findings) > _MAX_PUBLIC_FINDINGS,
            "engine_versions": {
                str(name)[:80]: str(version)[:160]
                for name, version in list(self.engine_versions.items())[:16]
            },
            "cached": self.cached,
            "quarantine_id": self.quarantine_id,
            "error": self.error,
        }
        if self.error is not None:
            if self.error in {
                "candidate_unresolved",
                "candidate_parse_failed",
                "candidate_limit_exceeded",
                "candidate_reference_too_long",
                "file_changed_during_scan",
                "scan_snapshot_unavailable",
            }:
                projection["error"] = self.error
            elif self.action == "quarantine_failed":
                projection["error"] = "quarantine_failed"
            elif self.verdict == Verdict.SCAN_ERROR:
                projection["error"] = "scanner_error"
            else:
                projection["error"] = "scan_error"
        projection.update(
            file_verdict=self.file_verdict.value,
            engine_health=self.engine_health.value,
            execution_decision=self.execution_decision.value,
        )
        return projection
