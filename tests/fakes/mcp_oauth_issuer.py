"""Real loopback OAuth/MCP peer with PKCE and token/effect ledgers."""

import base64
import hashlib
import http.server
import json
import threading
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse


class OwnedIssuer:
    def __init__(self, required=True):
        self.required = required
        self.ledger = []
        self.lock = threading.Lock()
        self.registrations = {}
        self.codes = {}
        self.token_started = threading.Event()
        self.token_release = threading.Event()
        self.token_release.set()
        self.token = "owned-synthetic-token"
        self.base = ""
        self.request_threads = []

    @property
    def issuer(self):
        return self.base + "/issuer"

    @property
    def mcp_url(self):
        return self.base + "/mcp"

    def record(self, operation, **fields):
        with self.lock:
            self.ledger.append({"operation": operation, **fields})

    def operations(self, operation):
        with self.lock:
            return [dict(row) for row in self.ledger if row["operation"] == operation]

    def issue_code(self, authorization_url):
        params = parse_qs(urlparse(authorization_url).query, keep_blank_values=True)
        client = params["client_id"][0]
        assert client in self.registrations
        assert params["redirect_uri"][0] in self.registrations[client]["redirect_uris"]
        assert params["code_challenge_method"] == ["S256"]
        assert len(params["code_challenge"][0]) == 43
        code = f"owned-code-{len(self.codes)}"
        self.codes[code] = params
        self.record("authorization", state=params["state"][0])
        return code, params["state"][0], params["redirect_uri"][0]


@contextmanager
def serve_issuer(required=True):
    owner = OwnedIssuer(required)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def reply(self, status, body=None, headers=None):
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

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            owner.record("get", path=path, authorization=self.headers.get("Authorization"))
            if "oauth-protected-resource" in path:
                self.reply(200, {"resource": owner.mcp_url, "authorization_servers": [owner.issuer]})
            elif "oauth-authorization-server" in path or "openid-configuration" in path:
                self.reply(200, {
                    "issuer": owner.issuer, "authorization_endpoint": owner.base + "/authorize",
                    "token_endpoint": owner.base + "/token", "registration_endpoint": owner.base + "/register",
                    "response_types_supported": ["code"], "grant_types_supported": ["authorization_code"],
                    "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"],
                    "authorization_response_iss_parameter_supported": owner.required,
                })
            else:
                self.reply(405)

        def do_DELETE(self):  # noqa: N802
            self.reply(200)

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if path == "/register":
                metadata = json.loads(raw)
                client_id = f"owned-client-{len(owner.registrations)}"
                owner.registrations[client_id] = metadata
                owner.record("registration", redirect_uris=metadata["redirect_uris"])
                self.reply(201, {**metadata, "client_id": client_id, "token_endpoint_auth_method": "none"})
                return
            if path == "/token":
                params = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                owner.record("token_request")
                authorization = owner.codes.pop(params.get("code", [None])[0], None)
                verifier = params.get("code_verifier", [""])[0]
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                if not authorization or not 43 <= len(verifier) <= 128 or challenge != authorization["code_challenge"][0]:
                    self.reply(400, {"error": "invalid_grant"})
                    return
                if params.get("client_id") != authorization["client_id"] or params.get("redirect_uri") != authorization["redirect_uri"]:
                    self.reply(400, {"error": "invalid_grant"})
                    return
                owner.token_started.set()
                if not owner.token_release.wait(8):
                    self.reply(500, {"error": "owned_barrier_timeout"})
                    return
                owner.record("token_redemption")
                self.reply(200, {"access_token": owner.token, "token_type": "Bearer", "expires_in": 3600})
                return
            if path != "/mcp":
                self.reply(404)
                return
            message = json.loads(raw)
            method = message["method"]
            header = self.headers.get("Authorization")
            owner.record("mcp_request", method=method, authorization=header)
            if header != f"Bearer {owner.token}":
                self.reply(401, {"error": "unauthorized"}, {
                    "WWW-Authenticate": f'Bearer resource_metadata="{owner.base}/.well-known/oauth-protected-resource"',
                })
                return
            if "id" not in message:
                self.reply(202)
                return
            if method == "initialize":
                result = {
                    "protocolVersion": message["params"]["protocolVersion"],
                    "capabilities": {"tools": {}}, "serverInfo": {"name": "owned-issuer", "version": "1"},
                }
            elif method == "tools/list":
                result = {"tools": [{
                    "name": "write_sentinel", "description": "Record an owned nonce.",
                    "inputSchema": {"type": "object", "properties": {"nonce": {"type": "string"}}, "required": ["nonce"]},
                }]}
            elif method == "tools/call":
                nonce = message["params"]["arguments"]["nonce"]
                owner.record("sentinel", nonce=nonce)
                result = {"content": [{"type": "text", "text": "owned:" + nonce}]}
            elif method == "ping":
                result = {}
            else:
                self.reply(200, {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Unknown method"}})
                return
            self.reply(200, {"jsonrpc": "2.0", "id": message["id"], "result": result})

        def log_message(self, *_args):
            pass

    class OwnedHTTPServer(http.server.ThreadingHTTPServer):
        daemon_threads = False
        block_on_close = False  # Explicit bounded joins below own every thread.

        def process_request(self, request, client_address):
            thread = threading.Thread(
                target=self.process_request_thread,
                args=(request, client_address),
                name="owned-m03-issuer-request",
                daemon=False,
            )
            with owner.lock:
                owner.request_threads.append(thread)
            thread.start()

    httpd = None
    listener = None
    started = False
    try:
        httpd = OwnedHTTPServer(("127.0.0.1", 0), Handler)
        owner.base = f"http://127.0.0.1:{httpd.server_address[1]}"
        listener = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, name="owned-m03-issuer")
        listener.start()
        started = True
        yield owner
    finally:
        errors = []

        def attempt(label, action):
            try:
                action()
            except BaseException as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")

        def joined(thread):
            if thread.ident is None:
                # start() failed; the ledger retains this unstarted thread.
                assert not thread.is_alive(), thread.name
                return
            thread.join(timeout=4)
            assert not thread.is_alive(), thread.name

        owner.token_release.set()
        if httpd is not None:
            if started:
                attempt("issuer_shutdown", httpd.shutdown)
            attempt("issuer_socket_close", httpd.server_close)
        if started:
            attempt("issuer_listener_exit", lambda: joined(listener))
        with owner.lock:
            request_threads = list(owner.request_threads)
        for index, thread in enumerate(request_threads):
            attempt(f"issuer_request_exit_{index}", lambda thread=thread: joined(thread))
        assert not errors, errors
