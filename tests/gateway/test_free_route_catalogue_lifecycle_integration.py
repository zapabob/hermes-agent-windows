"""Gateway lifecycle joins the profile-owned catalogue host without leaks."""

from __future__ import annotations

import asyncio
import threading

import pytest

from downstream.delegation import free_routes


def _enable_local_catalogue(monkeypatch, tmp_path, fetch_started):
    from hermes_cli import model_catalog
    import hermes_constants

    profile_home = tmp_path / "profile"
    cache_path = profile_home / "cache" / "free-routes.json"
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: profile_home)
    monkeypatch.setattr(
        model_catalog,
        "_load_catalog_config",
        lambda: {
            "enabled": True,
            "providers": {"openrouter": {"free_route_catalogue_enabled": True}},
        },
    )
    monkeypatch.setattr(
        model_catalog,
        "get_cached_curated_openrouter_model_ids",
        lambda: frozenset({"vendor/approved"}),
    )
    monkeypatch.setattr(model_catalog, "free_route_cache_path", lambda: cache_path)

    class NoNetworkAdapter:
        def __init__(self, *, account_scope, allowed_model_ids):
            self.account_scope = account_scope
            self.allowed_model_ids = allowed_model_ids

        def __call__(self, _etag):
            fetch_started.set()
            return free_routes.FreeRouteFetchResult(status_code=503)

    monkeypatch.setattr(free_routes, "OpenRouterFreeRouteAdapter", NoNetworkAdapter)
    return profile_home


@pytest.mark.asyncio
async def test_gateway_start_stop_shares_one_profile_host_with_desktop(
    monkeypatch, tmp_path
):
    from gateway.config import GatewayConfig
    from gateway.run import GatewayRunner

    fetch_started = threading.Event()
    profile_home = _enable_local_catalogue(monkeypatch, tmp_path, fetch_started)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    real_start = free_routes.start_free_route_catalogue_refresh_host
    real_stop = free_routes.stop_free_route_catalogue_refresh_host
    leases = []
    released = []

    def tracked_start():
        lease = real_start()
        leases.append(lease)
        return lease

    def tracked_stop(lease):
        released.append(lease)
        real_stop(lease)

    monkeypatch.setattr(free_routes, "start_free_route_catalogue_refresh_host", tracked_start)
    monkeypatch.setattr(free_routes, "stop_free_route_catalogue_refresh_host", tracked_stop)

    runner = None
    runner_stopped = False
    gateway_lease = None
    desktop_lease = tracked_start()
    try:
        assert desktop_lease is not None
        assert await asyncio.to_thread(fetch_started.wait, 2.0)

        runner = GatewayRunner(GatewayConfig(sessions_dir=tmp_path / "sessions"))
        await runner.start()
        gateway_lease = runner._free_route_catalogue_host
        assert gateway_lease is not None
        assert gateway_lease is not desktop_lease
        assert gateway_lease.host is desktop_lease.host
        assert len(leases) == 2

        await runner.stop()
        runner_stopped = True
        assert runner._free_route_catalogue_host is None
        assert released == [gateway_lease]
        assert desktop_lease.host.is_running

        # A repeated runner stop has no lease left to release.
        runner._stop_free_route_catalogue_refresh_host()
        assert released == [gateway_lease]
    finally:
        try:
            if runner is not None and not runner_stopped:
                await runner.stop()
        finally:
            if not desktop_lease._released:
                tracked_stop(desktop_lease)

    assert released == [gateway_lease, desktop_lease]
    assert desktop_lease.host.is_running is False


def test_gateway_catalogue_helpers_do_not_leak_or_double_release_on_failures(
    monkeypatch,
):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    stop_calls = []

    def fail_start():
        raise RuntimeError("test start failure")

    monkeypatch.setattr(free_routes, "start_free_route_catalogue_refresh_host", fail_start)
    runner._start_free_route_catalogue_refresh_host()
    assert getattr(runner, "_free_route_catalogue_host", None) is None
    runner._stop_free_route_catalogue_refresh_host()
    assert stop_calls == []

    sentinel = object()

    def fail_stop(lease):
        stop_calls.append(lease)
        raise RuntimeError("test stop failure")

    monkeypatch.setattr(free_routes, "stop_free_route_catalogue_refresh_host", fail_stop)
    runner._free_route_catalogue_host = sentinel
    runner._stop_free_route_catalogue_refresh_host()
    assert runner._free_route_catalogue_host is None
    runner._stop_free_route_catalogue_refresh_host()
    assert stop_calls == [sentinel]
