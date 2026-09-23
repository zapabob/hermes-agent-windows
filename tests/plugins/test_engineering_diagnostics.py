"""A failed stage exposes only fixed diagnostics; no replay or secret-bearing logs."""
from __future__ import annotations

from contextlib import nullcontext
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from downstream.implementation_router.kernel import ImplementationRouter, RunBinding
from plugins.implementation_router.configuration import picker_routes
from plugins.implementation_router.host import NativeEngineeringHost


def diagnostics():
    try:
        return importlib.import_module('agent.engineering_diagnostics')
    except ModuleNotFoundError:
        pytest.fail('Safe engineering failure diagnostics are not implemented')


@pytest.mark.parametrize('error, code', [
    (PermissionError('synthetic-secret'), 'permission_denied'),
    (TimeoutError('synthetic-secret'), 'timeout'),
    (ConnectionError('synthetic-secret'), 'connection_error'),
    (TypeError('synthetic-secret'), 'call_contract_error'),
    (ValueError('synthetic-secret'), 'invalid_payload'),
    (ImportError('synthetic-secret'), 'missing_dependency'),
    (RuntimeError('synthetic-secret'), 'host_error'),
])
def test_error_classification_never_serialises_exception_text(error, code):
    assert diagnostics().failure_code(error) == code


def test_unknown_exception_type_is_not_an_output_field():
    unsafe_type = type('synthetic_secret_in_exception_name', (Exception,), {})
    assert diagnostics().failure_code(unsafe_type('more-secrets')) == 'host_error'


@pytest.mark.parametrize('phase', ['inference', 'actor_output', 'tool_dispatch'])
def test_real_kernel_stops_and_journals_only_safe_failure_metadata(tmp_path, monkeypatch, phase):
    cfg = {'auxiliary': {f'engineering_{r}': {'provider': 'fixture', 'model': r}
                         for r in ('planner', 'worker', 'reviewer')}}
    routes = picker_routes(cfg)
    binding = RunBinding('fixture-run', 'fixture-workspace')
    llm = Mock()
    if phase == 'inference':
        llm.complete.side_effect = PermissionError('Bearer synthetic-secret')
        expected = 'permission_denied'
    elif phase == 'actor_output':
        llm.complete.return_value = SimpleNamespace(text='not JSON synthetic-secret')
        expected = 'invalid_payload'
    else:
        llm.complete.return_value = SimpleNamespace(text=json.dumps({
            'action': 'tool', 'name': 'read_file', 'arguments': {'path': '/workspace/file.txt'}}))
        expected = 'connection_error'
    ctx = SimpleNamespace(get_config=lambda *a: True, llm=llm,
                          dispatch_tool=Mock(side_effect=ConnectionError('synthetic-secret')))
    host = NativeEngineeringHost(ctx=ctx, routes=routes,
        workspace={'path': str(tmp_path), 'source_paths':['file.txt'], 'protected_paths':['file.txt'],
                   'image':'fixture', 'checks':[{'id':'unit','argv':['/bin/true']}]},
        data_dir=tmp_path/'data', binding=binding)
    env = SimpleNamespace(assert_credential_free=Mock(), assert_quiescent=Mock(), cleanup=Mock())
    monkeypatch.setattr('hermes_cli.config.load_config_readonly', lambda: cfg)
    monkeypatch.setattr('plugins.implementation_router.host.DockerEnvironment.credential_free', lambda **kw: env)
    monkeypatch.setattr('plugins.implementation_router.host.bind_credential_free_environment', lambda *a: nullcontext(env))
    files = {'file.txt': b'test'}
    monkeypatch.setattr('plugins.implementation_router.host.read_sources', lambda *a: files)
    monkeypatch.setattr('plugins.implementation_router.host.import_sources', lambda *a: files)
    monkeypatch.setattr('plugins.implementation_router.host.snapshot', lambda *a: files)
    monkeypatch.setattr('tools.registry.registry.get_schema', lambda name: {})
    try:
        result = ImplementationRouter(routing=routes).run(task='task', binding=binding,
                                                        required_checks=('unit',), host=host)
        assert result.state == 'BLOCKED'
        assert result.reason == 'host_boundary_error_no_replay'
        assert llm.complete.call_count == 1
        events = [json.loads(line) for line in (host.run_dir/'events.jsonl').read_text().splitlines()]
        failure = next((e for e in events if e['kind'] == 'stage_failed'), None)
        assert failure is not None, 'First failing stage lost its diagnostic checkpoint'
        assert failure['failure_boundary'] == phase
        assert failure['failure_code'] == expected
        assert failure['role'] == 'planner'
        assert 'synthetic-secret' not in json.dumps(events)
        assert not any(e['kind'] in ('verification_start', 'succeeded') for e in events)
        assert list((tmp_path/'data').glob('*.lease')), 'Ambiguous run lease was removed'
        assert host.result_dir is None
        assert host.failure_diagnostic['code'] == expected
    finally:
        host.close()


