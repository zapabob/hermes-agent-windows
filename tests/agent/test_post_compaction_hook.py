"""post_compaction fires only after durable compression commit."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.compaction_events import fire_post_compaction
from agent.conversation_compression import (
    finalize_context_engine_compression_notification,
    _notify_context_engine_compression_complete,
    _queue_context_engine_compression_notification,
)


def test_fire_post_compaction_invokes_hook_with_session_ids() -> None:
    seen: list[dict] = []

    def _capture(**kwargs):
        seen.append(kwargs)
        return None

    with patch("hermes_cli.lifecycle.has_hook", return_value=True), patch(
        "hermes_cli.lifecycle.invoke_hook", side_effect=lambda name, **kw: [_capture(**kw)]
    ):
        count = fire_post_compaction(
            session_id="new-1",
            old_session_id="old-1",
            kind="rotation",
            reason="compression",
            commit_identity="old-1->new-1:rotation",
        )

    assert count == 1
    assert seen[0]["session_id"] == "new-1"
    assert seen[0]["old_session_id"] == "old-1"
    assert "messages" not in seen[0]


def test_fire_post_compaction_noop_without_listeners() -> None:
    with patch("hermes_cli.lifecycle.has_hook", return_value=False), patch(
        "hermes_cli.lifecycle.invoke_hook"
    ) as invoke:
        assert fire_post_compaction(session_id="a", old_session_id="b") == 0
        invoke.assert_not_called()


def test_notify_fires_post_compaction_once() -> None:
    agent = MagicMock()
    agent.context_compressor.on_session_start = MagicMock()
    agent.platform = "cli"
    agent._gateway_session_key = None

    with patch("agent.compaction_events.fire_post_compaction") as fire, patch(
        "agent.relay_runtime.SESSION_COORDINATOR.notify_session_compacted"
    ):
        _notify_context_engine_compression_complete(
            agent, new_session_id="s2", old_session_id="s1"
        )
        fire.assert_called_once()
        kwargs = fire.call_args.kwargs
        assert kwargs["session_id"] == "s2"
        assert kwargs["old_session_id"] == "s1"
        assert kwargs["kind"] == "rotation"


def test_finalize_uncommitted_does_not_fire_post_compaction() -> None:
    # Plain object: MagicMock auto-creates callable attrs that trip the
    # "already pending" guard in _queue_context_engine_compression_notification.
    agent = type("AgentStub", (), {})()
    with patch(
        "agent.conversation_compression._notify_context_engine_compression_complete"
    ) as notify:
        _queue_context_engine_compression_notification(
            agent, new_session_id="s2", old_session_id="s1"
        )
        assert finalize_context_engine_compression_notification(agent, committed=False) is False
        notify.assert_not_called()


def test_finalize_committed_fires_exactly_once() -> None:
    agent = type("AgentStub", (), {})()
    with patch(
        "agent.conversation_compression._notify_context_engine_compression_complete",
        return_value=True,
    ) as notify:
        _queue_context_engine_compression_notification(
            agent, new_session_id="s2", old_session_id="s1"
        )
        assert finalize_context_engine_compression_notification(agent, committed=True) is True
        assert finalize_context_engine_compression_notification(agent, committed=True) is False
        notify.assert_called_once()


def test_post_compaction_hook_exception_does_not_raise() -> None:
    with patch("hermes_cli.lifecycle.has_hook", return_value=True), patch(
        "hermes_cli.lifecycle.invoke_hook", side_effect=RuntimeError("boom")
    ):
        assert fire_post_compaction(session_id="a", old_session_id="b") == 0
