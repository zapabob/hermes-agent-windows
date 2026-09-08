"""Binding failures cannot run on inherited credentials or leak a reservation."""
import threading
from types import SimpleNamespace

import pytest
from agent.credential_pool import CredentialPool, PooledCredential
from tools import delegate_tool


@pytest.mark.parametrize('failure', ['removed', 'bind-error'])
def test_binding_failure_releases_once_without_starting_child(monkeypatch, failure):
    entry = PooledCredential(id='synthetic', label='synthetic', provider='anthropic',
                             auth_type='oauth', source='oauth', priority=0, access_token='synthetic-token')
    pool = CredentialPool.__new__(CredentialPool)
    pool._lock = threading.RLock()
    pool._entries = [entry]
    pool._current_id = None
    pool._active_leases = {}
    pool._max_concurrent = 1
    pool._available_entries = lambda **kwargs: (list(pool._entries), [])
    acquire = pool.acquire_lease
    release = pool.release_lease
    releases = []
    def reserve():
        selected = acquire()
        if failure == 'removed':
            pool._entries.clear()
        return selected
    def unreserve(selected):
        releases.append(selected)
        release(selected)
    pool.acquire_lease = reserve
    pool.release_lease = unreserve
    ran, closed = [], []
    def bind(_entry):
        raise RuntimeError('synthetic binding failure')
    child = SimpleNamespace(_credential_pool=pool, _swap_credential=bind,
                            _delegate_saved_tool_names=[], _subagent_id=None,
                            tool_progress_callback=None, _delegate_role='leaf',
                            run_conversation=lambda **kwargs: ran.append(True),
                            close=lambda: closed.append(True))
    parent = SimpleNamespace(session_id='synthetic-parent', _current_task_id=None,
                             _active_children=[child], _active_children_lock=threading.Lock())
    monkeypatch.setattr(delegate_tool, '_get_worktree_isolation', lambda: False)
    result = delegate_tool._run_single_child(task_index=0, goal='synthetic', child=child, parent_agent=parent)
    assert result['status'] == 'error'
    assert releases == [entry.id]
    assert pool._active_leases == {}
    assert not ran and closed == [True]
    assert parent._active_children == []
