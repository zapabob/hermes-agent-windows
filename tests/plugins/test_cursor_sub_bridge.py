"""Unit tests for cursor_sub_bridge queue + loopback shim (no live Cursor)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from plugins.cursor_sub_bridge import mcp_server, queue, shim


@pytest.fixture
def bridge_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(queue, "get_hermes_home", lambda: home)
    return home


def test_enqueue_poll_respond_roundtrip(bridge_home: Path) -> None:
    req_id = queue.enqueue_chat_completion(
        messages=[{"role": "user", "content": "ping"}],
        model="cursor-sub/default",
    )
    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] == req_id

    polled = queue.poll_next()
    assert polled is not None
    assert polled["id"] == req_id
    assert polled["messages"][0]["content"] == "ping"

    result = queue.respond(req_id, "pong")
    assert result["ok"] is True

    content = queue.wait_for_response(req_id, timeout=2.0, interval=0.05)
    assert content == "pong"
    assert queue.list_pending() == []


def test_respond_unknown_id(bridge_home: Path) -> None:
    result = queue.respond("missing", "x")
    assert result["ok"] is False
    assert result["error"] == "unknown_request"


def test_wait_timeout(bridge_home: Path) -> None:
    req_id = queue.enqueue_chat_completion(
        messages=[{"role": "user", "content": "slow"}],
    )
    with pytest.raises(TimeoutError):
        queue.wait_for_response(req_id, timeout=0.2, interval=0.05)


def test_non_loopback_bind_refused() -> None:
    with pytest.raises(ValueError, match="non_loopback_bind_refused"):
        shim.resolve_bind_host("0.0.0.0")


def test_shim_chat_completions_with_background_responder(
    bridge_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    monkeypatch.setenv("CURSOR_SUB_BRIDGE_API_KEY", "test-key")
    monkeypatch.setattr(queue, "_poll_timeout", lambda: 3.0)
    monkeypatch.setattr(queue, "_poll_interval", lambda: 0.05)

    httpd = shim.serve(host="127.0.0.1", port=0)
    host, port = httpd.server_address[:2]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    stop = threading.Event()

    def _drain() -> None:
        while not stop.is_set():
            item = queue.poll_next()
            if item is not None:
                queue.respond(str(item["id"]), "hello-from-cursor")
                return
            time.sleep(0.05)

    drainer = threading.Thread(target=_drain, daemon=True)
    drainer.start()

    body = json.dumps(
        {
            "model": "cursor-sub/default",
            "messages": [{"role": "user", "content": "hi"}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    finally:
        stop.set()
        httpd.shutdown()
        httpd.server_close()
        drainer.join(timeout=2)
        thread.join(timeout=2)

    assert payload["choices"][0]["message"]["content"] == "hello-from-cursor"


def test_shim_rejects_bad_auth(bridge_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURSOR_SUB_BRIDGE_API_KEY", "secret")
    httpd = shim.serve(host="127.0.0.1", port=0)
    host, port = httpd.server_address[:2]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/models",
        headers={"Authorization": "Bearer wrong"},
        method="GET",
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 401
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_shim_invalid_json(bridge_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURSOR_SUB_BRIDGE_API_KEY", "secret")
    httpd = shim.serve(host="127.0.0.1", port=0)
    host, port = httpd.server_address[:2]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/chat/completions",
        data=b"{not-json",
        headers={
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_mcp_tools_poll_respond(bridge_home: Path) -> None:
    req_id = queue.enqueue_chat_completion(
        messages=[{"role": "user", "content": "mcp"}],
    )
    poll_msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "cursor_sub_poll", "arguments": {}},
    }
    poll_resp = mcp_server._handle(poll_msg)
    assert poll_resp is not None
    text = poll_resp["result"]["content"][0]["text"]
    data = json.loads(text)
    assert data["ok"] is True
    assert data["id"] == req_id

    respond_msg = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "cursor_sub_respond",
            "arguments": {"id": req_id, "content": "via-mcp"},
        },
    }
    respond_resp = mcp_server._handle(respond_msg)
    assert respond_resp is not None
    rdata = json.loads(respond_resp["result"]["content"][0]["text"])
    assert rdata["ok"] is True

    # Response already consumed the files via respond(); wait should fail softly
    # because respond wrote response file — wait_for_response still works if file exists.
    content = queue.wait_for_response(req_id, timeout=1.0, interval=0.05)
    assert content == "via-mcp"


def test_mcp_initialize() -> None:
    resp = mcp_server._handle(
        {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}
    )
    assert resp is not None
    assert resp["result"]["serverInfo"]["name"] == "cursor-sub-bridge"


def test_provider_profile_registers() -> None:
    import importlib.util
    from pathlib import Path

    from providers import get_provider_profile

    init_path = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "model-providers"
        / "cursor-sub"
        / "__init__.py"
    )
    spec = importlib.util.spec_from_file_location("cursor_sub_provider_under_test", init_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    profile = get_provider_profile("cursor-sub")
    assert profile is not None
    assert profile.name == "cursor-sub"
    assert "127.0.0.1" in (profile.base_url or "")
