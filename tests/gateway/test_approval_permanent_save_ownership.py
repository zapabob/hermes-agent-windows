"""Real permanent-save callers: concurrency REDs and useful scope controls."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import contextvars
import json
import threading

import pytest

from hermes_cli import approvals_suggest, config as config_owner
from tests.gateway._approval_permanent_save_support import owned_config_scope as owned_config_scope
from tests.gateway import _approval_permanent_save_support as config_fixture
from tests.gateway.test_approval_decision_ownership import (
    install_turns,
    isolated_approval_state as isolated_approval_state,
    until,
)
from tests.gateway.test_queued_followup_processing_hooks import SESSION_KEY
from tests.gateway.test_shared_input_run_ownership import ThreadBarrier
from tools import approval


class ObservedSaveLock:
    """Observe a real failed acquire; an unused baseline observer changes nothing."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.contended = threading.Event()
        self.attempts = []

    def __enter__(self):
        acquired = self.delegate.acquire(blocking=False)
        self.attempts.append({'thread': threading.get_ident(), 'acquired': acquired})
        if not acquired:
            self.contended.set()
            self.delegate.acquire()
        return self

    def __exit__(self, *args):
        self.delegate.release()


def observe_serialization(monkeypatch):
    existing = getattr(approval, '_permanent_save_lock', None)
    observed = ObservedSaveLock(existing if existing is not None else threading.RLock())
    monkeypatch.setattr(approval, '_permanent_save_lock', observed, raising=False)
    return observed, existing is not None


def observe_actual_writes(monkeypatch, *, pause_first=None):
    real_save = config_owner.save_config
    calls = []

    def write(payload, *args, **kwargs):
        patterns = sorted(payload['command_allowlist'])
        calls.append({'thread': threading.get_ident(), 'patterns': patterns,
                      'payload_id': id(payload)})
        if len(calls) == 1 and pause_first is not None:
            pause_first.wait()
            assert sorted(payload['command_allowlist']) == patterns
        # Delegate the identical actual helper payload to the actual writer.
        return real_save(payload, *args, **kwargs)

    monkeypatch.setattr(config_owner, 'save_config', write)
    return calls


def pause_after_real_load(monkeypatch, gate):
    real_load = approval.load_permanent_allowlist
    loads = []
    first_lock = threading.Lock()

    def load():
        patterns = real_load()
        with first_lock:
            first = not loads
            loads.append({'thread': threading.get_ident(), 'patterns': sorted(patterns)})
        if first:
            gate.wait()
        return patterns

    monkeypatch.setattr(approval, 'load_permanent_allowlist', load)
    return loads


def apply(pattern):
    return approvals_suggest.apply_proposals(
        [approvals_suggest.Proposal(pattern=pattern, kind='glob')], [0],
    )


def start_cli(pool, pattern):
    return asyncio.get_running_loop().run_in_executor(
        pool, contextvars.Context().run, apply, pattern,
    )


async def completion_or_contention(task, observed, path, seed, expected_saved):
    await until(lambda: task.done() or observed.contended.is_set())
    if task.done():
        await task  # Propagate setup/worker exceptions, never call them lost update.
        assert config_fixture.read_owned_config(path, seed) == expected_saved
        return 'B actual save completed before A release'
    assert observed.contended.is_set() and not task.done()
    return 'B real save-lock acquire contended before A release'


def record(tmp_path, *, schedule, writes, expected, actual, observed, had_lock,
           cli_results=None, loads=None, gateway_results=None):
    (tmp_path / 'permanent-save-observations.json').write_text(json.dumps({
        'schedule': schedule, 'had_production_save_lock': had_lock,
        'actual_lock_attempts': observed.attempts,
        'actual_writer_payloads': writes, 'actual_cli_loads': loads,
        'expected': sorted(expected), 'actual_disk_and_readback': sorted(actual),
        'actual_memory': sorted(approval._permanent_approved),
        'cli_results': [sorted(value) for value in (cli_results or [])],
        'gateway_results': gateway_results,
        'qualification': 'actual public owners, real resolver choices, config writer and YAML/load readback; no fabricated decision or payload',
    }, indent=2) + '\n', encoding='utf-8')


