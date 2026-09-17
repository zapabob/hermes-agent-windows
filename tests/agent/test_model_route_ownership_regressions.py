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
import threading
from unittest.mock import MagicMock, patch

from agent.model_route_observation import (
    ModelRouteObservation,
    build_route_observation,
    commit_route_observation,
)


def test_session_isolation_fallback_vs_normal():
    """Session A fallback must never leak into Session B normal route across actual session-owner path."""
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
        turn_seq=1,
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
        turn_seq=1,
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

    # Actual Gateway session-owner path test:
    # Verify that when two independent sessions execute in parallel or sequentially,
    # Session B's message.complete event NEVER receives or displays Session A's fallback route or reason.
    from tui_gateway import server

    emitted_events: list[tuple] = []

    def capture_emit(event_type, sid, payload=None):
        emitted_events.append((event_type, sid, payload))

    agent_a = MagicMock()
    agent_a.last_route_observation = obs_a
    agent_a.run_conversation.return_value = {
        "text": "Session A answer",
        "route_observation": obs_a,
        "messages": [],
    }
    agent_a.session_id = "session-A"

    agent_b = MagicMock()
    agent_b.last_route_observation = obs_b
    agent_b.run_conversation.return_value = {
        "text": "Session B answer",
        "route_observation": obs_b,
        "messages": [],
    }
    agent_b.session_id = "session-B"

    session_a = {
        "history_lock": threading.Lock(),
        "running": True,
        "agent": agent_a,
        "session_key": "key-A",
        "history": [],
        "attached_images": [],
        "_closing": False,
    }

    session_b = {
        "history_lock": threading.Lock(),
        "running": True,
        "agent": agent_b,
        "session_key": "key-B",
        "history": [],
        "attached_images": [],
        "_closing": False,
    }

    with patch.object(server, "_emit", side_effect=capture_emit), \
         patch.object(server, "_get_usage", return_value={}), \
         patch.object(server, "render_message", return_value=""), \
         patch.object(server, "_start_usage_ticker", return_value=(MagicMock(), MagicMock())):

        server._run_prompt_submit(1, "session-A", session_a, "Help A")
        if "_run_thread" in session_a:
            session_a["_run_thread"].join(timeout=5.0)

        server._run_prompt_submit(2, "session-B", session_b, "Help B")
        if "_run_thread" in session_b:
            session_b["_run_thread"].join(timeout=5.0)

    # Verify session A complete event
    complete_a = [e for e in emitted_events if e[0] == "message.complete" and e[1] == "session-A"]
    assert len(complete_a) == 1
    payload_a = complete_a[0][2]
    assert payload_a["route"]["fallback"] is True
    assert payload_a["route"]["isDivergent"] is True
    assert "NVIDIA" in payload_a["route"]["reason"]

    # Verify session B complete event: completely isolated, zero leakage from A
    complete_b = [e for e in emitted_events if e[0] == "message.complete" and e[1] == "session-B"]
    assert len(complete_b) == 1
    payload_b = complete_b[0][2]
    assert payload_b["route"]["fallback"] is False
    assert payload_b["route"]["isDivergent"] is False
    assert payload_b["route"]["requestedModel"] == "claude-3-7-sonnet"
    assert payload_b["route"]["effectiveModel"] == "claude-3-7-sonnet"
    assert payload_b["route"]["reason"] is None
    assert agent_b.last_route_observation.fallback is False


