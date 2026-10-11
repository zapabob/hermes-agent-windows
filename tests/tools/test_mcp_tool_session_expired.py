"""Tests for MCP tool-handler transport-session auto-reconnect.

When a Streamable HTTP MCP server garbage-collects its server-side
session (idle TTL, server restart, pod rotation, …) it rejects
subsequent requests with a JSON-RPC error containing phrases like
``"Invalid or expired session"``.  The OAuth token remains valid —
only the transport session state needs rebuilding.

Before the #13383 fix, this class of failure fell through as a plain
tool error with no recovery path, so every subsequent call on the
affected MCP server failed until the gateway was manually restarted.
"""
import asyncio
import json
import threading
import time
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# _is_session_expired_error — unit coverage
# ---------------------------------------------------------------------------


def test_is_session_expired_detects_invalid_or_expired_session():
    """Reporter's exact wpcom-mcp error message (#13383)."""
    from tools.mcp_tool import _is_session_expired_error
    exc = RuntimeError("Invalid params: Invalid or expired session")
    assert _is_session_expired_error(exc) is True


def test_is_session_expired_detects_expired_session_variant():
    """Generic ``session expired`` / ``expired session`` phrasings used
    by other SDK servers."""
    from tools.mcp_tool import _is_session_expired_error
    assert _is_session_expired_error(RuntimeError("Session expired")) is True
    assert _is_session_expired_error(RuntimeError("expired session: abc")) is True


def test_is_session_expired_detects_session_not_found():
    """Server-side GC produces ``session not found`` / ``unknown session``
    on some implementations."""
    from tools.mcp_tool import _is_session_expired_error
    assert _is_session_expired_error(RuntimeError("session not found")) is True
    assert _is_session_expired_error(RuntimeError("Unknown session: abc123")) is True


def test_is_session_expired_traversal_is_budget_bounded():
    """Pathologically long chains stop at the node budget without spinning."""
    import tools.mcp_tool as mcp_mod
    from tools.mcp_tool import _is_session_expired_error

    exc: BaseException = RuntimeError("leaf")
    for i in range(mcp_mod._EXC_TRAVERSAL_MAX_NODES * 2):
        wrapper = RuntimeError(f"layer {i}")
        wrapper.__cause__ = exc
        exc = wrapper

    # Terminates quickly and classifies false (no transport signal within
    # budget). The exact outcome past the budget is unspecified; the
    # invariant under test is termination.
    assert _is_session_expired_error(exc) is False


# ---------------------------------------------------------------------------
# Handler integration — verify the recovery plumbing wires end-to-end
# ---------------------------------------------------------------------------


def _install_stub_server(name: str = "wpcom"):
    """Register a minimal server stub that _handle_session_expired_and_retry
    can signal via _reconnect_event, and that reports ready+session after
    the event fires."""
    from tools import mcp_tool

    mcp_tool._ensure_mcp_loop()

    server = MagicMock()
    server.name = name

    ready_flag = threading.Event()
    ready_flag.set()

    class _ReadyAdapter:
        def is_set(self):
            return ready_flag.is_set()

        def clear(self):
            ready_flag.clear()

        def set(self):
            ready_flag.set()

    server._ready = _ReadyAdapter()

    # _reconnect_event is called via loop.call_soon_threadsafe(…set); use
    # a threading-safe substitute.  The production reconnect path must not
    # treat the old stale session as fresh, so this test double swaps in a
    # distinct session object when reconnect is requested.
    reconnect_flag = threading.Event()

    class _EventAdapter:
        def set(self):
            reconnect_flag.set()
            old_session = server.session
            new_session = MagicMock()
            for method_name in (
                "call_tool",
                "list_resources",
                "read_resource",
                "list_prompts",
                "get_prompt",
            ):
                if hasattr(old_session, method_name):
                    setattr(new_session, method_name, getattr(old_session, method_name))
            server.session = new_session
            ready_flag.set()

    server._reconnect_event = _EventAdapter()

    # session attr must be truthy for the handler's initial check
    # (``if not server or not server.session``) and for the post-
    # reconnect readiness probe (``srv.session is not None``).
    server.session = MagicMock()
    return server, reconnect_flag


