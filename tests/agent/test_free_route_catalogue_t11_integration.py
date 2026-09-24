"""Integration checks between the free-route fetcher and host request budget."""

from __future__ import annotations

import socket
import threading
import time

from downstream.delegation import free_routes
from downstream.delegation.network_budget import RequestBudget, RequestTimeouts


def test_stalled_dns_keeps_real_lease_until_worker_finishes_and_releases_profile_lock(
    monkeypatch, tmp_path
):
    resolver = free_routes._BoundedDNSResolver()
    dns_entered = threading.Event()
    release_dns = threading.Event()
    fetches: list[str | None] = []

    def stalled_getaddrinfo(host, port, *args, **kwargs):
        dns_entered.set()
        if not release_dns.wait(timeout=8):
            raise socket.gaierror("test resolver timed out")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("203.0.113.8", port))
        ]

    monkeypatch.setattr(free_routes, "_OPENROUTER_DNS_RESOLVER", resolver)
    monkeypatch.setattr(free_routes.socket, "getaddrinfo", stalled_getaddrinfo)
    # Keep a lock-regression test bounded while still exercising the real OS
    # lock path and actual network-budget lease.
    monkeypatch.setattr(free_routes, "_FREE_ROUTE_FILE_LOCK_WAIT_SECONDS", 0.2)

    budget = RequestBudget(
        timeouts={
            "catalogue": RequestTimeouts(
                connect_seconds=1.0,
                read_idle_seconds=1.0,
                total_seconds=1.0,
            )
        }
    )
    adapter = free_routes.OpenRouterFreeRouteAdapter(
        account_scope="profile:integration-a",
        allowed_model_ids={"vendor/approved"},
        budget=budget,
    )

    def fetch(etag):
        fetches.append(etag)
        return adapter(etag)

    cache_path = tmp_path / "profile-a" / "cache" / "free-routes.json"
    first_owner = free_routes.FreeRouteCatalogueOwner(
        fetch,
        provider_scope="openrouter:public",
        account_scope="profile:integration-a",
        cache_path=cache_path,
    )

    try:
        started = time.monotonic()
        first_owner.refresh_if_due()
        caller_elapsed = time.monotonic() - started

        assert dns_entered.wait(timeout=2.0)
        assert caller_elapsed < 4.0, "a blocked OS resolver must not hold the refresh caller"
        active = budget.status()
        assert active["active"] == 1
        assert active["requests"][0]["operation"] == "catalogue"
        assert active["requests"][0]["active_workers"] == 1

        # A retry backoff is intentionally stored after the network failure,
        # so probe the profile's actual cache lock directly rather than using
        # a second fetch to infer that it was released.
        with free_routes._free_route_file_lock(cache_path) as acquired:
            assert acquired, "the timed-out DNS worker must not retain the profile cache lock"
        assert len(fetches) == 1
        still_active = budget.status()
        assert still_active["active"] == 1
        assert still_active["requests"][0]["active_workers"] == 1
    finally:
        release_dns.set()
        assert resolver.wait_for_idle(timeout=5.0), "test DNS worker did not terminate"

    assert budget.status()["active"] == 0


def test_real_budget_shares_public_catalogue_cooldown_across_profile_scopes():
    budget = RequestBudget()
    connections: list[object] = []

    class FakeSocket:
        def settimeout(self, _timeout):
            return None

    class RetryResponse:
        status = 429
        headers = {"Retry-After": "60"}

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    class Connection:
        def __init__(self, *, timeout):
            self.sock = FakeSocket()
            self.timeout = timeout
            connections.append(self)

        def connect(self):
            return None

        def request(self, *_args, **_kwargs):
            return None

        def getresponse(self):
            return RetryResponse()

        def close(self):
            return None

    def adapter(profile_scope):
        return free_routes.OpenRouterFreeRouteAdapter(
            account_scope=profile_scope,
            allowed_model_ids={"vendor/approved"},
            budget=budget,
            connection_factory=Connection,
        )

    first = adapter("profile:desktop")
    second = adapter("profile:gateway")

    assert first(None).status_code == 429
    # Profile-local route ownership does not split the provider's public
    # request budget: the second owner observes the first owner's cooldown.
    assert second(None).status_code == 503
    assert len(connections) == 1
    assert budget.status()["active"] == 0
