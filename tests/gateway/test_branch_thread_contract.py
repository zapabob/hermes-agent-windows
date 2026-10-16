"""Branch destination identity through actual gateway/relay and SQLite owners."""

from dataclasses import replace

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.relay.adapter import RelayAdapter
from gateway.session import SessionSource, SessionStore
from tests.gateway.relay.stub_connector import StubConnector
from tests.gateway.relay.test_relay_threads import make_desc
from tests.gateway.test_branch_routing_columns import _make_branch_runner


@pytest.fixture
def surface(tmp_path, monkeypatch):
    import hermes_state
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(hermes_state, 'DEFAULT_DB_PATH', tmp_path / 'state.db')
    store = SessionStore(sessions_dir=tmp_path / 'sessions', config=GatewayConfig())
    runner = _make_branch_runner(store)
    runner.config = GatewayConfig()
    primary = make_desc(platform='discord')
    connector = StubConnector(primary)
    connector._identities = [('discord', 'owned-d'), ('slack', 'owned-s')]
    descriptors = {'discord': primary, 'slack': make_desc(platform='slack')}
    connector.descriptor_for_platform = descriptors.get
    adapter = RelayAdapter(PlatformConfig(enabled=True), primary, transport=connector)
    runner.adapters = {Platform.RELAY: adapter}
    async def outbound(action, *, platform=None):
        connector.sent.append(action)
        connector.sent_platforms.append(platform)
        return {'success': True, 'thread_id': 'owned-child-thread'}
    connector.send_outbound = outbound
    yield runner, store, adapter, connector, descriptors
    store._db.close()


def source(platform=Platform.SLACK, **kwargs):
    return SessionSource(platform=platform, chat_id='shared-chat', chat_type='group',
                         scope_id='scope-a', user_id='author-a', delivered_via_upstream_relay=True, **kwargs)


def seed(store, src):
    entry = store.get_or_create_session(src)
    store._db.update_system_prompt(entry.session_id, 'PARENT PREFIX ' + str(src.scope_id))
    store._db.append_message(entry.session_id, role='user', content='Original ' + str(src.scope_id))
    return entry.session_id


@pytest.mark.asyncio
async def test_thread_branch_uses_explicit_source_over_colliding_chat_caches(surface):
    runner, store, adapter, connector, _ = surface
    original = source()
    collision = replace(original, platform=Platform.DISCORD, scope_id='scope-b', user_id='author-b')
    parent = seed(store, original)
    other_parent = seed(store, collision)
    adapter._capture_scope(MessageEvent(text='original', source=original))
    adapter._capture_scope(MessageEvent(text='collision', source=collision))
    reply = await runner._handle_branch_command(MessageEvent(text='/branch KeepCase 日本語', source=original))
    assert len(connector.sent) == 1
    assert connector.sent_platforms == ['slack']
    action = connector.sent[0]
    assert action['op'] == 'thread_create'
    assert action['chat_id'] == 'shared-chat'
    assert action['metadata']['scope_id'] == 'scope-a'
    assert action['metadata']['user_id'] == 'author-a'
    destination = replace(original, thread_id='owned-child-thread', message_id=None)
    child = store.get_or_create_session(destination).session_id
    assert child != parent
    assert store.get_or_create_session(original).session_id == parent
    assert store.get_or_create_session(collision).session_id == other_parent
    assert store._db.get_session(child)['parent_session_id'] == parent
    assert store._db.get_session(child)['system_prompt'] == 'PARENT PREFIX scope-a'
    assert store._db.get_messages_as_conversation(child) == store._db.get_messages_as_conversation(parent)
    assert 'owned-child-thread' in reply


