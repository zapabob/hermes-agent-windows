"""Deferred LM03 review points closed before a real destination writer exists.

G: the live grant is revalidated inside the claim transaction, so no revocation
can fall between the check and RUNNING.
W: a landed destination write leaves an append-only witness that survives the
owner being displaced before it can record the outcome.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import logging
import sqlite3

import pytest

from downstream.control_mcp.contracts import ControlError
from plugins.implementation_router.apply import VerifiedApplyOwner
from plugins.implementation_router.control import EngineeringRunOwner
from tests.control_mcp.test_review_approval_binding import (  # noqa: F401 - fixtures
    GRANT_OK,
    _release_human_sessions,
    db,
    effects,
    make_ctx,
    open_host,
    reserve_approved,
    state_of,
)
from tests.control_mcp.test_review_execute_apply import (  # noqa: F401 - fixtures
    CANDIDATE,
    HEAD_A,
    REF,
    approved_apply,
    chain,
    claim_code,
    ctx_with,
    reservations_of,
)


def writer_lock_held(db):
    """True when another connection cannot take the journal write lock right now."""
    with closing(sqlite3.connect(db, timeout=0, isolation_level=None)) as probe:
        try:
            probe.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError:
            return True
        probe.execute('ROLLBACK')
        return False


def engineering_owner(journal, revalidate, pool):
    return EngineeringRunOwner(journal=journal, plugin_ctx=object(), submit=pool.submit,
                               validate_intent=lambda _request: True,
                               verify_result=lambda *_a: True,
                               revalidate_grant=revalidate, clock=lambda: 112)


def apply_owner_with(journal, chain, revalidate):
    _calls, _execute_owner, _apply_owner, destination, receipts = chain
    return VerifiedApplyOwner(journal=journal, destination=destination, receipt_for=receipts,
                              revalidate_grant=revalidate, clock=lambda: 112)


def displace(db):
    """Another host takes the journal: this handle's epoch is no longer the open one."""
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("UPDATE control_owner_epochs SET closed_at=112,close_reason='restart' "
                     "WHERE closed_at IS NULL")
        conn.execute('INSERT INTO control_owner_epochs(epoch_id,opened_at,owner_pid) VALUES (?,112,0)',
                     ('e' * 32,))
        conn.commit()


def evidence_rows(db):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute('SELECT count(*) FROM control_effect_evidence').fetchone()[0]


# --- G: grant revalidation is part of the claim ----------------------------------------------

def test_g_the_grant_is_revalidated_while_the_claim_holds_the_journal_write_lock(db, effects):
    calls, _hooks, _owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    observed = []

    def revalidate(_ctx, *, now):
        observed.append(writer_lock_held(db))

    with ThreadPoolExecutor(max_workers=1) as pool:
        handle = engineering_owner(journal, revalidate, pool).start_approved(ctx, operation_id)
        assert handle.future.result(timeout=30)['state'] == 'SUCCEEDED'
    assert observed[0] is True
    assert len(calls) == 1


def test_g_a_grant_revoked_before_the_claim_blocks_with_zero_effect(db, effects):
    calls, _hooks, _owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)

    def revoked(_ctx, *, now):
        raise ControlError('revoked_grant')

    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = engineering_owner(journal, revoked, pool)
        assert claim_code(lambda: owner.start_approved(ctx, operation_id)) == 'revoked_grant'
    assert calls == []
    assert state_of(db, operation_id) == 'BLOCKED'
    assert reservations_of(db, operation_id) == 0


def test_g_any_grant_store_failure_is_a_revocation_never_a_claim(db, effects):
    calls, _hooks, _owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)

    def unavailable(_ctx, *, now):
        raise OSError('grant store unreadable')

    assert claim_code(lambda: journal.claim_approved(ctx, operation_id, now=112,
                                                     revalidate_grant=unavailable)) == 'revoked_grant'
    assert state_of(db, operation_id) == 'APPROVED'
    assert calls == []


