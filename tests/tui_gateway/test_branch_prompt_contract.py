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
