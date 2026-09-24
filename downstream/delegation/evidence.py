"""Host-owned native verification evidence for delegated results."""

from __future__ import annotations

from dataclasses import dataclass
import re


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class NativeCheckResult:
    check_id: str
    revision: str
    exit_code: int | None
    completed: bool
    timed_out: bool
    cleanup_confirmed: bool
    source_before: str
    source_after: str
    result_before: str
    result_after: str


@dataclass(frozen=True, slots=True)
class VerificationReceipt:
    owner_epoch: str
    operation_id: str
    run_id: str
    profile_id: str
    workspace_id: str
    source_digest: str
    result_digest: str
    check_set_revision: str
    required_checks: tuple[str, ...]
    checks: tuple[NativeCheckResult, ...]
    process_exit_code: int | None
    process_completed: bool
    process_timed_out: bool
    cleanup_confirmed: bool
    platform: str


@dataclass(frozen=True, slots=True)
class VerificationExpectation:
    owner_epoch: str
    operation_id: str
    run_id: str
    profile_id: str
    workspace_id: str
    source_digest: str
    result_digest: str
    check_set_revision: str
    required_checks: tuple[str, ...]
    platform: str


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    verified: bool
    reason: str


def evaluate_native_receipt(
    receipt: VerificationReceipt,
    expected: VerificationExpectation,
) -> VerificationDecision:
    """Check host-produced facts against the current host expectation.

    This checks consistency only. The caller must obtain the receipt from the
    native producer, never from an MCP client or delegated child.
    """
    if not isinstance(receipt, VerificationReceipt) or not isinstance(expected, VerificationExpectation):
        return VerificationDecision(False, "invalid_receipt")

    bindings = (
        ("owner_epoch", "owner_changed"),
        ("operation_id", "operation_mismatch"),
        ("run_id", "run_mismatch"),
        ("profile_id", "profile_mismatch"),
        ("workspace_id", "workspace_mismatch"),
        ("source_digest", "source_changed"),
        ("result_digest", "result_changed"),
        ("check_set_revision", "check_set_changed"),
        ("platform", "platform_mismatch"),
    )
    for field, reason in bindings:
        actual, wanted = getattr(receipt, field), getattr(expected, field)
        if not isinstance(actual, str) or not actual or not isinstance(wanted, str) or not wanted:
            return VerificationDecision(False, "invalid_receipt")
        if actual != wanted:
            return VerificationDecision(False, reason)

    if any(not _SHA256.fullmatch(getattr(expected, field)) for field in
           ("source_digest", "result_digest", "check_set_revision")):
        return VerificationDecision(False, "invalid_receipt")
    if receipt.process_exit_code != 0 or type(receipt.process_exit_code) is not int:
        return VerificationDecision(False, "process_failed")
    if receipt.process_completed is not True:
        return VerificationDecision(False, "process_incomplete")
    if receipt.process_timed_out is not False:
        return VerificationDecision(False, "process_timed_out")
    if receipt.cleanup_confirmed is not True:
        return VerificationDecision(False, "cleanup_unknown")

    required = expected.required_checks
    if (not isinstance(required, tuple) or not required
            or any(not isinstance(item, str) or not item for item in required)
            or len(set(required)) != len(required)):
        return VerificationDecision(False, "invalid_check_set")
    if receipt.required_checks != required:
        return VerificationDecision(False, "check_set_changed")
    if (not isinstance(receipt.checks, tuple)
            or len(receipt.checks) != len(required)
            or any(not isinstance(check, NativeCheckResult) for check in receipt.checks)):
        return VerificationDecision(False, "check_set_incomplete")
    if any(not isinstance(check.check_id, str) or not check.check_id for check in receipt.checks):
        return VerificationDecision(False, "check_set_incomplete")
    if {check.check_id for check in receipt.checks} != set(required):
        return VerificationDecision(False, "check_set_incomplete")
    for check in receipt.checks:
        if check.exit_code != 0 or type(check.exit_code) is not int:
            return VerificationDecision(False, "check_failed")
        if check.completed is not True:
            return VerificationDecision(False, "check_incomplete")
        if check.timed_out is not False:
            return VerificationDecision(False, "check_timed_out")
        if check.cleanup_confirmed is not True:
            return VerificationDecision(False, "check_cleanup_unknown")
        if check.revision != expected.check_set_revision:
            return VerificationDecision(False, "check_set_changed")
        if check.source_before != expected.source_digest or check.source_after != expected.source_digest:
            return VerificationDecision(False, "source_changed")
        if check.result_before != expected.result_digest or check.result_after != expected.result_digest:
            return VerificationDecision(False, "result_changed")
    return VerificationDecision(True, "verified")
