"""MCP tools/call progress normalization and per-call callback factory.

SDK contract (locked via installed ``mcp`` package):
``ProgressFnT`` is ``async (progress: float, total: float | None, message: str | None)``.

Detection of ``progress_callback`` support happens *before* the call so a
TypeError after a side-effecting tool start never triggers a silent retry.
"""

from __future__ import annotations

import inspect
import logging
import math
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

_MESSAGE_MAX_CHARS = 500
_supports_progress: Optional[bool] = None

ProgressEmitter = Callable[..., bool]


def mcp_call_tool_supports_progress(call_tool: Any = None) -> bool:
    """Return whether ``ClientSession.call_tool`` accepts ``progress_callback``."""
    global _supports_progress
    if call_tool is None and _supports_progress is not None:
        return _supports_progress
    target = call_tool
    if target is None:
        try:
            from mcp.client.session import ClientSession

            target = ClientSession.call_tool
        except Exception:
            _supports_progress = False
            return False
    try:
        params = inspect.signature(target).parameters
        supported = "progress_callback" in params
    except (TypeError, ValueError):
        supported = False
    if call_tool is None:
        _supports_progress = supported
    return supported


def normalize_mcp_progress(
    progress: Any,
    total: Any,
    message: Any,
) -> Optional[tuple[float, Optional[float], Optional[str]]]:
    """Validate SDK progress fields. Invalid values return None (drop frame)."""
    try:
        prog = float(progress)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(prog) or prog < 0:
        return None

    norm_total: Optional[float]
    if total is None:
        norm_total = None
    else:
        try:
            tot = float(total)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(tot) or tot <= 0:
            return None
        norm_total = tot

    if message is None:
        norm_message: Optional[str] = None
    else:
        text = str(message)
        if len(text) > _MESSAGE_MAX_CHARS:
            text = text[:_MESSAGE_MAX_CHARS]
        norm_message = text

    return prog, norm_total, norm_message


def build_mcp_progress_callback(
    *,
    tool_call_id: str,
    tool_name: str,
    generation: int,
    emit: ProgressEmitter,
    closed_flag: dict[str, bool],
) -> Callable[[float, Optional[float], Optional[str]], Awaitable[None]]:
    """Build a per-call SDK progress callback closed over call identity."""

    async def _on_progress(
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        if closed_flag.get("closed"):
            return
        normalized = normalize_mcp_progress(progress, total, message)
        if normalized is None:
            return
        prog, tot, msg = normalized
        try:
            emit(
                progress=prog,
                total=tot,
                message=msg,
                closed=bool(closed_flag.get("closed")),
                expected_call_id=tool_call_id,
                expected_name=tool_name,
                expected_generation=generation,
            )
        except Exception:
            logger.debug("MCP progress emit failed for %s", tool_name, exc_info=True)

    return _on_progress


def close_mcp_progress(closed_flag: dict[str, bool]) -> None:
    """Mark the call closed so late notifications cannot reopen UI rows."""
    closed_flag["closed"] = True
