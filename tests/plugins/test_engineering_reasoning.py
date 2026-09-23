"""Reasoning is an operator-owned route property, not a UI-only annotation."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from plugins.implementation_router.configuration import picker_routes
from plugins.implementation_router.actors import run_actor
from plugins.implementation_router.host import NativeEngineeringHost
from downstream.implementation_router.kernel import RunBinding


def config():
    return {'auxiliary': {f'engineering_{role}': {
        'provider': 'openai-codex', 'model': 'gpt-daybreak-blue-latest',
        'reasoning_effort': effort,
    } for role, effort in [('planner', 'medium'), ('worker', 'medium'), ('reviewer', 'high')]}}


def test_native_picker_snapshots_effort_and_fingerprint():
    raw = config()
    routes = picker_routes(raw)
    assert [r.reasoning_effort for _, r in routes.entries] == ['medium', 'medium', 'high']
    raw['auxiliary']['engineering_worker']['reasoning_effort'] = 'high'
    assert routes.for_role('worker').reasoning_effort == 'medium'
    assert routes.fingerprint() != picker_routes(raw).fingerprint()


@pytest.mark.parametrize('effort, expected', [(False, 'none'), ('disabled', 'none'), (' HIGH ', 'high'), ('', None), (None, None)])
def test_effort_uses_shared_hermes_semantics(effort, expected):
    raw = config(); raw['auxiliary']['engineering_planner']['reasoning_effort'] = effort
    assert picker_routes(raw).for_role('planner').reasoning_effort == expected


@pytest.mark.parametrize('effort', [True, 1, {}, [], 'synthetic-secret-not-a-level'])
def test_invalid_explicit_effort_is_not_ignored_or_echoed(effort):
    raw = config(); raw['auxiliary']['engineering_worker']['reasoning_effort'] = effort
    with pytest.raises(ValueError) as caught:
        picker_routes(raw)
    assert 'synthetic-secret' not in str(caught.value)


def test_conflicting_extra_body_is_not_silently_reinterpreted():
    raw = config()
    raw['auxiliary']['engineering_worker']['extra_body'] = {'reasoning': {'enabled': True, 'effort': 'high'}}
    with pytest.raises(ValueError):
        picker_routes(raw)


@pytest.mark.parametrize('role, effort', [('planner', 'medium'), ('worker', 'medium'), ('reviewer', 'high')])
def test_actor_passes_the_frozen_effort_to_parent_facade(role, effort):
    route = replace(picker_routes(config()).for_role(role), reasoning_effort=effort)
    llm = Mock()
    llm.complete.return_value = SimpleNamespace(text=json.dumps({'action': 'finish', 'result': {'stub': True}}))
    run_actor(llm=llm, route=route, role=role, handoff='{}', dispatch=Mock(), schemas={}, cancelled=lambda:False)
    assert llm.complete.call_args.kwargs['reasoning_config'] == {'enabled': True, 'effort': effort}
    assert llm.complete.call_args.kwargs['allow_fallback'] is False
    assert llm.complete.call_args.kwargs['expected_route'] == (route.provider, route.model)


def test_effort_only_drift_revokes_stage_admission(monkeypatch, tmp_path):
    raw = config(); routes = picker_routes(raw)
    host = NativeEngineeringHost(ctx=SimpleNamespace(get_config=lambda *a: True), routes=routes,
        workspace={}, data_dir=tmp_path, binding=RunBinding('run-one', 'workspace-one'))
    raw['auxiliary']['engineering_reviewer']['reasoning_effort'] = 'medium'
    monkeypatch.setattr('hermes_cli.config.load_config_readonly', lambda: raw)
    with pytest.raises(RuntimeError, match='changed'):
        host._routes_still_selected()


def test_real_parent_facade_to_codex_wire_across_profiles(tmp_path, monkeypatch):
    """Only the remote SSE stream/auth acquisition are inert; the native call chain is real."""
    import yaml
    from agent import auxiliary_client as aux
    from agent.plugin_llm import PluginLlm, _TrustPolicy
    from hermes_cli.config import load_config_readonly

    captured = []
    response_text = json.dumps({'action':'finish','result':{'fixture':True}})

    class Stream:
        def __iter__(self):
            item = SimpleNamespace(type='message', role='assistant', status='completed',
                content=[SimpleNamespace(type='output_text',text=response_text)])
            return iter([SimpleNamespace(type='response.created'),
                SimpleNamespace(type='response.output_item.done',item=item),
                SimpleNamespace(type='response.completed',response=SimpleNamespace(
                    status='completed', id='synthetic-response', usage=SimpleNamespace(input_tokens=1,output_tokens=1,total_tokens=2)))])
        def close(self): pass

    def create(**kwargs):
        wire = {**kwargs, **kwargs.get('extra_body', {})}
        captured.append({'model':wire['model'], 'reasoning':wire.get('reasoning')})
        return Stream()

    sdk = SimpleNamespace(base_url='https://chatgpt.com/backend-api/codex',responses=SimpleNamespace(create=create))
    client = SimpleNamespace(base_url=sdk.base_url, chat=SimpleNamespace(
        completions=aux._CodexCompletionsAdapter(sdk,'gpt-daybreak-blue-latest')))
    monkeypatch.setattr(aux, '_get_cached_client', lambda provider,model,**kw: (client,model))
    monkeypatch.setattr('hermes_cli.plugins.get_plugin_auxiliary_tasks',lambda:[
        {'key':f'engineering_{r}','plugin':'implementation_router'} for r in ('planner','worker','reviewer')])
    llm=PluginLlm(plugin_id='implementation_router',policy_loader=lambda _: _TrustPolicy('implementation_router'))
    a, b = tmp_path/'profile-a', tmp_path/'profile-b'
    for home, worker in [(a,'medium'),(b,'high')]:
        home.mkdir(); cfg=config(); cfg['auxiliary']['engineering_worker']['reasoning_effort']=worker
        (home/'config.yaml').write_text(yaml.safe_dump(cfg),encoding='utf-8')
    for home, efforts in [(a,['medium','medium','high']),(b,['medium','high','high']),(a,['medium','medium','high'])]:
        monkeypatch.setenv('HERMES_HOME', str(home))
        routes=picker_routes(load_config_readonly())
        for (role, route), effort in zip(routes.entries,efforts):
            run_actor(llm=llm,route=route,role=role,handoff='{}',schemas={},dispatch=Mock(),cancelled=lambda:False)
            assert captured[-1]['reasoning']['effort']==effort
            assert captured[-1]['model']=='gpt-daybreak-blue-latest'
    assert len(captured)==9
