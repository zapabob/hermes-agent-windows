"""The native verifier itself publishes bounded, typed evidence."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import sys
from types import SimpleNamespace

from downstream.implementation_router.kernel import AuditEvent, RunBinding, RunResult, VerificationRequest
from plugins.implementation_router import host as native_host
from plugins.implementation_router.workspace import digest


class _FakeEnvironment:
    def assert_quiescent(self):
        pass

    def execute_clean(self, argv, *, timeout):
        assert argv == ('/usr/bin/true',)
        assert timeout == 120
        return {'returncode': 0, 'output': ''}


def test_native_verify_persists_typed_check_receipt(tmp_path: Path, monkeypatch):
    binding = RunBinding('eng-' + 'a' * 32, 'w1')
    routes = SimpleNamespace(fingerprint=lambda: 'b' * 64)
    files = {'source.py': b'print(1)\n'}
    candidate = digest(files)
    instance = native_host.NativeEngineeringHost(
        ctx=None, routes=routes,
        workspace={'checks': [{'id': 'unit', 'argv': ['/usr/bin/true']}]},
        data_dir=tmp_path, binding=binding, operation_id='op-' + 'c' * 32,
    )
    instance.run_dir.mkdir()
    instance._source = files
    instance.record_manifest()
    instance._guards = {}
    instance.env = _FakeEnvironment()
    evidence_file = instance.run_dir / 'verification.jsonl'
    instance._evidence = evidence_file.open('x', encoding='utf-8')
    monkeypatch.setattr(native_host, 'snapshot', lambda env: files)
    monkeypatch.setattr('tools.approval.check_all_command_guards',
                        lambda command, environment, **kwargs: {'approved': True})
    try:
        attempt = binding.run_id + ':stage:1:verify'
        receipts = instance.verify(VerificationRequest(
            binding, attempt, 1, candidate, ('unit',)))
        instance.result_dir = instance.run_dir / 'verified-workspace'
        instance.result_dir.mkdir()
        instance.record_result(RunResult(
            'SUCCEEDED', 'all_required_host_checks_passed', 1, 1,
            (AuditEvent('succeeded', attempt, 1),)))
        instance.close()
        rows = [json.loads(line) for line in evidence_file.read_text(encoding='utf-8').splitlines()]
    finally:
        if instance._evidence is not None:
            instance._evidence.close()
    assert len(receipts) == 1 and receipts[0].exit_code == 0
    manifest = json.loads((instance.run_dir / 'run-manifest.json').read_text(encoding='utf-8'))
    terminal = json.loads((instance.run_dir / 'run-result.json').read_text(encoding='utf-8'))
    assert manifest['workspace_id'] == 'w1' and manifest['required_checks'] == ['unit']
    assert manifest['operation_id'] == 'op-' + 'c' * 32
    assert terminal['verified_attempt_id'] == attempt and terminal['candidate_digest'] == candidate
    assert rows == [{
        'schema_version': 1, 'evidence_type': 'host_verifier_check',
        'run_id': binding.run_id, 'workspace_id': 'w1',
        'attempt_id': binding.run_id + ':stage:1:verify', 'revision': 1,
        'check_id': 'unit', 'exit_code': 0, 'completed': True,
        'timed_out': False, 'approved': True,
        'snapshot_before': candidate, 'snapshot_after': candidate,
        'source_digest': candidate, 'candidate_digest': candidate,
        'route_fingerprint': 'b' * 64, 'platform': sys.platform,
    }]


@pytest.mark.parametrize('fault', (None, 'exit_one', 'timeout', 'wrong_attempt',
                                   'missing_check', 'source_mismatch', 'route_mismatch'))
def test_scoped_observation_reads_bound_native_receipts(tmp_path: Path, control_module, control_context, fault):
    home = tmp_path / 'profile'
    run_id = 'eng-' + 'b' * 32
    run_dir = home / 'plugin-data' / 'implementation_router' / run_id
    run_dir.mkdir(parents=True)
    candidate = 'c' * 64
    attempt = run_id + ':stage:1:verify'
    manifest = {
        'schema_version': 1, 'run_id': run_id, 'workspace_id': 'w1',
        'source_digest': 'd' * 64, 'route_fingerprint': 'e' * 64,
        'required_checks': ['unit'],
    }
    terminal = {
        'schema_version': 1, 'run_id': run_id, 'workspace_id': 'w1',
        'run_state': 'SUCCEEDED', 'reason': 'all_required_host_checks_passed',
        'verified_attempt_id': attempt, 'candidate_digest': candidate,
    }
    receipt = {
        'schema_version': 1, 'evidence_type': 'host_verifier_check',
        'run_id': run_id, 'workspace_id': 'w1', 'attempt_id': attempt,
        'revision': 1, 'check_id': 'unit', 'exit_code': 0, 'completed': True,
        'timed_out': False, 'approved': True, 'snapshot_before': candidate,
        'snapshot_after': candidate, 'source_digest': 'd' * 64,
        'candidate_digest': candidate, 'route_fingerprint': 'e' * 64,
        'platform': sys.platform,
    }
    if fault == 'exit_one':
        receipt['exit_code'] = 1
    elif fault == 'timeout':
        receipt['timed_out'] = True
    elif fault == 'wrong_attempt':
        receipt['attempt_id'] = run_id + ':stage:2:verify'
    elif fault == 'source_mismatch':
        receipt['source_digest'] = '0' * 64
    elif fault == 'route_mismatch':
        receipt['route_fingerprint'] = '0' * 64
    for name, data in [('run-manifest.json', manifest), ('run-result.json', terminal)]:
        (run_dir / name).write_text(json.dumps(data), encoding='utf-8')
    evidence_line = '' if fault == 'missing_check' else json.dumps(receipt) + '\n'
    (run_dir / 'verification.jsonl').write_text(evidence_line, encoding='utf-8')
    source = control_module('observations').HermesObservations(
        homes={'p1': home}, registered_slots=())
    service = control_module('service').HostControlService(source=source, clock=lambda: 100)
    ctx = control_context()
    run = service.read(ctx, 'hermes_get_run', {
        'profile_id': 'p1', 'workspace_id': 'w1', 'run_id': run_id})
    assert run['state'] == 'AVAILABLE' and run['run_state'] == 'SUCCEEDED'
    if fault in ('source_mismatch', 'route_mismatch'):
        with pytest.raises(control_module('contracts').ControlError) as invalid:
            service.read(ctx, 'hermes_get_evidence', {
                'profile_id': 'p1', 'workspace_id': 'w1', 'run_id': run_id})
        assert invalid.value.code == 'observation_unavailable'
    else:
        evidence = service.read(ctx, 'hermes_get_evidence', {
            'profile_id': 'p1', 'workspace_id': 'w1', 'run_id': run_id})
        assert evidence['verified'] is (fault is None)
        assert evidence['state'] == ('AVAILABLE' if fault is None else 'PARTIAL')
        if fault != 'missing_check':
            assert evidence['checks'][0]['check_id'] == 'unit'
    with pytest.raises(control_module('contracts').ControlError) as denied:
        service.read(control_context(workspaces=(('p1', 'w2'),)), 'hermes_get_evidence', {
            'profile_id': 'p1', 'workspace_id': 'w2', 'run_id': run_id})
    assert denied.value.code == 'resource_denied'


def test_failed_native_result_is_observable_without_becoming_verified(
        tmp_path: Path, control_module):
    run_id = 'eng-' + 'd' * 32
    home = tmp_path / 'profile'
    run_dir = home / 'plugin-data' / 'implementation_router' / run_id
    run_dir.mkdir(parents=True)
    (run_dir / 'run-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'run_id': run_id, 'workspace_id': 'w1',
        'operation_id': 'op-' + 'e' * 32,
        'source_digest': 'a' * 64, 'route_fingerprint': 'b' * 64,
        'required_checks': ['unit']}), encoding='utf-8')
    (run_dir / 'run-result.json').write_text(json.dumps({
        'schema_version': 1, 'run_id': run_id, 'workspace_id': 'w1',
        'run_state': 'FAILED', 'reason': 'required_check_failed',
        'verified_attempt_id': None, 'candidate_digest': None}), encoding='utf-8')
    (run_dir / 'verification.jsonl').write_text('', encoding='utf-8')
    source = control_module('observations').HermesObservations(
        homes={'p1': home}, registered_slots=())
    assert source.run('p1', run_id)['run_state'] == 'FAILED'
    assert source.evidence('p1', run_id)['verified'] is False


def test_capabilities_report_persisted_evidence_without_claiming_live_owner(
        tmp_path: Path, control_module, control_context):
    source = control_module('observations').HermesObservations(
        homes={'p1': tmp_path}, registered_slots=())
    service = control_module('service').HostControlService(source=source, clock=lambda: 100)
    capabilities = service.read(control_context(), 'hermes_get_capabilities',
                                {'profile_id': 'p1'})['capabilities']
    assert capabilities['typed_verification_evidence'] is True
    assert capabilities['live_run_observation'] is False
    assert capabilities['write'] is False