@pytest.mark.asyncio
async def test_existing_discord_thread_branches_under_cold_real_parent(surface):
    runner, store, adapter, connector, _ = surface
    original = replace(source(Platform.DISCORD), chat_id='owned-old-thread', thread_id='owned-old-thread',
                       chat_type='thread', parent_chat_id='cold-parent')
    parent = seed(store, original)
    adapter._capture_scope(MessageEvent(text='original', source=original))
    await runner._handle_branch_command(MessageEvent(text='/branch Child', source=original))
    assert len(connector.sent) == 1
    assert connector.sent_platforms == ['discord']
    assert connector.sent[0]['chat_id'] == 'cold-parent'
    assert connector.sent[0]['metadata']['scope_id'] == 'scope-a'
    assert connector.sent[0]['metadata']['user_id'] == 'author-a'
    destination = replace(original, chat_id='owned-child-thread', thread_id='owned-child-thread',
                          parent_chat_id='cold-parent', message_id=None)
    child = store.get_or_create_session(destination).session_id
    assert store._db.get_session(child)['parent_session_id'] == parent
    assert store.get_or_create_session(original).session_id == parent


@pytest.mark.parametrize('primary_allowed, requested_allowed', [(True, False), (False, True)])
@pytest.mark.asyncio
async def test_requested_platform_negotiated_op_is_the_thread_create_authority(surface, primary_allowed, requested_allowed):
    runner, store, adapter, connector, descriptors = surface
    adapter.descriptor = make_desc(platform='discord', supported_ops=('send', 'thread_create') if primary_allowed else ('send',))
    descriptors['slack'] = make_desc(platform='slack', supported_ops=('send', 'thread_create') if requested_allowed else ('send',))
    original = source()
    parent = seed(store, original)
    await runner._handle_branch_command(MessageEvent(text='/branch Child', source=original))
    assert len(connector.sent) == int(requested_allowed)
    if requested_allowed:
        assert connector.sent_platforms == ['slack']
        assert store.get_or_create_session(original).session_id == parent
    else:
        assert store.get_or_create_session(original).session_id != parent


@pytest.mark.asyncio
async def test_here_switches_in_place_without_a_relay_thread_op(surface):
    runner, store, _, connector, _ = surface
    original = source()
    parent = seed(store, original)
    await runner._handle_branch_command(MessageEvent(text='/branch --here KeepCase 日本語', source=original))
    child = store.get_or_create_session(original).session_id
    assert child != parent
    assert store._db.get_session(child)['title'] == 'KeepCase 日本語'
    assert connector.sent == []


@pytest.mark.parametrize('scope,author', [(None, None), ('', ''), ('scope-a', None), (None, 'author-a')])
@pytest.mark.asyncio
async def test_unknown_source_identity_never_borrows_colliding_chat_identity(surface, scope, author):
    runner, store, adapter, connector, _ = surface
    original = replace(source(), scope_id=scope, guild_id=None, user_id=author)
    seed(store, original)
    adapter._capture_scope(MessageEvent(text='collision', source=replace(source(Platform.DISCORD),
                                                                       scope_id='foreign-scope', user_id='foreign-author')))
    await runner._handle_branch_command(MessageEvent(text='/branch Child', source=original))
    assert len(connector.sent) == 1
    assert connector.sent_platforms == ['slack']
    metadata = connector.sent[0]['metadata']
    assert metadata.get('scope_id') == scope
    assert metadata.get('user_id') == author


@pytest.mark.parametrize('provenance', [True, False])
@pytest.mark.asyncio
async def test_existing_handoff_thread_uses_configured_home_not_chat_cache(surface, monkeypatch, provenance):
    from gateway.config import HomeChannel

    runner, store, adapter, connector, _ = surface
    home = HomeChannel(platform=Platform.SLACK, chat_id='shared-chat', name='Owned home',
                       scope_id='home-scope' if provenance else None,
                       user_id='home-author' if provenance else None)
    runner.config.platforms[Platform.SLACK] = PlatformConfig(enabled=True, home_channel=home)
    adapter._capture_scope(MessageEvent(text='collision', source=replace(source(Platform.DISCORD),
                                                                       scope_id='foreign-scope', user_id='foreign-author')))
    store._db.create_session('owned-cli', source='cli')
    synthetic_sources = []
    async def owned_response(event):
        synthetic_sources.append(event.source)
        return 'Owned handoff reply'
    monkeypatch.setattr(runner, '_handle_message', owned_response)
    monkeypatch.setattr(runner, '_release_running_agent_state', lambda *args: None)
    await runner._process_handoff({'id': 'owned-cli', 'handoff_platform': 'slack', 'title': 'Owned CLI'})
    assert len(connector.sent) == 2
    assert connector.sent_platforms == ['slack', 'slack']
    assert [frame['op'] for frame in connector.sent] == ['thread_create', 'send']
    for frame in connector.sent:
        assert frame['metadata'].get('scope_id') == home.scope_id
        assert frame['metadata'].get('user_id') == home.user_id
    assert synthetic_sources[0].scope_id == home.scope_id
    assert synthetic_sources[0].user_id == home.user_id
    assert synthetic_sources[0].delivered_via_upstream_relay is True


