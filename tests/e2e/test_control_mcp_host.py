"""The locked MCP SDK uses the actual Hermes FastAPI parent and lifespan."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import importlib
import socket
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.mark.asyncio
async def test_real_hermes_parent_serves_two_scoped_clients_without_read_side_effects(
    tmp_path, monkeypatch
):
    """Use production middleware, the producer adapter, and parent-owned SDK lifespan."""
    from gateway import code_skew
    from hermes_cli import config, managed_scope, web_server

    auth = importlib.import_module("downstream.control_mcp.auth")
    service_module = importlib.import_module("downstream.control_mcp.service")
    observations_module = importlib.import_module("downstream.control_mcp.observations")
    transport = importlib.import_module("downstream.control_mcp.transport")
    resource = "https://hermes.invalid/api/control/mcp"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    profiles = {"codex-desktop": "profile-codex", "chatgpt-web": "profile-web"}
    grants = {
        client: auth.HostGrant(
            subject="operator-1",
            client_registration=client,
            revision=3,
            scopes=("hermes:read",),
            profiles=(profile,),
            workspaces=((profile, "workspace-1"),),
        )
        for client, profile in profiles.items()
    }
    verifier = auth.ResourceVerifier(
        issuer="https://issuer.invalid",
        resource=resource,
        public_keys={"test-key": public_key},
        grant_lookup=lambda subject, client: (
            grants.get(client) if subject == "operator-1" else None
        ),
    )

    homes = {profile: tmp_path / profile for profile in profiles.values()}
    snapshots = {
        "profile-codex": {
            "auxiliary": {
                "engineering_worker": {
                    "provider": "test-provider",
                    "model": "test-worker",
                    "reasoning": {"enabled": True, "effort": "high"},
                }
            }
        },
        "profile-web": {
            "auxiliary": {
                "engineering_worker": {
                    "provider": "test-provider",
                    "model": "test-worker",
                    "reasoning": {"enabled": True, "effort": "low"},
                }
            }
        },
    }
    cache = {}
    for profile, home in homes.items():
        home.mkdir()
        config_path = home / "config.yaml"
        config_path.write_text("auxiliary: {}\n", encoding="utf-8")
        stat = config_path.stat()
        # This is the normal already-loaded effective-config cache shape. The
        # MCP read must observe it without hydrating config or resolving secrets.
        cache[str(config_path)] = (
            stat.st_mtime_ns,
            stat.st_size,
            0,
            0,
            deepcopy(snapshots[profile]),
            {},
        )
    monkeypatch.setattr(config, "_LOAD_CONFIG_CACHE", cache)
    monkeypatch.setattr(managed_scope, "get_managed_dir", lambda: None)

    source = observations_module.HermesObservations(
        homes=homes,
        registered_slots=("engineering_worker",),
    )
    service = service_module.HostControlService(source=source, clock=lambda: 100)
    host = transport.create_control_mcp(
        service,
        verifier=verifier,
        allowed_hosts=("hermes.invalid",),
        allowed_origins=("https://chatgpt.com",),
        clock=lambda: 100,
    )
    app = web_server.app
    original_routes = list(app.router.routes)
    original_app_state = dict(app.state._state)
    original_host = getattr(app.state, "control_mcp_host", None)
    assert original_host is None, "the production host must remain opt-in before this test mounts it"

    # Avoid unrelated Hermes startup work while retaining the real parent
    # lifespan, middleware chain, route dispatch and MCP session manager.
    for name in (
        "_eager_reconcile_own_session_db",
        "_resume_security_watch_on_startup",
        "_auto_update_security_definitions_on_startup",
        "_warm_gateway_module",
    ):
        monkeypatch.setattr(web_server, name, lambda: None)
    monkeypatch.setattr(code_skew, "record_boot_fingerprint", lambda: None)
    monkeypatch.setattr(
        web_server,
        "PTY_REGISTRY",
        SimpleNamespace(close_all=AsyncMock()),
    )
    monkeypatch.setattr(web_server, "run_reaper", _idle)
    monkeypatch.setattr(web_server, "_dashboard_selftest_loop", _idle)
    monkeypatch.setattr(web_server, "_auto_archive_ticker_loop", _idle)
    monkeypatch.delenv("HERMES_DESKTOP", raising=False)
    monkeypatch.delenv("HERMES_WATCHDOG_MANAGED", raising=False)
    app.state.auth_required = False
    app.state.bound_host = "hermes.invalid"

    # Reads must consume the warm, side-effect-free config snapshot above.
    def forbidden_config_hydration(*_args, **_kwargs):
        raise AssertionError("MCP read invoked config hydration or secret expansion")

    monkeypatch.setattr(config, "load_config", forbidden_config_hydration)
    monkeypatch.setattr(config, "_load_config_impl", forbidden_config_hydration)
    monkeypatch.setattr(config, "_expand_env_vars", forbidden_config_hydration)

    # These requests are entirely in-process. Any socket or child-process
    # attempt during an MCP read would be an unexpected OAuth/provider/Docker/
    # scanner side effect, so make the boundary fail loudly.
    def forbidden_external_effect(*_args, **_kwargs):
        raise AssertionError("MCP read attempted network or child-process work")

    monkeypatch.setattr(socket.socket, "connect", forbidden_external_effect)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden_external_effect)
    monkeypatch.setattr(subprocess, "Popen", forbidden_external_effect)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_external_effect)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_external_effect)

    transport.mount_control_mcp(app, host)
    mounted_index = app.router.routes.index(
        next(r for r in app.router.routes if getattr(r, "path", None) == host.app.path)
    )
    spa_index = app.router.routes.index(
        next(r for r in app.router.routes if getattr(r, "path", None) == "/{full_path:path}")
    )
    assert mounted_index < spa_index

    def bearer(client: str) -> str:
        return jwt.encode(
            {
                "iss": verifier.issuer,
                "aud": verifier.resource,
                "sub": "operator-1",
                "client_id": client,
                "scope": "hermes:read",
                "iat": 90,
                "nbf": 90,
                "exp": 200,
                "grant_revision": 3,
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key", "typ": "at+jwt"},
        )

    @asynccontextmanager
    async def sdk_client(client_registration: str):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(
                app=app,
                client=("127.0.0.1", 54000),
            ),
            base_url="https://hermes.invalid",
            headers={"Authorization": "Bearer " + bearer(client_registration)},
        ) as http_client:
            async with streamable_http_client(resource, http_client=http_client) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    yield session

    manager = host.server.session_manager
    try:
        async with app.router.lifespan_context(app):
            assert manager._task_group is not None
            # The OAuth metadata route is also mounted on the real parent and
            # intentionally requires neither dashboard cookies nor a bearer.
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app, client=("127.0.0.1", 54000)),
                base_url="https://hermes.invalid",
            ) as http_client:
                metadata = await http_client.get(host.app.metadata_path)
                assert metadata.status_code == 200
                assert metadata.json()["resource"] == resource
                invalid_origin = await http_client.get(
                    host.app.metadata_path,
                    headers={"Origin": "https://evil.invalid"},
                )
                assert invalid_origin.status_code == 403
                assert invalid_origin.json()["error"] == "invalid_origin"
                dashboard_only = await http_client.get(
                    host.app.path,
                    headers={"X-Hermes-Session-Token": "dashboard-session-only"},
                )
                assert dashboard_only.status_code == 401
                assert dashboard_only.json()["error"] == "invalid_token"
                bound_host = app.state.bound_host
                app.state.bound_host = None
                try:
                    invalid_mcp_host = await http_client.get(
                        host.app.metadata_path,
                        headers={"Host": "attacker.invalid"},
                    )
                finally:
                    app.state.bound_host = bound_host
                assert invalid_mcp_host.status_code == 421
                assert invalid_mcp_host.json()["error"] == "invalid_host"

            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app, client=("127.0.0.1", 54000)),
                base_url="https://attacker.invalid",
            ) as bad_parent_client:
                parent_host_reject = await bad_parent_client.get(host.app.metadata_path)
                assert parent_host_reject.status_code == 400

            async with sdk_client("codex-desktop") as codex:
                names = {tool.name for tool in (await codex.list_tools()).tools}
                assert "hermes_get_routes" in names
                assert "hermes_start_engineering_run" not in names

                capabilities = await codex.call_tool(
                    "hermes_get_capabilities", {"profile_id": "profile-codex"}
                )
                assert capabilities.structured_content["capabilities"]["read"] is True
                assert capabilities.structured_content["capabilities"]["write"] is False

                routes = await codex.call_tool(
                    "hermes_get_routes", {"profile_id": "profile-codex"}
                )
                observed = routes.structured_content
                assert observed["routes"] == [
                    {
                        "slot": "engineering_worker",
                        "provider": "test-provider",
                        "model": "test-worker",
                        "configured_effort": "high",
                    }
                ]
                assert observed["request_sent_routes"] is None
                assert observed["provider_reported_routes"] is None

                runtime = await codex.call_tool(
                    "hermes_get_runtime_status", {"profile_id": "profile-codex"}
                )
                assert runtime.structured_content["state"] == "ABSENT"

                denied = await codex.call_tool(
                    "hermes_get_routes", {"profile_id": "profile-web"}
                )
                assert denied.is_error is True
                assert "resource_denied" in str(denied.content)
            assert manager._server_instances == {}

            async with sdk_client("chatgpt-web") as chatgpt:
                routes = await chatgpt.call_tool(
                    "hermes_get_routes", {"profile_id": "profile-web"}
                )
                assert routes.structured_content["routes"][0]["configured_effort"] == "low"
            assert manager._server_instances == {}
        assert manager._task_group is None
        assert manager._has_started is True
    finally:
        app.router.routes[:] = original_routes
        app.state._state.clear()
        app.state._state.update(original_app_state)

    for home in homes.values():
        assert {path.name for path in home.iterdir()} == {"config.yaml"}


async def _noop_async():
    return None


async def _idle(*_args):
    await asyncio.Event().wait()
