"""Cursor subscription bridge provider (loopback OpenAI shim).

Requires ``hermes cursor-sub serve`` plus a Cursor Agent session draining
the MCP queue (``hermes cursor-sub mcp`` / Cursor mcp.json). Interactive
only — not a gateway/cron default.
"""

from __future__ import annotations

import logging
import os

from providers import register_provider
from providers.base import ProviderProfile

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:48771/v1"
_FALLBACK_MODELS = ("cursor-sub/default",)


def _resolve_base_url(base_url: str | None = None) -> str:
    for candidate in (
        (base_url or "").strip(),
        os.environ.get("CURSOR_SUB_BRIDGE_BASE_URL", "").strip(),
    ):
        if candidate:
            return candidate.rstrip("/")
    return _DEFAULT_BASE_URL


class CursorSubProfile(ProviderProfile):
    """OpenAI-compatible profile pointing at the local cursor-sub shim."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        resolved = _resolve_base_url(base_url)
        try:
            result = super().fetch_models(
                api_key=api_key,
                base_url=resolved,
                timeout=timeout,
            )
            if result:
                return list(result)
        except Exception as exc:  # noqa: BLE001 — catalog soft-fail
            logger.debug("fetch_models(cursor-sub): %s", exc)
        return list(_FALLBACK_MODELS)


cursor_sub = CursorSubProfile(
    name="cursor-sub",
    aliases=("cursor_sub", "cursor-subscription", "cursor-sub-bridge"),
    display_name="Cursor Subscription Bridge",
    description="Local shim that drains Cursor Agent MCP poll/respond (interactive)",
    signup_url="https://cursor.com",
    env_vars=("CURSOR_SUB_BRIDGE_API_KEY", "CURSOR_SUB_BRIDGE_BASE_URL"),
    base_url=_DEFAULT_BASE_URL,
    hostname="127.0.0.1",
    auth_type="api_key",
    default_aux_model="cursor-sub/default",
    fallback_models=_FALLBACK_MODELS,
)

register_provider(cursor_sub)