@pytest.mark.parametrize(
    "transport_config, expected_route",
    [
        ({"command": "librarian-mcp"}, "stdio"),
        ({"url": "https://neo4j.example.test/mcp", "skip_preflight": True}, "http"),
    ],
    ids=["stdio", "http"],
)
def test_call_tool_handler_rebuilds_configured_server_transport(
    monkeypatch, tmp_path, transport_config, expected_route
):
    """The real server run loop selects and rebuilds its configured transport."""
    from anyio import ClosedResourceError
    from tools import mcp_tool
    from tools.mcp_tool import MCPServerTask, _make_tool_handler

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mcp_tool._ensure_mcp_loop()
    transport_ready = threading.Event()
    routes = []
    configs = []
    sessions = []
    call_count = {"n": 0}

    class _Session:
        async def call_tool(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ClosedResourceError
            result = MagicMock()
            result.is_error = False
            result.content = [MagicMock(type="text", text="reconnected")]
            result.structured_content = None
            return result

    class _LifecycleTask(MCPServerTask):
        async def _serve_transport(self, route, config):
            routes.append(route)
            configs.append(dict(config))
            self.session = _Session()
            sessions.append(self.session)
            self._ready.set()
            transport_ready.set()
            return await self._wait_for_lifecycle_event()

        async def _run_stdio(self, config):
            return await self._serve_transport("stdio", config)

        async def _run_http(self, config):
            return await self._serve_transport("http", config)

    server = _LifecycleTask("resumed")
    mcp_tool._servers["resumed"] = server
    mcp_tool._server_error_counts.pop("resumed", None)
    mcp_tool._server_breaker_opened_at.pop("resumed", None)
    loop = mcp_tool._mcp_loop
    assert loop is not None
    run_future = asyncio.run_coroutine_threadsafe(
        server.run(transport_config), loop
    )

    try:
        assert transport_ready.wait(3), "server lifecycle did not establish transport"
        handler = _make_tool_handler("resumed", "health", 10.0)
        parsed = json.loads(handler({}))

        assert parsed == {"result": "reconnected"}
        assert call_count["n"] == 2
        assert routes == [expected_route, expected_route]
        assert configs == [transport_config, transport_config]
        assert len(sessions) == 2
        assert sessions[0] is not sessions[1]
    finally:
        loop.call_soon_threadsafe(server._shutdown_event.set)
        run_future.result(timeout=5)
        mcp_tool._servers.pop("resumed", None)
        mcp_tool._server_error_counts.pop("resumed", None)
        mcp_tool._server_breaker_opened_at.pop("resumed", None)


def test_session_expired_retry_waits_for_new_session(monkeypatch, tmp_path):
    """Regression for long-lived HTTP/stream MCP sessions.

    If the reconnect helper only checks ``_ready.is_set()`` and
    ``session is not None``, it can return immediately while ``session`` still
    points at the stale transport. The retry then hits the same dead session
    and the circuit breaker eventually reports the server as unreachable. The
    handler must wait for a distinct session object before retrying.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools import mcp_tool
    from tools.mcp_tool import _make_tool_handler

    mcp_tool._ensure_mcp_loop()
    server = MagicMock()
    server.name = "hindsight"
    ready_flag = threading.Event()
    ready_flag.set()

    class _ReadyAdapter:
        def is_set(self):
            return ready_flag.is_set()

        def clear(self):
            ready_flag.clear()

        def set(self):
            ready_flag.set()

    old_session = MagicMock()

    async def _old_call(*a, **kw):
        raise RuntimeError("Session terminated")

    old_session.call_tool = _old_call
    new_session = MagicMock()

    async def _new_call(*a, **kw):
        result = MagicMock()
        result.is_error = False
        result.content = [MagicMock(type="text", text="bank ok")]
        result.structured_content = None
        return result

    new_session.call_tool = _new_call
    server.session = old_session
    server._ready = _ReadyAdapter()

    class _ReconnectAdapter:
        def set(self):
            server.session = new_session
            ready_flag.set()

    server._reconnect_event = _ReconnectAdapter()
    mcp_tool._servers["hindsight"] = server
    mcp_tool._server_error_counts["hindsight"] = 7
    # Stamp the breaker "open" far enough in the past that the cooldown has
    # provably elapsed, so this call is a half-open probe. The breaker compares
    # against time.monotonic() (tools/mcp_tool.py), whose origin is arbitrary and
    # small on a freshly-booted CI container — a hardcoded literal like 123.0
    # only looked "elapsed" on a long-uptime dev box and flaked under CI.
    mcp_tool._server_breaker_opened_at["hindsight"] = (
        time.monotonic() - mcp_tool._CIRCUIT_BREAKER_COOLDOWN_SEC - 1.0
    )

    try:
        handler = _make_tool_handler("hindsight", "get_bank", 10.0)
        parsed = json.loads(handler({}))
        assert parsed.get("result") == "bank ok", parsed
        assert mcp_tool._server_error_counts.get("hindsight", 0) == 0
        assert "hindsight" not in mcp_tool._server_breaker_opened_at
    finally:
        mcp_tool._servers.pop("hindsight", None)
        mcp_tool._server_error_counts.pop("hindsight", None)
        mcp_tool._server_breaker_opened_at.pop("hindsight", None)


def test_session_expired_handler_returns_none_without_loop(monkeypatch):
    """Defensive: if the MCP loop isn't running (cold start / shutdown
    race), the handler must fall through cleanly instead of hanging
    or raising."""
    from tools import mcp_tool
    from tools.mcp_tool import _handle_session_expired_and_retry

    # Install a server stub but make the event loop unavailable.
    server = MagicMock()
    server._reconnect_event = MagicMock()
    server._ready = MagicMock()
    server._ready.is_set = MagicMock(return_value=True)
    server.session = MagicMock()
    mcp_tool._servers["srv-noloop"] = server

    monkeypatch.setattr(mcp_tool, "_mcp_loop", None)

    try:
        out = _handle_session_expired_and_retry(
            "srv-noloop",
            RuntimeError("Invalid or expired session"),
            lambda: '{"ok": true}',
            "tools/call",
        )
        assert out is None, (
            "Without an event loop, session-expired handler must fall "
            "through to caller's generic error path — not hang or raise."
        )
    finally:
        mcp_tool._servers.pop("srv-noloop", None)


def test_session_expired_handler_returns_none_without_server_record():
    """If the server has been torn down / isn't in _servers, fall
    through cleanly — nothing to reconnect to."""
    from tools.mcp_tool import _handle_session_expired_and_retry
    out = _handle_session_expired_and_retry(
        "does-not-exist",
        RuntimeError("Invalid or expired session"),
        lambda: '{"ok": true}',
        "tools/call",
    )
    assert out is None


# ---------------------------------------------------------------------------
# Parallel coverage for resources/list, resources/read, prompts/list,
# prompts/get — all four handlers share the same exception path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "handler_factory, handler_kwargs, session_method, op_label",
    [
        ("_make_list_resources_handler", {"tool_timeout": 10.0}, "list_resources", "list_resources"),
        ("_make_read_resource_handler", {"tool_timeout": 10.0}, "read_resource", "read_resource"),
        ("_make_list_prompts_handler", {"tool_timeout": 10.0}, "list_prompts", "list_prompts"),
        ("_make_get_prompt_handler", {"tool_timeout": 10.0}, "get_prompt", "get_prompt"),
    ],
)
def test_non_tool_handlers_also_reconnect_on_session_expired(
    monkeypatch, tmp_path, handler_factory, handler_kwargs, session_method, op_label
):
    """All four non-``tools/call`` MCP handlers share the recovery
    pattern and must reconnect the same way on session-expired."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools import mcp_tool

    server, reconnect_flag = _install_stub_server(f"srv-{op_label}")
    mcp_tool._servers[f"srv-{op_label}"] = server
    mcp_tool._server_error_counts.pop(f"srv-{op_label}", None)

    call_count = {"n": 0}

    async def _sequence(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("Invalid or expired session")
        # Return something with the shapes each handler expects.
        # Explicitly set primitive attrs — MagicMock's default auto-attr
        # behaviour surfaces ``MagicMock`` values for optional fields
        # like ``description``, which break ``json.dumps`` downstream.
        result = MagicMock()
        result.resources = []
        result.prompts = []
        result.contents = []
        result.messages = []  # get_prompt
        result.description = None  # get_prompt optional field
        return result

    setattr(server.session, session_method, _sequence)

    factory = getattr(mcp_tool, handler_factory)
    # list_resources / list_prompts take (server_name, timeout).
    # read_resource / get_prompt take the same signature.
    try:
        handler = factory(f"srv-{op_label}", **handler_kwargs)
        if op_label == "read_resource":
            out = handler({"uri": "file://foo"})
        elif op_label == "get_prompt":
            out = handler({"name": "p1"})
        else:
            out = handler({})
        parsed = json.loads(out)
        assert "error" not in parsed, (
            f"{op_label}: expected retry success, got {parsed}"
        )
        assert reconnect_flag.is_set(), (
            f"{op_label}: reconnect should fire for session-expired"
        )
        assert call_count["n"] == 2, (
            f"{op_label}: expected 1 original + 1 retry"
        )
    finally:
        mcp_tool._servers.pop(f"srv-{op_label}", None)
        mcp_tool._server_error_counts.pop(f"srv-{op_label}", None)


@pytest.fixture
def failed_auth_reconnect(monkeypatch, tmp_path):
    """Exercise real auth policy/recovery with only the transport wait stubbed."""
    from types import SimpleNamespace
    from tools import mcp_tool, mcp_oauth_manager
    from tools.mcp_oauth import OAuthNonInteractiveError

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "mcp_servers:\n  retained-auth:\n    command: owned-unused\n    enabled: true\n",
        encoding="utf-8",
    )
    server = SimpleNamespace(
        session=None, _task=object(), _reconnect_event=object(),
        _error=ExceptionGroup("transport", [OAuthNonInteractiveError("owned expired token")]),
    )
    key = mcp_tool._resolve_server_key("retained-auth")
    monkeypatch.setitem(mcp_tool._servers, key, server)
    monkeypatch.setattr(mcp_tool, "_mcp_loop", SimpleNamespace(is_running=lambda: True))
    monkeypatch.setattr(mcp_tool, "_signal_reconnect_and_wait", lambda *args, **kw: False)
    monkeypatch.setattr(mcp_tool, "_run_on_mcp_loop", lambda factory, **kw: asyncio.run(factory()))
    calls = {"manager": 0, "retry": 0}

    async def handle_401(name, response):
        assert name == "retained-auth"
        assert response is None
        calls["manager"] += 1
        return False

    monkeypatch.setattr(mcp_oauth_manager, "get_manager", lambda: SimpleNamespace(handle_401=handle_401))
    monkeypatch.setattr(mcp_tool, "_server_error_counts", {})
    monkeypatch.setattr(mcp_tool, "_server_breaker_opened_at", {})

    def retry():
        calls["retry"] += 1
        return json.dumps({"result": "protected effect"})

    policy = mcp_tool._MCPInvocationPolicy("retained-auth")

    def invoke():
        return mcp_tool._handle_session_expired_and_retry(
            "retained-auth", RuntimeError("Connection closed"), retry,
            "tools/call", admission_check=policy.check,
        )

    return SimpleNamespace(
        core=mcp_tool, server=server, key=key, calls=calls,
        config_path=config_path, invoke=invoke,
    )


