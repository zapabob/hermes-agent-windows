"""Cancellation must retire a steer before tool or next-turn delivery."""
from copy import deepcopy
import threading

import pytest

from tests.run_agent.test_steer import _bare_agent
from tests.agent.test_turn_finalizer_interrupt_alternation import _StubAgent, _finalize


@pytest.mark.parametrize("producer", ["hard_interrupt", "interrupt"])
def test_explicit_stop_retires_pending_steer_and_rejects_late_arrivals(producer):
    agent = _bare_agent()
    agent._hard_interrupt_requested = threading.Event()
    assert agent.steer("cancelled instruction") is True

    if producer == "hard_interrupt":
        agent.hard_interrupt()
    else:
        agent.interrupt(hard_cancel=True)

    assert agent._drain_pending_steer() is None
    assert agent.steer("instruction arriving after stop") is False
    assert agent._drain_pending_steer() is None
    agent.clear_interrupt()
    assert agent.steer("still the stopped turn") is False
    agent._open_steer_turn()
    assert agent.steer("new turn instruction") is True
    assert agent._drain_pending_steer() == "new turn instruction"


def test_cancelled_steer_does_not_enter_persistable_tool_history():
    agent = _bare_agent()
    agent._hard_interrupt_requested = threading.Event()
    messages = [{"role": "assistant", "tool_calls": [{"id": "owned"}]},
                {"role": "tool", "tool_call_id": "owned", "content": "cancelled tool output"}]
    before = deepcopy(messages)
    assert agent.steer("must not reach a resumed conversation")
    agent.hard_interrupt()

    agent._apply_pending_steer_to_tool_results(messages, 1)

    assert messages == before
    assert agent._drain_pending_steer() is None


@pytest.mark.parametrize("has_tool", [True, False])
def test_stop_after_drain_cannot_commit_history_or_restore_the_slot(monkeypatch, has_tool):
    agent = _bare_agent()
    agent._hard_interrupt_requested = threading.Event()
    assert agent.steer("taken before stop")
    drain = agent._drain_pending_steer

    def stop_after_take():
        text = drain()
        agent.hard_interrupt()
        return text

    monkeypatch.setattr(agent, "_drain_pending_steer", stop_after_take)
    messages = [{"role": "tool" if has_tool else "assistant", "content": "owned content"}]
    before = deepcopy(messages)

    agent._apply_pending_steer_to_tool_results(messages, 1)

    assert messages == before
    assert drain() is None


def test_declined_liveness_claim_does_not_retire_pending_guidance():
    agent = _bare_agent()
    agent._hard_interrupt_requested = threading.Event()
    agent._turn_liveness_activity_generation = 2
    assert agent.steer("still authorized")

    assert agent.interrupt(hard_cancel=True, require_generation=1) is False

    assert getattr(agent, "_steer_cancel_generation", 0) == 0
    assert not agent._hard_interrupt_requested.is_set()
    assert agent._drain_pending_steer() == "still authorized"


@pytest.mark.parametrize("interrupted,hard_stop", [(True, True), (False, True), (True, False), (False, False)])
def test_finalizer_only_transfers_steer_from_a_turn_without_a_hard_stop(interrupted, hard_stop):
    agent = _StubAgent()
    agent._interrupt_requested = interrupted or hard_stop
    agent._hard_interrupt_requested = threading.Event()
    if hard_stop:
        agent._hard_interrupt_requested.set()
    agent._drain_pending_steer = lambda: "owned leftover instruction"

    result = _finalize(agent, [{"role": "user", "content": "owned question"},
                               {"role": "assistant", "content": "owned response"}],
                       interrupted=interrupted, final_response="owned response")

    if hard_stop:
        assert not result.get("pending_steer")
    else:
        assert result["pending_steer"] == "owned leftover instruction"
