"""Real Gateway worker registration/send/finally barriers for ordinary approvals."""
from __future__ import annotations

import asyncio
import pytest

from gateway.platforms.base import SendResult
from tests.gateway.test_queued_followup_processing_hooks import (
    HookRecordingAdapter, SESSION_KEY, _install_fake_agent, _make_runner, _source,
)
from tests.gateway.test_shared_input_run_ownership import ThreadBarrier
from tools import approval


@pytest.fixture(autouse=True)
def isolated_approval_state():
    with approval._lock:
        approval._gateway_notify_cbs.clear()
        approval._gateway_queues.clear()
    yield
    approval.unregister_gateway_notify(SESSION_KEY)


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), 6)


def data(command):
    return {'command': command, 'description': 'inert owned approval fixture',
            'pattern_key': command, 'pattern_keys': [command]}


@pytest.mark.asyncio
@pytest.mark.parametrize('retirement', ['generation', 'boundary'])
@pytest.mark.parametrize('edge', ['registration', 'finally', 'admission', 'queue-allocation', 'notify-hook', 'schedule', 'send-result'])
async def test_old_real_worker_cannot_replace_send_or_clean_new_approval(monkeypatch, tmp_path, edge, retirement):
    import gateway.run as gateway_run

    gate = ThreadBarrier()
    new_sent = asyncio.Event()
    loop = asyncio.get_running_loop()
    sent, fallback, returned, requested = [], [], [], []

    class Adapter(HookRecordingAdapter):
        async def send_exec_approval(self, chat_id, command, session_key, **kwargs):
            sent.append(command)
            if command == 'new-command':
                new_sent.set()
            if command == 'old-command' and edge == 'send-result':
                await asyncio.to_thread(gate.wait)
                return SendResult(success=False, error='inert failed old send')
            return SendResult(success=True, message_id=command)

        async def send(self, chat_id, content, **kwargs):
            fallback.append(content)
            return SendResult(success=True, message_id='fallback')

    adapter = Adapter()
    runner = _make_runner(adapter)

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            if message == 'old' and edge in {'finally', 'admission'}:
                gate.wait()
            if message == 'old' and edge in {'registration', 'finally'}:
                decision = None
            else:
                # Lookup after the barrier is intentional: a producer's bound
                # owner must reject even when this selects the newer callback.
                callback = approval._gateway_notify_cbs.get(SESSION_KEY)
                decision = approval._await_gateway_decision(SESSION_KEY, callback,
                    data('old-command' if message == 'old' else 'new-command'))
            loop.call_soon_threadsafe(returned.append, (message, decision))
            return {'final_response': 'inert reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    original_register = approval.register_gateway_notify
    calls = 0

    def register(key, callback, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1 and edge == 'registration':
            gate.wait()
        return original_register(key, callback, **kwargs)

    monkeypatch.setattr(approval, 'register_gateway_notify', register)
    original_init = approval._ApprovalEntry.__init__

    def entry_init(entry, payload):
        original_init(entry, payload)
        if edge == 'queue-allocation' and payload['command'] == 'old-command':
            gate.wait()

    monkeypatch.setattr(approval._ApprovalEntry, '__init__', entry_init)
    original_hook = approval._fire_approval_hook

    def hook(name, **kwargs):
        if name == 'pre_approval_request':
            requested.append(kwargs['command'])
            if edge == 'notify-hook' and kwargs['command'] == 'old-command':
                gate.wait()
        return original_hook(name, **kwargs)

    monkeypatch.setattr(approval, '_fire_approval_hook', hook)
    actual_schedule = gateway_run.safe_schedule_threadsafe

    def schedule(coro, *args, **kwargs):
        import sys
        caller = sys._getframe(1)
        if (edge == 'schedule' and caller.f_code.co_name == '_approval_notify_sync'
                and caller.f_locals['approval_data']['command'] == 'old-command'):
            gate.wait()
        return actual_schedule(coro, *args, **kwargs)

    monkeypatch.setattr(gateway_run, 'safe_schedule_threadsafe', schedule)
    generation = runner._begin_session_run_generation(SESSION_KEY)

    async def turn(message):
        return await runner._run_agent(message=message, context_prompt='', history=[], source=_source(),
            session_id='inert-session', session_key=SESSION_KEY,
            run_generation=runner._session_state(SESSION_KEY).persistent.run_generation)

    old = asyncio.create_task(turn('old'))
    new = None
    try:
        await asyncio.wait_for(gate.entered.wait(), 6)
        if retirement == 'generation':
            runner._begin_session_run_generation(SESSION_KEY)
        else:
            runner._clear_session_boundary_security_state(SESSION_KEY)
            assert runner._session_state(SESSION_KEY).persistent.run_generation == generation
        new = asyncio.create_task(turn('new'))
        await asyncio.wait_for(new_sent.wait(), 6)
        new_callback = approval._gateway_notify_cbs[SESSION_KEY]
        new_entry = next(entry for entry in approval._gateway_queues[SESSION_KEY]
                         if entry.data['command'] == 'new-command')
        gate.release.set()
        await until(lambda: old.done() or any(message == 'old' for message, _ in returned)
                    or any('old-command' in text for text in fallback)
                    or sent.count('old-command') > (1 if edge == 'send-result' else 0))
        assert sent.count('old-command') == (1 if edge == 'send-result' else 0), 'stale producer sent after retirement'
        assert not any('old-command' in text for text in fallback), 'old failed send fell back after retirement'
        if edge == 'queue-allocation':
            assert 'old-command' not in requested, 'stale allocation was published after its admission check'
        await asyncio.wait_for(old, 6)
        assert approval._gateway_notify_cbs.get(SESSION_KEY) is new_callback, 'old finally removed replacement callback'
        assert approval._gateway_queues.get(SESSION_KEY) == [new_entry]
        assert not new_entry.event.is_set(), 'old finally consumed replacement answer slot'
        assert approval.resolve_gateway_approval(SESSION_KEY, 'once', request_id=new_entry.data['request_id']) == 1
        await asyncio.wait_for(new, 6)
        decision = next(value for message, value in returned if message == 'new')
        assert decision['resolved'] and decision['choice'] == 'once'
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[t for t in (old, new) if t is not None], return_exceptions=True), 10)


