"""Actual admitted MCP2/HTTPX2 redirect boundary through public discovery.

Owned callback delivery is a user terminal, not listener/UI qualification.
Only the port origin dimension is exercised. No auth producer is replaced.
"""

from __future__ import annotations

import asyncio
import dis
import hashlib
import importlib.metadata
import json
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.fakes.mcp_oauth_gateway import scoped
from tests.fakes.mcp_redirect_peer import redirect_peers

pytestmark = pytest.mark.windows_only


class NativeObserver:
    """Copy actual-call evidence and hold read-only objects until finalization."""

    def __init__(self, core):
        import httpx2
        import httpx2._content as content
        from mcp.client.auth.oauth2 import OAuthClientProvider, OAuthContext

        self.core = core
        self.loop_thread = None
        self.byte_stream = content.ByteStream
        content_path = Path(content.__file__).resolve()
        assert content_path == Path(sys.prefix).resolve() / "Lib/site-packages/httpx2/_content.py"
        assert self.byte_stream is httpx2.ByteStream
        assert self.byte_stream.__init__.__module__ == "httpx2._content"
        assert Path(self.byte_stream.__init__.__code__.co_filename).resolve() == content_path
        content_sha256 = hashlib.sha256(content_path.read_bytes()).hexdigest()
        assert content_sha256 == "970731ffe23338f2c172fb9393703fff35af5fa4de9c269bdba932a4215eb211"
        self.body_source = {"file": content_path.as_posix(), "sha256": content_sha256,
                            "class": self.byte_stream.__qualname__, "module": self.byte_stream.__module__,
                            "implementation_module": self.byte_stream.__init__.__module__}
        self.codes = {
            "send": httpx2.AsyncClient._send_single_request.__code__,
            "basic": OAuthContext.prepare_token_auth.__code__,
            "owner": core.MCPServerTask._run_http.__code__,
            "close": httpx2.AsyncClient.__aexit__.__code__,
            "response_close": httpx2.Response.aclose.__code__,
            "initialize_sdk": OAuthClientProvider._initialize.__code__,
            "refresh_sdk": OAuthClientProvider._refresh_token.__code__,
            "validity": OAuthContext.is_token_valid.__code__,
            "can_refresh": OAuthContext.can_refresh_token.__code__,
            "expiry": OAuthContext.update_token_expiry.__code__,
        }
        root = Path(__file__).resolve().parents[2]
        self.oauth_sources = {}
        for relative, expected in {
            ".venv/Lib/site-packages/mcp/client/auth/oauth2.py": "912f43f60a023b66b05d102a5f2312affbccb6a626644f195aa6739d52c8717c",
            # U02's independently reviewed and committed owner bytes; keep
            # this source guard rather than reverting the retirement fix.
            "tools/mcp_oauth_manager.py": "e96e4c8cacf937964aca1dc6f6c802837439d7d75a4141d2ba2d28c64f3eaa8f",
            "tools/mcp_oauth.py": "3ad0d5af28de7ee2771fa139fe2dc861a6c6be808bbdf66de50bb046e663d678",
        }.items():
            path = (root / relative).resolve()
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == expected
            self.oauth_sources[path] = {"file": path.as_posix(), "sha256": actual}
        self.oauth_codes = {}
        self.oauth_admissions = []
        self.oauth_owners = {}
        self.admitted_providers = set()
        self.active_oauth = {}
        self.expiry_updates = {}
        self.rows = []
        self.clients = {}
        self.errors = []
        self.requests = {}
        self.product_clients = {}
        self.responses = {}
        self.active_sends = {}
        self.client_exits = set()
        self.response_exits = set()
        self.previous = threading.getprofile()

    def acquire_loop_thread(self):
        if self.loop_thread is None:
            candidate = self.core._mcp_thread
            if candidate is not None:
                assert isinstance(candidate, threading.Thread) and candidate.name == "mcp-event-loop"
                self.loop_thread = candidate
        return self.loop_thread

    def body_copy(self, request):
        stored = vars(request).get("_content")
        if type(stored) is bytes:
            return memoryview(stored).tobytes(), "existing_request_bytes"
        stream = request.stream
        if type(stream) is self.byte_stream and type(stream._stream) is bytes:
            return memoryview(stream._stream).tobytes(), "source_bound_ByteStream_bytes"
        raise TypeError("Unqualified passive request body: " + type(stream).__module__ + "." + type(stream).__qualname__)

    @staticmethod
    def terminal_return(frame, event):
        return (event == "return" and frame.f_lasti >= 0
                and dis.opname[frame.f_code.co_code[frame.f_lasti]] in {"RETURN_VALUE", "RETURN_CONST"})

    def record(self, **fields):
        row = {"sequence": len(self.rows), **fields}
        self.rows.append(row)
        return row

    def admit_provider(self, provider, client):
        """Bind the already-created manager provider before its auth decisions."""
        identity = id(provider)
        context = provider.context
        if identity not in self.admitted_providers:
            assert type(context).is_token_valid.__code__ is self.codes["validity"]
            assert type(context).can_refresh_token.__code__ is self.codes["can_refresh"]
            assert type(context).update_token_expiry.__code__ is self.codes["expiry"]
            methods = {
                "initialize_manager": type(provider)._initialize.__code__,
                "refresh_manager": type(provider)._refresh_token.__code__,
                "storage_load": type(context.storage).get_tokens.__code__,
                "initialize_sdk": self.codes["initialize_sdk"],
                "refresh_sdk": self.codes["refresh_sdk"],
            }
            for label, code in methods.items():
                source_path = Path(code.co_filename).resolve()
                assert source_path in self.oauth_sources
                self.codes[label] = code
                self.oauth_codes.setdefault(code, label)
                self.oauth_admissions.append({"producer": label, "provider_id": identity,
                                               "context_id": id(context), "qualname": code.co_qualname,
                                               "first_line": code.co_firstlineno,
                                               **self.oauth_sources[source_path]})
            self.admitted_providers.add(identity)
        self.oauth_owners[id(context)] = {"provider_id": identity, "context_id": id(context),
                                        "client_id": None if client is None else id(client),
                                        "storage_id": id(context.storage)}

    @staticmethod
    def oauth_scalars(context):
        tokens = context.current_tokens
        return {"context_id": id(context), "token_id": None if tokens is None else id(tokens),
                "expires_in": None if tokens is None else tokens.expires_in,
                "token_expiry_time": context.token_expiry_time,
                "client_info_id": None if context.client_info is None else id(context.client_info)}

    def observe_oauth(self, frame, event, returned):
        code = frame.f_code
        if code in (self.codes["validity"], self.codes["can_refresh"]):
            # No call-event work, clocks, hashes or I/O before the real decision.
            if self.terminal_return(frame, event):
                context = frame.f_locals["self"]
                owner = self.oauth_owners[id(context)]
                assert owner["client_id"] is not None
                assert type(returned) is bool
                self.record(operation="actual_oauth_decision", decision=code.co_name,
                            returned=returned, **owner,
                            scalars=self.oauth_scalars(context),
                            expiry_update=self.expiry_updates.get(id(context)))
            return True
        if code is self.codes["expiry"]:
            if self.terminal_return(frame, event):
                context = frame.f_locals["self"]
                token = frame.f_locals["token"]
                # Minimal scalar mapping only; serialize with the later decision.
                self.expiry_updates[id(context)] = (id(token), token.expires_in, context.token_expiry_time)
            return True
        label = self.oauth_codes.get(code)
        if label is None:
            return False
        subject = frame.f_locals["self"]
        if label == "storage_load":
            matches = [owner for owner in self.oauth_owners.values() if owner["storage_id"] == id(subject)]
            assert len(matches) == 1
            owner = matches[0]
            context = None
        else:
            context = subject.context
            owner = self.oauth_owners[id(context)]
            assert owner["provider_id"] == id(subject)
        frame_id = id(frame)
        if event == "call" and frame_id not in self.active_oauth:
            row = self.record(operation="actual_oauth_start", producer=label, frame_id=frame_id, **owner)
            self.active_oauth[frame_id] = {"start_sequence": row["sequence"], "subject_id": id(subject)}
        elif event == "return":
            active = self.active_oauth[frame_id]
            assert active["subject_id"] == id(subject)
            opcode = dis.opname[code.co_code[frame.f_lasti]]
            if opcode in {"YIELD_VALUE", "YIELD_FROM"}:
                self.record(operation="actual_oauth_suspend", producer=label, frame_id=frame_id,
                            start_sequence=active["start_sequence"], **owner)
                return True
            self.active_oauth.pop(frame_id)
            successful = self.terminal_return(frame, event)
            self.record(operation="actual_oauth_terminal", producer=label, frame_id=frame_id,
                        start_sequence=active["start_sequence"], successful=successful, opcode=opcode,
                        initialized=None if context is None else subject._initialized,
                        returned_id=None if returned is None else id(returned),
                        loaded_expires_in=(None if label != "storage_load" or returned is None else returned.expires_in),
                        scalars=None if context is None else self.oauth_scalars(context), **owner)
            if not successful:
                self.errors.append("Actual OAuth producer did not complete: " + label + ": " + opcode)
        return True

    def profile(self, frame, event, returned):
        if self.previous is not None:
            try:
                self.previous(frame, event, returned)
            except BaseException as exc:
                self.errors.append("Previous profile: " + type(exc).__name__ + ": " + str(exc))
                raise
        try:
            loop_thread = self.acquire_loop_thread()
            if loop_thread is None or threading.get_ident() != loop_thread.ident:
                return
            code = frame.f_code
            if self.observe_oauth(frame, event, returned):
                return
            if code is self.codes["send"] and event == "call":
                request = frame.f_locals["request"]
                client = frame.f_locals["self"]
                self.requests[id(request)] = request
                frame_id = id(frame)
                if frame_id not in self.active_sends:
                    row = self.record(operation="actual_send", client_id=id(client),
                                      request_id=id(request), method=request.method,
                                      url=str(request.url), headers=dict(request.headers),
                                      body_hex=None, body_observation="unqualified", code_file=code.co_filename)
                    self.active_sends[frame_id] = {"request_id": id(request), "client_id": id(client),
                                                   "send_sequence": row["sequence"]}
                    body, source = self.body_copy(request)
                    row.update(body_hex=body.hex(), body_observation=source)
                else:
                    active = self.active_sends[frame_id]
                    assert active["request_id"] == id(request) and active["client_id"] == id(client)
            elif code is self.codes["send"] and event == "return":
                opcode = dis.opname[code.co_code[frame.f_lasti]]
                if opcode in {"YIELD_VALUE", "YIELD_FROM"}:
                    return
                active = self.active_sends.pop(id(frame))
                if not self.terminal_return(frame, event):
                    raise RuntimeError("Actual send did not complete: " + opcode)
                import httpx2

                if not isinstance(returned, httpx2.Response):
                    raise TypeError("Actual send terminal did not return a Response")
                request = frame.f_locals["request"]
                client = frame.f_locals["self"]
                assert active["request_id"] == id(request) and active["client_id"] == id(client)
                self.responses[id(returned)] = returned
                self.record(operation="actual_response", client_id=id(client),
                            request_id=id(request), response_id=id(returned),
                            send_sequence=active["send_sequence"], method=request.method,
                            url=str(request.url), status=returned.status_code,
                            code_file=code.co_filename)
            elif code is self.codes["basic"] and self.terminal_return(frame, event) and returned is not None:
                data, headers = returned
                context = frame.f_locals["self"]
                self.record(operation="actual_prepare_token_auth", context_id=id(context),
                            auth_method=context.client_info.token_endpoint_auth_method,
                            data=dict(data), headers=dict(headers), code_file=code.co_filename)
            elif code is self.codes["owner"]:
                client = frame.f_locals.get("http_client")
                provider = frame.f_locals.get("_oauth_auth")
                if provider is not None:
                    self.admit_provider(provider, client)
                if client is not None:
                    self.product_clients[id(client)] = client
                    self.clients[id(client)] = {
                        "client_id": id(client), "is_closed": client.is_closed,
                        "owner_file": code.co_filename,
                        "provider_class": None if provider is None else type(provider).__qualname__,
                        "provider_module": None if provider is None else type(provider).__module__,
                        "context_id": None if provider is None else id(provider.context),
                    }
            elif code is self.codes["close"] and event == "return":
                client = frame.f_locals["self"]
                if id(client) in self.product_clients:
                    opcode = dis.opname[code.co_code[frame.f_lasti]]
                    if self.terminal_return(frame, event):
                        self.client_exits.add(id(client))
                        self.record(operation="actual_client_exit_terminal", client_id=id(client),
                                    opcode=opcode, code_file=code.co_filename)
                    elif opcode not in {"YIELD_VALUE", "YIELD_FROM"}:
                        self.errors.append("Actual client exit did not complete: " + opcode)
            elif code is self.codes["response_close"] and event == "return":
                response = frame.f_locals["self"]
                if id(response) in self.responses:
                    opcode = dis.opname[code.co_code[frame.f_lasti]]
                    if self.terminal_return(frame, event):
                        self.response_exits.add(id(response))
                        self.record(operation="actual_response_close_terminal", response_id=id(response),
                                    opcode=opcode, code_file=code.co_filename)
                    elif opcode not in {"YIELD_VALUE", "YIELD_FROM"}:
                        self.errors.append("Actual response close did not complete: " + opcode)
        except BaseException as exc:
            self.errors.append(type(exc).__name__ + ": " + str(exc))

    def snapshot(self):
        return {"calls": list(self.rows), "clients": list(self.clients.values()),
                "body_source": dict(self.body_source), "active_sends": dict(self.active_sends),
                "oauth_sources": list(self.oauth_sources.values()), "oauth_owners": list(self.oauth_owners.values()),
                "oauth_admissions": list(self.oauth_admissions),
                "active_oauth": dict(self.active_oauth),
                "oauth_timing_limit": "Passive profiling still costs time; observed decisions do not reconstruct earlier runs.",
                "mcp_thread": None if self.loop_thread is None else {
                    "name": self.loop_thread.name, "identity": id(self.loop_thread),
                    "ident": self.loop_thread.ident, "native_id": self.loop_thread.native_id,
                    "dead": not self.loop_thread.is_alive(),
                },
                "client_completion": [{"client_id": identity, "is_closed": client.is_closed,
                                       "successful_terminal_exit": identity in self.client_exits}
                                      for identity, client in self.product_clients.items()],
                "response_completion": [{"response_id": identity, "is_closed": response.is_closed,
                                         "successful_terminal_close": identity in self.response_exits,
                                         "request_id": id(response.request), "status": response.status_code}
                                        for identity, response in self.responses.items()],
                "retained_request_ids": list(self.requests),
                "observer_errors": list(self.errors)}

    def clear_references(self):
        self.requests.clear()
        self.product_clients.clear()
        self.responses.clear()
        self.active_sends.clear()
        self.active_oauth.clear()
        self.oauth_owners.clear()
        self.loop_thread = None
        self.core = None


