"""Minimal stdio MCP server: poll / respond / status for Cursor Agent drain.

Uses JSON-RPC 2.0 over stdin/stdout (MCP transport). No third-party MCP SDK
required so Cursor can launch it with plain ``py -3``.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from . import queue as bridge_queue

logger = logging.getLogger(__name__)

SERVER_NAME = "cursor-sub-bridge"
SERVER_VERSION = "1.0.0"

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "cursor_sub_poll",
        "description": (
            "Fetch the oldest pending Hermes→Cursor chat request. "
            "Answer with the Cursor subscription model, then call cursor_sub_respond."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "cursor_sub_respond",
        "description": "Write the assistant reply for a polled request id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Request id from cursor_sub_poll"},
                "content": {
                    "type": "string",
                    "description": "Final assistant text for Hermes",
                },
            },
            "required": ["id", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cursor_sub_status",
        "description": "Show pending queue depth and queue directory.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}
    if name == "cursor_sub_poll":
        item = bridge_queue.poll_next()
        if item is None:
            return _tool_result({"ok": True, "empty": True, "message": "no_pending_requests"})
        # Present a compact prompt for the Agent to answer.
        messages = item.get("messages") or []
        return _tool_result(
            {
                "ok": True,
                "empty": False,
                "id": item.get("id"),
                "model": item.get("model"),
                "messages": messages,
                "instruction": (
                    "Answer the messages as the assistant using the Cursor subscription "
                    "model, then call cursor_sub_respond with the same id and your reply."
                ),
            }
        )
    if name == "cursor_sub_respond":
        req_id = str(args.get("id") or "")
        content = args.get("content")
        if not isinstance(content, str):
            return _tool_result({"ok": False, "error": "content_must_be_string"}, is_error=True)
        result = bridge_queue.respond(req_id, content)
        return _tool_result(result, is_error=not result.get("ok", False))
    if name == "cursor_sub_status":
        return _tool_result(bridge_queue.status())
    return _tool_result({"ok": False, "error": f"unknown_tool:{name}"}, is_error=True)


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}

    # Notifications have no id — acknowledge by silence.
    if msg_id is None and method and str(method).startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _TOOLS}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32602, "message": "arguments must be object"},
            }
        result = _call_tool(name, arguments if isinstance(arguments, dict) else {})
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if method in ("prompts/list", "resources/list"):
        key = "prompts" if method.startswith("prompts") else "resources"
        return {"jsonrpc": "2.0", "id": msg_id, "result": {key: []}}

    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve_stdio() -> int:
    """Run until stdin closes."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger.info("cursor-sub MCP ready on stdio")
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("invalid JSON-RPC line: %s", exc)
            continue
        if not isinstance(message, dict):
            continue
        # Batch arrays are rare; ignore non-dict for simplicity.
        try:
            response = _handle(message)
        except Exception as exc:  # noqa: BLE001 — surface to MCP client
            logger.exception("handler failure")
            if message.get("id") is not None:
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )
            continue
        if response is not None:
            _write(response)
    return 0


def main(argv: list[str] | None = None) -> int:
    del argv  # unused — stdio only
    return serve_stdio()
