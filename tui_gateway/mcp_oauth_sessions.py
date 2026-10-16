"""Session-backed MCP OAuth flows for the gateway (mcp.servers.oauth.*).

This mirrors the *provider* OAuth model used by the dashboard
(``/api/providers/oauth/{id}/start`` + ``/poll/{session_id}``) rather than the
FastAPI-request-coupled MCP dashboard flow: a ``start`` primitive kicks off a
background worker and returns ``{session_id, auth_url, flow}``; a ``poll``
primitive reports ``{status: pending|approved|error}`` until the tokens land on
disk for that server in that profile.

The underlying token machinery is the *same* one the CLI ``hermes mcp login``
uses — ``hermes_cli.mcp_config._probe_single_server`` under
``tools.mcp_oauth.force_interactive_oauth`` — so no OAuth logic is reimplemented
here. The only new piece is decoupling the two browser callbacks (authorization
URL out, ``code``/``state`` back in) from a FastAPI ``Request``:

* ``tools.mcp_dashboard_oauth.DashboardOAuthFlow`` already provides the two
  thread-safe rendezvous points (``publish_authorization_url`` /
  ``deliver_callback``). We reuse it verbatim as the bridge object.
* Instead of routing the browser redirect through a FastAPI callback route, we
  run a tiny loopback HTTP listener on ``127.0.0.1:<port>/callback`` and set the
  flow's ``redirect_uri`` to it. When the provider redirects the user's browser
  there, the listener calls ``flow.deliver_callback(...)``. This is the same
  loopback strategy the CLI uses by default, just wired to the shared bridge.

Client contract (what the desktop plugin does):
  1. call ``mcp.servers.oauth.start(profile, name)`` → ``{session_id, auth_url}``
  2. open ``auth_url`` in the native browser (``openExternal``)
  3. poll ``mcp.servers.oauth.poll(profile, name, session_id)`` until
     ``status == "approved"`` (tokens persisted) or ``"error"``.

Remote-backend variant (client-side callback): when the desktop app runs on a
DIFFERENT machine than the gateway (SSH/Tailscale remote backend), the
gateway-side ``127.0.0.1`` listener is unreachable from the user's browser —
the redirect lands on the user's machine where nothing is listening, and the
flow times out. For that topology the client binds its OWN loopback listener
(same pattern as the desktop's native gateway login), passes its
``redirect_uri`` to ``start`` (``client_redirect_uri``), and relays the
provider redirect back via ``deliver_callback_flow`` /
``mcp.servers.oauth.callback``. State verification stays server-side in
``DashboardOAuthFlow.deliver_callback`` — a relayed code with the wrong
``state`` is rejected exactly like a forged loopback hit.
"""

from __future__ import annotations

import http.server
import logging
import secrets
import threading
import time
from pathlib import Path
from threading import Event, Lock
from types import MethodType
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# Session registry: session_id -> record. A record wraps the shared
# DashboardOAuthFlow bridge plus a bit of gateway bookkeeping.
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()

# How long a completed/abandoned session lingers before GC (seconds).
_SESSION_TTL_SECONDS = 900
# Cap concurrent in-flight flows so a runaway client can't exhaust ports/threads.
_MAX_PENDING = 12


class McpOAuthStartupError(RuntimeError):
    """Carry the already-reserved caller identity without claiming cleanup."""

    def __init__(self, message: str, *, session_id: str, server_name: str):
        super().__init__(message)
        self.session_id = session_id
        self.server_name = server_name


class _ListenerSetupCleanupError(RuntimeError):
    """Retain an acquired listener whose failed startup cleanup is unconfirmed."""

    def __init__(self, cause: Exception, httpd, started: bool):
        super().__init__(str(cause))
        self.httpd = httpd
        self.started = started


class _ListenerStop(Exception):
    """Leave the actual HTTP serve loop through its normal finally path."""


class _ListenerCleanupPending(RuntimeError):
    """The acquired callback owner has not confirmed resource completion."""


