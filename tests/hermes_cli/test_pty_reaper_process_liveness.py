"""Exercise registry ownership independently from PTY EOF delivery."""

import asyncio

import pytest

from hermes_cli.pty_session import PtySession, PtySessionRegistry


class OwnedBridge:
    def __init__(self, alive=True):
        self.alive = alive
        self.closed = 0

    def is_alive(self):
        return self.alive

    def close(self):
        self.closed += 1


def registry():
    return PtySessionRegistry(ttl=30, max_sessions=8, buffer_cap=128, read_timeout=0.01)


def add(reg, key, bridge):
    session = PtySession(key, bridge, buffer_cap=128, read_timeout=0.01)
    reg._sessions[key] = session
    return session


@pytest.mark.asyncio
async def test_dead_child_without_eof_releases_slot():
    reg = registry()
    bridge = OwnedBridge(alive=False)
    session = add(reg, "dead", bridge)
    session.attached = True
    assert session.alive  # The drain has not observed EOF.
    await reg.reap_idle(now=0)
    assert "dead" not in reg._sessions
    assert bridge.closed == 1
    assert not session.alive


@pytest.mark.asyncio
async def test_concurrent_reaps_do_not_raise_or_close_sibling():
    reg = registry()
    entered, release = asyncio.Event(), asyncio.Event()
    first = add(reg, "first", OwnedBridge())
    second = add(reg, "second", OwnedBridge())
    sibling = add(reg, "live", OwnedBridge())
    first.alive = second.alive = False
    original_close = first.close

    async def gated_close():
        entered.set()
        await release.wait()
        await original_close()

    first.close = gated_close
    one = asyncio.create_task(reg.reap_idle(now=0))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        await reg.reap_idle(now=0)
    finally:
        release.set()
    await one
    assert reg._sessions == {"live": sibling}
    assert first.bridge.closed == second.bridge.closed == 1
    assert sibling.bridge.closed == 0
    await reg.close_all()


@pytest.mark.asyncio
async def test_live_attached_session_survives_reaper():
    reg = registry()
    bridge = OwnedBridge()
    session = add(reg, "live", bridge)
    session.attached = True
    session.last_detached_at = 0
    await reg.reap_idle(now=1000)
    assert reg._sessions["live"] is session
    assert bridge.closed == 0
    await reg.close_all()


@pytest.mark.asyncio
async def test_paused_reaper_does_not_close_replacement_with_same_key(monkeypatch):
    reg = registry()
    entered, release = asyncio.Event(), asyncio.Event()
    first = add(reg, "first", OwnedBridge())
    old = add(reg, "reused", OwnedBridge())
    first.alive = old.alive = False
    original_close = first.close

    async def gated_close():
        entered.set()
        await release.wait()
        await original_close()

    async def no_drain(self):
        pass

    monkeypatch.setattr(PtySession, "start", no_drain)
    first.close = gated_close
    pending = asyncio.create_task(reg.reap_idle(now=0))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        await reg.reap_idle(now=0)
        replacement, created = await reg.attach_or_spawn("reused", spawn=OwnedBridge)
        assert created
        replacement.attached = True
    finally:
        release.set()
    await pending
    assert reg._sessions.get("reused") is replacement
    assert replacement.alive
    assert replacement.bridge.closed == 0
    assert old.bridge.closed == 1
    await reg.close_all()


@pytest.mark.asyncio
async def test_bridge_without_liveness_keeps_legacy_eof_contract():
    reg = registry()
    class LegacyBridge:
        def close(self):
            pass
    session = add(reg, "legacy", LegacyBridge())
    await reg.reap_idle(now=0)
    assert reg._sessions["legacy"] is session
    await reg.close_all()


@pytest.mark.asyncio
async def test_paused_reaper_preserves_session_reattached_during_another_close():
    reg = registry()
    entered, release = asyncio.Event(), asyncio.Event()
    first = add(reg, "first", OwnedBridge())
    reattached = add(reg, "reattached", OwnedBridge())
    first.alive = False
    reattached.last_detached_at = 0
    original_close = first.close

    async def gated_close():
        entered.set()
        await release.wait()
        await original_close()

    class OwnedSocket:
        async def send_bytes(self, data):
            pass

    first.close = gated_close
    pending = asyncio.create_task(reg.reap_idle(now=100))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        assert await reattached.attach(OwnedSocket())
    finally:
        release.set()
    await pending
    assert reg._sessions.get("reattached") is reattached
    assert reattached.alive and reattached.bridge.closed == 0
    await reg.close_all()
