"""LM05 / RV06: approval to execute in scratch never authorises applying the result.

Contract: docs/windows/workstation-20260924/cursor-handoff/F01_AUTHORITY_CONTRACT.md
sections 7.4 and 8.4. Execute, apply, PR creation, merge and deployment are
separate operations with separate scopes, rows and human decisions. A verified
receipt is evidence for the apply decision, never authority. Destination
effects are counted at the destination port.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
import threading

import pytest

from downstream.control_mcp import journal as journal_mod
from downstream.control_mcp.contracts import (ControlError, VerifiedResultReceipt,
                                              canonical_intent_digest, require_access)
from downstream.control_mcp.coordinator import HostControlCoordinator
from plugins.implementation_router.apply import VerifiedApplyOwner
from tests.control_mcp.test_review_approval_binding import (  # noqa: F401 - fixtures
    GRANT_OK,
    SOURCE,
    _SESSIONS,
    _release_human_sessions,
    approve,
    db,
    effects,
    make_ctx,
    make_request,
    open_host,
    state_of,
    ui_digest,
)
from tools import approval

APPLY = 'apply_verified_result'
REF = 'refs/heads/main'
HEAD_A = '1' * 40
HEAD_B = '2' * 40
CANDIDATE = 'c' * 64
VERIFICATION = 'd' * 64
SCOPES = ('hermes:read', 'hermes:run:start', 'hermes:workspace:apply')


class Destination:
    """A destination ref with compare-and-swap; counts effects that actually landed."""

    def __init__(self):
        self.heads = {REF: HEAD_A}
        self.calls = []
        self.applied = []
        self.before_swap = lambda: None

    def head(self, ref):
        self.calls.append(('head', ref))
        return self.heads[ref]

    def compare_and_swap(self, ref, *, expected, candidate_digest):
        self.calls.append(('cas', ref, expected, candidate_digest))
        self.before_swap()
        if self.heads[ref] != expected:
            raise ControlError('destination_changed')
        new_head = candidate_digest[:40]
        self.heads[ref] = new_head
        self.applied.append((ref, expected, candidate_digest))
        return new_head

    def push(self, *_args, **_kwargs):
        self.calls.append(('push',))
        raise AssertionError('apply must never push')


class Receipts:
    """Trusted verification evidence as the host verifier would publish it."""

    def __init__(self):
        self.by_run = {}
        self.calls = []

    def publish(self, source_operation_id, run_id, *, candidate=CANDIDATE,
                verification=VERIFICATION, verified=True):
        self.by_run[(source_operation_id, run_id)] = VerifiedResultReceipt(
            source_operation_id=source_operation_id, run_id=run_id,
            candidate_digest=candidate, verification_digest=verification, verified=verified)

    def __call__(self, profile_id, workspace_id, source_operation_id, run_id):
        self.calls.append((profile_id, workspace_id, source_operation_id, run_id))
        return self.by_run.get((source_operation_id, run_id))


@pytest.fixture
def chain(effects):
    """Production execute owner plus the apply owner over a counted destination."""
    calls, hooks, execute_owner = effects
    destination = Destination()
    receipts = Receipts()

    def apply_owner(journal, clock=lambda: 112):
        return VerifiedApplyOwner(journal=journal, destination=destination, receipt_for=receipts,
                                  revalidate_grant=lambda _ctx, *, now: None, clock=clock)

    return calls, execute_owner, apply_owner, destination, receipts


def ctx_with(*extra):
    return make_ctx(scopes=SCOPES + extra)


def executed(journal, ctx, execute_owner, workspace='w1'):
    """Human approves EXECUTE; the bounded worker succeeds in scratch."""
    operation_id = journal.reserve(ctx, make_request(workspace), now=100)['operation_id']
    approve(journal, ctx, operation_id)
    result = execute_owner(journal).start_approved(ctx, operation_id).future.result(timeout=30)
    assert result['state'] == 'SUCCEEDED'
    return operation_id, result['run_id']


def apply_request(source_operation_id, run_id, *, workspace='w1', key=None, head=HEAD_A,
                  candidate=CANDIDATE, verification=VERIFICATION, ref=REF):
    return {'kind': APPLY, 'profile_id': 'p1', 'workspace_id': workspace,
            'idempotency_key': key or f'apply-{workspace}', 'expected_revision': head,
            'source_sha': SOURCE,
            'parameters': {'source_operation_id': source_operation_id, 'source_run_id': run_id,
                           'candidate_digest': candidate, 'verification_digest': verification,
                           'destination_ref': ref}}


def verified_scratch_result(journal, ctx, chain, workspace='w1'):
    _calls, execute_owner, _apply_owner, _destination, receipts = chain
    source, run_id = executed(journal, ctx, execute_owner, workspace)
    receipts.publish(source, run_id)
    return source, run_id


def approved_apply(journal, ctx, chain, workspace='w1', **changes):
    source, run_id = verified_scratch_result(journal, ctx, chain, workspace)
    request = apply_request(source, run_id, workspace=workspace, **changes)
    operation_id = journal.reserve(ctx, request, now=120)['operation_id']
    approve(journal, ctx, operation_id, session=f'lm05-{workspace}')
    return operation_id, source, run_id


def kinds_in(db):
    with closing(sqlite3.connect(db)) as conn:
        return [row[0] for row in conn.execute('SELECT kind FROM control_operations')]


def result_of(db, operation_id):
    with closing(sqlite3.connect(db)) as conn:
        raw = conn.execute('SELECT result_json FROM control_operations WHERE operation_id=?',
                           (operation_id,)).fetchone()[0]
    return None if raw is None else json.loads(raw)


def reservations_of(db, operation_id):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute('SELECT count(*) FROM control_reservations WHERE operation_id=?',
                            (operation_id,)).fetchone()[0]


def retag(db, operation_id, kind):
    """Stand-in for a future admitted kind: the same stored row, re-kinded consistently."""
    with closing(sqlite3.connect(db)) as conn:
        request = json.loads(conn.execute('SELECT request_json FROM control_operations WHERE operation_id=?',
                                          (operation_id,)).fetchone()[0])
        request['kind'] = kind
        conn.execute('UPDATE control_operations SET kind=?,request_json=?,intent_digest=? WHERE operation_id=?',
                     (kind, json.dumps(request), canonical_intent_digest(request), operation_id))
        conn.commit()


def claim_code(call):
    with pytest.raises(ControlError) as denied:
        call()
    return denied.value.code


# --- A1 execute approval cannot apply ----------------------------------------------------------

def test_a1_execute_approval_and_passing_verification_never_apply(db, chain):
    _calls, _execute_owner, apply_owner, destination, receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    source, run_id = verified_scratch_result(journal, ctx, chain)

    # Worker "done" and verification PASS create no apply operation on their own.
    assert kinds_in(db) == ['start_engineering_run']
    assert destination.calls == []

    apply_op = journal.reserve(ctx, apply_request(source, run_id), now=120)['operation_id']
    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, apply_op)) == 'deny_no_apply_approval'
    assert state_of(db, apply_op) == 'PENDING_APPROVAL'
    assert (destination.heads[REF], destination.applied, receipts.calls) == (HEAD_A, [], [])


def test_a1_apply_owner_given_the_execute_operation_cannot_apply(db, chain):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    source, _run_id = verified_scratch_result(journal, ctx, chain)
    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, source)) == 'operation_kind_mismatch'
    assert state_of(db, source) == 'SUCCEEDED'
    assert destination.applied == []


# --- A2 a valid receipt is evidence, not authority --------------------------------------------

def test_a2_valid_receipt_does_not_mint_apply_approval(db, chain):
    _calls, _execute_owner, apply_owner, destination, receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    source, run_id = verified_scratch_result(journal, ctx, chain)
    receipt = receipts.by_run[(source, run_id)]
    assert receipt.verified is True
    apply_op = journal.reserve(ctx, apply_request(source, run_id), now=120)['operation_id']

    assert claim_code(lambda: journal.claim_apply(ctx, apply_op, revalidate_grant=GRANT_OK, receipt_for=lambda *_a: receipt,
                                                  now=112)) == 'deny_no_apply_approval'
    assert claim_code(lambda: journal.approve(ctx, apply_op, receipt, now=112)) == 'approval_required'
    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, apply_op)) == 'deny_no_apply_approval'
    assert state_of(db, apply_op) == 'PENDING_APPROVAL'
    assert destination.applied == []


# --- A3 apply approval is bound to the destination head ---------------------------------------

def test_a3_destination_moved_before_apply_blocks_with_zero_effect(db, chain):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    destination.heads[REF] = HEAD_B

    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, apply_op)) == 'destination_changed'
    assert [call for call in destination.calls if call[0] == 'cas'] == []
    assert (destination.heads[REF], destination.applied) == (HEAD_B, [])
    assert state_of(db, apply_op) == 'BLOCKED'
    assert result_of(db, apply_op) == {'state': 'BLOCKED', 'reason_code': 'destination_changed'}
    assert reservations_of(db, apply_op) == 0


def test_a3_destination_moving_during_apply_is_caught_by_the_compare_and_swap(db, chain):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    destination.before_swap = lambda: destination.heads.__setitem__(REF, HEAD_B)

    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, apply_op)) == 'destination_changed'
    assert ('cas', REF, HEAD_A, CANDIDATE) in destination.calls
    assert (destination.heads[REF], destination.applied) == (HEAD_B, [])
    assert state_of(db, apply_op) == 'BLOCKED'
    assert result_of(db, apply_op) == {'state': 'BLOCKED', 'reason_code': 'destination_changed'}


# --- A4 apply approval is bound to the verified source result ---------------------------------

def test_a4_apply_naming_a_result_the_source_operation_did_not_produce_is_refused(db, chain):
    journal = open_host(db)
    ctx = ctx_with()
    source, run_id = verified_scratch_result(journal, ctx, chain)
    other_run = 'eng-' + 'f' * 32
    assert claim_code(lambda: journal.reserve(ctx, apply_request(source, other_run), now=120)) \
        == 'source_result_mismatch'
    assert claim_code(lambda: journal.reserve(ctx, apply_request('op-' + 'f' * 32, run_id), now=120)) \
        == 'source_result_mismatch'
    assert kinds_in(db) == ['start_engineering_run']


def test_a4_receipt_for_a_different_result_cannot_be_applied(db, chain):
    _calls, _execute_owner, apply_owner, destination, receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, source, run_id = approved_apply(journal, ctx, chain)
    other_op, other_run = verified_scratch_result(journal, ctx, chain, workspace='w2')
    receipts.by_run[(source, run_id)] = receipts.by_run[(other_op, other_run)]

    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, apply_op)) == 'source_result_mismatch'
    assert destination.applied == []
    assert state_of(db, apply_op) == 'APPROVED'


# --- A5 an operation id cannot cross operation kinds ------------------------------------------

def test_a5_execute_and_apply_operation_ids_cannot_cross_owners(db, chain):
    calls, execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    native_before = len(calls)
    assert claim_code(lambda: execute_owner(journal).start_approved(ctx, apply_op)) == 'operation_kind_mismatch'
    assert len(calls) == native_before
    assert state_of(db, apply_op) == 'APPROVED'

    execute_op = journal.reserve(ctx, make_request('w2'), now=100)['operation_id']
    approve(journal, ctx, execute_op, session='lm05-exec')
    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, execute_op)) == 'operation_kind_mismatch'
    assert state_of(db, execute_op) == 'APPROVED'
    assert destination.applied == []


def test_a5_consumed_execute_decision_cannot_approve_an_apply(db, chain):
    _calls, _execute_owner, _apply_owner, _destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    source, run_id = verified_scratch_result(journal, ctx, chain, workspace='w2')
    execute_op = journal.reserve(ctx, make_request('w1'), now=100)['operation_id']
    binding = journal.approval_binding(ctx, execute_op, now=110)
    seen = []
    approval.register_gateway_notify('lm05-replay', seen.append)
    _SESSIONS.add('lm05-replay')
    ticket = approval.request_control_consent(binding, session_key='lm05-replay',
                                              timeout_seconds=60, now=110)
    assert approval.resolve_control_consent(
        session_key='lm05-replay', request_id=ticket.request_id, intent_digest=binding.intent_digest,
        choice='once', presentation_digest=ui_digest(seen[0]), now=111)
    decision = approval.take_control_decision(ticket, now=111)
    assert journal.approve(ctx, execute_op, decision, now=111)['state'] == 'APPROVED'

    apply_op = journal.reserve(ctx, apply_request(source, run_id, workspace='w2'), now=120)['operation_id']
    assert claim_code(lambda: journal.approve(ctx, apply_op, decision, now=112)) == 'approval_required'
    assert state_of(db, apply_op) == 'PENDING_APPROVAL'


# --- A6 apply approval is consumed once (LM04 claim) ------------------------------------------

def test_a6_two_apply_attempts_produce_exactly_one_destination_effect(db, chain):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, source, run_id = approved_apply(journal, ctx, chain)
    owners = [apply_owner(journal), apply_owner(journal)]
    gate = threading.Barrier(len(owners))

    def attempt(owner):
        gate.wait()
        try:
            return owner.start_approved(ctx, apply_op)
        except ControlError as exc:
            return exc.code

    with ThreadPoolExecutor(len(owners)) as pool:
        outcomes = list(pool.map(attempt, owners))
    assert sorted(o if isinstance(o, str) else o['state'] for o in outcomes) == ['SUCCEEDED', 'operation_conflict']
    assert destination.applied == [(REF, HEAD_A, CANDIDATE)]
    assert state_of(db, apply_op) == 'SUCCEEDED'
    assert claim_code(lambda: owners[0].start_approved(ctx, apply_op)) == 'operation_conflict'
    replay = journal.reserve(ctx, apply_request(source, run_id), now=130)
    assert (replay['operation_id'], replay['state']) == (apply_op, 'SUCCEEDED')
    assert replay['result'] == {'state': 'SUCCEEDED', 'reason_code': 'applied'}
    assert len(destination.applied) == 1


# --- A7 verification that changed after approval requires re-verification --------------------

@pytest.mark.parametrize('changes', [
    {'candidate': 'e' * 64},
    {'verification': 'e' * 64},
    {'verified': False},
])
def test_a7_changed_verification_requires_reverification(db, chain, changes):
    _calls, _execute_owner, apply_owner, destination, receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, source, run_id = approved_apply(journal, ctx, chain)
    receipts.publish(source, run_id, **changes)
    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, apply_op)) == 'reverify_required'
    assert destination.applied == []
    assert state_of(db, apply_op) == 'APPROVED'


def test_a7_missing_or_untrusted_receipt_never_applies(db, chain):
    _calls, _execute_owner, _apply_owner, destination, receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, source, run_id = approved_apply(journal, ctx, chain)
    receipt = receipts.by_run[(source, run_id)]
    forged = {field: getattr(receipt, field) for field in receipt.__dataclass_fields__}
    assert claim_code(lambda: journal.claim_apply(ctx, apply_op, revalidate_grant=GRANT_OK, receipt_for=lambda *_a: None,
                                                  now=112)) == 'reverify_required'
    assert claim_code(lambda: journal.claim_apply(ctx, apply_op, revalidate_grant=GRANT_OK, receipt_for=lambda *_a: forged,
                                                  now=112)) == 'untrusted_receipt'
    assert state_of(db, apply_op) == 'APPROVED'
    assert destination.applied == []


def test_a7_a_failing_or_absent_verifier_means_reverification(db, chain):
    _calls, _execute_owner, _apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)

    def broken(*_args):
        raise RuntimeError('verifier unavailable')

    assert claim_code(lambda: journal.claim_apply(ctx, apply_op, revalidate_grant=GRANT_OK, receipt_for=broken,
                                                  now=112)) == 'reverify_required'
    assert claim_code(lambda: journal.claim_effect(ctx, apply_op, kind=APPLY, now=112,
                                                      revalidate_grant=GRANT_OK)) \
        == 'reverify_required'
    assert state_of(db, apply_op) == 'APPROVED'
    assert destination.applied == []


def test_an_unclassified_destination_failure_is_unknown_and_keeps_the_workspace(db, chain):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)

    def lost_connection():
        raise OSError('transport dropped after send')

    destination.before_swap = lost_connection
    assert claim_code(lambda: apply_owner(journal).start_approved(ctx, apply_op)) == 'apply_outcome_unknown'
    assert state_of(db, apply_op) == 'UNKNOWN'
    assert result_of(db, apply_op) is None
    assert reservations_of(db, apply_op) == 1


# --- A8 / A9 / A10 each later stage is its own approved operation ------------------------------

def test_a8_local_apply_neither_pushes_nor_opens_a_pull_request(db, chain):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with('hermes:repo:pr')
    applied, _source, _run_id = approved_apply(journal, ctx, chain)
    assert apply_owner(journal).start_approved(ctx, applied)['state'] == 'SUCCEEDED'
    assert ('push',) not in destination.calls
    assert claim_code(lambda: journal.claim_effect(ctx, applied, kind='create_pull_request', now=113,
                                                      revalidate_grant=GRANT_OK)) \
        == 'operation_kind_mismatch'

    pending, _s, _r = approved_apply(journal, ctx, chain, workspace='w2')
    assert claim_code(lambda: journal.claim_effect(ctx, pending, kind='create_pull_request', now=113,
                                                      revalidate_grant=GRANT_OK)) \
        == 'operation_kind_mismatch'
    assert state_of(db, pending) == 'APPROVED'
    pr_request = {**make_request('w3'), 'kind': 'create_pull_request'}
    assert claim_code(lambda: journal.reserve(ctx, pr_request, now=120)) == 'unsupported_operation'


@pytest.mark.parametrize('approved_kind, requested_kind', [
    ('create_pull_request', 'merge_pull_request'),
    ('merge_pull_request', 'deploy'),
    ('create_pull_request', 'deploy'),
])
def test_a9_a10_approval_of_one_stage_never_claims_the_next(db, chain, approved_kind, requested_kind):
    journal = open_host(db)
    ctx = ctx_with('hermes:repo:pr', 'hermes:repo:merge', 'hermes:deploy')
    operation_id, _source, _run_id = approved_apply(journal, ctx, chain)
    retag(db, operation_id, approved_kind)
    assert claim_code(lambda: journal.claim_effect(ctx, operation_id, kind=requested_kind, now=113,
                                                      revalidate_grant=GRANT_OK)) \
        == 'operation_kind_mismatch'
    assert state_of(db, operation_id) == 'APPROVED'


@pytest.mark.parametrize('kind', ['create_pull_request', 'merge_pull_request', 'deploy'])
def test_a9_a10_a_stage_without_an_integrated_owner_is_never_claimed(db, chain, kind):
    journal = open_host(db)
    ctx = ctx_with('hermes:repo:pr', 'hermes:repo:merge', 'hermes:deploy')
    operation_id, _source, _run_id = approved_apply(journal, ctx, chain)
    retag(db, operation_id, kind)
    assert claim_code(lambda: journal.claim_effect(ctx, operation_id, kind=kind, now=113,
                                                      revalidate_grant=GRANT_OK)) \
        == 'unsupported_operation'
    assert state_of(db, operation_id) == 'APPROVED'


def test_a9_a10_every_effect_stage_needs_its_own_scope():
    stages = journal_mod.EFFECT_STAGES
    assert {'start_engineering_run', APPLY, 'create_pull_request', 'merge_pull_request', 'deploy'} <= set(stages)
    scopes = [journal_mod.SCOPES[stage] for stage in stages]
    assert len(set(scopes)) == len(scopes)
    for held in stages:
        ctx = make_ctx(scopes=('hermes:read', journal_mod.SCOPES[held]))
        for other in stages:
            if other != held:
                assert claim_code(lambda: require_access(
                    ctx, scope=journal_mod.SCOPES[other], profile_id='p1', workspace_id='w1',
                    now=1)) == 'insufficient_scope', (held, other)


# --- apply presentation: the human sees exactly what the apply binds ---------------------------

@pytest.mark.parametrize('changes', [
    {'head': HEAD_B},
    {'candidate': 'e' * 64},
    {'verification': 'e' * 64},
    {'ref': 'refs/heads/release'},
])
def test_apply_presentation_shows_every_bound_input(db, chain, changes):
    journal = open_host(db)
    ctx = ctx_with()
    source, run_id = verified_scratch_result(journal, ctx, chain)
    base = journal.reserve(ctx, apply_request(source, run_id, key='k1'), now=120)['operation_id']
    shown = journal_mod.approval_presentation
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM control_operations WHERE operation_id=?', (base,)).fetchone())
    presentation = shown(row)
    for field in ('destination_ref', 'expected_revision', 'source_operation_id', 'source_run_id',
                  'candidate_digest', 'verification_digest'):
        assert field in presentation
    changed = apply_request(source, run_id, key='k1', **changes)
    row.update(request_json=json.dumps(changed), expected_revision=changed['expected_revision'])
    assert shown(row) != presentation


def test_apply_presentation_reaches_the_human_and_is_approvable(db, chain):
    _calls, _execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, source, run_id = approved_apply(journal, ctx, chain)
    assert state_of(db, apply_op) == 'APPROVED'
    assert apply_owner(journal).start_approved(ctx, apply_op) == {'state': 'SUCCEEDED', 'reason_code': 'applied'}
    assert destination.applied == [(REF, HEAD_A, CANDIDATE)]


@pytest.mark.parametrize('shadowed', ['kind', 'expected_revision', 'workspace_id', 'owner_epoch'])
def test_a_parameter_can_never_shadow_an_authority_field_in_the_presentation(db, chain, shadowed):
    journal = open_host(db)
    ctx = ctx_with()
    apply_op, _source, _run_id = approved_apply(journal, ctx, chain)
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute('SELECT * FROM control_operations WHERE operation_id=?',
                                (apply_op,)).fetchone())
    request = json.loads(row['request_json'])
    request['parameters'][shadowed] = 'forged'
    row['request_json'] = json.dumps(request)
    assert claim_code(lambda: journal_mod.approval_presentation(row)) == 'argument_mismatch'


# --- coordinator: each approved kind reaches only its own owner -------------------------------

def submit_and_approve(journal, ctx, coordinator, request, session):
    seen = []
    approval.register_gateway_notify(session, seen.append)
    _SESSIONS.add(session)
    operation_id = coordinator.submit(ctx, request)['operation_id']
    payload = seen[0]
    assert approval.resolve_control_consent(
        session_key=session, request_id=payload['request_id'],
        intent_digest=payload['control']['intent_digest'], choice='once',
        presentation_digest=ui_digest(payload), now=112)
    return operation_id


@pytest.mark.parametrize('wired', [True, False])
def test_coordinator_routes_an_approved_apply_only_to_the_apply_owner(db, chain, wired):
    calls, execute_owner, apply_owner, destination, _receipts = chain
    journal = open_host(db)
    ctx = ctx_with()
    source, run_id = verified_scratch_result(journal, ctx, chain)
    native_before = len(calls)
    engineering = execute_owner(journal)
    reached_engineering = []
    start_engineering = engineering.start_approved

    def engineering_start(ctx_, operation_id):
        reached_engineering.append(operation_id)
        return start_engineering(ctx_, operation_id)

    engineering.start_approved = engineering_start
    jobs = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        coordinator = HostControlCoordinator(
            journal=journal, owner=engineering,
            apply_owner=apply_owner(journal) if wired else None,
            select_human_session=lambda _p, _w: 'lm05-coordinator',
            submit_background=lambda *job: jobs.append(pool.submit(*job)),
            revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 112)
        apply_op = submit_and_approve(journal, ctx, coordinator, apply_request(source, run_id),
                                      'lm05-coordinator')
        assert jobs[0].result(timeout=30) is None
    assert (len(calls), reached_engineering) == (native_before, [])
    if wired:
        assert (state_of(db, apply_op), destination.applied) == ('SUCCEEDED', [(REF, HEAD_A, CANDIDATE)])
    else:
        assert (state_of(db, apply_op), destination.applied) == ('BLOCKED', [])
