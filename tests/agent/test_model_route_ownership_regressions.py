"""Ownership regressions and edge-case qualification for ModelRouteObservation (Slice G.1).

Tests:
1. Session isolation: Session A fallback does not leak into Session B normal route.
2. Turn isolation: Late old-turn completion does not corrupt fresh turn observation.
3. Turn sequence: Fallback on Turn 1 followed by primary success on Turn 2 transitions cleanly.
4. Copilot ACP server-default: Server without setModel advertising default produces
   effective_model_source="server", is_drift() is False, is_divergent() is False, quiet label.
5. Metric separation: ModelRouteObservation maintains zero metric bookkeeping.
"""

from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock

from agent.model_route_observation import (
    ModelRouteObservation,
    build_route_observation,
)


def test_session_isolation_fallback_vs_normal():
    """Session A fallback must never leak into Session B normal route."""
    obs_a = build_route_observation(
        requested_provider="nvidia",
        requested_model="deepseek-r1",
        wire_provider="nous",
        wire_model="hermes-3-70b",
        effective_provider="nous",
        effective_model="hermes-3-70b",
        fallback=True,
        reason="NVIDIA API rate limit (429)",
        session_id="session-A",
    )

    obs_b = build_route_observation(
        requested_provider="anthropic",
        requested_model="claude-3-7-sonnet",
        wire_provider="anthropic",
        wire_model="claude-3-7-sonnet",
        effective_provider="anthropic",
        effective_model="claude-3-7-sonnet",
        fallback=False,
        session_id="session-B",
    )

    # Session A assertions
    assert obs_a.session_id == "session-A"
    assert obs_a.fallback is True
    assert obs_a.is_divergent() is True
    assert obs_a.is_drift() is False
    summary_a = obs_a.ux_summary()
    assert summary_a["divergent"] is True
    assert summary_a["type"] == "fallback"
    assert "NVIDIA" in summary_a["lines"][0]

    # Session B assertions
    assert obs_b.session_id == "session-B"
    assert obs_b.fallback is False
    assert obs_b.is_divergent() is False
    assert obs_b.is_drift() is False
    summary_b = obs_b.ux_summary()
    assert summary_b["divergent"] is False
    assert summary_b["type"] == "normal"

    # Isolation invariant: dict representations and badges are independent
    d_a = obs_a.to_dict()
    d_b = obs_b.to_dict()
    assert d_a["sessionId"] == "session-A"
    assert d_b["sessionId"] == "session-B"
    assert d_a["isDivergent"] is True
    assert d_b["isDivergent"] is False


def test_turn_sequence_fallback_then_primary_success():
    """Turn 1 fallback followed by Turn 2 primary success transitions cleanly."""
    mock_agent = MagicMock()
    mock_agent.provider = "openai"
    mock_agent.model = "gpt-4o"
    mock_agent.requested_provider = "openai"
    mock_agent.requested_model = "gpt-4o"

    # Turn 1: Fallback activates
    mock_agent._fallback_activated = True
    mock_agent._fallback_reason = "503 service unavailable"
    turn_1_obs = build_route_observation(
        agent=mock_agent,
        wire_provider="groq",
        wire_model="llama-3.3-70b",
        effective_provider="groq",
        effective_model="llama-3.3-70b",
        fallback=True,
        reason="503 service unavailable",
        effective_model_source="request",
    )
    mock_agent.last_route_observation = turn_1_obs

    assert mock_agent.last_route_observation.fallback is True
    assert mock_agent.last_route_observation.is_divergent() is True
    assert mock_agent.last_route_observation.ux_summary()["divergent"] is True

    # Turn 2: Primary succeeds without fallback
    mock_agent._fallback_activated = False
    mock_agent._fallback_reason = None
    turn_2_obs = build_route_observation(
        agent=mock_agent,
        wire_provider="openai",
        wire_model="gpt-4o",
        effective_provider="openai",
        effective_model="gpt-4o",
        fallback=False,
        reason=None,
        effective_model_source="response",
    )
    mock_agent.last_route_observation = turn_2_obs

    assert mock_agent.last_route_observation.fallback is False
    assert mock_agent.last_route_observation.is_divergent() is False
    assert mock_agent.last_route_observation.is_drift() is False
    summary_2 = mock_agent.last_route_observation.ux_summary()
    assert summary_2["divergent"] is False
    assert summary_2["type"] == "normal"
    assert mock_agent.last_route_observation.quiet_label() == "GPT-4o · OpenAI"


