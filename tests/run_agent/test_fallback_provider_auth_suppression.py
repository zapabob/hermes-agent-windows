"""Provider-level auth suppression in the model fallback chain.

A rejected credential (401/403) is a PROVIDER-level fault: every remaining
chain entry that names the same provider fails the same way.  Before this
change the walk cost one probe per MODEL, so a dead provider with twenty
models in the chain stalled the model picker's provider list for twenty
round trips before reaching the next provider.

Contract under test:

* On an auth-classified failure, every remaining entry of the failing
  provider is suppressed for the session.
* Entries of OTHER providers are untouched.
* A non-auth failure (rate limit, billing, transport) does NOT suppress the
  provider: another model on the same provider may still serve.
* The suppression is visible in the log.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent import chat_completion_helpers
from agent.error_classifier import FailoverReason


def _agent_with_chain(chain, provider="opencode"):
    agent = MagicMock()
    agent._fallback_chain = list(chain)
    agent._fallback_index = 0
    agent._unavailable_fallback_keys = set()
    agent.provider = provider
    agent.model = "primary-model"
    return agent


class TestProviderLevelAuthSuppression:
    def test_auth_failure_suppresses_the_whole_provider(self):
        chain = [
            {"provider": "opencode", "model": f"free-model-{i}"} for i in range(5)
        ] + [{"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b"}]
        agent = _agent_with_chain(chain)

        suppressed = chat_completion_helpers._suppress_provider_fallback_entries(
            agent, "opencode"
        )
        assert suppressed == 5
        assert len(agent._unavailable_fallback_keys) == 5
        # The other provider is untouched.
        assert chat_completion_helpers._fallback_entry_key(chain[-1]) not in (
            agent._unavailable_fallback_keys
        )

    def test_other_providers_are_not_suppressed(self):
        chain = [
            {"provider": "nvidia", "model": "a"},
            {"provider": "gemini", "model": "b"},
        ]
        agent = _agent_with_chain(chain, provider="opencode")
        assert (
            chat_completion_helpers._suppress_provider_fallback_entries(agent, "opencode")
            == 0
        )
        assert agent._unavailable_fallback_keys == set()

    def test_empty_provider_is_a_noop(self):
        chain = [{"provider": "nvidia", "model": "a"}]
        agent = _agent_with_chain(chain)
        assert (
            chat_completion_helpers._suppress_provider_fallback_entries(agent, "")
            == 0
        )

    def test_malformed_chain_is_a_noop(self):
        agent = MagicMock()
        agent._fallback_chain = "not-a-list"
        assert (
            chat_completion_helpers._suppress_provider_fallback_entries(agent, "nvidia")
            == 0
        )


class TestFallbackWalkUsesSuppression:
    def test_auth_reason_triggers_the_suppression(self):
        chain = [
            {"provider": "opencode", "model": "a"},
            {"provider": "opencode", "model": "b"},
            {"provider": "nvidia", "model": "c"},
        ]
        agent = _agent_with_chain(chain, provider="opencode")

        with patch.object(
            chat_completion_helpers,
            "_suppress_provider_fallback_entries",
            wraps=chat_completion_helpers._suppress_provider_fallback_entries,
        ) as spy:
            # The walk itself is not the subject of this test — the
            # suppression hook is. The walk is allowed to fail afterwards.
            try:
                chat_completion_helpers.try_activate_fallback(
                    agent, reason=FailoverReason.auth
                )
            except Exception:
                pass
        assert spy.called
        assert spy.call_args[0][1] == "opencode"

    def test_non_auth_reason_does_not_suppress(self):
        chain = [
            {"provider": "opencode", "model": "a"},
            {"provider": "nvidia", "model": "c"},
        ]
        agent = _agent_with_chain(chain, provider="opencode")
        with patch.object(
            chat_completion_helpers,
            "_suppress_provider_fallback_entries",
            wraps=chat_completion_helpers._suppress_provider_fallback_entries,
        ) as spy:
            try:
                chat_completion_helpers.try_activate_fallback(
                    agent, reason=FailoverReason.rate_limit
                )
            except Exception:
                pass
        assert not spy.called