@contextmanager
def owned_runtime(tmp_path, monkeypatch, record_property, peer, *, oauth=False):
    import httpx2
    import mcp.client.auth.oauth2 as sdk_auth
    import mcp.client.streamable_http as sdk_http
    import tools.mcp_tool as core
    from hermes_cli.mcp_config import _replace_mcp_servers
    from tools.mcp_dashboard_oauth import DashboardOAuthFlow, dashboard_oauth_flow
    from tools.mcp_oauth_manager import reset_manager_for_tests

    assert sys.platform == "win32"
    assert not core._servers and core._mcp_loop is None
    reset_manager_for_tests()
    home = tmp_path / "owned-redirect-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    name = "redirect_" + uuid.uuid4().hex[:10]
    flow = DashboardOAuthFlow(uuid.uuid4().hex, name, None, str(home), peer.bases["a"] + "/owned-callback")
    observer = NativeObserver(core)
    worker = None
    observer_failures = []
    loop = loop_thread = None
    initial_snapshot = [{"name": thread.name, "identity": id(thread), "native_id": thread.native_id}
                        for thread in threading.enumerate()]
    initial_threads = {thread["identity"] for thread in initial_snapshot}
    record_property("redirect_initial_threads", json.dumps(initial_snapshot))
    config = {"url": peer.url, "transport": "http", "headers": peer.headers(bearer=not oauth),
              "strict_redirect_headers": True, "connect_timeout": 8, "timeout": 8}
    if oauth:
        config.update(auth="oauth", oauth={"cimd": False, "timeout": 12})
    physical = {"platform": sys.platform,
                "mcp_version": importlib.metadata.version("mcp"),
                "httpx2_version": importlib.metadata.version("httpx2"),
                "oauth2_file": str(Path(sdk_auth.__file__).resolve()),
                "streamable_http_file": str(Path(sdk_http.__file__).resolve()),
                "httpx2_client_file": str(Path(observer.codes["send"].co_filename).resolve())}
    record_property("redirect_native_imports", json.dumps(physical))
    site_packages = Path(sys.prefix).resolve() / "Lib" / "site-packages"
    assert all(Path(physical[key]).is_relative_to(site_packages)
               for key in ("oauth2_file", "streamable_http_file", "httpx2_client_file"))
    assert core._ensure_mcp_sdk() and core._MCP_NEW_HTTP
    assert core.sdk_httpx() is httpx2 and sdk_http.httpx2 is httpx2
    assert sdk_auth.OAuthContext.prepare_token_auth.__code__ is observer.codes["basic"]
    record_property("redirect_observer_sources", json.dumps({
        key: {"file": code.co_filename, "first_line": code.co_firstlineno, "name": code.co_name}
        for key, code in observer.codes.items()
    }))
    record_property("redirect_modern_admission", "actual _MCP_NEW_HTTP and SDK-owned httpx2")
    first_body = None
    try:
        with scoped(home), dashboard_oauth_flow(flow):
            ok, issues = _replace_mcp_servers({name: config})
            assert ok and not issues, issues
            threading.setprofile(observer.profile)

            def start_terminal():
                nonlocal worker

                def deliver():
                    try:
                        if not flow._authorization_ready.wait(10):
                            raise TimeoutError("Owned authorization terminal deadline")
                        snapshot = flow.snapshot()
                        if not snapshot["authorization_url"]:
                            raise RuntimeError(snapshot["error"] or "Missing authorization URL")
                        code, state = peer.issue_code(snapshot["authorization_url"])
                        flow.deliver_callback(code=code, state=state, iss=peer.issuer, error=None)
                    except BaseException as exc:
                        observer_failures.append(type(exc).__name__ + ": " + str(exc))
                        flow.mark_error("Owned terminal failed: " + str(exc))

                worker = threading.Thread(target=deliver, name="owned-redirect-user-terminal", daemon=False)
                worker.start()

            try:
                yield core, name, home, flow, observer, config, start_terminal
            except BaseException as exc:
                first_body = exc
                raise
    finally:
        active_exception = sys.exception()
        first = first_body if first_body is not None else active_exception
        cleanup_errors = []
        if first_body is not None and active_exception is not None and active_exception is not first_body:
            cleanup_errors.append("Context exit also raised: " + repr(active_exception))

        def attempt(label, action):
            try:
                return action()
            except BaseException as exc:
                cleanup_errors.append(label + ": " + type(exc).__name__ + ": " + str(exc))
                return None

        def emit(label, name, value):
            serialized = attempt(label + "_serialization", lambda: json.dumps(value))
            attempt(label + "_property", lambda: record_property(
                name, serialized if serialized is not None else '{"serialization_failed":true}'))

        def joined(thread):
            if thread.ident is not None:
                thread.join(timeout=4)
            assert not thread.is_alive(), thread.name

        current_threads = attempt("initial_cleanup_thread_snapshot", threading.enumerate) or []
        owned_threads = [thread for thread in current_threads if id(thread) not in initial_threads]
        if worker is not None and worker not in owned_threads:
            owned_threads.append(worker)
        try:
            attempt("flow_release", lambda: flow.mark_error("Owned redirect fixture cleanup"))
            if worker is not None:
                attempt("user_terminal_exit", lambda: joined(worker))
            captured = attempt("MCP_owner_capture", lambda: (core._mcp_loop, observer.acquire_loop_thread()))
            if captured is not None:
                loop, loop_thread = captured
            if loop_thread is not None and loop_thread not in owned_threads:
                owned_threads.append(loop_thread)
            attempt("MCP_shutdown", core.shutdown_mcp_servers)
            # Dashboard wait_for_callback uses real asyncio.to_thread. Its
            # executor belongs to this fresh loop and must also finish.
            for thread in attempt("final_cleanup_thread_snapshot", threading.enumerate) or []:
                if id(thread) not in initial_threads and thread not in owned_threads:
                    owned_threads.append(thread)
            for thread in owned_threads:
                attempt("owned_thread_exit_" + thread.name, lambda thread=thread: joined(thread))
        finally:
            attempt("profile_restore", lambda: threading.setprofile(observer.previous))
        restored = attempt("profile_restore_verification", lambda: threading.getprofile() is observer.previous)
        attempt("manager_reset", reset_manager_for_tests)
        loop_closed = attempt("loop_closure_read", lambda: loop is not None and loop.is_closed() and not loop.is_running())
        if loop is not None and loop_closed is not True:
            cleanup_errors.append("MCP loop closure not confirmed")
        completion = attempt("actual_client_response_completion_read", observer.snapshot)
        if completion is None:
            cleanup_errors.append("Actual client/response completion unknown")
        else:
            clients = completion["client_completion"]
            responses = completion["response_completion"]
            if completion["active_sends"]:
                cleanup_errors.append("Actual send terminal completion not confirmed")
            if not clients or not all(row["is_closed"] and row["successful_terminal_exit"] for row in clients):
                cleanup_errors.append("Actual product HTTPX2 client successful exit not confirmed")
            if not responses or not all(row["is_closed"] and row["successful_terminal_close"] for row in responses):
                cleanup_errors.append("Actual product HTTPX2 response successful close not confirmed")
        emit("observer_receipt", "redirect_native_observer", completion)
        thread_rows = []
        for thread in owned_threads:
            row = attempt("owned_thread_state_read", lambda thread=thread: {
                "name": thread.name, "identity": id(thread), "native_id": thread.native_id,
                "dead": not thread.is_alive(),
            })
            if row is not None:
                thread_rows.append(row)
        resource = {"loop_existed": loop is not None,
                    "loop_closed": loop_closed,
                    "loop_thread_dead": attempt("loop_thread_state_read", lambda: loop_thread is not None and not loop_thread.is_alive()),
                    "terminal_thread_dead": attempt("terminal_state_read", lambda: worker is None or not worker.is_alive()),
                    "owned_threads": thread_rows,
                    "observed_mcp_thread_identity": None if observer.loop_thread is None else id(observer.loop_thread),
                    "profile_restored": restored, "cleanup_errors": cleanup_errors,
                    "previous_profile_identity": None if observer.previous is None else id(observer.previous),
                    "terminal_errors": observer_failures}
        if restored is not True:
            cleanup_errors.append("Previous threading profile restoration not confirmed")
        emit("runtime_cleanup_receipt", "redirect_runtime_cleanup", resource)
        # Actual Request/Response/client references prevent identity reuse and
        # remain read-only until restoration and every receipt attempt finish.
        attempt("observer_reference_release", observer.clear_references)
        errors = cleanup_errors + observer_failures + observer.errors
        if errors:
            if first is not None:
                first.add_note("Owned runtime cleanup: " + repr(errors))
            else:
                raise AssertionError(errors)
        if first_body is not None:
            raise first_body


