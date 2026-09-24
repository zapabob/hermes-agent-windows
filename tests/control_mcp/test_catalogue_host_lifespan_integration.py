"""The existing Control MCP manager and catalogue host share Desktop lifespan."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from downstream.control_mcp.transport import ControlMCPHost
from downstream.delegation import free_routes


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh_enabled", [False, True], ids=["opt-out", "opt-in"])
async def test_control_manager_and_catalogue_host_share_desktop_lifespan(
    monkeypatch, tmp_path, control_module, refresh_enabled
):
    from gateway import code_skew
    from hermes_cli import model_catalog, web_server
    import hermes_constants

    application = web_server.app
    original_state = dict(application.state._state)
    original_routes = list(application.router.routes)
    profile_home = tmp_path / "profile"
    cache_path = profile_home / "cache" / "free-routes.json"
    fetch_started = threading.Event()
    adapter_calls: list[str] = []
    starts: list[object | None] = []
    stops: list[object | None] = []

    class NoNetworkAdapter:
        def __init__(self, *, account_scope, allowed_model_ids):
            self.account_scope = account_scope
            self.allowed_model_ids = allowed_model_ids

        def __call__(self, _etag):
            adapter_calls.append(self.account_scope)
            fetch_started.set()
            return free_routes.FreeRouteFetchResult(status_code=503)

    real_start = free_routes.start_free_route_catalogue_refresh_host
    real_stop = free_routes.stop_free_route_catalogue_refresh_host

    def tracked_start():
        lease = real_start()
        starts.append(lease)
        return lease

    def tracked_stop(lease):
        stops.append(lease)
        real_stop(lease)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    service = control_module("service").HostControlService(
        source=SimpleNamespace(), clock=lambda: 100
    )
    startup = control_module("startup")
    config = startup.ControlMCPStartupConfig(
        service=service,
        issuer="https://issuer.invalid",
        resource="https://hermes.invalid/api/control/mcp",
        public_keys={"key-1": public_key},
        grant_lookup=lambda _subject, _client: None,
        allowed_hosts=("hermes.invalid",),
        allowed_origins=("https://chatgpt.com",),
        clock=lambda: 100,
    )
    control_host = startup.build_control_mcp_host(config)

    monkeypatch.setattr(
        model_catalog,
        "_load_catalog_config",
        lambda: {
            "enabled": True,
            "providers": {
                "openrouter": {"free_route_catalogue_enabled": refresh_enabled}
            },
        },
    )
    monkeypatch.setattr(
        model_catalog, "get_cached_curated_openrouter_model_ids", lambda: frozenset({"vendor/approved"})
    )
    monkeypatch.setattr(model_catalog, "free_route_cache_path", lambda: cache_path)
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: profile_home)
    monkeypatch.setattr(free_routes, "OpenRouterFreeRouteAdapter", NoNetworkAdapter)
    monkeypatch.setattr(free_routes, "start_free_route_catalogue_refresh_host", tracked_start)
    monkeypatch.setattr(free_routes, "stop_free_route_catalogue_refresh_host", tracked_stop)

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

    try:
        application.state.control_mcp_host = control_host
        application.state._state.pop("control_mcp_startup_config", None)
        application.state._state.pop("_control_mcp_startup_config", None)

        async with web_server._lifespan(application):
            assert application.state.control_mcp_host is control_host
            assert isinstance(control_host, ControlMCPHost)
            assert len(starts) == 1
            catalogue_lease = starts[0]
            if refresh_enabled:
                assert catalogue_lease is not None
                assert await asyncio.to_thread(fetch_started.wait, 2.0)
            else:
                assert catalogue_lease is None
                assert not fetch_started.is_set()

            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=application),
                base_url="http://hermes.invalid",
            ) as client:
                ready = await client.get("/api/health")
            assert ready.status_code == 200
            assert ready.json()["ok"] is True
    finally:
        application.router.routes[:] = original_routes
        application.state._state.clear()
        application.state._state.update(original_state)

    assert stops == starts
    if refresh_enabled:
        assert len(adapter_calls) == 1
        assert starts[0]._released is True
        assert starts[0].host.is_running is False
    else:
        assert adapter_calls == []
