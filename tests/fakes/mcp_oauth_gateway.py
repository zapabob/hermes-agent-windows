"""Real SDK discovery/DCR/PKCE/token/probe/registry effects on owned loopback."""

import errno
import json
import socket
import threading
from contextlib import contextmanager
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tui_gateway import mcp_oauth_sessions as sessions
from tui_gateway import server


@contextmanager
def scoped(home):
    token = set_hermes_home_override(str(home))
    try:
        yield
    finally:
        reset_hermes_home_override(token)


@pytest.fixture
def homes(tmp_path, monkeypatch):
    root = tmp_path / "owned-home"
    for name in ("work", "other"):
        (root / "profiles" / name).mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(root))
    from tools.mcp_oauth_manager import reset_manager_for_tests
    import tools.mcp_tool as core

    assert not sessions._sessions
    assert not core._servers
    reset_manager_for_tests()
    yield root
    for rec in list(sessions._sessions.values()):
        rec["flow"].mark_error("Owned fixture cleanup")
        sessions._shutdown_listener(rec)
    sessions._sessions.clear()
    core.shutdown_mcp_servers()
    reset_manager_for_tests()


def rpc(operation, *, profile="work", **params):
    method = f"mcp.servers.oauth.{operation}"
    assert method in server._methods
    result = server._methods[method](19, {"name": "reports", "profile": profile, **params})
    assert "error" not in result, result
    return result["result"]


@contextmanager
def running_flow(owner, root, *, manual_start=False):
    from hermes_cli.mcp_config import _replace_mcp_servers

    cfg = {"url": owner.mcp_url, "transport": "http", "auth": "oauth", "oauth": {"cimd": False}, "timeout": 5}
    for profile in ("work", "other"):
        with scoped(root / "profiles" / profile):
            ok, issues = _replace_mcp_servers({"reports": cfg})
            assert ok and not issues, issues
    import tools.mcp_tool as core

    before = set(threading.enumerate())
    owned_threads = set()
    owned_loops = []
    ports = set()
    try:
        if manual_start:
            yield None, None, None, None, None, owned_loops
            return
        result = rpc("start")
        if core._mcp_loop is not None:
            owned_loops.append((core._mcp_loop, core._mcp_thread))
        assert result["ok"], result
        rec = sessions._sessions[result["session_id"]]
        workers = [thread for thread in threading.enumerate() if thread not in before and thread.name == "mcp-oauth-reports"]
        listeners = [thread for thread in threading.enumerate() if thread not in before and thread.name == "mcp-oauth-cb-reports"]
        owned_threads.update(workers + listeners)
        ports.add(rec["httpd"].server_address[1])
        assert len(workers) == len(listeners) == 1
        assert owner.operations("registration")
        assert owner.operations("get")
        yield result, rec, workers[0], listeners[0], rec["httpd"].server_address[1], owned_loops
    finally:
        errors = []

        def attempt(label, action):
            try:
                action()
            except BaseException as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")

        def joined(thread):
            thread.join(timeout=12)
            assert not thread.is_alive(), thread.name

        owner.token_release.set()
        owned_threads.update(thread for thread in threading.enumerate() if thread not in before
                             and thread.name in {"mcp-oauth-reports", "mcp-oauth-cb-reports"})
        for sid, rec in list(sessions._sessions.items()):
            if rec["hermes_home"] != str(root / "profiles" / "work") or rec["server_name"] != "reports":
                continue
            if rec.get("httpd") is not None:
                ports.add(rec["httpd"].server_address[1])
            attempt(f"flow_release_{sid}", lambda rec=rec: rec["flow"].mark_error("Owned test cleanup"))
            attempt(f"listener_shutdown_{sid}", lambda rec=rec: sessions._shutdown_listener(rec))
        for index, thread in enumerate(owned_threads):
            attempt(f"gateway_thread_exit_{index}", lambda thread=thread: joined(thread))
        if core._mcp_loop is not None:
            owned_loops.append((core._mcp_loop, core._mcp_thread))
        attempt("mcp_shutdown", core.shutdown_mcp_servers)
        for loop, thread in owned_loops:
            attempt("mcp_thread_exit", lambda thread=thread: joined(thread))
            attempt("mcp_loop_closed", lambda loop=loop: closed(loop))
        for port in ports:
            attempt("gateway_refusal", lambda port=port: refused(port))
        assert not errors, errors


def closed(loop):
    assert loop.is_closed() and not loop.is_running()


def refused(port):
    with pytest.raises(ConnectionRefusedError) as refusal:
        socket.create_connection(("127.0.0.1", port), timeout=4)
    assert refusal.value.errno == errno.ECONNREFUSED or refusal.value.winerror == 10061


def finish(rec, worker, listener, port):
    assert rec["flow"]._worker_done.wait(12), rec["flow"].snapshot()
    worker.join(timeout=3)
    listener.join(timeout=3)
    assert not worker.is_alive()
    assert not listener.is_alive()
    assert rec["httpd"] is None
    refused(port)


def deliver(owner, flow, issuer_mode):
    code, state, redirect = owner.issue_code(flow["auth_url"])
    params = {"code": code, "state": state}
    if issuer_mode != "absent":
        params["iss"] = {
            "match": owner.issuer, "mismatch": owner.base + "/foreign-issuer",
            "empty": "", "slash": owner.issuer + "/",
        }[issuer_mode]
    with urlopen(redirect + "?" + urlencode(params), timeout=3) as response:
        assert response.status == 200


def registry_effect(owner, home, nonce):
    import tools.mcp_tool as core
    from tools.registry import registry

    with scoped(home):
        tool = "mcp__reports__write_sentinel"
        loop = thread = None
        try:
            assert tool in core.discover_mcp_tools(), core._server_connect_errors
            loop, thread = core._mcp_loop, core._mcp_thread
            before = len(owner.operations("sentinel"))
            result = json.loads(registry.dispatch(tool, {"nonce": nonce}))
            assert "error" not in result, result
            after = owner.operations("sentinel")
            assert len(after) == before + 1
            assert after[-1]["nonce"] == nonce
        finally:
            if loop is None:
                loop, thread = core._mcp_loop, core._mcp_thread
            core.shutdown_mcp_servers()
            if loop is not None:
                closed(loop)
                thread.join(timeout=3)
                assert not thread.is_alive()
