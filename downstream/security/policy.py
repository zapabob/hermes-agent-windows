from __future__ import annotations

from dataclasses import dataclass

from .models import EngineHealth, EngineState, ExecutionDecision, FileVerdict, Finding, Verdict


@dataclass(frozen=True)
class PolicyDecision:
    file_verdict: FileVerdict
    engine_health: EngineHealth
    execution_decision: ExecutionDecision
    verdict: Verdict
    score: int
    action: str
    error: str | None


def evaluate(findings: list[Finding], allowed: bool) -> PolicyDecision:
    score = max((finding.score for finding in findings), default=0)
    error_states = {
        EngineState.SCAN_TIMEOUT,
        EngineState.DATABASE_STALE,
        EngineState.DATABASE_ERROR,
        EngineState.ENGINE_ERROR,
    }
    authoritative_available = any(
        finding.source in {"clamav", "yara"} and finding.state == EngineState.AVAILABLE
        for finding in findings
    )
    authoritative_unavailable = any(
        finding.source in {"clamav", "yara"} and finding.state == EngineState.SCANNER_UNAVAILABLE
        for finding in findings
    )
    errors = [finding for finding in findings if finding.state in error_states]
    if errors:
        engine_health = EngineHealth.DEGRADED if authoritative_available else EngineHealth.ERROR
    elif authoritative_unavailable:
        engine_health = EngineHealth.DEGRADED if authoritative_available else EngineHealth.UNAVAILABLE
    elif authoritative_available:
        engine_health = EngineHealth.HEALTHY
    else:
        engine_health = EngineHealth.UNAVAILABLE

    if score >= 80:
        action = "allowlisted" if allowed else "quarantine"
        return PolicyDecision(
            FileVerdict.MALICIOUS,
            engine_health,
            ExecutionDecision.ALLOW if allowed else ExecutionDecision.BLOCK,
            Verdict.MALICIOUS,
            score,
            action,
            errors[0].name if errors else None,
        )
    if score >= 20:
        review_required = bool(errors) or (authoritative_unavailable and not authoritative_available)
        return PolicyDecision(
            FileVerdict.SUSPICIOUS,
            engine_health,
            ExecutionDecision.REVIEW if review_required else ExecutionDecision.WARN,
            Verdict.SUSPICIOUS,
            score,
            "blocked_pending_review" if review_required else "warn",
            errors[0].name if errors else None,
        )
    if authoritative_unavailable and not authoritative_available:
        unavailable = next(
            (finding.name for finding in findings if finding.state == EngineState.SCANNER_UNAVAILABLE),
            "authoritative scanners unavailable",
        )
        return PolicyDecision(
            FileVerdict.UNKNOWN,
            engine_health,
            ExecutionDecision.REVIEW,
            Verdict.SCAN_ERROR,
            score,
            "blocked_pending_review",
            errors[0].name if errors else unavailable,
        )
    if errors:
        return PolicyDecision(
            FileVerdict.UNKNOWN,
            engine_health,
            ExecutionDecision.REVIEW,
            Verdict.SCAN_ERROR,
            score,
            "blocked_pending_review",
            errors[0].name,
        )
    if authoritative_available:
        return PolicyDecision(
            FileVerdict.CLEAN,
            engine_health,
            ExecutionDecision.ALLOW,
            Verdict.CLEAN,
            score,
            "allow",
            None,
        )
    return PolicyDecision(
        FileVerdict.UNKNOWN,
        engine_health,
        ExecutionDecision.REVIEW,
        Verdict.UNKNOWN,
        score,
        "allow_with_unknown_verdict",
        None,
    )


def decide(findings: list[Finding], allowed: bool) -> tuple[Verdict, int, str, str | None]:
    """Return the original four-field policy envelope for existing callers."""
    decision = evaluate(findings, allowed)
    return decision.verdict, decision.score, decision.action, decision.error