def test_retained_auth_failure_surfaces_reauth_after_failed_reconnect(failed_auth_reconnect):
    state = failed_auth_reconnect
    result = json.loads(state.invoke())
    assert result["needs_reauth"] is True
    assert result["server"] == "retained-auth"
    assert state.calls == {"manager": 1, "retry": 0}


@pytest.mark.parametrize("failure", [RuntimeError("401 token expired"), TimeoutError(), None])
def test_non_auth_reconnect_failure_never_recovers_oauth(failed_auth_reconnect, failure):
    state = failed_auth_reconnect
    state.server._error = failure
    assert state.invoke() is None
    assert state.calls == {"manager": 0, "retry": 0}


def test_http_403_reconnect_failure_never_recovers_oauth(failed_auth_reconnect):
    state = failed_auth_reconnect
    transport = state.core.sdk_httpx()
    request = transport.Request("POST", "http://127.0.0.1/owned-unused")
    response = transport.Response(403, request=request)
    state.server._error = transport.HTTPStatusError("owned forbidden", request=request, response=response)
    assert state.invoke() is None
    assert state.calls == {"manager": 0, "retry": 0}


@pytest.mark.parametrize("boundary", ["manager_admission", "recovery_end"])
def test_recovery_rechecks_owner_at_manager_and_retry_boundaries(
    monkeypatch, failed_auth_reconnect, boundary
):
    from types import SimpleNamespace
    from tools import mcp_oauth_manager
    state = failed_auth_reconnect

    async def handle_401(name, response):
        state.calls["manager"] += 1
        state.server._task = object()
        return True

    def manager():
        if boundary == "manager_admission":
            state.server._task = object()
        return SimpleNamespace(handle_401=handle_401)

    monkeypatch.setattr(mcp_oauth_manager, "get_manager", manager)
    result = json.loads(state.invoke())
    assert result["mcp_policy"] == "connection_replaced"
    assert state.calls == {"manager": int(boundary == "recovery_end"), "retry": 0}


