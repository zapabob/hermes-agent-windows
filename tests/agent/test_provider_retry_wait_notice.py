"""Provider retry backoff names itself on the live status line (SR-007a)."""

from unittest.mock import MagicMock

from agent.conversation_loop import emit_provider_retry_wait_notice


def test_provider_retry_wait_notice_names_attempt_on_live_line():
    agent = MagicMock()
    emit_provider_retry_wait_notice(agent, wait_time=12.4, retry_count=1, max_retries=3)
    agent._emit_wait_notice.assert_called_once()
    text = agent._emit_wait_notice.call_args.args[0]
    assert text.startswith("⏳ waiting on provider")
    assert "retrying in 12s" in text
    assert "attempt 1/3" in text
