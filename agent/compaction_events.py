"""Post-compaction plugin hook dispatch (durable commit only).

Fires ``post_compaction`` after compression history is committed. Hook
exceptions must never roll back committed history. Process-crash
exactly-once delivery across restarts is intentionally out of scope;
listeners should treat ``commit_identity`` as an idempotency key when present.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)


def fire_post_compaction(
    *,
    session_id: str,
    old_session_id: str,
    kind: str = "compression",
    reason: str = "compression",
    tokens_before: Optional[int] = None,
    tokens_after: Optional[int] = None,
    messages_removed: Optional[int] = None,
    commit_identity: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> int:
    """Invoke registered ``post_compaction`` hooks. Returns listener count attempted."""
    try:
        from hermes_cli.lifecycle import has_hook, invoke_hook
    except Exception:
        logger.debug("post_compaction hook import failed", exc_info=True)
        return 0

    if not has_hook("post_compaction"):
        return 0

    payload: dict[str, Any] = {
        "session_id": str(session_id or ""),
        "old_session_id": str(old_session_id or ""),
        "kind": str(kind or "compression"),
        "reason": str(reason or "compression"),
    }
    if tokens_before is not None:
        payload["tokens_before"] = int(tokens_before)
    if tokens_after is not None:
        payload["tokens_after"] = int(tokens_after)
    if messages_removed is not None:
        payload["messages_removed"] = int(messages_removed)
    if commit_identity:
        payload["commit_identity"] = str(commit_identity)
    if extra:
        for key, value in extra.items():
            if key in payload:
                continue
            # Never forward free-form conversation bodies.
            if key in {"messages", "history", "content", "secrets", "token"}:
                continue
            payload[key] = value

    try:
        results = invoke_hook("post_compaction", **payload)
    except Exception:
        logger.debug("post_compaction invoke_hook failed", exc_info=True)
        return 0
    return len(results) if isinstance(results, list) else 0