def record_wire(record_property, peer, observer):
    # Baseline failures must retain wire values BEFORE the immutable oracle.
    record_property("redirect_wire_before_assertions", json.dumps(peer.snapshot()))
    record_property("redirect_calls_before_assertions", json.dumps(observer.snapshot()))


def discover(runtime, record_property, peer, wire_oracle=None):
    core, name, _home, _flow, observer, _config, _terminal = runtime
    error = None
    try:
        tools = core.discover_mcp_tools()
    except Exception as exc:
        error = exc
        tools = []
    record_wire(record_property, peer, observer)
    record_property("redirect_discovery", json.dumps({
        "tools": tools,
        "raised": None if error is None else type(error).__name__ + ": " + str(error),
        "errors": [{"server": repr(key), "error": str(value)}
                   for key, value in core._server_connect_errors.items()],
    }))
    if wire_oracle is not None:
        try:
            wire_oracle()
        except AssertionError as oracle_error:
            if error is not None:
                oracle_error.add_note("Public discovery also raised: " + repr(error))
                raise oracle_error from error
            raise
    if error is not None:
        raise error
    return "mcp__" + name + "__write_sentinel", tools


def dispatch(tool, nonce):
    from tools.registry import registry

    return json.loads(registry.dispatch(tool, {"nonce": nonce}))