@pytest.mark.asyncio
async def test_gateway_always_saves_cannot_lose_completed_grant(monkeypatch, tmp_path):
    path, seed = config_fixture.seed_owned_config(tmp_path, existing=True)
    _runner, turn, results, _adapter = install_turns(monkeypatch, tmp_path, 'plugin')
    gate = ThreadBarrier()
    observed, had_lock = observe_serialization(monkeypatch)
    writes = observe_actual_writes(monkeypatch, pause_first=gate)
    a = asyncio.create_task(turn('old'))
    b = None
    try:
        a_entry = await config_fixture.pending(a)
        a_pattern = a_entry.data['pattern_key']
        config_fixture.resolve(a_entry, 'always')
        await asyncio.wait_for(gate.entered.wait(), 6)
        assert set(writes[0]['patterns']) == {'owned-existing-consent', a_pattern}
        b = asyncio.create_task(turn('new'))
        b_entry = await config_fixture.pending(b)
        b_pattern = b_entry.data['pattern_key']
        assert b_pattern != a_pattern
        expected = {'owned-existing-consent', a_pattern, b_pattern}
        config_fixture.resolve(b_entry, 'always')
        await until(lambda: b_pattern in approval._permanent_approved or b.done())
        assert approval._permanent_approved == expected
        schedule = await completion_or_contention(b, observed, path, seed, expected)
        gate.release.set()
        await asyncio.wait_for(asyncio.gather(a, b), 6)
        assert results['old']['approved'] and results['new']['approved']
        assert len(writes) == 2 and approval._permanent_approved == expected
        actual = config_fixture.read_owned_config(path, seed)
        record(tmp_path, schedule=schedule, writes=writes, expected=expected,
               actual=actual, observed=observed, had_lock=had_lock, gateway_results=results)
        assert actual == expected, 'BEHAVIORAL LOST UPDATE: older Gateway save erased completed ALWAYS grant'
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[task for task in (a, b) if task is not None],
                                              return_exceptions=True), 10)


@pytest.mark.asyncio
async def test_cli_addition_cannot_erase_gateway_always(monkeypatch, tmp_path):
    path, seed = config_fixture.seed_owned_config(tmp_path, existing=True)
    _runner, turn, results, _adapter = install_turns(monkeypatch, tmp_path, 'plugin')
    gate = ThreadBarrier()
    observed, had_lock = observe_serialization(monkeypatch)
    loads = pause_after_real_load(monkeypatch, gate)
    writes = observe_actual_writes(monkeypatch)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='owned-cli-a')
    cli_pattern = 'owned-cli-a *'
    a = start_cli(pool, cli_pattern)
    b = None
    try:
        await asyncio.wait_for(gate.entered.wait(), 6)
        assert set(loads[0]['patterns']) == {'owned-existing-consent'}
        b = asyncio.create_task(turn('new'))
        entry = await config_fixture.pending(b)
        gateway_pattern = entry.data['pattern_key']
        config_fixture.resolve(entry, 'always')
        await until(lambda: gateway_pattern in approval._permanent_approved or b.done())
        expected_b = {'owned-existing-consent', gateway_pattern}
        assert approval._permanent_approved == expected_b
        schedule = await completion_or_contention(b, observed, path, seed, expected_b)
        gate.release.set()
        cli_return, _ = await asyncio.wait_for(asyncio.gather(a, b), 6)
        assert results['new']['approved'] and cli_pattern in cli_return
        expected = expected_b | {cli_pattern}
        assert len(writes) == 2 and approval._permanent_approved == expected
        actual = config_fixture.read_owned_config(path, seed)
        record(tmp_path, schedule=schedule, writes=writes, expected=expected,
               actual=actual, observed=observed, had_lock=had_lock, loads=loads,
               cli_results=[cli_return], gateway_results=results)
        assert actual == expected, 'BEHAVIORAL LOST UPDATE: copied CLI addition erased completed Gateway ALWAYS grant'
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[task for task in (a, b) if task is not None],
                                              return_exceptions=True), 10)
        pool.shutdown(wait=True)


