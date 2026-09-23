"""The approved journal operation reaches the registered native entrypoint once."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest


def _approved(control_module, control_context, tmp_path):
    from tools import approval

    ctx = control_context(scopes=('hermes:read', 'hermes:run:start', 'hermes:run:cancel'))
    journal = control_module('journal').HostControlJournal(tmp_path / 'control.db')
    journal.initialise()
    request = {'kind': 'start_engineering_run', 'profile_id': 'p1', 'workspace_id': 'w1',
               'idempotency_key': 'owner-1', 'expected_revision': 'revision-1',
               'source_sha': 'a' * 40, 'parameters': {'task': 'Implement a bounded test'}}
    operation = journal.reserve(ctx, request, now=100)
    binding = journal.approval_binding(ctx, operation['operation_id'], now=101)
    approval.register_gateway_notify('human-owner', lambda _: None)
    try:
        ticket = approval.request_control_consent(binding, session_key='human-owner',
                                                  timeout_seconds=60, now=101)
        assert approval.resolve_control_consent(session_key='human-owner',
            request_id=ticket.request_id, intent_digest=binding.intent_digest,
            choice='once', now=102)
        decision = approval.take_control_decision(ticket, now=102)
        journal.approve(ctx, operation['operation_id'], decision, now=102)
    finally:
        approval.unregister_gateway_notify('human-owner')
    return journal, ctx, operation['operation_id']


def test_approved_operation_invokes_registered_entrypoint_once(
        control_module, control_context, tmp_path, monkeypatch):
    from plugins.implementation_router import entrypoint
    from plugins.implementation_router.control import EngineeringRunOwner

    journal, ctx, operation_id = _approved(control_module, control_context, tmp_path)
    calls = []
    plugin_ctx = object()

    def native_run(actual_ctx, args, *, run_id, operation_id):
        calls.append((actual_ctx, args, run_id, operation_id))
        return json.dumps({'state': 'SUCCEEDED', 'run_id': run_id})

    monkeypatch.setattr(entrypoint, 'run_workflow', native_run)
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = EngineeringRunOwner(journal=journal, plugin_ctx=plugin_ctx,
                                    submit=pool.submit, validate_intent=lambda request: True,
                                    verify_result=lambda request, run_id, result: True,
                                    clock=lambda: 103)
        handle = owner.start_approved(ctx, operation_id)
        assert handle.future.result(timeout=5)['state'] == 'SUCCEEDED'
        assert calls == [(plugin_ctx, {'workspace': 'w1', 'task': 'Implement a bounded test'},
                          handle.run_id, operation_id)]
        assert journal.get(ctx, operation_id, profile_id='p1', workspace_id='w1',
                           now=104)['state'] == 'SUCCEEDED'
        with pytest.raises(control_module('contracts').ControlError):
            owner.start_approved(ctx, operation_id)
        assert len(calls) == 1


def test_cancel_is_bound_to_run_generation_and_live_thread(
        control_module, control_context, tmp_path, monkeypatch):
    from plugins.implementation_router import entrypoint
    from plugins.implementation_router.control import EngineeringRunOwner
    from tools.interrupt import is_interrupted

    journal, ctx, operation_id = _approved(control_module, control_context, tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def native_run(_ctx, _args, *, run_id, operation_id):
        entered.set()
        assert release.wait(5)
        return json.dumps({'state': 'BLOCKED' if is_interrupted() else 'SUCCEEDED',
                           'run_id': run_id})

    monkeypatch.setattr(entrypoint, 'run_workflow', native_run)
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = EngineeringRunOwner(journal=journal, plugin_ctx=object(),
                                    submit=pool.submit, validate_intent=lambda request: True,
                                    verify_result=lambda request, run_id, result: True,
                                    clock=lambda: 103)
        handle = owner.start_approved(ctx, operation_id)
        try:
            assert entered.wait(5)
            assert owner.cancel(handle.run_id, 'wrong-generation') is False
            assert owner.cancel('eng-foreign', handle.owner_generation) is False
            assert owner.cancel(handle.run_id, handle.owner_generation) is True
        finally:
            release.set()
        assert handle.future.result(timeout=5)['state'] == 'BLOCKED'
        assert owner.cancel(handle.run_id, handle.owner_generation) is False


def test_preflight_rejection_has_no_native_effect(control_module, control_context, tmp_path, monkeypatch):
    from plugins.implementation_router import entrypoint
    from plugins.implementation_router.control import EngineeringRunOwner

    journal, ctx, operation_id = _approved(control_module, control_context, tmp_path)
    calls = []
    monkeypatch.setattr(entrypoint, 'run_workflow', lambda *args, **kwargs: calls.append(True))
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = EngineeringRunOwner(journal=journal, plugin_ctx=object(),
            submit=pool.submit, validate_intent=lambda request: False,
            verify_result=lambda *args: True, clock=lambda: 103)
        handle = owner.start_approved(ctx, operation_id)
        assert handle.future.result(timeout=5)['state'] == 'BLOCKED'
    assert calls == []
    assert journal.get(ctx, operation_id, profile_id='p1', workspace_id='w1',
                       now=104)['state'] == 'BLOCKED'


def test_success_without_native_evidence_stays_unknown(
        control_module, control_context, tmp_path, monkeypatch):
    from plugins.implementation_router import entrypoint
    from plugins.implementation_router.control import EngineeringRunOwner

    journal, ctx, operation_id = _approved(control_module, control_context, tmp_path)
    monkeypatch.setattr(entrypoint, 'run_workflow',
        lambda _ctx, _args, *, run_id, operation_id: json.dumps(
            {'state': 'SUCCEEDED', 'run_id': run_id}))
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = EngineeringRunOwner(journal=journal, plugin_ctx=object(),
            submit=pool.submit, validate_intent=lambda request: True,
            verify_result=lambda *args: False, clock=lambda: 103)
        handle = owner.start_approved(ctx, operation_id)
        assert handle.future.result(timeout=5)['state'] == 'UNKNOWN'
    assert journal.get(ctx, operation_id, profile_id='p1', workspace_id='w1',
                       now=104)['state'] == 'UNKNOWN'
    with pytest.raises(control_module('contracts').ControlError) as caught:
        journal.reserve(ctx, {'kind': 'start_engineering_run', 'profile_id': 'p1',
            'workspace_id': 'w1', 'idempotency_key': 'owner-2',
            'expected_revision': 'revision-1', 'source_sha': 'a' * 40,
            'parameters': {'task': 'Do not replay'}}, now=104)
    assert caught.value.code == 'workspace_busy'
