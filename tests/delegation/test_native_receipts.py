"""Native verification must bind owner, result bytes, and actual check exit facts."""

from dataclasses import replace

import pytest

from downstream.delegation.evidence import (
    NativeCheckResult,
    VerificationExpectation,
    VerificationReceipt,
    evaluate_native_receipt,
)


def _expected() -> VerificationExpectation:
    return VerificationExpectation(
        owner_epoch="epoch-1",
        operation_id="op-1",
        run_id="run-1",
        profile_id="profile-1",
        workspace_id="workspace-1",
        source_digest="a" * 64,
        result_digest="b" * 64,
        check_set_revision="c" * 64,
        required_checks=("unit", "lint"),
        platform="win32",
    )


def _receipt(expected: VerificationExpectation) -> VerificationReceipt:
    checks = tuple(
        NativeCheckResult(
            check_id=check_id,
            revision=expected.check_set_revision,
            exit_code=0,
            completed=True,
            timed_out=False,
            cleanup_confirmed=True,
            source_before=expected.source_digest,
            source_after=expected.source_digest,
            result_before=expected.result_digest,
            result_after=expected.result_digest,
        )
        for check_id in expected.required_checks
    )
    return VerificationReceipt(
        owner_epoch=expected.owner_epoch,
        operation_id=expected.operation_id,
        run_id=expected.run_id,
        profile_id=expected.profile_id,
        workspace_id=expected.workspace_id,
        source_digest=expected.source_digest,
        result_digest=expected.result_digest,
        check_set_revision=expected.check_set_revision,
        required_checks=expected.required_checks,
        checks=checks,
        process_exit_code=0,
        process_completed=True,
        process_timed_out=False,
        cleanup_confirmed=True,
        platform=expected.platform,
    )


def test_current_native_receipt_requires_all_host_checks_and_cleanup():
    expected = _expected()
    decision = evaluate_native_receipt(_receipt(expected), expected)
    assert decision.verified is True
    assert decision.reason == "verified"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("owner_epoch", "stale-epoch", "owner_changed"),
        ("operation_id", "foreign-op", "operation_mismatch"),
        ("run_id", "foreign-run", "run_mismatch"),
        ("profile_id", "foreign-profile", "profile_mismatch"),
        ("workspace_id", "foreign-workspace", "workspace_mismatch"),
        ("source_digest", "d" * 64, "source_changed"),
        ("result_digest", "d" * 64, "result_changed"),
        ("check_set_revision", "d" * 64, "check_set_changed"),
        ("platform", "linux", "platform_mismatch"),
    ),
)
def test_foreign_or_stale_receipt_is_not_verification(field, value, reason):
    expected = _expected()
    decision = evaluate_native_receipt(replace(_receipt(expected), **{field: value}), expected)
    assert decision.verified is False
    assert decision.reason == reason


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"process_exit_code": 1}, "process_failed"),
        ({"process_completed": False}, "process_incomplete"),
        ({"process_timed_out": True}, "process_timed_out"),
        ({"cleanup_confirmed": False}, "cleanup_unknown"),
    ),
)
def test_zero_exit_without_process_completion_and_cleanup_is_not_verification(changes, reason):
    expected = _expected()
    decision = evaluate_native_receipt(replace(_receipt(expected), **changes), expected)
    assert decision.verified is False
    assert decision.reason == reason


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        ({"exit_code": 1}, "check_failed"),
        ({"completed": False}, "check_incomplete"),
        ({"timed_out": True}, "check_timed_out"),
        ({"cleanup_confirmed": False}, "check_cleanup_unknown"),
        ({"revision": "d" * 64}, "check_set_changed"),
        ({"source_after": "d" * 64}, "source_changed"),
        ({"result_after": "d" * 64}, "result_changed"),
    ),
)
def test_check_result_must_be_complete_current_and_bound_to_bytes(change, reason):
    expected = _expected()
    receipt = _receipt(expected)
    altered = replace(receipt.checks[0], **change)
    decision = evaluate_native_receipt(replace(receipt, checks=(altered, receipt.checks[1])), expected)
    assert decision.verified is False
    assert decision.reason == reason


def test_missing_or_duplicate_protected_check_does_not_verify():
    expected = _expected()
    receipt = _receipt(expected)
    missing = replace(receipt, checks=receipt.checks[:1])
    duplicate = replace(receipt, checks=(receipt.checks[0], receipt.checks[0]))
    assert evaluate_native_receipt(missing, expected).verified is False
    assert evaluate_native_receipt(duplicate, expected).verified is False


def test_receipt_cannot_replace_or_erase_host_required_checks():
    expected = _expected()
    receipt = _receipt(expected)
    for claimed in ((), ("unit",), ("unit", "unit"), ("unit", "lint", "extra")):
        decision = evaluate_native_receipt(replace(receipt, required_checks=claimed), expected)
        assert decision.verified is False
        assert decision.reason == "check_set_changed"


def test_invalid_host_expectation_and_boolean_exit_are_not_positive_evidence():
    expected = _expected()
    receipt = _receipt(expected)
    assert evaluate_native_receipt(receipt, replace(expected, required_checks=())).verified is False
    invalid_digest = replace(expected, source_digest="invalid")
    assert evaluate_native_receipt(
        replace(receipt, source_digest="invalid"), invalid_digest
    ).reason == "invalid_receipt"
    assert evaluate_native_receipt(replace(receipt, process_exit_code=False), expected).verified is False
    changed = replace(receipt.checks[0], exit_code=False)
    assert evaluate_native_receipt(replace(receipt, checks=(changed, receipt.checks[1])), expected).verified is False
