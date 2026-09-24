from __future__ import annotations

import threading
import time
from typing import Literal

import pytest

from downstream.delegation.network_budget import (
    RequestBudget,
    RequestBudgetError,
    RequestCancelled,
    RequestDeadlineExceeded,
    RequestTimeouts,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_unresolved_provider_worker_keeps_account_capacity_reserved() -> None:
    budget = RequestBudget(
        max_in_flight=4,
        per_account_limit=2,
        reserved_interactive_slots=1,
    )
    lease = budget.reserve("trusted-account-scope", "inference")
    lease.worker_started()

    # The caller has timed out, but the provider worker has not exited. The
    # outcome is unresolved, so another alias on the same account must not
    # launch a retry while the original transport is still active.
    lease.finish(outcome="unknown")

    with pytest.raises(RequestBudgetError) as caught:
        budget.reserve("trusted-account-scope", "inference")
    assert caught.value.code == "request_outcome_unknown"
    assert budget.status()["requests"][0]["state"] == "outcome_unknown"

    lease.worker_finished()
    retry = budget.reserve("trusted-account-scope", "inference")
    retry.finish()


def test_maintenance_leaves_reserved_inference_capacity_for_same_account() -> None:
    budget = RequestBudget(per_account_limit=2, reserved_interactive_slots=1)
    background = budget.reserve("shared-account", "catalogue")
    with pytest.raises(RequestBudgetError) as caught:
        budget.reserve("shared-account", "embedding")
    assert caught.value.code == "account_capacity_full"

    interactive = budget.reserve("shared-account", "inference")
    assert budget.status()["active"] == 2
    background.finish()
    interactive.finish()


def test_progress_resets_read_idle_but_heartbeat_does_not_extend_total_deadline() -> None:
    clock = _Clock()
    budget = RequestBudget(
        monotonic_clock=clock,
        timeouts={"inference": RequestTimeouts(2, 5, 20)},
    )
    lease = budget.reserve("account", "inference")
    clock.now += 6
    lease.mark_progress()
    lease.check_active()

    clock.now += 6
    lease.heartbeat()
    with pytest.raises(RequestDeadlineExceeded) as idle:
        lease.check_active()
    assert idle.value.code == "read_idle_deadline"
    lease.finish(outcome="timeout")

    next_lease = budget.reserve("account", "inference")
    clock.now += 21
    next_lease.mark_progress()
    next_lease.heartbeat()
    with pytest.raises(RequestDeadlineExceeded) as total:
        next_lease.check_active()
    assert total.value.code == "total_deadline"
    next_lease.finish(outcome="timeout")


def test_total_deadline_timer_aborts_transport_and_reports_timeout() -> None:
    budget = RequestBudget(
        timeouts={"inference": RequestTimeouts(0.05, 0.1, 0.15)}
    )
    lease = budget.reserve("deadline-account", "inference")
    aborted = threading.Event()
    lease.set_abort_callback(lambda reason: aborted.set() if reason == "deadline" else None)

    assert aborted.wait(1.0)
    assert lease.cancelled is True
    assert lease.cancel_reason == "deadline"
    with pytest.raises(RequestDeadlineExceeded) as caught:
        lease.check_active()
    assert caught.value.code == "total_deadline"

    lease.finish(outcome="timeout")
    assert budget.status()["active"] == 0


def test_first_cancel_reason_is_preserved_and_abort_callback_runs_once() -> None:
    budget = RequestBudget()
    lease = budget.reserve("cancel-reason-account", "inference")
    reasons = []
    lease.set_abort_callback(reasons.append)

    assert budget.cancel(lease.request_id, reason="user_cancel") is True
    assert budget.cancel(lease.request_id, reason="deadline") is True

    assert reasons == ["user_cancel"]
    assert lease.cancel_reason == "user_cancel"
    with pytest.raises(RequestCancelled):
        lease.check_active()
    lease.finish(outcome="cancelled")


def test_external_cancel_reason_wins_over_later_budget_deadline() -> None:
    budget = RequestBudget()
    lease = budget.reserve("external-cancel-account", "inference")
    reasons = []
    lease.set_abort_callback(reasons.append)

    lease.note_cancelled("interrupt")
    assert budget.cancel(lease.request_id, reason="deadline") is True

    assert lease.cancel_reason == "interrupt"
    assert reasons == []
    with pytest.raises(RequestCancelled):
        lease.check_active()
    lease.finish(outcome="cancelled")


def test_abort_callback_registered_after_deadline_runs_immediately() -> None:
    budget = RequestBudget(
        timeouts={"inference": RequestTimeouts(0.05, 0.1, 0.15)}
    )
    lease = budget.reserve("late-abort-account", "inference")
    deadline = time.monotonic() + 1.0
    while not lease.cancelled and time.monotonic() < deadline:
        time.sleep(0.005)
    assert lease.cancelled is True

    reasons = []
    lease.set_abort_callback(reasons.append)
    assert reasons == ["deadline"]
    lease.finish(outcome="timeout")


def test_retry_after_cooldown_is_shared_across_provider_aliases_and_bounded() -> None:
    clock = _Clock()
    budget = RequestBudget(monotonic_clock=clock)
    first_alias = budget.reserve("one-account", "inference")
    capped = first_alias.record_retry_after(30 * 24 * 60 * 60)
    assert capped == 7 * 24 * 60 * 60
    first_alias.finish()

    with pytest.raises(RequestBudgetError) as caught:
        budget.reserve("one-account", "catalogue")
    assert caught.value.code == "account_cooldown"

    clock.now += capped
    second_alias = budget.reserve("one-account", "catalogue")
    second_alias.finish()


def test_status_is_bounded_and_does_not_expose_account_scope() -> None:
    account_scope = "private-admission-scope-do-not-project"
    budget = RequestBudget(max_in_flight=100)
    leases = [budget.reserve(f"{account_scope}-{index}") for index in range(63)]
    leases.append(budget.reserve("reserved-control", "control"))
    with pytest.raises(RequestBudgetError) as caught:
        budget.reserve(f"{account_scope}-overflow")
    assert caught.value.code == "capacity_full"

    status = budget.status()
    assert status["active"] == 64
    assert len(status["requests"]) == 64
    assert account_scope not in repr(status)
    assert all("account_scope" not in item for item in status["requests"])

    for lease in leases:
        lease.finish()


def test_status_and_cancel_stay_responsive_at_global_capacity() -> None:
    budget = RequestBudget(max_in_flight=100)
    leases = [budget.reserve(f"account-{index}") for index in range(63)]
    leases.append(budget.reserve("control-account", "control"))
    cancelled = []
    leases[0].set_abort_callback(lambda _reason: cancelled.append(True))

    started = time.monotonic()
    assert budget.status()["active"] == 64
    assert budget.cancel(leases[0].request_id)
    assert cancelled == [True]
    assert time.monotonic() - started < 0.5

    for lease in leases:
        lease.finish(outcome="cancelled")


def test_inference_leaves_one_global_control_slot() -> None:
    budget = RequestBudget(
        max_in_flight=2,
        per_account_limit=4,
        reserved_interactive_slots=1,
    )
    first = budget.reserve("first-account", operation="inference")
    try:
        with pytest.raises(RequestBudgetError) as full:
            budget.reserve("second-account", operation="inference")
        assert full.value.code == "capacity_reserved"

        control = budget.reserve("control-account", operation="control")
        try:
            assert budget.status()["active"] == 2
        finally:
            control.finish(outcome="success")
    finally:
        first.finish(outcome="success")


@pytest.mark.parametrize("operation", ["catalogue", "embedding"])
def test_maintenance_leaves_global_inference_and_control_capacity(
    operation: Literal["catalogue", "embedding"],
) -> None:
    budget = RequestBudget(
        max_in_flight=3,
        per_account_limit=4,
        reserved_interactive_slots=1,
    )
    maintenance = budget.reserve("maintenance-account", operation=operation)
    try:
        with pytest.raises(RequestBudgetError) as full:
            budget.reserve("second-maintenance-account", operation=operation)
        assert full.value.code == "maintenance_capacity_reserved"

        inference = budget.reserve("inference-account", operation="inference")
        control = budget.reserve("control-account", operation="control")
        try:
            assert budget.status()["active"] == 3
        finally:
            inference.finish(outcome="success")
            control.finish(outcome="success")
    finally:
        maintenance.finish(outcome="success")


def test_release_callback_does_not_hold_status_or_cancel_lock() -> None:
    budget = RequestBudget(per_account_limit=2, reserved_interactive_slots=1)
    finishing = budget.reserve("account-a", "inference")
    active = budget.reserve("account-b", "inference")
    callback_started = threading.Event()
    release_callback = threading.Event()
    cancelled = threading.Event()

    def slow_cleanup() -> None:
        callback_started.set()
        release_callback.wait(3.0)

    finishing.add_release_callback(slow_cleanup)
    active.set_abort_callback(lambda _reason: cancelled.set())
    finish_thread = threading.Thread(target=finishing.finish)
    finish_thread.start()
    try:
        assert callback_started.wait(1.0)
        started = time.monotonic()
        assert budget.status()["active"] == 1
        assert budget.cancel(active.request_id)
        assert cancelled.wait(1.0)
        assert time.monotonic() - started < 0.5
    finally:
        release_callback.set()
        finish_thread.join(timeout=3.0)
    assert not finish_thread.is_alive()
    active.finish(outcome="cancelled")


def test_retry_after_table_saturation_fails_closed_without_evicting_live_scope() -> None:
    clock = _Clock()
    budget = RequestBudget(monotonic_clock=clock)
    for index in range(1025):
        lease = budget.reserve(f"scope-{index}")
        lease.record_retry_after(60)
        lease.finish()

    with pytest.raises(RequestBudgetError) as caught:
        budget.reserve("new-scope")
    assert caught.value.code == "cooldown_capacity_full"

    clock.now += 60
    lease = budget.reserve("new-scope")
    lease.finish()


def test_request_id_collision_is_rejected_before_capacity_mutation() -> None:
    tokens = iter(("same-id", "same-id", "next-id"))
    budget = RequestBudget(random_token=lambda: next(tokens))
    original = budget.reserve("first-account")

    with pytest.raises(RequestBudgetError) as caught:
        budget.reserve("second-account")
    assert caught.value.code == "request_id_collision"
    assert budget.status()["active"] == 1

    next_lease = budget.reserve("second-account")
    assert next_lease.request_id == "next-id"
    original.finish()
    next_lease.finish()