class _ListenerOwner:
    def __init__(self, httpd, flow):
        self.httpd = httpd
        self.flow = flow
        self.listener = None
        self.start_attempted = False
        self.serving = False
        self.target_completed = False
        self.closed = False
        self.settle_startup_failure = False
        self.lock = Lock()
        self.stop_requested = Event()
        self.completed = Event()
        self.serve = httpd.serve_forever
        self.service_actions = httpd.service_actions
        with _sessions_lock:
            rec = _sessions.get(flow.flow_id)
            self.rec = rec if rec is not None and rec["flow"] is flow else None
            if self.rec is not None:
                self.rec["httpd"] = httpd

    def _close_locked(self):
        if not self.closed:
            self.httpd.server_close()
            self.closed = True

    def _clear_record_locked(self):
        if self.rec is not None:
            with _sessions_lock:
                if self.rec.get("httpd") is self.httpd:
                    self.rec["httpd"] = None

    def _settle_locked(self):
        if self.closed and (self.target_completed or not self.start_attempted):
            self.completed.set()
            if self.settle_startup_failure:
                self._clear_record_locked()
                self.flow.mark_worker_done()

    def authorize_startup_settlement(self):
        # Only start_flow can prove it has not acquired an OAuth worker.
        with self.lock:
            self.settle_startup_failure = True
            self._settle_locked()

    def request_stop(self):
        with self.lock:
            self.stop_requested.set()
            if not self.serving or self.target_completed:
                self._close_locked()
            self._settle_locked()

    def check_stop(self):
        if self.stop_requested.is_set():
            raise _ListenerStop()
        self.service_actions()
        if self.stop_requested.is_set():
            raise _ListenerStop()

    def run(self, *, poll_interval=0.5):
        try:
            with self.lock:
                enter = not self.stop_requested.is_set()
                self.serving = enter
            if enter:
                self.serve(poll_interval=poll_interval)
        except _ListenerStop:
            pass
        finally:
            with self.lock:
                self.target_completed = True
                try:
                    self._close_locked()
                except Exception:
                    logger.exception("MCP OAuth callback socket close is unconfirmed")
                self._settle_locked()

    def shutdown(self):
        deadline = time.monotonic() + 5.0
        try:
            self.request_stop()
        except Exception as exc:
            raise _ListenerCleanupPending(
                'MCP OAuth callback socket closure is unconfirmed'
            ) from exc
        if not self.completed.wait(max(0.0, deadline - time.monotonic())):
            raise _ListenerCleanupPending("MCP OAuth callback cleanup is unconfirmed")
        if self.start_attempted:
            self.listener.join(timeout=max(0.0, deadline - time.monotonic()))
            if self.listener.is_alive():
                raise _ListenerCleanupPending("MCP OAuth callback thread exit is unconfirmed")
        with self.lock:
            self._clear_record_locked()


def _gc_sessions() -> None:
    """Collect expired sessions only after owned worker/listener cleanup."""
    cutoff = time.time() - _SESSION_TTL_SECONDS
    with _sessions_lock:
        stale = [sid for sid, rec in _sessions.items()
                 if rec["created_at"] < cutoff and rec["flow"].worker_done
                 and rec.get("httpd") is None]
        for sid in stale:
            _sessions.pop(sid, None)


def _shutdown_listener(rec: Dict[str, Any]) -> None:
    server = rec.get("httpd")
    if server is not None:
        owner = getattr(server, "_hermes_oauth_listener_owner", None)
        if owner is not None and owner.httpd is server:
            owner.shutdown()
            if rec.get("httpd") is server:
                rec["httpd"] = None
            return
        try:
            if rec.get("listener_started", True):
                server.shutdown()
        finally:
            server.server_close()
        rec["httpd"] = None


def _validate_client_redirect_uri(uri: str) -> str:
    """Validate a client-supplied loopback redirect URI.

    Only plain-http loopback URLs are accepted (``http://127.0.0.1:<port>/...``
    or ``http://localhost:<port>/...``), mirroring RFC 8252 native-app rules —
    the client hosts a one-shot listener on ITS machine, so anything else
    (public hosts, https proxies, schemes) is rejected to keep the gateway from
    pinning an attacker-controlled redirect into a DCR registration.
    """
    parsed = urlparse(str(uri or "").strip())
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "http"
        or host not in ("127.0.0.1", "localhost", "::1")
        or not parsed.port
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "client_redirect_uri must be a loopback http URL like "
            "http://127.0.0.1:<port>/callback"
        )
    return f"http://{'[' + host + ']' if ':' in host else host}:{parsed.port}{parsed.path or '/callback'}"


