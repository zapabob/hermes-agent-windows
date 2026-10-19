"""Single owner of retained session states and their Telegram chat index."""
from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gateway.session_state import SessionState


class SessionStateStore(MutableMapping[str, 'SessionState']):
    """Publish a state and its chat membership atomically, without timestamps.

    Telegram DM keys come from build_session_key: namespace:telegram:dm:chat
    followed by an optional topic. The index contains keys, not another state
    registry. Looking up one chat visits only that chat's retained topics.
    """

    def __init__(self, initial: Mapping[str, SessionState] | None = None):
        self._lock = RLock()
        self._states: dict[str, SessionState] = {}
        self._telegram_dm_keys: dict[str, set[str]] = {}
        if initial:
            self.update(initial)

    @staticmethod
    def _telegram_dm_base(key: str) -> str | None:
        namespace, marker, rest = key.rpartition(':telegram:dm:')
        if not marker or not rest:
            return None
        chat_id = rest.partition(':')[0]
        return namespace + marker + chat_id

    def __getitem__(self, key: str) -> SessionState:
        with self._lock:
            return self._states[key]

    def __setitem__(self, key: str, state: SessionState) -> None:
        with self._lock:
            self._states[key] = state
            base = self._telegram_dm_base(key)
            if base is not None:
                self._telegram_dm_keys.setdefault(base, set()).add(key)

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._states[key]
            base = self._telegram_dm_base(key)
            if base is not None:
                members = self._telegram_dm_keys[base]
                members.remove(key)
                if not members:
                    del self._telegram_dm_keys[base]

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(self._states))

    def __len__(self) -> int:
        with self._lock:
            return len(self._states)

    def setdefault(self, key: str, default: SessionState) -> SessionState:
        # First-destination arbitration must include publication in the index.
        # A state constructed before a route snapshot confers no authority if
        # another thread publishes it after that snapshot.
        with self._lock:
            if key not in self._states:
                self[key] = default
            return self._states[key]

    def telegram_dm_items(self, base: str) -> tuple[tuple[str, SessionState], ...]:
        with self._lock:
            return tuple((key, self._states[key]) for key in self._telegram_dm_keys.get(base, ()))
