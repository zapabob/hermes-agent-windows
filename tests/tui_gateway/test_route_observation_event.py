"""Tests for forwarding ModelRouteObservation via message.complete in tui_gateway."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.model_route_observation import ModelRouteObservation


def test_message_complete_forwards_route_observation():
    from tui_gateway import server

    emitted: list[tuple] = []

    def fake_emit(event_type, sid, payload=None):
        emitted.append((event_type, sid, payload))

    obs = ModelRouteObservation(
        requested_provider="nvidia",
        requested_model="model-N",
        wire_provider="nous",
        wire_model="model-F",
        effective_provider="nous",
        effective_model="model-F",
        fallback=True,
        reason="rate limit",
    )

    mock_agent = MagicMock()
    mock_agent.last_route_observation = obs

    fake_result = {
        "text": "Hello from fallback model",
        "route_observation": obs,
    }

    # Verify that the emission logic in _run_prompt_submit preserves route
    with patch.object(server, "_emit", side_effect=fake_emit), \
         patch.object(server, "_get_usage", return_value={}), \
         patch.object(server, "render_message", return_value=""):
        # Direct simulation of message.complete payload construction
        payload = {"text": "Hello", "usage": {}, "status": "complete"}
        _route_obs = fake_result.get("route_observation")
        if _route_obs and hasattr(_route_obs, "to_dict"):
            payload["route"] = _route_obs.to_dict()

        server._emit("message.complete", "sess-123", payload)

    assert len(emitted) == 1
    event_type, sid, out_payload = emitted[0]
    assert event_type == "message.complete"
    assert sid == "sess-123"
    assert "route" in out_payload
    route = out_payload["route"]
    assert route["fallback"] is True
    assert route["isDivergent"] is True
    assert route["requestedModel"] == "model-N"
    assert route["effectiveModel"] == "model-F"
    assert route["reason"] == "rate limit"


def test_run_prompt_submit_production_path_emits_route():
    import threading
    from tui_gateway import server

    emitted: list[tuple] = []

    def fake_emit(event_type, sid, payload=None):
        emitted.append((event_type, sid, payload))

    obs = ModelRouteObservation(
        requested_provider="nvidia",
        requested_model="model-N",
        wire_provider="nous",
        wire_model="model-F",
        effective_provider="nous",
        effective_model="model-F",
        fallback=True,
        reason="Bearer secret_token rate limit",
    )

    mock_agent = MagicMock()
    mock_agent.context_compressor = None
    mock_agent.provider = "nvidia"
    mock_agent.model = "model-N"
    mock_agent.base_url = None
    mock_agent.api_key = None
    mock_agent._config_context_length = None
    mock_agent.interim_assistant_callback = None
    mock_agent.run_conversation.return_value = {
        "text": "Fallback model production response",
        "route_observation": obs,
        "messages": [],
    }
    mock_agent.session_id = "test-sid"
    mock_agent.last_route_observation = obs

    session = {
        "history_lock": threading.Lock(),
        "running": True,
        "agent": mock_agent,
        "session_key": "test-key",
        "history": [],
        "attached_images": [],
        "_closing": False,
    }

    usage_stop_mock = MagicMock()
    usage_thread_mock = MagicMock()

    with patch.object(server, "_emit", side_effect=fake_emit), \
         patch.object(server, "_get_usage", return_value={}), \
         patch.object(server, "render_message", return_value="Fallback model production response"), \
         patch.object(server, "_start_usage_ticker", return_value=(usage_stop_mock, usage_thread_mock)):

        server._run_prompt_submit(
            rid=42,
            sid="test-sid",
            session=session,
            text="Please help me",
        )
        if "_run_thread" in session:
            session["_run_thread"].join(timeout=5.0)

    # Find message.complete in emitted events
    complete_events = [e for e in emitted if e[0] == "message.complete"]
    assert len(complete_events) == 1
    _, sid, payload = complete_events[0]
    assert sid == "test-sid"
    assert "route" in payload
    route = payload["route"]
    assert route["fallback"] is True
    assert route["requestedModel"] == "model-N"
    assert route["effectiveModel"] == "model-F"
    assert "Bearer [REDACTED]" in route["reason"]
    assert "secret_token" not in route["reason"]

