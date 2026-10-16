"""Branch publication phases retain real persisted state and recoverable IDs."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent.i18n import t
from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.slash_commands_branch_thread import branch_dest_source
from tests.gateway.test_branch_thread_contract import seed, source, surface


def _session_ids(store):
    with store._db._read_ctx() as conn:
        return [row[0] for row in conn.execute('SELECT id FROM sessions ORDER BY id')]


@pytest.mark.asyncio
async def test_child_create_failure_reports_the_already_created_thread(surface, monkeypatch):
    runner, store, _, connector, _ = surface
    original = source()
    parent = seed(store, original)
    def fail(*args, **kwargs):
        raise RuntimeError('owned create failure')
    monkeypatch.setattr(store._db, 'create_session', fail)
    reply = await runner._handle_branch_command(MessageEvent(text='/branch Child', source=original))
    assert len(connector.sent) == 1
    assert 'owned-child-thread' in reply
    assert store.get_or_create_session(original).session_id == parent
    assert store._db.get_session(parent)['ended_at'] is None
    assert _session_ids(store) == [parent]


@pytest.mark.parametrize('failure', ['copy_zero', 'copy_partial', 'title'])
@pytest.mark.parametrize('stay_here', [False, True])
@pytest.mark.asyncio
async def test_best_effort_branch_reports_degraded_persistence_without_a_copy_count(surface, monkeypatch, failure, stay_here):
    runner, store, _, connector, _ = surface
    original = source()
    parent = seed(store, original)
    store._db.append_message(parent, role='assistant', content='Retained answer')
    copy = store._db.append_messages_batch
    def fail_copy(session_id, messages, **kwargs):
        if failure == 'copy_partial':
            copy(session_id, messages[:1], **kwargs)
        raise RuntimeError('owned interrupted copy')
    def fail_title(*args, **kwargs):
        raise RuntimeError('owned title failure')
    monkeypatch.setattr(store._db, 'set_session_title' if failure == 'title' else 'append_messages_batch',
                        fail_title if failure == 'title' else fail_copy)
    reply = await runner._handle_branch_command(MessageEvent(text='/branch ' + ('--here ' if stay_here else '') + 'Child', source=original))
    destination = original if stay_here else branch_dest_source(original, parent_id=original.chat_id,
                                                                thread_id='owned-child-thread', title='Child')
    child = store.get_or_create_session(destination).session_id
    assert child != parent
    row = store._db.get_session(child)
    assert row['parent_session_id'] == parent
    assert row['system_prompt'] == 'PARENT PREFIX scope-a'
    assert len(store._db.get_messages(child)) == {'copy_zero': 0, 'copy_partial': 1, 'title': 2}[failure]
    assert row['title'] is None if failure == 'title' else row['title'] == 'Child'
    assert parent in reply and child in reply
    assert t('gateway.branch.persistence_incomplete', parent=parent, new=child) in reply
    assert 'message copied' not in reply and 'messages copied' not in reply
    if not stay_here:
        assert 'owned-child-thread' in reply
        assert store.get_or_create_session(original).session_id == parent
    assert len(connector.sent) == (0 if stay_here else 1)


@pytest.mark.parametrize('phase', ['materialize', 'switch_raise', 'switch_none'])
@pytest.mark.asyncio
async def test_destination_binding_failure_reports_saved_child_and_thread(surface, monkeypatch, phase):
    runner, store, _, connector, _ = surface
    original = source()
    parent = seed(store, original)
    created = []
    create = store._db.create_session
    def record_create(*args, **kwargs):
        result = create(*args, **kwargs)
        if kwargs.get('parent_session_id') == parent:
            created.append(kwargs['session_id'])
        return result
    monkeypatch.setattr(store._db, 'create_session', record_create)
    if phase == 'materialize':
        get_or_create = store.get_or_create_session
        def fail_destination(src, *args, **kwargs):
            if src.thread_id == 'owned-child-thread':
                raise RuntimeError('owned destination materialize failure')
            return get_or_create(src, *args, **kwargs)
        monkeypatch.setattr(store, 'get_or_create_session', fail_destination)
    else:
        def fail_switch(*args, **kwargs):
            if phase == 'switch_none':
                return None
            raise RuntimeError('owned destination switch failure')
        monkeypatch.setattr(store, 'switch_session', fail_switch)
    reply, escaped_error = None, None
    try:
        reply = await runner._handle_branch_command(MessageEvent(text='/branch Child', source=original))
    except RuntimeError as exc:
        escaped_error = str(exc)
    assert len(connector.sent) == 1 and len(created) == 1
    child = created[0]
    row = store._db.get_session(child)
    assert row['parent_session_id'] == parent
    assert row['chat_id'] == original.chat_id and row['thread_id'] == 'owned-child-thread'
    assert row['session_key'] != store._db.get_session(parent)['session_key']
    origin = json.loads(row['origin_json'])
    assert origin['scope_id'] == 'scope-a' and origin['user_id'] == 'author-a'
    assert origin['thread_id'] == 'owned-child-thread'
    assert store._db.get_messages_as_conversation(child) == store._db.get_messages_as_conversation(parent)
    assert store.get_or_create_session(original).session_id == parent
    assert escaped_error is None, escaped_error
    assert parent in reply and child in reply and 'owned-child-thread' in reply
    assert t('gateway.branch.binding_incomplete', parent=parent, new=child) in reply


@pytest.mark.asyncio
async def test_thread_marker_failure_reports_created_thread_without_creating_child(surface, monkeypatch):
    runner, store, adapter, connector, _ = surface
    original = source(Platform.DISCORD)
    parent = seed(store, original)
    async def fail_marker(thread_id):
        assert thread_id == 'owned-child-thread'
        raise RuntimeError('owned marker failure')
    monkeypatch.setattr(adapter, '_threads', SimpleNamespace(mark_async=fail_marker), raising=False)
    reply, escaped_error = None, None
    try:
        reply = await runner._handle_branch_command(MessageEvent(text='/branch Child', source=original))
    except RuntimeError as exc:
        escaped_error = str(exc)
    assert len(connector.sent) == 1
    assert store.get_or_create_session(original).session_id == parent
    assert _session_ids(store) == [parent]
    assert escaped_error is None, escaped_error
    assert 'owned-child-thread' in reply


@pytest.mark.parametrize('platform', [Platform.DISCORD, Platform.TELEGRAM, Platform.SLACK, Platform.MATRIX])
@pytest.mark.asyncio
async def test_native_two_argument_thread_adapter_preserves_source_destination(surface, platform):
    runner, store, _, _, _ = surface
    calls = []
    class NativeAdapter:
        async def create_handoff_thread(self, parent_chat_id, name):
            calls.append((parent_chat_id, name))
            return 'owned-native-thread'
    original = replace(source(platform), delivered_via_upstream_relay=False)
    runner.adapters = {platform: NativeAdapter()}
    parent = seed(store, original)
    reply = await runner._handle_branch_command(MessageEvent(text='/branch Native Child', source=original))
    destination = branch_dest_source(original, parent_id=original.chat_id, thread_id='owned-native-thread', title='Native Child')
    child = store.get_or_create_session(destination).session_id
    assert calls == [(original.chat_id, 'Native Child')]
    assert store.get_or_create_session(original).session_id == parent
    assert store._db.get_session(child)['parent_session_id'] == parent
    assert store._db.get_messages_as_conversation(child) == store._db.get_messages_as_conversation(parent)
    assert 'owned-native-thread' in reply


@pytest.mark.parametrize('reason', ['discord_dm', 'unknown_discord_parent', 'nonfronted_matrix', 'adapter_declines', 'adapter_raises'])
@pytest.mark.asyncio
async def test_thread_unavailability_branches_in_place_without_repeated_creation(surface, reason):
    runner, store, _, connector, _ = surface
    original = source(Platform.DISCORD)
    calls = []
    if reason == 'discord_dm':
        original = replace(original, chat_type='dm')
    elif reason == 'unknown_discord_parent':
        original = replace(original, chat_id='old-thread', thread_id='old-thread', chat_type='thread', parent_chat_id=None)
    elif reason == 'nonfronted_matrix':
        original = source(Platform.MATRIX)
    else:
        class UnavailableAdapter:
            async def create_handoff_thread(self, parent_chat_id, name):
                calls.append((parent_chat_id, name))
                if reason == 'adapter_raises':
                    raise RuntimeError('owned native creation unavailable')
                return None
        original = replace(original, delivered_via_upstream_relay=False)
        runner.adapters = {Platform.DISCORD: UnavailableAdapter()}
    parent = seed(store, original)
    reply = await runner._handle_branch_command(MessageEvent(text='/branch Child', source=original))
    child = store.get_or_create_session(original).session_id
    assert child != parent
    assert store._db.get_session(child)['parent_session_id'] == parent
    assert store._db.get_session(child)['title'] == 'Child'
    assert store._db.get_messages_as_conversation(child) == store._db.get_messages_as_conversation(parent)
    assert t('gateway.branch.thread_fallback') in reply
    assert calls == ([(original.chat_id, 'Child')] if reason.startswith('adapter_') else [])
    assert connector.sent == []
