"""Exercise strict entries in the actual existing approval queue, not a fake permit."""
import dataclasses
import hashlib
import json

import pytest


def owner():
    from tools import approval
    required=('ControlApprovalBinding','request_control_consent','resolve_control_consent',
              'take_control_decision','consume_control_decision')
    if not all(hasattr(approval,k) for k in required):
        pytest.fail('Existing approval owner has no strict control-consent path',pytrace=False)
    return approval


BOUND={'operation_id':'op-1','subject':'human-1','client_registration':'codex',
       'resource':'https://hermes.invalid/control/mcp','grant_revision':1,'profile_id':'p1',
       'workspace_id':'w1','owner_epoch':'e'*32,'policy_revision':'b'*64,
       'tool_revision':'start_engineering_run@1','route_revision':'c'*64,'provider_revision':''}


def canonical(presentation):
    text=json.dumps(presentation,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return text,hashlib.sha256(text.encode()).hexdigest()


PRESENTATION,PD=canonical({**BOUND,'task':'Start engineering in w1'})


def make_binding(approval):
    return approval.ControlApprovalBinding(operation_id='op-1',intent_digest='a'*64,
        subject='human-1',client_registration='codex',resource='https://hermes.invalid/control/mcp',
        grant_revision=1,profile_id='p1',workspace_id='w1',expires_at=200,
        description='Start engineering in w1 at the approved revision',
        owner_epoch='e'*32,policy_revision='b'*64,tool_revision='start_engineering_run@1',
        route_revision='c'*64,provider_revision='',presentation_json=PRESENTATION,presentation_digest=PD)


def begin(approval):
    seen=[]
    key='control-test-session'
    approval.register_gateway_notify(key, seen.append)
    binding=make_binding(approval)
    ticket=approval.request_control_consent(binding,session_key=key,timeout_seconds=60,now=100)
    return key,binding,ticket,seen


def test_actual_owner_queue_notifies_then_consumes_exact_once():
    a=owner(); key,binding,ticket,seen=begin(a)
    try:
        assert seen[0]['request_id']==ticket.request_id
        assert seen[0]['control']['intent_digest']==binding.intent_digest
        assert a.take_control_decision(ticket,now=110) is None
        assert a.resolve_control_consent(session_key=key,request_id=ticket.request_id,
                                        intent_digest='a'*64,choice='once',now=110,presentation_digest=PD) is True
        decision=a.take_control_decision(ticket,now=110)
        assert decision.choice=='once'
        assert a.consume_control_decision(decision,binding,now=110) is True
        assert a.consume_control_decision(decision,binding,now=110) is False
    finally:
        a.unregister_gateway_notify(key)


@pytest.mark.parametrize('kwargs',[{'choice':'always'},{'choice':'session'},{'choice':'smart_approve'},
    {'choice':'once','request_id':'stale'}, {'choice':'once','intent_digest':'b'*64}, {'choice':'once','now':161},
    {'choice':'once','presentation_digest':None}, {'choice':'once','presentation_digest':'f'*64}])
def test_invalid_decision_cannot_signal_or_consume(kwargs):
    a=owner();key,binding,ticket,_=begin(a)
    try:
        args=dict(session_key=key,request_id=ticket.request_id,intent_digest='a'*64,choice='once',now=110,presentation_digest=PD)
        args.update(kwargs)
        assert a.resolve_control_consent(**args) is False
        decision=a.take_control_decision(ticket,now=args['now'])
        assert decision is None or decision.choice!='once'
    finally:
        a.unregister_gateway_notify(key)


@pytest.mark.parametrize('kwargs',[{}, {'resolve_all':True}, {'request_id':'matching'}])
def test_legacy_fifo_all_or_request_id_cannot_approve_strict_entry(kwargs):
    a=owner();key,binding,ticket,_=begin(a)
    try:
        if kwargs.get('request_id')=='matching':
            kwargs={'request_id':ticket.request_id}
        assert a.resolve_gateway_approval(key,'once',**kwargs)==0
        assert a.take_control_decision(ticket,now=110) is None
        assert a.list_gateway_approvals(key)[0]['request_id']==ticket.request_id
    finally:
        a.unregister_gateway_notify(key)


def test_legacy_delivery_ack_does_not_decide_strict_control_consent():
    a=owner();key,binding,ticket,_=begin(a)
    try:
        assert a.ack_gateway_approval(key,ticket.request_id) is True
        assert a.take_control_decision(ticket,now=110) is None
        assert a.list_gateway_approvals(key)[0]['request_id']==ticket.request_id
    finally:
        a.unregister_gateway_notify(key)


def test_legacy_entry_still_resolves_when_strict_entry_is_queued_first():
    a=owner();key,binding,ticket,_=begin(a)
    try:
        legacy=a._ApprovalEntry({'command':'echo test','request_id':'legacy'})
        with a._lock:
            a._gateway_queues[key].append(legacy)
        assert a.resolve_gateway_approval(key,'once',resolve_all=True)==1
        assert legacy.result=='once'
        assert a.take_control_decision(ticket,now=110) is None
    finally:
        a.unregister_gateway_notify(key)


def test_missing_or_failing_notify_does_not_auto_approve():
    a=owner()
    binding=make_binding(a)
    with pytest.raises(RuntimeError):
        a.request_control_consent(binding,session_key='unregistered',timeout_seconds=60,now=100)
    def fail(data):
        raise RuntimeError('synthetic secret in private transport error')
    a.register_gateway_notify('bad-notify',fail)
    try:
        with pytest.raises(RuntimeError) as caught:
            a.request_control_consent(binding,session_key='bad-notify',timeout_seconds=60,now=100)
        assert 'synthetic secret' not in str(caught.value)
        assert not a.list_gateway_approvals('bad-notify')
    finally:
        a.unregister_gateway_notify('bad-notify')


@pytest.mark.parametrize('changes', [
    {'resource': ''},
    {'resource': 'https://hermes.invalid/control/mcp invalid'},
    {'resource': 'https://hermes.invalid/control/mcp\nforged'},
    {'resource': 'x' * 2049},
    {'grant_revision': 0},
    {'grant_revision': True},
    {'owner_epoch': ''},
    {'policy_revision': 'short'},
    {'presentation_json': '{"task":"edited"}'},
    {'presentation_digest': 'f' * 64},
])
def test_control_binding_rejects_invalid_resource_or_grant_revision(changes):
    a=owner();key,binding,ticket,_=begin(a)
    try:
        with pytest.raises(ValueError,match='invalid_control_approval_binding'):
            dataclasses.replace(binding,**changes)
    finally:
        a.unregister_gateway_notify(key)


@pytest.mark.parametrize('field',sorted(BOUND))
def test_presentation_that_disagrees_with_the_binding_is_rejected_even_with_its_own_digest(field):
    a=owner()
    value=BOUND[field]
    forged={**BOUND,'task':'Start engineering in w1',
            field:(value+1 if type(value) is int else value+'x')}
    text,digest=canonical(forged)
    with pytest.raises(ValueError,match='invalid_control_approval_binding'):
        dataclasses.replace(make_binding(a),presentation_json=text,presentation_digest=digest)


def test_non_canonical_presentation_json_is_rejected():
    a=owner()
    text=json.dumps({**BOUND,'task':'Start engineering in w1'},indent=1)
    with pytest.raises(ValueError,match='invalid_control_approval_binding'):
        dataclasses.replace(make_binding(a),presentation_json=text,
                            presentation_digest=hashlib.sha256(text.encode()).hexdigest())


def test_ui_payload_withholds_the_host_digest():
    a=owner();key,_binding,_ticket,seen=begin(a)
    try:
        assert seen[0]['control']['presentation']==json.loads(PRESENTATION)
        assert 'presentation_digest' not in seen[0]['control']
        assert PD not in json.dumps(seen[0])
    finally:
        a.unregister_gateway_notify(key)


def test_forged_dataclass_copy_cannot_be_used_as_owner_decision():
    a=owner();key,binding,ticket,_=begin(a)
    try:
        a.resolve_control_consent(session_key=key,request_id=ticket.request_id,intent_digest='a'*64,choice='once',now=110,presentation_digest=PD)
        actual=a.take_control_decision(ticket,now=110)
        forged=dataclasses.replace(actual)
        assert a.consume_control_decision(forged,binding,now=110) is False
        assert a.consume_control_decision(actual,binding,now=110) is True
    finally:
        a.unregister_gateway_notify(key)


def test_unregister_cancels_pending_control_request():
    a=owner();key,binding,ticket,_=begin(a)
    a.unregister_gateway_notify(key)
    decision=a.take_control_decision(ticket,now=110)
    assert decision.choice=='deny'
    assert a.consume_control_decision(decision,binding,now=110) is False


def test_decision_issued_before_deadline_cannot_be_consumed_later():
    a=owner();key,binding,ticket,_=begin(a)
    try:
        assert a.resolve_control_consent(session_key=key,request_id=ticket.request_id,intent_digest='a'*64,choice='once',now=110,presentation_digest=PD)
        decision=a.take_control_decision(ticket,now=110)
        assert a.consume_control_decision(decision,binding,now=161) is False
    finally:
        a.unregister_gateway_notify(key)
