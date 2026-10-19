"""Post-decision ownership: real Gateway wait, boundary and caller persistence."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import contextvars
import threading

import pytest

from gateway.platforms.base import SendResult
from gateway.session_context import clear_session_vars, set_session_vars
from tests.gateway.test_queued_followup_processing_hooks import (
    HookRecordingAdapter,
    SESSION_KEY,
    _install_fake_agent,
    _make_runner,
    _source,
)
from tests.gateway.test_shared_input_run_ownership import ThreadBarrier
from tools import approval


async def until(predicate) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), 6)


@pytest.fixture(autouse=True)
def isolated_approval_state(monkeypatch):
    """Select builtin manual policy; never replace a human decision or owner."""
    with approval._lock:
        saved_permanent = set(approval._permanent_approved)
        approval._permanent_approved.clear()
        approval._session_approved.clear()
        approval._denial_tally.clear()
        approval._gateway_queues.clear()
        approval._gateway_notify_cbs.clear()
    monkeypatch.setattr(approval, '_YOLO_MODE_FROZEN', False)
    monkeypatch.setattr(approval, '_get_approval_mode', lambda: 'manual')
    monkeypatch.setattr(approval, '_get_approval_transport_config', lambda: ('builtin', None))
    # Classification leaves force an inert warning; the decision, queue,
    # persistence and current-session checks remain the actual public owners.
    import tools.tirith_security as tirith
    monkeypatch.setattr(tirith, 'check_command_security',
                        lambda command: {'action': 'allow', 'findings': [], 'summary': ''})
    monkeypatch.setattr(approval, 'detect_dangerous_command',
                        lambda command: (True, 'owned-warning:' + command, 'inert fixture warning'))
    yield
    approval.unregister_gateway_notify(SESSION_KEY)
    with approval._lock:
        approval._permanent_approved.clear()
        approval._permanent_approved.update(saved_permanent)
        approval._session_approved.clear()
        approval._denial_tally.clear()


class Adapter(HookRecordingAdapter):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.presented = threading.Event()

    async def send_exec_approval(self, chat_id, command, session_key, **kwargs) -> SendResult:
        self.sent.append(command)
        self.presented.set()
        return SendResult(success=True, message_id=command)


def public_guard(kind, label):
    if kind == 'plugin':
        return approval.request_tool_approval(label + '-inert-tool', 'owned fixture')
    if kind == 'combined':
        return approval.check_all_command_guards('owned inert command ' + label, 'local')
    assert kind == 'execute'
    return approval.check_execute_code_guard('owned_value = ' + repr(label), 'local')


def install_turns(monkeypatch, tmp_path, kind, *, new_denials=False, parallel=None):
    adapter = Adapter()
    runner = _make_runner(adapter)
    results = {}

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            assert approval._is_gateway_approval_context(), 'real Gateway context was not bound'
            assert approval.get_gateway_approval_registration() is not None
            if message == 'parallel':
                with ThreadPoolExecutor(max_workers=3) as pool:
                    first = pool.submit(contextvars.copy_context().run, public_guard, 'plugin', 'first')
                    assert adapter.presented.wait(5), 'leader was never displayed'
                    others = [pool.submit(contextvars.copy_context().run, public_guard, 'plugin',
                              'first' if parallel == 'identical' else 'next-' + str(index)) for index in range(2)]
                    results[message] = [f.result(timeout=8) for f in [first, *others]]
            else:
                results[message] = public_guard('plugin' if message == 'new' else kind, message)
                if message == 'new' and new_denials:
                    assert [approval._record_denial(SESSION_KEY) for _ in range(3)] == [1, 2, 3]
            return {'final_response': 'inert reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    runner._begin_session_run_generation(SESSION_KEY)

    async def turn(message):
        tokens = set_session_vars(platform='telegram', chat_id='4242', cron_session='')
        try:
            return await runner._run_agent(message=message, context_prompt='', history=[], source=_source(),
                session_id='owned-session', session_key=SESSION_KEY,
                run_generation=runner._session_state(SESSION_KEY).persistent.run_generation)
        finally:
            clear_session_vars(tokens)

    return runner, turn, results, adapter


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,observation', [
    ('plugin', 'pattern'), ('combined', 'pattern'), ('execute', 'pattern'),
    ('combined', 'denials'), ('execute', 'denials'),
])
async def test_retired_caller_cannot_publish_after_true_boundary(monkeypatch, tmp_path, kind, observation):
    runner, turn, results, _adapter = install_turns(monkeypatch, tmp_path, kind, new_denials=True)
    gate = ThreadBarrier()
    real_wait = approval._await_gateway_decision
    decisions = {}
    first = True

    def wait_then_pause(key, callback, payload, **kwargs):
        nonlocal first
        is_old = first
        first = False
        decision = real_wait(key, callback, payload, **kwargs)
        if is_old:
            # This is AFTER the actual wait's last current-owner check. The
            # actual returned decision is preserved byte-for-byte in content.
            assert approval.get_gateway_approval_registration().is_current()
            decisions['old'] = dict(decision)
            gate.wait()
        return decision

    monkeypatch.setattr(approval, '_await_gateway_decision', wait_then_pause)
    old = asyncio.create_task(turn('old'))
    new = None
    try:
        await until(lambda: bool(approval._gateway_queues.get(SESSION_KEY)) or old.done())
        assert not old.done(), 'public caller bypassed the real approval wait'
        old_entry = approval._gateway_queues[SESSION_KEY][0]
        old_pattern = old_entry.data['pattern_key']
        assert approval.resolve_gateway_approval(SESSION_KEY, 'session', request_id=old_entry.data['request_id']) == 1
        await asyncio.wait_for(gate.entered.wait(), 6)
        assert decisions['old']['resolved'] and decisions['old']['choice'] == 'session'
        assert not approval.is_approved(SESSION_KEY, old_pattern)
        epoch = runner._session_state(SESSION_KEY).persistent.shared_input_epoch
        generation = runner._session_state(SESSION_KEY).persistent.run_generation
        assert runner._clear_session_boundary_security_state(SESSION_KEY)
        assert runner._session_state(SESSION_KEY).persistent.shared_input_epoch > epoch
        assert runner._session_state(SESSION_KEY).persistent.run_generation == generation
        new = asyncio.create_task(turn('new'))
        await until(lambda: bool(approval._gateway_queues.get(SESSION_KEY)) or new.done())
        assert not new.done(), 'replacement caller bypassed approval'
        new_entry = approval._gateway_queues[SESSION_KEY][0]
        new_pattern = new_entry.data['pattern_key']
        assert new_pattern != old_pattern
        assert approval.resolve_gateway_approval(SESSION_KEY, 'session', request_id=new_entry.data['request_id']) == 1
        await asyncio.wait_for(new, 6)
        assert results['new']['approved'] and approval.is_approved(SESSION_KEY, new_pattern)
        assert approval._denial_tally[SESSION_KEY] == 3
        gate.release.set()
        await asyncio.wait_for(old, 6)
        assert approval.is_approved(SESSION_KEY, new_pattern), 'old caller damaged the current session grant'
        if observation == 'pattern':
            assert not approval.is_approved(SESSION_KEY, old_pattern), 'retired caller restored its pattern after true boundary'
        else:
            assert approval._denial_tally.get(SESSION_KEY) == 3, 'retired caller cleared replacement denial tally'
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[t for t in (old, new) if t is not None], return_exceptions=True), 10)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['plugin', 'combined', 'execute'])
@pytest.mark.parametrize('choice', ['session', 'once', 'always'])
async def test_current_caller_keeps_legitimate_scope(monkeypatch, tmp_path, kind, choice):
    from hermes_constants import get_hermes_home
    import yaml

    runner, turn, results, _adapter = install_turns(monkeypatch, tmp_path, kind)
    task = asyncio.create_task(turn('current'))
    try:
        await until(lambda: bool(approval._gateway_queues.get(SESSION_KEY)) or task.done())
        assert not task.done(), 'current caller did not request real approval'
        entry = approval._gateway_queues[SESSION_KEY][0]
        pattern = entry.data['pattern_key']
        assert approval.resolve_gateway_approval(SESSION_KEY, choice, request_id=entry.data['request_id']) == 1
        await asyncio.wait_for(task, 6)
        assert results['current']['approved']
        assert (pattern in approval._session_approved.get(SESSION_KEY, set())) == (choice != 'once')
        assert (pattern in approval._permanent_approved) == (choice == 'always')
        if choice == 'always':
            config = yaml.safe_load((get_hermes_home() / 'config.yaml').read_text(encoding='utf-8'))
            assert pattern in config['command_allowlist'], 'valid permanent consent was not saved'
            assert runner._clear_session_boundary_security_state(SESSION_KEY)
            assert pattern not in approval._session_approved.get(SESSION_KEY, set())
            assert approval.is_approved(SESSION_KEY, pattern), 'true boundary revoked valid permanent consent'
        assert SESSION_KEY not in approval._gateway_queues
    finally:
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)


@pytest.mark.asyncio
@pytest.mark.parametrize('parallel', ['distinct', 'identical'])
async def test_current_parallel_once_preserves_fifo_and_nonsharing(monkeypatch, tmp_path, parallel):
    runner, turn, results, adapter = install_turns(monkeypatch, tmp_path, 'plugin', parallel=parallel)
    followers = []
    real_hook = approval._fire_approval_hook

    def hook(name, **kwargs):
        if name == 'pre_approval_request' and kwargs.get('coalesced'):
            followers.append(True)
        return real_hook(name, **kwargs)

    monkeypatch.setattr(approval, '_fire_approval_hook', hook)
    task = asyncio.create_task(turn('parallel'))
    try:
        await until(lambda: task.done() or (len(followers) == 2 if parallel == 'identical' else len(adapter.sent) == 3))
        assert len(adapter.sent) == (1 if parallel == 'identical' else 3)
        queue = list(approval._gateway_queues[SESSION_KEY])
        assert approval.resolve_gateway_approval(SESSION_KEY, 'once') == 1
        assert queue[0].result == 'once'
        assert all(not e.event.is_set() for e in queue[1:]), 'FIFO consent consumed another entry'
        if parallel == 'identical':
            await until(lambda: task.done() or len(adapter.sent) == 3)
            assert len(adapter.sent) == 3, 'once consent was reused by coalesced callers'
        for _ in range(2):
            assert approval.resolve_gateway_approval(SESSION_KEY, 'once') == 1
        await asyncio.wait_for(task, 6)
        assert len(results['parallel']) == 3 and all(r['approved'] for r in results['parallel'])
        assert not approval._session_approved.get(SESSION_KEY)
        assert not approval._permanent_approved
    finally:
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)