def _start_loopback_listener(flow) -> "http.server.HTTPServer":
    """Bind a loopback callback listener that feeds the flow's deliver_callback.

    Returns the running HTTPServer (already serving on a daemon thread). The
    bound port is read back off ``server.server_address`` so the caller can set
    ``flow.redirect_uri`` to the matching ``/callback`` URL BEFORE the worker
    starts the OAuth flow (the redirect URI must be pinned at authorization).
    """

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — stdlib naming
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") not in ("/callback", ""):
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query, keep_blank_values=True)
            code = (qs.get("code") or [None])[0]
            state = (qs.get("state") or [None])[0]
            error = (qs.get("error") or [None])[0]
            iss = (qs.get("iss") or [None])[0]
            body = b"<h1>Authorization received</h1><p>You can close this tab and return to Hermes.</p>"
            status = 200
            try:
                flow.deliver_callback(code=code, state=state, error=error, iss=iss)
            except Exception:
                body = b"<h1>OAuth callback rejected</h1><p>The callback was invalid or already used.</p>"
                status = 400
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def log_message(self, *_a):  # silence stdlib request logging
            return

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    owner = None
    try:
        owner = _ListenerOwner(httpd, flow)
        httpd._hermes_oauth_listener_owner = owner
        httpd.service_actions = owner.check_stop

        def serve_owned(server, *, poll_interval=0.5):
            # Keep the bound HTTPServer identity for existing direct callers.
            owner.run(poll_interval=poll_interval)

        httpd.serve_forever = MethodType(serve_owned, httpd)
        owner.listener = threading.Thread(
            target=httpd.serve_forever,
            kwargs={"poll_interval": 0.5},
            daemon=True,
            name=f"mcp-oauth-cb-{flow.server_name}",
        )
        owner.start_attempted = True
        owner.listener.start()
    except Exception as exc:
        if owner is None:
            # No callback Thread has been constructed or started. Preserve
            # the acquired socket if even this direct closure is uncertain.
            try:
                httpd.server_close()
            except Exception as cleanup:
                failure = _ListenerSetupCleanupError(exc, httpd, False)
                failure.add_note("MCP OAuth callback socket closure failed: " + repr(cleanup))
                raise failure from exc
            raise
        try:
            owner.request_stop()
        except Exception:
            logger.exception("MCP OAuth listener startup cleanup is unconfirmed")
        # start() may have acquired a native thread before raising, even
        # before its ident is populated. Carry ownership without waiting.
        raise _ListenerSetupCleanupError(exc, httpd, owner.start_attempted) from exc
    return httpd