def test_g_an_expired_token_is_refused_but_is_not_a_revocation(db, effects):
    calls, _hooks, _owner = effects
    journal = open_host(db)
    operation_id = reserve_approved(journal, make_ctx())
    expired = make_ctx(expires_at=100)
    consulted = []

    def revalidate(_ctx, *, now):
        consulted.append(now)

    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = engineering_owner(journal, revalidate, pool)
        assert claim_code(lambda: owner.start_approved(expired, operation_id)) == 'expired_grant'
    # A fresh token may still run the human's approval; it lapses only at its own expiry.
    assert (calls, consulted) == ([], [])
    assert state_of(db, operation_id) == 'APPROVED'
    assert reservations_of(db, operation_id) == 1


def test_g_a_revoked_apply_grant_never_consults_evidence_or_the_destination(db, chain):
    _calls, _execute_owner, _apply_owner, destination, receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    receipts.calls.clear()

    def revoked(_ctx, *, now):
        raise ControlError('revoked_grant')

    owner = apply_owner_with(journal, chain, revoked)
    assert claim_code(lambda: owner.start_approved(ctx, apply_op)) == 'revoked_grant'
    assert (receipts.calls, destination.calls, destination.applied) == ([], [], [])
    assert state_of(db, apply_op) == 'BLOCKED'
    assert reservations_of(db, apply_op) == 0


# --- W: a landed destination write is witnessed append-only --------------------------------

def test_w_a_write_landing_after_the_owner_was_displaced_is_still_witnessed(db, chain, caplog):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    recorder = journal._epoch_id
    swap = destination.compare_and_swap

    def swap_then_lose_the_journal(*args, **kwargs):
        new_head = swap(*args, **kwargs)
        displace(db)
        return new_head

    destination.compare_and_swap = swap_then_lose_the_journal
    with caplog.at_level(logging.WARNING):
        apply_owner(journal).start_approved(ctx, apply_op)
    assert destination.applied == [(REF, HEAD_A, CANDIDATE)]
    assert f'control operation {apply_op} not recorded: stale_owner_epoch' in caplog.text
    witness = [{'recorder_epoch': recorder, 'recorded_at': 112, 'evidence': {
        'outcome': 'destination_written', 'destination_ref': REF, 'previous_revision': HEAD_A,
        'new_revision': CANDIDATE[:40], 'candidate_digest': CANDIDATE}}]
    assert journal.effect_evidence(apply_op) == witness

    journal.close()
    successor = open_host(db)
    # Reconciliation still cannot claim to know the outcome, but the witness says it landed.
    assert state_of(db, apply_op) == 'UNKNOWN'
    assert reservations_of(db, apply_op) == 1
    assert successor.effect_evidence(apply_op) == witness


@pytest.mark.parametrize('outcome', ['applied', 'destination_changed', 'unclassified'])
def test_w_only_a_landed_write_is_witnessed_and_exactly_once(db, chain, outcome):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    if outcome == 'destination_changed':
        destination.before_swap = lambda: destination.heads.__setitem__(REF, '2' * 40)
    elif outcome == 'unclassified':
        def dropped():
            raise OSError('transport dropped')
        destination.before_swap = dropped
    try:
        apply_owner(journal).start_approved(ctx, apply_op)
    except ControlError:
        pass
    assert len(journal.effect_evidence(apply_op)) == (1 if outcome == 'applied' else 0)
    assert len(destination.applied) == (1 if outcome == 'applied' else 0)


@pytest.mark.parametrize('statement', ['UPDATE control_effect_evidence SET evidence_json=?',
                                       'DELETE FROM control_effect_evidence WHERE evidence_json<>?'])
def test_w_the_witness_is_append_only(db, chain, statement):
    _calls, _execute_owner, apply_owner, _destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    apply_owner(journal).start_approved(ctx, apply_op)
    before = journal.effect_evidence(apply_op)
    with closing(sqlite3.connect(db)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match='append_only'):
            conn.execute(statement, ('{}',))
    assert journal.effect_evidence(apply_op) == before


