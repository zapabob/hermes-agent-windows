"""Park OAuth authentication failures until their saved credentials change."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _token(access_token: str, refresh_token: str):
    token = MagicMock()
    token.model_dump.return_value = {
        "access_token": access_token,
        "token_type": "Bearer",
        "refresh_token": refresh_token,
    }
    return token


@pytest.mark.no_isolate
def test_parked_oauth_discovery_waits_for_credentials_but_explicit_reconnect_works(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools import mcp_tool
    from tools.mcp_oauth import HermesTokenStorage

    monkeypatch.setattr(mcp_tool, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_tool, "_ensure_mcp_sdk", lambda: True)
    monkeypatch.setattr(mcp_tool, "_MCP_SAMPLING_TYPES", False)
    monkeypatch.setattr(mcp_tool, "_MCP_ELICITATION_TYPES", False)
    monkeypatch.setattr(mcp_tool, "_classify_mcp_failure", lambda _exc: "permanent")
    monkeypatch.setattr(mcp_tool, "_is_auth_error", lambda _exc: True)
    monkeypatch.setattr(mcp_tool, "_validate_remote_mcp_url", lambda *_a, **_kw: None)

    storage = HermesTokenStorage("parked-oauth")
    asyncio.run(storage.set_tokens(_token("old-access", "old-refresh")))

    server = mcp_tool.MCPServerTask("parked-oauth")
    config = {
        "url": "https://mcp.example.invalid/",
        "auth": "oauth",
        "skip_preflight": True,
    }

    async def fail_auth(_self, _config):
        raise RuntimeError("authorization rejected")

    async def stop_after_park(_self, *, timeout=None):
        assert timeout == mcp_tool._PARKED_RETRY_INTERVAL
        return "shutdown"

    monkeypatch.setattr(mcp_tool.MCPServerTask, "_run_http", fail_auth)
    monkeypatch.setattr(
        mcp_tool.MCPServerTask, "_wait_for_reconnect_or_shutdown", stop_after_park
    )
    asyncio.run(server.run(config))

    monkeypatch.setitem(mcp_tool._servers, "parked-oauth", server)
    reconnects: list[str] = []
    monkeypatch.setattr(
        mcp_tool, "_signal_reconnect", lambda srv: reconnects.append(srv.name) or True
    )

    auth_paths = {storage._tokens_path(), storage._client_info_path()}
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes

    def reject_credential_reads(path, *args, **kwargs):
        if path in auth_paths:
            raise AssertionError("credential stamps must not read credential contents")
        return original_read_text(path, *args, **kwargs)

    def reject_credential_bytes(path, *args, **kwargs):
        if path in auth_paths:
            raise AssertionError("credential stamps must not read credential contents")
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_credential_reads)
    monkeypatch.setattr(Path, "read_bytes", reject_credential_bytes)

    # Repeated session discovery must not replay a known-dead refresh token.
    for _ in range(3):
        mcp_tool.register_mcp_servers({"parked-oauth": config})
    assert reconnects == []

    # A normal OAuth token writer changes the stat-only stamp and wakes the
    # parked server so the next session can use the newly authorized token.
    asyncio.run(storage.set_tokens(_token("fresh-access", "fresh-refresh-value")))
    mcp_tool.register_mcp_servers({"parked-oauth": config})
    assert reconnects == ["parked-oauth"]

    # User-requested reconnect remains an independent escape hatch.
    assert mcp_tool.reconnect_mcp_server("parked-oauth") is True
    assert reconnects == ["parked-oauth", "parked-oauth"]
