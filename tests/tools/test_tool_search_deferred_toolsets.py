"""Deferred tool loading: an operator opt-in that moves a FIRST-PARTY
toolset's schemas behind the tool_search bridge without removing the tools.

Contract under test:

* ``tools.tool_search.deferred_toolsets`` names toolsets whose tool schemas
  defer even when the tools are first-party (in ``_HERMES_CORE_TOOLS``).
  The tools keep working — they stay registered, enabled, discoverable via
  tool_search / tool_describe, and callable via tool_call.
* ``tools.tool_search.deferred_exceptions`` keeps individual tools direct
  (the safety valve for a capability an automation loop drives).
* The bridge's SCOPING gate must know about the opt-in, otherwise opting a
  toolset in would silently make its tools unreachable through tool_call.
* The default (no opt-in) must be byte-for-byte the previous behaviour: no
  first-party tool defers.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tools import tool_search
from tools.tool_search import (
    BRIDGE_TOOL_NAMES,
    ToolSearchConfig,
    assemble_tool_defs,
    classify_tools,
    is_deferrable_tool_name,
    scoped_deferrable_names,
)


def _schema(name: str, description: str = "Does a thing.") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


@pytest.fixture
def first_party_tool(monkeypatch):
    """Register a tool that lives in a first-party (core-list) toolset."""
    from tools.registry import registry
    from toolsets import _HERMES_CORE_TOOLS

    name = "hakua_first_party_probe"
    toolset = "hakua_probe"
    monkeypatch.setattr(tool_search, "_core_tool_names", lambda: frozenset(_HERMES_CORE_TOOLS) | {name})
    entry = registry.get_entry(name)
    if entry is None:
        registry.register(
            name=name,
            toolset=toolset,
            schema=_schema(name),
            handler=lambda args, **kw: {"ok": True},
            check_fn=None,
            requires_env=(),
        )
    yield name, toolset
    try:
        registry.deregister(name)
    except Exception:
        pass


class TestDeferredToolsetOptIn:
    def test_first_party_tool_does_not_defer_by_default(self, first_party_tool):
        name, _toolset = first_party_tool
        assert is_deferrable_tool_name(name) is False
        visible, deferrable = classify_tools([_schema(name)])
        assert [td["function"]["name"] for td in visible] == [name]
        assert deferrable == []

    def test_opted_in_toolset_defers(self, first_party_tool):
        name, toolset = first_party_tool
        assert is_deferrable_tool_name(
            name, deferred_toolsets=[toolset]
        ) is True
        visible, deferrable = classify_tools(
            [_schema(name)], deferred_toolsets=[toolset]
        )
        assert visible == []
        assert [td["function"]["name"] for td in deferrable] == [name]

    def test_exception_keeps_a_tool_direct(self, first_party_tool):
        name, toolset = first_party_tool
        assert is_deferrable_tool_name(
            name,
            deferred_toolsets=[toolset],
            deferred_exceptions=[name],
        ) is False

    def test_exception_matching_is_case_and_space_insensitive(self, first_party_tool):
        name, toolset = first_party_tool
        assert is_deferrable_tool_name(
            name,
            deferred_toolsets=[f"  {toolset.upper()}  "],
            deferred_exceptions=[f" {name.upper()} "],
        ) is False

    def test_bridge_tools_are_never_deferrable(self, first_party_tool):
        for bridge in BRIDGE_TOOL_NAMES:
            assert is_deferrable_tool_name(
                bridge, deferred_toolsets=["hakua_probe"]
            ) is False

    def test_unknown_tool_is_not_deferrable(self):
        assert is_deferrable_tool_name(
            "definitely_not_registered_xyz", deferred_toolsets=["hakua_probe"]
        ) is False


class TestConfigParsing:
    def test_defaults_are_empty(self):
        cfg = ToolSearchConfig.from_raw({})
        assert cfg.deferred_toolsets == ()
        assert cfg.deferred_exceptions == ()

    def test_list_and_single_string_both_parse(self):
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": ["vrchat", "tts"]})
        assert cfg.deferred_toolsets == ("vrchat", "tts")
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": "vrchat"})
        assert cfg.deferred_toolsets == ("vrchat",)

    def test_malformed_values_degrade_to_empty(self):
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": 42})
        assert cfg.deferred_toolsets == ()
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": ["vrchat", "", None]})
        assert cfg.deferred_toolsets == ("vrchat",)


class TestAssemblyAndScoping:
    def test_assembly_defers_the_opted_in_toolset(self, first_party_tool):
        name, toolset = first_party_tool
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": [toolset]})
        result = assemble_tool_defs([_schema(name)], config=cfg)
        assert result.activated is True
        names = {td["function"]["name"] for td in result.tool_defs}
        assert name not in names
        assert BRIDGE_TOOL_NAMES.issubset(names)

    def test_scoped_deferrable_names_includes_the_opted_in_tool(self, first_party_tool):
        """The bridge scoping gate must know the opt-in.

        Without this the tool would be deferred out of the model-facing array
        and then REFUSED by tool_call — the opt-in would break the very
        capability it was meant to make cheap.
        """
        name, toolset = first_party_tool
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": [toolset]})
        assert name in scoped_deferrable_names([_schema(name)], config=cfg)

    def test_resolve_underlying_call_accepts_the_opted_in_tool(self, first_party_tool):
        name, toolset = first_party_tool
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": [toolset]})
        resolved, args, err = tool_search.resolve_underlying_call(
            {"name": name, "arguments": {}}, config=cfg
        )
        assert err is None
        assert resolved == name
        assert args == {}

    def test_resolve_underlying_call_rejects_a_non_deferred_tool(self, first_party_tool):
        name, _toolset = first_party_tool
        cfg = ToolSearchConfig.from_raw({})
        resolved, _args, err = tool_search.resolve_underlying_call(
            {"name": name, "arguments": {}}, config=cfg
        )
        assert resolved is None
        assert err and "not a deferrable tool" in err

    def test_describe_classification_follows_the_opt_in(self, first_party_tool):
        name, toolset = first_party_tool
        assert (
            tool_search._describe_classification(name, deferred_toolsets=[toolset])
            == "available"
        )
        assert (
            tool_search._describe_classification(name) == "not_deferrable"
        )

    def test_dispatch_tool_describe_serves_the_opted_in_tool(self, first_party_tool):
        """The bridge must be able to DESCRIBE an opted-in tool."""
        name, toolset = first_party_tool
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": [toolset]})
        payload = json.loads(
            tool_search.dispatch_tool_describe(
                {"names": [name]},
                current_tool_defs=[_schema(name)],
                config=cfg,
            )
        )
        assert name in payload["tools"]
        assert "errors" not in payload

    def test_dispatch_tool_search_finds_the_opted_in_tool(self, first_party_tool):
        name, toolset = first_party_tool
        cfg = ToolSearchConfig.from_raw({"deferred_toolsets": [toolset]})
        payload = json.loads(
            tool_search.dispatch_tool_search(
                {"queries": [name]},
                current_tool_defs=[_schema(name)],
                config=cfg,
            )
        )
        assert name in payload["tools"]
