"""Owned loopback redirect, MCP effect and confidential OAuth peers.

These peers are test terminals, not replacements for the MCP client or auth
provider. Every value they issue is synthetic and every listener is owned.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import socket
import sys
import threading
from contextlib import contextmanager
from urllib.parse import parse_qs, quote, urlparse


class RedirectPeers:
    def __init__(self, route="same"):
        self.route = route
        self.redirect_status = 307
        self.lock = threading.RLock()
        self.ledger = []
        self.effects = []
        self.errors = []
        self.bases = {}
        self.servers = []
        self.listeners = []
        self.request_threads = []
        self.shutdown_threads = []
        self.request_sockets = []
        self.registrations = {}
        self.codes = {}
        self.access_token = "owned-redirect-access"
        self.expired_token = "owned-redirect-expired"
        self.refresh_token = "owned-redirect-refresh"
        self.api_key = "owned-redirect-api-key"
        self.tenant = "owned-redirect-tenant"
        self.client_id = "owned-redirect-client"
        self.client_secret = "owned-redirect-secret"

    @property
    def url(self):
        return self.bases["a"] + "/mcp"

    @property
    def issuer(self):
        return self.bases["issuer"] + "/issuer"

    @property
    def basic(self):
        raw = quote(self.client_id, safe="") + ":" + quote(self.client_secret, safe="")
        return "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")

    def headers(self, *, bearer=True):
        values = {"X-API-Key": self.api_key, "X-Tenant": self.tenant}
        if bearer:
            values["Authorization"] = "Bearer " + self.access_token
        return values

    def record(self, **fields):
        with self.lock:
            row = {"sequence": len(self.ledger), **fields}
            self.ledger.append(row)
            return row

    def snapshot(self):
        with self.lock:
            return {
                "wire": json.loads(json.dumps(self.ledger)),
                "effects": list(self.effects), "peer_errors": list(self.errors),
            }

    def wire(self, *, role=None, path=None, rpc_method=None, operation=None):
        with self.lock:
            return [dict(row) for row in self.ledger
                    if (role is None or row.get("role") == role)
                    and (path is None or row.get("path") == path)
                    and (rpc_method is None or row.get("rpc_method") == rpc_method)
                    and (operation is None or row.get("operation") == operation)]

    def metadata(self):
        return {
            "issuer": self.issuer,
            "authorization_endpoint": self.bases["issuer"] + "/authorize",
            "token_endpoint": self.bases["issuer"] + "/token",
            "registration_endpoint": self.bases["issuer"] + "/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            "authorization_response_iss_parameter_supported": True,
        }

    def registration(self, redirect):
        return {
            "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uris": [redirect], "response_types": ["code"],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "client_secret_basic", "issuer": self.issuer,
        }

    def issue_code(self, authorization_url):
        parsed = urlparse(authorization_url)
        assert parsed.scheme + "://" + parsed.netloc == self.bases["issuer"]
        assert parsed.path == "/authorize"
        params = parse_qs(parsed.query, keep_blank_values=True)
        assert params["client_id"] == [self.client_id]
        assert params["redirect_uri"][0] in self.registrations[self.client_id]["redirect_uris"]
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert len(params["code_challenge"][0]) == 43
        assert params["state"][0]
        with self.lock:
            code = "owned-redirect-code-" + str(len(self.codes))
            self.codes[code] = params
        self.record(operation="authorization_terminal", state=params["state"][0],
                    challenge=params["code_challenge"][0], issuer=self.issuer)
        return code, params["state"][0]

    def _handler(self, role):
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(3)

            def reply(self, row, status, body=None, headers=None):
                row["status"] = status
                payload = b"" if body is None else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.close_connection = True
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

            def request_row(self, body=None):
                path = urlparse(self.path).path
                return owner.record(
                    operation="http", role=role, origin=owner.bases[role],
                    url=owner.bases[role] + self.path, method=self.command, path=path,
                    headers={key.lower(): value for key, value in self.headers.items()},
                    body=body,
                    rpc_method=body.get("method") if isinstance(body, dict) else None,
                )

            def do_GET(self):  # noqa: N802
                row = self.request_row()
                if "oauth-protected-resource" in row["path"]:
                    self.reply(row, 200, {"resource": owner.url, "authorization_servers": [owner.issuer]})
                elif role == "issuer" and ("oauth-authorization-server" in row["path"]
                                            or "openid-configuration" in row["path"]):
                    self.reply(row, 200, owner.metadata())
                else:
                    self.reply(row, 405)

            def do_DELETE(self):  # noqa: N802
                self.reply(self.request_row(), 200)

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 65536:
                    self.reply(self.request_row(), 413)
                    return
                raw = self.rfile.read(length)
                path = urlparse(self.path).path
                body = (parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                        if role == "issuer" and path == "/token" else json.loads(raw))
                row = self.request_row(body)
                if role == "issuer":
                    self.issuer_post(row, body)
                    return
                if role == "a" and path in {"/mcp", "/local"}:
                    with owner.lock:
                        route = owner.route
                    if route == "same":
                        target = owner.bases["a"] + "/protected"
                    elif route == "foreign":
                        target = owner.bases["b"] + "/mcp"
                    elif route == "multi":
                        target = (owner.bases["a"] + "/local" if path == "/mcp"
                                  else owner.bases["b"] + "/hop")
                    else:
                        raise ValueError("Unknown owned route " + route)
                    row["location"] = target
                    self.reply(row, owner.redirect_status, headers={"Location": target})
                    return
                if role == "b" and path == "/hop":
                    target = owner.bases["b"] + "/mcp"
                    row["location"] = target
                    self.reply(row, 307, headers={"Location": target})
                    return
                if (role, path) not in {("a", "/protected"), ("b", "/mcp")}:
                    self.reply(row, 404)
                    return
                authorized = all(row["headers"].get(key.lower()) == value
                                 for key, value in owner.headers().items())
                if role == "a" and not authorized:
                    self.reply(row, 401, {"error": "unauthorized"}, {
                        "WWW-Authenticate": 'Bearer resource_metadata="'
                        + owner.bases["a"] + '/.well-known/oauth-protected-resource"',
                    })
                    return
                if "id" not in body:
                    self.reply(row, 202)
                    return
                method = body["method"]
                if method == "initialize":
                    result = {
                        "protocolVersion": body["params"]["protocolVersion"],
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "owned-redirect-" + role, "version": "1"},
                    }
                elif method == "tools/list":
                    result = {"tools": [{
                        "name": "write_sentinel", "description": "Record an owned nonce.",
                        "inputSchema": {"type": "object", "properties": {"nonce": {"type": "string"}},
                                        "required": ["nonce"]},
                    }]}
                elif method == "tools/call":
                    nonce = body["params"]["arguments"]["nonce"]
                    if authorized:
                        with owner.lock:
                            owner.effects.append({"role": role, "nonce": nonce, "sequence": row["sequence"]})
                    row["protected_effect"] = authorized
                    result = {"content": [{"type": "text", "text": ("owned:" if authorized else "echo:") + nonce}]}
                elif method == "ping":
                    result = {}
                else:
                    self.reply(row, 200, {"jsonrpc": "2.0", "id": body["id"],
                                          "error": {"code": -32601, "message": "Unknown owned method"}})
                    return
                self.reply(row, 200, {"jsonrpc": "2.0", "id": body["id"], "result": result})

            def issuer_post(self, row, body):
                if row["path"] == "/register":
                    info = {**body, **owner.registration(body["redirect_uris"][0])}
                    owner.registrations[owner.client_id] = info
                    row["operation"] = "registration"
                    self.reply(row, 201, info)
                    return
                if row["path"] != "/token":
                    self.reply(row, 404)
                    return
                row["operation"] = "token"
                row["grant_type"] = body.get("grant_type", [None])[0]
                # An unconditional origin filter must fail the Basic wire
                # oracle; it cannot be rescued by accepting an anonymous AS.
                if row["headers"].get("authorization") != owner.basic or "client_secret" in body:
                    self.reply(row, 401, {"error": "invalid_client"})
                    return
                if body.get("client_id") != [owner.client_id]:
                    self.reply(row, 400, {"error": "invalid_client"})
                    return
                if row["grant_type"] == "refresh_token":
                    valid = body.get("refresh_token") == [owner.refresh_token]
                elif row["grant_type"] == "authorization_code":
                    with owner.lock:
                        issued = owner.codes.pop(body.get("code", [None])[0], None)
                    verifier = body.get("code_verifier", [""])[0]
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).decode("ascii").rstrip("=")
                    valid = (issued is not None and 43 <= len(verifier) <= 128
                             and challenge == issued["code_challenge"][0]
                             and body.get("redirect_uri") == issued["redirect_uri"]
                             and body.get("client_id") == issued["client_id"])
                    row["pkce_verified"] = valid
                else:
                    valid = False
                if not valid:
                    self.reply(row, 400, {"error": "invalid_grant"})
                    return
                self.reply(row, 200, {"access_token": owner.access_token, "token_type": "Bearer",
                                      "refresh_token": owner.refresh_token, "expires_in": 3600})

            def log_message(self, *_args):
                pass

        return Handler

    def start(self):
        owner = self

        class OwnedServer(http.server.ThreadingHTTPServer):
            daemon_threads = False
            block_on_close = False

            def process_request(self, request, address):
                thread = threading.Thread(target=self.process_request_thread, args=(request, address),
                                          name="owned-redirect-request", daemon=False)
                with owner.lock:
                    owner.request_threads.append(thread)
                    owner.request_sockets.append(request)
                thread.start()

            def handle_error(self, _request, _address):
                exc = sys.exception()
                with owner.lock:
                    owner.errors.append(type(exc).__name__ + ": " + str(exc))

        for role in ("a", "b", "issuer"):
            server = OwnedServer(("127.0.0.1", 0), self._handler(role))
            self.servers.append(server)
            self.bases[role] = "http://127.0.0.1:" + str(server.server_address[1])
            listener = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                        name="owned-redirect-listener-" + role, daemon=False)
            self.listeners.append(listener)
            listener.start()

    def close(self):
        errors = []

        def attempt(label, action):
            try:
                return action()
            except BaseException as exc:
                errors.append(label + ": " + type(exc).__name__ + ": " + str(exc))
                return None

        def join(thread):
            if thread.ident is not None:
                thread.join(timeout=4)
            if thread.is_alive():
                raise AssertionError("Thread survived: " + thread.name)

        for server, listener in zip(self.servers, self.listeners):
            alive = attempt("listener_state", listener.is_alive)
            if alive is True:
                def shutdown(server=server):
                    try:
                        server.shutdown()
                    except BaseException as exc:
                        with self.lock:
                            self.errors.append("Shutdown: " + type(exc).__name__ + ": " + str(exc))

                thread = threading.Thread(target=shutdown, name="owned-redirect-shutdown", daemon=False)
                self.shutdown_threads.append(thread)
                attempt("shutdown_start", thread.start)
                attempt("shutdown_join", lambda thread=thread: join(thread))
            attempt("listener_socket_close", server.server_close)
        with self.lock:
            threads = list(self.listeners) + list(self.request_threads) + list(self.shutdown_threads)
            sockets = list(self.request_sockets)
        for thread in threads:
            attempt("owned_thread_join", lambda thread=thread: join(thread))
        refusals = []
        refusal_sockets = []
        for base in self.bases.values():
            def refusal(base=base):
                port = urlparse(base).port
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                        refusal_sockets.append(connection)
                        connection.settimeout(5)
                        connection.connect(("127.0.0.1", port))
                        raise AssertionError("Owned port still accepts: " + str(port))
                except ConnectionRefusedError:
                    refusals.append(port)

            attempt("port_refusal", refusal)
        thread_rows = []
        for thread in threads:
            row = attempt("owned_thread_state", lambda thread=thread: {
                "name": thread.name, "identity": id(thread), "native_id": thread.native_id,
                "dead": not thread.is_alive(),
            })
            if row is not None:
                thread_rows.append(row)
        resource = {"listener_threads_dead": attempt("listener_threads_dead", lambda: all(not thread.is_alive() for thread in self.listeners)),
                    "request_threads_dead": attempt("request_threads_dead", lambda: all(not thread.is_alive() for thread in self.request_threads)),
                    "shutdown_threads_dead": attempt("shutdown_threads_dead", lambda: all(not thread.is_alive() for thread in self.shutdown_threads)),
                    "owned_threads": thread_rows,
                    "listener_sockets_closed": attempt("listener_sockets_closed", lambda: all(server.socket.fileno() == -1 for server in self.servers)),
                    "request_sockets_closed": attempt("request_sockets_closed", lambda: all(sock.fileno() == -1 for sock in sockets)),
                    "refusal_sockets_closed": attempt("refusal_sockets_closed", lambda: all(sock.fileno() == -1 for sock in refusal_sockets)),
                    "refused_ports": refusals, "errors": errors}
        for key in ("listener_threads_dead", "request_threads_dead", "shutdown_threads_dead",
                    "listener_sockets_closed", "request_sockets_closed", "refusal_sockets_closed"):
            if resource[key] is not True:
                errors.append("Owned resource closure not confirmed: " + key)
        return resource


@contextmanager
def redirect_peers(record_property, route="same"):
    owner = RedirectPeers(route)
    first_body = None
    try:
        owner.start()
        try:
            yield owner
        except BaseException as exc:
            first_body = exc
            raise
    finally:
        first = first_body if first_body is not None else sys.exception()
        cleanup_errors = []

        def attempt(label, action):
            try:
                return action()
            except BaseException as exc:
                cleanup_errors.append(label + ": " + type(exc).__name__ + ": " + str(exc))
                return None

        def emit(label, name, value):
            serialized = attempt(label + "_serialization", lambda: json.dumps(value, ensure_ascii=False))
            attempt(label + "_property", lambda: record_property(
                name, serialized if serialized is not None else '{"serialization_failed":true}'))

        resource = attempt("peer_close", owner.close)
        if resource is None:
            resource = {"closure_unknown": True, "errors": ["Peer close did not return a resource ledger"]}
        snapshot = attempt("peer_final_wire_snapshot", owner.snapshot)
        emit("peer_final_wire_receipt", "redirect_peer_final_ledger", snapshot)
        emit("peer_cleanup_receipt", "redirect_peer_cleanup", resource)
        cleanup_errors.extend(resource["errors"])
        cleanup_errors.extend(owner.errors)
        if cleanup_errors:
            if first is not None:
                first.add_note("Owned peer cleanup: " + repr(cleanup_errors))
            else:
                raise AssertionError(cleanup_errors)
        if first_body is not None:
            raise first_body
