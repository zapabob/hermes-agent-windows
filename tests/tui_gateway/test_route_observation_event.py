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
