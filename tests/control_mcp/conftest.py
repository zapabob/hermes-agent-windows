"""Test-only module loader: a missing feature is a behavioural RED, not collection error."""
import importlib

import pytest


@pytest.fixture
def control_module():
    def load(name):
        try:
            return importlib.import_module(f"downstream.control_mcp.{name}")
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.startswith("downstream.control_mcp"):
                pytest.fail(f"Control MCP {name} is not implemented", pytrace=False)
            raise
    return load


@pytest.fixture
def control_context(control_module):
    def make(**changes):
        values = dict(subject="human-1", client_registration="codex", issuer="https://issuer.invalid",
                      resource="https://hermes.invalid/control/mcp", grant_revision=1,
                      expires_at=200, scopes=("hermes:read",), profiles=("p1",),
                      workspaces=(("p1", "w1"),))
        values.update(changes)
        return control_module("contracts").ControlContext(**values)
    return make