def test_late_old_turn_completion_isolation():
    """Simulated late turn completion from turn N does not overwrite turn N+1."""
    completed_turns: dict[int, ModelRouteObservation] = {}

    def simulate_turn(turn_id: int, fallback: bool, reason: str | None = None):
        return build_route_observation(
            requested_provider="openai",
            requested_model="gpt-4o",
            wire_provider="groq" if fallback else "openai",
            wire_model="llama-3.3-70b" if fallback else "gpt-4o",
            effective_provider="groq" if fallback else "openai",
            effective_model="llama-3.3-70b" if fallback else "gpt-4o",
            fallback=fallback,
            reason=reason,
            session_id=f"turn-{turn_id}",
        )

    # Submit turn 1 (slow, fallback) and turn 2 (fast, normal) concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(simulate_turn, 1, True, "slow timeout")
        f2 = executor.submit(simulate_turn, 2, False, None)
        obs_2 = f2.result()
        obs_1 = f1.result()

    completed_turns[1] = obs_1
    completed_turns[2] = obs_2

    assert completed_turns[1].fallback is True
    assert completed_turns[1].is_divergent() is True
    assert completed_turns[2].fallback is False
    assert completed_turns[2].is_divergent() is False
    assert completed_turns[1].session_id == "turn-1"
    assert completed_turns[2].session_id == "turn-2"


def test_copilot_acp_server_default_ux():
    """Copilot ACP server-default model advertising produces non-drift quiet label."""
    # Virtual slug 'copilot-acp' requesting server default
    obs = build_route_observation(
        requested_provider="copilot",
        requested_model="copilot-acp",
        wire_provider="copilot",
        wire_model="copilot-acp",
        effective_provider="copilot",
        effective_model="server-default",
        fallback=False,
        effective_model_source="server",
    )

    assert obs.effective_model_source == "server"
    assert obs.fallback is False
    assert obs.is_drift() is False
    assert obs.is_divergent() is False

    # UX presentation
    summary = obs.ux_summary()
    assert summary["divergent"] is False
    assert summary["type"] == "normal"
    assert obs.quiet_label() == "server-default · Copilot"

    # Also verify when requested_model is 'default' or 'auto'
    for slug in ("default", "auto"):
        slug_obs = build_route_observation(
            requested_provider="copilot",
            requested_model=slug,
            wire_provider="copilot",
            wire_model=slug,
            effective_provider="copilot",
            effective_model="claude-3-5-sonnet",
            fallback=False,
            effective_model_source="server",
        )
        assert slug_obs.is_drift() is False
        assert slug_obs.is_divergent() is False
        assert slug_obs.quiet_label() == "Claude 3 5 Sonnet · Copilot"


def test_metric_separation_from_routing_semantics():
    """ModelRouteObservation must remain strictly decoupled from metric counters."""
    obs = ModelRouteObservation(
        requested_provider="openai",
        requested_model="gpt-4o",
        wire_provider="openai",
        wire_model="gpt-4o",
        effective_provider="openai",
        effective_model="gpt-4o",
        fallback=False,
    )

    # Invariant: zero metric bookkeeping fields on route observation
    banned_metric_fields = [
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "cost_usd",
        "retry_count",
    ]
    for field in banned_metric_fields:
        assert not hasattr(obs, field), f"ModelRouteObservation unexpectedly has metric field: {field}"

    # Verify serialization does not contain metric keys
    d = obs.to_dict()
    for field in banned_metric_fields:
        assert field not in d
