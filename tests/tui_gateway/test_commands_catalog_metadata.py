"""Additive registry metadata through the actual short JSON-RPC dispatch."""
import importlib
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.commands import CommandDef


@pytest.fixture()
def server(monkeypatch):
    with patch.dict("sys.modules", {
        "hermes_cli.env_loader": MagicMock(), "hermes_cli.banner": MagicMock(),
    }):
        mod = importlib.import_module("tui_gateway.server")
    monkeypatch.setattr(mod, "_load_cfg", lambda: {})
    monkeypatch.setattr(mod, "_skill_usage_lookup", lambda: (lambda name: 0, lambda name: "local"))
    monkeypatch.setattr("agent.skill_commands.scan_skill_commands", lambda: {})
    return mod


def test_catalog_dispatch_preserves_legacy_fields_and_includes_hidden_alias_metadata(server, monkeypatch):
    monkeypatch.setattr("hermes_cli.commands.COMMAND_REGISTRY", [
        CommandDef("draft-note", "Write a note", "Session", aliases=("dn",), args_hint="<prompt>"),
        CommandDef("approve", "Approve", "Session", args_hint="[id]", gateway_only=True),
    ])
    result = server.dispatch({"jsonrpc": "2.0", "id": 701, "method": "commands.catalog", "params": {}})
    payload = result["result"]
    assert {"pairs", "sub", "canon", "categories", "skills", "skill_count", "warning"} <= payload.keys()
    assert payload["commands"]["/draft-note"] == {"argument_mode": "text"}
    assert payload["commands"]["/dn"] == {"argument_mode": "text"}
    assert payload["commands"]["/approve"] == {"argument_mode": "text"}
    assert not any(pair[0] == "/approve" for pair in payload["pairs"])
    assert payload["canon"]["/dn"] == "/draft-note"


@pytest.mark.parametrize("kwargs, expected", [
    ({}, None), ({"args_hint": "<name>"}, "text"),
    ({"subcommands": ("on", "off")}, "options"),
    ({"subcommands": ("start", "status"), "args_hint": "<prompt>"}, "mixed"),
    ({"args_hint": "<prompt>", "argument_mode": "options"}, "options"),
    ({"argument_mode": "invalid", "args_hint": "<name>"}, "text"),
])
def test_registry_argument_contract(kwargs, expected):
    from hermes_cli.commands import infer_argument_mode
    assert infer_argument_mode(CommandDef("fixture", "Fixture", "Session", **kwargs)) == expected
