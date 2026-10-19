"""Parent prompt snapshot at the real session.branch RPC persistence seam."""

from threading import Lock
from contextlib import ExitStack
from types import SimpleNamespace

import pytest

from hermes_state import SessionDB
from tui_gateway import server


@pytest.mark.parametrize('persisted,read_failure,profile_owned', [('PARENT PREFIX\nKeepCase 日本語', False, False),
                                                               (None, False, False), ('PARENT PREFIX', True, False),
                                                               ('PROFILE PREFIX\nKeepCase 日本語', False, True),
                                                               (None, False, True)])
def test_branch_rpc_carries_only_the_profile_db_parent_prompt(tmp_path, monkeypatch, persisted, read_failure, profile_owned):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home'))
    with ExitStack() as handles:
        launch_db = handles.enter_context(SessionDB(tmp_path / 'state.db'))
        profile_home = tmp_path / 'profile-owned'
        db = handles.enter_context(SessionDB(profile_home / 'state.db')) if profile_owned else launch_db
        if profile_owned:
            launch_db.create_session('parent', source='tui', system_prompt='FOREIGN LAUNCH PREFIX')
            launch_db.append_message('parent', role='user', content='Foreign launch transcript')
        db.create_session('parent', source='tui', system_prompt=persisted)
        db.append_message('parent', role='user', content='Original visible transcript')
        session = {'agent': SimpleNamespace(_cached_system_prompt='UNPERSISTED AGENT PREFIX'),
                   'session_key': 'parent', 'history': [{'role': 'user', 'content': 'Original visible transcript'}],
                   'history_lock': Lock(), 'history_version': 0, 'running': False,
                   'attached_images': [], 'image_counter': 0, 'cols': 80, 'slash_worker': None,
                   'show_reasoning': False, 'tool_progress_mode': 'all'}
        if profile_owned:
            session['profile_home'] = str(profile_home)
        monkeypatch.setitem(server._sessions, 'owned-parent-sid', session)
        monkeypatch.setattr(server, '_get_db', lambda: launch_db)
        monkeypatch.setattr(server, '_new_session_key', lambda: 'child')
        monkeypatch.setattr(server, '_start_agent_build', lambda *args: None)
        monkeypatch.setattr(server, '_wait_agent', lambda *args: None)
        monkeypatch.setattr(server, '_resolve_model', lambda: 'fixture-model')
        monkeypatch.setattr(server, '_session_cwd', lambda *args: str(tmp_path))
        monkeypatch.setattr(server, '_make_agent', lambda *args, **kwargs: SimpleNamespace())
        monkeypatch.setattr(server, '_init_session', lambda *args, **kwargs: None)
        get_session = db.get_session
        if read_failure:
            def read_row(key, *args, **kwargs):
                if key == 'parent':
                    raise OSError('owned prompt read failure')
                return get_session(key, *args, **kwargs)
            monkeypatch.setattr(db, 'get_session', read_row)
        try:
            response = server.handle_request({'id': 'owned-branch', 'method': 'session.branch',
                                              'params': {'session_id': 'owned-parent-sid', 'name': 'Child 日本語'}})
        except OSError as exc:
            response = {'error': str(exc)}
        assert response.get('result'), response
        assert response['result']['stored_session_id'] == 'child'
        child = db.get_session('child')
        assert child['system_prompt'] == (None if read_failure else persisted)
        assert child['parent_session_id'] == 'parent'
        assert child['title'] == 'Child 日本語'
        assert get_session('parent')['ended_at'] is None
        assert db.get_messages_as_conversation('child') == db.get_messages_as_conversation('parent')
        assert session['session_key'] == 'parent'
        if profile_owned:
            assert child['profile_name'] == 'profile-owned'
            assert launch_db.get_session('child') is None
            assert launch_db.get_session('parent')['system_prompt'] == 'FOREIGN LAUNCH PREFIX'


