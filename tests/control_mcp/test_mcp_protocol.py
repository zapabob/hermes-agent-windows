"""The locked SDK client talks to the real Streamable HTTP server."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from fastapi import FastAPI


def _isolate_web_lifespan(monkeypatch, web_server):
    from gateway import code_skew

    for name in (
        "_eager_reconcile_own_session_db",
        "_resume_security_watch_on_startup",
        "_auto_update_security_definitions_on_startup",
        "_warm_gateway_module",
    ):
        monkeypatch.setattr(web_server, name, lambda: None)
    monkeypatch.setattr(code_skew, "record_boot_fingerprint", lambda: None)
    monkeypatch.delenv("HERMES_DESKTOP", raising=False)
    monkeypatch.delenv("HERMES_WATCHDOG_MANAGED", raising=False)

    async def idle(*_args):
        await asyncio.Event().wait()

    monkeypatch.setattr(web_server, "run_reaper", idle)
    monkeypatch.setattr(web_server, "_dashboard_selftest_loop", idle)
    monkeypatch.setattr(web_server, "_auto_archive_ticker_loop", idle)
    monkeypatch.setattr(web_server, "PTY_REGISTRY", SimpleNamespace(close_all=AsyncMock()))


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
    async def client(client_name="codex", app=None):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app or host.app),
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
async def test_existing_host_startup_mounts_explicit_config_for_two_real_sdk_clients(
    monkeypatch, tmp_path, control_module
):
    from hermes_cli import web_server

    auth = control_module("auth")
    service_module = control_module("service")
    observations_module = control_module("observations")
    startup_module = control_module("startup")
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
    issuer = "https://issuer.invalid"
    resource = "https://hermes.invalid/api/control/mcp"
    observations = observations_module.HermesObservations(
        homes={"p1": tmp_path / "p1", "p2": tmp_path / "p2"},
        registered_slots=(),
    )
    service = service_module.HostControlService(source=observations, clock=lambda: 100)
    startup_config = startup_module.ControlMCPStartupConfig(
        service=service,
        issuer=issuer,
        resource=resource,
        public_keys={"key-1": public},
        grant_lookup=lambda subject, client: (
            grants.get(client) if subject == "human-1" else None
        ),
        allowed_hosts=("hermes.invalid",),
        allowed_origins=("https://chatgpt.com",),
        clock=lambda: 100,
    )
    with pytest.raises(TypeError):
        startup_config.public_keys["other-key"] = public

    def token(client):
        return jwt.encode({
            "iss": issuer, "aud": resource, "sub": "human-1",
            "client_id": client, "scope": "hermes:read", "iat": 90,
            "nbf": 90, "exp": 200, "grant_revision": 1,
        }, private, algorithm="RS256", headers={"kid": "key-1", "typ": "at+jwt"})

    async def read_status(application, client_id, profile_id):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=application),
            base_url="https://hermes.invalid",
            headers={"Authorization": "Bearer " + token(client_id)},
        ) as http_client:
            async with streamable_http_client(resource, http_client=http_client) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    return await session.call_tool(
                        "hermes_get_runtime_status", {"profile_id": profile_id}
                    )

    application = web_server.app
    original_app_state = dict(application.state._state)
    original_routes = list(application.router.routes)
    application.state.control_mcp_startup_config = startup_config
    _isolate_web_lifespan(monkeypatch, web_server)

    try:
        assert getattr(application.state, "control_mcp_host", None) is None
        async with web_server._lifespan(application):
            assert getattr(application.state, "control_mcp_host", None) is not None
            mounted_index = application.router.routes.index(
                next(
                    route for route in application.router.routes
                    if getattr(route, "path", None) == "/api/control/mcp"
                )
            )
            spa_index = application.router.routes.index(
                next(
                    route for route in application.router.routes
                    if getattr(route, "path", None) == "/{full_path:path}"
                )
            )
            assert mounted_index < spa_index
            left, right = await asyncio.gather(
                read_status(application, "codex", "p1"),
                read_status(application, "chatgpt", "p2"),
            )
            assert left.structured_content["state"] == "ABSENT"
            assert right.structured_content["state"] == "ABSENT"
            assert left.structured_content["producer_epoch"] == right.structured_content["producer_epoch"]
    finally:
        application.router.routes[:] = original_routes
        application.state._state.clear()
        application.state._state.update(original_app_state)


@pytest.mark.asyncio
async def test_existing_host_startup_is_disabled_without_explicit_config(monkeypatch):
    from hermes_cli import web_server

    application = web_server.app
    original_app_state = dict(application.state._state)
    original_routes = list(application.router.routes)
    _isolate_web_lifespan(monkeypatch, web_server)

    try:
        assert getattr(application.state, "control_mcp_startup_config", None) is None
        assert getattr(application.state, "control_mcp_host", None) is None
        async with web_server._lifespan(application):
            assert getattr(application.state, "control_mcp_host", None) is None
            assert application.router.routes == original_routes
        assert getattr(application.state, "control_mcp_host", None) is None
        assert application.router.routes == original_routes
    finally:
        application.router.routes[:] = original_routes
        application.state._state.clear()
        application.state._state.update(original_app_state)


@pytest.mark.asyncio
async def test_empty_trusted_key_config_fails_before_mount_or_host_change(
    monkeypatch, control_module
):
    from downstream.control_mcp.contracts import ControlError
    from hermes_cli import web_server

    service = control_module("service").HostControlService(
        source=SimpleNamespace(runtime=lambda _profile: {}, routes=lambda _profile: {}),
        clock=lambda: 100,
    )
    config = control_module("startup").ControlMCPStartupConfig(
        service=service,
        issuer="https://issuer.invalid",
        resource="https://hermes.invalid/api/control/mcp",
        public_keys={},
        grant_lookup=lambda _subject, _client: None,
        allowed_hosts=("hermes.invalid",),
        allowed_origins=("https://chatgpt.com",),
        clock=lambda: 100,
    )
    application = web_server.app
    original_app_state = dict(application.state._state)
    original_routes = list(application.router.routes)
    application.state.control_mcp_startup_config = config
    _isolate_web_lifespan(monkeypatch, web_server)

    try:
        with pytest.raises(ControlError, match="invalid_host_configuration"):
            async with web_server._lifespan(application):
                pytest.fail("invalid configuration must fail before lifespan yield")
        assert getattr(application.state, "control_mcp_host", None) is None
        assert application.router.routes == original_routes
    finally:
        application.router.routes[:] = original_routes
        application.state._state.clear()
        application.state._state.update(original_app_state)


@pytest.mark.asyncio
async def test_untyped_startup_config_fails_before_route_registration(monkeypatch):
    from downstream.control_mcp.contracts import ControlError
    from hermes_cli import web_server

    application = web_server.app
    original_app_state = dict(application.state._state)
    original_routes = list(application.router.routes)
    application.state.control_mcp_startup_config = SimpleNamespace(
        issuer="https://issuer.invalid",
        resource="https://hermes.invalid/api/control/mcp",
    )
    _isolate_web_lifespan(monkeypatch, web_server)

    try:
        with pytest.raises(ControlError, match="invalid_host_configuration"):
            async with web_server._lifespan(application):
                pytest.fail("untyped configuration must fail before lifespan yield")
        assert getattr(application.state, "control_mcp_host", None) is None
        assert application.router.routes == original_routes
    finally:
        application.router.routes[:] = original_routes
        application.state._state.clear()
        application.state._state.update(original_app_state)


@pytest.mark.asyncio
async def test_existing_host_lifespan_preserves_preexisting_host_without_config(
    monkeypatch, protocol_host
):
    from hermes_cli import web_server

    host, _, _, _ = protocol_host
    application = web_server.app
    original_app_state = dict(application.state._state)
    original_routes = list(application.router.routes)
    application.state.control_mcp_host = host
    _isolate_web_lifespan(monkeypatch, web_server)

    try:
        async with web_server._lifespan(application):
            assert application.state.control_mcp_host is host
            assert application.router.routes == original_routes
        assert application.state.control_mcp_host is host
        assert application.router.routes == original_routes
    finally:
        application.router.routes[:] = original_routes
        application.state._state.clear()
        application.state._state.update(original_app_state)


@pytest.mark.asyncio
async def test_explicit_config_does_not_replace_or_unmount_preexisting_host(
    monkeypatch, protocol_host, control_module
):
    from downstream.control_mcp.contracts import ControlError
    from hermes_cli import web_server

    host, _, _, _ = protocol_host
    application = web_server.app
    original_app_state = dict(application.state._state)
    original_routes = list(application.router.routes)
    application.state.control_mcp_host = host
    application.state.control_mcp_startup_config = control_module("startup").ControlMCPStartupConfig(
        service=control_module("service").HostControlService(
            source=SimpleNamespace(runtime=lambda _profile: {}, routes=lambda _profile: {}),
        ),
        issuer="https://issuer.invalid",
        resource="https://hermes.invalid/api/control/mcp",
        public_keys={},
        grant_lookup=lambda _subject, _client: None,
        allowed_hosts=("hermes.invalid",),
        allowed_origins=("https://chatgpt.com",),
    )
    _isolate_web_lifespan(monkeypatch, web_server)

    try:
        with pytest.raises(ControlError, match="route_conflict"):
            async with web_server._lifespan(application):
                pytest.fail("conflicting config must not enter the lifespan")
        assert application.state.control_mcp_host is host
        assert application.router.routes == original_routes
    finally:
        application.router.routes[:] = original_routes
        application.state._state.clear()
        application.state._state.update(original_app_state)


@pytest.mark.asyncio
@pytest.mark.parametrize(('resource', 'authority', 'peer'), [
    ('http://127.0.0.1:9118/api/control/mcp', '127.0.0.1:9118', '127.0.0.1'),
    ('http://[::1]:9118/api/control/mcp', '[::1]:9118', '::1'),
])
async def test_real_sdk_read_on_explicit_loopback_http_resource(
    control_module, resource, authority, peer
):
    auth = control_module("auth")
    service_module = control_module("service")
    transport = control_module("transport")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    grant = auth.HostGrant(
        subject="human-1", client_registration="codex", revision=1,
        scopes=("hermes:read",), profiles=("p1",), workspaces=(("p1", "w1"),),
    )
    verifier = auth.ResourceVerifier(
        issuer="https://issuer.invalid", resource=resource,
        public_keys={"key-1": public},
        grant_lookup=lambda sub, client: grant if (sub, client) == ("human-1", "codex") else None,
    )

    class Source:
        def runtime(self, profile):
            return {"state": "ABSENT", "reason": "test_host"}

        def routes(self, profile):
            return {"state": "UNKNOWN", "routes": None}

    service = service_module.HostControlService(source=Source(), clock=lambda: 100)
    host = transport.create_control_mcp(
        service, verifier=verifier, allowed_hosts=(authority,),
        allowed_origins=("https://chatgpt.com",), clock=lambda: 100,
    )
    token = jwt.encode({
        "iss": verifier.issuer, "aud": resource, "sub": "human-1",
        "client_id": "codex", "scope": "hermes:read",
        "iat": 90, "nbf": 90, "exp": 200, "grant_revision": 1,
    }, private, algorithm="RS256", headers={"kid": "key-1", "typ": "at+jwt"})
    async with host.lifespan():
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=host.app, client=(peer, 50123)),
            base_url=resource.rsplit('/api/control/mcp', 1)[0],
            headers={"Authorization": "Bearer " + token},
        ) as http_client:
            async with streamable_http_client(resource, http_client=http_client) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "hermes_get_runtime_status", {"profile_id": "p1"}
                    )
                    assert result.structured_content["state"] == "ABSENT"


@pytest.mark.asyncio
async def test_revocation_blocks_the_next_protocol_request(protocol_host):
    host, client, _, grants = protocol_host
    async with host.lifespan():
        async with client() as session:
            await session.list_tools()
            grants["codex"] = replace(grants["codex"], enabled=False)
            with pytest.raises(Exception):
                await session.list_tools()

@pytest.mark.asyncio
async def test_parent_mount_starts_sdk_lifespan_and_preserves_other_routes(
    protocol_host, control_module
):
    host, client, _, _ = protocol_host
    transport = control_module("transport")
    parent = FastAPI()

    @parent.get("/api/existing")
    def existing():
        return {"existing": True}

    transport.mount_control_mcp(parent, host)
    async with transport.control_mcp_lifespan(parent):
        async with client(app=parent) as session:
            result = await session.call_tool("hermes_get_capabilities", {"profile_id": "p1"})
            assert result.structured_content["capabilities"]["read"] is True
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=parent),
            base_url="https://hermes.invalid",
        ) as http_client:
            assert (await http_client.get("/api/existing")).json() == {"existing": True}
            assert (await http_client.get("/api/control/mcp")).status_code == 401


@pytest.mark.asyncio
async def test_late_parent_mount_precedes_existing_spa_catch_all(
    protocol_host, control_module
):
    host, client, _, _ = protocol_host
    parent = FastAPI()

    @parent.api_route("/{full_path:path}", methods=["GET", "POST", "DELETE"])
    def spa_fallback(full_path: str):
        return {"spa": full_path}

    control_module("transport").mount_control_mcp(parent, host)
    async with control_module("transport").control_mcp_lifespan(parent):
        async with client(app=parent) as session:
            result = await session.call_tool(
                "hermes_get_capabilities", {"profile_id": "p1"}
            )
            assert result.structured_content["capabilities"]["read"] is True
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=parent),
            base_url="https://hermes.invalid",
        ) as http_client:
            assert (await http_client.get("/unrelated")).json() == {"spa": "unrelated"}


@pytest.mark.asyncio
@pytest.mark.parametrize("dashboard_gate", [False, True])
async def test_parent_dashboard_auth_never_grants_or_blocks_resource_auth(
    protocol_host, control_module, dashboard_gate
):
    from hermes_cli import web_server

    host, client, _, _ = protocol_host
    parent = FastAPI()
    parent.state.auth_required = dashboard_gate
    parent.middleware("http")(web_server.auth_middleware)
    parent.middleware("http")(web_server._dashboard_auth_gate)
    parent.middleware("http")(web_server._token_auth_seam)
    control_module("transport").mount_control_mcp(parent, host)

    @parent.get("/api/unrelated-private")
    def unrelated():
        return {"private": True}

    async with control_module("transport").control_mcp_lifespan(parent):
        async with client(app=parent) as session:
            result = await session.call_tool("hermes_get_capabilities", {"profile_id": "p1"})
            assert result.structured_content["capabilities"]["read"] is True
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=parent),
            base_url="https://hermes.invalid",
        ) as http_client:
            assert (await http_client.get("/api/control/mcp")).status_code == 401
            assert (await http_client.get(
                "/api/control/mcp",
                headers={"X-Hermes-Session-Token": web_server._SESSION_TOKEN},
            )).status_code == 401
            assert (await http_client.get(
                "/.well-known/oauth-protected-resource/api/control/mcp"
            )).status_code == 200
            assert (await http_client.get("/api/unrelated-private")).status_code == 401


@pytest.mark.asyncio
async def test_retired_engineering_tool_is_absent_even_with_legacy_coordinator(
        protocol_host, control_module):
    from types import SimpleNamespace

    old_host, client, _, _ = protocol_host
    journal = object()
    coordinator = SimpleNamespace(journal=journal)

    class Source:
        def runtime(self, profile):
            return {'state': 'UNKNOWN'}
        def routes(self, profile):
            return {'state': 'UNKNOWN', 'routes': []}

    service = control_module('service').HostControlService(
        source=Source(), journal=journal, coordinator=coordinator,
        clock=lambda: 100)
    host = control_module('transport').create_control_mcp(
        service, verifier=old_host.app.verifier,
        allowed_hosts=('hermes.invalid',),
        allowed_origins=('https://chatgpt.com',), clock=lambda: 100)
    async with host.lifespan():
        async with client(app=host.app) as session:
            names = {item.name for item in (await session.list_tools()).tools}
            assert 'hermes_start_engineering_run' not in names
            capabilities = await session.call_tool(
                'hermes_get_capabilities', {'profile_id': 'p1'})
            assert capabilities.structured_content['capabilities']['write'] is False
            assert capabilities.structured_content['capabilities']['write_operations']['start_engineering_run'] is False
            rejected = await session.call_tool('hermes_start_engineering_run', {})
            assert rejected.is_error is True
