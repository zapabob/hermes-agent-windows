"""Exercise strict entries in the actual existing approval queue, not a fake permit."""
import dataclasses

import pytest


def owner():
    from tools import approval
    required=('ControlApprovalBinding','request_control_consent','resolve_control_consent',
              'take_control_decision','consume_control_decision')
    if not all(hasattr(approval,k) for k in required):
        pytest.fail('Existing approval owner has no strict control-consent path',pytrace=False)
    return approval


def begin(approval):
    seen=[]
    key='control-test-session'
    approval.register_gateway_notify(key, seen.append)
    binding=approval.ControlApprovalBinding(operation_id='op-1',intent_digest='a'*64,
        subject='human-1',client_registration='codex',profile_id='p1',workspace_id='w1',expires_at=200,
        description='Start engineering in w1 at the approved revision')
    ticket=approval.request_control_consent(binding,session_key=key,timeout_seconds=60,now=100)
    return key,binding,ticket,seen


def test_actual_owner_queue_notifies_then_consumes_exact_once():
    a=owner(); key,binding,ticket,seen=begin(a)
    try:
        assert seen[0]['request_id']==ticket.request_id
        assert seen[0]['control']['intent_digest']==binding.intent_digest
        assert a.take_control_decision(ticket,now=110) is None
        assert a.resolve_control_consent(session_key=key,request_id=ticket.request_id,
                                        intent_digest='a'*64,choice='once',now=110) is True
        decision=a.take_control_decision(ticket,now=110)
        assert decision.choice=='once'
        assert a.consume_control_decision(decision,binding,now=110) is True
        assert a.consume_control_decision(decision,binding,now=110) is False
    finally:
        a.unregister_gateway_notify(key)


@pytest.mark.parametrize('kwargs',[{'choice':'always'},{'choice':'session'},{'choice':'smart_approve'},
    {'choice':'once','request_id':'stale'}, {'choice':'once','intent_digest':'b'*64}, {'choice':'once','now':161}])
def test_invalid_decision_cannot_signal_or_consume(kwargs):
    a=owner();key,binding,ticket,_=begin(a)
    try:
        args=dict(session_key=key,request_id=ticket.request_id,intent_digest='a'*64,choice='once',now=110)
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
    binding=a.ControlApprovalBinding(operation_id='op-1',intent_digest='a'*64,
        subject='human-1',client_registration='codex',profile_id='p1',workspace_id='w1',expires_at=200,
        description='Start engineering in w1 at the approved revision')
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


def test_forged_dataclass_copy_cannot_be_used_as_owner_decision():
    a=owner();key,binding,ticket,_=begin(a)
    try:
        a.resolve_control_consent(session_key=key,request_id=ticket.request_id,intent_digest='a'*64,choice='once',now=110)
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
