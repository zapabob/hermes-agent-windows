"""Gateway bridge: tool.progress events reach Desktop-shaped payloads."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_on_tool_progress_emits_tool_progress_with_call_id() -> None:
    from tui_gateway import server as gw

    emitted: list[tuple] = []

    def _capture(event_type, sid, payload=None, **kwargs):
        emitted.append((event_type, sid, payload or {}))

    with patch.object(gw, "_emit", side_effect=_capture), patch.object(
        gw, "_tool_progress_enabled", return_value=True
    ):
        gw._on_tool_progress(
            "sess-1",
            "tool.progress",
            "mcp__demo__work",
            "halfway",
            None,
            tool_call_id="call-9",
            progress=5.0,
            total=10.0,
        )

    assert emitted, "expected tool.progress emit"
    event_type, sid, payload = emitted[0]
    assert event_type == "tool.progress"
    assert sid == "sess-1"
    assert payload.get("tool_id") == "call-9"
    assert payload.get("name") == "mcp__demo__work"
    assert payload.get("progress") == 5.0
    assert payload.get("total") == 10.0
    assert payload.get("preview") == "halfway"


def test_on_tool_progress_ignores_invalid_progress_values() -> None:
    from tui_gateway import server as gw

    emitted: list = []

    with patch.object(gw, "_emit", side_effect=lambda *a, **k: emitted.append(a)), patch.object(
        gw, "_tool_progress_enabled", return_value=True
    ):
        gw._on_tool_progress(
            "sess-1",
            "tool.progress",
            "mcp__demo__work",
            "bad",
            None,
            tool_call_id="call-9",
            progress=float("nan"),
            total=10.0,
        )

    assert emitted == []


def test_tool_progress_does_not_count_as_tool_result() -> None:
    """Progress frames must not look like completed tool results."""
    from tui_gateway import server as gw

    emitted: list[tuple] = []

    def _capture(event_type, sid, payload=None, **kwargs):
        emitted.append((event_type, payload or {}))

    with patch.object(gw, "_emit", side_effect=_capture), patch.object(
        gw, "_tool_progress_enabled", return_value=True
    ):
        gw._on_tool_progress(
            "sess-1",
            "tool.progress",
            "mcp__demo__work",
            "ok",
            None,
            tool_call_id="call-9",
            progress=1.0,
            total=None,
        )

    assert emitted[0][0] == "tool.progress"
    payload = emitted[0][1]
    assert "result" not in payload
    assert payload.get("error") in (None, False, "")