@pytest.mark.asyncio
async def test_true_boundary_rejects_old_admission_without_a_replacement(monkeypatch, tmp_path):
    runner = _make_runner(HookRecordingAdapter())
    gate = ThreadBarrier()
    sent = []

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            callback = approval._gateway_notify_cbs[SESSION_KEY]
            gate.wait()
            result = approval._await_gateway_decision(SESSION_KEY, callback, data('retired-command'))
            sent.append(result)
            return {'final_response': 'inert reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    monkeypatch.setattr(approval, '_get_approval_timeout', lambda: 0)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(runner._run_agent(message='old', context_prompt='', history=[],
        source=_source(), session_id='inert-session', session_key=SESSION_KEY, run_generation=generation))
    actual_hook = approval._fire_approval_hook
    requested = []

    def hook(name, **kwargs):
        if name == 'pre_approval_request':
            requested.append(kwargs)
        return actual_hook(name, **kwargs)

    monkeypatch.setattr(approval, '_fire_approval_hook', hook)
    await gate.change(task, lambda: runner._clear_session_boundary_security_state(SESSION_KEY))
    assert not requested, 'a retired producer re-entered the queue after cancel-all'
    assert sent and sent[0]['choice'] == 'deny'


@pytest.mark.asyncio
@pytest.mark.parametrize('identical', [False, True], ids=['parallel-fifo', 'parallel-once-only'])
async def test_current_real_worker_preserves_parallel_fifo_and_once(monkeypatch, tmp_path, identical):
    from concurrent.futures import ThreadPoolExecutor
    import contextvars

    sent, results, followers = [], [], []

    class Adapter(HookRecordingAdapter):
        async def send_exec_approval(self, chat_id, command, session_key, **kwargs):
            sent.append(command)
            return SendResult(success=True, message_id=command)

    runner = _make_runner(Adapter())
    actual_hook = approval._fire_approval_hook

    def hook(name, **kwargs):
        if name == 'pre_approval_request' and kwargs.get('coalesced'):
            followers.append(True)
        return actual_hook(name, **kwargs)

    monkeypatch.setattr(approval, '_fire_approval_hook', hook)

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            def request(command):
                callback = approval._gateway_notify_cbs[SESSION_KEY]
                return approval._await_gateway_decision(SESSION_KEY, callback, data(command))
            with ThreadPoolExecutor(max_workers=3) as pool:
                first = pool.submit(contextvars.copy_context().run, request, 'same' if identical else 'first')
                # Ensure the first leader was presented before admitting the
                # followers; no timing assumption about concurrent coalescing.
                import time
                deadline = time.monotonic() + 6
                while not sent and time.monotonic() < deadline:
                    time.sleep(0.005)
                assert sent
                others = [pool.submit(contextvars.copy_context().run, request,
                          'same' if identical else f'next-{i}') for i in range(2)]
                results.extend(future.result(timeout=8) for future in [first, *others])
            return {'final_response': 'inert reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(runner._run_agent(message='current', context_prompt='', history=[],
        source=_source(), session_id='inert-session', session_key=SESSION_KEY, run_generation=generation))
    try:
        await until(lambda: task.done() or (len(followers) == 2 if identical else len(sent) == 3))
        assert len(sent) == (1 if identical else 3), 'current producer lost its approval prompts'
        queue = approval._gateway_queues[SESSION_KEY]
        first_entry = queue[0]
        other_entries = list(queue[1:])
        assert len(queue) == (1 if identical else 3)
        assert approval.resolve_gateway_approval(SESSION_KEY, 'once') == 1
        assert first_entry.result == 'once'
        if identical:
            await until(lambda: task.done() or len(sent) == 3)
            assert len(sent) == 3, 'once consent was shared with coalesced followers'
            assert approval.resolve_gateway_approval(SESSION_KEY, 'once', resolve_all=True) == 2
        else:
            assert all(not entry.event.is_set() for entry in other_entries)
            assert approval.resolve_gateway_approval(SESSION_KEY, 'deny', resolve_all=True) == 2
        await asyncio.wait_for(task, 10)
        choices = [result['choice'] for result in results]
        assert choices.count('once') == (3 if identical else 1)
        assert choices.count('deny') == (0 if identical else 2)
        assert SESSION_KEY not in approval._gateway_queues
        assert SESSION_KEY not in approval._gateway_notify_cbs
    finally:
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)


