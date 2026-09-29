from __future__ import annotations

from .cli import hermes_gpt_command, register_cli


def register(ctx) -> None:
    ctx.register_cli_command(
        name="hermes-gpt",
        help="Run the Hermes GPT local MCP sidecar",
        setup_fn=register_cli,
        handler_fn=hermes_gpt_command,
        description=(
            "Expose selected Hermes Agent capabilities through a local MCP "
            "sidecar; remote Streamable HTTP requires OAuth 2.1/PKCE and HTTPS, "
            "while write, memory-write, terminal, and session-search remain gated."
        ),
    )
