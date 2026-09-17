"""Unit tests for CLI route observability UX (Slice G)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.model_route_observation import ModelRouteObservation


def test_cli_chat_divergence_panel_on_fallback():
    from cli import HermesCLI

    cli = HermesCLI(model="model-N")
    cli.agent = MagicMock()

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
    cli.agent.last_route_observation = obs

    # Verify that ux_summary provides the expected strings
    summary = obs.ux_summary()
    assert summary["type"] == "fallback"
    assert "Requested: NVIDIA / model-N" in summary["lines"]
    assert "Using: Nous / model-F" in summary["lines"]
    assert "Reason: rate limit" in summary["lines"]


def test_cli_session_status_shows_route_divergence():
    from cli import HermesCLI

    cli = HermesCLI(model="model-N")
    cli.session_id = "test-session"
    cli.provider = "nvidia"
    cli.model = "model-N"

    mock_agent = MagicMock()
    mock_agent.session_total_tokens = 100
    mock_agent.reasoning_config = None
    mock_agent.last_route_observation = ModelRouteObservation(
        requested_provider="nvidia",
        requested_model="model-N",
        wire_provider="nous",
        wire_model="model-F",
        effective_provider="nous",
        effective_model="model-F",
        fallback=True,
        reason="rate limit",
    )
    cli.agent = mock_agent

    printed_lines = []

    def fake_print(text, **kwargs):
        printed_lines.append(text)

    with patch.object(cli, "_console_print", side_effect=fake_print):
        cli._show_session_status()

    output = "\n".join(printed_lines)
    assert "Model: model-N (nvidia)" in output
    assert "Route Status: Fallback active" in output
    assert "Requested: NVIDIA / model-N" in output
    assert "Using: Nous / model-F" in output
    assert "Reason: rate limit" in output


def test_cli_session_status_quiet_on_normal_route():
    from cli import HermesCLI

    cli = HermesCLI(model="claude-3-7-sonnet")
    cli.session_id = "test-session"
    cli.provider = "anthropic"
    cli.model = "claude-3-7-sonnet"

    mock_agent = MagicMock()
    mock_agent.session_total_tokens = 50
    mock_agent.reasoning_config = None
    mock_agent.last_route_observation = ModelRouteObservation(
        requested_provider="anthropic",
        requested_model="claude-3-7-sonnet",
        wire_provider="anthropic",
        wire_model="claude-3-7-sonnet",
        effective_provider="anthropic",
        effective_model="claude-3-7-sonnet",
        fallback=False,
    )
    cli.agent = mock_agent

    printed_lines = []

    def fake_print(text, **kwargs):
        printed_lines.append(text)

    with patch.object(cli, "_console_print", side_effect=fake_print):
        cli._show_session_status()

    output = "\n".join(printed_lines)
    assert "Model: claude-3-7-sonnet (anthropic)" in output
    assert "Route Status:" not in output