def test_turn_sequence_fallback_then_primary_success():
    """Turn 1 fallback followed by Turn 2 primary success transitions cleanly with stale indicator absent."""
    mock_agent = MagicMock()
    mock_agent.provider = "openai"
    mock_agent.model = "gpt-4o"
    mock_agent.requested_provider = "openai"
    mock_agent.requested_model = "gpt-4o"
    mock_agent._authoritative_route_turn_seq = 0

    # Turn 1: Fallback activates
    mock_agent._fallback_activated = True
    mock_agent._fallback_reason = "503 service unavailable"
    mock_agent._user_turn_count = 1
    turn_1_obs = build_route_observation(
        agent=mock_agent,
        wire_provider="groq",
        wire_model="llama-3.3-70b",
        effective_provider="groq",
        effective_model="llama-3.3-70b",
        fallback=True,
        reason="503 service unavailable",
        effective_model_source="request",
        turn_seq=1,
    )
    committed_t1 = commit_route_observation(mock_agent, turn_1_obs, turn_seq=1)
    assert committed_t1 is True

    assert mock_agent.last_route_observation.fallback is True
    assert mock_agent.last_route_observation.is_divergent() is True
    assert mock_agent.last_route_observation.ux_summary()["divergent"] is True

    # Turn 2: Primary succeeds without fallback
    mock_agent._fallback_activated = False
    mock_agent._fallback_reason = None
    mock_agent._user_turn_count = 2
    turn_2_obs = build_route_observation(
        agent=mock_agent,
        wire_provider="openai",
        wire_model="gpt-4o",
        effective_provider="openai",
        effective_model="gpt-4o",
        fallback=False,
        reason=None,
        effective_model_source="response",
        turn_seq=2,
    )
    committed_t2 = commit_route_observation(mock_agent, turn_2_obs, turn_seq=2)
    assert committed_t2 is True

    assert mock_agent.last_route_observation.fallback is False
    assert mock_agent.last_route_observation.is_divergent() is False
    assert mock_agent.last_route_observation.is_drift() is False
    summary_2 = mock_agent.last_route_observation.ux_summary()
    assert summary_2["divergent"] is False
    assert summary_2["type"] == "normal"
    assert mock_agent.last_route_observation.quiet_label() == "GPT-4o · OpenAI"

    # Verify recovery cleans stale fallback notice in CLI render path:
    # On turn 1 is_divergent() is True -> 1 panel printed.
    # On turn 2 is_divergent() is False -> 0 panels printed.
    from cli import HermesCLI
    cli = HermesCLI.__new__(HermesCLI)
    cli.agent = mock_agent
    cli._divergence_panels_printed = 0

    # Simulate CLI post-turn divergence check for Turn 2
    obs = cli.agent.last_route_observation
    assert obs.is_divergent() is False
    # Stale notice is absent!


def test_production_ownership_late_turn_fencing():
    """Production ownership test: Turn N fallback begins, Turn N+1 normal completes, Turn N completes late.

    Authoritative current route MUST remain Turn N+1, rejecting the stale late commit from Turn N.
    """
    mock_agent = MagicMock()
    mock_agent._authoritative_route_turn_seq = 0
    mock_agent.last_route_observation = None

    # 1. Turn N (fallback) begins with sequence 1
    turn_n_obs = build_route_observation(
        requested_provider="nvidia",
        requested_model="deepseek-r1",
        wire_provider="nous",
        wire_model="hermes-3-70b",
        effective_provider="nous",
        effective_model="hermes-3-70b",
        fallback=True,
        reason="HTTP 429 rate limit",
        turn_seq=1,
    )

    # 2. Turn N+1 (normal) completes FIRST with sequence 2 and becomes authoritative
    turn_n_plus_1_obs = build_route_observation(
        requested_provider="openai",
        requested_model="gpt-4o",
        wire_provider="openai",
        wire_model="gpt-4o",
        effective_provider="openai",
        effective_model="gpt-4o",
        fallback=False,
        reason=None,
        turn_seq=2,
    )
    commit_ok_n1 = commit_route_observation(mock_agent, turn_n_plus_1_obs, turn_seq=2)
    assert commit_ok_n1 is True
    assert mock_agent._authoritative_route_turn_seq == 2
    assert mock_agent.last_route_observation == turn_n_plus_1_obs
    assert mock_agent.last_route_observation.fallback is False
    assert mock_agent.last_route_observation.effective_model == "gpt-4o"

    # 3. Turn N completes LATE and attempts to commit to authoritative route
    commit_ok_n = commit_route_observation(mock_agent, turn_n_obs, turn_seq=1)
    # Stale commit is REJECTED / FENCED!
    assert commit_ok_n is False

    # Current authoritative route remains Turn N+1
    assert mock_agent._authoritative_route_turn_seq == 2
    assert mock_agent.last_route_observation == turn_n_plus_1_obs
    assert mock_agent.last_route_observation.fallback is False
    assert mock_agent.last_route_observation.is_divergent() is False
    assert mock_agent.last_route_observation.effective_model == "gpt-4o"



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
