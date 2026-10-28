"""T04 advanced delegation — fail-closed backends, sibling independence, metadata."""

from __future__ import annotations

from typing import Any, Mapping
from unittest.mock import MagicMock

import pytest

from agent.delegation_provider import DelegationProvider, DelegationRouteError
from agent.delegation_registry import (
    configured_backend,
    get_active_provider,
    register_provider,
)
from tools.delegate_tool_routes import resolve_task_routes, schema_extension


class _Options(DelegationProvider):
    @property
    def name(self) -> str:
        return "probe-options"

    @property
    def display_name(self) -> str:
        return "Probe options"

    @property
    def summary(self) -> str:
        return "Test model_map-shaped backend."

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            "option": {
                "type": "string",
                "enum": ["fast", "deep"],
                "description": "Named option.",
            }
        }

    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        option = task.get("option") or "fast"
        if option == "deep":
            return {
                "provider": "openrouter",
                "model": "deep-model",
                "label": "deep",
                "reasoning_effort": "high",
            }
        if option == "fast":
            return {
                "provider": "openrouter",
                "model": "fast-model",
                "label": "fast",
            }
        raise DelegationRouteError(f"unknown option {option!r}")


class _Profiles(DelegationProvider):
    @property
    def name(self) -> str:
        return "probe-profiles"

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {"profile": {"type": "string", "enum": ["coder"]}}

    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        profile = task.get("profile")
        if profile is None or (isinstance(profile, str) and not profile.strip()):
            return {
                k: v
                for k, v in config.items()
                if k
                in {
                    "model",
                    "provider",
                    "base_url",
                    "api_key",
                    "api_mode",
                    "request_overrides",
                    "reasoning_effort",
                    "fallback_providers",
                }
            }
        if profile != "coder":
            raise DelegationRouteError(f"unauthorized profile {profile!r}")
        return {"profile": "coder", "label": "coder"}


@pytest.fixture
def recorded(monkeypatch):
    """Stub credential resolution to avoid live provider calls."""
    calls: list[dict[str, Any]] = []

    def fake_resolve(cfg, parent):
        calls.append(dict(cfg) if isinstance(cfg, Mapping) else {})
        return {
            "model": cfg.get("model"),
            "provider": cfg.get("provider"),
            "base_url": cfg.get("base_url"),
            "api_key": "secret-should-not-leak",
            "api_mode": cfg.get("api_mode"),
            "request_overrides": cfg.get("request_overrides"),
            "max_output_tokens": None,
            "command": None,
            "args": None,
        }

    monkeypatch.setattr(
        "tools.delegate_tool._resolve_delegation_credentials",
        fake_resolve,
    )
    return calls


def test_configured_backend_defaults_to_default():
    assert configured_backend({}) == "default"
    assert configured_backend({"backend": "Model_Map"}) == "model_map"


def test_missing_backend_fails_closed(recorded):
    parent = MagicMock()
    parent._delegation_backend = ""
    with pytest.raises(DelegationRouteError) as exc:
        resolve_task_routes(
            [{"goal": "do thing"}],
            {"backend": "not-installed-backend"},
            parent,
        )
    assert "not-installed-backend" in str(exc.value)
    assert "No subagent was started" in str(exc.value)


def test_selected_plugin_backend_extends_schema_and_routes(recorded, monkeypatch):
    register_provider(_Options())
    config = {"backend": "probe-options"}
    params, addendum = schema_extension(config)
    assert "option" in params
    assert params["option"]["enum"] == ["fast", "deep"]

    parent = MagicMock()
    parent._delegation_backend = "probe-options"
    routes = resolve_task_routes(
        [
            {"goal": "a", "option": "fast"},
            {"goal": "b", "option": "deep"},
        ],
        config,
        parent,
    )
    assert [r.model for r in routes] == ["fast-model", "deep-model"]
    assert routes[0].public_metadata()["backend"] == "probe-options"
    assert "api_key" not in routes[0].public_metadata()
    assert routes[1].reasoning_effort == "high"