@pytest.mark.parametrize('params, expected_title', [
    ({'name': 'MixedCase 日本語', 'parse_slash_args': True}, 'MixedCase 日本語'),
    ({'name': '--here Child 日本語', 'parse_slash_args': True}, 'Child 日本語'),
    ({'name': '--HERE Other 日本語', 'parse_slash_args': True}, 'Other 日本語'),
    ({'name': '--here', 'parse_slash_args': True}, None),
    ({'name': '', 'parse_slash_args': True}, None),
    ({'name': '--here Child 日本語'}, '--here Child 日本語'),
    ({'name': '--here'}, '--here'),
    ({'name': '--here Literal', 'parse_slash_args': False}, '--here Literal'),
    ({'name': 'Embedded --here 日本語', 'parse_slash_args': True}, 'Embedded --here 日本語'),
])
def test_branch_typed_args_and_literal_names_preserve_parent_bytes(tmp_path, monkeypatch, params, expected_title):
    import json

    def encoded(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

    with SessionDB(tmp_path / 'state.db') as db:
        prompt = 'PARENT PREFIX\nKeepCase 日本語\n'
        db.create_session('parent', source='tui', system_prompt=prompt)
        db.set_session_title('parent', 'Parent 日本語')
        history = [{'role': 'user', 'content': 'Original 日本語'}, {'role': 'assistant', 'content': 'Stable reply'}]
        for message in history:
            db.append_message('parent', **message)
        parent_before = encoded(db.get_session('parent'))
        history_before = encoded(db.get_messages_as_conversation('parent'))
        expected = expected_title if expected_title is not None else db.get_next_title_in_lineage('Parent 日本語')
        session = {'agent': None, 'session_key': 'parent', 'history': history, 'history_lock': Lock(),
                   'history_version': 0, 'running': False, 'attached_images': [], 'image_counter': 0,
                   'cols': 80, 'slash_worker': None, 'show_reasoning': False, 'tool_progress_mode': 'all'}
        monkeypatch.setitem(server._sessions, 'owned-parent-sid', session)
        for name, value in {'_get_db': lambda: db, '_new_session_key': lambda: 'child',
                            '_start_agent_build': lambda *a: None, '_wait_agent': lambda *a: None,
                            '_resolve_model': lambda: 'fixture-model', '_session_cwd': lambda *a: str(tmp_path),
                            '_make_agent': lambda *a, **kw: SimpleNamespace(), '_init_session': lambda *a, **kw: None}.items():
            monkeypatch.setattr(server, name, value)
        response = server.handle_request({'id': 'typed-branch', 'method': 'session.branch',
                                          'params': {'session_id': 'owned-parent-sid', **params}})
        assert response.get('result'), response
        child = db.get_session('child')
        assert child['title'] == expected
        assert child['parent_session_id'] == 'parent'
        assert child['system_prompt'].encode('utf-8') == prompt.encode('utf-8')
        assert encoded(db.get_messages_as_conversation('child')) == history_before
        assert encoded(db.get_session('parent')) == parent_before
        assert encoded(db.get_messages_as_conversation('parent')) == history_before
        assert session['session_key'] == 'parent'
        with SessionDB(db.db_path) as reopened:
            assert reopened.get_session('child')['title'] == expected
            assert encoded(reopened.get_session('parent')) == parent_before


@pytest.mark.parametrize('params', [
    {'name': 'Child', 'parse_slash_args': 'true'},
    {'name': 'Child', 'parse_slash_args': 1},
    {'name': None, 'parse_slash_args': True},
])
def test_branch_rejects_invalid_typed_marker_without_opening_db(monkeypatch, params):
    monkeypatch.setattr(server, '_sess', lambda params, rid: ({}, None))
    monkeypatch.setattr(server, '_session_db', lambda *args: pytest.fail('invalid params reached DB'))
    response = server.handle_request({'id': 'invalid-typed-branch', 'method': 'session.branch', 'params': params})
    assert response['error']['code'] == -32602
