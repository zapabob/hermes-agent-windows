"""Hermes plugin: Cursor subscription bridge (loopback OpenAI shim + MCP drain)."""

from __future__ import annotations

from .cli import cursor_sub_command, register_cli


def register(ctx) -> None:
    """Register ``hermes cursor-sub {serve,mcp,status,doctor}``."""
    ctx.register_cli_command(
        name="cursor-sub",
        help="Loopback OpenAI shim + MCP drain for Cursor subscription models",
        setup_fn=register_cli,
        handler_fn=cursor_sub_command,
        description=(
            "Serve http://127.0.0.1:48771/v1 for Hermes model.provider=cursor-sub, "
            "and expose MCP tools cursor_sub_poll / cursor_sub_respond so a Cursor "
            "Agent session can answer with the subscription model. Interactive only — "
            "not for gateway/cron."
        ),
    )