@pytest.mark.asyncio
async def test_parallel_cli_additions_preserve_both(monkeypatch, tmp_path):
    path, seed = config_fixture.seed_owned_config(tmp_path, existing=True)
    gate = ThreadBarrier()
    observed, had_lock = observe_serialization(monkeypatch)
    loads = pause_after_real_load(monkeypatch, gate)
    writes = observe_actual_writes(monkeypatch)
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='owned-cli-pair')
    a_pattern, b_pattern = 'owned-cli-a *', 'owned-cli-b *'
    a = start_cli(pool, a_pattern)
    b = None
    try:
        await asyncio.wait_for(gate.entered.wait(), 6)
        assert set(loads[0]['patterns']) == {'owned-existing-consent'}
        b = start_cli(pool, b_pattern)
        expected_b = {'owned-existing-consent', b_pattern}
        schedule = await completion_or_contention(b, observed, path, seed, expected_b)
        gate.release.set()
        a_return, b_return = await asyncio.wait_for(asyncio.gather(a, b), 6)
        assert a_pattern in a_return and b_pattern in b_return
        expected = expected_b | {a_pattern}
        assert len(writes) == 2 and approval._permanent_approved == expected
        actual = config_fixture.read_owned_config(path, seed)
        record(tmp_path, schedule=schedule, writes=writes, expected=expected,
               actual=actual, observed=observed, had_lock=had_lock, loads=loads,
               cli_results=[a_return, b_return])
        assert actual == expected, 'BEHAVIORAL LOST UPDATE: copied CLI addition erased another completed CLI addition'
    finally:
        gate.release.set()
        await asyncio.wait_for(asyncio.gather(*[task for task in (a, b) if task is not None],
                                              return_exceptions=True), 10)
        pool.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['always', 'once', 'session'])
async def test_single_real_choice_preserves_scope(monkeypatch, tmp_path, choice):
    path, seed = config_fixture.seed_owned_config(tmp_path, existing=True)
    _runner, turn, results, _adapter = install_turns(monkeypatch, tmp_path, 'plugin')
    task = asyncio.create_task(turn('current'))
    try:
        entry = await config_fixture.pending(task)
        pattern = entry.data['pattern_key']
        config_fixture.resolve(entry, choice)
        await asyncio.wait_for(task, 6)
        assert results['current']['approved']
        assert (pattern in approval._session_approved.get(SESSION_KEY, set())) == (choice != 'once')
        assert (pattern in approval._permanent_approved) == (choice == 'always')
        expected = {'owned-existing-consent'} | ({pattern} if choice == 'always' else set())
        assert config_fixture.read_owned_config(path, seed) == expected
    finally:
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)


@pytest.mark.parametrize('replacement', [set(), {'owned-replacement *'}], ids=['empty', 'exact-set'])
def test_explicit_replacement_is_not_union(tmp_path, replacement):
    path, seed = config_fixture.seed_owned_config(tmp_path, existing=True)
    approval.load_permanent({'owned-memory-only *'})
    memory_before = set(approval._permanent_approved)
    assert approval.save_permanent_allowlist(replacement) is None
    assert config_fixture.read_owned_config(path, seed) == replacement
    assert approval._permanent_approved == memory_before


def test_cli_addition_does_not_resurrect_disk_deletion(tmp_path):
    path, seed = config_fixture.seed_owned_config(tmp_path, existing=True)
    assert 'owned-existing-consent' in approval._permanent_approved
    approval.save_permanent_allowlist(set())
    assert config_fixture.read_owned_config(path, seed) == set()
    returned = apply('owned-cli-new *')
    assert returned == {'owned-cli-new *'}
    assert config_fixture.read_owned_config(path, seed) == returned
    # Existing memory revocation is separate and remains OPEN.
    assert approval._permanent_approved == {'owned-existing-consent', 'owned-cli-new *'}


def test_sequential_cli_returns_merge_and_preserves_useful_config(monkeypatch, tmp_path):
    path, seed = config_fixture.seed_owned_config(tmp_path, existing=True)
    writes = observe_actual_writes(monkeypatch)
    first = apply('owned-cli-a *')
    assert first == {'owned-existing-consent', 'owned-cli-a *'}
    assert config_fixture.read_owned_config(path, seed) == first
    second = apply('owned-cli-b *')
    assert second == first | {'owned-cli-b *'}
    assert first == {'owned-existing-consent', 'owned-cli-a *'}
    assert config_fixture.read_owned_config(path, seed) == approval._permanent_approved == second
    assert len(writes) == 2
