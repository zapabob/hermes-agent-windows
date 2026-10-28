"""Per-call sink for mid-tool progress (MCP notifications → UI bridge).

ContextVar-scoped so concurrent tool workers keep call identity without a
process-global pending-call owner. Set by the tool executor around dispatch;
read by MCP (or other) handlers that receive SDK progress callbacks.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ProgressCallback = Callable[..., Any]


@dataclass(frozen=True)
class ToolProgressSink:
    """Bound identity for one in-flight tool call's progress events."""

    tool_call_id: str
    tool_name: str
    callback: Optional[ProgressCallback]
    generation: int = 0


_sink: contextvars.ContextVar[Optional[ToolProgressSink]] = contextvars.ContextVar(
    "hermes_tool_progress_sink",
    default=None,
)
_generation = 0


def install_tool_progress_sink(
    *,
    tool_call_id: str,
    tool_name: str,
    callback: Optional[ProgressCallback],
) -> contextvars.Token:
    """Install the active sink for this worker; return a reset token."""
    global _generation
    _generation += 1
    sink = ToolProgressSink(
        tool_call_id=str(tool_call_id or ""),
        tool_name=str(tool_name or ""),
        callback=callback,
        generation=_generation,
    )
    return _sink.set(sink)


def reset_tool_progress_sink(token: contextvars.Token) -> None:
    """Restore the previous sink (or clear)."""
    try:
        _sink.reset(token)
    except Exception:
        logger.debug("tool progress sink reset failed", exc_info=True)


def get_tool_progress_sink() -> Optional[ToolProgressSink]:
    """Return the sink installed for the current context, if any."""
    return _sink.get()


def emit_tool_progress(
    *,
    progress: float,
    total: Optional[float],
    message: Optional[str],
    closed: bool,
    expected_call_id: str,
    expected_name: str,
    expected_generation: int,
) -> bool:
    """Forward a normalized mid-call progress event to the active sink.

    Returns True when an event was delivered. Closed calls, call-id mismatches,
    and missing callbacks are silent no-ops (never reopen a finished row).
    """
    if closed:
        return False
    sink = _sink.get()
    if sink is None or sink.callback is None:
        return False
    if expected_generation and sink.generation != expected_generation:
        return False
    if expected_call_id and sink.tool_call_id and sink.tool_call_id != expected_call_id:
        return False
    if expected_name and sink.tool_name and sink.tool_name != expected_name:
        return False
    preview = message if isinstance(message, str) else None
    try:
        sink.callback(
            "tool.progress",
            sink.tool_name or expected_name,
            preview,
            None,
            tool_call_id=sink.tool_call_id or expected_call_id,
            progress=progress,
            total=total,
        )
        return True
    except Exception:
        logger.debug("tool.progress sink callback failed", exc_info=True)
        return False
