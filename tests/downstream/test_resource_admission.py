"""Contracts for conservative workstation admission of delegated work."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from subprocess import CompletedProcess, DEVNULL, TimeoutExpired
from threading import Barrier
from types import SimpleNamespace

from downstream.platform.windows.gpu import (
    NvidiaGpuProbeResult,
    NvidiaGpuTelemetry,
    query_nvidia_gpu_telemetry,
)
from downstream.delegation.resources import (
    GpuResourceSnapshot,
    ResourceClaims,
    ResourcePolicy,
    ResourceReflection,
    ResourceRequest,
    ResourceReservationBook,
    ResourceSnapshot,
    ResourceSnapshotCollector,
    admit_resources,
)


GiB = 1024**3
MiB = 1024**2


def snapshot(
    *,
    at: float = 100.0,
    ram_total: int | None = 32 * GiB,
    ram_available: int | None = 16 * GiB,
    commit_limit: int | None = 64 * GiB,
    commit_available: int | None = 32 * GiB,
    cpu: float | None = 20.0,
    gpus: tuple[GpuResourceSnapshot, ...] | None = None,
) -> ResourceSnapshot:
    if gpus is None:
        gpus = (
            GpuResourceSnapshot(
                uuid="GPU-test-001",
                free_vram_bytes=8 * GiB,
                local_resident_bytes=2 * GiB,
                observed_at_monotonic=at,
            ),
        )
    return ResourceSnapshot(
        observed_at_monotonic=at,
        ram_total_bytes=ram_total,
        ram_available_bytes=ram_available,
        commit_limit_bytes=commit_limit,
        commit_available_bytes=commit_available,
        cpu_busy_percent=cpu,
        gpus=gpus,
    )


def local_request(
    *,
    workload: str = "inference",
    ram: int = 1 * GiB,
    commit: int = 1 * GiB,
    cpu: float = 10.0,
    gpu_uuid: str | None = "GPU-test-001",
    vram: int = 1 * GiB,
) -> ResourceRequest:
    return ResourceRequest(
        route="local",
        workload=workload,  # type: ignore[arg-type]
        ram_bytes=ram,
        commit_bytes=commit,
        cpu_percent=cpu,
        gpu_uuid=gpu_uuid,
        vram_bytes=vram,
    )


def test_stale_gpu_denies_local_compute_but_not_remote_read() -> None:
    stale_gpu = GpuResourceSnapshot(
        uuid="GPU-test-001",
        free_vram_bytes=8 * GiB,
        local_resident_bytes=2 * GiB,
        observed_at_monotonic=90.0,
    )
    policy = ResourcePolicy(max_gpu_age_seconds=5.0)

    local = admit_resources(
        snapshot(gpus=(stale_gpu,)),
        local_request(),
        policy,
        now_monotonic=100.0,
    )
    remote_read = admit_resources(
        snapshot(gpus=None, ram_available=None, commit_available=None, cpu=None),
        ResourceRequest(route="remote", workload="read"),
        policy,
        now_monotonic=100.0,
    )

    assert not local.admitted
    assert "gpu_telemetry_stale" in local.reasons
    assert remote_read.admitted
    assert remote_read.reasons == ()


def test_missing_host_telemetry_fails_closed_for_local_compute() -> None:
    incomplete = snapshot(ram_available=None, commit_available=None, cpu=None)

    decision = admit_resources(
        incomplete, local_request(gpu_uuid=None, vram=0), now_monotonic=100.0
    )

    assert not decision.admitted
    assert {"ram_telemetry_missing", "commit_telemetry_missing", "cpu_telemetry_missing"}.issubset(
        set(decision.reasons)
    )


def test_competing_reservations_are_atomic_and_cannot_overbook_ram() -> None:
    observed = snapshot(ram_available=8 * GiB, commit_available=8 * GiB, gpus=())
    request = local_request(ram=4 * GiB, commit=4 * GiB, gpu_uuid=None, vram=0)
    book = ResourceReservationBook(
        ResourcePolicy(min_ram_available_bytes=2 * GiB, min_commit_available_bytes=2 * GiB)
    )
    barrier = Barrier(2)

    def compete() -> bool:
        barrier.wait()
        return book.reserve(observed, request, now_monotonic=100.0).reservation_id is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: compete(), range(2)))

    assert sorted(outcomes) == [False, True]
    assert book.reserved_claims() == ResourceClaims(
        ram_bytes=4 * GiB,
        commit_bytes=4 * GiB,
        cpu_percent=10.0,
        gpu_vram_bytes=(),
    )


def test_suspended_child_reservation_remains_charged_until_explicit_release() -> None:
    observed = snapshot(ram_available=8 * GiB, commit_available=8 * GiB, gpus=())
    request = local_request(ram=4 * GiB, commit=4 * GiB, gpu_uuid=None, vram=0)
    book = ResourceReservationBook(
        ResourcePolicy(min_ram_available_bytes=2 * GiB, min_commit_available_bytes=2 * GiB)
    )

    child = book.reserve(observed, request, now_monotonic=100.0)
    suspended_snapshot = book.reserved_claims()
    contender = book.reserve(observed, request, now_monotonic=101.0)

    assert child.reservation_id is not None
    assert suspended_snapshot.ram_bytes == 4 * GiB
    assert contender.reservation_id is None
    assert not contender.decision.admitted
    assert book.release(child.reservation_id)
    assert book.reserved_claims().ram_bytes == 0


def test_reservation_book_has_a_bounded_active_entry_count() -> None:
    observed = snapshot(ram_available=16 * GiB, commit_available=16 * GiB, gpus=())
    request = local_request(gpu_uuid=None, vram=0)
    book = ResourceReservationBook(ResourcePolicy(max_active_reservations=1))

    first = book.reserve(observed, request, now_monotonic=100.0)
    second = book.reserve(observed, request, now_monotonic=100.0)

    assert first.reservation_id is not None
    assert second.reservation_id is None
    assert second.decision.reasons == ("reservation_limit",)


def test_embedding_allocation_is_reserved_after_admission() -> None:
    observed = snapshot(
        ram_available=12 * GiB,
        commit_available=12 * GiB,
        gpus=(
            GpuResourceSnapshot(
                uuid="GPU-test-001",
                free_vram_bytes=8 * GiB,
                local_resident_bytes=2 * GiB,
                observed_at_monotonic=100.0,
            ),
        ),
    )
    embedding = local_request(
        workload="embedding", ram=2 * GiB, commit=2 * GiB, vram=3 * GiB
    )
    book = ResourceReservationBook(
        ResourcePolicy(
            min_ram_available_bytes=2 * GiB,
            min_commit_available_bytes=2 * GiB,
            min_gpu_free_vram_bytes=2 * GiB,
        )
    )

    admitted = book.reserve(observed, embedding, now_monotonic=100.0)
    following = book.reserve(
        observed,
        local_request(ram=1 * GiB, commit=1 * GiB, vram=4 * GiB),
        now_monotonic=100.0,
    )

    assert admitted.reservation_id is not None
    assert book.reserved_claims().vram_bytes == 3 * GiB
    assert not following.decision.admitted
    assert "gpu_vram_low" in following.decision.reasons


def test_reflected_running_claim_is_not_subtracted_again_from_free_counters() -> None:
    policy = ResourcePolicy(
        min_ram_available_bytes=3 * GiB,
        min_commit_available_bytes=3 * GiB,
        min_gpu_free_vram_bytes=int(2.5 * GiB),
        max_cpu_busy_percent=65.0,
        resume_cpu_busy_percent=55.0,
    )
    book = ResourceReservationBook(policy)
    before_start = snapshot(
        ram_available=8 * GiB,
        commit_available=8 * GiB,
        cpu=20.0,
        gpus=(
            GpuResourceSnapshot(
                uuid="GPU-test-001",
                free_vram_bytes=6 * GiB,
                local_resident_bytes=0,
                observed_at_monotonic=100.0,
            ),
        ),
    )
    running = book.reserve(
        before_start,
        local_request(ram=2 * GiB, commit=2 * GiB, cpu=20.0, vram=2 * GiB),
        now_monotonic=100.0,
    )
    assert running.reservation_id is not None
    assert book.mark_started(running.reservation_id)
    assert book.reconcile(
        running.reservation_id,
        ResourceReflection(
            ram_bytes=2 * GiB,
            commit_bytes=2 * GiB,
            cpu_percent=20.0,
            gpu_vram_bytes=(("GPU-test-001", 2 * GiB),),
            observed_at_monotonic=101.0,
            gpu_observed_at_monotonic=101.0,
        ),
    )

    after_start = snapshot(
        at=101.0,
        ram_available=6 * GiB,
        commit_available=6 * GiB,
        cpu=40.0,
        gpus=(
            GpuResourceSnapshot(
                uuid="GPU-test-001",
                free_vram_bytes=4 * GiB,
                local_resident_bytes=2 * GiB,
                observed_at_monotonic=101.0,
            ),
        ),
    )
    pending = book.reserve(
        after_start,
        local_request(ram=2 * GiB, commit=2 * GiB, cpu=10.0, vram=1 * GiB),
        now_monotonic=101.0,
    )

    assert pending.reservation_id is not None
    assert pending.decision.admitted
    assert book.reserved_claims(now_monotonic=101.0) == ResourceClaims(
        ram_bytes=2 * GiB,
        commit_bytes=2 * GiB,
        cpu_percent=10.0,
        gpu_vram_bytes=(("GPU-test-001", 1 * GiB),),
    )


def test_suspended_started_claim_uses_fresh_observation_and_is_not_released() -> None:
    policy = ResourcePolicy(min_ram_available_bytes=2 * GiB, min_commit_available_bytes=2 * GiB)
    book = ResourceReservationBook(policy)
    request = local_request(ram=4 * GiB, commit=4 * GiB, cpu=10.0, gpu_uuid=None, vram=0)
    initial = snapshot(ram_available=16 * GiB, commit_available=16 * GiB, gpus=())
    child = book.reserve(initial, request, now_monotonic=100.0)
    assert child.reservation_id is not None
    assert book.mark_started(child.reservation_id)
    assert book.reconcile(
        child.reservation_id,
        ResourceReflection(
            ram_bytes=4 * GiB,
            commit_bytes=4 * GiB,
            cpu_percent=10.0,
            gpu_vram_bytes=(),
            observed_at_monotonic=101.0,
        ),
    )

    # A suspended child may have most of its working set paged out while its
    # reservation remains live; only current working-set bytes are reflected.
    assert book.reconcile(
        child.reservation_id,
        ResourceReflection(
            ram_bytes=1 * GiB,
            commit_bytes=4 * GiB,
            cpu_percent=0.0,
            gpu_vram_bytes=(),
            observed_at_monotonic=102.0,
        ),
    )

    remaining = book.reserved_claims(now_monotonic=102.0)
    assert remaining == ResourceClaims(ram_bytes=3 * GiB, cpu_percent=10.0)
    contender = book.reserve(
        snapshot(at=102.0, ram_available=8 * GiB, commit_available=8 * GiB, gpus=()),
        local_request(ram=4 * GiB, commit=4 * GiB, cpu=5.0, gpu_uuid=None, vram=0),
        now_monotonic=102.0,
    )
    assert contender.reservation_id is None
    assert "ram_capacity_low" in contender.decision.reasons
    assert book.release(child.reservation_id)


def test_started_claim_with_unknown_reconciliation_fails_closed_and_is_explained() -> None:
    book = ResourceReservationBook()
    initial = snapshot(ram_available=16 * GiB, commit_available=16 * GiB, gpus=())
    child = book.reserve(initial, local_request(gpu_uuid=None, vram=0), now_monotonic=100.0)
    assert child.reservation_id is not None
    assert book.mark_started(child.reservation_id)
    assert book.unreconciled_resource_kinds(now_monotonic=101.0) == (
        "commit",
        "cpu",
        "ram",
    )

    blocked = book.reserve(
        initial,
        local_request(gpu_uuid=None, vram=0),
        now_monotonic=101.0,
    )
    remote_read = book.reserve(
        snapshot(at=101.0, ram_available=None, commit_available=None, cpu=None, gpus=None),
        ResourceRequest(route="remote", workload="read"),
        now_monotonic=101.0,
    )

    assert blocked.reservation_id is None
    assert "reservation_reconciliation_unknown" in blocked.decision.reasons
    assert remote_read.decision.admitted

    assert book.reconcile(
        child.reservation_id,
        ResourceReflection(
            ram_bytes=0,
            commit_bytes=0,
            cpu_percent=0.0,
            gpu_vram_bytes=(),
            observed_at_monotonic=90.0,
        ),
    )
    stale = book.reserve(
        initial,
        local_request(gpu_uuid=None, vram=0),
        now_monotonic=101.0,
    )
    assert stale.reservation_id is None
    assert "reservation_reconciliation_unknown" in stale.decision.reasons

    assert book.reconcile(
        child.reservation_id,
        ResourceReflection(
            ram_bytes=0,
            commit_bytes=0,
            cpu_percent=0.0,
            gpu_vram_bytes=(),
            observed_at_monotonic=101.0,
        ),
    )
    assert book.unreconciled_resource_kinds(now_monotonic=101.0) == ()
    recovered = book.reserve(
        initial,
        local_request(gpu_uuid=None, vram=0),
        now_monotonic=101.0,
    )
    assert recovered.decision.admitted


def test_stale_gpu_reflection_blocks_only_the_claimed_gpu_until_refreshed() -> None:
    book = ResourceReservationBook()
    initial = snapshot(ram_available=16 * GiB, commit_available=16 * GiB)
    request = local_request(ram=1 * GiB, commit=1 * GiB, cpu=5.0, vram=1 * GiB)
    child = book.reserve(initial, request, now_monotonic=100.0)
    assert child.reservation_id is not None
    assert book.mark_started(child.reservation_id)

    stale_gpu = ResourceReflection(
        ram_bytes=1 * GiB,
        commit_bytes=1 * GiB,
        cpu_percent=5.0,
        gpu_vram_bytes=(("GPU-test-001", 1 * GiB),),
        observed_at_monotonic=101.0,
        gpu_observed_at_monotonic=90.0,
    )
    assert book.reconcile(child.reservation_id, stale_gpu)
    assert book.unreconciled_resource_kinds(now_monotonic=101.0) == ("gpu",)

    same_gpu = book.reserve(
        snapshot(at=101.0),
        local_request(ram=1 * GiB, commit=1 * GiB, cpu=5.0, vram=1 * GiB),
        now_monotonic=101.0,
    )
    other_resources = book.reserve(
        snapshot(at=101.0, gpus=()),
        local_request(ram=1 * GiB, commit=1 * GiB, cpu=5.0, gpu_uuid=None, vram=0),
        now_monotonic=101.0,
    )

    assert same_gpu.reservation_id is None
    assert "reservation_reconciliation_unknown" in same_gpu.decision.reasons
    assert other_resources.decision.admitted

    assert book.reconcile(
        child.reservation_id,
        ResourceReflection(
            ram_bytes=1 * GiB,
            commit_bytes=1 * GiB,
            cpu_percent=5.0,
            gpu_vram_bytes=(("GPU-test-001", 1 * GiB),),
            observed_at_monotonic=101.0,
            gpu_observed_at_monotonic=101.0,
        ),
    )
    assert book.unreconciled_resource_kinds(now_monotonic=101.0) == ()


def test_pressure_hysteresis_requires_resume_threshold_before_reopening() -> None:
    policy = ResourcePolicy(max_cpu_busy_percent=90.0, resume_cpu_busy_percent=75.0)
    request = local_request(gpu_uuid=None, vram=0, cpu=10.0)
    high = admit_resources(
        snapshot(cpu=95.0), request, policy, now_monotonic=100.0
    )
    between = admit_resources(
        snapshot(at=101.0, cpu=80.0),
        request,
        policy,
        now_monotonic=101.0,
        active_pressure_reasons=high.active_pressure_reasons,
    )
    recovered = admit_resources(
        snapshot(at=102.0, cpu=70.0),
        request,
        policy,
        now_monotonic=102.0,
        active_pressure_reasons=between.active_pressure_reasons,
    )

    assert not high.admitted
    assert "cpu_pressure" in high.active_pressure_reasons
    assert not between.admitted
    assert "cpu_pressure" in between.active_pressure_reasons
    assert recovered.admitted
    assert recovered.active_pressure_reasons == frozenset()


def test_commit_headroom_is_enforced_even_when_ram_is_available() -> None:
    observed = snapshot(ram_available=16 * GiB, commit_available=3 * GiB, gpus=())
    request = local_request(
        ram=1 * GiB,
        commit=2 * GiB,
        gpu_uuid=None,
        vram=0,
    )
    policy = ResourcePolicy(
        min_ram_available_bytes=2 * GiB,
        min_commit_available_bytes=2 * GiB,
    )

    decision = admit_resources(observed, request, policy, now_monotonic=100.0)

    assert not decision.admitted
    assert "commit_capacity_low" in decision.reasons
    assert "ram_capacity_low" not in decision.reasons


def test_ram_hysteresis_stays_latched_until_headroom_clears_resume_margin() -> None:
    policy = ResourcePolicy(
        min_ram_available_bytes=2 * GiB,
        ram_hysteresis_bytes=1 * GiB,
        min_commit_available_bytes=1 * GiB,
    )
    request = local_request(
        ram=1 * GiB,
        commit=1 * GiB,
        gpu_uuid=None,
        vram=0,
    )
    low = admit_resources(
        snapshot(ram_available=int(1.5 * GiB), commit_available=8 * GiB, gpus=()),
        request,
        policy,
        now_monotonic=100.0,
    )
    recovering = admit_resources(
        snapshot(
            at=101.0,
            ram_available=int(2.5 * GiB),
            commit_available=8 * GiB,
            gpus=(),
        ),
        request,
        policy,
        now_monotonic=101.0,
        active_pressure_reasons=low.active_pressure_reasons,
    )
    healthy = admit_resources(
        snapshot(
            at=102.0,
            ram_available=int(3.1 * GiB),
            commit_available=8 * GiB,
            gpus=(),
        ),
        request,
        policy,
        now_monotonic=102.0,
        active_pressure_reasons=recovering.active_pressure_reasons,
    )

    assert not low.admitted
    assert "ram_pressure" in low.active_pressure_reasons
    assert not recovering.admitted
    assert "ram_pressure" in recovering.active_pressure_reasons
    assert healthy.admitted
    assert "ram_pressure" not in healthy.active_pressure_reasons


def test_snapshot_collector_keeps_unknowns_explicit_and_cpu_probe_nonblocking() -> None:
    cpu_values = iter((0.0, 23.5))
    cpu_intervals: list[float | None] = []
    psutil_stub = SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(total=64 * GiB, available=18 * GiB),
        cpu_percent=lambda *, interval: (cpu_intervals.append(interval), next(cpu_values))[1],
    )
    gpu_probe_calls: list[tuple[int, ...] | None] = []

    def gpu_provider(*, local_process_ids: tuple[int, ...] | None) -> NvidiaGpuProbeResult:
        gpu_probe_calls.append(local_process_ids)
        return NvidiaGpuProbeResult(
            devices=(
                NvidiaGpuTelemetry(
                    uuid="GPU-test-001",
                    free_vram_bytes=6 * GiB,
                    local_resident_bytes=2 * GiB,
                    observed_at_monotonic=101.0,
                ),
            ),
            observed_at_monotonic=101.0,
        )

    clock_values = iter((100.5, 101.0, 101.5, 102.0))
    collector = ResourceSnapshotCollector(
        psutil_module=psutil_stub,
        commit_provider=lambda: (96 * GiB, 22 * GiB),
        gpu_provider=gpu_provider,
        local_pid_provider=lambda: (5001,),
        monotonic_clock=lambda: next(clock_values),
        platform_name="win32",
    )

    first = collector.collect()
    second = collector.collect()

    assert first.ram_available_bytes == 18 * GiB
    assert first.commit_limit_bytes == 96 * GiB
    assert first.commit_available_bytes == 22 * GiB
    assert first.cpu_busy_percent is None
    assert "cpu_first_sample" in first.errors
    assert second.cpu_busy_percent == 23.5
    assert second.gpus is not None
    assert second.gpus[0].local_resident_bytes == 2 * GiB
    assert second.gpus[0].telemetry_age_seconds(102.0) == 1.0
    assert cpu_intervals == [None, None]
    assert gpu_probe_calls == [(5001,), (5001,)]


def test_unavailable_local_residency_is_not_coerced_to_zero_or_admitted() -> None:
    collector = ResourceSnapshotCollector(
        psutil_module=SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(total=32 * GiB, available=16 * GiB),
            cpu_percent=lambda *, interval: 25.0,
        ),
        commit_provider=lambda: (64 * GiB, 32 * GiB),
        gpu_provider=lambda *, local_process_ids: NvidiaGpuProbeResult(
            devices=(
                NvidiaGpuTelemetry(
                    uuid="GPU-test-001",
                    free_vram_bytes=8 * GiB,
                    local_resident_bytes=None,
                    observed_at_monotonic=100.0,
                ),
            ),
            observed_at_monotonic=100.0,
            residency_error="gpu_local_residency_unavailable",
        ),
        monotonic_clock=lambda: 100.0,
        platform_name="win32",
    )
    observed = collector.collect()

    decision = admit_resources(observed, local_request(), now_monotonic=100.0)

    assert observed.gpus is not None
    assert observed.gpus[0].local_resident_bytes is None
    assert not decision.admitted
    assert "gpu_local_residency_unknown" in decision.reasons


def test_collector_rejects_unbounded_local_pid_iterables_without_iteration() -> None:
    seen_pids: list[tuple[int, ...] | None] = []

    def unbounded_ids():
        raise AssertionError("unbounded PID source must not be iterated")
        yield 123

    def gpu_provider(*, local_process_ids: tuple[int, ...] | None) -> NvidiaGpuProbeResult:
        seen_pids.append(local_process_ids)
        return NvidiaGpuProbeResult(None, None, error="gpu_probe_unavailable")

    collector = ResourceSnapshotCollector(
        psutil_module=SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(total=32 * GiB, available=16 * GiB),
            cpu_percent=lambda *, interval: 30.0,
        ),
        commit_provider=lambda: (64 * GiB, 32 * GiB),
        gpu_provider=gpu_provider,
        local_pid_provider=unbounded_ids,
        monotonic_clock=lambda: 100.0,
        platform_name="win32",
    )

    observed = collector.collect()

    assert seen_pids == [None]
    assert "gpu_local_process_ids_invalid" in observed.errors


def test_collector_does_not_reuse_cpu_average_after_a_long_sampling_gap() -> None:
    cpu_values = iter((0.0, 30.0))
    clock_values = iter((100.0, 101.0, 110.0, 111.0))
    collector = ResourceSnapshotCollector(
        psutil_module=SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(total=32 * GiB, available=16 * GiB),
            cpu_percent=lambda *, interval: next(cpu_values),
        ),
        commit_provider=lambda: (64 * GiB, 32 * GiB),
        gpu_provider=lambda *, local_process_ids: NvidiaGpuProbeResult(
            None, None, error="gpu_probe_unavailable"
        ),
        monotonic_clock=lambda: next(clock_values),
        platform_name="win32",
        max_cpu_sample_window_seconds=5.0,
    )

    first = collector.collect()
    after_gap = collector.collect()

    assert first.cpu_busy_percent is None
    assert after_gap.cpu_busy_percent is None
    assert "cpu_sample_window_too_wide" in after_gap.errors


def test_nvidia_probe_aggregates_only_supplied_local_pids_and_bounds_timeout(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HERMES_TEST_SECRET", "must-not-reach-child")
    monkeypatch.setenv("PATH", "parent-only-secret-path")
    calls: list[tuple[list[str], dict[str, object]]] = []
    outputs = iter(
        (
            "GPU-test-001, 8192\n",
            "GPU-test-001, 5151, 1024\nGPU-test-001, 7171, 4096\nGPU-test-001, 121, 512\n",
        )
    )

    def runner(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, stdout=next(outputs), stderr="sensitive stderr")

    result = query_nvidia_gpu_telemetry(
        local_process_ids=(5151, 121),
        timeout_seconds=900.0,
        executable_lookup=lambda _name: "nvidia-smi",
        runner=runner,
        monotonic_clock=lambda: 50.0,
    )

    assert result.error is None
    assert result.devices is not None
    assert result.devices[0].free_vram_bytes == 8192 * MiB
    assert result.devices[0].local_resident_bytes == 1536 * MiB
    assert len(calls) == 2
    assert all(kwargs["timeout"] == 2.0 for _command, kwargs in calls)
    assert all(kwargs["stdin"] is DEVNULL for _command, kwargs in calls)
    assert calls[0][0] == [
        "nvidia-smi",
        "--query-gpu=uuid,memory.free",
        "--format=csv,noheader,nounits",
    ]
    assert calls[1][0] == [
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid,pid,used_memory",
        "--format=csv,noheader,nounits",
    ]
    for _command, kwargs in calls:
        child_env = kwargs["env"]
        assert isinstance(child_env, dict)
        assert set(child_env).issubset({"PATH", "SystemRoot", "WINDIR"})
        assert "must-not-reach-child" not in repr(child_env)
        assert "parent-only-secret-path" not in repr(child_env)
    assert "5151" not in repr(result) and "121" not in repr(result)
    assert "sensitive stderr" not in repr(result)


def test_nvidia_probe_timeout_returns_only_a_sanitized_error_code() -> None:
    seen_timeout: list[float] = []

    def runner(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        seen_timeout.append(float(kwargs["timeout"]))
        raise TimeoutExpired(command, kwargs["timeout"], stderr="private details")

    result = query_nvidia_gpu_telemetry(
        executable_lookup=lambda _name: "nvidia-smi",
        runner=runner,
        timeout_seconds=0.001,
    )

    assert result.devices is None
    assert result.error == "gpu_probe_timeout"
    assert seen_timeout == [0.1]
    assert "private details" not in repr(result)
