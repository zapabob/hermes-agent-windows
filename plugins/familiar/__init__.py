"""Hermes plugin for explicitly launching the vendored Familiar body."""

from __future__ import annotations

import logging
from typing import Any

from . import core

logger = logging.getLogger(__name__)


def _on_pre_llm_call(
    *,
    user_message: object = "",
    platform: str = "",
    **_: Any,
) -> None:
    """Inspect the trusted current user turn before any model invocation."""
    result = core.request_launch(
        raw_text=user_message,
        source="user",
        platform=platform,
    )
    if result.get("status") != "ignored":
        logger.info("Familiar explicit launch result: %s", result.get("status"))


def register(ctx) -> None:
    """Register only a trusted raw-turn hook; expose no model-callable tool."""
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
