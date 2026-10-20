"""A recovered trial consumes one stale attempt, in either native worker order."""
from __future__ import annotations

import http.server
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from tests.run_agent.test_stream_elapsed_clock import (
    test_native_stream_elapsed_clock as _native_clock_case,
)


@pytest.mark.parametrize("order", ["worker-after-abort", "worker-before-abort", "watchdog-first"])
def test_native_trial_stale_accounting_order(monkeypatch, record_property, order):
    """Keep the original real SDK fixture, exact count, and cleanup assertions."""
    from agent import chat_completion_helpers as helper
    from run_agent import AIAgent

    caller = threading.get_ident()
    settled, bumped, allow_cleanup = (threading.Event() for _ in range(3))
    trace, peer, barrier_failures = [], [], []
    actual_settle = helper._settle_stream_stale_trial
    actual_bump = helper._bump_stale_streak
    actual_abort = AIAgent._abort_request_openai_client
    actual_status = AIAgent._buffer_status
    actual_headers = http.server.BaseHTTPRequestHandler.send_response

    def wait(event, label):
        if not event.wait(8):
            barrier_failures.append(label)

    def headers(handler, *args, **kwargs):
        if handler.command == "POST":
            peer.append(handler.connection)
        return actual_headers(handler, *args, **kwargs)

    def settle(agent, response):
        is_worker_failure = threading.get_ident() != caller and response is None
        if is_worker_failure and order == "watchdog-first":
            wait(bumped, "watchdog did not account before worker settlement")
        result = actual_settle(agent, response)
        if is_worker_failure and result:
            trace.append(("worker-settled", agent._consecutive_stale_streams))
            settled.set()
            if order == "worker-before-abort":
                wait(allow_cleanup, "watchdog did not release worker cleanup")
        return result

    def bump(agent):
        trace.append(("watchdog-before-account", agent._consecutive_stale_streams))
        actual_bump(agent)
        trace.append(("watchdog-accounted", agent._consecutive_stale_streams))
        bumped.set()

    def abort(agent, client, *, reason):
        trace.append((reason, agent._consecutive_stale_streams))
        try:
            return actual_abort(agent, client, reason=reason)
        finally:
            if reason == "stale_stream_kill":
                allow_cleanup.set()
                if order == "worker-after-abort":
                    wait(settled, "real socket abort did not settle the SDK worker")

    def status(agent, message):
        result = actual_status(agent, message)
        if (order == "worker-before-abort" and peer
                and threading.get_ident() == caller and not settled.is_set()):
            # Close only this fixture's accepted POST socket. The watchdog is
            # paused before attempt cancellation/abort, while the real SDK
            # observes EOF and executes the real failed-trial settlement.
            trace.append(("owned-peer-eof", agent._consecutive_stale_streams))
            peer[-1].shutdown(socket.SHUT_RDWR)
            wait(settled, "owned peer EOF did not settle the SDK worker")
        return result

    monkeypatch.setattr(helper, "_settle_stream_stale_trial", settle)
    monkeypatch.setattr(helper, "_bump_stale_streak", bump)
    monkeypatch.setattr(AIAgent, "_abort_request_openai_client", abort)
    monkeypatch.setattr(AIAgent, "_buffer_status", status)
    monkeypatch.setattr(http.server.BaseHTTPRequestHandler, "send_response", headers)
    try:
        _native_clock_case(monkeypatch, record_property, "trial-stall")
    finally:
        allow_cleanup.set()
        record_property("accounting_order", order)
        record_property("accounting_trace", json.dumps(trace))
        assert not barrier_failures, barrier_failures
        assert settled.is_set() and bumped.is_set()
        names = [item[0] for item in trace]
        if order == "watchdog-first":
            assert names.index("watchdog-accounted") < names.index("worker-settled")
        else:
            assert names.index("worker-settled") < names.index("watchdog-before-account")
            if order == "worker-before-abort":
                assert names.index("worker-settled") < names.index("stale_stream_kill")


@pytest.mark.parametrize("trial", [None, ("previous-turn", 5)])
def test_ordinary_and_stale_turn_stales_keep_incrementing(trial):
    from agent import chat_completion_helpers as helper

    agent = SimpleNamespace(_current_turn_id="current-turn", _local_stale_trial=trial,
                            _consecutive_stale_streams=4)
    helper._bump_stale_streak(agent)
    assert agent._consecutive_stale_streams == 5
    helper._bump_stale_streak(agent)
    assert agent._consecutive_stale_streams == 6


def test_real_completion_clears_trial_and_restores_ordinary_accounting():
    from agent import chat_completion_helpers as helper

    agent = SimpleNamespace(_current_turn_id="current-turn",
                            _local_stale_trial=("current-turn", 5),
                            _consecutive_stale_streams=5)
    assert helper._settle_stream_stale_trial(agent, SimpleNamespace(id="completed")) is False
    assert agent._consecutive_stale_streams == 0
    assert agent._local_stale_trial is None
    helper._bump_stale_streak(agent)
    helper._bump_stale_streak(agent)
    assert agent._consecutive_stale_streams == 2
