"""Browser/Webapp → canonical Gateway session admission adapter.

This module is the narrow waist between browser (and Gateway-attached Desktop)
viewers and a single execution owner. It must not spawn a second AIAgent loop.

Until ``SessionAuthority`` (or an equivalent durable admission owner) is wired
on ``GatewayRunner``, mutating admissions fail closed.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class WebappAuthorityUnavailable(RuntimeError):
    """Canonical session owner is not installed on this checkout."""


class ConflictingSubmission(ValueError):
    """Same submission_id with a different payload digest."""


@dataclass(frozen=True)
class AdmissionKey:
    profile_id: str
    principal_id: str
    session_id: str
    submission_id: str


@dataclass
class AdmissionReceipt:
    key: AdmissionKey
    payload_digest: str
    execution_generation: int
    state: str  # admitted | unknown | completed
    executor_starts: int = 0


@dataclass
class _SessionViewState:
    viewers: set[str] = field(default_factory=set)
    pending_approval: dict[str, Any] | None = None
    execution_generation: int = 1
    receipts: dict[str, AdmissionReceipt] = field(default_factory=dict)


def payload_digest(payload: dict[str, Any]) -> str:
    """Stable digest for conflict detection (not a security MAC)."""
    text = repr(sorted((str(k), repr(payload[k])) for k in payload))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class WebappSessionAdapter:
    """In-process admission ledger used until full SessionAuthority is ported.

    Unit tests may exercise this ledger. Product write paths must still refuse
    when ``authority_bound`` is False.
    """

    def __init__(self, *, authority_bound: bool = False) -> None:
        self._authority_bound = authority_bound
        self._lock = threading.RLock()
        self._sessions: dict[tuple[str, str], _SessionViewState] = {}

    @property
    def authority_bound(self) -> bool:
        return self._authority_bound

    def bind_authority(self, bound: bool = True) -> None:
        self._authority_bound = bool(bound)

    def _session_state(self, profile_id: str, session_id: str) -> _SessionViewState:
        key = (profile_id, session_id)
        state = self._sessions.get(key)
        if state is None:
            state = _SessionViewState()
            self._sessions[key] = state
        return state

    def attach_viewer(
        self,
        *,
        profile_id: str,
        session_id: str,
        viewer_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._session_state(profile_id, session_id)
            state.viewers.add(viewer_id)
            return {
                "session_id": session_id,
                "viewer_count": len(state.viewers),
                "execution_generation": state.execution_generation,
                "pending_approval": dict(state.pending_approval)
                if state.pending_approval
                else None,
            }

    def detach_viewer(
        self,
        *,
        profile_id: str,
        session_id: str,
        viewer_id: str,
        cancel_execution: bool = False,
    ) -> dict[str, Any]:
        """Detach a viewer. Never cancels execution/approval by default."""
        if cancel_execution:
            raise WebappAuthorityUnavailable(
                "cancel_on_disconnect is forbidden for canonical Webapp sessions"
            )
        with self._lock:
            state = self._session_state(profile_id, session_id)
            state.viewers.discard(viewer_id)
            return {
                "session_id": session_id,
                "viewer_count": len(state.viewers),
                "pending_approval": dict(state.pending_approval)
                if state.pending_approval
                else None,
                "execution_alive": True,
            }

    def set_pending_approval(
        self,
        *,
        profile_id: str,
        session_id: str,
        prompt_id: str,
        execution_generation: int,
    ) -> None:
        with self._lock:
            state = self._session_state(profile_id, session_id)
            state.pending_approval = {
                "prompt_id": prompt_id,
                "execution_generation": execution_generation,
            }
            state.execution_generation = execution_generation

    def admit_submission(
        self,
        *,
        profile_id: str,
        principal_id: str,
        session_id: str,
        submission_id: str,
        payload: dict[str, Any],
        viewer_id: str,
    ) -> AdmissionReceipt:
        if not self._authority_bound:
            raise WebappAuthorityUnavailable(
                "canonical SessionAuthority is not bound; refusing browser write path"
            )
        if not submission_id or not isinstance(submission_id, str):
            raise ValueError("submission_id required")
        digest = payload_digest(payload)
        key = AdmissionKey(profile_id, principal_id, session_id, submission_id)
        with self._lock:
            state = self._session_state(profile_id, session_id)
            state.viewers.add(viewer_id)
            existing = state.receipts.get(submission_id)
            if existing is not None:
                if existing.payload_digest != digest:
                    raise ConflictingSubmission(
                        "submission_id reuse with conflicting payload"
                    )
                return existing
            receipt = AdmissionReceipt(
                key=key,
                payload_digest=digest,
                execution_generation=state.execution_generation,
                state="admitted",
                executor_starts=1,
            )
            state.receipts[submission_id] = receipt
            return receipt

    def mark_unknown_no_retry(
        self, *, profile_id: str, session_id: str, submission_id: str
    ) -> None:
        with self._lock:
            state = self._session_state(profile_id, session_id)
            receipt = state.receipts.get(submission_id)
            if receipt is None:
                return
            receipt.state = "unknown"


_ADAPTER: WebappSessionAdapter | None = None
_ADAPTER_LOCK = threading.Lock()


def get_webapp_session_adapter() -> WebappSessionAdapter:
    global _ADAPTER
    with _ADAPTER_LOCK:
        if _ADAPTER is None:
            _ADAPTER = WebappSessionAdapter(authority_bound=False)
        return _ADAPTER


def reset_webapp_session_adapter_for_tests(
    adapter: WebappSessionAdapter | None = None,
) -> WebappSessionAdapter:
    global _ADAPTER
    with _ADAPTER_LOCK:
        _ADAPTER = (
            adapter
            if adapter is not None
            else WebappSessionAdapter(authority_bound=True)
        )
        return _ADAPTER
