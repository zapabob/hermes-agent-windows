"""Server→client JSON-RPC requests: the backend asks the renderer a question and waits for the
response frame carrying the same ``id``.

Windows-native COMPOSE of U_NEXT ``tui_gateway/server_requests.py`` (345cd2b): same wire
semantics without the Pydantic contracts package. Method allowlist replaces
``tui_gateway.contracts`` validation.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable

logger = logging.getLogger(__name__)

# U_NEXT server_request methods (contracts/server_requests.py) — keep in sync when carrying.
ALLOWED_SERVER_REQUEST_METHODS = frozenset({
    "clarify",
    "approval",
    "sudo",
    "secret",
    "vault.unlock_prompt",
    "vault.save_login",
    "vault.code",
    "mcp.setup",
    "terminal.read",
    "preview.read",
    "window.read",
    "preview.act",
    "tour",
})


class ServerRequest:
    __slots__ = ("id", "sid", "method", "params", "event", "result", "answered", "created_at",
                 "qids", "locked", "on_result")

    def __init__(self, sid: str, method: str, params: dict, *, qids: list[str] | None = None,
                 on_result: Callable[[dict | None], None] | None = None) -> None:
        self.id = f"srq-{uuid.uuid4().hex[:12]}"
        self.sid = sid
        self.method = method
        self.params = dict(params)
        self.event = threading.Event()
        self.result: dict | None = None
        self.answered = False
        self.created_at = time.time()
        self.qids = list(qids) if qids else None
        self.locked: dict[str, str] = {}
        self.on_result = on_result

    def frame(self) -> dict:
        return {"jsonrpc": "2.0", "id": self.id, "method": self.method,
                "params": {"session_id": self.sid, **self.params}}

    def snapshot(self) -> dict:
        params = {"session_id": self.sid, **self.params}
        if self.locked:
            params["answers"] = dict(self.locked)
        return {"id": self.id, "method": self.method, "params": params}


_lock = threading.Lock()
_open: dict[str, ServerRequest] = {}

_write: Callable[[dict], Any] = lambda frame: None  # noqa: E731
_emit: Callable[[str, str, dict], Any] = lambda event, sid, payload: None  # noqa: E731


def bind_sinks(write_json: Callable[[dict], Any], emit: Callable[[str, str, dict], Any]) -> None:
    global _write, _emit
    _write, _emit = write_json, emit


def _emit_cancel(req: ServerRequest, reason: str) -> None:
    _emit("request.cancel", req.sid, {"id": req.id, "method": req.method, "reason": reason})


def _register(req: ServerRequest) -> None:
    if req.method not in ALLOWED_SERVER_REQUEST_METHODS:
        raise RuntimeError(f"server request {req.method!r} is not an allowed wire method")
    if not isinstance(req.sid, str) or not req.sid:
        raise ValueError("session_id is required for server requests")
    with _lock:
        _open[req.id] = req
    _write(req.frame())


def send(method: str, sid: str, params: dict, *, timeout: float | None,
         qids: list[str] | None = None) -> dict | None:
    """Send one request and block for the response ``result`` (a dict).

    Returns ``None`` when the renderer never answered (timeout, cancel, or an error response).
    ``timeout``: None → wait until answered/cancelled, 0 → return immediately, >0 → bounded wait.
    A batch (``qids``) that times out returns ``{"answers": <locked>, "timed_out": True}``.
    """
    req = ServerRequest(sid, method, params, qids=qids)
    _register(req)
    timed_out = False
    try:
        timed_out = not req.event.wait(timeout)
    finally:
        with _lock:
            _open.pop(req.id, None)
    if timed_out:
        _emit_cancel(req, "timeout")
        if req.qids is not None:
            return {"answers": dict(req.locked), "timed_out": True}
        return None
    return req.result if req.answered else None


def send_async(method: str, sid: str, params: dict, on_result: Callable[[dict | None], None]) -> Callable[[str], None]:
    """Queue-backed request. Returns ``settle(reason)`` to withdraw with ``request.cancel``."""
    req = ServerRequest(sid, method, params, on_result=on_result)
    _register(req)

    def settle(reason: str) -> None:
        with _lock:
            still_open = _open.pop(req.id, None) is not None
        if still_open:
            _emit_cancel(req, reason)

    return settle


def resolve_response(frame: dict) -> bool:
    """Route one client response frame. False when id is unknown/stale (dropped)."""
    rid = frame.get("id")
    if not isinstance(rid, str):
        return False
    with _lock:
        req = _open.get(rid)
        if req is None:
            return False
        if req.on_result is not None:
            _open.pop(rid, None)
    if "error" in frame:
        logger.debug("server request %s (%s) answered with error: %s", rid, req.method, frame.get("error"))
        req.result, req.answered = None, False
    else:
        result = frame.get("result")
        req.result = result if isinstance(result, dict) else {}
        if req.qids and "answers" in req.result:
            answers = req.result.get("answers")
            merged = dict(req.locked)
            if isinstance(answers, dict):
                merged.update(answers)
            req.result = {**req.result, "answers": merged}
        req.answered = True
    if req.on_result is not None:
        req.on_result(req.result)
    req.event.set()
    return True


def lock_answer(request_id: str, question_id: str, answer: str) -> list[str] | None:
    with _lock:
        req = _open.get(request_id)
        if req is None or req.qids is None:
            return None
        if question_id not in req.qids:
            raise ValueError(f"unknown question_id {question_id!r}")
        req.locked[question_id] = answer
        remaining = [qid for qid in req.qids if qid not in req.locked]
        if not remaining:
            req.result, req.answered = {"answers": dict(req.locked)}, True
    if not remaining:
        req.event.set()
    return remaining


def cancel(sid: str | None = None, reason: str = "interrupted") -> int:
    with _lock:
        targets = [req for req in _open.values() if sid is None or req.sid == sid]
        for req in targets:
            _open.pop(req.id, None)
    for req in targets:
        req.result, req.answered = None, False
        if req.on_result is not None:
            req.on_result(None)
        req.event.set()
        _emit_cancel(req, reason)
    return len(targets)


def open_requests(sid: str) -> list[dict]:
    with _lock:
        reqs = sorted((req for req in _open.values() if req.sid == sid), key=lambda r: r.created_at)
    return [req.snapshot() for req in reqs]


def pending_kind(sid: str) -> str:
    with _lock:
        reqs = [req for req in _open.values() if req.sid == sid]
    return min(reqs, key=lambda r: r.created_at).method if reqs else ""


def is_response_frame(obj: Any) -> bool:
    return isinstance(obj, dict) and "method" not in obj and "id" in obj and ("result" in obj or "error" in obj)


def reset_for_tests() -> None:
    with _lock:
        _open.clear()
