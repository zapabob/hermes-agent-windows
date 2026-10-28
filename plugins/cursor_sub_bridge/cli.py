"""CLI: ``hermes cursor-sub {serve,mcp,status,doctor}``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from . import queue as bridge_queue
from .shim import DEFAULT_PORT, resolve_api_key, resolve_bind_host, resolve_port, serve

logger = logging.getLogger(__name__)


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="cursor_sub_command")

    serve_p = subs.add_parser(
        "serve",
        help="Run the loopback OpenAI shim (127.0.0.1 only)",
    )
    serve_p.add_argument("--host", default=None, help="Loopback host only")
    serve_p.add_argument("--port", type=int, default=None, help=f"Port (default {DEFAULT_PORT})")

    subs.add_parser("mcp", help="Run stdio MCP (poll/respond/status) for Cursor Agent")
    subs.add_parser("status", help="Show queue directory and pending depth")
    subs.add_parser("doctor", help="Validate loopback bind + queue writability")

    subparser.set_defaults(func=cursor_sub_command)


def cursor_sub_command(args: argparse.Namespace) -> int:
    command = getattr(args, "cursor_sub_command", None)
    if not command:
        _emit({"ok": False, "error": "usage: hermes cursor-sub {serve,mcp,status,doctor}"})
        return 2

    if command == "status":
        _emit(bridge_queue.status())
        return 0

    if command == "doctor":
        payload = _doctor()
        _emit(payload)
        return 0 if payload.get("ok") else 1

    if command == "mcp":
        from .mcp_server import serve_stdio

        return serve_stdio()

    if command == "serve":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        try:
            host = resolve_bind_host(getattr(args, "host", None))
            port = resolve_port(getattr(args, "port", None))
        except ValueError as exc:
            _emit({"ok": False, "error": str(exc)})
            return 2
        httpd = serve(host=host, port=port)
        _emit(
            {
                "ok": True,
                "listening": f"http://{host}:{port}/v1",
                "api_key_hint": "CURSOR_SUB_BRIDGE_API_KEY or default local-cursor-sub",
                "note": "Keep a Cursor Agent session draining via hermes cursor-sub mcp",
            }
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.shutdown()
        return 0

    _emit({"ok": False, "error": f"unknown_command:{command}"})
    return 2


def _doctor() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    ok = True

    try:
        host = resolve_bind_host(None)
        checks.append({"name": "loopback_host", "ok": True, "host": host})
    except ValueError as exc:
        ok = False
        checks.append({"name": "loopback_host", "ok": False, "error": str(exc)})

    try:
        port = resolve_port(None)
        checks.append({"name": "port", "ok": True, "port": port})
    except (TypeError, ValueError) as exc:
        ok = False
        checks.append({"name": "port", "ok": False, "error": str(exc)})

    try:
        root = bridge_queue.queue_root()
        probe = root / ".doctor_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append({"name": "queue_writable", "ok": True, "queue_dir": root.as_posix()})
    except OSError as exc:
        ok = False
        checks.append({"name": "queue_writable", "ok": False, "error": str(exc)})

    key = resolve_api_key()
    checks.append(
        {
            "name": "api_key",
            "ok": bool(key),
            "set": bool(key),
            "is_default": key == "local-cursor-sub",
        }
    )

    status = bridge_queue.status()
    return {
        "ok": ok,
        "checks": checks,
        "queue": status,
        "reminder": (
            "Interactive Cursor Agent must run MCP poll/respond; "
            "do not use as gateway/cron default provider."
        ),
    }
