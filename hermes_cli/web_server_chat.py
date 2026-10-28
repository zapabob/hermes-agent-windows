"""WebSocket gate helpers for Webapp host-terminal (and similar) sockets.

Upstream extracts these from the dashboard chat surface; on this tree they wrap
the existing ``hermes_cli.web_server`` auth primitives so ``web_routers.webapp``
can open ``/api/host-terminal`` without a second HTTP stack.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)


def __getattr__(name: str):
    if name in {"_PTY_BRIDGE_AVAILABLE", "PtyUnavailableError"}:
        from hermes_cli import web_server as server

        return getattr(server, name)
    raise AttributeError(name)


async def _pty_fail(ws: WebSocket, exc: BaseException, *, surface: str = "Terminal") -> None:
    """Tell the browser the PTY surface is unavailable, then close."""
    try:
        await ws.send_json({"type": "error", "surface": surface, "error": str(exc)})
    except (RuntimeError, OSError, WebSocketDisconnect):
        pass
    try:
        await ws.close(code=1011, reason=str(exc)[:120] or "pty unavailable")
    except (RuntimeError, OSError, WebSocketDisconnect):
        pass


async def _ws_gate(ws: WebSocket, socket: str) -> Optional[tuple[str, str, str]]:
    """Authenticate a WebSocket upgrade for *socket*; close and return None on refusal.

    Returns ``(peer, mode, cred)`` when the upgrade may proceed (caller must ``accept``).
    """
    from hermes_cli import web_server as server
    from hermes_cli.web_session_sockets import HOST_TERMINAL_SOCKET, ticket_refusal

    peer = ws.client.host if ws.client else "?"
    mode = server._ws_auth_mode()

    host_origin_reason = server._ws_host_origin_reason(ws)
    if host_origin_reason is not None:
        logger.warning("%s refused: %s peer=%s", socket, host_origin_reason, peer)
        await ws.close(code=4403, reason=server._ws_close_reason(host_origin_reason))
        return None

    client_reason = server._ws_client_reason(ws)
    if client_reason is not None:
        logger.warning("%s refused: %s peer=%s", socket, client_reason, peer)
        await ws.close(code=4408, reason=server._ws_close_reason(client_reason))
        return None

    auth_reason, cred = server._ws_auth_reason(ws)
    if auth_reason is not None:
        logger.warning(
            "%s auth rejected reason=%s mode=%s cred=%s peer=%s",
            socket, auth_reason, mode, cred, peer,
        )
        await ws.close(code=4401, reason=server._ws_close_reason(f"auth: {auth_reason}"))
        return None

    # Host terminal requires a ticket minted for that socket when tickets are in play.
    ticket_info = getattr(ws, "_hermes_ws_ticket", None)
    if isinstance(ticket_info, dict):
        refusal = ticket_refusal(
            ticket_info,
            socket,
            auth_required=bool(getattr(ws.app.state, "auth_required", False)),
        )
        if refusal is not None:
            logger.warning("%s ticket refused: %s peer=%s", socket, refusal, peer)
            await ws.close(code=4403, reason=server._ws_close_reason(refusal))
            return None
    elif socket == HOST_TERMINAL_SOCKET and bool(getattr(ws.app.state, "auth_required", False)):
        # Gated Webapp: host terminal opens only with its own ticket.
        await ws.close(code=4403, reason="host terminal requires a socket ticket")
        return None

    return peer, mode, cred or "ok"