@pytest.mark.parametrize('metadata_owner', ['adapter', 'runner'])
@pytest.mark.asyncio
async def test_edit_based_first_reply_keeps_source_identity(surface, metadata_owner):
    from gateway.platforms.base import _thread_metadata_for_source

    runner, _, adapter, connector, _ = surface
    original = replace(source(), thread_id='owned-child-thread')
    adapter._capture_scope(MessageEvent(text='collision', source=replace(original, platform=Platform.DISCORD,
                                                                       scope_id='foreign-scope', user_id='foreign-author')))
    metadata = (_thread_metadata_for_source(original) if metadata_owner == 'adapter'
                else runner._thread_metadata_for_source(original))
    result = await adapter.edit_message(original.chat_id, 'owned-first-message', 'Owned final edit', finalize=True, metadata=metadata)
    assert result.success
    assert connector.sent_platforms == ['slack']
    assert connector.sent[0]['op'] == 'edit'
    assert connector.sent[0]['metadata']['scope_id'] == 'scope-a'
    assert connector.sent[0]['metadata']['user_id'] == 'author-a'
    assert not any(key.startswith('_relay_') for key in connector.sent[0]['metadata'])


@pytest.mark.parametrize('metadata_owner', ['adapter', 'runner'])
@pytest.mark.parametrize('platform,scope,author', [('slack', 'scope-a', 'author-a'),
                                                ('discord', 'scope-a', 'author-a'),
                                                ('slack', None, None), ('discord', '', '')])
@pytest.mark.asyncio
async def test_first_thread_reply_uses_source_identity_after_cache_collision(surface, metadata_owner, platform, scope, author):
    from gateway.platforms.base import _thread_metadata_for_source
    from gateway.slash_commands_branch_thread import branch_dest_source

    runner, _, adapter, connector, _ = surface
    original = replace(source(Platform(platform)), scope_id=scope, guild_id=None, user_id=author)
    destination = branch_dest_source(original, parent_id='shared-chat', thread_id='owned-child-thread', title='Child')
    collision = replace(destination, platform=Platform.DISCORD if platform == 'slack' else Platform.SLACK,
                        scope_id='foreign-scope', user_id='foreign-author')
    adapter._capture_scope(MessageEvent(text='collision', source=collision))
    metadata = (_thread_metadata_for_source(destination) if metadata_owner == 'adapter'
                else runner._thread_metadata_for_source(destination))
    result = await adapter.send(destination.chat_id, 'Owned first reply', metadata=metadata)
    assert result.success
    assert connector.sent_platforms == [platform]
    frame = connector.sent[0]
    assert frame['op'] == 'send'
    assert frame['metadata'].get('scope_id') == scope
    assert frame['metadata'].get('user_id') == author
    assert frame['metadata']['thread_id'] == 'owned-child-thread'


