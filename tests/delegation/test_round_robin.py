from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier
from time import monotonic, sleep

from downstream.delegation.admission import (
    AdmissionGrant,
    AdmissionIntent,
    AdmissionRejection,
    DelegationAdmission,
)
from downstream.delegation.free_routes import (
    FreeRoute,
    FreeRouteCostClass,
    FreeRoutePolicy,
    FreeRouteSnapshot,
)
from downstream.delegation.resources import (
    ResourceClaims,
    ResourcePolicy,
    ResourceRequest,
    ResourceReservationBook,
    ResourceSnapshot,
)

NOW = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)
TOOLS = frozenset({"read_file"})
GiB = 1024**3


class _Clock:
    def __init__(self, value: float = 100.0, *, live: bool = False) -> None:
        self.value = value
        self.live = live

    def monotonic(self) -> float:
        return monotonic() if self.live else self.value

    def utc(self) -> datetime:
        return NOW


def _route(
    provider: str,
    model: str,
    *,
    tools: frozenset[str] = TOOLS,
    cost_class: FreeRouteCostClass = "VERIFIED_ZERO_PRICE",
) -> FreeRoute:
    return FreeRoute(
        provider=provider,
        provider_scope="provider-scope",
        account_scope="account-scope",
        model_id=model,
        cost_class=cost_class,
        price_source="official_docs_snapshot",
        price_source_url="https://vendor.example/pricing",
        price_version="2026-09-24",
        price_values=(Decimal("0"),),
        price_fetched_at=NOW,
        supported_tools=tools,
        entitlement_expires_at=None,
        entitlement_observed_at=None,
        observed_at=NOW,
        observation_age_seconds=0.0,
    )


def _snapshot(*routes: FreeRoute, revision: str = "a" * 64) -> FreeRouteSnapshot:
    return FreeRouteSnapshot(
        revision=revision,
        provider_scope="provider-scope",
        account_scope="account-scope",
        created_at=NOW,
        routes=tuple(routes),
        validated_in_process=True,
    )


def _resource_snapshot(
    at: float,
    *,
    ram: int | None = None,
    commit: int | None = None,
    cpu: float | None = None,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        observed_at_monotonic=at,
        ram_total_bytes=None,
        ram_available_bytes=ram,
        commit_limit_bytes=None,
        commit_available_bytes=commit,
        cpu_busy_percent=cpu,
        gpus=(),
    )


def _owner(clock: _Clock, book: ResourceReservationBook | None = None) -> DelegationAdmission:
    return DelegationAdmission(
        book or ResourceReservationBook(),
        monotonic_clock=clock.monotonic,
        utc_clock=clock.utc,
    )


def _intent(
    request_id: str,
    clock: _Clock,
    *,
    routes: tuple[FreeRoute, ...] | None = None,
    revision: str = "a" * 64,
    profile: str = "profile-a",
    account: str = "account-scope",
    tree: str = "tree-a",
    parent_grant_id: str | None = None,
    parent_tools: frozenset[str] = TOOLS,
    tools: frozenset[str] = TOOLS,
    resource_request: ResourceRequest | None = None,
    observed: ResourceSnapshot | None = None,
    queue_timeout: float = 0.0,
) -> AdmissionIntent:
    candidates = routes or (
        _route("vendor-a", "vendor-a/free", tools=tools),
        _route("vendor-b", "vendor-b/free", tools=tools),
    )
    snapshot = _snapshot(*candidates, revision=revision)
    return AdmissionIntent(
        request_id=request_id,
        profile_scope=profile,
        account_scope=account,
        tree_id=tree,
        parent_grant_id=parent_grant_id,
        parent_tool_scope=parent_tools if parent_grant_id is None else frozenset(),
        tool_scope=tools,
        route_snapshot=snapshot,
        route_policy=FreeRoutePolicy(
            provider_scope=snapshot.provider_scope,
            account_scope=snapshot.account_scope,
            required_tools=tools,
        ),
        resource_snapshot=observed or _resource_snapshot(clock.monotonic()),
        resource_request=resource_request or ResourceRequest(route="remote", workload="inference"),
        queue_timeout_seconds=queue_timeout,
    )


