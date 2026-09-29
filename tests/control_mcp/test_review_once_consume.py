"""LM04 / RV05: one human approval authorises at most one effect.

Contract: docs/windows/workstation-20260924/cursor-handoff/F01_AUTHORITY_CONTRACT.md
sections 5 and 7.1-7.3. The durable journal row is the only replay identity:
a retry returns the recorded outcome, and restart never turns an unknown
outcome back into authority. Effects are counted at the native entrypoint.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from downstream.control_mcp import journal as journal_mod
from downstream.control_mcp.contracts import ControlError
from downstream.control_mcp.coordinator import HostControlCoordinator
from downstream.control_mcp.service import HostControlService
from plugins.implementation_router import entrypoint
from tests.control_mcp import test_review_approval_binding as lm03
from tests.control_mcp.test_review_approval_binding import (  # noqa: F401 - fixtures
    GRANT_OK,
    REPO_ROOT,
    TASK,
    _SESSIONS,
    _release_human_sessions,
    db,
    effects,
    make_ctx,
    make_request,
    open_host,
    previous_host_crashes_after,
    present,
    reserve_approved,
    run_through_coordinator,
    state_of,
    ui_digest,
)
from tools import approval

LM03_HELPERS = Path(lm03.__file__).resolve()


def reservations_of(db, operation_id):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute('SELECT count(*) FROM control_reservations WHERE operation_id=?',
                            (operation_id,)).fetchone()[0]


def wait_state(db, operation_id, states, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if state_of(db, operation_id) in states:
            return state_of(db, operation_id)
        time.sleep(0.02)
    raise AssertionError(state_of(db, operation_id))


def human_says(journal, ctx, operation_id, choice, *, session='lm04-human', repeat=1):
    """The UI sends one decision (possibly more than once); returns the ticket."""
    ticket, binding, payload = present(journal, ctx, operation_id, session=session)
    kwargs = dict(session_key=session, request_id=ticket.request_id,
                  intent_digest=binding.intent_digest, choice=choice, now=111)
    if choice == 'once':
        kwargs['presentation_digest'] = ui_digest(payload)
    accepted = [approval.resolve_control_consent(**kwargs) for _ in range(repeat)]
    assert accepted == [True] + [False] * (repeat - 1)
    return ticket


def run_once(journal, ctx, owner):
    operation_id = reserve_approved(journal, ctx)
    result = owner(journal).start_approved(ctx, operation_id).future.result(timeout=30)
    assert result['state'] == 'SUCCEEDED'
    return operation_id, result


# --- R1 atomic claim ------------------------------------------------------------------------

def test_r1_simultaneous_claims_of_one_approval_produce_one_effect(db, effects):
    calls, hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    owners = [owner(journal), owner(journal)]
    gate = threading.Barrier(len(owners))
    effect_in_flight = threading.Event()
    hooks.append(lambda: effect_in_flight.wait(timeout=30))

    def claim(run_owner):
        gate.wait()
        try:
            return run_owner.start_approved(ctx, operation_id)
        except ControlError as exc:
            return exc.code

    with ThreadPoolExecutor(len(owners)) as pool:
        outcomes = list(pool.map(claim, owners))
    handles = [o for o in outcomes if not isinstance(o, str)]
    assert [o for o in outcomes if isinstance(o, str)] == ['operation_conflict']
    assert len(handles) == 1
    assert state_of(db, operation_id) == 'RUNNING'
    with pytest.raises(ControlError) as while_running:
        owners[0].start_approved(ctx, operation_id)
    assert while_running.value.code == 'operation_conflict'
    effect_in_flight.set()
    handles[0].future.result(timeout=30)
    assert wait_state(db, operation_id, {'SUCCEEDED'}) == 'SUCCEEDED'
    assert [c['operation_id'] for c in calls] == [operation_id]


# --- R2 / R3 replay returns the recorded outcome --------------------------------------------

def test_r2_duplicate_request_after_success_returns_the_recorded_result(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id, first = run_once(journal, ctx, owner)

    replay = journal.reserve(ctx, make_request(), now=120)
    assert (replay['operation_id'], replay['state']) == (operation_id, 'SUCCEEDED')
    assert replay['result'] == first
    observed = journal.get(ctx, operation_id, profile_id='p1', workspace_id='w1', now=121)
    assert observed['result'] == first
    with pytest.raises(ControlError) as again:
        owner(journal).start_approved(ctx, operation_id)
    assert again.value.code == 'operation_conflict'
    for expected in ('SUCCEEDED', 'RUNNING'):
        with pytest.raises(ControlError):
            journal.transition(operation_id, expected_state=expected, new_state='RUNNING', now=122)
    assert journal.reserve(ctx, make_request(), now=123)['result'] == first
    assert len(calls) == 1


def test_r3_client_retry_after_lost_response_gets_the_known_result(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    run_owner = owner(journal)
    operation_id = run_through_coordinator(journal, ctx, run_owner)
    assert wait_state(db, operation_id, {'SUCCEEDED'}) == 'SUCCEEDED'

    # The committed outcome's response never reached the client; it retries
    # the identical MCP request through the production admission path.
    def no_new_approval(*_args):
        raise AssertionError('a retry must not present a new approval')

    retry = HostControlCoordinator(
        journal=journal, owner=run_owner, select_human_session=no_new_approval,
        submit_background=no_new_approval, revalidate_grant=lambda _ctx, *, now: None,
        clock=lambda: 130)
    retried = retry.submit(ctx, make_request())
    assert (retried['operation_id'], retried['state']) == (operation_id, 'SUCCEEDED')
    assert retried['result']['state'] == 'SUCCEEDED'
    assert len(calls) == 1


@pytest.mark.parametrize('version', [1, 2, 3])
def test_an_older_journal_upgrades_in_place_and_its_rows_carry_no_invented_result(db, version):
    db.parent.mkdir(parents=True)
    with closing(sqlite3.connect(db)) as conn:
        statements = (journal_mod._V1_STATEMENTS
                      + (journal_mod._V2_STATEMENTS if version >= 2 else ())
                      + (journal_mod._V3_STATEMENTS if version >= 3 else ()))
        for statement in statements:
            conn.execute(statement)
        conn.execute(f'PRAGMA user_version={version}')
        conn.commit()
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = journal.reserve(ctx, make_request(), now=100)['operation_id']
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == journal_mod._SCHEMA_VERSION
    assert 'result' not in journal.get(ctx, operation_id, profile_id='p1', workspace_id='w1', now=101)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute('INSERT INTO control_effect_evidence(operation_id,recorder_epoch,recorded_at,evidence_json) '
                     "VALUES (?,'e',101,'{}')", (operation_id,))
        conn.commit()
        for statement in ("UPDATE control_effect_evidence SET evidence_json='[]'",
                          'DELETE FROM control_effect_evidence'):
            with pytest.raises(sqlite3.DatabaseError, match='append_only'):
                conn.execute(statement)


def test_the_recorded_result_keeps_identity_and_codes_but_never_host_paths_or_diagnostics(db):
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    journal.claim_approved(ctx, operation_id, now=112, revalidate_grant=GRANT_OK)
    journal.transition(operation_id, expected_state='RUNNING', new_state='SUCCEEDED', now=113, result={
        'state': 'SUCCEEDED', 'run_id': 'eng-1', 'reason_code': 'verified', 'stage_calls': 3,
        'revision': 2, 'message': 'x' * 70_000, 'locale': 'en',
        'verified_workspace': 'C:\\Users\\someone\\secret-repo', 'diagnostic': {'stderr': 'token=abc'}})
    expected = {'state': 'SUCCEEDED', 'run_id': 'eng-1', 'reason_code': 'verified',
                'stage_calls': 3, 'revision': 2}
    assert journal.reserve(ctx, make_request(), now=120)['result'] == expected
    service = HostControlService(source=object(), journal=journal, clock=lambda: 121)
    observed = service.read(ctx, 'hermes_get_operation',
                            {'profile_id': 'p1', 'workspace_id': 'w1', 'operation_id': operation_id})
    assert observed['result'] == expected
    assert reservations_of(db, operation_id) == 0


def test_a_blocked_outcome_through_the_owner_is_recorded_without_its_diagnostic(db, effects, monkeypatch):
    calls, _hooks, owner = effects

    def blocked_run(_plugin_ctx, args, *, run_id, operation_id):
        calls.append({'operation_id': operation_id, 'task': args['task']})
        return json.dumps({'state': 'BLOCKED', 'run_id': run_id, 'reason_code': 'checks_failed',
                           'diagnostic': {'path': 'C:\\host\\run'}})

    monkeypatch.setattr(entrypoint, 'run_workflow', blocked_run)
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    handle = owner(journal).start_approved(ctx, operation_id)
    handle.future.result(timeout=30)
    replay = journal.reserve(ctx, make_request(), now=120)
    assert replay['state'] == 'BLOCKED'
    assert replay['result'] == {'state': 'BLOCKED', 'run_id': handle.run_id, 'reason_code': 'checks_failed'}
    assert len(calls) == 1


# --- R4 / R5 / R6 restart semantics ---------------------------------------------------------

_DIES_AFTER_EFFECT = r'''
import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('lm03_helpers', sys.argv[1])
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
journal = helpers.open_host(Path(sys.argv[2]))
ctx = helpers.make_ctx()
op = journal.reserve(ctx, helpers.make_request(), now=100)['operation_id']
helpers.approve(journal, ctx, op)
journal.claim_approved(ctx, op, now=112, revalidate_grant=helpers.GRANT_OK)
with open(sys.argv[3], 'a', encoding='utf-8') as effect:
    effect.write(op + '\n')
os._exit(0)
'''


def test_r4_death_after_the_effect_before_a_durable_outcome_is_unknown_never_replayed(
        tmp_path, db, effects):
    calls, _hooks, owner = effects
    marker = tmp_path / 'external-effects.log'
    subprocess.run([sys.executable, '-c', _DIES_AFTER_EFFECT, str(LM03_HELPERS), str(db), str(marker)],
                   cwd=REPO_ROOT, check=True, timeout=120)
    [operation_id] = marker.read_text(encoding='utf-8').split()

    journal = open_host(db)
    ctx = make_ctx()
    assert state_of(db, operation_id) == 'UNKNOWN'
    replay = journal.reserve(ctx, make_request(), now=120)
    assert (replay['operation_id'], replay['state']) == (operation_id, 'UNKNOWN')
    assert 'result' not in replay
    with pytest.raises(ControlError) as again:
        owner(journal).start_approved(ctx, operation_id)
    assert again.value.code == 'operation_conflict'
    assert calls == []
    assert marker.read_text(encoding='utf-8').split() == [operation_id]


def test_r5_restart_with_an_unclaimed_approval_blocks_it_instead_of_rehydrating(tmp_path, db, effects):
    calls, _hooks, owner = effects
    operation_id = previous_host_crashes_after(tmp_path, db, [{'workspace': 'w1', 'until': 'APPROVED'}])['w1']
    journal = open_host(db)
    ctx = make_ctx()
    assert state_of(db, operation_id) == 'BLOCKED'
    assert reservations_of(db, operation_id) == 0
    replay = journal.reserve(ctx, make_request(), now=120)
    assert (replay['operation_id'], replay['state']) == (operation_id, 'BLOCKED')
    with pytest.raises(ControlError) as again:
        owner(journal).start_approved(ctx, operation_id)
    assert again.value.code == 'operation_conflict'
    assert state_of(db, operation_id) == 'BLOCKED'
    assert calls == []


def test_r6_restart_with_a_running_operation_is_unknown_and_keeps_the_reservation(tmp_path, db, effects):
    calls, _hooks, owner = effects
    operation_id = previous_host_crashes_after(tmp_path, db, [{'workspace': 'w1', 'until': 'RUNNING'}])['w1']
    for _restart in range(2):
        journal = open_host(db)
        journal.close()
    journal = open_host(db)
    ctx = make_ctx()
    assert state_of(db, operation_id) == 'UNKNOWN'
    assert reservations_of(db, operation_id) == 1
    with pytest.raises(ControlError) as busy:
        journal.reserve(ctx, make_request(key='fresh-key'), now=120)
    assert busy.value.code == 'workspace_busy'
    with pytest.raises(ControlError) as again:
        owner(journal).start_approved(ctx, operation_id)
    assert again.value.code == 'operation_conflict'
    assert (state_of(db, operation_id), reservations_of(db, operation_id)) == ('UNKNOWN', 1)
    assert calls == []


# --- R7 / R8 binding and authority before replay --------------------------------------------

def test_r7_reused_key_or_decision_with_a_different_intent_is_a_binding_mismatch(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id, _first = run_once(journal, ctx, owner)

    with pytest.raises(ControlError) as reused_key:
        journal.reserve(ctx, make_request(task=TASK + ' and deploy it'), now=120)
    assert reused_key.value.code == 'idempotency_conflict'

    approved_for = journal.reserve(ctx, make_request('w2'), now=120)['operation_id']
    other = journal.reserve(ctx, make_request('w3'), now=120)['operation_id']
    ticket = human_says(journal, ctx, approved_for, 'once')
    decision = approval.take_control_decision(ticket, now=111)
    with pytest.raises(ControlError) as reused_decision:
        journal.approve(ctx, other, decision, now=111)
    assert reused_decision.value.code == 'approval_required'
    assert state_of(db, other) == 'PENDING_APPROVAL'

    with closing(sqlite3.connect(db)) as conn:
        conn.execute('UPDATE control_operations SET request_json=? WHERE operation_id=?',
                     (json.dumps(make_request(task=TASK + ' and deploy it')), operation_id))
        conn.commit()
    with pytest.raises(ControlError) as replayed:
        owner(journal).start_approved(ctx, operation_id)
    assert replayed.value.code == 'argument_mismatch'
    assert len(calls) == 1


@pytest.mark.parametrize('changes, reserve_code', [
    ({'client_registration': 'claude'}, None),
    ({'subject': 'human-2'}, None),
    ({'profiles': ('p2',), 'workspaces': (('p2', 'w1'),)}, 'resource_denied'),
])
def test_r8_same_intent_from_another_principal_is_denied_before_any_replay(db, effects, changes, reserve_code):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id, _first = run_once(journal, ctx, owner)
    other = make_ctx(**changes)

    with pytest.raises(ControlError) as claimed:
        owner(journal).start_approved(other, operation_id)
    assert claimed.value.code == 'resource_denied'
    with pytest.raises(ControlError) as read:
        journal.get(other, operation_id, profile_id=other.profiles[0], workspace_id='w1', now=120)
    assert read.value.code == 'resource_denied'
    if reserve_code is None:
        fresh = journal.reserve(other, make_request(), now=120)
        assert fresh['operation_id'] != operation_id
        assert fresh['state'] == 'PENDING_APPROVAL' and 'result' not in fresh
    else:
        with pytest.raises(ControlError) as reserved:
            journal.reserve(other, make_request(), now=120)
        assert reserved.value.code == reserve_code
    assert len(calls) == 1


# --- R9 / R10 duplicate human decisions -----------------------------------------------------

def test_r9_duplicate_deny_is_idempotent_and_never_executes(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = journal.reserve(ctx, make_request(), now=100)['operation_id']
    ticket = human_says(journal, ctx, operation_id, 'deny', repeat=2)

    first = journal.approve(ctx, operation_id, approval.take_control_decision(ticket, now=111), now=111)
    second = journal.approve(ctx, operation_id, approval.take_control_decision(ticket, now=112), now=112)
    assert (first['state'], second['state']) == ('DENIED', 'DENIED')
    assert second['operation_id'] == operation_id
    with pytest.raises(ControlError) as claimed:
        owner(journal).start_approved(ctx, operation_id)
    assert claimed.value.code == 'operation_conflict'
    for other in (make_ctx(client_registration='claude'), make_ctx(subject='human-2')):
        with pytest.raises(ControlError) as foreign:
            journal.approve(other, operation_id, approval.take_control_decision(ticket, now=113), now=113)
        assert foreign.value.code == 'resource_denied'
    assert reservations_of(db, operation_id) == 0
    assert calls == []


def test_r9_a_deny_replay_never_downgrades_or_upgrades_another_decision(db, effects):
    calls, _hooks, _owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    denied = journal.reserve(ctx, make_request('w2'), now=100)['operation_id']
    ticket = human_says(journal, ctx, denied, 'deny', session='lm04-deny')
    journal.approve(ctx, denied, approval.take_control_decision(ticket, now=111), now=111)
    approved = reserve_approved(journal, ctx)
    with pytest.raises(ControlError) as crossed:
        journal.approve(ctx, approved, approval.take_control_decision(ticket, now=112), now=112)
    assert crossed.value.code == 'approval_conflict'
    assert (state_of(db, denied), state_of(db, approved)) == ('DENIED', 'APPROVED')
    assert calls == []


def test_r10_duplicate_once_from_the_ui_causes_no_second_transition_or_run(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    run_owner = owner(journal)
    operation_id = journal.reserve(ctx, make_request(), now=100)['operation_id']
    ticket = human_says(journal, ctx, operation_id, 'once', repeat=2)
    assert journal.approve(ctx, operation_id, approval.take_control_decision(ticket, now=111),
                           now=111)['state'] == 'APPROVED'
    run_owner.start_approved(ctx, operation_id).future.result(timeout=30)

    for now in (112, 113):
        with pytest.raises(ControlError) as duplicate:
            journal.approve(ctx, operation_id, approval.take_control_decision(ticket, now=now), now=now)
        assert duplicate.value.code == 'approval_conflict'
        with pytest.raises(ControlError) as claimed:
            run_owner.start_approved(ctx, operation_id)
        assert claimed.value.code == 'operation_conflict'
    assert state_of(db, operation_id) == 'SUCCEEDED'
    assert len(calls) == 1


def test_r10_duplicate_once_through_the_coordinator_runs_the_workflow_once(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    session = 'lm04-coordinator'
    seen = []
    approval.register_gateway_notify(session, seen.append)
    _SESSIONS.add(session)
    jobs = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        coordinator = HostControlCoordinator(
            journal=journal, owner=owner(journal), select_human_session=lambda _p, _w: session,
            submit_background=lambda *job: jobs.append(pool.submit(*job)),
            revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 112)
        operation_id = coordinator.submit(ctx, make_request())['operation_id']
        payload = seen[0]
        once = dict(session_key=session, request_id=payload['request_id'],
                    intent_digest=payload['control']['intent_digest'], choice='once',
                    presentation_digest=ui_digest(payload), now=112)
        assert [approval.resolve_control_consent(**once) for _ in range(3)] == [True, False, False]
        assert coordinator.submit(ctx, make_request())['operation_id'] == operation_id
        for job in jobs:
            assert job.result(timeout=30) is None
    assert len(jobs) == 1
    assert wait_state(db, operation_id, {'SUCCEEDED'}) == 'SUCCEEDED'
    assert len(calls) == 1
