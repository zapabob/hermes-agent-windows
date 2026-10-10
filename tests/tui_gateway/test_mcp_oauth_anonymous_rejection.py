"""An actual anonymous MCP catalogue cannot establish OAuth approval."""
import http.server
import json
import threading
from contextlib import contextmanager

import pytest

from tests.fakes.mcp_oauth_gateway import homes as homes, refused, scoped
from tui_gateway import mcp_oauth_sessions as sessions
from tui_gateway import server


@contextmanager
def anonymous_peer(record_property):
    ledger = []
    lock = threading.Lock()
    request_threads = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def do_POST(self):
            message = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            method = message["method"]
            with lock:
                ledger.append({"method": method, "authorization": self.headers.get("Authorization")})
            if method == "initialize":
                result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {"tools": {}},
                          "serverInfo": {"name": "owned-anonymous-mcp", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "public_catalogue", "description": "Owned anonymous listing.",
                                     "inputSchema": {"type": "object"}}]}
            else:
                result = {}
            if "id" in message:
                payload = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode("utf-8")
                self.send_response(200)
            else:
                payload = b""
                self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if payload:
                self.wfile.write(payload)

        def do_DELETE(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            return

    class OwnedServer(http.server.ThreadingHTTPServer):
        block_on_close = False

        def process_request(self, request, address):
            thread = threading.Thread(target=self.process_request_thread, args=(request, address), name="owned-m03-anonymous-request")
            with lock:
                request_threads.append(thread)
            thread.start()

    peer = OwnedServer(("127.0.0.1", 0), Handler)
    listener = None
    started = False
    try:
        listener = threading.Thread(target=peer.serve_forever, kwargs={"poll_interval": 0.05}, name="owned-m03-anonymous-peer")
        listener.start()
        started = True
        yield f"http://127.0.0.1:{peer.server_address[1]}/mcp", ledger
    finally:
        failures = []
        def attempt(action):
            try:
                action()
            except BaseException as error:
                failures.append(repr(error))
        if started:
            attempt(peer.shutdown)
        attempt(peer.server_close)
        with lock:
            requests = list(request_threads)
        acquired = [*([listener] if listener is not None else []), *requests]
        for thread in acquired:
            if thread.ident is not None:
                attempt(lambda thread=thread: thread.join(timeout=4))
            if thread.is_alive():
                failures.append("Actual anonymous peer thread remains alive: " + thread.name)
        attempt(lambda: refused(peer.server_address[1]))
        record_property("anonymous_peer_cleanup", json.dumps({"failures": failures,
            "threads": [{"name": thread.name, "alive": thread.is_alive()} for thread in acquired],
            "socket_fileno": peer.socket.fileno()}))
        assert failures == [], failures


@contextmanager
def owned_gateway_resources(home, record_property):
    from tools import mcp_tool as core

    resources = set()
    listeners = []
    loops = []
    errors = []
    ledger_lock = threading.Lock()
    original_thread = threading.Thread
    original_server = sessions.http.server.HTTPServer
    original_hook = threading.excepthook
    patches = pytest.MonkeyPatch()

    class OwnedThread(original_thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"}:
                with ledger_lock:
                    resources.add(self)

    def owned_server(*args, **kwargs):
        actual = original_server(*args, **kwargs)
        with ledger_lock:
            listeners.append((actual, actual.server_address[1]))
        return actual

    def hook(args):
        with ledger_lock:
            owned = args.thread in resources
        if owned:
            errors.append({"type": args.exc_type.__name__, "message": str(args.exc_value)})
        else:
            original_hook(args)

    try:
        patches.setattr(threading, "Thread", OwnedThread)
        patches.setattr(sessions.http.server, "HTTPServer", owned_server)
        patches.setattr(threading, "excepthook", hook)
        yield
    finally:
        failures = []
        def attempt(label, action):
            try:
                action()
            except BaseException as error:
                failures.append(label + ": " + repr(error))
        for rec in list(sessions._sessions.values()):
            if rec["hermes_home"] == str(home):
                attempt("release_callback_wait", lambda rec=rec: rec["flow"].mark_error("Owned anonymous fixture cleanup"))
        with ledger_lock:
            threads = list(resources)
            acquired = list(listeners)
        for thread in threads:
            if thread.name == "mcp-oauth-reports" and thread.ident is not None:
                attempt("worker_join", lambda thread=thread: thread.join(timeout=12))
                if thread.is_alive():
                    failures.append("Actual gateway worker remains alive")
        live_callback = any(thread.name == "mcp-oauth-cb-reports" and thread.is_alive() for thread in threads)
        for actual, port in acquired:
            if live_callback:
                attempt("independent_listener_shutdown", actual.shutdown)
            attempt("independent_listener_close", actual.server_close)
            attempt("independent_port_refused", lambda port=port: refused(port))
        for thread in threads:
            if thread.ident is not None:
                attempt("gateway_join", lambda thread=thread: thread.join(timeout=4))
            if thread.is_alive():
                failures.append("Actual gateway thread remains alive: " + thread.name)
        if core._mcp_loop is not None:
            loops.append((core._mcp_loop, core._mcp_thread))
        attempt("core_shutdown", core.shutdown_mcp_servers)
        for loop, thread in loops:
            attempt("core_thread_join", lambda thread=thread: thread.join(timeout=4))
            if thread.is_alive() or not loop.is_closed() or loop.is_running():
                failures.append("Actual MCP core thread or loop remains live")
        patches.undo()
        record_property("anonymous_gateway_cleanup", json.dumps({"failures": failures, "thread_errors": errors,
            "threads": [{"name": thread.name, "alive": thread.is_alive()} for thread in threads],
            "listeners": [{"port": port, "fileno": actual.socket.fileno()} for actual, port in acquired],
            "loops": [{"closed": loop.is_closed(), "running": loop.is_running(), "thread_alive": thread.is_alive()} for loop, thread in loops]}))
        assert failures == [] and errors == [], (failures, errors)


def test_public_start_rejects_actual_anonymous_catalogue_as_oauth_success(homes, record_property):
    from hermes_cli.mcp_config import _replace_mcp_servers

    work = homes / "profiles/work"
    with anonymous_peer(record_property) as (url, ledger):
        with scoped(work):
            ok, issues = _replace_mcp_servers({"reports": {"url": url, "transport": "http", "auth": "oauth", "timeout": 5}})
            assert ok and not issues, issues
        method = "mcp.servers.oauth.start"
        assert method in server._methods
        with owned_gateway_resources(work, record_property):
            response = server._methods[method](98, {"name": "reports", "profile": "work"})
            records = list(sessions._sessions.values())
            record_property("anonymous_public_start", json.dumps(response))
            assert len(records) == 1, records
            rec = records[0]
            assert rec["flow"].wait_worker_done(12), rec["flow"].snapshot()
            snapshot = rec["flow"].snapshot()
            record_property("anonymous_flow_snapshot", json.dumps(snapshot))
            record_property("anonymous_actual_ledger", json.dumps(ledger))
            assert any(row["method"] == "tools/list" for row in ledger), ledger
            assert all(row["authorization"] is None for row in ledger), ledger
            assert snapshot["status"] == "error", snapshot
            assert "no OAuth token" in snapshot["error"], snapshot
            assert "error" in response, response
            assert not (work / "mcp-tokens/reports.json").exists()
            assert not (homes / "profiles/other/mcp-tokens/reports.json").exists()
            assert rec["httpd"] is None
