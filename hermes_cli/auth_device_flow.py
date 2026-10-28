"""Loopback PKCE helpers for browser OAuth logins (subset of upstream's ``hermes_cli.auth_device_flow``).

Only what :mod:`hermes_cli.auth_oauth_pkce_plugin` drives is ported: S256 PKCE material and the RFC 8252
loopback redirect listener. The device-code flow, polling and Nous helpers of the upstream module are not
part of this fork's plugin OAuth broker. ``_can_open_graphical_browser`` and ``_print_loopback_ssh_hint`` stay
implemented in ``hermes_cli.auth`` (where this fork's Spotify login also uses them) and are re-exported so a
caller, or a test, resolves them from one place.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from hermes_cli.auth import AuthError, _can_open_graphical_browser, _print_loopback_ssh_hint


def _pkce_code_verifier(length: int = 64) -> str:
    return base64.urlsafe_b64encode(os.urandom(length)).decode("ascii").rstrip("=")[:128]


def _pkce_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _make_loopback_callback_handler(
    expected_path: str, *, display_name: str,
) -> tuple[type[BaseHTTPRequestHandler], dict[str, Any]]:
    """Handler class for an RFC 8252 loopback redirect plus the dict it fills in.

    Only a GET on *expected_path* is accepted (anything else is a 404 and leaves the result
    untouched), so a nonce embedded in the path acts as the CSRF ``state`` for authorization
    servers that do not echo an explicit ``state`` parameter.
    """
    result: dict[str, Any] = {"code": None, "state": None, "error": None, "error_description": None}

    class _LoopbackCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != expected_path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found.")
                return

            params = parse_qs(parsed.query)
            for key in result:
                result[key] = params.get(key, [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            outcome = "failed" if result["error"] else "received"
            self.wfile.write(
                f"<html><body><h1>{display_name} authorization {outcome}.</h1>"
                "You can close this tab.</body></html>".encode())

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return _LoopbackCallbackHandler, result


def _bind_loopback_callback_server(
    host: str, port: int, handler_cls: type[BaseHTTPRequestHandler], *, err: Callable[..., AuthError],
    bind_failed_code: str,
) -> HTTPServer:
    """Bind the loopback listener up front (``port=0`` = OS-assigned) so the redirect URI sent to
    the authorization server names a port we already own: no probe-close-rebind race."""

    class _ReuseHTTPServer(HTTPServer):
        allow_reuse_address = True

    try:
        return _ReuseHTTPServer((host, port), handler_cls)
    except OSError as exc:
        raise err(f"Could not bind callback server on {host}:{port}: {exc}", bind_failed_code) from exc


def _serve_loopback_callback(
    server: HTTPServer, result: dict[str, Any], *, timeout_seconds: float, err: Callable[..., AuthError],
    timeout_code: str,
) -> dict[str, Any]:
    """Serve *server* until the redirect lands in *result* or the deadline passes; always closes."""
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    deadline = time.monotonic() + max(5.0, timeout_seconds)
    try:
        while time.monotonic() < deadline:
            if result["code"] or result["error"]:
                return result
            time.sleep(0.1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)
    raise err("Authorization timed out waiting for the local callback.", timeout_code)


__all__ = [
    "_bind_loopback_callback_server", "_can_open_graphical_browser", "_make_loopback_callback_handler",
    "_pkce_code_challenge", "_pkce_code_verifier", "_print_loopback_ssh_hint", "_serve_loopback_callback",
]
