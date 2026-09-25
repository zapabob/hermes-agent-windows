"""Tests for recovery-time LLMStreamMiddlewareRefusal propagation.

When _reset_stream_delivery_tracking() or _fire_stream_delta() raises
LLMStreamMiddlewareRefusal during _handle_stream_error recovery, the
refusal must be preserved in self.result["error"] and the handler must
return False (no retry).  Prior to the fix, _quiet() swallowed these
refusals and the provider was retried.
"""

from __future__ import annotations

import contextlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent import chat_completion_helpers as helpers
from agent.chat_completion_helpers import _StreamingCall
from hermes_cli.middleware import LLMStreamMiddlewareRefusal


class _FakeAgent:
    """Minimal agent stub for _StreamingCall tests."""

    provider = "openrouter"
    model = "test/model"
    base_url = ""
    api_mode = "chat_completions"
    _current_streamed_assistant_text = ""
    _stream_options_unsupported = False
    stream_delta_callback = None
    _stream_diag_capture_response = lambda self, *a: None  # noqa: E731

    def __init__(self):
        self._reset_raises: type | None = None
        self._fire_delta_raises: type | None = None
        self._dispatched = 0
        self._emit_stream_drop_calls = []

    def _reset_stream_delivery_tracking(self):
        if self._reset_raises:
            raise self._reset_raises("recovery tail flush blocked")

    def _fire_stream_delta(self, text):
        if self._fire_delta_raises:
            raise self._fire_delta_raises("recovery marker blocked")
        return text

    def _is_provider_stream_parse_error(self, e):
        return False

    def _warning_presentation_enabled(self):
        return False

    def _emit_stream_drop(self, **kwargs):
        self._emit_stream_drop_calls.append(kwargs)

    def _emit_warning(self, msg):
        pass

    def _vprint(self, *a, **kw):
        pass

    def _stream_diag_capture_response(self, *a):
        pass


def _make_streaming_call(agent=None):
    """Build a _StreamingCall with minimal scaffolding."""
    if agent is None:
        agent = _FakeAgent()
    sc = _StreamingCall(agent, api_kwargs={}, on_first_delta=lambda: None)
    sc.deltas_were_sent["yes"] = True  # pretend deltas were sent
    return sc


# ── No-visible-text branch ────────────────────────────────────────

def test_recovery_refusal_preserved_in_no_visible_text_branch():
    """_handle_stream_error returns False when _reset_stream_delivery_tracking
    raises LLMStreamMiddlewareRefusal in the 'deltas but nothing visible' branch."""
    agent = _FakeAgent()
    agent._reset_raises = LLMStreamMiddlewareRefusal
    sc = _make_streaming_call(agent)

    result = sc._handle_stream_error(
        ConnectionError("transport dropped"), attempt=0, max_retries=3
    )

    assert result is False
    assert isinstance(sc.result["error"], LLMStreamMiddlewareRefusal)


def test_recovery_refusal_no_retry_in_no_visible_text_branch():
    """When a refusal occurs during recovery cleanup, the retry count must not advance."""
    agent = _FakeAgent()
    agent._reset_raises = LLMStreamMiddlewareRefusal
    sc = _make_streaming_call(agent)

    sc._handle_stream_error(ConnectionError("drop"), attempt=0, max_retries=3)

    # No retry_after_drop should have been called (no dispatch)
    assert agent._emit_stream_drop_calls == []


# ── Mid-tool retry branch ─────────────────────────────────────────

def test_recovery_refusal_preserved_in_mid_tool_reset_branch():
    """_handle_stream_error returns False when _reset_stream_delivery_tracking
    raises LLMStreamMiddlewareRefusal in the mid-tool transient retry branch."""
    agent = _FakeAgent()
    agent._reset_raises = LLMStreamMiddlewareRefusal
    sc = _make_streaming_call(agent)
    # Simulate a partial tool in flight
    sc.result["partial_tool_names"] = ["some_tool"]

    # Need a transient error for the mid-tool branch
    import httpx
    err = httpx.ReadTimeout("stream timed out")

    result = sc._handle_stream_error(err, attempt=0, max_retries=3)

    assert result is False
    assert isinstance(sc.result["error"], LLMStreamMiddlewareRefusal)


def test_recovery_refusal_preserved_in_reconnect_marker():
    """_handle_stream_error returns False when _fire_stream_delta
    (reconnect marker) raises LLMStreamMiddlewareRefusal."""
    agent = _FakeAgent()
    agent._fire_delta_raises = LLMStreamMiddlewareRefusal
    agent._warning_presentation_enabled = lambda: True
    sc = _make_streaming_call(agent)
    sc.result["partial_tool_names"] = ["some_tool"]

    import httpx
    err = httpx.ReadTimeout("stream timed out")

    result = sc._handle_stream_error(err, attempt=0, max_retries=3)

    assert result is False
    assert isinstance(sc.result["error"], LLMStreamMiddlewareRefusal)


def test_partial_stream_warning_refusal_is_not_converted_to_stub():
    agent = _FakeAgent()
    agent._warning_presentation_enabled = lambda: True
    agent._fire_delta_raises = LLMStreamMiddlewareRefusal
    sc = _make_streaming_call(agent)
    sc.result["partial_tool_names"] = ["some_tool"]
    sc.result["error"] = ConnectionError("stream dropped")

    with pytest.raises(LLMStreamMiddlewareRefusal):
        sc._partial_stream_stub()

    assert isinstance(sc.result["error"], LLMStreamMiddlewareRefusal)


def test_partial_stream_warning_display_error_remains_best_effort():
    agent = _FakeAgent()
    agent._warning_presentation_enabled = lambda: True
    agent._fire_delta_raises = RuntimeError
    sc = _make_streaming_call(agent)
    sc.result["partial_tool_names"] = ["some_tool"]
    sc.result["error"] = ConnectionError("stream dropped")

    stub = sc._partial_stream_stub()

    assert stub.choices[0].message.content.endswith("Ask me to retry if you want to continue.")


# ── Positive controls ─────────────────────────────────────────────

def test_ordinary_transport_error_still_retries():
    """Normal transport errors should still result in retry=True."""
    agent = _FakeAgent()
    sc = _make_streaming_call(agent)

    import httpx
    err = httpx.ReadTimeout("stream timed out")

    # Mock the retry path to prevent actual retry logic from running
    sc._retry_after_drop = lambda *a, **kw: None

    result = sc._handle_stream_error(err, attempt=0, max_retries=3)

    # In the mid-tool branch with transient error, should retry
    # (partial_tool_names empty + no visible text → undelivered path → retry)
    assert result is True


def test_fail_open_reset_does_not_block_retry():
    """When _reset_stream_delivery_tracking succeeds (fail-open), retry proceeds normally."""
    agent = _FakeAgent()
    # No raises set — reset succeeds silently
    sc = _make_streaming_call(agent)

    import httpx
    err = httpx.ReadTimeout("stream timed out")

    sc._retry_after_drop = lambda *a, **kw: None

    result = sc._handle_stream_error(err, attempt=0, max_retries=3)

    # Should retry (undelivered path with transient error)
    assert result is True
    assert sc.result["error"] is None


def test_initial_refusal_still_terminates():
    """Refusal raised before recovery (the existing check at the top of _handle_stream_error)
    still works as before."""
    agent = _FakeAgent()
    sc = _make_streaming_call(agent)

    result = sc._handle_stream_error(
        LLMStreamMiddlewareRefusal(ConnectionError("block"), callback_name="test"),
        attempt=0,
        max_retries=3,
    )

    assert result is False
    assert isinstance(sc.result["error"], LLMStreamMiddlewareRefusal)
