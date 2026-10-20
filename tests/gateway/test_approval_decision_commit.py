"""Real caller commit ordering and mixed-warning permanent scope controls."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import contextvars
import threading

import pytest
import yaml

from hermes_constants import get_hermes_home
from tests.gateway import test_approval_decision_ownership as fixture_owner
from tests.gateway.test_approval_decision_ownership import (
    isolated_approval_state as isolated_approval_state,
    until,
)
from tests.gateway.test_queued_followup_processing_hooks import SESSION_KEY
from tests.gateway.test_shared_input_run_ownership import ThreadBarrier
from tools import approval


class ObservedLock:
    """Delegate to the real lock, observing a contender's actual first acquire."""
    def __init__(self, delegate):
        self.delegate = delegate
        self.contender = None
        self.probed = threading.Event()
        self.first_acquired = None

    def __enter__(self):
        if threading.get_ident() == self.contender and self.first_acquired is None:
            acquired = self.delegate.acquire(blocking=False)
            self.first_acquired = acquired
            self.probed.set()
            if not acquired:
                self.delegate.acquire()
        else:
            self.delegate.acquire()
        return self

    def __exit__(self, *args):
        self.delegate.release()


@pytest.mark.asyncio
@pytest.mark.parametrize('contender', ['true-boundary', 'exact-unregister'])
async def test_actual_caller_commit_serializes_boundary_and_retirement(monkeypatch, tmp_path, contender):
    # This test deliberately parks a lock-owning caller. Keep unrelated UI
    # consumers from blocking its event-loop controller on that same lock.
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump({
        'display': {'platforms': {'telegram': {
            'streaming': False, 'interim_assistant_messages': False,
            'tool_progress': 'off', 'thinking_progress': False,
        }}},
    }), encoding='utf-8')
    runner, turn, results, _adapter = fixture_owner.install_turns(monkeypatch, tmp_path, 'plugin')
    gate = ThreadBarrier()
    state = runner._session_state(SESSION_KEY)
    observed = ObservedLock(state.shared_input_lock if contender == 'true-boundary' else approval._lock)
    if contender == 'true-boundary':
        monkeypatch.setattr(state, 'shared_input_lock', observed)
    else:
        monkeypatch.setattr(approval, '_lock', observed)
    registration = {}

    class PausedSessionGrants(dict):
        def setdefault(self, *args, **kwargs):
            registration['a'] = approval.get_gateway_approval_registration()
            gate.wait()  # Actual helper reached its actual first session write.
            return super().setdefault(*args, **kwargs)

    monkeypatch.setattr(approval, '_session_approved', PausedSessionGrants())
    task = asyncio.create_task(turn('current'))
    pending_contender = None
    contender_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='approval-commit-contender')
    try:
        await until(lambda: bool(approval._gateway_queues.get(SESSION_KEY)) or task.done())
        assert not task.done()
        entry = approval._gateway_queues[SESSION_KEY][0]
        pattern = entry.data['pattern_key']
        assert approval.resolve_gateway_approval(SESSION_KEY, 'session', request_id=entry.data['request_id']) == 1
        await asyncio.wait_for(gate.entered.wait(), 6)
        epoch = state.persistent.shared_input_epoch

        def compete():
            observed.contender = threading.get_ident()
            if contender == 'true-boundary':
                return runner._clear_session_boundary_security_state(SESSION_KEY)
            return approval.unregister_gateway_notify(SESSION_KEY, registration=registration['a'])

        pending_contender = asyncio.get_running_loop().run_in_executor(
            contender_pool, contextvars.Context().run, compete,
        )
        await until(lambda: observed.probed.is_set() or pending_contender.done())
        if pending_contender.done():
            await pending_contender
        assert observed.first_acquired is False, 'boundary/retirement acquired its real lock during caller commit'
        assert state.persistent.shared_input_epoch == epoch
        assert registration['a'].active
        gate.release.set()
        await asyncio.wait_for(asyncio.gather(task, pending_contender), 6)
        assert results['current']['approved']
        if contender == 'true-boundary':
            assert state.persistent.shared_input_epoch > epoch
            assert not approval.is_approved(SESSION_KEY, pattern)
        else:
            assert not registration['a'].active
            assert approval.is_approved(SESSION_KEY, pattern)
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[t for t in (task, pending_contender) if t is not None], return_exceptions=True), 10)
        contender_pool.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('pure_tirith', [False, True])
async def test_actual_combined_always_preserves_scope_and_save_count(monkeypatch, tmp_path, pure_tirith):
    from tools import tirith_security

    _runner, turn, results, _adapter = fixture_owner.install_turns(monkeypatch, tmp_path, 'combined')
    monkeypatch.setattr(tirith_security, 'check_command_security', lambda command: {
        'action': 'warn', 'summary': 'owned warning', 'findings': [{'rule_id': 'owned-tirith'}],
    })
    monkeypatch.setattr(approval, 'detect_dangerous_command',
                        lambda command: (not pure_tirith, 'owned-danger', 'owned dangerous warning'))
    saves = []
    real_save = approval.save_permanent_allowlist

    def observe_save(patterns):
        saves.append(set(patterns))
        return real_save(patterns)

    monkeypatch.setattr(approval, 'save_permanent_allowlist', observe_save)
    task = asyncio.create_task(turn('current'))
    try:
        await until(lambda: bool(approval._gateway_queues.get(SESSION_KEY)) or task.done())
        assert not task.done()
        entry = approval._gateway_queues[SESSION_KEY][0]
        keys = set(entry.data['pattern_keys'])
        assert len(keys) == (1 if pure_tirith else 2)
        assert entry.data['allow_permanent'] is (not pure_tirith)
        assert approval.resolve_gateway_approval(SESSION_KEY, 'always', request_id=entry.data['request_id']) == 1
        await asyncio.wait_for(task, 6)
        assert results['current']['approved'] and results['current']['user_approved']
        assert keys <= approval._session_approved[SESSION_KEY]
        assert approval._permanent_approved == (set() if pure_tirith else {'owned-danger'})
        assert len(saves) == (0 if pure_tirith else 1)
        if not pure_tirith:
            disk = yaml.safe_load((get_hermes_home() / 'config.yaml').read_text(encoding='utf-8'))
            assert set(disk['command_allowlist']) == {'owned-danger'}
    finally:
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)