@pytest.mark.asyncio
async def test_retired_public_tool_gate_cannot_reenter_legacy_pending(monkeypatch, tmp_path):
    runner = _make_runner(HookRecordingAdapter())
    gate = ThreadBarrier()
    results = []

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            gate.wait()
            results.append(approval.request_tool_approval('inert_fixture', 'owned gate fixture'))
            return {'final_response': 'inert reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    monkeypatch.setattr(approval, '_is_gateway_approval_context', lambda: True)
    monkeypatch.setattr(approval, '_get_approval_timeout', lambda: 0)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(runner._run_agent(message='old', context_prompt='', history=[],
        source=_source(), session_id='inert-session', session_key=SESSION_KEY, run_generation=generation))
    try:
        await gate.change(task, lambda: runner._clear_session_boundary_security_state(SESSION_KEY))
        assert SESSION_KEY not in approval._pending, 'retired public caller repopulated legacy pending state'
        assert results and results[0]['approved'] is False
        assert not results[0].get('approval_pending'), 'retired producer reported a live pending approval'
    finally:
        approval.clear_session(SESSION_KEY)


def test_clear_retires_captured_registration_without_a_gateway_predicate(monkeypatch):
    seen = []
    old = approval.register_gateway_notify(SESSION_KEY, seen.append)
    token = approval.set_gateway_approval_registration(old)
    try:
        approval.clear_session(SESSION_KEY)
        monkeypatch.setattr(approval, '_get_approval_timeout', lambda: 0)
        assert not old.is_current()
        new = approval.register_gateway_notify(SESSION_KEY, seen.append)
        result = approval._await_gateway_decision(SESSION_KEY, new, data('old-bound-context'))
        assert result['choice'] == 'deny'
        assert not seen
        assert SESSION_KEY not in approval._gateway_queues
        assert approval._gateway_notify_cbs[SESSION_KEY] is new
    finally:
        approval.reset_gateway_approval_registration(token)


@pytest.mark.asyncio
async def test_current_real_worker_definitive_native_failure_falls_back_once(monkeypatch, tmp_path):
    native, fallback, results = [], [], []

    class Adapter(HookRecordingAdapter):
        async def send_exec_approval(self, chat_id, command, session_key, **kwargs):
            native.append(command)
            return SendResult(success=False, error='inert definitive failure')

        async def send(self, chat_id, content, **kwargs):
            if kwargs.get('metadata', {}).get('is_approval_prompt'):
                fallback.append(content)
            return SendResult(success=True, message_id='fallback')

    runner = _make_runner(Adapter())

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            callback = approval._gateway_notify_cbs[SESSION_KEY]
            results.append(approval._await_gateway_decision(SESSION_KEY, callback, data('fallback-command')))
            return {'final_response': 'inert reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(runner._run_agent(message='current', context_prompt='', history=[],
        source=_source(), session_id='inert-session', session_key=SESSION_KEY, run_generation=generation))
    try:
        await until(lambda: task.done() or bool(fallback))
        assert native == ['fallback-command'] and len(fallback) == 1
        assert approval.resolve_gateway_approval(SESSION_KEY, 'once') == 1
        await asyncio.wait_for(task, 6)
        assert results[0]['resolved'] and results[0]['choice'] == 'once'
        assert len(fallback) == 1
    finally:
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)


