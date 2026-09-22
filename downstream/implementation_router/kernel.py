"""Bounded engineering workflow contracts; execution authority remains host-owned.

This module contains no provider, credential, shell, plugin registration, or
resume implementation. HostPort is a trusted integration boundary, not an LLM
tool schema. Its receipts must be produced from actual host observations.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True)
class RunBinding:
    run_id: str
    workspace_id: str

    def __post_init__(self) -> None:
        if not all(_valid_token(value) for value in (self.run_id, self.workspace_id)):
            raise ValueError("Run and workspace identities must be bounded opaque tokens")


@dataclass(frozen=True)
class Policy:
    worker_retries: int = 1
    planner_reentry_limit: int = 1
    max_stage_calls: int = 8
    max_handoff_bytes: int = 32_768

    def __post_init__(self) -> None:
        for name, low, high in (
            ("worker_retries", 0, 8), ("planner_reentry_limit", 0, 4),
            ("max_stage_calls", 1, 64), ("max_handoff_bytes", 1024, 65_536),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in [{low}, {high}]")


@dataclass(frozen=True)
class StageRequest:
    binding: RunBinding
    attempt_id: str
    role: str
    revision: int
    handoff_json: str


@dataclass(frozen=True)
class StageResult:
    attempt_id: str
    state: str
    completed: bool
    output: str
    workspace_digest: str


@dataclass(frozen=True)
class VerificationRequest:
    binding: RunBinding
    attempt_id: str
    revision: int
    workspace_digest: str
    required_checks: tuple[str, ...]


@dataclass(frozen=True)
class CheckReceipt:
    check_id: str
    attempt_id: str
    run_id: str
    workspace_id: str
    revision: int
    exit_code: int
    completed: bool
    timed_out: bool
    approved: bool
    snapshot_before: str
    snapshot_after: str


@dataclass(frozen=True)
class AuditEvent:
    kind: str
    attempt_id: str
    revision: int
    role: str = ""
    payload_digest: str = ""


@dataclass(frozen=True)
class RunResult:
    state: str
    reason: str
    stage_calls: int
    revision: int
    events: tuple[AuditEvent, ...]


class HostPort(Protocol):
    """Trusted Hermes integration contracts, deliberately not implemented here.

    lease must exclusively bind the approved workspace, block previously
    uncertain runs, and validate routes/tool permissions before yielding.
    checkpoint must durably record intent before side effects. stage must bind
    immutable requests to actual completed child executions and report the
    effective workspace snapshot. verify must execute *operator-defined* check
    IDs through the canonical approval/terminal path. Exceptions never authorise
    a retry. cancellation_requested must observe host cancellation, not LLM text.

    No port may expose credentials in requests, results, exceptions, or receipts.
    An adapter that cannot satisfy a contract must refuse the run.
    """
    def lease(self, binding: RunBinding) -> AbstractContextManager[None]: ...
    def cancellation_requested(self, binding: RunBinding) -> bool: ...
    def checkpoint(self, binding: RunBinding, event: AuditEvent) -> None: ...
    def stage(self, request: StageRequest) -> StageResult: ...
    def verify(self, request: VerificationRequest) -> tuple[CheckReceipt, ...]: ...


class _Hold(Exception):
    pass


class _Cancelled(Exception):
    pass


def _valid_token(value: object) -> bool:
    return isinstance(value, str) and bool(_TOKEN.fullmatch(value)) and ".." not in value


def _text(value: object, *, maximum: int = 16_000) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _Hold("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise _Hold("non_finite_json_value")


def _decode(output: object, limit: int) -> dict:
    if not isinstance(output, str) or len(output.encode("utf-8")) > limit:
        raise _Hold("invalid_or_oversized_output")
    try:
        parsed = json.loads(output, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise _Hold("invalid_json_output") from exc
    if type(parsed) is not dict:
        raise _Hold("output_must_be_an_object")
    return parsed


def _plan(output: object, limit: int) -> dict:
    value = _decode(output, limit)
    fields = {"objective", "constraints", "steps", "acceptance_criteria"}
    if set(value) != fields or not _text(value.get("objective")):
        raise _Hold("invalid_plan_contract")
    for field in fields - {"objective"}:
        values = value[field]
        if type(values) is not list or not 1 <= len(values) <= 64 or not all(_text(x) for x in values):
            raise _Hold("invalid_plan_contract")
    return value


def _worker(output: object, limit: int) -> dict:
    value = _decode(output, limit)
    if set(value) != {"status", "summary", "decision_required"}:
        raise _Hold("invalid_worker_contract")
    if value["status"] not in ("READY", "BLOCKED") or not _text(value["summary"]):
        raise _Hold("invalid_worker_contract")
    decision = value["decision_required"]
    if not isinstance(decision, str) or len(decision) > 16_000:
        raise _Hold("invalid_worker_contract")
    if (value["status"] == "BLOCKED") != bool(decision.strip()):
        raise _Hold("invalid_worker_contract")
    return value


def _verification_failures(request: VerificationRequest, receipts: object) -> tuple[str, ...]:
    if type(receipts) is not tuple or len(receipts) != len(request.required_checks):
        raise _Hold("incomplete_verification")
    seen: set[str] = set()
    failures: list[str] = []
    for receipt in receipts:
        if type(receipt) is not CheckReceipt:
            raise _Hold("untrusted_verification_receipt")
        if (
            receipt.check_id not in request.required_checks or receipt.check_id in seen
            or receipt.attempt_id != request.attempt_id
            or receipt.run_id != request.binding.run_id
            or receipt.workspace_id != request.binding.workspace_id
            or type(receipt.revision) is not int or receipt.revision != request.revision
            or receipt.snapshot_before != request.workspace_digest
            or receipt.snapshot_after != request.workspace_digest
        ):
            raise _Hold("verification_binding_mismatch")
        if (
            receipt.completed is not True or receipt.timed_out is not False
            or receipt.approved is not True or type(receipt.exit_code) is not int
        ):
            raise _Hold("verification_not_conclusively_complete")
        seen.add(receipt.check_id)
        if receipt.exit_code != 0:
            failures.append(receipt.check_id)
    if seen != set(request.required_checks):
        raise _Hold("incomplete_verification")
    return tuple(failures)


class ImplementationRouter:
    """A stateless factory for bounded, single-run workflow executions."""
    def __init__(self, policy: Policy | None = None) -> None:
        self.policy = policy if policy is not None else Policy()
        if type(self.policy) is not Policy:
            raise ValueError("policy must be a validated Policy")

    def run(
        self, *, task: str, binding: RunBinding,
        required_checks: tuple[str, ...], host: HostPort,
    ) -> RunResult:
        events: list[AuditEvent] = []
        calls = 0
        revision = 1

        def result(state: str, reason: str) -> RunResult:
            return RunResult(state, reason, calls, revision, tuple(events))

        def cancellation_gate() -> None:
            requested = host.cancellation_requested(binding)
            if type(requested) is not bool:
                raise _Hold("invalid_cancellation_state")
            if requested:
                raise _Cancelled()

        def record(kind: str, attempt: str, role: str = "", payload: str = "") -> None:
            event = AuditEvent(kind, attempt, revision, role,
                               hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else "")
            # Do not append an event as durable when its write failed.
            host.checkpoint(binding, event)
            events.append(event)

        def stage(role: str, handoff: dict) -> StageResult:
            nonlocal calls
            cancellation_gate()
            if calls >= self.policy.max_stage_calls:
                raise _Hold("stage_call_budget_exhausted")
            encoded = _canonical(handoff)
            if len(encoded.encode("utf-8")) > self.policy.max_handoff_bytes:
                raise _Hold("handoff_budget_exhausted")
            attempt = f"{binding.run_id}:stage:{calls + 1}"
            request = StageRequest(binding, attempt, role, revision, encoded)
            record("stage_start", attempt, role, encoded)
            cancellation_gate()
            calls += 1
            response = host.stage(request)
            if type(response) is not StageResult or response.attempt_id != attempt:
                raise _Hold("stage_binding_mismatch")
            if response.state in ("CANCELLED", "INTERRUPTED"):
                raise _Cancelled()
            if response.completed is not True or response.state != "SUCCEEDED":
                raise _Hold("stage_completion_uncertain")
            cancellation_gate()
            record("stage_complete", attempt, role)
            return response

        try:
            if type(binding) is not RunBinding or not _text(task):
                raise _Hold("invalid_run_input")
            if (type(required_checks) is not tuple or not required_checks
                    or not all(_valid_token(check) for check in required_checks)
                    or len(required_checks) > 64 or len(set(required_checks)) != len(required_checks)):
                raise _Hold("invalid_required_checks")
            with host.lease(binding):
                cancellation_gate()
                plan = _plan(stage("planner", {"task": task}).output, self.policy.max_handoff_bytes)
                reentries = 0
                retries = 0
                feedback: dict = {}
                while True:
                    response = stage("worker", {"task": task, "plan": plan, "feedback": feedback})
                    worker = _worker(response.output, self.policy.max_handoff_bytes)
                    if worker["status"] == "BLOCKED":
                        feedback = {"kind": "design_blocker", "decision_required": worker["decision_required"]}
                    else:
                        if not isinstance(response.workspace_digest, str) or not _DIGEST.fullmatch(response.workspace_digest):
                            raise _Hold("missing_workspace_snapshot")
                        cancellation_gate()
                        verify_request = VerificationRequest(
                            binding, f"{response.attempt_id}:verify", revision,
                            response.workspace_digest, required_checks,
                        )
                        record("verification_start", verify_request.attempt_id)
                        cancellation_gate()
                        failures = _verification_failures(verify_request, host.verify(verify_request))
                        cancellation_gate()
                        record("verification_complete", verify_request.attempt_id)
                        if not failures:
                            cancellation_gate()
                            completed_attempt = verify_request.attempt_id
                            break
                        feedback = {"kind": "verification_failed", "failed_checks": list(failures)}
                        if retries < self.policy.worker_retries:
                            retries += 1
                            continue
                    if reentries >= self.policy.planner_reentry_limit:
                        raise _Hold("planner_reentry_budget_exhausted")
                    reentries += 1
                    revision += 1
                    retries = 0
                    plan = _plan(stage("reviewer", {
                        "task": task, "previous_plan": plan, "feedback": feedback,
                    }).output, self.policy.max_handoff_bytes)
                    feedback = {}
            # A failed lease finalisation must not leave a success receipt.
            cancellation_gate()
            record("succeeded", completed_attempt)
            return result("SUCCEEDED", "all_required_host_checks_passed")
        except _Cancelled:
            return result("CANCELLED", "host_cancellation")
        except _Hold as exc:
            return result("BLOCKED", str(exc))
        except Exception:
            # An exception may follow an accepted side effect. Never replay it,
            # and never expose provider messages or credentials in the receipt.
            return result("BLOCKED", "host_boundary_error_no_replay")
