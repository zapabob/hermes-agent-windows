from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Event
from time import monotonic, sleep

import pytest

from downstream.delegation import admission as admission_module
from downstream.delegation.admission import (
    AdmissionGrant,
    AdmissionIntent,
    AdmissionRejection,
    DelegationAdmission,
)
from downstream.delegation.free_routes import (
    FreeRoute,
    FreeRoutePolicy,
    FreeRouteSnapshot,
)
from downstream.delegation.resources import (
    ResourceClaims,
    ResourceRequest,
    ResourceReservationBook,
    ResourceSnapshot,
)

NOW = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)
GiB = 1024**3
READ_TOOLS = frozenset({"read_file", "web_search"})
PARENT_TOOLS = frozenset({"read_file", "web_search", "write_file"})


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
    provider_scope: str = "provider-scope",
) -> FreeRoute:
    return FreeRoute(
        provider=provider,
        provider_scope=provider_scope,
        account_scope="account-scope",
        model_id=model,
        cost_class="VERIFIED_ZERO_PRICE",
        price_source="official_docs_snapshot",
        price_source_url="https://vendor.example/pricing",
        price_version="2026-09-24",
        price_values=(Decimal("0"),),
        price_fetched_at=NOW,
        supported_tools=PARENT_TOOLS,
        entitlement_expires_at=None,
        entitlement_observed_at=None,
        observed_at=NOW,
        observation_age_seconds=0.0,
    )


def _snapshot(
    *,
    account: str = "account-scope",
    provider_scope: str = "provider-scope",
    revision: str = "a" * 64,
):
    routes = tuple(
        _route(provider, model, provider_scope=provider_scope)
        for provider, model in (
            ("vendor-a", "vendor-a/free"),
            ("vendor-b", "vendor-b/free"),
        )
    )
    return FreeRouteSnapshot(
        revision=revision,
        provider_scope=provider_scope,
        account_scope=account,
        created_at=NOW,
        routes=routes,
        validated_in_process=True,
    )


