"""Transport configuration must connect without inventing OAuth authority."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("oauth", [False, True])
def test_transport_enters_session_and_preserves_explicit_configuration(monkeypatch, tmp_path, transport, oauth):
    from tools import mcp_tool as core
    from tools import mcp_oauth_manager

    core._ensure_mcp_sdk()
    server = core.MCPServerTask("owned-transport-fixture")
    server._auth_type = "oauth" if oauth else ""
    provider = object()
    manager = SimpleNamespace(get_or_build_provider=MagicMock(return_value=provider))
    get_manager = MagicMock(return_value=manager)
    if not oauth:
        get_manager.side_effect = AssertionError("Plain transport must never build an OAuth provider")
    monkeypatch.setattr(mcp_oauth_manager, "get_manager", get_manager)
    seen, sessions = {}, []
    cert = tmp_path / "fixture.pem"
    cert.write_text("synthetic certificate fixture", encoding="utf-8")

    class Client:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False

    class Streams:
        async def __aenter__(self):
            return MagicMock(), MagicMock()
        async def __aexit__(self, *_args):
            return False

    class Session:
        def __init__(self, *_args, **_kwargs):
            self.initialize = AsyncMock()
        async def __aenter__(self):
            sessions.append(self)
            return self
        async def __aexit__(self, *_args):
            return False

    def sse(**kwargs):
        seen["sse"] = kwargs
        kwargs["httpx_client_factory"]()
        return Streams()

    monkeypatch.setattr(core, "_MCP_HTTP_AVAILABLE", True)
    monkeypatch.setattr(core, "_MCP_NEW_HTTP", True)
    monkeypatch.setattr(core.sdk_httpx(), "AsyncClient", Client)
    monkeypatch.setattr(core, "streamable_http_client", lambda *_a, **_kw: Streams())
    monkeypatch.setattr(core, "sse_client", sse)
    monkeypatch.setattr(core, "ClientSession", Session)
    monkeypatch.setattr(core.MCPServerTask, "_discover_tools", AsyncMock())
    monkeypatch.setattr(core.MCPServerTask, "_wait_for_lifecycle_event", AsyncMock(return_value="shutdown"))
    config = {"url": "http://127.0.0.1:9/owned-mocked-transport", "transport": transport,
              "connect_timeout": 7, "ssl_verify": False, "client_cert": str(cert),
              "headers": {"MCP-Protocol-Version": "fixture-override", "X-Fixture": "kept"}}
    assert asyncio.run(server._run_http(config)) == "shutdown"
    assert len(sessions) == 1 and sessions[0].initialize.await_count == 1
    assert server._ready.is_set() and server._ever_connected
    assert seen["client"]["verify"] is False and seen["client"]["cert"] == str(cert)
    actual = seen["sse"] if transport == "sse" else seen["client"]
    assert actual["headers"] == config["headers"]
    assert actual.get("auth") is (provider if oauth else None)
    if transport == "sse":
        assert actual["timeout"] == 7 and actual["sse_read_timeout"] == 300
    else:
        assert actual["timeout"].connect == 7 and actual["timeout"].read == 300
    assert get_manager.call_count == int(oauth)
    assert manager.get_or_build_provider.call_count == int(oauth)