def assert_generated(rows):
    rows = [row for row in rows if row["method"] == "POST" and row.get("rpc_method")]
    assert rows, "No actual MCP wire request"
    assert all("application/json" in row["headers"].get("accept", "") for row in rows)
    for row in rows:
        if row.get("rpc_method") == "initialize":
            assert row["headers"].get("mcp-protocol-version") == row["body"]["params"]["protocolVersion"]
        else:
            assert row["headers"].get("mcp-protocol-version")


def assert_absent(rows):
    assert rows, "Foreign boundary was not exercised"
    for row in rows:
        assert "authorization" not in row["headers"], row
        assert "x-api-key" not in row["headers"], row
        assert "x-tenant" not in row["headers"], row


def assert_same_origin(peer):
    protected = peer.wire(role="a", path="/protected", rpc_method="initialize")
    assert protected, "No actual same-origin request; setup failure cannot qualify this oracle"
    assert all(all(row["headers"].get(key.lower()) == value for key, value in peer.headers().items())
               for row in protected), protected


def assert_compatibility(peer):
    foreign = peer.wire(role="b")
    assert foreign, "No actual foreign request; setup failure cannot qualify this oracle"
    assert all("authorization" not in row["headers"] for row in foreign), foreign
    assert all(row["headers"].get("x-api-key") == peer.api_key
               and row["headers"].get("x-tenant") == peer.tenant for row in foreign), foreign
    assert_generated(foreign)


