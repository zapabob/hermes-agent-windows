"""Removing field allow-listing or copy isolation must break these tests."""
from copy import deepcopy
import json

import pytest


def test_projection_neither_leaks_nor_mutates_config(control_module):
    config = {"auxiliary": {"engineering_worker": {
        "provider": "fixture", "model": "worker", "reasoning_effort": "medium",
        "api_key": "synthetic-provider-secret", "base_url": "https://private.invalid/token-in-path",
        "headers": {"Authorization": "synthetic"},
    }}}
    original = deepcopy(config)
    routes = control_module("projection").project_routes(config)
    assert routes == [{"slot": "engineering_worker", "provider": "fixture", "model": "worker", "configured_effort": "medium"}]
    routes[0]["model"] = "changed-in-response"
    assert config == original


def test_nested_reasoning_keeps_configured_not_observed_effort(control_module):
    cfg = {"auxiliary": {"engineering_reviewer": {"provider": "fixture", "model": "judge", "reasoning": {"enabled": True, "effort": "high"}}}}
    row = control_module("projection").project_routes(cfg)[0]
    assert row["configured_effort"] == "high"
    assert "request_effort" not in row
    assert "provider_effort" not in row


@pytest.mark.parametrize("aux", [None, [], True, "bad"])
def test_invalid_config_is_not_an_empty_success(control_module, aux):
    contracts = control_module("contracts")
    with pytest.raises(contracts.ControlError) as error:
        control_module("projection").project_routes({"auxiliary": aux})
    assert error.value.code == "invalid_snapshot"


def test_unregistered_slots_are_not_exported(control_module):
    cfg = {"auxiliary": {"engineering_worker": {"provider": "p", "model": "m"}, "vision": {"api_key": "secret"}, "engineering_fake": {"model": "secret"}}}
    rows = control_module("projection").project_routes(cfg)
    assert len(rows) == 1
    assert rows[0]["configured_effort"] is None
    assert "secret" not in json.dumps(rows)


def test_disabled_reasoning_not_falsely_reported_high(control_module):
    cfg = {"auxiliary": {"engineering_planner": {"provider": "p", "model": "m", "reasoning": {"enabled": False, "effort": "high"}}}}
    assert control_module("projection").project_routes(cfg)[0]["configured_effort"] is None


@pytest.mark.parametrize("field,value", [("provider", "https://private.invalid/token"), ("model", "bad\nvalue"), ("model", {"api_key": "secret"})])
def test_invalid_identity_is_rejected_without_echo(control_module, field, value):
    row = {"provider": "p", "model": "m", field: value}
    contracts = control_module("contracts")
    with pytest.raises(contracts.ControlError) as error:
        control_module("projection").project_routes({"auxiliary": {"engineering_worker": row}})
    assert str(error.value) == "invalid_snapshot"
