"""Native workflow contracts: parent-owned inference, configured native picker slots."""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def module(name):
    try:
        return importlib.import_module('plugins.implementation_router.' + name)
    except ModuleNotFoundError as exc:
        pytest.fail(f'native engineering integration is missing: {exc.name}')


def test_register_reuses_native_picker_and_does_not_activate_provider_clients():
    plugin = module('__init__')
    ctx = Mock()
    ctx.get_config.return_value = False
    plugin.register(ctx)
    assert [call.kwargs['key'] for call in ctx.register_auxiliary_task.call_args_list] == [
        'engineering_planner', 'engineering_worker', 'engineering_reviewer']
    assert ctx.register_command.call_args.args[0] == 'engineer'
    assert ctx.register_tool.call_args.kwargs['name'] == 'engineering_run'
    assert not ctx.llm.complete.called
    assert not ctx.subagent_lifecycle.launch.called


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


def test_source_paths_reject_secrets_symlinks_and_traversal(tmp_path):
    workspace = module('workspace')
    (tmp_path/'hello.py').write_text('print(1)')
    (tmp_path/'.env').write_text('SECRET=synthetic')
    assert list(workspace.read_sources(tmp_path, ('hello.py',))) == ['hello.py']
    for name in ('.env', '../outside', str(tmp_path/'hello.py')):
        with pytest.raises(ValueError):
            workspace.read_sources(tmp_path, (name,))
    (tmp_path/'alias').symlink_to(tmp_path/'hello.py')
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
