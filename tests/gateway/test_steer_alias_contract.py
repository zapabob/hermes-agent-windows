"""F03: Gateway shorthand preserves live steering and canonical access gates."""
import threading

import pytest

from agent.prompt_builder import format_steer_marker
from run_agent import AIAgent
from tests.gateway.test_steer_command import _make_event, _make_runner, _session_entry
from tests.gateway.test_slash_access_dispatch import (
    _make_event as access_event,
    _make_runner as access_runner,
    _make_source as access_source,
)


def _agent():
    agent = object.__new__(AIAgent)
    agent._pending_steer = None
    agent._pending_steer_lock = threading.Lock()
    agent._interrupt_requested = False
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/steer", "/s", "/S", "/s@owned_bot"])
async def test_gateway_alias_has_real_steer_effect(command):
    entry = _session_entry()
    runner, adapter = _make_runner(entry)
    agent = _agent()
    runner._running_agents[entry.session_key] = agent
    payload = "Check Auth.LOG 日本語"
    response = await runner._handle_message(_make_event(f"{command} {payload}"))
    assert response is not None
    messages = [{"role": "tool", "tool_call_id": "owned", "content": "tool output"}]
    agent._apply_pending_steer_to_tool_results(messages, 1)
    assert messages[0]["content"] == "tool output" + format_steer_marker(payload)
    assert agent._interrupt_requested is False
    assert runner._pending_messages == {}
    assert adapter._pending_messages == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("busy", [True, False])
@pytest.mark.parametrize("command", ["/steer", "/s", "/S"])
async def test_gateway_alias_cannot_bypass_canonical_acl(command, busy):
    runner = access_runner(platform_extra={
        "allow_admin_from": ["111"], "user_allowed_commands": [],
    })
    source = access_source(user_id="999")
    entry = runner.session_store.get_or_create_session.return_value
    agent = _agent()
    if busy:
        runner._running_agents[entry.session_key] = agent
    response = await runner._handle_message(access_event(f"{command} Not authorized", source))
    assert response is not None and "⛔" in response
    assert agent._drain_pending_steer() is None
    assert agent._interrupt_requested is False
    assert runner._pending_messages == {}
