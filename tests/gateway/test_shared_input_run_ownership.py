"""Shared input must stay with its owner at real producer/consumer barriers."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.platforms.base import MessageEvent, MessageType, SendResult
from tests.gateway.test_queued_followup_processing_hooks import (
    HookRecordingAdapter, SESSION_KEY, _install_fake_agent, _make_runner, _source,
)


class ThreadBarrier:
    """A dependency leaf blocks; the actual Gateway coroutine keeps running."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.release = threading.Event()

    def wait(self) -> None:
        self.loop.call_soon_threadsafe(self.entered.set)
        assert self.release.wait(8), 'test did not release dependency'

    async def change(self, task, callback) -> None:
        try:
            await asyncio.wait_for(self.entered.wait(), 5)
            assert not task.done(), 'owner must be suspended at dependency'
            callback()
        finally:
            self.release.set()
        await asyncio.wait_for(task, 8)


def event(text: str = 'owned input', *, image: str | None = None) -> MessageEvent:
    return MessageEvent(text=text, source=_source(), message_id='owned-input',
        message_type=MessageType.PHOTO if image else MessageType.TEXT,
        media_urls=[image] if image else [], media_types=['image/png'] if image else [])


@pytest.mark.asyncio
async def test_late_native_producer_cannot_overwrite_replacement(monkeypatch) -> None:
    runner = _make_runner(HookRecordingAdapter())
    runner._begin_session_run_generation(SESSION_KEY)
    gate = ThreadBarrier()

    def route(**kwargs):
        gate.wait()
        return 'native'

    monkeypatch.setattr(runner, '_decide_image_input_mode', route)
    task = asyncio.create_task(runner._prepare_inbound_message_text(
        event=event(image='old.png'), source=_source(), history=[], session_key=SESSION_KEY))

    def replace() -> None:
        runner._invalidate_session_run_generation(SESSION_KEY, reason='owned replacement')
        runner._begin_session_run_generation(SESSION_KEY)
        runner._session_state(SESSION_KEY).persistent.native_image_paths = ['replacement.png']

    await gate.change(task, replace)
    assert runner._consume_pending_native_image_paths(SESSION_KEY) == ['replacement.png']


@pytest.mark.asyncio
async def test_late_skill_producer_cannot_overwrite_replacement(monkeypatch) -> None:
    import agent.skill_commands as commands
    runner = _make_runner(HookRecordingAdapter())
    key = runner._session_key_for_source(_source())
    runner._begin_session_run_generation(key)
    gate = ThreadBarrier()

    def reload():
        gate.wait()
        return {'added': [{'name': 'old-skill', 'description': 'old'}], 'removed': [], 'total': 1}

    monkeypatch.setattr(commands, 'reload_skills', reload)
    task = asyncio.create_task(runner._handle_reload_skills_command(event('/reload-skills')))

    def replace() -> None:
        runner._invalidate_session_run_generation(key, reason='owned replacement')
        runner._begin_session_run_generation(key)
        runner._pending_skills_reload_notes = {key: 'replacement skill note'}

    await gate.change(task, replace)
    assert runner._pending_skills_reload_notes[key] == 'replacement skill note'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['model', 'skill', 'native'])
