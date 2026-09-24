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
                                    verify_result=lambda request, operation_id, run_id, result: True,
                                    revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
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
                                    verify_result=lambda request, operation_id, run_id, result: True,
                                    revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
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
            verify_result=lambda *args: True, revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
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
            verify_result=lambda *args: False, revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
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


def test_owner_calls_real_entrypoint_with_host_issued_identity(
        control_module, control_context, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from downstream.implementation_router.kernel import RunResult
    from plugins.implementation_router import entrypoint
    from plugins.implementation_router.control import EngineeringRunOwner

    journal, ctx, operation_id = _approved(control_module, control_context, tmp_path)
    routes = {f'engineering_{role}': {'provider': 'custom:fixture', 'model': role}
              for role in ('planner', 'worker', 'reviewer')}
    monkeypatch.setattr('hermes_cli.config.load_config_readonly',
                        lambda: {'auxiliary': routes})
    monkeypatch.setattr('plugins.plugin_storage.plugin_data_dir',
                        lambda name: tmp_path / 'plugin-data')
    seen = []

    class FakeNativeHost:
        def __init__(self, **kwargs):
            seen.append(kwargs)
            self.run_dir = tmp_path / 'not-created'
            self.result_dir = None
            self.failure_diagnostic = None

        def close(self):
            pass

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, **kwargs):
            assert kwargs['host'] is not None
            return RunResult('BLOCKED', 'credential_boundary_unavailable', 0, 1, ())

    monkeypatch.setattr('plugins.implementation_router.host.NativeEngineeringHost', FakeNativeHost)
    monkeypatch.setattr(entrypoint, 'ImplementationRouter', FakeRouter)
    policy = {'path': str(tmp_path), 'image': 'sha256:' + 'a' * 64,
              'source_paths': ['source.py'], 'protected_paths': ['source.py'],
              'checks': [{'id': 'unit', 'argv': ['/usr/bin/true']}]}
    plugin_ctx = SimpleNamespace(get_config=lambda key, default=None:
        True if key == 'enabled' else {'w1': policy} if key == 'workspaces' else default)
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = EngineeringRunOwner(journal=journal, plugin_ctx=plugin_ctx,
            submit=pool.submit, validate_intent=lambda request: True,
            verify_result=lambda *args: False, revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
        handle = owner.start_approved(ctx, operation_id)
        assert handle.future.result(timeout=5)['state'] == 'BLOCKED'
    assert len(seen) == 1
    assert seen[0]['binding'].run_id == handle.run_id
    assert seen[0]['operation_id'] == operation_id
    assert seen[0]['ctx'] is plugin_ctx


def test_revoked_grant_before_native_worker_has_no_effect(
        control_module, control_context, tmp_path, monkeypatch):
    from downstream.control_mcp.contracts import ControlError
    from plugins.implementation_router import entrypoint
    from plugins.implementation_router.control import EngineeringRunOwner

    journal, ctx, operation_id = _approved(control_module, control_context, tmp_path)
    calls = []
    monkeypatch.setattr(entrypoint, 'run_workflow',
                        lambda *args, **kwargs: calls.append(True))
    gate = threading.Event()
    revoked = threading.Event()

    def revalidate(_ctx, *, now):
        if revoked.is_set():
            raise ControlError('revoked_grant')

    with ThreadPoolExecutor(max_workers=1) as pool:
        def deferred(fn, *args):
            return pool.submit(lambda: (gate.wait(5), fn(*args))[1])
        owner = EngineeringRunOwner(journal=journal, plugin_ctx=object(),
            submit=deferred, validate_intent=lambda request: True,
            verify_result=lambda *args: True, revalidate_grant=revalidate,
            clock=lambda: 103)
        handle = owner.start_approved(ctx, operation_id)
        revoked.set()
        gate.set()
        assert handle.future.result(timeout=5)['state'] == 'BLOCKED'
    assert calls == []
    assert journal.get(ctx, operation_id, profile_id='p1', workspace_id='w1',
                       now=104)['state'] == 'BLOCKED'


def test_ambiguous_native_dispatch_never_runs_and_keeps_reservation(
        control_module, control_context, tmp_path, monkeypatch):
    from downstream.control_mcp.contracts import ControlError
    from plugins.implementation_router import entrypoint
    from plugins.implementation_router.control import EngineeringRunOwner

    journal, ctx, operation_id = _approved(control_module, control_context, tmp_path)
    native_calls = []
    monkeypatch.setattr(entrypoint, 'run_workflow',
                        lambda *args, **kwargs: native_calls.append(True))
    scheduled = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        def ambiguous(fn, *args):
            scheduled.append(pool.submit(fn, *args))
            raise RuntimeError('accepted but no acknowledgement')
        owner = EngineeringRunOwner(journal=journal, plugin_ctx=object(),
            submit=ambiguous, validate_intent=lambda request: True,
            verify_result=lambda *args: True,
            revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
        with pytest.raises(ControlError) as caught:
            owner.start_approved(ctx, operation_id)
        assert caught.value.code == 'host_executor_unavailable'
        assert scheduled[0].result(timeout=5)['state'] == 'UNKNOWN'
    assert native_calls == []
    assert journal.get(ctx, operation_id, profile_id='p1', workspace_id='w1',
                       now=104)['state'] == 'UNKNOWN'
    with pytest.raises(ControlError) as busy:
        journal.reserve(ctx, {'kind': 'start_engineering_run', 'profile_id': 'p1',
            'workspace_id': 'w1', 'idempotency_key': 'another',
            'expected_revision': 'revision-1', 'source_sha': 'a' * 40,
            'parameters': {'task': 'No accidental replay'}}, now=104)
    assert busy.value.code == 'workspace_busy'


def test_owner_accepts_only_its_persisted_native_verification(
        control_module, control_context, tmp_path, monkeypatch):
    import sys
    from plugins.implementation_router import entrypoint
    from plugins.implementation_router.control import EngineeringRunOwner
    from plugins.implementation_router.workspace import digest

    journal, ctx, operation_id = _approved(control_module, control_context, tmp_path)
    home = tmp_path / 'profile'
    source = control_module('observations').HermesObservations(
        homes={'p1': home}, registered_slots=())

    def native_run(_ctx, _args, *, run_id, operation_id):
        run_dir = home / 'plugin-data' / 'implementation_router' / run_id
        result_dir = run_dir / 'verified-workspace'
        result_dir.mkdir(parents=True)
        files = {'source.py': b'print(1)\n'}
        (result_dir / 'source.py').write_bytes(files['source.py'])
        candidate = digest(files)
        attempt = run_id + ':stage:1:verify'
        manifest = {'schema_version': 1, 'run_id': run_id,
                    'operation_id': operation_id, 'workspace_id': 'w1',
                    'source_digest': 'd' * 64, 'route_fingerprint': 'e' * 64,
                    'required_checks': ['unit']}
        terminal = {'schema_version': 1, 'run_id': run_id, 'workspace_id': 'w1',
                    'run_state': 'SUCCEEDED', 'reason': 'all_required_host_checks_passed',
                    'verified_attempt_id': attempt, 'candidate_digest': candidate}
        receipt = {'schema_version': 1, 'evidence_type': 'host_verifier_check',
                   'run_id': run_id, 'workspace_id': 'w1', 'attempt_id': attempt,
                   'revision': 1, 'check_id': 'unit', 'exit_code': 0,
                   'completed': True, 'timed_out': False, 'approved': True,
                   'snapshot_before': candidate, 'snapshot_after': candidate,
                   'source_digest': 'd' * 64, 'candidate_digest': candidate,
                   'route_fingerprint': 'e' * 64, 'platform': sys.platform}
        workspace_receipt = {'run_id': run_id, 'workspace_digest': candidate,
                             'original_digest': 'd' * 64,
                             'route_fingerprint': 'e' * 64}
        for name, value in (('run-manifest.json', manifest),
                            ('run-result.json', terminal),
                            ('workspace-receipt.json', workspace_receipt)):
            (run_dir / name).write_text(json.dumps(value), encoding='utf-8')
        (run_dir / 'verification.jsonl').write_text(json.dumps(receipt) + '\n', encoding='utf-8')
        return json.dumps({'state': 'SUCCEEDED', 'run_id': run_id,
                           'verified_workspace': str(result_dir)})

    monkeypatch.setattr(entrypoint, 'run_workflow', native_run)
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = EngineeringRunOwner(journal=journal, plugin_ctx=object(),
            submit=pool.submit, validate_intent=lambda request: True,
            verify_result=source.verify_native_result,
            revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
        handle = owner.start_approved(ctx, operation_id)
        assert handle.future.result(timeout=5)['state'] == 'SUCCEEDED'
    assert journal.get(ctx, operation_id, profile_id='p1', workspace_id='w1',
                       now=104)['state'] == 'SUCCEEDED'
