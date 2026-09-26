"""Native workflow contracts: parent-owned inference, configured native picker slots."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def module(name):
    try:
        return importlib.import_module('plugins.implementation_router.' + name)
    except ModuleNotFoundError as exc:
        pytest.fail(f'native engineering integration is missing: {exc.name}')


def test_retired_plugin_registers_only_a_diagnostic_even_when_enabled(monkeypatch):
    plugin = module('__init__')
    ctx = Mock()
    ctx.get_config.return_value = True
    entrypoint = module('entrypoint')
    retired_run = Mock(side_effect=AssertionError('retired workflow was invoked'))
    monkeypatch.setattr(entrypoint, 'run_workflow', retired_run)

    plugin.register(ctx)
    ctx.register_auxiliary_task.assert_not_called()
    ctx.register_tool.assert_not_called()
    assert ctx.register_command.call_args.args[0] == 'engineer'
    handler = ctx.register_command.call_args.kwargs['handler']
    result = json.loads(handler('{"workspace":"sample","task":"execute"}'))
    assert result['state'] == 'BLOCKED'
    assert result['reason_code'] == 'legacy_engineering_router_retired'
    assert 'migration' in result
    assert result['legacy_operation']['read_tool'] == 'hermes_get_operation'
    assert result['legacy_operation']['stop_status'] == 'NO_PUBLIC_STOP'
    retired_run.assert_not_called()
    assert not ctx.llm.complete.called
    assert not ctx.subagent_lifecycle.launch.called


def test_retired_plugin_loader_exposes_no_stage_tool_or_picker_slot(tmp_path, monkeypatch):
    from hermes_cli import plugins as plugin_api
    from hermes_cli.plugins import PluginManager, PluginManifest
    from tools.registry import registry

    plugin_path = Path(__file__).resolve().parents[2] / 'plugins' / 'implementation_router'
    manager = PluginManager(scope_key=str(tmp_path))
    manifest = PluginManifest(name='implementation_router', source='project', path=str(plugin_path))
    try:
        manager._load_plugin(manifest)
        monkeypatch.setattr(plugin_api, '_ensure_plugins_discovered', lambda: manager)

        assert manager._plugins['implementation_router'].enabled is True
        assert set(plugin_api.get_plugin_commands()) == {'engineer'}
        assert plugin_api.get_plugin_auxiliary_tasks() == []
        assert registry.get_entry('engineering_run', scope=manager.scope_key) is None
        assert json.loads(plugin_api.get_plugin_commands()['engineer']['handler']('invalid JSON'))[
            'reason_code'] == 'legacy_engineering_router_retired'
    finally:
        manager.unload()


def test_routes_come_from_existing_picker_including_custom_provider():
    config = module('configuration')
    slots = {f'engineering_{role}': {'provider': 'custom:lab', 'model': f'org/{role}'}
             for role in ('planner','worker','reviewer')}
    routes = config.picker_routes({'auxiliary': slots})
    assert routes.for_role('worker').provider == 'custom:lab'
    assert routes.for_role('worker').model == 'org/worker'


@pytest.mark.parametrize('values', [{}, {'provider':'auto','model':''}, {'provider':'custom:lab','model':'auto'}])
def test_unselected_native_slot_is_not_silently_promoted(values):
    config = module('configuration')
    with pytest.raises(ValueError):
        config.picker_routes({'auxiliary': {f'engineering_{role}': values for role in ('planner','worker','reviewer')}})


def test_actor_uses_only_the_host_facade_and_rejects_authority_arguments():
    actors = module('actors')
    route = SimpleNamespace(provider='custom:lab', model='org/worker')
    llm = Mock()
    llm.complete.return_value = SimpleNamespace(text=json.dumps({
        'action':'tool', 'name':'terminal', 'arguments':{'command':'true','force':True}}))
    dispatch = Mock()
    with pytest.raises(ValueError, match='argument'):
        actors.run_actor(llm=llm, route=route, role='worker', handoff='{}',
                         dispatch=dispatch, schemas={'terminal':{}}, cancelled=lambda:False,
                         max_calls=3)
    dispatch.assert_not_called()
    assert llm.complete.call_args.kwargs['task'] == 'engineering_worker'
    assert llm.complete.call_args.kwargs['allow_fallback'] is False
    assert llm.complete.call_args.kwargs['expected_route'] == ('custom:lab','org/worker')


def test_planner_cannot_execute_a_terminal_or_write():
    actors = module('actors')
    llm = Mock()
    llm.complete.return_value = SimpleNamespace(text=json.dumps({
        'action':'tool','name':'terminal','arguments':{'command':'true'}}))
    with pytest.raises(ValueError):
        actors.run_actor(llm=llm, route=SimpleNamespace(provider='p',model='m'), role='planner',
                         handoff='{}', dispatch=Mock(), schemas={'read_file':{}},
                         cancelled=lambda:False, max_calls=3)


def test_actor_budget_is_finite_and_explicit_finish_keeps_structured_plan():
    actors = module('actors')
    llm = Mock()
    plan={'objective':'task','constraints':['keep API'],'steps':['test first'],'acceptance_criteria':['tests pass']}
    llm.complete.return_value = SimpleNamespace(text=json.dumps({'action':'finish','result':plan}))
    result = actors.run_actor(llm=llm, route=SimpleNamespace(provider='p',model='m'), role='planner',
                             handoff='{}', dispatch=Mock(), schemas={}, cancelled=lambda:False, max_calls=2)
    assert json.loads(result) == plan
    llm.complete.return_value = SimpleNamespace(text=json.dumps({'action':'tool','name':'read_file','arguments':{'path':'x'}}))
    with pytest.raises(RuntimeError, match='budget'):
        actors.run_actor(llm=llm, route=SimpleNamespace(provider='p',model='m'), role='planner',
                         handoff='{}', dispatch=lambda *args:'{"content":"x"}', schemas={'read_file':{}},
                         cancelled=lambda:False, max_calls=2)


def test_source_paths_reject_secrets_and_traversal(tmp_path):
    workspace = module('workspace')
    (tmp_path/'hello.py').write_text('print(1)')
    (tmp_path/'.env').write_text('SECRET=synthetic')
    assert list(workspace.read_sources(tmp_path, ('hello.py',))) == ['hello.py']
    for name in ('.env', '../outside', str(tmp_path/'hello.py')):
        with pytest.raises(ValueError):
            workspace.read_sources(tmp_path, (name,))


def test_source_paths_reject_symlinks(tmp_path):
    workspace = module('workspace')
    (tmp_path/'hello.py').write_text('print(1)')
    try:
        (tmp_path/'alias').symlink_to(tmp_path/'hello.py')
    except OSError as exc:
        if os.name == 'nt' and exc.winerror == 1314:
            pytest.skip('Creating symlinks requires Windows privileges')
        raise
    with pytest.raises(ValueError):
        workspace.read_sources(tmp_path, ('alias',))


def test_disabled_entrypoint_never_constructs_a_host(monkeypatch):
    entry = module('entrypoint')
    ctx = Mock()
    ctx.get_config.return_value = False
    ctx.plugin_id = 'implementation_router'
    out = json.loads(entry.run_workflow(ctx, {'workspace':'sample','task':'implement'}))
    assert out['state'] == 'BLOCKED'
    assert out['reason_code'] == 'routing_disabled'
    ctx.llm.complete.assert_not_called()


@pytest.mark.parametrize('args', [
    {'workspace':'sample','task':'x','provider':'override'},
    {'workspace':'../escape','task':'x'}, {'workspace':'sample','task':''},
])
def test_entrypoint_never_accepts_model_controlled_authority(args):
    entry = module('entrypoint')
    ctx = Mock()
    ctx.get_config.return_value = True
    out = json.loads(entry.run_workflow(ctx,args))
    assert out['state'] == 'BLOCKED'
    ctx.llm.complete.assert_not_called()


def test_host_is_not_an_authenticated_subagent_factory():
    host = module('host')
    assert callable(host.NativeEngineeringHost)
    import inspect
    source = inspect.getsource(host)
    assert 'subagent_lifecycle.launch' not in source
    assert 'AIAgent(' not in source
    assert 'ctx.llm' in source
    assert 'bind_credential_free_environment' in source


def test_picker_model_ids_are_opaque_not_brand_or_snapshot_allowlists():
    config = module('configuration')
    slots = {f'engineering_{r}': {'provider':'custom:lab','model':'team/model@checkpoint?revision=2'}
             for r in ('planner','worker','reviewer')}
    assert config.picker_routes({'auxiliary':slots}).for_role('worker').model == 'team/model@checkpoint?revision=2'
