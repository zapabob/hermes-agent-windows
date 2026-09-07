"""Differential observable contracts for upstream Windows semantic carry.

These tests assert behavior, not source-tree parity with NousResearch/hermes-agent.
See docs/windows/UPSTREAM_SEMANTIC_CARRY_2026-09-08.md.
"""

from __future__ import annotations

import asyncio
import inspect
import types

import pytest

from hermes_cli.main import _fleet_probe_expected_runtimes
from hermes_cli.pty_session import PtySession
from hermes_cli.win_pty_bridge import WinPtyBridge


def _plan(runtimes):
    return types.SimpleNamespace(runtimes=runtimes)


class TestFleetRuntimeKindContract:
    def test_gateway_plan_expects_rows(self):
        assert (
            _fleet_probe_expected_runtimes(
                _plan([types.SimpleNamespace(kind="gateway")]),
                [],
                None,
                [],
                set(),
            )
            is True
        )

    def test_dashboard_and_serve_plans_do_not(self):
        for kind in ("dashboard", "serve"):
            assert (
                _fleet_probe_expected_runtimes(
                    _plan([types.SimpleNamespace(kind=kind)]),
                    [],
                    None,
                    [],
                    set(),
                )
                is False
            )

    def test_windows_resume_token_is_bookkeeping_only(self):
        token = {"resume_needed": True, "profiles": {"default": 1}}
        assert _fleet_probe_expected_runtimes(None, [], token, [], set()) is False


class TestConPtyWriteContract:
    def test_write_is_async_with_timeout(self):
        assert inspect.iscoroutinefunction(WinPtyBridge.write)
        assert "timeout" in inspect.signature(WinPtyBridge.write).parameters


@pytest.mark.asyncio
async def test_pty_session_generation_isolates_superseded_failures():
    class Bridge:
        def __init__(self):
            self.n = 0

        def read(self, timeout):
            return b""

        async def write(self, data, *, timeout: float = 10.0):
            self.n += 1
            return False

        def close(self):
            return None

    class WS:
        async def send_bytes(self, data):
            return None

        async def close(self, code=1000, reason=""):
            return None

    s = PtySession("k", Bridge(), buffer_cap=64, read_timeout=0.01)
    await s.start()
    a, b = WS(), WS()
    assert await s.attach(a) is True
    assert await s.attach(b) is True
    assert await s.write(a, b"old") is True
    assert s.alive is True
    assert await s.write(b, b"cur") is False
    assert s.alive is False
    await s.close()
