"""Recovered busy destinations keep pre-yield owners and chat-local cost."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import GatewayConfig
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session_state import SessionState
from tests.gateway.test_shared_input_normalized_ownership import routed_runner
from tests.gateway.test_shared_input_run_ownership import ThreadBarrier


def busy_runner(monkeypatch, mode):
    runner, adapter, _, raw, resolved, _ = routed_runner(monkeypatch)
    runner.config = GatewayConfig()
    runner._external_drain_active = False
    runner._background_tasks = set()
    runner._busy_ack_ts = {}
    runner._session_sources = {}
    runner.session_store.get_session_metadata = lambda *args: None
    runner._is_user_authorized_for_source = lambda source: True
    runner._persist_active_agents = lambda: None
    runner._scale_to_zero_note_real_inbound = lambda: None
    runner._effective_busy_input_mode = lambda source: mode
    runner._session_busy_input_mode = lambda source: None
    monkeypatch.setenv('HERMES_GATEWAY_BUSY_ACK_ENABLED', 'false')
    monkeypatch.setattr('agent.estop.paused_reply', lambda: None)
    monkeypatch.setattr('hermes_cli.lifecycle.invoke_hook', lambda *args, **kwargs: [])
    key = runner._session_key_for_source(resolved)
    runner._begin_session_run_generation(key)
    agent = SimpleNamespace(steer=Mock(return_value=False), interrupt=Mock(), _active_children=[],
                            _supports_active_turn_redirect=False)
    runner._session_state(key).turn.agent = agent
    return runner, adapter, raw, resolved, key, agent


@pytest.mark.asyncio
@pytest.mark.parametrize('edge', ['compression', 'steer', 'admission'])
@pytest.mark.parametrize('retirement', ['none', 'boundary', 'generation', 'state-replacement', 'other-chat'])
async def test_recovered_busy_ingress_keeps_owner_through_wait(monkeypatch, edge, retirement):
    runner, adapter, raw, resolved, key, old_agent = busy_runner(
        monkeypatch, 'interrupt' if edge == 'compression' else 'steer')
    gate = ThreadBarrier()
    if edge == 'compression':
        def lookup(store, selected):
            assert selected == key
            gate.wait()
            return 'old-session'
        monkeypatch.setattr(runner, '_lookup_session_id_under_store_lock', lookup)
        runner._session_db._db.get_compression_lock_holder = lambda sid: 'compression-owner'
    elif edge == 'steer':
        async def prepare(event, **kwargs):
            await asyncio.to_thread(gate.wait)
            return 'old input'
        monkeypatch.setattr(runner, '_prepare_busy_steer_text', prepare)
    else:
        actual = runner._handle_active_session_busy_message
        async def admission(event, selected, **kwargs):
            await asyncio.to_thread(gate.wait)
            return await actual(event, selected, **kwargs)
        monkeypatch.setattr(runner, '_handle_active_session_busy_message', admission)

    first = MessageEvent(text='old input', source=raw, message_id='busy-1')
    second = MessageEvent(text='replacement input', source=resolved, message_id='busy-2')
    replacement = SimpleNamespace(steer=Mock(), interrupt=Mock())
    state = runner._session_state(key)
    raw_key = runner._session_key_for_source(raw)

    def retire():
        if retirement == 'none':
            return
        if retirement == 'other-chat':
            runner._begin_session_run_generation(runner._session_key_for_source(replace(resolved, chat_id='5555')))
            return
        if retirement == 'boundary':
            runner._clear_conversation_scope(key, reason='busy barrier boundary')
        elif retirement == 'generation':
            runner._begin_session_run_generation(key)
        else:
            runner._sessions_map()[key] = SessionState()
        runner._session_state(key).turn.agent = replacement
        runner._queue_or_replace_pending_event(key, second)

    task = asyncio.create_task(runner._handle_message(first))
    await gate.change(task, retire)
    assert task.result() is None
    old_agent.interrupt.assert_not_called()
    replacement.steer.assert_not_called()
    replacement.interrupt.assert_not_called()
    assert raw.thread_id is None and first.source.thread_id == '73'
    assert runner._session_state(raw_key).persistent.run_generation == 0
    if retirement in {'none', 'other-chat'}:
        assert adapter._pending_messages[key] is first
        runner._queue_or_replace_pending_event(key, second)
        assert list(state.conversation.queued_events) == [second]
        assert not state.persistent.native_image_paths
    else:
        old_agent.steer.assert_not_called()
        assert adapter._pending_messages[key] is second
        assert list(runner._session_state(key).conversation.queued_events) == []


class NoGlobalEnumeration(dict):
    """An operation oracle: selected chat lookup may not scan retained states."""
    def __iter__(self):
        raise AssertionError('global state iteration')

    def items(self):
        raise AssertionError('global state items copy')

    def values(self):
        raise AssertionError('global state values copy')


@pytest.mark.parametrize('unrelated', [0, 2000])
def test_route_snapshot_never_enumerates_global_states(monkeypatch, unrelated):
    runner, _, _, raw, resolved, _ = routed_runner(monkeypatch)
    key = runner._session_key_for_source(resolved)
    runner._session_state(key)
    for i in range(unrelated):
        runner._session_state(runner._session_key_for_source(replace(raw, chat_id=str(10000 + i))))
    store = runner._sessions_map()
    # Keep the real store and its index; poison only global traversal. Before
    # the owner-store fix, _sessions itself is the underlying global dict.
    if hasattr(store, '_states'):
        store._states = NoGlobalEnumeration(store._states)
        store._telegram_dm_keys = NoGlobalEnumeration(store._telegram_dm_keys)
    else:
        runner._sessions = NoGlobalEnumeration(store)
    route = runner._capture_shared_input_route(raw)
    assert set(route.owners) == {runner._session_key_for_source(raw), key}
    assert runner._resolve_shared_input_route(route, resolved)[1] is runner._session_state(key)


@pytest.mark.parametrize('publication', ['setitem', 'setdefault', 'update'])
def test_destination_publication_after_snapshot_cannot_donate_prebuilt_state(monkeypatch, publication):
    runner, _, _, raw, resolved, _ = routed_runner(monkeypatch)
    key = runner._session_key_for_source(resolved)
    prebuilt = SessionState()
    route = runner._capture_shared_input_route(raw)
    store = runner._sessions_map()
    if publication == 'setitem':
        store[key] = prebuilt
    elif publication == 'setdefault':
        store.setdefault(key, prebuilt)
    else:
        store.update({key: prebuilt})
    assert runner._resolve_shared_input_route(route, resolved) is None
    fresh = runner._capture_shared_input_route(raw)
    assert fresh.owners[key][1] is prebuilt
    assert runner._resolve_shared_input_route(fresh, resolved)[1] is prebuilt


@pytest.mark.parametrize('retirement', ['boundary', 'generation', 'state-replacement'])
def test_busy_queue_publication_rechecks_inside_state_lock(monkeypatch, retirement):
    runner, _, _, raw, resolved, _ = routed_runner(monkeypatch)
    key = runner._session_key_for_source(resolved)
    owner = runner._capture_shared_input_owner(key)
    state = owner[1]
    actual_lock = state.shared_input_lock
    acquisitions = 0

    class BoundaryBeforeAcquisition:
        # Deterministically linearize a real boundary immediately before the
        # publisher acquires its lock, catching check-before-lock anti-fixes.
        def __enter__(self):
            nonlocal acquisitions
            acquisitions += 1
            if acquisitions == 2:
                if retirement == 'boundary':
                    runner._clear_conversation_scope(key, reason='publication lock boundary')
                elif retirement == 'generation':
                    runner._begin_session_run_generation(key)
                else:
                    runner._sessions_map()[key] = SessionState()
            return actual_lock.__enter__()

        def __exit__(self, *args):
            return actual_lock.__exit__(*args)

    state.shared_input_lock = BoundaryBeforeAcquisition()
    queued = Mock()
    monkeypatch.setattr(runner, '_enqueue_fifo', queued)
    runner._queue_or_replace_pending_event(key, MessageEvent(text='retired', source=raw),
                                          shared_input_owner=owner)
    assert acquisitions >= 2
    queued.assert_not_called()


@pytest.mark.parametrize('mutation', ['replace', 'pop', 'delete', 'clear', 'setdefault-existing'])
def test_state_store_mapping_changes_keep_scoped_authority_consistent(monkeypatch, mutation):
    runner, _, _, raw, resolved, _ = routed_runner(monkeypatch)
    runner.config = GatewayConfig(multiplex_profiles=True)
    key = runner._session_key_for_source(resolved)
    other = runner._session_key_for_source(replace(raw, chat_id='42420', thread_id='73'))
    other_profile = runner._session_key_for_source(replace(resolved, profile='other'))
    store = runner._sessions_map()
    original, neighbor, profile = SessionState(), SessionState(), SessionState()
    store.update({key: original, other: neighbor, other_profile: profile})
    route = runner._capture_shared_input_route(raw)
    fresh = SessionState()
    if mutation == 'replace':
        store[key] = fresh
    elif mutation == 'pop':
        assert store.pop(key) is original
    elif mutation == 'delete':
        del store[key]
    elif mutation == 'clear':
        store.clear()
    else:
        assert store.setdefault(key, fresh) is original
    current = runner._capture_shared_input_route(raw)
    assert other not in current.owners and other_profile not in current.owners
    if mutation == 'replace':
        assert current.owners[key][1] is fresh
        assert runner._resolve_shared_input_route(route, resolved) is None
    elif mutation == 'setdefault-existing':
        assert current.owners[key][1] is original
        assert runner._resolve_shared_input_route(route, resolved)[1] is original
    else:
        assert key not in current.owners


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['steer', 'interrupt'])
@pytest.mark.parametrize('retirement', ['none', 'boundary', 'generation'])
async def test_busy_voice_wait_keeps_owner_before_echo_and_agent_mutation(monkeypatch, mode, retirement):
    runner, adapter, raw, resolved, key, agent = busy_runner(monkeypatch, mode)
    monkeypatch.setattr(runner, '_lookup_session_id_under_store_lock', lambda *args: None)
    agent.steer.return_value = True
    gate = ThreadBarrier()

    async def transcribe(event, text):
        await asyncio.to_thread(gate.wait)
        return 'voice follow up', ['voice follow up']

    echo = AsyncMock()
    monkeypatch.setattr(runner, '_transcribe_pending_audio_event_once', transcribe)
    monkeypatch.setattr(runner, '_echo_pending_stt_transcripts_once', echo)
    event = MessageEvent(text='', source=raw, message_id='busy-voice', message_type=MessageType.VOICE,
                         media_urls=['voice.ogg'], media_types=['audio/ogg'])
    replacement = MessageEvent(text='new pending', source=resolved, message_id='new-voice-owner')

    def retire():
        if retirement == 'none':
            return
        if retirement == 'boundary':
            runner._clear_conversation_scope(key, reason='voice boundary')
        else:
            runner._begin_session_run_generation(key)
        adapter.get_pending_message(key)
        runner._queue_or_replace_pending_event(key, replacement)

    task = asyncio.create_task(runner._handle_message(event))
    await gate.change(task, retire)
    if retirement == 'none':
        echo.assert_awaited_once()
        if mode == 'steer':
            agent.steer.assert_called_once_with('voice follow up')
            assert key not in adapter._pending_messages
        else:
            agent.interrupt.assert_called_once_with('voice follow up')
            assert adapter._pending_messages[key] is event
    else:
        echo.assert_not_awaited()
        agent.steer.assert_not_called()
        agent.interrupt.assert_not_called()
        assert adapter._pending_messages[key] is replacement
        assert list(runner._session_state(key).conversation.queued_events) == []