@pytest.mark.parametrize("replacement", ["server", "task"])
def test_replaced_connection_denies_reauth_before_side_effects(
    monkeypatch, failed_auth_reconnect, replacement
):
    state = failed_auth_reconnect

    def reconnect(*args, **kwargs):
        if replacement == "server":
            state.core._servers[state.key] = object()
        else:
            state.server._task = object()
        return False

    monkeypatch.setattr(state.core, "_signal_reconnect_and_wait", reconnect)
    result = json.loads(state.invoke())
    assert result["mcp_policy"] == "connection_replaced"
    assert state.calls == {"manager": 0, "retry": 0}


def test_disabled_config_denies_reauth_before_side_effects(monkeypatch, failed_auth_reconnect):
    state = failed_auth_reconnect

    def reconnect(*args, **kwargs):
        state.config_path.write_text(
            "mcp_servers:\n  retained-auth:\n    command: owned-unused\n    enabled: false\n",
            encoding="utf-8",
        )
        return False

    monkeypatch.setattr(state.core, "_signal_reconnect_and_wait", reconnect)
    result = json.loads(state.invoke())
    assert result["mcp_policy"] == "disabled"
    assert state.calls == {"manager": 0, "retry": 0}


def test_live_session_does_not_reuse_retained_auth_failure(failed_auth_reconnect):
    state = failed_auth_reconnect
    state.server.session = object()
    assert state.invoke() is None
    assert state.calls == {"manager": 0, "retry": 0}


