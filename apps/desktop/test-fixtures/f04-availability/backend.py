"""Test-owned static catalog through public server.dispatch; no agent startup."""
import importlib
import json
import queue
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(root))
with patch.dict("sys.modules", {"hermes_cli.env_loader": MagicMock(), "hermes_cli.banner": MagicMock()}):
    server = importlib.import_module("tui_gateway.server")
from hermes_cli.commands import CommandDef, COMMAND_REGISTRY
from dataclasses import fields, replace

fixtures = [
    CommandDef("fixture-text", "Text", "Session", args_hint="<prompt>"),
    CommandDef("fixture-options", "Options", "Session", subcommands=("on", "off")),
    CommandDef("fixture-mixed", "Mixed", "Session", subcommands=("start", "status"), args_hint="<prompt>"),
    CommandDef("fixture-null", "No arguments", "Session"),
]
availability = [CommandDef('f04-'+value, value, 'Session', args_hint='<prompt>')
                for value in ('hidden', 'terminal', 'messaging', 'advanced')]
if 'desktop' in {field.name for field in fields(CommandDef)}:
    availability = [replace(cmd, desktop=cmd.name.removeprefix('f04-')) for cmd in availability]
fixtures.extend(availability)
responses = queue.Queue()


class CaptureTransport:
    def write(self, response):
        responses.put(response)


with patch("hermes_cli.commands.COMMAND_REGISTRY", [*COMMAND_REGISTRY, *fixtures]), \
     patch.object(server, "_load_cfg", return_value={}), \
     patch.object(server, "_skill_usage_lookup", return_value=(lambda name: 0, lambda name: "local")), \
     patch("agent.skill_commands.scan_skill_commands", return_value={}), \
     patch("hermes_cli.plugins.get_plugin_commands", return_value={}):
    envelope = server.dispatch({"jsonrpc": "2.0", "id": 704, "method": "commands.catalog", "params": {}})
    completion = server.dispatch({"jsonrpc": "2.0", "id": 705, "method": "complete.slash", "params": {"text": "/roll"}}, CaptureTransport())
    if completion is None:
        completion = responses.get(timeout=30)
assert "result" in envelope, envelope
assert "result" in completion, completion
Path(sys.argv[1]).write_text(json.dumps({"catalog": envelope, "completion": completion}, ensure_ascii=False)+"\n", encoding="utf-8")