def assert_basic(peer, observer, grant):
    token_rows = [row for row in peer.wire(operation="token") if row["grant_type"] == grant]
    assert token_rows, "No real bound token request; setup failure cannot qualify this oracle"
    assert all(row["headers"].get("authorization") == peer.basic for row in token_rows), token_rows
    assert all("client_secret" not in row["body"] and row["status"] == 200 for row in token_rows)
    prepared = [row for row in observer.rows if row["operation"] == "actual_prepare_token_auth"
                and row["data"].get("grant_type") == grant]
    assert prepared and all(row["headers"].get("Authorization") == peer.basic for row in prepared)
    sent = [row for row in observer.rows if row["operation"] == "actual_send"]
    bound = [row for row in sent if row["url"] == peer.bases["issuer"] + "/token"]
    mcp = [row for row in sent if row["url"] == peer.url]
    assert bound and mcp
    assert {row["client_id"] for row in bound} == {row["client_id"] for row in mcp}
    clients = list(observer.clients.values())
    assert clients and all(client["provider_class"].endswith("HermesMCPOAuthProvider") for client in clients)
    assert {row["context_id"] for row in prepared} == {client["context_id"] for client in clients}


def test_same_origin_credentials_and_exact_protected_nonce(tmp_path, monkeypatch, record_property):
    with redirect_peers(record_property) as peer:
        with owned_runtime(tmp_path, monkeypatch, record_property, peer) as runtime:
            tool, tools = discover(runtime, record_property, peer, lambda: assert_same_origin(peer))
            assert tool in tools
            nonce = uuid.uuid4().hex
            result = dispatch(tool, nonce)
            record_wire(record_property, peer, runtime[4])
            assert "error" not in result, result
            assert result.get("result") == "owned:" + nonce, result
            assert peer.effects == [{"role": "a", "nonce": nonce,
                                     "sequence": peer.wire(role="a", rpc_method="tools/call")[-1]["sequence"]}]
            assert_generated(peer.wire(role="a", path="/protected"))


