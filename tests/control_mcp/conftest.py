"""Test-only module loader: a missing feature is a behavioural RED, not collection error."""
import importlib
import itertools
import os

import pytest
import yaml

from hermes_constants import get_hermes_home

ENGINEERING_ROLES = ("planner", "worker", "reviewer")
_TICKS = itertools.count(1)


def engineering_config(*, model="model-a", roles=ENGINEERING_ROLES, settings=None):
    """A profile config with the native engineering picker slots selected."""
    config = {"auxiliary": {f"engineering_{role}": {"provider": "provider-a", "model": model}
                            for role in roles}}
    if settings is not None:
        config["plugins"] = {"entries": {"implementation_router": {"settings": settings}}}
    return config


@pytest.fixture
def host_config():
    """Write the isolated profile's config.yaml, as an operator edit would."""
    def write(config):
        path = get_hermes_home() / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
        # The config cache keys on (mtime_ns, size); a same-tick rewrite must still be seen.
        stamp = path.stat().st_mtime_ns + next(_TICKS) * 1_000_000_000
        os.utime(path, ns=(stamp, stamp))
        return path
    return write


@pytest.fixture(autouse=True)
def _engineering_routes_selected(host_config):
    host_config(engineering_config())


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
