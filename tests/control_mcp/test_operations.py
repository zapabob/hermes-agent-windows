"""Real SQLite transactions plus the existing strict approval owner."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import sqlite3

import pytest


def request(**changes):
    data={'kind':'start_engineering_run','profile_id':'p1','workspace_id':'w1',
          'idempotency_key':'request-1','expected_revision':'revision-1','source_sha':'a'*40,
          'parameters':{'task':'Add a bounded test'}}
    data.update(changes)
    return data


def journal(control_module,tmp_path):
    return control_module('journal').HostControlJournal(tmp_path/'state'/'control.db')


def writable(control_context, **changes):
    return control_context(scopes=('hermes:read','hermes:run:start'), **changes)


def test_journal_read_does_not_create_storage(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path)
    out=j.get(control_context(),'op-'+'a'*32,profile_id='p1',workspace_id='w1',now=100)
    assert out['state']=='ABSENT'
    assert not j.path.parent.exists()


def test_reserve_is_immutable_idempotent_and_not_execution(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise()
    ctx=writable(control_context)
    first=j.reserve(ctx,request(),now=100)
    second=j.reserve(ctx,request(),now=101)
    assert first['operation_id']==second['operation_id']
    assert first['state']=='PENDING_APPROVAL'
    assert not first.get('executed',False)
    assert 'task' not in str(first)
    with pytest.raises(control_module('contracts').ControlError) as caught:
        j.reserve(ctx,request(parameters={'task':'Changed task'}),now=101)
    assert caught.value.code=='idempotency_conflict'


def test_wrong_scope_and_unknown_fields_have_zero_write_effect(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path)
    for data,ctx in [(request(),control_context()), (request(approved=True),writable(control_context)),
                     (request(parameters={'task':'x','command':'unsafe'}),writable(control_context))]:
        with pytest.raises(control_module('contracts').ControlError):
            j.reserve(ctx,data,now=100)
        assert not j.path.parent.exists()


def test_two_clients_get_only_one_workspace_reservation(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise()
    contexts=[writable(control_context,client_registration='codex'),writable(control_context,client_registration='chatgpt')]
    def submit(ctx):
        try:
            return j.reserve(ctx,request(),now=100)
        except control_module('contracts').ControlError as exc:
            return {'error':exc.code}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,contexts))
    assert sum(r.get('state')=='PENDING_APPROVAL' for r in results)==1
    assert sum(r.get('error')=='workspace_busy' for r in results)==1


def test_same_intent_from_parallel_requests_reserved_once(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:j.reserve(ctx,request(),now=100),range(8)))
    assert len({r['operation_id'] for r in results})==1


def rendered_digest(payload):
    # What a human UI computes over the presentation it rendered.
    return hashlib.sha256(json.dumps(payload['control']['presentation'],ensure_ascii=False,sort_keys=True,
                                     separators=(',',':')).encode('utf-8')).hexdigest()


def decide(control_module,j,ctx,op,**changes):
    from tools import approval as a
    binding=j.approval_binding(ctx,op,now=110)
    session='journal-human-test'
    seen=[]
    a.register_gateway_notify(session,seen.append)
    ticket=a.request_control_consent(binding,session_key=session,timeout_seconds=60,now=110)
    try:
        a.resolve_control_consent(session_key=session,request_id=ticket.request_id,
                                  intent_digest=binding.intent_digest,choice='once',now=111,
                                  presentation_digest=rendered_digest(seen[0]))
        decision=a.take_control_decision(ticket,now=111)
        if changes:
            decision=replace(decision,**changes)
        return j.approve(ctx,op,decision,now=111)
    finally:
        a.unregister_gateway_notify(session)


def test_actual_single_use_owner_decision_allows_transition(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    op=j.reserve(ctx,request(),now=100)['operation_id']
    assert decide(control_module,j,ctx,op)['state']=='APPROVED'
    j.claim_approved(ctx,op,now=112)
    assert j.get(ctx,op,profile_id='p1',workspace_id='w1',now=112)['state']=='RUNNING'
    j.transition(op,expected_state='RUNNING',new_state='SUCCEEDED',now=113)
    with pytest.raises(control_module('contracts').ControlError):
        j.transition(op,expected_state='APPROVED',new_state='RUNNING',now=114)
    assert j.reserve(ctx,request(),now=114)['state']=='SUCCEEDED'


def rebind(binding, **changes):
    """A self-consistent binding for another principal: the projection moves with it."""
    presentation = {**json.loads(binding.presentation_json), **changes}
    rendered = json.dumps(presentation, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return replace(binding, **changes, presentation_json=rendered,
                   presentation_digest=hashlib.sha256(rendered.encode('utf-8')).hexdigest())


def test_human_approval_ticket_binds_and_discloses_resource_and_grant_revision(
        control_module, control_context, tmp_path):
    from tools import approval as a

    j = journal(control_module, tmp_path)
    j.initialise()
    ctx = writable(control_context, grant_revision=7)
    op = j.reserve(ctx, request(), now=100)['operation_id']
    binding = j.approval_binding(ctx, op, now=110)
    session = 'human-binding-test'
    seen = []
    a.register_gateway_notify(session, seen.append)
    try:
        ticket = a.request_control_consent(binding, session_key=session,
                                           timeout_seconds=60, now=110)
        payload = seen[0]
        assert getattr(binding, 'resource', None) == ctx.resource
        assert getattr(binding, 'grant_revision', None) == ctx.grant_revision
        assert payload['control']['resource'] == ctx.resource
        assert payload['control']['grant_revision'] == ctx.grant_revision
        assert ctx.resource in payload['description']
        assert f'grant revision {ctx.grant_revision}' in payload['description'].lower()
        assert a.take_control_decision(ticket, now=111) is None
        assert a.resolve_control_consent(
            session_key=session, request_id=ticket.request_id,
            intent_digest=binding.intent_digest, choice='once', now=111,
            presentation_digest=rendered_digest(payload))
        decision = a.take_control_decision(ticket, now=111)
        with pytest.raises(ValueError):
            replace(binding, resource='https://other.invalid/control/mcp')
        assert a.consume_control_verdict(
            decision, rebind(binding, resource='https://other.invalid/control/mcp'), now=111) is None
        assert a.consume_control_verdict(
            decision, rebind(binding, grant_revision=8), now=111) is None
        assert a.consume_control_verdict(decision, binding, now=111) == 'once'
        assert a.consume_control_verdict(decision, binding, now=111) is None
    finally:
        a.unregister_gateway_notify(session)


def test_forged_owner_decision_or_cross_client_does_not_approve(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    op=j.reserve(ctx,request(),now=100)['operation_id']
    with pytest.raises(control_module('contracts').ControlError):
        decide(control_module,j,ctx,op,choice='once')  # copied dataclass, not issued object
    other=writable(control_context,client_registration='chatgpt')
    with pytest.raises(control_module('contracts').ControlError):
        j.approval_binding(other,op,now=110)
    other_resource=writable(control_context,resource='https://other.invalid/control/mcp')
    with pytest.raises(control_module('contracts').ControlError):
        j.approval_binding(other_resource,op,now=110)
    assert j.get(ctx,op,profile_id='p1',workspace_id='w1',now=110)['state']=='PENDING_APPROVAL'


def test_restart_marks_inflight_unknown_and_never_releases_writer(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    op=j.reserve(ctx,request(),now=100)['operation_id']
    decide(control_module,j,ctx,op)
    j.claim_approved(ctx,op,now=112)
    j.close()
    restarted=journal(control_module,tmp_path)
    restarted.initialise(now=113)
    result=restarted.get(ctx,op,profile_id='p1',workspace_id='w1',now=114)
    assert result['state']=='UNKNOWN'
    with pytest.raises(control_module('contracts').ControlError) as caught:
        restarted.reserve(ctx,request(idempotency_key='new'),now=115)
    assert caught.value.code=='workspace_busy'
    with pytest.raises(control_module('contracts').ControlError):
        restarted.transition(op,expected_state='UNKNOWN',new_state='RUNNING',now=115)


def test_pending_expiry_cannot_be_approved_and_can_release_safe_reservation(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    op=j.reserve(ctx,request(),now=100)['operation_id']
    with pytest.raises(control_module('contracts').ControlError):
        j.approval_binding(ctx,op,now=200)
    fresh=writable(control_context,expires_at=600)
    result=j.reserve(fresh,request(idempotency_key='new'),now=210)
    assert result['state']=='PENDING_APPROVAL'


def test_foreign_workspace_never_reads_operation(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    op=j.reserve(ctx,request(),now=100)['operation_id']
    other=control_context(workspaces=(('p1','w2'),))
    with pytest.raises(control_module('contracts').ControlError):
        j.get(other,op,profile_id='p1',workspace_id='w2',now=110)


def test_unapproved_transition_cannot_skip_owner_consent(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    op=j.reserve(ctx,request(),now=100)['operation_id']
    for new in ('APPROVED','RUNNING','SUCCEEDED'):
        with pytest.raises(control_module('contracts').ControlError):
            j.transition(op,expected_state='PENDING_APPROVAL',new_state=new,now=110)


def test_read_existing_journal_creates_no_wal_shm_or_other_files(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise()
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    j.get(control_context(),'op-'+'b'*32,profile_id='p1',workspace_id='w1',now=100)
    after={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after==before


def test_real_deny_releases_only_unexecuted_reservation(control_module,control_context,tmp_path):
    from tools import approval as a
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    op=j.reserve(ctx,request(),now=100)['operation_id']
    binding=j.approval_binding(ctx,op,now=110)
    a.register_gateway_notify('deny-test',lambda _:None)
    ticket=a.request_control_consent(binding,session_key='deny-test',now=110,timeout_seconds=60)
    try:
        assert a.resolve_control_consent(session_key='deny-test',request_id=ticket.request_id,
                                         intent_digest=binding.intent_digest,choice='deny',now=111)
        decision=a.take_control_decision(ticket,now=111)
        assert j.approve(ctx,op,decision,now=111)['state']=='DENIED'
        assert j.reserve(ctx,request(idempotency_key='new'),now=112)['state']=='PENDING_APPROVAL'
    finally:
        a.unregister_gateway_notify('deny-test')


def test_explicit_unknown_after_effect_keeps_workspace_reserved(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise();ctx=writable(control_context)
    op=j.reserve(ctx,request(),now=100)['operation_id']
    decide(control_module,j,ctx,op)
    j.claim_approved(ctx,op,now=112)
    j.transition(op,expected_state='RUNNING',new_state='UNKNOWN',now=113)
    with pytest.raises(control_module('contracts').ControlError) as caught:
        j.reserve(ctx,request(idempotency_key='new'),now=114)
    assert caught.value.code=='workspace_busy'


def test_repeated_expired_pending_intent_is_not_reported_as_active(control_module,control_context,tmp_path):
    j=journal(control_module,tmp_path);j.initialise()
    j.reserve(writable(control_context),request(),now=100)
    fresh=writable(control_context,expires_at=600)
    assert j.reserve(fresh,request(),now=210)['state']=='EXPIRED'


def test_operation_read_and_replay_require_original_client_and_grant(
        control_module, control_context, tmp_path):
    from downstream.control_mcp.contracts import ControlError

    j = journal(control_module, tmp_path)
    j.initialise()
    original = writable(control_context)
    op = j.reserve(original, request(), now=100)['operation_id']
    for other in (writable(control_context, client_registration='chatgpt'),
                  writable(control_context, subject='human-2'),
                  writable(control_context, grant_revision=2)):
        with pytest.raises(ControlError) as denied:
            j.get(other, op, profile_id='p1', workspace_id='w1', now=101)
        assert denied.value.code == 'resource_denied'
    with pytest.raises(ControlError) as denied:
        j.reserve(writable(control_context, grant_revision=2), request(), now=101)
    assert denied.value.code == 'idempotency_conflict'