@pytest.mark.parametrize("route", ["foreign", "multi"])
def test_strict_foreign_wire_absence_and_no_effect(tmp_path, monkeypatch, record_property, route):
    with redirect_peers(record_property, route) as peer:
        with owned_runtime(tmp_path, monkeypatch, record_property, peer) as runtime:
            tool, tools = discover(runtime, record_property, peer,
                                   lambda: assert_absent(peer.wire(role="b")))
            assert tool in tools
            nonce = uuid.uuid4().hex
            result = dispatch(tool, nonce)
            record_wire(record_property, peer, runtime[4])
            foreign = peer.wire(role="b")
            assert_absent(foreign)
            assert "error" not in result and not peer.effects, result
            assert result.get("result") == "echo:" + nonce, result
            assert peer.wire(role="b", rpc_method="tools/call")[-1]["protected_effect"] is False
            assert_generated(foreign)
            if route == "multi":
                local = peer.wire(role="a", path="/local")
                assert local and all(all(row["headers"].get(key.lower()) == value
                                         for key, value in peer.headers().items()) for row in local)
                assert peer.wire(role="b", path="/hop") and peer.wire(role="b", path="/mcp")


def test_nonstrict_custom_header_compatibility(tmp_path, monkeypatch, record_property):
    from hermes_cli.mcp_config import _replace_mcp_servers

    with redirect_peers(record_property, "foreign") as peer:
        with owned_runtime(tmp_path, monkeypatch, record_property, peer) as runtime:
            config = dict(runtime[5], strict_redirect_headers=False)
            ok, issues = _replace_mcp_servers({runtime[1]: config})
            assert ok and not issues
            tool, tools = discover(runtime, record_property, peer, lambda: assert_compatibility(peer))
            assert tool in tools
            nonce = uuid.uuid4().hex
            result = dispatch(tool, nonce)
            record_wire(record_property, peer, runtime[4])
            foreign = peer.wire(role="b")
            assert foreign and all("authorization" not in row["headers"] for row in foreign)
            assert all(row["headers"].get("x-api-key") == peer.api_key
                       and row["headers"].get("x-tenant") == peer.tenant for row in foreign)
            assert "error" not in result and not peer.effects
            assert result.get("result") == "echo:" + nonce, result
            assert_generated(foreign)