def test_diagnostic_checkpoint_failure_does_not_claim_recorded_success(tmp_path, monkeypatch):
    from downstream.implementation_router.kernel import StageRequest
    from downstream.implementation_router.routes import RoutingTable, ModelRoute
    routes = RoutingTable(True, tuple((r, ModelRoute('fixture',r)) for r in ('planner','worker','reviewer')))
    binding = RunBinding('fixture-run','fixture-workspace')
    host=NativeEngineeringHost(ctx=SimpleNamespace(llm=Mock()),routes=routes,workspace={},data_dir=tmp_path,binding=binding)
    host.ctx.llm.complete.side_effect=ValueError('synthetic-secret')
    host.checkpoint=Mock(side_effect=OSError('disk-full synthetic-secret'))
    monkeypatch.setattr('tools.registry.registry.get_schema', lambda name: {})
    request=StageRequest(binding,'attempt','planner',1,'{}',routes.for_role('planner'))
    with pytest.raises(Exception):
        host.stage(request)
    assert getattr(host,'failure_diagnostic',None) is None
    assert host.checkpoint.call_count == 1


@pytest.mark.parametrize('status, expected', [(400,'provider_request_rejected'),(401,'provider_authentication'),
    (403,'provider_authorisation'),(429,'provider_rate_limit'),(503,'provider_unavailable'),(418,'provider_error')])
def test_provider_diagnostics_use_only_http_status_not_body(status, expected):
    from openai import APIStatusError
    import httpx
    error=APIStatusError('synthetic-secret',response=httpx.Response(status,
        request=httpx.Request('POST','https://example.test/private-secret')),
        body={'token':'synthetic-secret'})
    assert diagnostics().failure_code(error)==expected


@pytest.mark.parametrize('state', ['BLOCKED', 'SUCCEEDED'])
def test_tool_output_exposes_only_a_recorded_blocked_diagnostic(state, tmp_path, monkeypatch):
    from downstream.implementation_router.kernel import RunResult
    from plugins.implementation_router.entrypoint import run_workflow
    cfg={'auxiliary':{f'engineering_{r}':{'provider':'fixture','model':r} for r in ('planner','worker','reviewer')}}
    workspaces={'sample':{'path':str(tmp_path),'image':'fixture','source_paths':['x'],
        'protected_paths':['x'],'checks':[{'id':'unit','argv':['/bin/true']}]}}
    ctx=SimpleNamespace(get_config=lambda key,default=None:True if key=='enabled' else workspaces)
    diagnostic={'stage':'planner','attempt_id':'fixture-run:stage:1','boundary':'inference','code':'timeout'}
    host=SimpleNamespace(failure_diagnostic=diagnostic,result_dir=None,close=Mock())
    monkeypatch.setattr('hermes_cli.config.load_config_readonly',lambda:cfg)
    monkeypatch.setattr('plugins.plugin_storage.plugin_data_dir',lambda *args:tmp_path)
    monkeypatch.setattr('plugins.implementation_router.host.NativeEngineeringHost',lambda **kwargs:host)
    monkeypatch.setattr('downstream.implementation_router.kernel.ImplementationRouter.run',lambda *a,**kw:
        RunResult(state,'host_boundary_error_no_replay' if state=='BLOCKED' else 'all_required_host_checks_passed',1,1,()))
    result=json.loads(run_workflow(ctx,{'workspace':'sample','task':'task'}))
    assert result['state']==state
    if state=='BLOCKED':assert result['diagnostic']==diagnostic
    else:assert 'diagnostic' not in result
    host.close.assert_called_once()
