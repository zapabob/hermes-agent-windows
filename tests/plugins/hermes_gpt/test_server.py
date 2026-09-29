import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.hermes_gpt import register, server
from plugins.hermes_gpt import oauth_auth
from plugins.hermes_gpt.oauth_asgi import build_oauth_http_app
from plugins.hermes_gpt.cli import hermes_gpt_command
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


GATE_ENVS = [
    server.ENABLE_WRITE_ENV,
    server.ENABLE_MEMORY_WRITE_ENV,
    server.ENABLE_SESSION_SEARCH_ENV,
    server.ENABLE_TERMINAL_ENV,
    server.UNSAFE_REMOTE_ENV,
    oauth_auth.OAUTH_ENABLE_ENV,
    oauth_auth.OAUTH_ISSUER_ENV,
    oauth_auth.OAUTH_CLIENT_ID_ENV,
    oauth_auth.OAUTH_CLIENT_SECRET_ENV,
    oauth_auth.OAUTH_REDIRECT_URI_ENV,
]


class _FakeContext:
    def __init__(self) -> None:
        self.cli_commands = {}

    def register_cli_command(self, name, **kwargs):
        self.cli_commands[name] = kwargs


def clear_gate_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in GATE_ENVS:
        monkeypatch.delenv(name, raising=False)


def tool_names(mcp_server) -> list[str]:
    tools = asyncio.run(mcp_server.list_tools())
    return sorted(tool.name for tool in tools)


def tools_by_name(mcp_server):
    tools = asyncio.run(mcp_server.list_tools())
    return {tool.name: tool for tool in tools}


def test_register_exposes_cli_command():
    ctx = _FakeContext()

    register(ctx)

    assert "hermes-gpt" in ctx.cli_commands
    command = ctx.cli_commands["hermes-gpt"]
    assert command["handler_fn"] is hermes_gpt_command


def test_cli_status_returns_json(monkeypatch, capsys):
    payload = {"ok": True, "tools": ["hermes_read_file"], "gates": {}}
    monkeypatch.setattr(server, "status", lambda: payload)
    monkeypatch.setattr(server, "IMPORT_ERROR", None)

    rc = hermes_gpt_command(SimpleNamespace(hermes_gpt_command="status"))

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == payload


def test_default_tool_surface_is_read_or_local_metadata_only(monkeypatch):
    clear_gate_envs(monkeypatch)

    built = server.build_server()
    names = tool_names(built)

    assert names == sorted(
        [
            "hermes_memory",
            "hermes_read_file",
            "hermes_search_files",
            "hermes_skill_list",
            "hermes_skill_view",
        ]
    )

    for tool in tools_by_name(built).values():
        assert tool.meta == {"securitySchemes": [{"type": "noauth"}]}


def test_env_gates_expose_high_risk_tools(monkeypatch):
    clear_gate_envs(monkeypatch)
    monkeypatch.setenv(server.ENABLE_WRITE_ENV, "1")
    monkeypatch.setenv(server.ENABLE_TERMINAL_ENV, "1")
    monkeypatch.setenv(server.ENABLE_SESSION_SEARCH_ENV, "1")

    names = tool_names(server.build_server())

    assert "hermes_write_file" in names
    assert "hermes_patch" in names
    assert "hermes_run_command" in names
    assert "hermes_session_search" in names


def test_memory_write_actions_are_disabled_by_default(monkeypatch):
    clear_gate_envs(monkeypatch)
    monkeypatch.setattr(server, "require_imports", lambda: None)
    monkeypatch.setattr(
        server,
        "memory_tool",
        SimpleNamespace(memory_tool=lambda **kwargs: "should not be called"),
    )

    with pytest.raises(RuntimeError, match=server.ENABLE_MEMORY_WRITE_ENV):
        server.hermes_memory(action="add", target="memory", content="x")


def test_memory_search_remains_available(monkeypatch):
    clear_gate_envs(monkeypatch)
    captured = {}

    def fake_memory_tool(**kwargs):
        captured.update(kwargs)
        return "memory search ok"

    monkeypatch.setattr(server, "require_imports", lambda: None)
    monkeypatch.setattr(server, "memory_tool", SimpleNamespace(memory_tool=fake_memory_tool))

    assert server.hermes_memory(action="search", target="memory") == "memory search ok"
    assert captured["action"] == "search"


def test_terminal_direct_call_is_disabled_by_default(monkeypatch):
    clear_gate_envs(monkeypatch)
    monkeypatch.setattr(server, "require_imports", lambda: None)
    monkeypatch.setattr(
        server,
        "terminal_tool",
        SimpleNamespace(terminal_tool=lambda **kwargs: "should not be called"),
    )

    with pytest.raises(RuntimeError, match=server.ENABLE_TERMINAL_ENV):
        server.hermes_run_command("echo nope")


def test_terminal_timeout_is_capped_when_enabled(monkeypatch):
    clear_gate_envs(monkeypatch)
    monkeypatch.setenv(server.ENABLE_TERMINAL_ENV, "1")
    captured = {}

    def fake_terminal_tool(command, timeout=None, workdir=None):
        captured.update({"command": command, "timeout": timeout, "workdir": workdir})
        return "ok"

    monkeypatch.setattr(server, "require_imports", lambda: None)
    monkeypatch.setattr(server, "terminal_tool", SimpleNamespace(terminal_tool=fake_terminal_tool))

    assert server.hermes_run_command("echo ok", timeout=999) == "ok"
    assert captured["timeout"] == 120


def test_remote_profile_requires_explicit_unsafe_ack(monkeypatch):
    clear_gate_envs(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["server.py", "--http", "--profile", "remote"])

    with pytest.raises(SystemExit, match="Remote profile requires OAuth"):
        server.main()