def test_preemptive_bound_basic_refresh_same_product_client(tmp_path, monkeypatch, record_property):
    from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken
    from tools.mcp_oauth import HermesTokenStorage

    with redirect_peers(record_property) as peer:
        with owned_runtime(tmp_path, monkeypatch, record_property, peer, oauth=True) as runtime:
            storage = HermesTokenStorage(runtime[1], hermes_home=runtime[2])
            storage.bind_issuer(peer.issuer)
            info = peer.registration(runtime[3].redirect_uri)
            peer.registrations[peer.client_id] = info
            asyncio.run(storage.set_client_info(OAuthClientInformationFull.model_validate(info)))
            storage.save_oauth_metadata(OAuthMetadata.model_validate(peer.metadata()))
            asyncio.run(storage.set_tokens(OAuthToken(access_token=peer.expired_token, expires_in=0,
                                                     refresh_token=peer.refresh_token)))
            record_property("redirect_seeded_issuance", "Owned expired token/client/issuer persisted through HermesTokenStorage; no DCR/PKCE credit")
            tool, tools = discover(runtime, record_property, peer,
                                   lambda: assert_basic(peer, runtime[4], "refresh_token"))
            assert not peer.wire(operation="registration") and not peer.wire(operation="authorization_terminal")
            assert tool in tools
            nonce = uuid.uuid4().hex
            result = dispatch(tool, nonce)
            record_wire(record_property, peer, runtime[4])
            assert "error" not in result
            assert result.get("result") == "owned:" + nonce, result
            assert len(peer.effects) == 1 and peer.effects[0]["nonce"] == nonce
            assert not runtime[3].authorization_url