def test_old_qualified_cleanup_preserves_new_strict_ticket():
    from tests.control_mcp.test_control_approval import PD, make_binding

    old = approval.register_gateway_notify(SESSION_KEY, lambda payload: None)
    binding = make_binding(approval)
    old_ticket = approval.request_control_consent(binding, session_key=SESSION_KEY, timeout_seconds=60, now=100)
    old_entry = approval._gateway_queues[SESSION_KEY][0]
    new = approval.register_gateway_notify(SESSION_KEY, lambda payload: None)
    new_ticket = approval.request_control_consent(binding, session_key=SESSION_KEY, timeout_seconds=60, now=100)
    new_entry = approval._gateway_queues[SESSION_KEY][-1]
    approval.unregister_gateway_notify(SESSION_KEY, registration=old)
    assert old_entry.event.is_set()
    old_decision = approval.take_control_decision(old_ticket, now=110)
    assert old_decision is not None and old_decision.choice == 'deny'
    assert not approval.consume_control_decision(old_decision, binding, now=110)
    assert approval._gateway_notify_cbs[SESSION_KEY] is new
    assert approval._gateway_queues[SESSION_KEY] == [new_entry]
    assert not new_entry.event.is_set()
    assert approval.resolve_gateway_approval(SESSION_KEY, 'once', resolve_all=True) == 0
    assert approval.resolve_control_consent(session_key=SESSION_KEY, request_id=new_ticket.request_id,
        intent_digest=binding.intent_digest, choice='once', now=110, presentation_digest=PD)
    decision = approval.take_control_decision(new_ticket, now=110)
    assert decision is not None
    assert approval.consume_control_decision(decision, binding, now=110)
    assert not approval.consume_control_decision(decision, binding, now=110)