@pytest.mark.parametrize('lane', ['send', 'send_for_platform', 'abandon'])
@pytest.mark.parametrize('collide_before_draft', [False, True])
@pytest.mark.asyncio
async def test_scoped_draft_and_final_keep_the_authentic_route(surface, lane, collide_before_draft):
    from gateway.platforms.base import _thread_metadata_for_source

    _, _, adapter, connector, descriptors = surface
    descriptors['slack'] = make_desc(platform='slack', supports_draft_streaming=True,
                                     supported_ops=('send', 'draft'))
    original = replace(source(), thread_id='owned-child-thread')
    collision = replace(original, platform=Platform.DISCORD, scope_id='foreign-scope', user_id='foreign-author')
    metadata = dict(_thread_metadata_for_source(original), message_id='owned-turn')
    adapter._capture_scope(MessageEvent(text='original', source=original))
    if collide_before_draft:
        adapter._capture_scope(MessageEvent(text='collision', source=collision))
    try:
        draft = await adapter.send_draft(original.chat_id, 71, 'Owned partial', metadata=metadata)
    except NotImplementedError as exc:
        draft = None
        draft_error = str(exc)
    assert draft is not None and draft.success, locals().get('draft_error')
    adapter._capture_scope(MessageEvent(text='collision', source=collision))
    if lane == 'send':
        final = await adapter.send(original.chat_id, 'Owned final', metadata=metadata)
    elif lane == 'send_for_platform':
        final = await adapter.send_for_platform(Platform.SLACK, original.chat_id, 'Owned final', metadata=metadata)
    else:
        final = await adapter.abandon_open_draft(original.chat_id, 'Owned final', metadata=metadata)
    assert final.success
    assert [(frame['op'], frame.get('final')) for frame in connector.sent] == [('draft', False), ('draft', True)]
    assert connector.sent_platforms == ['slack', 'slack']
    for frame in connector.sent:
        assert frame['metadata']['scope_id'] == 'scope-a'
        assert frame['metadata']['user_id'] == 'author-a'
        assert not any(key.startswith('_relay_') for key in frame['metadata'])
    assert adapter._open_draft_by_chat == {}
    await adapter.send_draft(original.chat_id, 71, 'Owned late partial', metadata=metadata)
    assert len(connector.sent) == 2


@pytest.mark.asyncio
async def test_same_chat_and_turn_in_different_scopes_keep_independent_drafts(surface):
    from gateway.platforms.base import _thread_metadata_for_source

    _, _, adapter, connector, descriptors = surface
    descriptors['slack'] = make_desc(platform='slack', supports_draft_streaming=True, supported_ops=('send', 'draft'))
    first = replace(source(), thread_id='same-thread')
    second = replace(first, scope_id='scope-b', user_id='author-b')
    first_metadata = dict(_thread_metadata_for_source(first), message_id='same-turn-id')
    second_metadata = dict(_thread_metadata_for_source(second), message_id='same-turn-id')
    adapter._capture_scope(MessageEvent(text='first', source=first))
    await adapter.send_draft(first.chat_id, 81, 'First partial', metadata=first_metadata)
    adapter._capture_scope(MessageEvent(text='second', source=second))
    await adapter.send_draft(second.chat_id, 82, 'Second partial', metadata=second_metadata)
    assert len(adapter._open_draft_by_chat) == 2
    await adapter.send(first.chat_id, 'First final', metadata=first_metadata)
    await adapter.send(second.chat_id, 'Second final', metadata=second_metadata)
    seals = [frame for frame in connector.sent if frame.get('final')]
    assert [(frame['draft_id'], frame['metadata']['scope_id'], frame['content']) for frame in seals] == [
        (81, 'scope-a', 'First final'), (82, 'scope-b', 'Second final')]
    assert adapter._open_draft_by_chat == {}


@pytest.mark.parametrize('metadata_owner', ['adapter', 'runner'])
@pytest.mark.parametrize('reply_in_thread,real_thread', [(True, None), (False, None), (False, 'real-thread')])
@pytest.mark.asyncio
async def test_source_reply_preserves_slack_dm_placement_after_collision(surface, metadata_owner, reply_in_thread, real_thread):
    from gateway.platforms.base import _thread_metadata_for_source

    runner, _, adapter, connector, _ = surface
    adapter.config.extra['reply_in_thread'] = reply_in_thread
    original = replace(source(), chat_type='dm', thread_id=real_thread)
    collision = replace(original, platform=Platform.DISCORD, chat_type='group', scope_id='foreign-scope', user_id='foreign-author')
    adapter._capture_scope(MessageEvent(text='collision', source=collision))
    metadata = (_thread_metadata_for_source(original) if metadata_owner == 'adapter'
                else runner._thread_metadata_for_source(original))
    result = await adapter.send(original.chat_id, 'Owned DM reply', reply_to='trigger-ts', metadata=metadata)
    assert result.success
    assert connector.sent_platforms == ['slack']
    expected_anchor = real_thread or ('trigger-ts' if reply_in_thread else None)
    assert connector.sent[0]['metadata'].get('thread_id') == expected_anchor
    assert connector.sent[0]['reply_to'] == ('trigger-ts' if reply_in_thread or real_thread else None)


