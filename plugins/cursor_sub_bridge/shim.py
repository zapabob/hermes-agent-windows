"""Loopback OpenAI-compatible HTTP shim for Cursor subscription drain."""

from __future__ import annotations

import json
import logging
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .queue import MODEL_ID, enqueue_chat_completion, wait_for_response

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48771
DEFAULT_API_KEY = "local-cursor-sub"


def resolve_bind_host(host: str | None = None) -> str:
    """Only loopback binds are allowed."""
    candidate = (host or os.environ.get("CURSOR_SUB_BRIDGE_HOST") or DEFAULT_HOST).strip()
    if candidate not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"non_loopback_bind_refused:{candidate}")
    # Normalize localhost / IPv6 loopback to IPv4 for the stdlib server.
    if candidate in ("localhost", "::1"):
        return "127.0.0.1"
    return candidate


def resolve_port(port: int | None = None) -> int:
    if port is not None:
        return int(port)
    raw = os.environ.get("CURSOR_SUB_BRIDGE_PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    return int(raw)


def resolve_api_key() -> str:
    return (
        os.environ.get("CURSOR_SUB_BRIDGE_API_KEY", "").strip()
        or DEFAULT_API_KEY
    )


def _openai_completion(content: str, model: str) -> dict[str, Any]:
    created = int(time.time())
    return {
        "id": f"chatcmpl-cursor-sub-{created}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def _models_payload() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 0,
                "owned_by": "cursor-sub-bridge",
            }
        ],
    }


class CursorSubHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI chat-completions surface on loopback."""

    server_version = "CursorSubBridge/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized(self) -> None:
        self._send_json(401, {"error": {"message": "unauthorized", "type": "auth_error"}})

    def _check_auth(self) -> bool:
        expected = resolve_api_key()
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            return token == expected
        # Also accept raw api-key header used by some OpenAI clients.
        alt = self.headers.get("api-key") or self.headers.get("x-api-key")
        if alt is not None and alt.strip() == expected:
            return True
        return False

    def do_GET(self) -> None:  # noqa: N802 — HTTP verb
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/v1/models", "/models"):
            if not self._check_auth():
                self._unauthorized()
                return
            self._send_json(200, _models_payload())
            return
        if path in ("/health", "/v1/health"):
            self._send_json(200, {"ok": True, "service": "cursor-sub-bridge"})
            return
        self._send_json(404, {"error": {"message": "not_found", "type": "invalid_request"}})

    def do_POST(self) -> None:  # noqa: N802 — HTTP verb
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json(404, {"error": {"message": "not_found", "type": "invalid_request"}})
            return
        if not self._check_auth():
            self._unauthorized()
            return

        length_raw = self.headers.get("Content-Length", "0")
        try:
            length = max(0, int(length_raw))
        except ValueError:
            self._send_json(400, {"error": {"message": "bad_content_length", "type": "invalid_request"}})
            return
        if length > 8_000_000:
            self._send_json(413, {"error": {"message": "payload_too_large", "type": "invalid_request"}})
            return

        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": {"message": "invalid_json", "type": "invalid_request"}})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": {"message": "body_must_be_object", "type": "invalid_request"}})
            return

        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            self._send_json(
                400,
                {"error": {"message": "messages_required", "type": "invalid_request"}},
            )
            return

        model = str(body.get("model") or MODEL_ID)
        extra = {k: v for k, v in body.items() if k not in ("messages", "model", "stream")}
        if body.get("stream") is True:
            self._send_json(
                400,
                {
                    "error": {
                        "message": "stream_not_supported",
                        "type": "invalid_request",
                    }
                },
            )
            return

        try:
            req_id = enqueue_chat_completion(messages=messages, model=model, extra=extra)
            content = wait_for_response(req_id)
        except TimeoutError:
            self._send_json(
                504,
                {
                    "error": {
                        "message": (
                            "cursor_sub_timeout: start a Cursor Agent session and "
                            "call cursor_sub_poll / cursor_sub_respond"
                        ),
                        "type": "timeout",
                    }
                },
            )
            return
        except ValueError as exc:
            self._send_json(
                502,
                {"error": {"message": str(exc), "type": "bad_gateway"}},
            )
            return
        except OSError as exc:
            logger.exception("cursor_sub enqueue/wait failed")
            self._send_json(
                500,
                {"error": {"message": f"internal_error:{exc}", "type": "server_error"}},
            )
            return

        self._send_json(200, _openai_completion(content, model))


def serve(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    """Bind the shim and serve forever (caller may run in a thread)."""
    bind_host = resolve_bind_host(host)
    bind_port = resolve_port(port)
    httpd = ThreadingHTTPServer((bind_host, bind_port), CursorSubHandler)
    logger.info(
        "cursor-sub-bridge listening on http://%s:%s/v1 (api_key configured)",
        bind_host,
        bind_port,
    )
    return httpd


def main(argv: list[str] | None = None) -> int:
    """CLI entry: serve until KeyboardInterrupt."""
    import argparse

    parser = argparse.ArgumentParser(description="Cursor sub OpenAI loopback shim")
    parser.add_argument("--host", default=None, help="Bind host (loopback only)")
    parser.add_argument("--port", type=int, default=None, help="Bind port")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        httpd = serve(host=args.host, port=args.port)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
        httpd.shutdown()
    return 0
