"""Actual Telegram key recovery must retain pre-yield destination authority."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from tests.gateway.test_shared_input_run_ownership import ThreadBarrier, model_runner


def routed_runner(monkeypatch):
    runner, adapter, models = model_runner(monkeypatch)
    raw = SessionSource(platform=Platform.TELEGRAM, chat_type='dm', chat_id='4242', user_id='17')
    resolved = replace(raw, thread_id='73')
    sync_db = SimpleNamespace(
        is_telegram_topic_mode_enabled=lambda **kw: True,
        list_telegram_topic_bindings_for_chat=lambda **kw: [{'user_id': '17', 'thread_id': '73'}],
    )
    runner._session_db = SimpleNamespace(
        _db=sync_db, update_session_model=AsyncMock(),
        get_session=AsyncMock(return_value={'id': 'resumed', 'user_id': '17'}),
        resolve_resume_session_id=AsyncMock(return_value='resumed'),
        get_session_title=AsyncMock(return_value='owned title'),
    )
    runner._async_session_store = SimpleNamespace(
        _store=runner.session_store,
        get_or_create_session=AsyncMock(return_value=SimpleNamespace(session_id='current', was_auto_reset=False)),
        switch_session=AsyncMock(return_value=SimpleNamespace(session_id='resumed')),
        load_transcript=AsyncMock(return_value=[]), set_model_override=AsyncMock(),
    )
    monkeypatch.setattr(runner, '_normalize_source_for_session_key',
                        GatewayRunner._normalize_source_for_session_key.__get__(runner))
    monkeypatch.setattr(runner, '_resume_target_allowed', AsyncMock(return_value=True))
    monkeypatch.setattr(runner, '_evict_cached_agent', Mock())
    return runner, adapter, models, raw, resolved, sync_db


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['model', 'resume'])
@pytest.mark.parametrize('retirement', ['generation', 'boundary', 'new-destination'])
async def test_changed_key_command_cannot_adopt_destination_after_recovery_wait(
    monkeypatch, command, retirement,
):
    runner, _, _, raw, resolved, db = routed_runner(monkeypatch)
    raw_key = runner._session_key_for_source(raw)
    dest_key = runner._session_key_for_source(resolved)
    assert raw_key != dest_key
    if retirement != 'new-destination':
        runner._begin_session_run_generation(dest_key)
    gate = ThreadBarrier()

    def bindings(**kwargs):
        gate.wait()
        return [{'user_id': '17', 'thread_id': '73'}]

    db.list_telegram_topic_bindings_for_chat = bindings
    text = '/model old-choice --session' if command == 'model' else '/resume resumed'
    event = MessageEvent(text=text, source=raw)
    operation = runner._handle_model_command(event) if command == 'model' else runner._handle_resume_command(event)
    task = asyncio.create_task(operation)

    def retire():
        if retirement == 'boundary':
            runner._clear_conversation_scope(dest_key, reason='test destination boundary')
        else:
            runner._begin_session_run_generation(dest_key)
        runner._pending_model_notes = {dest_key: 'replacement model'}
        runner._pending_skills_reload_notes = {dest_key: 'replacement skill'}
        runner._session_state(dest_key).persistent.native_image_paths = ['replacement.png']

    await gate.change(task, retire)
    assert raw.thread_id is None
    assert runner._session_state(raw_key).persistent.run_generation == 0
    assert runner._pending_model_notes[dest_key] == 'replacement model'
    assert runner._pending_skills_reload_notes[dest_key] == 'replacement skill'
    assert runner._session_state(dest_key).persistent.native_image_paths == ['replacement.png']
    runner._session_db.update_session_model.assert_not_awaited()
    runner._async_session_store.switch_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['model', 'resume'])
@pytest.mark.parametrize('other_chat', [False, True], ids=['other-topic', 'other-chat'])
async def test_changed_key_command_survives_other_chat_during_recovery(monkeypatch, command, other_chat):
    runner, _, _, raw, resolved, db = routed_runner(monkeypatch)
    key = runner._session_key_for_source(resolved)
    runner._begin_session_run_generation(key)
    gate = ThreadBarrier()

    def bindings(**kwargs):
        gate.wait()
        return [{'user_id': '17', 'thread_id': '73'}]

    db.list_telegram_topic_bindings_for_chat = bindings
    text = '/model current-choice --session' if command == 'model' else '/resume resumed'
    event = MessageEvent(text=text, source=raw)
    task = asyncio.create_task(runner._handle_model_command(event) if command == 'model'
                               else runner._handle_resume_command(event))
    other_key = runner._session_key_for_source(replace(
        raw, chat_id='42420' if other_chat else raw.chat_id, thread_id='74'))
    await gate.change(task, lambda: runner._begin_session_run_generation(other_key))
    assert raw.thread_id is None
    if command == 'model':
        assert 'to current-choice' in runner._pending_model_notes[key]
    else:
        runner._async_session_store.switch_session.assert_awaited_once_with(key, 'resumed')


@pytest.mark.parametrize('retirement', ['generation', 'boundary', 'state-replacement'])
def test_stale_boundary_is_entirely_inert(monkeypatch, retirement):
    runner, _, _, raw, _, _ = routed_runner(monkeypatch)
    key = runner._session_key_for_source(raw)
    owner = runner._capture_shared_input_owner(key)
    if retirement == 'generation':
        runner._begin_session_run_generation(key)
    elif retirement == 'boundary':
        runner._clear_conversation_scope(key, reason='test boundary')
    else:
        from gateway.session_state import SessionState
        runner._sessions_map()[key] = SessionState()
    state = runner._session_state(key)
    approval = {'command': 'replacement inert request'}
    state.persistent.approvals = approval
    state.persistent.update_prompt_pending = True
    state.persistent.native_image_paths = ['replacement.png']
    runner._pending_model_notes = {key: 'replacement model'}
    runner._pending_skills_reload_notes = {key: 'replacement skill'}
    epoch = state.persistent.shared_input_epoch
    from tools import approval as approval_mod, slash_confirm
    clear_approval, clear_slash = Mock(), Mock()
    monkeypatch.setattr(approval_mod, 'clear_session', clear_approval)
    monkeypatch.setattr(slash_confirm, 'clear', clear_slash)
    runner._clear_session_boundary_security_state(key, shared_input_owner=owner)
    assert state.persistent.approvals is approval
    assert state.persistent.update_prompt_pending is True
    assert state.persistent.shared_input_epoch == epoch
    assert state.persistent.native_image_paths == ['replacement.png']
    assert runner._pending_model_notes[key] == 'replacement model'
    assert runner._pending_skills_reload_notes[key] == 'replacement skill'
    clear_approval.assert_not_called()
    clear_slash.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True], ids=['body', 'native-image'])
@pytest.mark.parametrize('internal', [False, True], ids=['human-ingress', 'internal-ingress'])
@pytest.mark.parametrize('retirement', ['none', 'generation', 'boundary', 'other-chat'])
async def test_normal_ingress_recovers_key_before_claim_and_consumes_once(
    monkeypatch, tmp_path, native, internal, retirement,
):
    import base64
    from gateway.config import GatewayConfig
    from gateway.platforms.base import MessageType
    from tests.gateway.test_queued_followup_processing_hooks import _install_fake_agent

    runner, _, _, raw, resolved, db = routed_runner(monkeypatch)
    runner.config = GatewayConfig()
    runner._external_drain_active = False
    runner._background_tasks = set()
    runner._busy_ack_ts = {}
    runner._session_sources = {}
    runner.session_store.get_session_metadata = lambda *args: None
    runner._is_user_authorized_for_source = lambda source: True
    runner._persist_active_agents = lambda: None
    runner._scale_to_zero_note_real_inbound = lambda: None
    runner._clear_durable_active_turn = AsyncMock()
    runner._run_post_turn_hooks = AsyncMock()
    runner._restore_moa_one_shot = lambda *args: None
    runner._restore_pending_one_turn_model_override = lambda *args: None
    monkeypatch.setattr('agent.estop.paused_reply', lambda: None)
    monkeypatch.setattr('hermes_cli.lifecycle.invoke_hook', lambda *args, **kwargs: [])
    raw_key = runner._session_key_for_source(raw)
    dest_key = runner._session_key_for_source(resolved)
    # Equal numeric generations must not stand in for equal session identity.
    runner._begin_session_run_generation(raw_key)
    runner._begin_session_run_generation(dest_key)
    image = tmp_path / 'owned.png'
    image.write_bytes(base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jk1sAAAAASUVORK5CYII='))
    calls, claims = [], []

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            calls.append(message)
            return {'final_response': 'owned reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    monkeypatch.setattr(runner, '_decide_image_input_mode', lambda **kwargs: 'native')
    actual_claim = runner._claim_active_session_slot

    def claim(key, source):
        claims.append(key)
        return actual_claim(key, source)

    monkeypatch.setattr(runner, '_claim_active_session_slot', claim)

    async def input_turn(event, source, key, generation, *, shared_input_owner):
        # Session/transcript assembly is outside this routing proof. Preserve
        # the real preparation, ownership checks, TurnRunner and agent input.
        runner._session_db = None
        text = await runner._prepare_profile_scoped_inbound_message_text(
            event=event, source=source, history=[], session_key=key, run_generation=generation,
            shared_input_owner=shared_input_owner)
        assert text is not None
        result = await runner._run_agent(message=text, context_prompt='', history=[],
            source=source, session_id='owned-session', session_key=key, run_generation=generation,
            shared_input_owner=shared_input_owner)
        return result['final_response']

    monkeypatch.setattr(runner, '_handle_message_with_agent', input_turn)
    event = MessageEvent(text='owned normal body', source=raw, message_id='normalized-inbound',
        internal=internal, message_type=MessageType.PHOTO if native else MessageType.TEXT,
        media_urls=[str(image)] if native else [], media_types=['image/png'] if native else [])
    if retirement == 'none':
        response = await runner._handle_message(event)
    else:
        gate = ThreadBarrier()

        def bindings(**kwargs):
            gate.wait()
            return [{'user_id': '17', 'thread_id': '73'}]

        db.list_telegram_topic_bindings_for_chat = bindings

        def retire():
            if retirement == 'other-chat':
                key = runner._session_key_for_source(replace(raw, chat_id='42420', thread_id='73'))
                runner._begin_session_run_generation(key)
                return
            if retirement == 'generation':
                runner._begin_session_run_generation(dest_key)
            else:
                runner._clear_conversation_scope(dest_key, reason='ingress barrier boundary')
            runner._pending_model_notes = {dest_key: 'replacement model'}
            runner._pending_skills_reload_notes = {dest_key: 'replacement skill'}
            runner._session_state(dest_key).persistent.native_image_paths = ['replacement.png']

        task = asyncio.create_task(runner._handle_message(event))
        await gate.change(task, retire)
        response = task.result()
        if retirement != 'other-chat':
            assert response is None
            assert not claims and not calls
            assert runner._pending_model_notes[dest_key] == 'replacement model'
            assert runner._pending_skills_reload_notes[dest_key] == 'replacement skill'
            assert runner._session_state(dest_key).persistent.native_image_paths == ['replacement.png']
            return
    assert response == 'owned reply'
    assert raw.thread_id is None
    assert event.source.thread_id == '73'
    assert claims == [dest_key]
    assert runner._session_state(raw_key).persistent.run_generation == 1
    assert len(calls) == 1
    if native:
        assert isinstance(calls[0], list)
        assert len([part for part in calls[0] if part.get('type') == 'image_url']) == 1
        assert any('owned normal body' in part.get('text', '') for part in calls[0])
    else:
        assert 'owned normal body' in calls[0]
    assert runner._consume_pending_native_image_paths(dest_key) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['model', 'resume'])
async def test_first_destination_has_initial_authority_without_recapture(monkeypatch, command):
    runner, _, _, raw, resolved, _ = routed_runner(monkeypatch)
    key = runner._session_key_for_source(resolved)
    assert runner._peek_session_state(key) is None
    event = MessageEvent(text='/model first-choice --session' if command == 'model' else '/resume resumed',
                         source=raw)
    if command == 'model':
        await runner._handle_model_command(event)
        assert 'to first-choice' in runner._pending_model_notes[key]
    else:
        await runner._handle_resume_command(event)
        runner._async_session_store.switch_session.assert_awaited_once_with(key, 'resumed')
    assert raw.thread_id is None