@pytest.mark.asyncio
async def test_actual_consumer_keeps_slack_segments_in_one_source_owned_stream(surface):
    from gateway.platforms.base import _thread_metadata_for_source
    from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig

    _, _, adapter, connector, descriptors = surface
    descriptors['slack'] = make_desc(platform='slack', supports_draft_streaming=True, supported_ops=('send', 'draft'))
    original = replace(source(), thread_id='owned-child-thread')
    adapter._capture_scope(MessageEvent(text='collision', source=replace(original, platform=Platform.DISCORD,
                                                                       scope_id='foreign-scope', user_id='foreign-author')))
    async def record_frame(frame, *, platform=None):
        connector.sent.append(frame)
        connector.sent_platforms.append(platform)
        return {'success': True, 'message_id': 'owned-stream-message'}
    connector.send_outbound = record_frame
    consumer = GatewayStreamConsumer(adapter, original.chat_id,
                                     config=StreamConsumerConfig(transport='draft', chat_type='group', edit_interval=0),
                                     metadata=_thread_metadata_for_source(original), initial_reply_to_id='owned-turn')
    consumer.on_delta('Owned first segment.')
    consumer.on_segment_break()
    consumer.on_delta('Owned second segment.')
    consumer.finish()
    await consumer.run()
    final_frames = [frame for frame in connector.sent if frame.get('final') or frame['op'] == 'send']
    assert len(final_frames) == 1, connector.sent
    assert final_frames[0]['op'] == 'draft'
    assert 'Owned first segment.' in final_frames[0]['content']
    assert 'Owned second segment.' in final_frames[0]['content']
    assert all(platform == 'slack' for platform in connector.sent_platforms)
    assert consumer.final_response_sent
    assert adapter._open_draft_by_chat == {}


@pytest.mark.asyncio
async def test_placement_only_final_seals_only_its_source_namespace(surface):
    from gateway.platforms.base import _thread_metadata_for_source

    _, _, adapter, connector, descriptors = surface
    descriptors['slack'] = make_desc(platform='slack', supports_draft_streaming=True, supported_ops=('send', 'draft'))
    first = replace(source(), thread_id='same-thread')
    second = replace(first, scope_id='scope-b', user_id='author-b')
    first_metadata = _thread_metadata_for_source(first)
    second_metadata = _thread_metadata_for_source(second)
    await adapter.send_draft(first.chat_id, 91, 'First partial', metadata=dict(first_metadata, message_id='first-turn'))
    await adapter.send_draft(second.chat_id, 92, 'Second partial', metadata=dict(second_metadata, message_id='second-turn'))
    result = await adapter.send(first.chat_id, 'First placement final', metadata=first_metadata)
    assert result.success
    assert connector.sent[-1]['final'] is True
    assert connector.sent[-1]['draft_id'] == 91
    assert connector.sent[-1]['metadata']['scope_id'] == 'scope-a'
    assert list(adapter._open_draft_by_chat.values()) == [92]
    await adapter.send(second.chat_id, 'Second placement final', metadata=second_metadata)
    assert connector.sent[-1]['draft_id'] == 92
    assert adapter._open_draft_by_chat == {}


@pytest.mark.asyncio
async def test_legacy_final_does_not_absorb_a_scoped_stream(surface):
    from gateway.platforms.base import _thread_metadata_for_source

    _, _, adapter, connector, descriptors = surface
    descriptors['slack'] = make_desc(platform='slack', supports_draft_streaming=True, supported_ops=('send', 'draft'))
    original = replace(source(), thread_id='owned-thread')
    metadata = dict(_thread_metadata_for_source(original), message_id='owned-turn')
    adapter._capture_scope(MessageEvent(text='original', source=original))
    await adapter.send_draft(original.chat_id, 93, 'Owned partial', metadata=metadata)
    result = await adapter.send(original.chat_id, 'Unscoped final')
    assert result.success
    assert connector.sent[-1]['op'] == 'send'
    assert list(adapter._open_draft_by_chat.values()) == [93]
    await adapter.send(original.chat_id, 'Owned final', metadata=metadata)
    assert adapter._open_draft_by_chat == {}


