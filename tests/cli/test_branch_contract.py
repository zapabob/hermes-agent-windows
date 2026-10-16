"""Branch effects through classic CLI dispatch and an isolated real session DB."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli import HermesCLI
from hermes_state import SessionDB


@pytest.fixture
def surface(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home'))
    db = SessionDB(tmp_path / 'state.db')
    db.create_session('parent', source='cli', system_prompt='PERSISTED PREFIX\nKeepCase 日本語')
    db.set_session_title('parent', 'Original')
    owner = object.__new__(HermesCLI)
    owner._session_db = db
    owner.session_id = 'parent'
    owner.session_start = datetime.now()
    owner.model = 'fixture-model'
    owner.max_turns = 4
    owner.reasoning_config = {'enabled': True}
    owner._agent_running = False
    owner._pending_title = None
    owner._resumed = False
    owner.agent = None
    owner.conversation_history = [{'role': 'user', 'content': 'KeepCase 日本語'},
                                  {'role': 'assistant', 'content': 'Fixed reply'}]
    output = []
    monkeypatch.setattr('cli._cprint', output.append)
    yield owner, db, output
    db.close()


@pytest.mark.parametrize('command', ['/branch --here MixedCase 日本語', '/fork --HERE MixedCase 日本語',
                                     '/BRANCH --here MixedCase 日本語'])
def test_leading_here_flag_is_not_the_persisted_title(surface, command):
    owner, db, _ = surface
    history = deepcopy(owner.conversation_history)
    assert owner.process_command(command)
    assert owner.session_id != 'parent'
    child = db.get_session(owner.session_id)
    assert child['parent_session_id'] == 'parent'
    assert child['title'] == 'MixedCase 日本語'
    persisted_history = db.get_messages_as_conversation(owner.session_id)
    assert [{key: msg[key] for key in ('role', 'content')} for msg in persisted_history] == history
    assert owner.conversation_history == history
    assert db.get_session('parent')['end_reason'] == 'branched'
    # Reopen the committed identity independently of the live selection.
    with SessionDB(db.db_path) as resumed:
        assert resumed.get_session(owner.session_id)['title'] == 'MixedCase 日本語'
        assert resumed.get_messages_as_conversation(owner.session_id) == persisted_history


@pytest.mark.parametrize('title, persisted', [('Mixed --here Case', 'Mixed --here Case'),
                                             ('--here\tTitle', '--here Title')])
def test_source_literal_title_rule_is_preserved(surface, title, persisted):
    owner, db, _ = surface
    owner.process_command('/branch ' + title)
    assert db.get_session_title(owner.session_id) == persisted


@pytest.mark.parametrize('cached', ['LIVE PREFIX\nOpaque 日本語', '', None])
def test_child_carries_exact_live_prompt_or_persisted_parent_fallback(surface, cached):
    owner, db, _ = surface
    owner.agent = SimpleNamespace(_cached_system_prompt=cached,
                                  _flush_messages_to_session_db=Mock(),
                                  reset_session_state=Mock())
    owner.process_command('/branch Child')
    expected = cached or db.get_session('parent')['system_prompt']
    assert db.get_session(owner.session_id)['system_prompt'] == expected
    assert owner.agent.session_id == owner.session_id


@pytest.mark.parametrize('command', ['/branch', '/fork Child', '/BRANCH --here Child'])
def test_direct_busy_dispatch_keeps_parent_open_without_flushing(surface, command):
    owner, db, output = surface
    owner._agent_running = True
    flush = Mock()
    owner.agent = SimpleNamespace(_flush_messages_to_session_db=flush, reset_session_state=Mock())
    before = deepcopy(owner.conversation_history)
    assert owner.process_command(command)
    assert owner.session_id == 'parent'
    assert db.get_session('parent')['ended_at'] is None
    assert db.get_messages('parent') == []
    flush.assert_not_called()
    assert owner.conversation_history == before
    assert output


def test_failed_child_create_keeps_parent_open_and_does_not_flush(surface, monkeypatch):
    owner, db, output = surface
    flush = Mock()
    owner.agent = SimpleNamespace(_flush_messages_to_session_db=flush, reset_session_state=Mock())
    def fail(*args, **kwargs):
        raise RuntimeError('owned child-create failure')
    monkeypatch.setattr(db, 'create_session', fail)
    assert owner.process_command('/branch Child')
    assert owner.session_id == 'parent'
    assert db.get_session('parent')['ended_at'] is None
    flush.assert_not_called()
    assert any('Failed to create' in line for line in output)


def test_child_exists_before_parent_end_and_live_flush(surface, monkeypatch):
    owner, db, _ = surface
    created = []
    create = db.create_session
    end = db.end_session
    def record_create(*args, **kwargs):
        result = create(*args, **kwargs)
        created.append(kwargs['session_id'])
        return result
    def observe(*args, **kwargs):
        observations.append(bool(created and db.get_session(created[0]) is not None))
    def checked_end(*args, **kwargs):
        observe()
        return end(*args, **kwargs)
    monkeypatch.setattr(db, 'create_session', record_create)
    monkeypatch.setattr(db, 'end_session', checked_end)
    observations = []
    owner.agent = SimpleNamespace(_flush_messages_to_session_db=observe, reset_session_state=Mock())
    owner.process_command('/branch Child')
    assert owner.session_id == created[0]
    assert observations == [True, True]
    assert db.get_session('parent')['end_reason'] == 'branched'


def test_branch_reopen_preserves_wire_sidecars_and_tool_exchange(surface):
    owner, db, _ = surface
    tool_call = {'id': 'owned-call', 'type': 'function',
                 'function': {'name': 'terminal', 'arguments': '{"command":"echo owned"}'}}
    history = [{'role': 'user', 'content': 'Visible 日本語',
                'api_content': 'Visible 日本語\n\nOpaque API context'},
               {'role': 'assistant', 'content': None, 'tool_calls': [tool_call]},
               {'role': 'tool', 'content': 'owned result', 'tool_call_id': 'owned-call', 'name': 'terminal'},
               {'role': 'assistant', 'content': 'Visible answer', 'api_content': 'Exact API answer'}]
    owner.conversation_history = deepcopy(history)
    assert owner.process_command('/branch --here Child')
    with SessionDB(db.db_path) as reopened:
        copied = reopened.get_messages_as_conversation(owner.session_id)
    fields = ('role', 'content', 'api_content', 'tool_calls', 'tool_call_id')
    assert [{key: msg.get(key) for key in fields} for msg in copied] == [
        {key: msg.get(key) for key in fields} for msg in history]
    assert owner.conversation_history == history


@pytest.mark.parametrize('failure', ['append_messages_batch', 'set_session_title'])
def test_copy_and_title_failure_preserve_the_source_best_effort_policy(surface, monkeypatch, failure):
    owner, db, output = surface
    def fail(*args, **kwargs):
        raise RuntimeError('owned best-effort failure')
    monkeypatch.setattr(db, failure, fail)
    owner.process_command('/branch Child')
    assert owner.session_id != 'parent'
    assert db.get_session(owner.session_id)['parent_session_id'] == 'parent'
    if failure == 'append_messages_batch':
        assert db.get_messages(owner.session_id) == []
    else:
        assert db.get_session_title(owner.session_id) is None
    assert any('Branched session' in line for line in output)


def test_post_publication_agent_sync_failure_reports_actual_partial_selection(surface):
    owner, db, output = surface
    owner.agent = SimpleNamespace(_flush_messages_to_session_db=Mock(),
                                  reset_session_state=Mock(side_effect=RuntimeError('owned sync failure')))
    with pytest.raises(RuntimeError, match='owned sync failure'):
        owner.process_command('/branch Child')
    assert owner.session_id != 'parent'
    assert owner.agent.session_id == owner.session_id
    assert db.get_session(owner.session_id)['parent_session_id'] == 'parent'
    assert not any('Branched session' in line for line in output)


def test_yolo_transfer_failure_keeps_selection_before_publication(surface, monkeypatch):
    owner, db, output = surface
    created = []
    create = db.create_session
    def record_create(*args, **kwargs):
        result = create(*args, **kwargs)
        created.append(kwargs['session_id'])
        return result
    def failed_transfer(*args):
        raise RuntimeError('owned yolo-transfer failure')
    monkeypatch.setattr(db, 'create_session', record_create)
    monkeypatch.setattr(owner, '_transfer_session_yolo', failed_transfer)
    with pytest.raises(RuntimeError, match='owned yolo-transfer failure'):
        owner.process_command('/branch Child')
    assert owner.session_id == 'parent'
    assert len(created) == 1
    assert db.get_session(created[0])['parent_session_id'] == 'parent'
    assert db.get_session('parent')['end_reason'] == 'branched'
    assert not any('Branched session' in line for line in output)
