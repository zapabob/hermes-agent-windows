"""A reserved ID, not the shared cursor, determines a child credential."""
import threading
from dataclasses import replace

import pytest

from agent.credential_pool import CredentialPool, PooledCredential, STATUS_DEAD, STATUS_EXHAUSTED


def make_pool():
    entry = PooledCredential(id='synthetic-a', provider='anthropic', auth_type='oauth',
                             access_token='synthetic-token', source='oauth', priority=0, label='synthetic')
    pool = CredentialPool.__new__(CredentialPool)
    pool._lock = threading.RLock()
    pool._entries = [entry]
    pool._active_leases = {entry.id: 1}
    pool._current_id = 'another-entry'
    return pool, entry


def test_reserved_id_survives_cursor_change_and_uses_replacement():
    pool, entry = make_pool()
    replacement = replace(entry, access_token='synthetic-replacement')
    pool._replace_entry(entry, replacement)
    assert pool.leased_entry(entry.id) is replacement
    assert pool._active_leases == {entry.id: 1}


def test_removed_or_unreserved_identity_has_no_fallback():
    pool, entry = make_pool()
    assert pool.leased_entry('not-reserved') is None
    pool._entries.clear()
    assert pool.leased_entry(entry.id) is None
    pool.release_lease(entry.id)
    assert pool._active_leases == {}


@pytest.mark.parametrize('status', [STATUS_DEAD, STATUS_EXHAUSTED])
def test_quarantined_reserved_entry_cannot_be_bound(status):
    pool, entry = make_pool()
    pool._entries = [replace(entry, last_status=status)]
    assert pool.leased_entry(entry.id) is None


def test_empty_reserved_credential_cannot_be_bound():
    pool, entry = make_pool()
    pool._entries = [replace(entry, access_token='')]
    assert pool.leased_entry(entry.id) is None


def test_soft_cap_still_distributes_without_blocking():
    pool, entry = make_pool()
    other = replace(entry, id='synthetic-b', priority=1)
    pool._entries.append(other)
    pool._active_leases.clear()
    pool._max_concurrent = 1
    pool._available_entries = lambda **kwargs: (list(pool._entries), [])
    selected = [pool.acquire_lease() for _ in range(4)]
    assert selected == [entry.id, other.id, entry.id, other.id]
    for identity in selected:
        assert pool.leased_entry(identity).id == identity
        pool.release_lease(identity)
    assert pool._active_leases == {}


def test_deferred_refresh_runs_without_pool_lock_then_binds_refreshed_entry():
    pool, entry = make_pool()
    pool._active_leases.clear()
    pool._max_concurrent = 1
    refreshed = replace(entry, access_token='synthetic-refreshed')
    ready = False
    def available(**kwargs):
        return ([refreshed], []) if ready else ([], [(entry.id, 'synthetic-token')])
    def refresh(_pending):
        nonlocal ready
        acquired = threading.Event()
        def contender():
            with pool._lock:
                acquired.set()
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(2)
        assert acquired.is_set() and not thread.is_alive()
        pool._replace_entry(entry, refreshed)
        ready = True
    pool._available_entries = available
    pool._refresh_pending_entries = refresh
    selected = pool.acquire_lease()
    assert pool.leased_entry(selected) is refreshed
    pool.release_lease(selected)
    assert pool._active_leases == {}
