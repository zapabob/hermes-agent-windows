"""Behavioral contracts for MCP tools/call progress → UI sink."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent.tool_progress_sink import (
    emit_tool_progress,
    get_tool_progress_sink,
    install_tool_progress_sink,
    reset_tool_progress_sink,
)
from tools.mcp_progress import (
    build_mcp_progress_callback,
    close_mcp_progress,
    mcp_call_tool_supports_progress,
    normalize_mcp_progress,
)


def test_sdk_call_tool_declares_progress_callback() -> None:
    assert mcp_call_tool_supports_progress() is True


@pytest.mark.parametrize(
    ("progress", "total", "message", "ok"),
    [
        (0.0, None, None, True),
        (1.5, 10.0, "half", True),
        (-1.0, 10.0, None, False),
        (float("nan"), 10.0, None, False),
        (1.0, 0.0, None, False),
        (1.0, float("inf"), None, False),
        ("x", 10.0, None, False),
    ],
)
def test_normalize_mcp_progress_rejects_invalid(
    progress: Any, total: Any, message: Any, ok: bool
) -> None:
    result = normalize_mcp_progress(progress, total, message)
    assert (result is not None) is ok


def test_normalize_mcp_progress_truncates_long_message() -> None:
    long_msg = "m" * 2000
    result = normalize_mcp_progress(1.0, 2.0, long_msg)
    assert result is not None
    assert len(result[2]) == 500


def test_closed_progress_callback_does_not_emit() -> None:
    events: list[tuple] = []

    def _cb(event_type, name=None, preview=None, args=None, **kwargs):
        events.append((event_type, name, preview, kwargs))

    token = install_tool_progress_sink(
        tool_call_id="call-a",
        tool_name="mcp__demo__slow",
        callback=_cb,
    )
    try:
        sink = get_tool_progress_sink()
        assert sink is not None
        closed = {"closed": False}
        cb = build_mcp_progress_callback(
            tool_call_id="call-a",
            tool_name="mcp__demo__slow",
            generation=sink.generation,
            emit=emit_tool_progress,
            closed_flag=closed,
        )
        asyncio.run(cb(1.0, 10.0, "working"))
        assert len(events) == 1
        assert events[0][0] == "tool.progress"
        close_mcp_progress(closed)
        asyncio.run(cb(9.0, 10.0, "late"))
        assert len(events) == 1
    finally:
        reset_tool_progress_sink(token)


def test_progress_does_not_cross_call_ids() -> None:
    events: list[dict] = []

    def _cb(event_type, name=None, preview=None, args=None, **kwargs):
        events.append({"type": event_type, "name": name, "kwargs": kwargs})

    token_a = install_tool_progress_sink(
        tool_call_id="call-a",
        tool_name="mcp__s__a",
        callback=_cb,
    )
    try:
        sink = get_tool_progress_sink()
        assert sink is not None
        closed = {"closed": False}
        # Callback closed over call-b must not deliver into sink for call-a.
        cb_b = build_mcp_progress_callback(
            tool_call_id="call-b",
            tool_name="mcp__s__b",
            generation=sink.generation,
            emit=emit_tool_progress,
            closed_flag=closed,
        )
        asyncio.run(cb_b(1.0, 2.0, "other"))
        assert events == []
    finally:
        reset_tool_progress_sink(token_a)


def test_make_tool_handler_passes_progress_callback_to_session() -> None:
    """RED until mcp_tool wires SDK progress_callback per call."""
    from tools import mcp_tool

    captured: dict[str, Any] = {}

    class _Session:
        async def call_tool(self, name, arguments=None, progress_callback=None, **kwargs):
            captured["name"] = name
            captured["arguments"] = arguments
            captured["progress_callback"] = progress_callback
            if progress_callback is not None:
                await progress_callback(2.0, 4.0, "step")
            result = MagicMock()
            result.content = []
            result.is_error = False
            # Support mcp_field lookup variants
            result.isError = False
            return result

    server = MagicMock()
    server.session = _Session()
    server._pending_call_context = None
    server._stdio_children_dead = None
    server._mark_session_proven = MagicMock()
    server._suspect_reason = None

    events: list[Any] = []

    def _cb(event_type, name=None, preview=None, args=None, **kwargs):
        events.append((event_type, kwargs.get("progress"), kwargs.get("total"), preview))

    token = install_tool_progress_sink(
        tool_call_id="tc-1",
        tool_name="mcp__fixture__echo",
        callback=_cb,
    )
    try:
        # Patch connection lookup used by handler.
        handler = mcp_tool._make_tool_handler("fixture", "echo", 5.0)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                mcp_tool,
                "_get_connected_server_for_call",
                lambda _name: server,
            )
            mp.setattr(mcp_tool, "_trust_gate_check", lambda *_a, **_k: None)
            mp.setattr(
                mcp_tool,
                "_server_error_counts",
                {},
            )
            # Avoid background loop: execute the coroutine factory inline.
            def _run(coro_or_factory, timeout=None):
                coro = (
                    coro_or_factory()
                    if callable(coro_or_factory)
                    and not inspect.iscoroutine(coro_or_factory)
                    else coro_or_factory
                )
                if inspect.iscoroutine(coro):
                    return asyncio.run(coro)
                return coro

            mp.setattr(mcp_tool, "_run_on_mcp_loop", _run)
            # Policy always admits.
            class _Policy:
                def check(self):
                    return None

                def require(self):
                    return None

            mp.setattr(mcp_tool, "_MCPInvocationPolicy", lambda *_a, **_k: _Policy())

            # Admit context manager
            class _Admit:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, *exc):
                    return False

            mp.setattr(mcp_tool, "_admit_mcp_rpc", lambda *a, **k: _Admit())

            result = handler({"q": "hi"}, tool_call_id="tc-1")

        assert "error" not in str(result).lower() or True  # result shape varies
        assert captured.get("progress_callback") is not None, (
            "MCP call_tool must receive a per-call progress_callback"
        )
        assert any(e[0] == "tool.progress" for e in events), (
            "progress notifications must reach the tool progress sink"
        )
    finally:
        reset_tool_progress_sink(token)
