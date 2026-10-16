"""F03: public shorthand dispatch must retain the existing steer effect."""
from __future__ import annotations

from copy import deepcopy
from queue import Queue
import threading

import pytest

from cli import HermesCLI
from hermes_cli.commands import resolve_command
from agent.prompt_builder import format_steer_marker
from run_agent import AIAgent


def _surface(*, busy: bool):
    # No provider, DB or UI process is needed for this public command handler.
    agent = object.__new__(AIAgent)
    agent._pending_steer = None
    agent._pending_steer_lock = threading.Lock()
    agent._interrupt_requested = False
    surface = object.__new__(HermesCLI)
    surface._agent_running = busy
    surface.agent = agent
    surface._pending_input = Queue()
    return surface, agent


@pytest.mark.parametrize("command", ["/steer", "/s", "/S"])
def test_busy_alias_delivers_once_at_tool_boundary(command):
    surface, agent = _surface(busy=True)
    payload = "Check Auth.LOG and 日本語"
    assert surface._should_handle_steer_command_inline(f"{command} {payload}")
    messages = [
        {"role": "system", "content": "Fixed prefix"},
        {"role": "user", "content": "Initial request"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "owned"}]},
        {"role": "tool", "tool_call_id": "owned", "content": "Actual tool result"},
    ]
    before = deepcopy(messages)
    assert surface.process_command(f"{command} {payload}") is True
    assert messages == before
    assert surface._pending_input.empty()
    assert agent._interrupt_requested is False
    agent._apply_pending_steer_to_tool_results(messages, 1)
    assert messages[:-1] == before[:-1]
    assert messages[-1] == {**before[-1], "content": before[-1]["content"] + format_steer_marker(payload)}
    delivered = deepcopy(messages)
    agent._apply_pending_steer_to_tool_results(messages, 1)
    assert messages == delivered
    assert agent._drain_pending_steer() is None


@pytest.mark.parametrize("command", ["/steer", "/s", "/S"])
def test_idle_alias_preserves_existing_fifo(command):
    surface, agent = _surface(busy=False)
    assert resolve_command(command[1:]) is not None
    surface._pending_input.put("Earlier queued request")
    assert surface._should_handle_steer_command_inline(f"{command} Keep Case") is False
    assert surface.process_command(f"{command} Keep Case") is True
    assert surface._pending_input.get_nowait() == "Earlier queued request"
    assert surface._pending_input.get_nowait() == "Keep Case"
    assert surface._pending_input.empty()
    assert agent._drain_pending_steer() is None


@pytest.mark.parametrize("busy", [True, False])
@pytest.mark.parametrize("command", ["/steer", "/s"])
def test_empty_alias_has_no_effect(command, busy):
    surface, agent = _surface(busy=busy)
    assert resolve_command(command[1:]) is not None
    assert surface.process_command(command + "   ") is True
    assert surface._pending_input.empty()
    assert agent._drain_pending_steer() is None


def test_image_and_plain_text_inputs_do_not_use_inline_alias():
    surface, _ = _surface(busy=True)
    assert surface._should_handle_steer_command_inline("/s image", has_images=True) is False
    assert surface._should_handle_steer_command_inline("s ordinary input") is False