@pytest.mark.parametrize('outcome', ['draft_ambiguous', 'draft_exception', 'draft_rejected', 'seal_retry_success', 'seal_retry_lost'])
@pytest.mark.asyncio
async def test_source_owned_stream_preserves_route_and_other_stream_on_transport_failures(surface, outcome):
    from gateway.platforms.base import _thread_metadata_for_source

    _, _, adapter, connector, descriptors = surface
    descriptors['slack'] = make_desc(platform='slack', supports_draft_streaming=True, supported_ops=('send', 'draft'))
    original = replace(source(), thread_id='owned-thread')
    other = replace(original, scope_id='other-scope', user_id='other-author')
    metadata = dict(_thread_metadata_for_source(original), message_id='same-turn')
    other_metadata = dict(_thread_metadata_for_source(other), message_id='same-turn')
    await adapter.send_draft(other.chat_id, 94, 'Other partial', metadata=other_metadata)
    other_key = next(iter(adapter._open_draft_by_chat))
    seal_attempts = []

    async def respond(frame, *, platform=None):
        connector.sent.append(frame)
        connector.sent_platforms.append(platform)
        if frame['op'] == 'draft' and not frame['final']:
            if outcome == 'draft_exception':
                raise TimeoutError('owned fixture lost draft ack')
            if outcome == 'draft_ambiguous':
                return {'success': False, 'ambiguous': True, 'error': 'owned fixture lost draft ack'}
            if outcome == 'draft_rejected':
                return {'success': False, 'error': 'owned fixture rejected draft'}
        if frame.get('final'):
            seal_attempts.append(frame)
            if outcome == 'seal_retry_lost' or (outcome == 'seal_retry_success' and len(seal_attempts) == 1):
                return {'success': False, 'ambiguous': True, 'error': 'owned fixture lost seal ack'}
        return {'success': True, 'message_id': 'owned-message'}

    connector.send_outbound = respond
    adapter._capture_scope(MessageEvent(text='collision', source=replace(original, platform=Platform.DISCORD,
                                                                       scope_id='foreign-scope', user_id='foreign-author')))
    draft = await adapter.send_draft(original.chat_id, 95, 'Owned partial', metadata=metadata)
    assert draft.success is (outcome not in {'draft_ambiguous', 'draft_exception', 'draft_rejected'})
    final = await adapter.send(original.chat_id, 'Owned final', metadata=metadata)
    assert final.success
    assert adapter._open_draft_by_chat == {other_key: 94}
    own_frames = connector.sent[1:]
    assert all(platform == 'slack' for platform in connector.sent_platforms[1:])
    for frame in own_frames:
        assert frame['metadata']['scope_id'] == 'scope-a'
        assert frame['metadata']['user_id'] == 'author-a'
        assert not any(key.startswith('_relay_') for key in frame['metadata'])
    if outcome.startswith('seal_retry'):
        assert len(seal_attempts) == 2
        assert seal_attempts[0] is seal_attempts[1]
    if outcome in {'draft_rejected', 'seal_retry_lost'}:
        assert own_frames[-1]['op'] == 'send'
    else:
        assert own_frames[-1]['op'] == 'draft' and own_frames[-1]['final'] is True


@pytest.mark.parametrize('platform', ['matrix', 'unknown-platform'])
@pytest.mark.asyncio
async def test_nonfronted_source_send_cannot_seal_or_take_an_existing_stream(surface, platform):
    from gateway.platforms.base import _thread_metadata_for_source

    _, _, adapter, connector, descriptors = surface
    descriptors['slack'] = make_desc(platform='slack', supports_draft_streaming=True, supported_ops=('send', 'draft'))
    original = replace(source(), thread_id='owned-thread')
    metadata = dict(_thread_metadata_for_source(original), message_id='owned-turn')
    await adapter.send_draft(original.chat_id, 96, 'Owned partial', metadata=metadata)
    open_before = dict(adapter._open_draft_by_chat)
    result = await adapter.send(original.chat_id, 'Unowned final', metadata=dict(metadata, _relay_logical_platform=platform))
    assert not result.success
    assert len(connector.sent) == 1
    assert adapter._open_draft_by_chat == open_before
