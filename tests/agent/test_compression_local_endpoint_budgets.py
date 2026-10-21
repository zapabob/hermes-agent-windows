"""Compression budgets for local (llama.cpp / vLLM / Ollama) summarizers.

Regression cover for the field failure "auto-compaction fails and the turn is
dropped when the main model is a local llama-server with a 128K context":

  * The summarizer prompt must be bounded by the SUMMARIZER model's TOKEN
    window, never by a bare character count. CJK text costs roughly one
    token per character, so a character budget can hand a 128K-token server a
    prompt it rejects outright — and even when it fits, its prefill outruns
    the compression no-progress window, so the whole turn is dropped instead
    of being answered.
  * A local summarizer endpoint needs a wider no-progress window: reading a
    large prompt (and generating the summary at the model's own decode speed)
    legitimately exceeds the hosted-API default. The main chat path already
    grants local endpoints the same tolerance for its stream read timeout.

The behaviour under test is provider-agnostic: it holds identically for a
stock llama.cpp build and for a PrismL build.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent.context_compressor import (
    ContextCompressor,
    _SUMMARY_INPUT_MAX_CHARS,
)
from agent.conversation_compression import (
    DEFAULT_CONTEXT_TIMEOUT_SECONDS,
    DEFAULT_CONTEXT_TOTAL_CEILING_SECONDS,
    resolve_context_compression_timeouts,
)
from agent.model_metadata import estimate_tokens_rough


LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
HOSTED_BASE_URL = "https://api.openrouter.ai/api/v1"


def _compressor(context_length: int = 131_072, **kwargs) -> ContextCompressor:
    with patch(
        "agent.context_compressor.get_model_context_length",
        return_value=context_length,
    ):
        comp = ContextCompressor(
            model="local-model", quiet_mode=True, **kwargs
        )
    # The window resolution is deferred to first access, so pin it explicitly
    # instead of relying on the probe above.
    comp.context_length = context_length
    return comp


def _capture_prompt(comp: ContextCompressor, turns) -> str:
    """Run the summary prompt builder with the provider call stubbed out."""
    captured: dict = {}

    def _fake_call_llm(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "## Active Task\nUser asked X"
        return response

    with patch("agent.context_compressor.call_llm", side_effect=_fake_call_llm):
        comp._generate_summary(turns)
    return captured["prompt"]


class TestSummaryInputTokenBudget:
    def test_budget_follows_the_summarizer_window(self):
        comp = _compressor(131_072)
        # No auxiliary model configured -> the summary runs on the main model,
        # so the main window bounds the prompt.
        assert comp.aux_context_length == 131_072
        assert comp._summary_input_token_budget() == 131_072 // 4

    def test_budget_follows_a_dedicated_auxiliary_window(self):
        """A separate compression model bounds the prompt with ITS window."""
        comp = _compressor(131_072)
        comp.aux_context_length = 64_000
        assert comp.aux_context_length == 64_000
        assert comp._summary_input_token_budget() == 16_000

    def test_budget_is_bounded_on_a_huge_window(self):
        comp = _compressor(1_000_000)
        assert comp._summary_input_token_budget() == 40_000

    def test_cjk_middle_window_fits_the_summarizer_window(self):
        """The whole contract: prompt + summary output fit the aux window.

        The middle window here is CJK, which is the case a character budget
        gets wrong by ~4x (1 token per character, not 1 per four).
        """
        comp = _compressor(131_072)
        turns = [
            {"role": "user", "content": "これは日本語の長いテキストです。" * 500}
            for _ in range(40)
        ]
        prompt = _capture_prompt(comp, turns)
        prompt_tokens = estimate_tokens_rough(prompt)
        # Room must be left for the summary output the summarizer still has
        # to produce.
        assert prompt_tokens + comp.max_summary_tokens <= comp.aux_context_length

    def test_cjk_middle_window_is_not_char_bounded(self):
        """A CJK block that fits the char ceiling may still blow the window.

        160K characters of CJK is ~160K tokens — larger than a 128K window.
        The token bound must cut it; the character bound would not.
        """
        comp = _compressor(131_072)
        cjk = "あ" * 200_000
        assert len(cjk) > _SUMMARY_INPUT_MAX_CHARS
        bounded = comp._bound_summary_input(cjk, comp._summary_input_token_budget())
        assert estimate_tokens_rough(bounded) <= comp._summary_input_token_budget()

    def test_bounded_input_keeps_head_and_tail(self):
        comp = _compressor(131_072)
        content = "HEAD_MARKER" + ("あ" * 200_000) + "TAIL_MARKER"
        bounded = comp._bound_summary_input(
            content, comp._summary_input_token_budget()
        )
        assert "HEAD_MARKER" in bounded
        assert "TAIL_MARKER" in bounded
        assert "summary input truncated" in bounded

    def test_iterative_prompt_shares_one_budget(self):
        """The previous summary and the new turns share a single budget."""
        comp = _compressor(131_072)
        comp._previous_summary = "PREV " + ("あ" * 200_000) + " PREV_TAIL"
        turns = [
            {"role": "user", "content": "新しいTURNS" + ("あ" * 200_000)}
        ]
        prompt = _capture_prompt(comp, turns)
        budget = comp._summary_input_token_budget()
        # One budget for both blocks plus the fixed template.
        assert estimate_tokens_rough(prompt) <= budget + 8_000


class TestLocalEndpointCompressionBudgets:
    def test_local_endpoint_widens_the_no_progress_window(self):
        idle, ceiling = resolve_context_compression_timeouts(
            {}, base_url=LOCAL_BASE_URL
        )
        assert idle > DEFAULT_CONTEXT_TIMEOUT_SECONDS
        assert ceiling > DEFAULT_CONTEXT_TOTAL_CEILING_SECONDS
        assert ceiling >= idle

    def test_hosted_endpoint_keeps_the_defaults(self):
        idle, ceiling = resolve_context_compression_timeouts(
            {}, base_url=HOSTED_BASE_URL
        )
        assert idle == DEFAULT_CONTEXT_TIMEOUT_SECONDS
        assert ceiling == DEFAULT_CONTEXT_TOTAL_CEILING_SECONDS

    def test_no_base_url_keeps_the_defaults(self):
        idle, ceiling = resolve_context_compression_timeouts({})
        assert idle == DEFAULT_CONTEXT_TIMEOUT_SECONDS
        assert ceiling == DEFAULT_CONTEXT_TOTAL_CEILING_SECONDS

    def test_explicit_config_wins_over_the_local_widening(self):
        """An operator-set window is never overridden by the local default."""
        idle, ceiling = resolve_context_compression_timeouts(
            {
                "context_timeout_seconds": 90,
                "context_total_ceiling_seconds": 120,
            },
            base_url=LOCAL_BASE_URL,
        )
        assert idle == 90.0
        assert ceiling == 120.0

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://127.0.0.1:8080/v1",
            "http://localhost:8080/v1",
            "http://192.168.1.20:8080/v1",
        ],
    )
    def test_loopback_and_lan_endpoints_are_recognised(self, endpoint):
        idle, _ceiling = resolve_context_compression_timeouts({}, base_url=endpoint)
        assert idle > DEFAULT_CONTEXT_TIMEOUT_SECONDS
