"""Registered auxiliary slots use the native dashboard picker, not a second catalogue."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy

import pytest


@pytest.fixture
def dashboard(monkeypatch):
    from hermes_cli import plugins, web_server as ws

    # The real plugin registration API owns these slots. Only persistence and
    # profile selection are inert here; no model, auth store or listener runs.
    managers = {}
    configs = {}
    active = ["default"]
    for profile in ("default", "engineering"):
        manager = plugins.PluginManager()
        manager._discovered = True
        managers[profile] = manager
        configs[profile] = {"auxiliary": {}, "model": {"provider": "local", "default": "base"}}
    ctx = plugins.PluginContext(plugins.PluginManifest(name="engineering"), managers["engineering"])
    ctx.register_auxiliary_task(
        "engineering_worker", display_name="Implementation worker", description="Bounded implementation",
        defaults={"api_key": "synthetic-do-not-display", "timeout": 73},
    )

    @contextmanager
    def scope(profile=None):
        previous = active[0]
        active[0] = profile or previous
        try:
            yield
        finally:
            active[0] = previous

    monkeypatch.setattr(ws, "_profile_scope", scope)
    monkeypatch.setattr(ws, "load_config", lambda: deepcopy(configs[active[0]]))
    monkeypatch.setattr(ws, "save_config", lambda cfg: configs.__setitem__(active[0], deepcopy(cfg)))
    monkeypatch.setattr(plugins, "_ensure_plugins_discovered", lambda: managers[active[0]])
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: managers[active[0]])
    return ws, scope, configs, managers


def test_list_uses_active_profile_registry_and_never_exports_defaults(dashboard):
    ws, _, _, _ = dashboard
    result = ws.get_auxiliary_models(profile="engineering")
    entry = next((item for item in result["tasks"] if item["task"] == "engineering_worker"), None)
    assert entry is not None
    assert entry["display_name"] == "Implementation worker"
    assert entry["description"] == "Bounded implementation"
    assert entry["plugin"] == "engineering"
    assert "synthetic-do-not-display" not in repr(result)
    assert all(item["task"] != "engineering_worker" for item in ws.get_auxiliary_models()["tasks"])


@pytest.mark.parametrize("path", ["async", "sync"])
def test_set_custom_provider_model_from_existing_picker_and_reset(dashboard, path):
    ws, scope, configs, _ = dashboard
    slot = "engineering_worker"
    configs["engineering"]["auxiliary"][slot] = {"timeout": 73}
    if path == "async":
        result = asyncio.run(ws.set_model_assignment(ws.ModelAssignment(
            scope="auxiliary", task=slot, provider="custom:local-worker", model="org/custom-model",
            profile="engineering", confirm_expensive_model=True,
        )))
    else:
        with scope("engineering"):
            result = ws._apply_model_assignment_sync("auxiliary", "custom:local-worker", "org/custom-model", slot, "")
    assert result["ok"] is True
    assert configs["engineering"]["auxiliary"][slot]["model"] == "org/custom-model"
    assert configs["engineering"]["auxiliary"][slot]["timeout"] == 73
    assert slot not in configs["default"]["auxiliary"]
    if path == "async":
        asyncio.run(ws.set_model_assignment(ws.ModelAssignment(
            scope="auxiliary", task="__reset__", provider="", model="", profile="engineering", confirm_expensive_model=True,
        )))
    else:
        with scope("engineering"):
            ws._apply_model_assignment_sync("auxiliary", "", "", "__reset__", "")
    assert configs["engineering"]["auxiliary"][slot]["provider"] == "auto"
    assert configs["engineering"]["auxiliary"][slot]["timeout"] == 73


@pytest.mark.parametrize("path", ["async", "sync"])
def test_unregistered_task_does_not_gain_routing_permission(dashboard, path):
    ws, scope, configs, _ = dashboard
    before = deepcopy(configs)
    with pytest.raises(ws.HTTPException) as error:
        if path == "async":
            asyncio.run(ws.set_model_assignment(ws.ModelAssignment(
                scope="auxiliary", task="invented_slot", provider="local", model="anything",
                profile="engineering", confirm_expensive_model=True,
            )))
        else:
            with scope("engineering"):
                ws._apply_model_assignment_sync("auxiliary", "local", "anything", "invented_slot", "")
    assert error.value.status_code == 400
    assert configs == before


def test_plugin_cannot_shadow_builtin_slot_or_duplicate_entries(dashboard):
    ws, _, _, managers = dashboard
    # Even corrupt registration metadata cannot alter a built-in picker row.
    managers["engineering"]._aux_tasks["vision"] = {
        "key": "vision", "plugin": "bad", "display_name": "Do not use", "description": "bad",
    }
    result = ws.get_auxiliary_models(profile="engineering")
    rows = [entry for entry in result["tasks"] if entry["task"] == "vision"]
    assert len(rows) == 1
    assert "plugin" not in rows[0]