@pytest.mark.parametrize('boundary_only', [False, True], ids=['run-replaced', 'boundary-only'])
async def test_stale_real_turn_consumer_preserves_replacement(monkeypatch, tmp_path, kind, boundary_only) -> None:
    import gateway.run as gateway_run
    runner = _make_runner(HookRecordingAdapter())
    generation = runner._begin_session_run_generation(SESSION_KEY)
    runner._pending_model_notes = {}
    runner._pending_skills_reload_notes = {}
    value = ['replacement.png'] if kind == 'native' else 'replacement note'
    store_name = {'model': '_pending_model_notes', 'skill': '_pending_skills_reload_notes',
                  'native': '_pending_native_image_paths_by_session'}[kind]
    calls = []

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            calls.append(message)
            return {'final_response': 'owned reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)

    def replace(_turn_runner, agent, context):
        if boundary_only:
            runner._clear_conversation_scope(SESSION_KEY, reason='consumer boundary barrier')
        else:
            runner._invalidate_session_run_generation(SESSION_KEY, reason='consumer barrier')
            runner._begin_session_run_generation(SESSION_KEY)
        getattr(runner, store_name)[SESSION_KEY] = value

    monkeypatch.setattr(gateway_run.TurnRunner, '_attach_session_title_callback', replace)
    result = await runner._run_agent(message='owned input', context_prompt='', history=[],
        source=_source(), session_id='owned-session', session_key=SESSION_KEY,
        run_generation=generation)
    assert getattr(runner, store_name).get(SESSION_KEY) == value
    assert not calls
    assert result['interrupted']


@pytest.mark.asyncio
async def test_legitimate_skill_note_survives_normal_next_generation(monkeypatch) -> None:
    import agent.skill_commands as commands
    runner = _make_runner(HookRecordingAdapter())
    key = runner._session_key_for_source(_source())
    runner._begin_session_run_generation(key)
    monkeypatch.setattr(commands, 'reload_skills', lambda: {
        'added': [{'name': 'legitimate', 'description': 'ready'}], 'removed': [], 'total': 1})
    await runner._handle_reload_skills_command(event('/reload-skills'))
    before = runner._pending_skills_reload_notes[key]
    runner._begin_session_run_generation(key)
    assert runner._pending_skills_reload_notes[key] == before
    assert 'legitimate' in before


def model_runner(monkeypatch):
    """Use real command/notes owners and synthetic model, config, transport leaves."""
    import gateway.run as gateway_run
    import gateway.slash_commands as slash
    import hermes_cli.context_switch_guard as warning
    import hermes_cli.model_selection_guards as selection
    import hermes_cli.model_switch as models

    class Picker(HookRecordingAdapter):
        callback = None

        async def send_model_picker(self, **kwargs):
            self.callback = kwargs['on_model_selected']
            return SendResult(success=True, message_id='owned-picker')

    adapter = Picker()
    runner = _make_runner(adapter)
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner.session_store = SimpleNamespace(_entries={})
    runner._session_db = None
    monkeypatch.setattr(runner, '_normalize_source_for_session_key', lambda source: source)
    monkeypatch.setattr(gateway_run, '_load_gateway_config', lambda **kwargs: {
        'model': {'default': 'before', 'provider': 'custom'}})
    monkeypatch.setattr(slash, '_model_switch_skew_guard', lambda: None)
    monkeypatch.setattr(warning, 'enrich_model_switch_warnings_for_gateway', lambda *a, **kw: None)
    monkeypatch.setattr(selection, 'combined_selection_warning', lambda *a, **kw: None)
    monkeypatch.setattr(models, 'list_picker_providers', lambda **kw: [{'slug': 'custom', 'models': []}])
    monkeypatch.setattr(models, 'resolve_display_context_length_async', AsyncMock(return_value=4096))
    monkeypatch.setattr(models, 'switch_model', lambda **kwargs: models.ModelSwitchResult(
        success=True, new_model=kwargs['raw_input'], target_provider='custom'))
    return runner, adapter, models


@pytest.mark.asyncio
@pytest.mark.parametrize('picker', [False, True], ids=['typed', 'retained-picker'])
@pytest.mark.parametrize('barrier', ['switch', 'db'])
async def test_late_model_producer_preserves_replacement(monkeypatch, picker, barrier) -> None:
    runner, adapter, models = model_runner(monkeypatch)
    key = runner._session_key_for_source(_source())
    runner._begin_session_run_generation(key)
    entered, release = asyncio.Event(), asyncio.Event()
    thread_gate = ThreadBarrier()
    if barrier == 'switch':
        def switch(**kwargs):
            thread_gate.wait()
            return models.ModelSwitchResult(success=True, new_model='old-choice', target_provider='custom')
        monkeypatch.setattr(models, 'switch_model', switch)
    else:
        async def update(*args, **kwargs):
            entered.set()
            await release.wait()
        runner._session_db = SimpleNamespace(update_session_model=update)
        runner._async_session_store = SimpleNamespace(_store=runner.session_store,
            get_or_create_session=AsyncMock(return_value=SimpleNamespace(session_id='owned', was_auto_reset=False)))
    if picker:
        await runner._handle_model_command(event('/model --session'))
        assert adapter.callback is not None
    operation = adapter.callback('4242', 'old-choice', 'custom') if picker else runner._handle_model_command(
        event('/model old-choice --session'))
    task = asyncio.create_task(operation)

    def replace() -> None:
        runner._invalidate_session_run_generation(key, reason='model barrier')
        runner._begin_session_run_generation(key)
        runner._pending_model_notes = {key: 'replacement model note'}

    if barrier == 'switch':
        await thread_gate.change(task, replace)
    else:
        try:
            await asyncio.wait_for(entered.wait(), 5)
            replace()
        finally:
            release.set()
        await asyncio.wait_for(task, 8)
    assert runner._pending_model_notes[key] == 'replacement model note'


@pytest.mark.asyncio
async def test_model_notes_keep_fifo_across_normal_turns(monkeypatch) -> None:
    runner, _, _ = model_runner(monkeypatch)
    key = runner._session_key_for_source(_source())
    runner._begin_session_run_generation(key)
    await runner._handle_model_command(event('/model first-choice --session'))
    await runner._handle_model_command(event('/model second-choice --session'))
    generation = runner._begin_session_run_generation(key)
    note = runner._consume_pending_shared_input(key, '_pending_model_notes', run_generation=generation)
    assert note.index('to first-choice') < note.index('to second-choice')
    assert runner._consume_pending_shared_input(key, '_pending_model_notes', run_generation=generation) is None


@pytest.mark.asyncio
async def test_skill_notes_keep_fifo_across_normal_turns(monkeypatch) -> None:
    import agent.skill_commands as commands
    runner = _make_runner(HookRecordingAdapter())
    key = runner._session_key_for_source(_source())
    for name in ('first-skill', 'second-skill'):
        monkeypatch.setattr(commands, 'reload_skills', lambda n=name: {
            'added': [{'name': n}], 'removed': [], 'total': 1})
        await runner._handle_reload_skills_command(event('/reload-skills'))
    generation = runner._begin_session_run_generation(key)
    note = runner._consume_pending_shared_input(key, '_pending_skills_reload_notes', run_generation=generation)
    assert note.index('first-skill') < note.index('second-skill')


@pytest.mark.asyncio
async def test_native_order_survives_normal_generation(monkeypatch) -> None:
    runner = _make_runner(HookRecordingAdapter())
    generation = runner._begin_session_run_generation(SESSION_KEY)
    monkeypatch.setattr(runner, '_decide_image_input_mode', lambda **kw: 'native')
    incoming = event(image='first.png')
    incoming.media_urls.append('second.png')
    incoming.media_types.append('image/png')
    await runner._prepare_inbound_message_text(event=incoming, source=_source(), history=[],
        session_key=SESSION_KEY, run_generation=generation)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    assert runner._consume_pending_native_image_paths(SESSION_KEY, run_generation=generation) == ['first.png', 'second.png']
    assert runner._consume_pending_native_image_paths(SESSION_KEY, run_generation=generation) == []


@pytest.mark.asyncio
async def test_delayed_reset_cleanup_preserves_replacement(monkeypatch) -> None:
    runner = _make_runner(HookRecordingAdapter())
    key = runner._session_key_for_source(_source())
    runner._agent_cache_lock = threading.Lock()
    runner._agent_cache = {key: (object(), 'owned')}
    runner.session_store = SimpleNamespace(_entries={})
    entered, release = asyncio.Event(), asyncio.Event()

    async def teardown(*args):
        entered.set()
        await release.wait()

    monkeypatch.setattr(runner, '_run_in_executor_with_context', teardown)
    monkeypatch.setattr(runner, '_evict_cached_agent', lambda key: None)
    task = asyncio.create_task(runner._handle_reset_command(event('/new')))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        runner._begin_session_run_generation(key)
        runner._pending_model_notes = {key: 'replacement model'}
        runner._pending_skills_reload_notes = {key: 'replacement skill'}
        runner._session_state(key).persistent.native_image_paths = ['replacement.png']
    finally:
        release.set()
    await asyncio.wait_for(task, 8)
    assert runner._pending_model_notes[key] == 'replacement model'
    assert runner._pending_skills_reload_notes[key] == 'replacement skill'
    assert runner._consume_pending_native_image_paths(key) == ['replacement.png']


@pytest.mark.parametrize('boundary', ['conversation', 'branch-input'])
def test_true_boundary_retires_old_producer_without_new_generation(boundary) -> None:
    runner = _make_runner(HookRecordingAdapter())
    owner = runner._capture_shared_input_owner(SESSION_KEY)
    assert runner._publish_pending_shared_input(owner, '_pending_model_notes', 'old model')
    assert runner._publish_pending_shared_input(owner, '_pending_skills_reload_notes', 'old skill')
    assert runner._publish_pending_shared_input(owner, '_pending_native_image_paths_by_session', ['old.png'])
    generation = runner._session_state(SESSION_KEY).persistent.run_generation
    if boundary == 'conversation':
        runner._clear_conversation_scope(SESSION_KEY, reason='owned boundary')
    else:
        runner._clear_session_boundary_security_state(SESSION_KEY)
    assert runner._session_state(SESSION_KEY).persistent.run_generation == generation
    assert not runner._publish_pending_shared_input(owner, '_pending_model_notes', 'late old model')
    assert not runner._pending_model_notes
    assert not runner._pending_skills_reload_notes
    assert not runner._consume_pending_native_image_paths(SESSION_KEY)


@pytest.mark.parametrize('kind', ['model', 'skill', 'native'])
@pytest.mark.parametrize('action', ['publish', 'consume', 'cleanup'])
def test_handoff_while_waiting_for_owner_lock_cannot_touch_replacement(kind, action) -> None:
    runner = _make_runner(HookRecordingAdapter())
    generation = runner._begin_session_run_generation(SESSION_KEY)
    owner = runner._capture_shared_input_owner(SESSION_KEY)
    state = runner._session_state(SESSION_KEY)
    waiting = threading.Event()
    main_thread = threading.get_ident()

    class ObservedLock:
        """Report a contender before acquisition, never while holding its lock."""
        def __init__(self):
            self.lock = threading.RLock()

        def __enter__(self):
            if threading.get_ident() != main_thread:
                waiting.set()
            self.lock.acquire()
            return self

        def __exit__(self, *args):
            self.lock.release()

    state.shared_input_lock = ObservedLock()
    attr = {'model': '_pending_model_notes', 'skill': '_pending_skills_reload_notes',
            'native': '_pending_native_image_paths_by_session'}[kind]
    replacement = ['replacement.png'] if kind == 'native' else 'replacement note'
    result, errors = [], []

    def old_worker():
        try:
            if action == 'publish':
                result.append(runner._publish_pending_shared_input(owner, attr, replacement))
            elif action == 'consume':
                result.append(runner._consume_pending_shared_input(SESSION_KEY, attr, run_generation=generation))
            else:
                result.append(runner._clear_conversation_scope(SESSION_KEY, reason='old cleanup', shared_input_owner=owner))
        except BaseException as exc:
            errors.append(exc)

    with state.shared_input_lock:
        worker = threading.Thread(target=old_worker)
        worker.start()
        assert waiting.wait(5), 'old operation must be contending for the actual owner lock'
        runner._begin_session_run_generation(SESSION_KEY)
        getattr(runner, attr, {})[SESSION_KEY] = replacement
        if kind != 'native':
            setattr(runner, attr, {SESSION_KEY: replacement})
    worker.join(5)
    assert not worker.is_alive()
    assert not errors
    assert result == ([None] if action == 'consume' else [False])
    assert getattr(runner, attr)[SESSION_KEY] == replacement


@pytest.mark.asyncio
async def test_retained_picker_from_retired_run_refuses_before_model_work(monkeypatch) -> None:
    runner, adapter, models = model_runner(monkeypatch)
    key = runner._session_key_for_source(_source())
    calls = []
    def switch(**kwargs):
        calls.append(kwargs['raw_input'])
        return models.ModelSwitchResult(success=True, new_model=kwargs['raw_input'], target_provider='custom')
    monkeypatch.setattr(models, 'switch_model', switch)
    await runner._handle_model_command(event('/model --session'))
    runner._invalidate_session_run_generation(key, reason='picker retired')
    # The registered closure captured its original model leaf; the observable
    # note oracle below also catches a callback that ignores its captured owner.
    runner._pending_model_notes = {key: 'replacement model'}
    result = await adapter.callback('4242', 'retired-selection', 'custom')
    assert 'superseded' in result
    assert not calls
    assert runner._pending_model_notes[key] == 'replacement model'


@pytest.mark.asyncio
async def test_model_ingress_owner_is_not_recaptured_after_normalization(monkeypatch) -> None:
    runner, _, _ = model_runner(monkeypatch)
    key = runner._session_key_for_source(_source())
    gate = ThreadBarrier()

    def normalize(source):
        gate.wait()
        return source

    monkeypatch.setattr(runner, '_normalize_source_for_session_key', normalize)
    task = asyncio.create_task(runner._handle_model_command(event('/model old-choice --session')))

    def replace():
        runner._begin_session_run_generation(key)
        runner._pending_model_notes = {key: 'replacement model'}

    await gate.change(task, replace)
    assert runner._pending_model_notes[key] == 'replacement model'


@pytest.mark.asyncio
async def test_skill_publication_after_adapter_refresh_await_is_fenced(monkeypatch) -> None:
    import agent.skill_commands as commands
    runner = _make_runner(HookRecordingAdapter())
    key = runner._session_key_for_source(_source())
    entered, release = asyncio.Event(), asyncio.Event()

    async def refresh():
        entered.set()
        await release.wait()

    next(iter(runner.adapters.values())).refresh_skill_group = refresh
    monkeypatch.setattr(commands, 'reload_skills', lambda: {
        'added': [{'name': 'stale-skill'}], 'removed': [], 'total': 1})
    task = asyncio.create_task(runner._handle_reload_skills_command(event('/reload-skills')))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        runner._begin_session_run_generation(key)
        runner._pending_skills_reload_notes = {key: 'replacement skill'}
    finally:
        release.set()
    await asyncio.wait_for(task, 8)
    assert runner._pending_skills_reload_notes[key] == 'replacement skill'


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True], ids=['notes', 'native-images'])
async def test_current_real_turn_consumes_next_turn_inputs_once(monkeypatch, tmp_path, native) -> None:
    runner = _make_runner(HookRecordingAdapter())
    first_generation = runner._begin_session_run_generation(SESSION_KEY)
    calls = []

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            calls.append(message)
            return {'final_response': 'owned reply', 'messages': [], 'api_calls': 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    if native:
        import base64
        image = tmp_path / 'owned.png'
        image.write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jk1sAAAAASUVORK5CYII='))
        runner._pending_native_image_paths_by_session[SESSION_KEY] = [str(image)]
    else:
        runner._pending_model_notes = {SESSION_KEY: 'legitimate model note'}
        runner._pending_skills_reload_notes = {SESSION_KEY: 'legitimate skill note'}
    generation = runner._begin_session_run_generation(SESSION_KEY)
    assert generation > first_generation
    await runner._run_agent(message='owned input', context_prompt='', history=[], source=_source(),
        session_id='owned-session', session_key=SESSION_KEY, run_generation=generation)
    assert len(calls) == 1
    if native:
        assert isinstance(calls[0], list)
        assert len([part for part in calls[0] if part.get('type') == 'image_url']) == 1
        assert not runner._consume_pending_native_image_paths(SESSION_KEY)
    else:
        assert 'legitimate model note' in calls[0]
        assert 'legitimate skill note' in calls[0]
        assert SESSION_KEY not in runner._pending_model_notes
        assert SESSION_KEY not in runner._pending_skills_reload_notes