@pytest.mark.parametrize('change', [
    {'outcome': 'applied'},
    {'destination_ref': 'main'},
    {'previous_revision': 'HEAD'},
    {'new_revision': 'C:\\repo\\.git'},
    {'new_revision': 'c' * 64},
    {'candidate_digest': 'c' * 63},
    {'diagnostic': 'stderr'},
])
def test_w_a_witness_carries_only_validated_identity(db, chain, change):
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    evidence = {'outcome': 'destination_written', 'destination_ref': REF,
                'previous_revision': HEAD_A, 'new_revision': CANDIDATE[:40],
                'candidate_digest': CANDIDATE, **change}
    assert claim_code(lambda: journal.append_effect_evidence(apply_op, now=112, evidence=evidence)) \
        == 'invalid_effect_evidence'
    assert evidence_rows(db) == 0


def landed_evidence(**change):
    return {'outcome': 'destination_written', 'destination_ref': REF, 'previous_revision': HEAD_A,
            'new_revision': CANDIDATE[:40], 'candidate_digest': CANDIDATE, **change}


def running_apply(journal, ctx, chain):
    receipts = chain[4]
    apply_op, source, _run_id = approved_apply(journal, ctx, chain)
    journal.claim_apply(ctx, apply_op, revalidate_grant=GRANT_OK, receipt_for=receipts, now=112)
    return apply_op, source


@pytest.mark.parametrize('change', [
    {'destination_ref': 'refs/heads/release'},
    {'previous_revision': '2' * 40},
    {'candidate_digest': 'e' * 64},
])
def test_w_a_witness_must_match_the_approved_apply_intent(db, chain, change):
    journal = open_host(db)
    apply_op, _source = running_apply(journal, ctx_with(), chain)
    assert claim_code(lambda: journal.append_effect_evidence(
        apply_op, now=112, evidence=landed_evidence(**change))) == 'invalid_effect_evidence'
    assert evidence_rows(db) == 0
    journal.append_effect_evidence(apply_op, now=112, evidence=landed_evidence())
    assert evidence_rows(db) == 1


def test_w_only_a_claimed_apply_can_be_witnessed(db, chain):
    journal = open_host(db)
    ctx = ctx_with()
    approved, source, _run_id = approved_apply(journal, ctx, chain)
    for operation_id in (source, approved, 'op-' + '0' * 32):
        assert claim_code(lambda: journal.append_effect_evidence(
            operation_id, now=112, evidence=landed_evidence())) == 'operation_conflict'
    assert evidence_rows(db) == 0


@pytest.mark.parametrize('now', [float('nan'), float('inf'), '112', None])
def test_w_a_witness_time_must_be_a_finite_number(db, chain, now):
    journal = open_host(db)
    apply_op, _source = running_apply(journal, ctx_with(), chain)
    assert claim_code(lambda: journal.append_effect_evidence(
        apply_op, now=now, evidence=landed_evidence())) == 'invalid_effect_evidence'
    assert evidence_rows(db) == 0


def test_w_a_witness_failure_never_relabels_a_landed_write(db, chain, caplog, monkeypatch):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)

    def journal_busy(*_args, **_kwargs):
        raise ControlError('journal_unavailable')

    monkeypatch.setattr(journal, 'append_effect_evidence', journal_busy)
    with caplog.at_level(logging.WARNING):
        result = apply_owner(journal).start_approved(ctx, apply_op)
    assert result == {'state': 'SUCCEEDED', 'reason_code': 'applied'}
    assert state_of(db, apply_op) == 'SUCCEEDED'
    assert destination.applied == [(REF, HEAD_A, CANDIDATE)]
    assert f'destination write for {apply_op} not witnessed: journal_unavailable' in caplog.text


def test_w_a_closed_journal_handle_cannot_witness(db, chain):
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    journal.close()
    evidence = {'outcome': 'destination_written', 'destination_ref': REF,
                'previous_revision': HEAD_A, 'new_revision': CANDIDATE[:40],
                'candidate_digest': CANDIDATE}
    assert claim_code(lambda: journal.append_effect_evidence(apply_op, now=112, evidence=evidence)) \
        == 'owner_epoch_required'
    assert evidence_rows(db) == 0
