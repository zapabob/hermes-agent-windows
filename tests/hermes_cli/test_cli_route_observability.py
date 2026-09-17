"""Unit tests for CLI route observability UX (Slice G)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.model_route_observation import ModelRouteObservation


from rich.panel import Panel


def test_cli_chat_renders_exactly_one_panel_on_fallback():
    from cli import HermesCLI

    cli = HermesCLI(model="model-N")
    cli.session_id = "test-session"
    cli._ensure_runtime_credentials = MagicMock(return_value=True)

    def fake_init(*args, **kwargs):
        cli.agent = mock_agent
        return True

    cli._init_agent = fake_init

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
    mock_agent.max_iterations = 500
    mock_agent.run_conversation.return_value = {
        "final_response": "Hello from fallback model",
        "route_observation": obs,
        "messages": [],
        "completed": True,
    }
    mock_agent.last_route_observation = obs
    cli.agent = mock_agent

    panels_printed = []
    fake_console = MagicMock()

    def fake_print(*args, **kwargs):
        for a in args:
            if isinstance(a, Panel):
                panels_printed.append(a)

    fake_console.print.side_effect = fake_print

    with patch("cli.ChatConsole", return_value=fake_console), \
         patch("cli._cprint", return_value=None):
        cli.chat("hi")

    divergence_panels = [
        p for p in panels_printed
        if "Fallback" in str(p.title) or "drift" in str(p.title) or "⚠" in str(p.title)
    ]
    assert len(divergence_panels) == 1
    panel = divergence_panels[0]
    assert "Fallback active" in str(panel.title)
    assert "Requested: NVIDIA / model-N" in str(panel.renderable)
    assert "Using: Nous / model-F" in str(panel.renderable)
    assert "Reason: rate limit" in str(panel.renderable)


def test_cli_chat_renders_zero_panel_on_normal_route():
    from cli import HermesCLI

    cli = HermesCLI(model="claude-3-7-sonnet")
    cli.session_id = "test-session"
    cli._ensure_runtime_credentials = MagicMock(return_value=True)

    def fake_init(*args, **kwargs):
        cli.agent = mock_agent
        return True

    cli._init_agent = fake_init

    obs = ModelRouteObservation(
        requested_provider="anthropic",
        requested_model="claude-3-7-sonnet",
        wire_provider="anthropic",
        wire_model="claude-3-7-sonnet",
        effective_provider="anthropic",
        effective_model="claude-3-7-sonnet",
        fallback=False,
    )

    mock_agent = MagicMock()
    mock_agent.max_iterations = 500
    mock_agent.run_conversation.return_value = {
        "final_response": "Hello from Claude",
        "route_observation": obs,
        "messages": [],
        "completed": True,
    }
    mock_agent.last_route_observation = obs
    cli.agent = mock_agent

    panels_printed = []
    fake_console = MagicMock()

    def fake_print(*args, **kwargs):
        for a in args:
            if isinstance(a, Panel):
                panels_printed.append(a)

    fake_console.print.side_effect = fake_print

    with patch("cli.ChatConsole", return_value=fake_console), \
         patch("cli._cprint", return_value=None):
        cli.chat("hi")

    divergence_panels = [
        p for p in panels_printed
        if "Fallback" in str(p.title) or "drift" in str(p.title) or "⚠" in str(p.title)
    ]
    assert len(divergence_panels) == 0


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
