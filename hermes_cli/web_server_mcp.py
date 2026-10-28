"""MCP create-request normalisation shared by Profile Builder and the MCP page.

The implementation lives on ``hermes_cli.web_server`` (historical location).
This module exists so extracted helpers (``web_server_profiles``) can import a
stable name without a circular import at module load.
"""

from __future__ import annotations

from typing import Any, Optional


def _normalize_mcp_server_create(body: Any) -> tuple[str, dict[str, Any], Optional[str]]:
    from hermes_cli.web_server import _normalize_mcp_server_create as impl

    return impl(body)
