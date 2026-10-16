"""Branch/reply routing over an authenticated loopback production WS transport.

The registered handler invokes the real branch owner; follow-up reads the real
session store. Provider inference is covered separately by the native CLI oracle.
"""
import asyncio
from dataclasses import asdict, replace
import errno
import json
import socket
import sys

import pytest
import websockets

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.relay.adapter import RelayAdapter
from gateway.relay.auth import verify_token
from gateway.relay.ws_transport import WebSocketRelayTransport
from gateway.session import SessionSource, SessionStore
from tests.gateway.relay.test_relay_threads import make_desc
from tests.gateway.test_branch_routing_columns import _make_branch_runner


@pytest.mark.asyncio
@pytest.mark.parametrize('stay_here,thread_allowed', [(False, True), (True, True), (False, False)])
async def test_authenticated_ws_branch_and_followup_keep_the_persisted_source(tmp_path, monkeypatch, stay_here, thread_allowed):
    import hermes_state
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(hermes_state, 'DEFAULT_DB_PATH', tmp_path / 'state.db')
    store = SessionStore(sessions_dir=tmp_path / 'sessions', config=GatewayConfig())
    runner = _make_branch_runner(store)
    runner.config = GatewayConfig()
    original = SessionSource(platform=Platform.SLACK, chat_id='same-chat', chat_type='group',
                             thread_id='owned-existing-thread', user_id='owned-author',
                             scope_id='owned-workspace', delivered_via_upstream_relay=True)
    parent = store.get_or_create_session(original).session_id
    store._db.update_system_prompt(parent, 'PERSISTED PREFIX 日本語')
    store._db.append_message(parent, role='user', content='Visible user', api_content='Exact wire user 日本語')
    store._db.append_message(parent, role='assistant', content='Retained answer')
    parent_history = store._db.get_messages_as_conversation(parent)
    received = []
    replies = asyncio.Queue()
    connected = asyncio.Event()
    all_descriptors = asyncio.Event()
    socket_holder = []
    handler_errors = []
    selected = []
    descriptors = {'discord': make_desc(platform='discord'),
                   'slack': make_desc(platform='slack', supported_ops=('send', 'typing', 'thread_create')
                                      if thread_allowed else ('send', 'typing'))}
    fixture_secret = 'owned-loopback-upgrade-secret'

    async def connector(ws):
        bearer = ws.request.headers.get('Authorization', '')
        assert bearer.startswith('Bearer ')
        assert verify_token(bearer.removeprefix('Bearer '), [fixture_secret]) == 'owned-gateway'
        socket_holder.append(ws)
        connected.set()
        hello_platforms = set()
        async for raw in ws:
            for line in raw.splitlines():
                frame = json.loads(line)
                received.append(frame)
                if frame['type'] == 'hello':
                    platform = frame['platform']
                    hello_platforms.add(platform)
                    await ws.send(json.dumps({'type': 'descriptor', 'descriptor': asdict(descriptors[platform])}) + '\n')
                    if hello_platforms == {'discord', 'slack'}:
                        all_descriptors.set()
                elif frame['type'] == 'outbound':
                    action = frame['action']
                    result = {'success': True, 'message_id': 'owned-reply'}
                    if action['op'] == 'thread_create':
                        result['thread_id'] = 'owned-thread'
                    await ws.send(json.dumps({'type': 'outbound_result', 'requestId': frame['requestId'], 'result': result}) + '\n')
                    if action['op'] == 'send':
                        await replies.put(frame)
                elif frame['type'] == 'going_idle':
                    await ws.send(json.dumps({'type': 'going_idle_ack'}) + '\n')

    server = await websockets.serve(connector, '127.0.0.1', 0)
    port = next(iter(server.sockets)).getsockname()[1]
    transport = WebSocketRelayTransport(f'ws://127.0.0.1:{port}', 'discord', 'owned-d',
                                        identities=[('discord', 'owned-d'), ('slack', 'owned-s')],
                                        gateway_id='owned-gateway', upgrade_secret=fixture_secret,
                                        connect_timeout_s=5, outbound_timeout_s=5)
    adapter = RelayAdapter(PlatformConfig(enabled=True), descriptors['discord'], transport=transport)
    runner.adapters = {Platform.RELAY: adapter}

    async def handle(event):
        try:
            if event.text.startswith('/branch'):
                reply = await runner._handle_branch_command(event)
            else:
                entry = store.get_or_create_session(event.source)
                selected.append(entry.session_id)
                assert store._db.get_messages_as_conversation(entry.session_id) == parent_history
                assert store._db.get_session(entry.session_id)['system_prompt'] == 'PERSISTED PREFIX 日本語'
                reply = 'Owned followup reply'
            # A competing source overwrites the chat-only caches before base
            # sends this handler's reply. Source metadata must still win.
            collision = replace(event.source, platform=Platform.DISCORD, user_id='foreign-author', scope_id='foreign-workspace')
            adapter._capture_scope(MessageEvent(text='collision', source=collision))
            return reply
        except Exception as exc:
            handler_errors.append(repr(exc))
            raise

    adapter.set_message_handler(handle)
    reader = None
    monitor = None
    try:
        assert await adapter.connect()
        reader, monitor = transport._reader, adapter._revocation_monitor
        await asyncio.wait_for(connected.wait(), 5)
        await asyncio.wait_for(all_descriptors.wait(), 5)
        # Descriptor receipt, rather than the server send, is the admission fence.
        async with asyncio.timeout(5):
            while transport.descriptor_for_platform('slack') is None:
                await asyncio.sleep(0)

        async def push(text, src, message_id):
            wire_source = asdict(src)
            wire_source['platform'] = src.platform.value
            await socket_holder[0].send(json.dumps({'type': 'inbound', 'event': {
                'text': text, 'message_type': 'text', 'message_id': message_id, 'source': wire_source}}) + '\n')

        await push('/branch ' + ('--here ' if stay_here else '') + 'Child 日本語', original, 'branch-event')
        branch_reply = await asyncio.wait_for(replies.get(), 8)
        destination = replace(original, thread_id='owned-thread') if thread_allowed and not stay_here else original
        child = store.get_or_create_session(destination).session_id
        assert child != parent
        assert store._db.get_session(child)['parent_session_id'] == parent
        assert store._db.get_session(child)['title'] == 'Child 日本語'
        assert store._db.get_messages_as_conversation(child) == parent_history
        assert store.get_or_create_session(original).session_id == (parent if thread_allowed and not stay_here else child)
        await push('Owned followup', destination, 'followup-event')
        followup_reply = await asyncio.wait_for(replies.get(), 8)
        assert selected == [child]
        for frame in (branch_reply, followup_reply):
            assert frame['platform'] == 'slack'
            assert frame['action']['metadata']['scope_id'] == 'owned-workspace'
            assert frame['action']['metadata']['user_id'] == 'owned-author'
        assert followup_reply['action']['metadata'].get('thread_id') == destination.thread_id
        creates = [f for f in received if f['type'] == 'outbound' and f['action']['op'] == 'thread_create']
        assert len(creates) == (1 if thread_allowed and not stay_here else 0)
        assert not handler_errors
        owned_handlers = list(set(adapter._session_tasks.values()) | adapter._background_tasks)
        if owned_handlers:
            await asyncio.wait_for(asyncio.gather(*owned_handlers), 5)
        assert not adapter._active_sessions and not adapter._session_tasks
        assert all(task.done() for task in adapter._background_tasks)
    finally:
        try:
            await adapter.disconnect()
        finally:
            try:
                server.close()
            finally:
                try:
                    await asyncio.wait_for(server.wait_closed(), 5)
                finally:
                    store._db.close()
    assert reader is not None and reader.done()
    assert monitor is not None and monitor.done()
    assert transport._pending == {} and transport._ws is None
    # Windows ConnectEx (the asyncio Proactor path) reports 1225 for refusal;
    # Winsock connect_ex provides the native 10061 receipt used by our oracle.
    with socket.socket() as connection:
        connection.settimeout(5)
        refusal_code = connection.connect_ex(('127.0.0.1', port))
    assert refusal_code == (10061 if sys.platform == 'win32' else errno.ECONNREFUSED)
