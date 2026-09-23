"""Generic host facade forwards reasoning without changing ordinary plugin calls."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from agent.plugin_llm import PluginLlm, _TrustPolicy


@pytest.mark.parametrize('method', ['complete', 'acomplete', 'complete_structured', 'acomplete_structured'])
@pytest.mark.parametrize('reasoning', [{'enabled': True, 'effort': 'high'}, {'enabled': False}, None])
def test_parent_facade_forwards_explicit_reasoning(method, reasoning):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    caller = AsyncMock(return_value=('p', 'm', response)) if method.startswith('a') else Mock(return_value=('p','m',response))
    llm = PluginLlm(plugin_id='test-plugin', policy_loader=lambda _: _TrustPolicy('test-plugin'),
                    **({'async_caller':caller} if method.startswith('a') else {'sync_caller':caller}))
    args = {'instructions':'Return JSON', 'input':[{'type':'text','text':'task'}]} if 'structured' in method else {'messages':[{'role':'user','content':'task'}]}
    if reasoning is not None: args['reasoning_config'] = deepcopy(reasoning)
    try:
        output = getattr(llm, method)(**args)
        if method.startswith('a'): output = asyncio.run(output)
    except TypeError as exc:
        pytest.fail(f'Facade cannot accept the requested reasoning configuration: {exc}')
    if reasoning is None:
        assert 'reasoning_config' not in caller.call_args.kwargs
    else:
        assert caller.call_args.kwargs['reasoning_config'] == reasoning
    assert output.text == '{}'


@pytest.mark.parametrize('method', ['complete', 'acomplete', 'complete_structured', 'acomplete_structured'])
def test_native_facade_path_forwards_reasoning_to_shared_auxiliary(method, monkeypatch):
    from agent import auxiliary_client as aux
    response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    caller=AsyncMock(return_value=response) if method.startswith('a') else Mock(return_value=response)
    monkeypatch.setattr(aux, 'async_call_llm' if method.startswith('a') else 'call_llm',caller)
    llm=PluginLlm(plugin_id='fixture',policy_loader=lambda _: _TrustPolicy('fixture'))
    kwargs={'instructions':'Return JSON','input':[{'type':'text','text':'test'}]} if 'structured' in method else {'messages':[{'role':'user','content':'test'}]}
    kwargs['reasoning_config']={'enabled':True,'effort':'high'}
    outcome=getattr(llm,method)(**kwargs)
    if method.startswith('a'):outcome=asyncio.run(outcome)
    assert caller.call_args.kwargs['reasoning_config']=={'enabled':True,'effort':'high'}
    assert outcome.text=='{}'
