"""The locked SDK client talks to the real Streamable HTTP server."""
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.fixture
def protocol_host(control_module):
    auth = control_module("auth")
    service_module = control_module("service")
    transport = control_module("transport")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    grants = {
        client: auth.HostGrant(
            subject="human-1", client_registration=client, revision=1,
            scopes=("hermes:read",), profiles=(profile,),
            workspaces=((profile, "w1"),),
        )
        for client, profile in (("codex", "p1"), ("chatgpt", "p2"))
    }
    verifier = auth.ResourceVerifier(
        issuer="https://issuer.invalid",
        resource="https://hermes.invalid/api/control/mcp",
        public_keys={"key-1": public},
        grant_lookup=lambda subject, client: grants.get(client) if subject == "human-1" else None,
    )

    class Source:
        def runtime(self, profile):
            return {"state": "UNKNOWN", "profile": profile}

        def routes(self, profile):
            return {"state": "UNKNOWN", "profile": profile, "routes": []}

    service = service_module.HostControlService(source=Source(), clock=lambda: 100)
    host = transport.create_control_mcp(
        service, verifier=verifier, allowed_hosts=("hermes.invalid",),
        allowed_origins=("https://chatgpt.com",), clock=lambda: 100,
    )

    def token(client="codex", **changes):
        claims = {
            "iss": verifier.issuer, "aud": verifier.resource, "sub": "human-1",
            "client_id": client, "scope": "hermes:read", "iat": 90,
            "nbf": 90, "exp": 200, "grant_revision": 1, **changes,
        }
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "key-1", "typ": "at+jwt"})

    @asynccontextmanager
    async def client(client_name="codex"):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=host.app),
            base_url="https://hermes.invalid",
            headers={"Authorization": "Bearer " + token(client_name)},
        ) as http_client:
            async with streamable_http_client(
                "https://hermes.invalid/api/control/mcp", http_client=http_client
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    yield session

    return host, client, token, grants


@pytest.mark.asyncio
async def test_real_sdk_initialise_list_and_scoped_call(protocol_host):
    host, client, _, _ = protocol_host
    async with host.lifespan():
        async with client("codex") as session:
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert "hermes_get_capabilities" in names
            assert "hermes_get_routes" in names
            assert "hermes_start_engineering_run" not in names
            result = await session.call_tool("hermes_get_routes", {"profile_id": "p1"})
            assert result.is_error is not True
            assert result.structured_content["profile_id"] == "p1"
            denied = await session.call_tool("hermes_get_routes", {"profile_id": "p2"})
            assert denied.is_error is True
            assert "resource_denied" in str(denied.content)
        async with client("chatgpt") as session:
            result = await session.call_tool("hermes_get_routes", {"profile_id": "p2"})
            assert result.structured_content["profile_id"] == "p2"


@pytest.mark.asyncio
async def test_revocation_blocks_the_next_protocol_request(protocol_host):
    host, client, _, grants = protocol_host
    async with host.lifespan():
        async with client() as session:
            await session.list_tools()
            grants["codex"] = replace(grants["codex"], enabled=False)
            with pytest.raises(Exception):
                await session.list_tools()
