"""Every reader of ``mcp_servers.<name>.enabled`` gives one answer per value.

The MCP client, the toolset resolver, the catalog, the picker and the list/status
surfaces used to parse the key several different ways, so ``enabled: 0`` was off
for the resolver and on for the client, and ``enabled: "false"`` was on in the
server list. The case table is shared with the desktop
(``apps/desktop/src/lib/mcp-enabled-cases.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "apps/desktop/src/lib/mcp-enabled-cases.json").read_text(
        encoding="utf-8"
    )
)


def _readers(monkeypatch):
    import hermes_cli.config as hermes_config
    import hermes_cli.mcp_catalog as mcp_catalog
    from agent.coding_context import _enabled_mcp_servers
    from hermes_cli.tools_config import enabled_mcp_server_names
    from hermes_cli.web_server import _mcp_server_summary
    from tools.mcp_tool import mcp_server_enabled
    from tui_gateway.mcp_rpc_helpers import summarize_server

    def catalog(cfg):
        monkeypatch.setattr(mcp_catalog, "installed_servers", lambda: {"s": cfg})
        return mcp_catalog.is_enabled("s")

    def coding_posture(cfg):
        monkeypatch.setattr(hermes_config, "read_raw_config", lambda: {"mcp_servers": {"s": cfg}})
        return "s" in _enabled_mcp_servers(None)

    return {
        "mcp client": mcp_server_enabled,
        "toolset resolver": lambda cfg: "s" in enabled_mcp_server_names({"mcp_servers": {"s": cfg}}),
        "catalog": catalog,
        "coding posture": coding_posture,
        "tui server list": lambda cfg: summarize_server("s", cfg)["enabled"],
        "dashboard server list": lambda cfg: _mcp_server_summary("s", cfg)["enabled"],
    }


@pytest.mark.parametrize("case", CASES, ids=lambda c: repr(c.get("enabled", "<absent>")))
def test_every_reader_agrees_with_the_shared_table(case, monkeypatch):
    entry = {k: v for k, v in case.items() if k != "on"}
    answers = {
        name: bool(read({"command": "x", **entry})) for name, read in _readers(monkeypatch).items()
    }

    assert answers == dict.fromkeys(answers, case["on"])