def test_first_admission_returns_a_grant_pinned_to_the_verified_free_route():
    clock = _Clock()
    owner = _owner(clock)

    result = owner.reserve(_intent("request-1", clock))

    assert isinstance(result, AdmissionGrant), f"expected a verified route grant, got {result!r}"
    assert result.model_id == "vendor-a/free"
    assert result.route_revision == "a" * 64
    assert result.profile_scope == "profile-a"
    assert result.account_scope == "account-scope"
    assert result.tool_scope == TOOLS
    assert result.read_only is True
    assert result.soft_deadline_monotonic == 280.0
    assert result.idle_deadline_monotonic == 160.0
    assert result.hard_deadline_monotonic == 340.0


def test_new_admissions_rotate_fairly_across_fresh_free_routes():
    clock = _Clock()
    owner = _owner(clock)
    models = []

    for number in range(3):
        result = owner.reserve(_intent(f"round-robin-{number}", clock))
        assert isinstance(result, AdmissionGrant)
        models.append(result.model_id)
        assert owner.record_writer_outcome(result.grant_id, "not_started")

    assert models == ["vendor-a/free", "vendor-b/free", "vendor-a/free"]


def test_paid_and_unknown_routes_are_not_used_as_a_fallback():
    clock = _Clock()
    owner = _owner(clock)
    paid = _route("vendor-paid", "vendor-paid/model", cost_class="PAID")
    unknown = _route("vendor-unknown", "vendor-unknown/model", cost_class="UNKNOWN")

    result = owner.reserve(_intent("no-fallback", clock, routes=(paid, unknown)))

    assert isinstance(result, AdmissionRejection)
    assert result.code == "no_eligible_free_route"
    assert owner.active_grants() == ()


def test_rate_limit_cools_every_alias_and_bounds_retry_after():
    clock = _Clock()
    owner = _owner(clock)
    tools = TOOLS
    aliases = (
        _route("vendor-a", "vendor-a/alias-one", tools=tools),
        _route("vendor-a", "vendor-a/alias-two", tools=tools),
        _route("vendor-b", "vendor-b/free", tools=tools),
    )
    first = owner.reserve(_intent("rate-limit-first", clock, routes=aliases))
    assert isinstance(first, AdmissionGrant)
    assert first.model_id == "vendor-a/alias-one"
    assert owner.record_writer_outcome(first.grant_id, "started")

    backoff = owner.report_rate_limit(first.grant_id, retry_after_seconds=1e300)
    next_grant = owner.reserve(_intent("rate-limit-next", clock, routes=aliases))

    assert backoff.code == "rate_limited"
    assert backoff.retry_after_seconds == 7 * 24 * 60 * 60
    assert isinstance(next_grant, AdmissionGrant)
    assert next_grant.provider == "vendor-b"
    assert next_grant.model_id == "vendor-b/free"


def test_competing_resource_reservations_are_atomic_through_one_admission_owner():
    clock = _Clock()
    book = ResourceReservationBook(
        ResourcePolicy(min_ram_available_bytes=2 * GiB, min_commit_available_bytes=2 * GiB)
    )
    owner = _owner(clock, book)
    observed = _resource_snapshot(100.0, ram=8 * GiB, commit=8 * GiB, cpu=20.0)
    request = ResourceRequest(
        route="remote", workload="inference", ram_bytes=4 * GiB, commit_bytes=4 * GiB
    )
    barrier = Barrier(2)

    def compete(number: int):
        intent = _intent(
            f"resource-race-{number}",
            clock,
            tree=f"tree-{number}",
            resource_request=request,
            observed=observed,
        )
        barrier.wait()
        return owner.reserve(intent)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, range(2)))

    assert sum(isinstance(result, AdmissionGrant) for result in results) == 1
    assert sum(isinstance(result, AdmissionRejection) for result in results) == 1
    assert book.reserved_claims(now_monotonic=100.0) == ResourceClaims(
        ram_bytes=4 * GiB,
        commit_bytes=4 * GiB,
        cpu_percent=0.0,
        gpu_vram_bytes=(),
    )
