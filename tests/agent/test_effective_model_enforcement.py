"""Tests for Slice F — Effective Model Enforcement.

Verifies:
1. OPENAI_EFFECTIVE_MODEL
2. ANTHROPIC_EFFECTIVE_MODEL
3. GEMINI_EFFECTIVE_MODEL
4. OPENROUTER_EFFECTIVE_MODEL
5. NVIDIA_EFFECTIVE_MODEL
6. NOUS_EFFECTIVE_MODEL
7. CUSTOM_EFFECTIVE_MODEL
8. LOCAL_EFFECTIVE_MODEL
9. COPILOT_ACP_EFFECTIVE_MODEL (9.A, 9.B, 9.C, 9.D)
10. SESSION_EFFECTIVE_MODEL_ISOLATION
11. RESUME_EFFECTIVE_MODEL
12. NO_SILENT_MODEL_SUBSTITUTION
13. EXPLICIT_FALLBACK_OBSERVABLE
14. REQUESTED_VS_EFFECTIVE_OBSERVABLE
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.model_route_observation import (
    ModelRouteObservation,
    build_route_observation,
)
from agent.turn_finalizer import finalize_turn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test Helpers & Dummies
# ---------------------------------------------------------------------------

class MockAgent:
    """Mock agent for turn finalization and route observation testing."""

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o",
        requested_provider: str | None = None,
        requested_model: str | None = None,
        base_url: str | None = None,
        session_id: str = "test-session-1",
    ):
        self.provider = provider
        self.model = model
        self.requested_provider = requested_provider or provider
        self.requested_model = requested_model or model
        self.base_url = base_url
        self.session_id = session_id

        self.quiet_mode = True
        self.max_iterations = 5
        self.iteration_budget = SimpleNamespace(
            remaining=5, used=0, max_total=5
        )
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_cache_read_tokens = 0
        self.session_cache_write_tokens = 0
        self.session_reasoning_tokens = 0
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_total_tokens = 0
        self.session_estimated_cost_usd = 0.0
        self.session_cost_status = "unknown"
        self.session_cost_source = "test"
        self.context_compressor = SimpleNamespace(last_prompt_tokens=0)
        self._tool_guardrail_halt_decision = None
        self._response_was_previewed = False
        self._interrupt_message = None
        self.valid_tool_names = []
        self._skill_nudge_interval = 0
        self._iters_since_skill = 0
        self._fallback_reason = None
        self.last_route_observation = None

    def _emit_status(self, *_args, **_kwargs):
        pass

    def _safe_print(self, *_args, **_kwargs):
        pass

    def _handle_max_iterations(self, _messages, _api_call_count):
        return "max iterations"

    def _save_trajectory(self, *_args, **_kwargs):
        pass

    def _cleanup_task_resources(self, *_args, **_kwargs):
        pass

    def _drop_trailing_empty_response_scaffolding(self, *_args, **_kwargs):
        pass

    def _persist_session(self, *_args, **_kwargs):
        pass

    def _file_mutation_verifier_enabled(self):
        return False

    def _turn_completion_explainer_enabled(self):
        return False

    def _drain_pending_steer(self):
        return None

    def clear_interrupt(self):
        pass

    def _sync_external_memory_for_turn(self, **_kwargs):
        pass


# ---------------------------------------------------------------------------
# 1. OPENAI_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_openai_effective_model():
    """RED 1: OpenAI-compatible transport boundary passes model to api_kwargs."""
    agent = MockAgent(provider="openai", model="gpt-4o-2024-11-20")
    obs = build_route_observation(agent, wire_model="gpt-4o-2024-11-20")

    assert obs.requested_provider == "openai"
    assert obs.requested_model == "gpt-4o-2024-11-20"
    assert obs.wire_model == "gpt-4o-2024-11-20"
    assert obs.effective_model == "gpt-4o-2024-11-20"
    assert obs.effective_provider == "openai"
    assert not obs.fallback


# ---------------------------------------------------------------------------
# 2. ANTHROPIC_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_anthropic_effective_model():
    """RED 2: Anthropic transport boundary normalizes model without silent substitution."""
    from agent.anthropic_adapter import normalize_model_name

    requested = "anthropic/claude-3-7-sonnet"
    wire = normalize_model_name(requested)
    assert wire == "claude-3-7-sonnet"

    agent = MockAgent(
        provider="anthropic",
        model=requested,
        requested_provider="anthropic",
        requested_model=requested,
    )
    obs = build_route_observation(
        agent,
        wire_provider="anthropic",
        wire_model=wire,
        effective_model=wire,
        effective_model_source="response",
    )

    assert obs.requested_model == "anthropic/claude-3-7-sonnet"
    assert obs.wire_model == "claude-3-7-sonnet"
    assert obs.effective_model == "claude-3-7-sonnet"
    assert not obs.fallback


# ---------------------------------------------------------------------------
# 3. GEMINI_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_gemini_effective_model():
    """RED 3: Gemini native transport boundary uses bare_gemini_model_id."""
    from agent.gemini_native_adapter import bare_gemini_model_id

    requested = "google/gemini-2.5-pro"
    wire = bare_gemini_model_id(requested)
    assert wire == "gemini-2.5-pro"

    agent = MockAgent(
        provider="gemini",
        model=requested,
        requested_provider="gemini",
        requested_model=requested,
    )
    obs = build_route_observation(
        agent,
        wire_provider="gemini",
        wire_model=wire,
        effective_model=wire,
    )

    assert obs.requested_model == "google/gemini-2.5-pro"
    assert obs.wire_model == "gemini-2.5-pro"
    assert obs.effective_model == "gemini-2.5-pro"
    assert not obs.fallback


# ---------------------------------------------------------------------------
# 4. OPENROUTER_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_openrouter_effective_model():
    """RED 4: OpenRouter transport boundary preserves vendor/model[:variant] verbatim."""
    requested = "anthropic/claude-3.5-sonnet:beta"
    agent = MockAgent(
        provider="openrouter",
        model=requested,
        requested_provider="openrouter",
        requested_model=requested,
    )
    obs = build_route_observation(
        agent,
        wire_provider="openrouter",
        wire_model=requested,
        effective_model=requested,
    )

    assert obs.requested_model == requested
    assert obs.wire_model == requested
    assert obs.effective_model == requested
    assert not obs.fallback


# ---------------------------------------------------------------------------
# 5. NVIDIA_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_nvidia_effective_model():
    """RED 5: NVIDIA transport boundary does not route to implicit Nous or other provider."""
    requested = "meta/llama-3.1-405b-instruct"
    agent = MockAgent(
        provider="nvidia",
        model=requested,
        requested_provider="nvidia",
        requested_model=requested,
    )
    obs = build_route_observation(
        agent,
        wire_provider="nvidia",
        wire_model=requested,
        effective_model=requested,
    )

    assert obs.requested_provider == "nvidia"
    assert obs.effective_provider == "nvidia"
    assert obs.effective_model == requested
    assert not obs.fallback


# ---------------------------------------------------------------------------
# 6. NOUS_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_nous_effective_model():
    """RED 6: Explicit Nous provider is reached only when requested."""
    requested = "hermes-3-llama-3.1-405b"
    agent = MockAgent(
        provider="nous",
        model=requested,
        requested_provider="nous",
        requested_model=requested,
    )
    obs = build_route_observation(
        agent,
        wire_provider="nous",
        wire_model=requested,
        effective_model=requested,
    )

    assert obs.requested_provider == "nous"
    assert obs.effective_provider == "nous"
    assert obs.effective_model == requested


# ---------------------------------------------------------------------------
# 7. CUSTOM_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_custom_effective_model():
    """RED 7: Custom OpenAI-compatible provider boundary preserves endpoint and model."""
    custom_endpoint = "https://custom-llm.corp.local/v1"
    model = "custom-deepseek-v3"
    agent = MockAgent(
        provider="custom:internal-llm",
        model=model,
        base_url=custom_endpoint,
        requested_provider="custom:internal-llm",
        requested_model=model,
    )
    obs = build_route_observation(
        agent,
        wire_provider="custom:internal-llm",
        wire_model=model,
        effective_model=model,
    )

    assert obs.requested_provider == "custom:internal-llm"
    assert obs.wire_provider == "custom:internal-llm"
    assert obs.effective_provider == "custom:internal-llm"
    assert obs.effective_model == model
    assert not obs.fallback


# ---------------------------------------------------------------------------
# 8. LOCAL_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_local_effective_model():
    """RED 8: Local llama / Ollama addresses the configured model without substitution."""
    model = "qwen2.5:32b-instruct-q4_K_M"
    agent = MockAgent(
        provider="ollama",
        model=model,
        base_url="http://127.0.0.1:11434/v1",
        requested_provider="ollama",
        requested_model=model,
    )
    obs = build_route_observation(
        agent,
        wire_provider="ollama",
        wire_model=model,
        effective_model=model,
    )

    assert obs.requested_provider == "ollama"
    assert obs.effective_provider == "ollama"
    assert obs.effective_model == model
    assert not obs.fallback


# ---------------------------------------------------------------------------
# 9. COPILOT_ACP_EFFECTIVE_MODEL (9.A, 9.B, 9.C, 9.D)
# ---------------------------------------------------------------------------

def test_copilot_acp_effective_model_supported():
    """RED 9.A: Supported model issues session/set_model and effective_model matches."""
    from agent.copilot_acp_client import _apply_session_model

    mock_send = MagicMock(return_value={})
    available_models = [
        {"id": "claude-3-7-sonnet", "name": "Claude 3.7 Sonnet"},
        {"id": "gpt-4o", "name": "GPT-4o"},
    ]

    effective = _apply_session_model(
        send_req=mock_send,
        session_id="acp-sess-1",
        requested_model="claude-3-7-sonnet",
        server_default="gpt-4o",
        available_models=available_models,
    )

    assert effective == "claude-3-7-sonnet"
    mock_send.assert_called_once_with(
        "session/set_model",
        {"sessionId": "acp-sess-1", "modelId": "claude-3-7-sonnet"},
    )


def test_copilot_acp_effective_model_unsupported():
    """RED 9.B: Unsupported model logs warning and falls back to server default without false claim."""
    from agent.copilot_acp_client import _apply_session_model

    mock_send = MagicMock(return_value={})
    available_models = [
        {"id": "gpt-4o", "name": "GPT-4o"},
    ]

    effective = _apply_session_model(
        send_req=mock_send,
        session_id="acp-sess-1",
        requested_model="gemini-2.5-flash",
        server_default="gpt-4o",
        available_models=available_models,
    )

    assert effective == "gpt-4o"
    mock_send.assert_not_called()


def test_copilot_acp_effective_model_virtual_slug():
    """RED 9.C: Virtual/internal slug is never forwarded onto ACP wire."""
    from agent.copilot_acp_client import _apply_session_model

    mock_send = MagicMock(return_value={})
    available_models = [
        {"id": "gpt-4o", "name": "GPT-4o"},
    ]

    effective = _apply_session_model(
        send_req=mock_send,
        session_id="acp-sess-1",
        requested_model="copilot-acp",
        server_default="gpt-4o",
        available_models=available_models,
    )

    assert effective == "gpt-4o"
    mock_send.assert_not_called()


def test_copilot_acp_effective_model_server_without_switching():
    """RED 9.D: Server without model switching preserves server default explicitly."""
    from agent.copilot_acp_client import _apply_session_model

    mock_send = MagicMock(return_value={})

    effective = _apply_session_model(
        send_req=mock_send,
        session_id="acp-sess-1",
        requested_model="claude-3-7-sonnet",
        server_default="default-acp-model",
        available_models=[],
    )

    assert effective == "default-acp-model"
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# 10. SESSION_EFFECTIVE_MODEL_ISOLATION
# ---------------------------------------------------------------------------

def test_session_effective_model_isolation():
    """RED 10: Concurrent sessions maintain independent requested and effective models."""
    agent_a = MockAgent(
        provider="openai",
        model="gpt-4o",
        requested_provider="openai",
        requested_model="gpt-4o",
        session_id="session-A",
    )
    agent_b = MockAgent(
        provider="anthropic",
        model="claude-3-7-sonnet",
        requested_provider="anthropic",
        requested_model="claude-3-7-sonnet",
        session_id="session-B",
    )

    obs_a = build_route_observation(agent_a)
    obs_b = build_route_observation(agent_b)

    assert obs_a.requested_model == "gpt-4o"
    assert obs_a.effective_model == "gpt-4o"
    assert obs_b.requested_model == "claude-3-7-sonnet"
    assert obs_b.effective_model == "claude-3-7-sonnet"
    assert obs_a.session_id != obs_b.session_id


# ---------------------------------------------------------------------------
# 11. RESUME_EFFECTIVE_MODEL
# ---------------------------------------------------------------------------

def test_resume_effective_model():
    """RED 11: Resumed session preserves its persisted session model over profile default."""
    profile_default_model = "gpt-4o-mini"
    persisted_session_model = "claude-3-7-sonnet"

    # Agent initialized with resumed session model
    resumed_agent = MockAgent(
        provider="anthropic",
        model=persisted_session_model,
        requested_provider="anthropic",
        requested_model=persisted_session_model,
        session_id="resumed-session-123",
    )

    obs = build_route_observation(resumed_agent)
    assert obs.requested_model == persisted_session_model
    assert obs.effective_model == persisted_session_model
    assert obs.effective_model != profile_default_model


# ---------------------------------------------------------------------------
# 12. NO_SILENT_MODEL_SUBSTITUTION
# ---------------------------------------------------------------------------

def test_no_silent_model_substitution():
    """RED 12: When response reports different model, observation captures it and warns."""
    agent = MockAgent(
        provider="openai",
        model="gpt-4o",
        requested_provider="openai",
        requested_model="gpt-4o",
    )

    # Server returned gpt-3.5-turbo instead of requested gpt-4o
    obs = build_route_observation(
        agent,
        wire_model="gpt-4o",
        effective_model="gpt-3.5-turbo",
        effective_model_source="response",
    )

    assert obs.requested_model == "gpt-4o"
    assert obs.wire_model == "gpt-4o"
    assert obs.effective_model == "gpt-3.5-turbo"
    assert obs.effective_model_source == "response"


# ---------------------------------------------------------------------------
# 13. EXPLICIT_FALLBACK_OBSERVABLE
# ---------------------------------------------------------------------------

def test_explicit_fallback_observable():
    """RED 13: Explicit fallback preserves original requested route and records reason."""
    agent = MockAgent(
        provider="anthropic",
        model="claude-3-haiku",
        requested_provider="openai",
        requested_model="gpt-4o",
    )
    agent._fallback_reason = "rate_limit_exceeded"

    obs = build_route_observation(
        agent,
        wire_provider="anthropic",
        wire_model="claude-3-haiku",
        effective_provider="anthropic",
        effective_model="claude-3-haiku",
        fallback=True,
        reason="rate_limit_exceeded",
    )

    assert obs.requested_provider == "openai"
    assert obs.requested_model == "gpt-4o"
    assert obs.effective_provider == "anthropic"
    assert obs.effective_model == "claude-3-haiku"
    assert obs.fallback is True
    assert obs.reason == "rate_limit_exceeded"


# ---------------------------------------------------------------------------
# 14. REQUESTED_VS_EFFECTIVE_OBSERVABLE
# ---------------------------------------------------------------------------

def test_requested_vs_effective_observable():
    """RED 14: ModelRouteObservation data contract exposes getters, to_dict, and zero secrets."""
    obs = ModelRouteObservation(
        requested_provider="openrouter",
        requested_model="deepseek/deepseek-r1",
        wire_provider="openrouter",
        wire_model="deepseek/deepseek-r1",
        effective_provider="openrouter",
        effective_model="deepseek/deepseek-r1",
        fallback=False,
        reason=None,
        effective_model_source="request",
    )

    # CamelCase properties
    assert obs.requestedProvider == "openrouter"
    assert obs.requestedModel == "deepseek/deepseek-r1"
    assert obs.wireProvider == "openrouter"
    assert obs.wireModel == "deepseek/deepseek-r1"
    assert obs.effectiveProvider == "openrouter"
    assert obs.effectiveModel == "deepseek/deepseek-r1"
    assert obs.effectiveModelSource == "request"

    # Serialization
    d = obs.to_dict()
    assert d["requested_provider"] == "openrouter"
    assert d["requested_model"] == "deepseek/deepseek-r1"
    assert d["effective_provider"] == "openrouter"
    assert d["effective_model"] == "deepseek/deepseek-r1"
    assert d["fallback"] is False

    # Turn finalizer integration
    agent = MockAgent(
        provider="openrouter",
        model="deepseek/deepseek-r1",
        requested_provider="openrouter",
        requested_model="deepseek/deepseek-r1",
    )
    agent.last_route_observation = obs

    res = finalize_turn(
        agent=agent,
        messages=[{"role": "user", "content": "hello"}],
        final_response="Hello world",
        api_call_count=1,
        interrupted=False,
        failed=False,
        conversation_history=None,
        effective_task_id="default",
        turn_id="t1",
        user_message="hello",
        original_user_message="hello",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert res["requested_provider"] == "openrouter"
    assert res["requested_model"] == "deepseek/deepseek-r1"
    assert res["effective_provider"] == "openrouter"
    assert res["effective_model"] == "deepseek/deepseek-r1"
    assert res["route_observation"] == obs
    assert res["route_observation"].to_dict() == d