def _resource_snapshot(at: float, *, ram=None, commit=None, cpu=None) -> ResourceSnapshot:
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
    tree: str = "tree-a",
    parent_grant_id: str | None = None,
    tools: frozenset[str] = READ_TOOLS,
    parent_tools: frozenset[str] = PARENT_TOOLS,
    account: str = "account-scope",
    provider_scope: str = "provider-scope",
    queue_timeout: float = 0.0,
    resource_request: ResourceRequest | None = None,
    observed: ResourceSnapshot | None = None,
) -> AdmissionIntent:
    snapshot = _snapshot(account=account, provider_scope=provider_scope)
    return AdmissionIntent(
        request_id=request_id,
        profile_scope="profile-a",
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


def _start(owner: DelegationAdmission, intent: AdmissionIntent) -> AdmissionGrant:
    grant = owner.reserve(intent)
    assert isinstance(grant, AdmissionGrant), f"expected grant, got {grant!r}"
    assert owner.record_writer_outcome(grant.grant_id, "started")
    return grant


def test_two_top_level_and_one_read_only_grandchild_share_tree_and_host_caps():
    clock = _Clock()
    owner = _owner(clock)
    first_parent = _start(owner, _intent("top-one", clock))
    second_parent = _start(owner, _intent("top-two", clock))

    grandchild = owner.reserve(
        _intent("grandchild-one", clock, parent_grant_id=first_parent.grant_id, tools=frozenset({"read_file"}))
    )
    second_grandchild = owner.reserve(
        _intent("grandchild-two", clock, parent_grant_id=second_parent.grant_id, tools=frozenset({"web_search"}))
    )
    third_top = owner.reserve(_intent("top-three", clock, tree="another-tree"))

    assert isinstance(grandchild, AdmissionGrant)
    assert grandchild.depth == 2
    assert grandchild.parent_grant_id == first_parent.grant_id
    assert grandchild.tree_id == first_parent.tree_id
    assert grandchild.profile_scope == first_parent.profile_scope
    assert grandchild.account_scope == first_parent.account_scope
    assert grandchild.read_only is True
    assert owner.record_writer_outcome(grandchild.grant_id, "started")
    depth_three = owner.reserve(
        _intent(
            "depth-three",
            clock,
            parent_grant_id=grandchild.grant_id,
            tools=frozenset({"read_file"}),
        )
    )
    assert isinstance(second_grandchild, AdmissionRejection)
    assert second_grandchild.code in {"nested_capacity", "execution_capacity"}
    assert isinstance(depth_three, AdmissionRejection)
    assert depth_three.code == "maximum_depth"
    assert isinstance(third_top, AdmissionRejection)
    assert third_top.code == "execution_capacity"
    assert len(owner.active_grants()) == 3


def test_nested_child_cannot_expand_parent_tool_scope_or_change_lineage():
    clock = _Clock()
    owner = _owner(clock)
    parent = _start(
        owner,
        _intent("parent-scope", clock, tools=frozenset({"read_file"}), parent_tools=READ_TOOLS),
    )

    expanded = owner.reserve(
        _intent("expanded", clock, parent_grant_id=parent.grant_id, tools=frozenset({"web_search"}))
    )
    wrong_scope = owner.reserve(
        _intent(
            "wrong-account",
            clock,
            parent_grant_id=parent.grant_id,
            tools=frozenset({"read_file"}),
            account="other-account",
        )
    )

    assert isinstance(expanded, AdmissionRejection)
    assert expanded.code == "tool_scope_exceeds_parent"
    assert isinstance(wrong_scope, AdmissionRejection)
    assert wrong_scope.code == "parent_scope_mismatch"


def test_nested_child_cannot_change_provider_scope():
    clock = _Clock()
    owner = _owner(clock)
    parent = _start(owner, _intent("parent-provider-scope", clock))

    result = owner.reserve(
        _intent(
            "alternate-provider-scope",
            clock,
            parent_grant_id=parent.grant_id,
            tools=frozenset({"read_file"}),
            provider_scope="alternate-provider-scope",
        )
    )

    assert isinstance(result, AdmissionRejection)
    assert result.code == "parent_scope_mismatch"


def test_depth_two_rejects_mutating_tools_even_when_parent_has_them():
    clock = _Clock()
    owner = _owner(clock)
    parent = _start(owner, _intent("parent-writer-cap", clock, tools=PARENT_TOOLS, parent_tools=PARENT_TOOLS))

    result = owner.reserve(
        _intent("grandchild-writer", clock, parent_grant_id=parent.grant_id, tools=frozenset({"write_file"}))
    )

    assert isinstance(result, AdmissionRejection)
    assert result.code == "grandchild_tool_not_read_only"


def test_unknown_writer_outcome_blocks_relaunch_and_keeps_resource_reservation():
    clock = _Clock()
    book = ResourceReservationBook()
    owner = _owner(clock, book)
    request = ResourceRequest(
        route="remote", workload="inference", ram_bytes=1 * GiB, commit_bytes=1 * GiB
    )
    observed = _resource_snapshot(100.0, ram=8 * GiB, commit=8 * GiB, cpu=20.0)
    first = owner.reserve(
        _intent("uncertain", clock, resource_request=request, observed=observed)
    )
    assert isinstance(first, AdmissionGrant)
    assert owner.record_writer_outcome(first.grant_id, "unknown")

    retry = owner.reserve(
        _intent("uncertain-retry", clock, resource_request=request, observed=observed)
    )

    assert isinstance(retry, AdmissionRejection)
    assert retry.code == "writer_outcome_unknown"
    assert [grant.grant_id for grant in owner.active_grants()] == [first.grant_id]
    assert book.reserved_claims(now_monotonic=100.0) == ResourceClaims(
        ram_bytes=1 * GiB,
        commit_bytes=1 * GiB,
        cpu_percent=0.0,
        gpu_vram_bytes=(),
    )
    assert owner.resolve_unknown(first.grant_id, terminal_outcome="not_started")
    assert book.reserved_claims(now_monotonic=100.0) == ResourceClaims()


def test_running_writer_timeout_transitions_to_unknown_without_releasing_claims():
    clock = _Clock()
    book = ResourceReservationBook()
    owner = _owner(clock, book)
    request = ResourceRequest(
        route="remote", workload="inference", ram_bytes=1 * GiB, commit_bytes=1 * GiB
    )
    observed = _resource_snapshot(100.0, ram=8 * GiB, commit=8 * GiB, cpu=20.0)
    first = owner.reserve(
        _intent("started-uncertain", clock, resource_request=request, observed=observed)
    )
    assert isinstance(first, AdmissionGrant)
    assert owner.record_writer_outcome(first.grant_id, "started")
    assert owner.record_writer_outcome(first.grant_id, "unknown")

    retry = owner.reserve(
        _intent("started-retry", clock, resource_request=request, observed=observed)
    )
    directly_rejected = book.reserve(
        observed,
        request,
        now_monotonic=100.0,
    )

    assert isinstance(retry, AdmissionRejection)
    assert retry.code == "writer_outcome_unknown"
    assert book.unreconciled_resource_kinds(now_monotonic=100.0) == ("commit", "ram")
    assert directly_rejected.reservation_id is None
    assert directly_rejected.decision.reasons == ("reservation_reconciliation_unknown",)


def test_capacity_wait_has_a_deadline_and_is_counted_while_waiting():
    clock = _Clock(live=True)
    owner = _owner(clock)
    assert isinstance(owner.reserve(_intent("occupied-one", clock)), AdmissionGrant)
    assert isinstance(owner.reserve(_intent("occupied-two", clock, tree="tree-b")), AdmissionGrant)
    queued = Event()

    def wait_for_slot():
        queued.set()
        return owner.reserve(_intent("queued", clock, tree="tree-c", queue_timeout=0.03))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(wait_for_slot)
        assert queued.wait(timeout=1)
        deadline = monotonic() + 1
        while owner.waiting_count == 0 and monotonic() < deadline:
            sleep(0.001)
        assert owner.waiting_count == 1
        result = future.result(timeout=1)

    assert isinstance(result, AdmissionRejection)
    assert result.code == "queue_deadline"
    assert owner.waiting_count == 0


def test_admission_caps_and_unknown_tree_state_are_shared_by_book_owners():
    clock = _Clock()
    book = ResourceReservationBook()
    first_owner = _owner(clock, book)
    second_owner = _owner(clock, book)

    first = first_owner.reserve(_intent("shared-one", clock, tree="tree-a"))
    second = second_owner.reserve(_intent("shared-two", clock, tree="tree-b"))
    third = second_owner.reserve(_intent("shared-three", clock, tree="tree-c"))

    assert isinstance(first, AdmissionGrant)
    assert isinstance(second, AdmissionGrant)
    assert isinstance(third, AdmissionRejection)
    assert third.code == "top_level_capacity"
    assert len(first_owner.active_grants()) == 2
    assert first_owner.active_grants() == second_owner.active_grants()

    assert first_owner.record_writer_outcome(first.grant_id, "unknown")
    retry = second_owner.reserve(_intent("shared-retry", clock, tree="tree-a"))

    assert isinstance(retry, AdmissionRejection)
    assert retry.code == "writer_outcome_unknown"


def test_grandchild_cap_is_shared_by_admission_owners():
    clock = _Clock()
    book = ResourceReservationBook()
    first_owner = _owner(clock, book)
    second_owner = _owner(clock, book)
    first_parent = _start(first_owner, _intent("shared-parent-one", clock, tree="tree-a"))
    second_parent = _start(second_owner, _intent("shared-parent-two", clock, tree="tree-b"))

    first_child = first_owner.reserve(
        _intent(
            "shared-grandchild-one",
            clock,
            tree="tree-a",
            parent_grant_id=first_parent.grant_id,
            tools=frozenset({"read_file"}),
        )
    )
    second_child = second_owner.reserve(
        _intent(
            "shared-grandchild-two",
            clock,
            tree="tree-b",
            parent_grant_id=second_parent.grant_id,
            tools=frozenset({"web_search"}),
        )
    )

    assert isinstance(first_child, AdmissionGrant)
    assert isinstance(second_child, AdmissionRejection)
    assert second_child.code in {"nested_capacity", "execution_capacity"}
    assert len(first_owner.active_grants()) == 3
    assert first_owner.active_grants() == second_owner.active_grants()


@pytest.mark.parametrize("failure_point", ["grant_id", "created_clock"])
def test_grant_creation_exception_releases_resource_reservation(
    failure_point: str, monkeypatch: pytest.MonkeyPatch
):
    clock = _Clock()
    book = ResourceReservationBook()
    request = ResourceRequest(
        route="remote", workload="inference", ram_bytes=GiB, commit_bytes=GiB
    )
    observed = _resource_snapshot(100.0, ram=8 * GiB, commit=8 * GiB, cpu=20.0)
    intent = _intent(
        f"rollback-{failure_point}",
        clock,
        resource_request=request,
        observed=observed,
    )

    if failure_point == "grant_id":
        def fail_grant_id(_size: int) -> str:
            raise RuntimeError("synthetic grant id failure")

        monkeypatch.setattr(admission_module, "token_urlsafe", fail_grant_id)
        owner = _owner(clock, book)
    else:
        calls = 0

        def fail_creation_clock() -> float:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("synthetic creation clock failure")
            return 100.0

        owner = DelegationAdmission(
            book,
            monotonic_clock=fail_creation_clock,
            utc_clock=clock.utc,
        )

    with pytest.raises(RuntimeError):
        owner.reserve(intent)

    assert owner.active_grants() == ()
    assert book.reserved_claims(now_monotonic=100.0) == ResourceClaims()