def test_oauth_config_advertises_oauth_security_scheme(monkeypatch):
    clear_gate_envs(monkeypatch)
    monkeypatch.setenv(oauth_auth.OAUTH_ENABLE_ENV, "1")
    monkeypatch.setenv(oauth_auth.OAUTH_ISSUER_ENV, "https://mcp.example.test")
    monkeypatch.setenv(oauth_auth.OAUTH_CLIENT_ID_ENV, "chatgpt-client")
    monkeypatch.setenv(
        oauth_auth.OAUTH_CLIENT_SECRET_ENV,
        "test-client-secret-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    )
    monkeypatch.setenv(
        oauth_auth.OAUTH_REDIRECT_URI_ENV,
        "https://chatgpt.com/connector/oauth/callback",
    )

    built = server.build_server()

    assert all(
        tool.meta == {"securitySchemes": [{"type": "oauth2", "scopes": ["hermes"]}]}
        for tool in tools_by_name(built).values()
    )


def test_oauth_asgi_protects_mcp_and_serves_discovery():
    state = oauth_auth.OAuthState(
        oauth_auth.OAuthConfig(
            issuer="https://mcp.example.test",
            client_id="chatgpt-client",
            client_secret="test-client-secret-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            redirect_uris=("https://chatgpt.com/connector/oauth/callback",),
            scope="hermes",
        )
    )

    async def mcp_endpoint(_request: Request):
        return JSONResponse({"ok": True})

    app = build_oauth_http_app(
        Starlette(routes=[Route("/mcp", mcp_endpoint, methods=["GET"])]),
        state,
    )

    with TestClient(app) as client:
        discovery = client.get("/.well-known/oauth-protected-resource")
        denied = client.get("/mcp")

    assert discovery.status_code == 200
    assert discovery.json()["authorization_servers"] == ["https://mcp.example.test"]
    assert denied.status_code == 401
    assert "resource_metadata" in denied.headers["www-authenticate"]


def test_oauth_wraps_the_real_mcp_streamable_http_app(monkeypatch, tmp_path):
    import base64
    import hashlib
    import secrets
    import urllib.parse

    clear_gate_envs(monkeypatch)
    monkeypatch.setenv(oauth_auth.OAUTH_ENABLE_ENV, "1")
    monkeypatch.setenv(oauth_auth.OAUTH_ISSUER_ENV, "https://mcp.example.test")
    monkeypatch.setenv(oauth_auth.OAUTH_CLIENT_ID_ENV, "chatgpt-client")
    monkeypatch.setenv(
        oauth_auth.OAUTH_CLIENT_SECRET_ENV,
        "test-client-secret-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    )
    monkeypatch.setenv(
        oauth_auth.OAUTH_REDIRECT_URI_ENV,
        "https://chatgpt.com/connector/oauth/callback",
    )
    monkeypatch.setattr(server, "hermes_data_root", lambda: tmp_path)
    built = server.build_server(host="127.0.0.1", port=7777, http=True)
    raw_app = built.streamable_http_app(
        host="127.0.0.1",
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
    app = build_oauth_http_app(raw_app, built._hermes_oauth_state)

    with TestClient(app) as client:
        metadata = client.get("/.well-known/oauth-authorization-server")
        unauthorized = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        authorization = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "chatgpt-client",
                "redirect_uri": "https://chatgpt.com/connector/oauth/callback",
                "scope": "hermes openid offline_access",
                "resource": "https://mcp.example.test/mcp",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "test-state",
            },
            follow_redirects=False,
        )
        auth_query = urllib.parse.parse_qs(urllib.parse.urlparse(authorization.headers["location"]).query)
        token_response = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "chatgpt-client",
                "client_secret": "test-client-secret-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                "code": auth_query["code"][0],
                "redirect_uri": "https://chatgpt.com/connector/oauth/callback",
                "code_verifier": verifier,
            },
        )
        authenticated = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Authorization": f"Bearer {token_response.json()['access_token']}"},
        )
    access_token = token_response.json()["access_token"]

    restarted = server.build_server(host="127.0.0.1", port=7777, http=True)
    restarted_raw_app = restarted.streamable_http_app(
        host="127.0.0.1",
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
    restarted_app = build_oauth_http_app(restarted_raw_app, restarted._hermes_oauth_state)
    with TestClient(restarted_app) as client:
        restored = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert metadata.status_code == 200
    assert metadata.json()["authorization_endpoint"] == "https://mcp.example.test/oauth/authorize"
    assert unauthorized.status_code == 401
    assert "resource_metadata" in unauthorized.headers["www-authenticate"]
    assert authorization.status_code == 302
    assert auth_query["state"] == ["test-state"]
    assert token_response.status_code == 200
    assert authenticated.status_code != 401
    assert restored.status_code != 401


def test_local_dev_http_rejects_non_loopback_without_unsafe_ack(monkeypatch):
    clear_gate_envs(monkeypatch)

    with pytest.raises(SystemExit, match="non-loopback host exposes noauth Hermes tools"):
        server.main(["--http", "--host", "0.0.0.0"])


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_http_initialize_smoke(monkeypatch):
    port = free_port()
    env = os.environ.copy()
    for name in GATE_ENVS:
        env.pop(name, None)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "plugins.hermes_gpt.server",
            "--http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        deadline = time.time() + 30
        last_error = None
        response_text = None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1"},
            },
        }
        data = json.dumps(payload).encode("utf-8")
        while time.time() < deadline:
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/mcp",
                    data=data,
                    method="POST",
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    response_text = response.read().decode("utf-8")
                    break
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
        if response_text is None:
            raise AssertionError(f"HTTP MCP server did not respond: {last_error}")

        parsed = json.loads(response_text)
        assert parsed["result"]["serverInfo"]["name"] == "hermes-gpt"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