def _worker(session_id: str, hermes_home: str, server_name: str, cfg: dict, reconnect_live: bool) -> None:
    """Drive the interactive MCP OAuth probe under the shared dashboard bridge.

    Structurally identical to ``web_server._run_dashboard_mcp_oauth`` — the same
    HERMES_HOME override + secret-scope + force_interactive_oauth +
    dashboard_oauth_flow wrapping around ``_probe_single_server`` — but keyed to
    our session record instead of a FastAPI request. On success the token file
    exists on disk (verified via ``_oauth_tokens_present``) and the server config
    is (re)saved into the profile's config.yaml.
    """
    from hermes_cli.mcp_config import (
        _probe_single_server,
    )
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    rec = _sessions.get(session_id)
    flow = rec["flow"] if rec else None
    try:
        from agent.secret_scope import (
            build_profile_secret_scope,
            reset_secret_scope,
            set_secret_scope,
        )
        from tools.mcp_dashboard_oauth import dashboard_oauth_flow
        from tools.mcp_oauth import force_interactive_oauth
        from tools.mcp_oauth_manager import get_manager

        home_token = secret_token = None
        try:
            home_token = set_hermes_home_override(hermes_home)
            secret_token = set_secret_scope(build_profile_secret_scope(Path(hermes_home)))
            with force_interactive_oauth(), dashboard_oauth_flow(flow):
                from tools.mcp_oauth import HermesTokenStorage

                manager = get_manager()
                storage = HermesTokenStorage(server_name)
                backup, backup_generations = storage.snapshot_with_generations()
                previous_entry = None
                try:
                    previous_entry = manager.remove(
                        server_name,
                        hermes_home=hermes_home,
                        removal_owner=flow,
                    )
                    tools = _probe_single_server(
                        server_name,
                        cfg,
                        connect_timeout=max(float(cfg.get("connect_timeout", 0) or 0), 315),
                    )
                    if flow is None:
                        raise RuntimeError("MCP OAuth flow state is unavailable")
                    manager.adopt_dashboard_flow(
                        flow,
                        storage,
                        [{"name": t, "description": d} for t, d in tools],
                    )
                    if reconnect_live:
                        from tools.mcp_tool import reconnect_mcp_server

                        reconnect_mcp_server(server_name)
                except Exception:
                    binding = flow.config_binding if flow is not None else None
                    authority_current = binding is None
                    if binding is not None:
                        try:
                            binding.assert_current()
                            authority_current = True
                        except Exception:
                            authority_current = False
                    if authority_current:
                        try:
                            storage.restore_snapshot_if_owned(backup, backup_generations)
                        except Exception as restore_exc:
                            from tools.mcp_dashboard_oauth import McpOAuthConfigChangedError

                            if not isinstance(restore_exc, McpOAuthConfigChangedError):
                                raise
                            authority_current = False
                    if authority_current:
                        manager.restore_entry(
                            server_name,
                            previous_entry,
                            hermes_home=hermes_home,
                            binding=binding,
                            removal_owner=flow,
                        )
                    else:
                        storage.rollback_owned_effects()
                    raise
                finally:
                    manager.release_dashboard_flow(flow)
        finally:
            if secret_token is not None:
                reset_secret_scope(secret_token)
            if home_token is not None:
                reset_hermes_home_override(home_token)
    except Exception as exc:
        msg = str(exc)
        try:
            from tools.mcp_oauth import humanize_oauth_registration_error

            humanized = humanize_oauth_registration_error(
                server_name, exc, server_url=cfg.get("url") if isinstance(cfg, dict) else None
            )
            if humanized:
                msg = humanized
        except Exception:
            pass
        if flow is not None:
            flow.mark_error(msg)
    finally:
        if rec is not None:
            try:
                _shutdown_listener(rec)
            except _ListenerCleanupPending as pending:
                # A close failure is not evidence of a callback still running.
                if pending.__cause__ is not None:
                    raise
                httpd = rec.get("httpd")
                owner = getattr(httpd, "_hermes_oauth_listener_owner", None)
                if not isinstance(owner, _ListenerOwner) or owner.listener is None:
                    raise
                callback = owner.listener

                def owns_pending_listener():
                    return (
                        _sessions.get(session_id) is rec
                        and rec.get("flow") is flow
                        and rec.get("httpd") is httpd
                        and rec.get("server_name") == server_name
                        and rec.get("hermes_home") == hermes_home
                        and getattr(httpd, "_hermes_oauth_listener_owner", None) is owner
                        and owner.httpd is httpd and owner.flow is flow
                        and owner.rec is rec and owner.listener is callback
                        and owner.start_attempted
                    )

                with _sessions_lock:
                    if not owns_pending_listener():
                        raise
                # This acquired OAuth worker keeps responsibility for late
                # callback completion. Neither ownership lock is held here.
                owner.completed.wait()
                callback.join()
                with _sessions_lock:
                    if not owns_pending_listener():
                        raise
                _shutdown_listener(rec)
        if flow is not None:
            flow.mark_worker_done()