@pytest.mark.asyncio
@pytest.mark.parametrize('edge', ['inherited-context', 'allocation'])
async def test_old_real_worker_strict_admission_cannot_adopt_new_registration(monkeypatch, tmp_path, edge):
    from tests.control_mcp.test_control_approval import make_binding

    gate = ThreadBarrier()
    sent, outcomes = [], []
    binding = make_binding(approval)

    class Adapter(HookRecordingAdapter):
        async def send_exec_approval(self, chat_id, command, session_key, **kwargs):
            sent.append(command)
            return SendResult(success=True, message_id=command)

    runner = _make_runner(Adapter())
    original_init = approval._ControlApprovalEntry.__init__

    def initialize(entry, *args):
        original_init(entry, *args)
        if edge == 'allocation':
            gate.wait()

    monkeypatch.setattr(approval._ControlApprovalEntry, '__init__', initialize)

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            if message == 'old':
                if edge == 'inherited-context':
                    gate.wait()
                try:
                    approval.request_control_consent(binding, session_key=SESSION_KEY, timeout_seconds=60, now=100)
                except RuntimeError as exc:
                    outcomes.append(str(exc))
                else:
                    outcomes.append('admitted')
            else:
                callback = approval._gateway_notify_cbs[SESSION_KEY]
                approval._await_gateway_decision(SESSION_KEY, callback, data('new-command'))
            return {'final_response': 'inert reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    runner._begin_session_run_generation(SESSION_KEY)

    async def turn(message):
        return await runner._run_agent(message=message, context_prompt='', history=[], source=_source(),
            session_id='inert-session', session_key=SESSION_KEY,
            run_generation=runner._session_state(SESSION_KEY).persistent.run_generation)

    old = asyncio.create_task(turn('old'))
    new = None
    try:
        await asyncio.wait_for(gate.entered.wait(), 6)
        runner._clear_session_boundary_security_state(SESSION_KEY)
        new = asyncio.create_task(turn('new'))
        await until(lambda: 'new-command' in sent)
        callback = approval._gateway_notify_cbs[SESSION_KEY]
        entry = approval._gateway_queues[SESSION_KEY][0]
        publications = []

        class ObservedQueue(list):
            def append(self, value):
                if isinstance(value, approval._ControlApprovalEntry):
                    publications.append(value)
                return super().append(value)

        with approval._lock:
            approval._gateway_queues[SESSION_KEY] = ObservedQueue(approval._gateway_queues[SESSION_KEY])
        gate.release.set()
        await asyncio.wait_for(old, 6)
        assert not publications, 'strict entry was published under a retired producer'
        assert outcomes == ['control_approval_producer_retired'], 'strict producer adopted a new registration'
        assert sent == ['new-command']
        assert approval._gateway_notify_cbs[SESSION_KEY] is callback
        assert approval._gateway_queues[SESSION_KEY] == [entry] and not entry.event.is_set()
        assert approval.resolve_gateway_approval(SESSION_KEY, 'once', request_id=entry.data['request_id']) == 1
        await asyncio.wait_for(new, 6)
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[task for task in (old, new) if task is not None], return_exceptions=True), 10)


@pytest.mark.asyncio
async def test_replacement_no_id_approval_finishes_before_old_send_ack(monkeypatch, tmp_path):
    gate = ThreadBarrier()
    sent, decisions = [], {}

    class Adapter(HookRecordingAdapter):
        async def send_exec_approval(self, chat_id, command, session_key, **kwargs):
            sent.append(command)
            if command == 'old-command':
                await asyncio.to_thread(gate.wait)
            return SendResult(success=True, message_id=command)

    runner = _make_runner(Adapter())

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            callback = approval._gateway_notify_cbs[SESSION_KEY]
            decisions[message] = approval._await_gateway_decision(SESSION_KEY, callback, data(message + '-command'))
            return {'final_response': 'inert reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    runner._begin_session_run_generation(SESSION_KEY)

    async def turn(message):
        return await runner._run_agent(message=message, context_prompt='', history=[], source=_source(),
            session_id='inert-session', session_key=SESSION_KEY,
            run_generation=runner._session_state(SESSION_KEY).persistent.run_generation)

    old = asyncio.create_task(turn('old'))
    new = None
    try:
        await asyncio.wait_for(gate.entered.wait(), 6)
        old_entry = approval._gateway_queues[SESSION_KEY][0]
        runner._begin_session_run_generation(SESSION_KEY)
        new = asyncio.create_task(turn('new'))
        await until(lambda: 'new-command' in sent)
        new_entry = next(entry for entry in approval._gateway_queues[SESSION_KEY] if entry.data['command'] == 'new-command')
        # Exactly the plaintext /approve contract: no request_id and no all.
        assert approval.resolve_gateway_approval(SESSION_KEY, 'once') == 1
        assert new_entry.result == 'once', 'replacement approval was consumed by the retired queue head'
        await asyncio.wait_for(new, 6)
        assert not old.done() and not gate.release.is_set(), 'old ACK was released before the replacement completed'
        assert old_entry.event.is_set(), 'retired waiters were not woken at registration replacement'
        assert decisions['new']['resolved'] and decisions['new']['choice'] == 'once'
        gate.release.set()
        await asyncio.wait_for(old, 6)
        assert decisions['old']['choice'] not in {'once', 'session', 'always'}
        assert SESSION_KEY not in approval._gateway_queues
    finally:
        gate.release.set()
        approval.unregister_gateway_notify(SESSION_KEY)
        await asyncio.wait_for(asyncio.gather(*[task for task in (old, new) if task is not None], return_exceptions=True), 10)