def test_unroutable_task_refused_alone_siblings_run(recorded, monkeypatch):
    register_provider(_Options())
    parent = MagicMock()
    parent._delegation_backend = "probe-options"
    routes = resolve_task_routes(
        [
            {"goal": "ok", "option": "fast"},
            {"goal": "bad", "option": "nope"},
            {"goal": "also-ok", "option": "deep"},
        ],
        {"backend": "probe-options"},
        parent,
    )
    assert routes[0].refused is False
    assert routes[1].refused is True
    assert "nope" in (routes[1].error or "")
    assert routes[2].refused is False
    assert routes[2].model == "deep-model"


def test_backend_route_inherits_delegation_fallback_providers(recorded):
    register_provider(_Options())
    parent = MagicMock()
    parent._delegation_backend = "probe-options"
    chain = [{"provider": "openrouter", "model": "fallback/model"}]
    routes = resolve_task_routes(
        [{"goal": "a", "option": "fast"}],
        {"backend": "probe-options", "fallback_providers": chain},
        parent,
    )
    assert routes[0].fallback_providers == chain


def test_explicit_empty_fallback_is_preserved(recorded):
    """``fallback_providers: []`` must stay empty (disabled), never ignored."""
    register_provider(_Options())
    parent = MagicMock()
    parent._delegation_backend = "probe-options"
    routes = resolve_task_routes(
        [{"goal": "a", "option": "fast"}],
        {"backend": "probe-options", "fallback_providers": []},
        parent,
    )
    assert routes[0].fallback_providers == []


def test_session_switch_refuses_previous_backend_parameter(recorded, monkeypatch):
    register_provider(_Options())
    register_provider(_Profiles())
    monkeypatch.setattr(
        "tools.delegate_tool_routes._profile_home",
        lambda name: __import__("pathlib").Path(f"/tmp/profiles/{name}"),
    )
    monkeypatch.setattr(
        "tools.delegate_tool_routes._profile_route",
        lambda home, backend, label: __import__(
            "tools.delegate_tool_routes", fromlist=["TaskRoute"]
        ).TaskRoute(
            backend=backend,
            model="coder-model",
            provider="openrouter",
            label=label,
            profile=str(home).rsplit("/", 1)[-1],
            profile_home=home,
        ),
    )
    parent = MagicMock()
    # Session tools were built for probe-options; pinned backend is profiles.
    parent._delegation_backend = "probe-profiles"
    routes = resolve_task_routes(
        [
            {"goal": "plain"},
            {"goal": "legacy", "option": "fast"},
            {"goal": "ok", "profile": "coder"},
        ],
        {"backend": "probe-profiles"},
        parent,
    )
    assert routes[0].refused is False
    assert routes[1].refused is True
    assert "option" in (routes[1].error or "")
    assert "probe-profiles" in (routes[1].error or "")
    assert routes[2].refused is False
    assert routes[2].model == "coder-model"


def test_default_bundled_strategy_routes_without_plugin_sweep(recorded, monkeypatch):
    parent = MagicMock()
    parent._delegation_backend = ""
    provider = get_active_provider({})
    assert provider.name == "default"
    routes = resolve_task_routes(
        [{"goal": "inherit"}],
        {"model": "child-model", "provider": "openrouter"},
        parent,
    )
    assert len(routes) == 1
    assert routes[0].refused is False
    assert routes[0].model == "child-model"
    assert routes[0].backend == "default"


def test_public_metadata_omits_secrets(recorded):
    register_provider(_Options())
    parent = MagicMock()
    parent._delegation_backend = "probe-options"
    routes = resolve_task_routes(
        [{"goal": "a", "option": "fast"}],
        {"backend": "probe-options"},
        parent,
    )
    meta = routes[0].public_metadata()
    assert "api_key" not in meta
    assert "secret" not in str(meta).lower()
    assert meta["provider"] == "openrouter"
    assert meta["model"] == "fast-model"