def start_flow(
    hermes_home: str,
    server_name: str,
    cfg: dict,
    *,
    config_binding=None,
    reconnect_live: bool = False,
    url_timeout: float = 30.0,
    client_redirect_uri: Optional[str] = None,
) -> Dict[str, Any]:
    """Begin an MCP OAuth flow and return ``{session_id, auth_url, flow}``.

    ``cfg`` is the server's resolved config dict (must have ``url`` and be
    OAuth-capable). ``hermes_home`` is the already-resolved profile home dir
    string. Blocks up to ``url_timeout`` for the worker to publish the browser
    authorization URL, then returns it.

    ``client_redirect_uri`` (remote-backend variant): a loopback callback URL
    the CLIENT hosts on its own machine. When set (and valid), no gateway-side
    listener is bound — the OAuth ``redirect_uri`` is pinned to the client's
    listener, and the client relays the redirect's ``code``/``state`` back via
    ``deliver_callback_flow``. Invalid values raise ``ValueError``.
    """
    from hermes_constants import hermes_home_key
    from tools.mcp_dashboard_oauth import DashboardOAuthFlow, SavedMcpConfigBinding

    deadline = time.monotonic() + max(0.0, url_timeout)
    caller_home = hermes_home_key(hermes_home)

    if client_redirect_uri is not None:
        client_redirect_uri = _validate_client_redirect_uri(client_redirect_uri)

    _gc_sessions()

    while True:
        with _sessions_lock:
            blockers = [
                r["flow"] for r in _sessions.values()
                if r["server_name"] == server_name
                and hermes_home_key(r["hermes_home"]) == caller_home
                and not r["flow"].worker_done
            ]
            if any(not previous.cancelled for previous in blockers):
                raise RuntimeError(f"MCP OAuth for '{server_name}' is already in progress")
            if not blockers:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for MCP authorization URL")
                if sum(not r["flow"].worker_done for r in _sessions.values()) >= _MAX_PENDING:
                    raise RuntimeError("Too many MCP OAuth flows are already in progress")
                session_id = secrets.token_urlsafe(24)
                binding = config_binding
                if binding is None:
                    binding = SavedMcpConfigBinding.capture(hermes_home, server_name)
                else:
                    binding.assert_current()
                flow = DashboardOAuthFlow(
                    flow_id=session_id, server_name=server_name, profile=None,
                    hermes_home=hermes_home, redirect_uri=client_redirect_uri or "",
                    reconnect_live=reconnect_live,
                    config_binding=binding,
                )
                rec = {
                    "session_id": session_id, "server_name": server_name,
                    "hermes_home": hermes_home, "flow": flow,
                    "httpd": None, "created_at": time.time(),
                }
                # Reserve before listener/thread acquisition. Other starts see
                # this active owner while setup and network waits run outside.
                _sessions[session_id] = rec
                break
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not blockers[0].wait_worker_done(remaining):
            raise TimeoutError("Timed out waiting for cancelled MCP OAuth flow to finish")

    worker = None
    try:
        if not client_redirect_uri:
            httpd = _start_loopback_listener(flow)
            rec["httpd"] = httpd
            port = httpd.server_address[1]
            flow.redirect_uri = f"http://127.0.0.1:{port}/callback"
        worker = threading.Thread(
            target=_worker,
            args=(session_id, hermes_home, server_name, dict(cfg), reconnect_live),
            daemon=True, name=f"mcp-oauth-{server_name}",
        )
        worker.start()
        auth_url = None
        # wait_for_authorization_url is async; run its wait synchronously.
        while time.monotonic() < deadline:
            snap = flow.snapshot()
            if snap.get("authorization_url"):
                auth_url = snap["authorization_url"]
                break
            if snap.get("status") == "error":
                raise RuntimeError(snap.get("error") or "MCP OAuth flow failed before authorization")
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        if not auth_url:
            raise TimeoutError("Timed out waiting for MCP authorization URL")
    except Exception as exc:
        flow.mark_error(str(exc))
        # An acquired OAuth worker owns rollback and completion. Only an
        # unacquired worker permits this caller to authorize local settlement.
        if worker is None:
            server = exc.httpd if isinstance(exc, _ListenerSetupCleanupError) else rec.get("httpd")
            owner = getattr(server, "_hermes_oauth_listener_owner", None)
            if isinstance(exc, _ListenerSetupCleanupError) and owner is None:
                rec["httpd"] = server
                rec["listener_started"] = False
            if owner is not None and owner.httpd is server and owner.flow is flow and owner.rec is rec:
                owner.authorize_startup_settlement()
                try:
                    owner.request_stop()
                except Exception:
                    logger.exception("MCP OAuth listener cleanup failed for '%s'", server_name)
            else:
                try:
                    _shutdown_listener(rec)
                except Exception:
                    logger.exception("MCP OAuth listener cleanup failed for '%s'", server_name)
                else:
                    flow.mark_worker_done()
        raise McpOAuthStartupError(
            str(exc), session_id=session_id, server_name=server_name,
        ) from exc

    return {
        "session_id": session_id,
        "auth_url": auth_url,
        # "pkce" mirrors the provider-OAuth ``flow`` discriminator: the client
        # opens a URL then polls (no user_code to type, unlike device_code).
        "flow": "pkce",
    }


