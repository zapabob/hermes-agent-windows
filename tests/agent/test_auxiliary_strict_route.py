"""A pinned workflow stage must not promote itself through provider fallback."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agent import auxiliary_client as aux
from agent.plugin_llm import PluginLlm, _TrustPolicy


@pytest.fixture
def strict_boundary(monkeypatch):
    monkeypatch.setattr(aux, "_normalize_main_runtime", lambda value: {})
    monkeypatch.setattr(aux, "_resolve_task_provider_model", lambda *args: ("chosen-provider", "chosen-model", None, None, None))
    monkeypatch.setattr(aux, "_get_task_extra_body", lambda task: {})
    monkeypatch.setattr(aux, "_effective_provider_for_client", lambda client, requested: requested)
    missing = Mock(return_value=(None, "chosen-model"))
    fallback = Mock(side_effect=AssertionError("A different route must not be attempted"))
    monkeypatch.setattr(aux, "_get_cached_client", missing)
    monkeypatch.setattr(aux, "_try_configured_fallback_for_unavailable_client", fallback)
    return missing, fallback


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_unavailable_pinned_route_stops_without_trying_another_provider(strict_boundary, mode):
    missing, fallback = strict_boundary
    kwargs = dict(task="engineering_worker", messages=[{"role": "user", "content": "task"}], allow_fallback=False)
    with pytest.raises(RuntimeError, match="[Ss]trict"):
        if mode == "sync":
            aux.call_llm(**kwargs)
        else:
            asyncio.run(aux.async_call_llm(**kwargs))
    assert missing.call_count == 1
    fallback.assert_not_called()


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_strict_flag_is_forwarded_by_the_host_facade_without_exposing_clients(monkeypatch, mode):
    monkeypatch.setattr("hermes_cli.plugins.get_plugin_auxiliary_tasks", lambda: [
        {"key": "engineering_worker", "plugin": "engineering"},
    ])
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="done"))], model="chosen-model")
    caller = Mock(return_value=response) if mode == "sync" else AsyncMock(return_value=response)
    monkeypatch.setattr(aux, "call_llm" if mode == "sync" else "async_call_llm", caller)
    llm = PluginLlm(plugin_id="engineering", policy_loader=lambda _: _TrustPolicy(plugin_id="engineering"))
    if mode == "sync":
        result = llm.complete([{"role": "user", "content": "task"}], task="engineering_worker", allow_fallback=False)
    else:
        result = asyncio.run(llm.acomplete([{"role": "user", "content": "task"}], task="engineering_worker", allow_fallback=False))
    assert caller.call_args.kwargs["allow_fallback"] is False
    assert result.text == "done"
    assert not hasattr(result, "client")
    assert not hasattr(result, "api_key")


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_non_boolean_fallback_policy_is_rejected_before_resolution(monkeypatch, mode):
    resolve = Mock(side_effect=AssertionError("invalid policy reached resolution"))
    monkeypatch.setattr(aux, "_normalize_main_runtime", resolve)
    with pytest.raises(ValueError, match="allow_fallback"):
        if mode == "sync":
            aux.call_llm(messages=[], allow_fallback="false")
        else:
            asyncio.run(aux.async_call_llm(messages=[], allow_fallback="false"))
    resolve.assert_not_called()


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_changed_picker_choice_is_rejected_before_client_construction(monkeypatch, mode):
    monkeypatch.setattr(aux, "_get_auxiliary_task_config", lambda _: {"provider": "custom:new", "model": "new-model"})
    constructor = Mock(side_effect=AssertionError("configuration drift reached auth"))
    monkeypatch.setattr(aux, "_get_cached_client", constructor)
    kwargs = dict(task="engineering_worker", messages=[], allow_fallback=False,
                  expected_route=("custom:old", "old-model"))
    with pytest.raises(RuntimeError, match="changed"):
        if mode == "sync":
            aux.call_llm(**kwargs)
        else:
            asyncio.run(aux.async_call_llm(**kwargs))
    constructor.assert_not_called()


def test_selected_custom_route_is_checked_before_native_normalisation(monkeypatch):
    monkeypatch.setattr(aux, "_get_auxiliary_task_config", lambda _: {"provider": "custom:lab", "model": "org/test"})
    value = aux._resolve_task_provider_model("engineering_worker", expected_route=("custom:lab", "org/test"))
    assert value[1] == "org/test"


@pytest.mark.parametrize('mode', ['sync','async'])
def test_strict_route_rejects_extra_body_model_override_before_auth(strict_boundary, monkeypatch, mode):
    missing, fallback = strict_boundary
    monkeypatch.setattr(aux, '_get_task_extra_body', lambda _: {'model':'not-selected'})
    with pytest.raises(ValueError,match='routing'):
        if mode=='sync':
            aux.call_llm(task='engineering_worker',messages=[],allow_fallback=False)
        else:
            asyncio.run(aux.async_call_llm(task='engineering_worker',messages=[],allow_fallback=False))
    missing.assert_not_called()
