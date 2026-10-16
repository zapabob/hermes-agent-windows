"""Public catalog metadata narrows Desktop without changing CLI authority."""
from dataclasses import fields, replace

import pytest

from hermes_cli.commands import COMMAND_REGISTRY, CommandDef, command_desktop_meta
from test_metadata import rpc, server


def with_scope(command, scope):
    if "desktop_subcommands" in {field.name for field in fields(CommandDef)}:
        return replace(command, desktop_subcommands=scope)
    return command


def test_actual_skills_registry_exposes_only_the_review_slice(server):
    command = next(cmd for cmd in COMMAND_REGISTRY if cmd.name == "skills")
    expected = ["pending", "approve", "reject", "diff", "approval"]
    assert command_desktop_meta(command).get("desktop_subcommands") == expected
    catalog = rpc(server, "commands.catalog")["result"]
    assert catalog["commands"]["/skills"].get("desktop_subcommands") == expected
    assert command.cli_only and command.gateway_config_gate == "skills.write_approval"
    assert "install" in command.subcommands


@pytest.mark.parametrize("scope", [("pending", "diff"), ()])
def test_public_catalog_preserves_explicit_scope_and_aliases(server, monkeypatch, scope):
    command = with_scope(CommandDef("f04-review", "Review", "Session", aliases=("f04-review-alias",)), scope)
    monkeypatch.setattr("hermes_cli.commands.COMMAND_REGISTRY", [command])
    catalog = rpc(server, "commands.catalog")["result"]
    for name in ("/f04-review", "/f04-review-alias"):
        assert catalog["commands"][name].get("desktop_subcommands") == list(scope)
    assert catalog["canon"]["/f04-review-alias"] == "/f04-review"


def test_undeclared_scope_keeps_the_legacy_envelope():
    assert command_desktop_meta(CommandDef("fixture", "Fixture", "Session")) == {
        "argument_mode": None, "desktop": None}