@pytest.mark.parametrize("next_attempt", ["success", "non_auth"])
def test_run_retains_original_failure_until_next_transport_attempt(monkeypatch, next_attempt):
    """A real persistent run task parks with its group, then drops stale auth."""
    from tools import mcp_tool
    from tools.mcp_oauth import OAuthNonInteractiveError

    original = ExceptionGroup("owned transport", [OAuthNonInteractiveError("expired")])
    non_auth = RuntimeError("owned network failure")
    attempts = []
    parked = []
    monkeypatch.setattr(mcp_tool, "_ensure_mcp_sdk", lambda: True)

    async def transport(server, config):
        assert server._error is None
        attempts.append(asyncio.current_task())
        if len(attempts) == 1:
            raise original
        assert len(attempts) == 2
        server._shutdown_event.set()
        if next_attempt == "non_auth":
            raise non_auth
        return "shutdown"

    async def wait(server, timeout):
        assert server._error is original
        parked.append(asyncio.current_task())
        return "reconnect"

    monkeypatch.setattr(mcp_tool.MCPServerTask, "_run_stdio", transport)
    monkeypatch.setattr(mcp_tool.MCPServerTask, "_wait_for_reconnect_or_shutdown", wait)

    async def scenario():
        server = mcp_tool.MCPServerTask("owned-lifetime")
        server._ever_connected = True
        server._task = asyncio.current_task()
        await server.run({
            "command": "owned-unused", "sampling": {"enabled": False},
            "elicitation": {"enabled": False},
        })
        assert attempts == [server._task, server._task]
        assert parked == [server._task]
        assert server._error is (non_auth if next_attempt == "non_auth" else None)

    asyncio.run(scenario())
