"""Real save-lock ordering, additive memory sync and boundary availability."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import sys
import threading

import pytest

from hermes_cli import config as config_owner
from tests.gateway._approval_permanent_save_support import owned_config_scope as owned_config_scope
from tests.gateway import _approval_permanent_save_support as fixture
from tests.gateway import test_approval_permanent_save_ownership as oracles
from tests.gateway.test_approval_decision_ownership import (
    install_turns,
    isolated_approval_state as isolated_approval_state,
    until,
)
from tests.gateway.test_queued_followup_processing_hooks import SESSION_KEY
from tests.gateway.test_shared_input_run_ownership import ThreadBarrier
from tools import approval


@pytest.mark.asyncio
async def test_live_snapshot_is_created_after_real_outer_acquire(monkeypatch, tmp_path):
    path, seed = fixture.seed_owned_config(tmp_path, existing=True)
    _runner, turn, results, _adapter = install_turns(monkeypatch, tmp_path, 'plugin')
    gate = ThreadBarrier()
    delegate = approval._permanent_save_lock
    writes = oracles.observe_actual_writes(monkeypatch)

    class BeforeAcquire:
        first = True

        def __enter__(self):
            if self.first:
                self.first = False
                gate.wait()  # Before the actual A acquire, never while holding it.
            delegate.acquire()
            return self

        def __exit__(self, *args):
            delegate.release()

    monkeypatch.setattr(approval, '_permanent_save_lock', BeforeAcquire())
    a = asyncio.create_task(turn('old'))
    b = None
    try:
        entry_a = await fixture.pending(a)
        fixture.resolve(entry_a, 'always')
        await asyncio.wait_for(gate.entered.wait(), 6)
        b = asyncio.create_task(turn('new'))
        entry_b = await fixture.pending(b)
        fixture.resolve(entry_b, 'always')
        await asyncio.wait_for(b, 6)
        expected = {'owned-existing-consent', entry_a.data['pattern_key'], entry_b.data['pattern_key']}
        assert results['new']['approved']
        assert fixture.read_owned_config(path, seed) == expected
        gate.release.set()
        await asyncio.wait_for(a, 6)
        assert results['old']['approved']
        assert len(writes) == 2
        assert set(writes[-1]['patterns']) == expected, 'late-acquiring saver used an older pre-lock snapshot'
        assert fixture.read_owned_config(path, seed) == approval._permanent_approved == expected
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[t for t in (a, b) if t is not None], return_exceptions=True), 10)


@pytest.mark.asyncio
async def test_cli_sync_finishes_before_waiting_always_save(monkeypatch, tmp_path):
    path, seed = fixture.seed_owned_config(tmp_path, existing=True)
    _runner, turn, results, _adapter = install_turns(monkeypatch, tmp_path, 'plugin')
    gate = ThreadBarrier()
    observed, had_lock = oracles.observe_serialization(monkeypatch)
    assert had_lock
    real_sync = approval.load_permanent

    def sync(patterns):
        if sys._getframe(1).f_code.co_name == 'merge_permanent_allowlist':
            gate.wait()  # Immediately before the actual additive memory update.
        return real_sync(patterns)

    monkeypatch.setattr(approval, 'load_permanent', sync)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='owned-cli-sync')
    cli_pattern = 'owned-cli-sync *'
    a = oracles.start_cli(pool, cli_pattern)
    b = None
    try:
        await asyncio.wait_for(gate.entered.wait(), 6)
        assert cli_pattern not in approval._permanent_approved
        b = asyncio.create_task(turn('new'))
        entry = await fixture.pending(b)
        fixture.resolve(entry, 'always')
        pattern = entry.data['pattern_key']
        await until(lambda: pattern in approval._permanent_approved or b.done())
        await oracles.completion_or_contention(b, observed, path, seed, {'owned-existing-consent', pattern})
        gate.release.set()
        cli_return, _ = await asyncio.wait_for(asyncio.gather(a, b), 6)
        assert cli_pattern in cli_return and results['new']['approved']
        expected = {'owned-existing-consent', cli_pattern, pattern}
        assert approval._permanent_approved == expected
        assert fixture.read_owned_config(path, seed) == expected, 'CLI synced memory after another save had already lost its addition'
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[t for t in (a, b) if t is not None], return_exceptions=True), 10)
        pool.shutdown(wait=True)


@pytest.mark.asyncio
async def test_real_boundary_proceeds_during_disk_io_and_keeps_valid_always(monkeypatch, tmp_path):
    path, seed = fixture.seed_owned_config(tmp_path, existing=True)
    runner, turn, results, _adapter = install_turns(monkeypatch, tmp_path, 'plugin')
    gate = ThreadBarrier()
    oracles.observe_actual_writes(monkeypatch, pause_first=gate)
    a = asyncio.create_task(turn('current'))
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='owned-save-boundary')
    probe = None
    try:
        entry = await fixture.pending(a)
        fixture.resolve(entry, 'always')
        await asyncio.wait_for(gate.entered.wait(), 6)
        state = runner._session_state(SESSION_KEY)
        epoch = state.persistent.shared_input_epoch

        def boundary():
            state_free = state.shared_input_lock.acquire(blocking=False)
            if state_free:
                state.shared_input_lock.release()
            approval_free = approval._lock.acquire(blocking=False)
            if approval_free:
                approval._lock.release()
            changed = runner._clear_session_boundary_security_state(SESSION_KEY) if state_free and approval_free else False
            return state_free, approval_free, changed

        probe = asyncio.get_running_loop().run_in_executor(pool, boundary)
        state_free, approval_free, changed = await asyncio.wait_for(probe, 6)
        gate.release.set()
        await asyncio.wait_for(a, 6)
        assert state_free and approval_free, 'disk I/O held a Gateway owner or approval lock'
        assert changed and state.persistent.shared_input_epoch > epoch
        assert results['current']['approved']
        assert entry.data['pattern_key'] in approval._permanent_approved
        assert fixture.read_owned_config(path, seed) == {'owned-existing-consent', entry.data['pattern_key']}
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[t for t in (a, probe) if t is not None], return_exceptions=True), 10)
        pool.shutdown(wait=True)


def test_warning_only_save_failure_releases_lock_for_next_save(monkeypatch, tmp_path, caplog):
    path, seed = fixture.seed_owned_config(tmp_path, existing=True)
    real_save = config_owner.save_config

    def fail(payload, *args, **kwargs):
        raise OSError('owned injected persistence failure')

    monkeypatch.setattr(config_owner, 'save_config', fail)
    assert approval.save_permanent_allowlist({'owned-first *'}) is None
    assert 'Could not save allowlist' in caplog.text
    assert fixture.read_owned_config(path, seed) == {'owned-existing-consent'}
    monkeypatch.setattr(config_owner, 'save_config', real_save)
    assert approval.save_permanent_allowlist({'owned-next *'}) is None
    assert fixture.read_owned_config(path, seed) == {'owned-next *'}
