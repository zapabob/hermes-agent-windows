"""Bounded real-SDK controls for CVE-2026-59951; no network listeners."""

import asyncio

import httpx2
import pytest
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
               "clientInfo": {"name": "owned-retention-control", "version": "1"}},
}


@pytest.mark.asyncio
async def test_stateful_admission_keeps_existing_session_and_delete_frees_capacity():
    manager = StreamableHTTPSessionManager(Server("owned-retention"), json_response=True, max_sessions=1)
    # The dependency's default must also bound retention, rather than only
    # accepting a cap that applications have to know to opt into.
    default = StreamableHTTPSessionManager(Server("owned-default"))
    assert default.max_sessions is not None and default.max_sessions > 0
    assert default.session_idle_timeout is not None and default.session_idle_timeout > 0
    async with manager.run(), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=manager.asgi_app),
        base_url="http://127.0.0.1", headers=HEADERS,
    ) as client:
        first = await client.post("/mcp", json=INITIALIZE)
        assert first.status_code == 200
        session = {"Mcp-Session-Id": first.headers["mcp-session-id"]}
        assert (await client.post("/mcp", json=INITIALIZE)).status_code == 503
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        assert (await client.post("/mcp", json=initialized, headers=session)).status_code == 202
        ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        response = await client.post("/mcp", json=ping, headers=session)
        assert response.status_code == 200 and response.json()["result"] == {}
        assert (await client.delete("/mcp", headers=session)).status_code == 200
        assert (await client.post("/mcp", json=ping, headers=session)).status_code == 404
        replacement = await client.post("/mcp", json=INITIALIZE)
        assert replacement.status_code == 200
        assert replacement.headers["mcp-session-id"] != session["Mcp-Session-Id"]


@pytest.mark.asyncio
async def test_idle_session_is_reclaimed_and_new_session_remains_usable():
    manager = StreamableHTTPSessionManager(
        Server("owned-idle"), json_response=True, max_sessions=1, session_idle_timeout=0.05,
    )
    async with manager.run(), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=manager.asgi_app),
        base_url="http://127.0.0.1", headers=HEADERS,
    ) as client:
        first = await client.post("/mcp", json=INITIALIZE)
        assert first.status_code == 200
        session = {"Mcp-Session-Id": first.headers["mcp-session-id"]}
        # Read-only observation avoids resetting the session's idle timer.
        async with asyncio.timeout(5):
            while manager._server_instances:
                await asyncio.sleep(0.01)
        assert not manager._session_owners
        ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        assert (await client.post("/mcp", json=ping, headers=session)).status_code == 404
        replacement = await client.post("/mcp", json=INITIALIZE)
        assert replacement.status_code == 200
        assert replacement.headers["mcp-session-id"] != session["Mcp-Session-Id"]