def test_actual_401_original_request_retry_then_live_foreign_call(tmp_path, monkeypatch, record_property):
    with redirect_peers(record_property) as peer:
        with owned_runtime(tmp_path, monkeypatch, record_property, peer, oauth=True) as runtime:
            runtime[6]()
            tool, tools = discover(runtime, record_property, peer,
                                   lambda: assert_basic(peer, runtime[4], "authorization_code"))
            token = peer.wire(operation="token")[-1]
            assert token["pkce_verified"] and peer.wire(operation="registration")
            assert peer.wire(operation="authorization_terminal")
            protected = peer.wire(role="a", path="/protected", rpc_method="initialize")
            assert len(protected) >= 2 and protected[0]["status"] == 401 and protected[-1]["status"] == 200
            sends = [row for row in runtime[4].rows if row["operation"] == "actual_send" and row["url"] == peer.url]
            observations = runtime[4].rows
            actual_401 = [row for row in observations if row["operation"] == "actual_response"
                          and row["url"] == peer.bases["a"] + "/protected" and row["status"] == 401]
            actual_token = [row for row in observations if row["operation"] == "actual_response"
                            and row["url"] == peer.bases["issuer"] + "/token" and row["status"] == 200]
            retried = [(first, denied, token_response, second)
                       for first in sends for denied in actual_401 for token_response in actual_token for second in sends
                       if first["sequence"] < denied["send_sequence"] < denied["sequence"]
                       < token_response["send_sequence"] < token_response["sequence"] < second["sequence"]
                       and first["method"] == second["method"] == "POST"
                       and denied["method"] == token_response["method"] == "POST"
                       and first["url"] == second["url"] == peer.url
                       and first["body_hex"] == second["body_hex"]
                       and observations[denied["send_sequence"]]["body_hex"] == first["body_hex"]
                       and denied["request_id"] != first["request_id"]
                       and observations[token_response["send_sequence"]]["headers"].get("authorization") == peer.basic
                       and json.loads(bytes.fromhex(first["body_hex"]))["method"] == "initialize"
                       and runtime[4].requests[first["request_id"]] is runtime[4].requests[second["request_id"]]
                       and denied["client_id"] == token_response["client_id"] == first["client_id"] == second["client_id"]
                       and "authorization" not in first["headers"]
                       and second["headers"].get("authorization") == "Bearer " + peer.access_token]
            assert retried, "Actual SDK original request was not observed reused after token exchange"
            record_property("redirect_original_request_retry", json.dumps({
                "anonymous_send": retried[0][0], "actual_401": retried[0][1],
                "actual_token_response": retried[0][2], "bearer_retry": retried[0][3],
                "retained_request_same_object": True,
            }))
            copies = [row for row in runtime[4].rows if row["operation"] == "actual_send"
                      and row["url"] == peer.bases["a"] + "/protected"]
            assert copies and all(copy["request_id"] != retried[0][0]["request_id"] for copy in copies)
            assert protected[0]["sequence"] < token["sequence"] < protected[-1]["sequence"]
            assert tool in tools
            first_nonce = uuid.uuid4().hex
            first_result = dispatch(tool, first_nonce)
            record_wire(record_property, peer, runtime[4])
            assert "error" not in first_result and len(peer.effects) == 1
            assert first_result.get("result") == "owned:" + first_nonce, first_result
            assert peer.effects[0]["nonce"] == first_nonce
            identity = {(row["client_id"]) for row in sends}
            with peer.lock:
                peer.route = "foreign"
            second_nonce = uuid.uuid4().hex
            second_result = dispatch(tool, second_nonce)
            record_wire(record_property, peer, runtime[4])
            foreign = peer.wire(role="b", rpc_method="tools/call")
            assert_absent(foreign)
            assert "error" not in second_result and len(peer.effects) == 1
            assert second_result.get("result") == "echo:" + second_nonce, second_result
            assert foreign[-1]["body"]["params"]["arguments"]["nonce"] == second_nonce
            assert foreign[-1]["protected_effect"] is False
            assert_generated(foreign)
            foreign_sends = [row for row in runtime[4].rows if row["operation"] == "actual_send"
                             and row["url"].startswith(peer.bases["b"] + "/")]
            assert {row["client_id"] for row in foreign_sends} == identity