def _lookup_flow(session_id: str, server_name: str):
    """Resolve only sessions owned by the caller's current profile HOME."""
    from hermes_constants import hermes_home_key

    with _sessions_lock:
        rec = _sessions.get(session_id)
    if rec is None or hermes_home_key(rec["hermes_home"]) != hermes_home_key():
        return None, "OAuth session not found or expired"
    if rec["server_name"] != server_name:
        return None, "server name mismatch for session"
    return rec, None


def poll_flow(session_id: str, server_name: str) -> Dict[str, Any]:
    """Poll a session's status → ``{status, error_message?, auth_url?, tools?}``.

    ``status`` is one of ``pending`` | ``approved`` | ``error`` — the same
    vocabulary as the provider poll endpoint (``authorization_required`` from
    the underlying bridge maps to ``pending`` since the client only needs to
    know whether to keep waiting).
    """
    rec, error = _lookup_flow(session_id, server_name)
    if rec is None:
        return {"status": "error", "error_message": error}

    flow = rec["flow"]
    snap = flow.snapshot()
    raw = snap.get("status")
    if raw == "approved":
        status = "approved"
    elif raw == "error":
        status = "error"
    else:
        status = "pending"
    out: Dict[str, Any] = {
        "session_id": session_id,
        "status": status,
        "error_message": snap.get("error"),
        "auth_url": snap.get("authorization_url"),
    }
    if status == "approved":
        out["tools"] = list(getattr(flow, "tools", []) or [])
    return out


def deliver_callback_flow(
    session_id: str,
    server_name: str,
    *,
    code: Optional[str],
    state: Optional[str],
    error: Optional[str] = None,
    iss: Optional[str] = None,
) -> Dict[str, Any]:
    """Relay a client-captured OAuth redirect into a session's flow.

    Remote-backend companion to ``start_flow(client_redirect_uri=...)``: the
    desktop app's loopback listener caught the provider redirect on the USER'S
    machine and forwards ``code``/``state`` (or ``error``) here. Security
    properties are unchanged from the gateway-listener path — the underlying
    ``DashboardOAuthFlow.deliver_callback`` verifies ``state`` against the
    pinned authorization request (constant-time compare) and rejects replays,
    so a forged or replayed relay fails identically to a forged loopback hit.

    Returns ``{ok: true}`` on acceptance or ``{ok: false, error_message}``.
    """
    rec, lookup_error = _lookup_flow(session_id, server_name)
    if rec is None:
        return {"ok": False, "error_message": lookup_error}

    flow = rec["flow"]
    try:
        flow.deliver_callback(code=code, state=state, error=error, iss=iss)
    except ValueError as exc:
        return {"ok": False, "error_message": str(exc)}
    return {"ok": True, "session_id": session_id}


def cancel_flow(session_id: str, server_name: str) -> Dict[str, Any]:
    """Request cancellation of this profile's unadmitted callback.

    The worker owns listener shutdown in its finally block. Waking its flow
    releases the callback wait without blocking the gateway reader on HTTP
    shutdown; clients continue polling the actual settled result.
    """
    rec, error = _lookup_flow(session_id, server_name)
    if rec is None:
        return {"ok": False, "error_message": error}
    flow = rec["flow"]
    cancelled = flow.cancel_pending()
    return {"ok": True, "session_id": session_id, "cancelled": cancelled,
            "status": flow.snapshot()["status"]}
