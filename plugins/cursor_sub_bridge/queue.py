"""File-queue exchange between the OpenAI shim and Cursor Agent MCP.

Request/response files live under ``{HERMES_HOME}/cursor_sub/``.
A Cursor Agent session drains requests via MCP ``cursor_sub_poll`` /
``cursor_sub_respond``.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

QUEUE_SUBDIR = "cursor_sub"
DEFAULT_TIMEOUT_SECONDS = 1800.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
MODEL_ID = "cursor-sub/default"


def queue_root(home: Path | None = None) -> Path:
    """Return the queue directory, creating it if needed."""
    root = (home or get_hermes_home()) / QUEUE_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _poll_timeout() -> float:
    raw = os.environ.get("CURSOR_SUB_BRIDGE_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(30.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS


def _poll_interval() -> float:
    raw = os.environ.get("CURSOR_SUB_BRIDGE_POLL_SEC", "").strip()
    if not raw:
        return DEFAULT_POLL_INTERVAL_SECONDS
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_POLL_INTERVAL_SECONDS


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def list_pending(home: Path | None = None) -> list[dict[str, Any]]:
    """Return pending request metadata (oldest first)."""
    root = queue_root(home)
    pending: list[tuple[float, dict[str, Any]]] = []
    for path in root.glob("request_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable request %s: %s", path.name, exc)
            continue
        if not isinstance(data, dict):
            continue
        req_id = str(data.get("id") or path.stem.removeprefix("request_"))
        resp = root / f"response_{req_id}.json"
        if resp.exists():
            continue
        mtime = path.stat().st_mtime
        pending.append(
            (
                mtime,
                {
                    "id": req_id,
                    "created_at": data.get("created_at"),
                    "model": data.get("model", MODEL_ID),
                    "path": path.as_posix(),
                },
            )
        )
    pending.sort(key=lambda item: item[0])
    return [item[1] for item in pending]


def poll_next(home: Path | None = None) -> dict[str, Any] | None:
    """Claim the oldest unanswered request for a Cursor Agent."""
    root = queue_root(home)
    for meta in list_pending(home):
        req_id = meta["id"]
        path = root / f"request_{req_id}.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("poll_next failed for %s: %s", req_id, exc)
            continue
        if not isinstance(data, dict):
            continue
        data["id"] = req_id
        return data
    return None


def respond(req_id: str, content: str, home: Path | None = None) -> dict[str, Any]:
    """Write a response for ``req_id`` and return a status payload."""
    cleaned_id = (req_id or "").strip()
    if not cleaned_id:
        return {"ok": False, "error": "missing_id"}
    if not isinstance(content, str):
        return {"ok": False, "error": "content_must_be_string"}

    root = queue_root(home)
    req_path = root / f"request_{cleaned_id}.json"
    if not req_path.exists():
        return {"ok": False, "error": "unknown_request", "id": cleaned_id}

    resp_path = root / f"response_{cleaned_id}.json"
    payload = {
        "id": cleaned_id,
        "content": content,
        "responded_at": time.time(),
    }
    tmp = resp_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(resp_path)
    logger.info("cursor_sub response written id=%s", cleaned_id)
    return {"ok": True, "id": cleaned_id, "path": resp_path.as_posix()}


def status(home: Path | None = None) -> dict[str, Any]:
    """Queue health snapshot for MCP / CLI."""
    root = queue_root(home)
    pending = list_pending(home)
    return {
        "ok": True,
        "queue_dir": root.as_posix(),
        "pending": len(pending),
        "pending_ids": [item["id"] for item in pending[:20]],
        "timeout_seconds": _poll_timeout(),
        "poll_interval_seconds": _poll_interval(),
        "model_id": MODEL_ID,
    }


def enqueue_chat_completion(
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    extra: dict[str, Any] | None = None,
    home: Path | None = None,
) -> str:
    """Write a chat-completions request and return its id."""
    root = queue_root(home)
    req_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:10]}"
    body: dict[str, Any] = {
        "id": req_id,
        "created_at": time.time(),
        "model": (model or MODEL_ID).strip() or MODEL_ID,
        "messages": messages,
    }
    if extra:
        body["extra"] = {k: v for k, v in extra.items() if _json_safe(v)}
    path = root / f"request_{req_id}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("cursor_sub request enqueued id=%s", req_id)
    return req_id


def wait_for_response(
    req_id: str,
    *,
    home: Path | None = None,
    timeout: float | None = None,
    interval: float | None = None,
) -> str:
    """Block until a response file appears; raise TimeoutError on expiry."""
    root = queue_root(home)
    resp_path = root / f"response_{req_id}.json"
    req_path = root / f"request_{req_id}.json"
    deadline = time.monotonic() + (timeout if timeout is not None else _poll_timeout())
    sleep_for = interval if interval is not None else _poll_interval()

    while time.monotonic() < deadline:
        if resp_path.exists():
            try:
                data = json.loads(resp_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid_response:{exc}") from exc
            content = data.get("content")
            if not isinstance(content, str):
                raise ValueError("response_missing_content")
            try:
                resp_path.unlink(missing_ok=True)
                req_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("cleanup failed for %s: %s", req_id, exc)
            return content
        time.sleep(sleep_for)

    try:
        req_path.unlink(missing_ok=True)
    except OSError:
        pass
    raise TimeoutError(req_id)
