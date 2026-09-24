# T08 workstation resource observation and admission

## Source and scope

Repository: zapabob/hermes-agent-windows.

Worktree: H:\hermes-control-mcp-t08-resources-20260924.

Branch: codex/t08-resources-h-20260924.

Base: 98e1be6e94bab5cc0d70d4a827f826e3a6a020b2.

Implementation commit: 1e1b9515f6ee8feedf3a6b754cc5cce22110709e.

The commit adds passive host observations, pure admission, bounded NVIDIA probes, and an atomic reservation ledger. It does not connect admission to production delegation or start workloads.

## Design and source decision

ResourceSnapshotCollector reuses psutil for nonblocking host RAM/CPU readings and GlobalMemoryStatusEx for Windows commit headroom. GPU probing lives alongside the existing CUDA visibility helper in downstream/platform/windows/gpu.py; it uses read-only nvidia-smi CSV queries with capped timeouts, rejects outputs over 16 KiB, caps device and PID counts, sanitizes errors, and does not inherit provider credentials. Missing values remain None.

admit_resources is pure and uses explicit request estimates separately from observed host values. Remote reads with no resource claims remain available when local telemetry is missing or stale. Proposed policy thresholds are conservative placeholders and are not calibrated measurements.

ResourceReservationBook serializes decisions and reservations with a lock. Pending claims are subtracted once. When a host lifecycle owner starts a worker, it must provide fresh per-reservation ResourceReflection observations; measured use already represented in the operating-system counters is not subtracted again. The ledger subtracts only the remaining estimate. Missing or stale measurements return the explicit reservation_reconciliation_unknown reason for the affected resource. Other resource dimensions and remote reads remain usable. Reservations persist across suspension until the host owner confirms completion and explicitly releases them.

The collector can aggregate GPU residency for caller-supplied known local process IDs. T08 does not create a separate child lifecycle or per-reservation RAM/commit/CPU producer. CodeGraph and direct symbol search found no production caller for this new API. T10 must bind actual host-owned process measurements to reservations before production admission is enabled.

Docker is not queried or required. No service is restarted, no driver is installed, no model is started, and no stress benchmark is run.

## TDD and verification

The initial public API scaffold avoided ModuleNotFoundError. Its first behavior run produced six assertion failures for unimplemented admission/reservation behavior. After implementation, the initial focused resource and existing Windows GPU contracts passed 49 tests.

The reservation-reflection regression was then added first. Its RED run failed the assertion that a newly started reservation could be marked active because mark_started still returned false. After implementing reflection-aware reconciliation, the running-claim, suspended-child, and unknown-reconciliation tests passed. A later stale-GPU-reflection test checked dimension-specific unknown state and recovery after fresh telemetry.

Final focused command:

    uv run --frozen --extra dev python -m pytest tests/downstream/test_resource_admission.py tests/downstream/test_windows_contracts.py -q

Result: 53 passed in 1.71 seconds. Inputs are synthetic; no hardware calibration is implied.

Static checks:

    uv run --frozen --extra dev ruff check downstream/delegation/resources.py downstream/platform/windows/gpu.py tests/downstream/test_resource_admission.py
    uv run --frozen --extra dev ty check downstream/delegation/resources.py downstream/platform/windows/gpu.py
    git diff --check

All passed.

CodeGraph 1.6.0 sync . exited successfully. The after status showed 8,908 files, 190,696 nodes, 610,392 edges, zero pending changes, zero pending references, and no worktree mismatch. The source fingerprint is the SHA-256 of compact JSON over the ordered CodeGraph file manifest [path, content_hash, size]. Receipts: evidence/codegraph/T08-98e1be-before.json, evidence/codegraph/T08-1e1b9515-after.json, and evidence/codegraph/T08-1e1b9515-after-results.md.

## Review and limits

Self-review checked the CodeGraph impact result against direct rg; the graph's edge to downstream/delegation/inference_port.py::complete was a name-based false positive, and no production references to the new admission API were found. Independent parent/gate review remains pending.

No actual workstation p50/p95 sample was taken while T06/T07 test and index work was active. Real GlobalMemoryStatusEx and nvidia-smi output, idle capacity, active local inference/embedding allocations, and Windows workload admission remain unverified. CPU/RAM/commit/GPU thresholds must be calibrated only after stable passive samples and T10 supplies per-reservation observations. Production admission stays unwired.

If a started reservation cannot be reconciled, the caller sees an explicit unknown-resource status and relevant new local work fails closed. There is no automatic timeout release: only the existing host lifecycle owner can refresh the observation or confirm child termination and release the reservation. That lifecycle integration is required to prevent stale bookkeeping without assuming a live or suspended child has exited.

## Independent review follow-up

The reviewer found that the former `subprocess.run(capture_output=True)` path checked its 16 KiB limit after buffering all child output. The replacement uses `Popen` with stdout piped and stderr discarded. A daemon reader requests at most 4096 bytes per read and never retains more than 16 KiB plus the one byte needed to prove overflow. Overflow terminates and reaps the child; a timeout is clamped to at most two seconds and termination/kill each use a 0.1-second wait bound. Probe diagnostics contain only fixed error codes; child stdout and stderr are not returned. The test helper's workload parameter is now `Literal["read", "inference", "embedding"]` without a type-ignore.

TDD evidence: the new reader-boundary test first failed because `query_nvidia_gpu_telemetry` did not accept a process factory. After the streaming implementation, the focused suite passed. It includes a fake infinite stream that is read for exactly 16 KiB + 1 byte, a real local Python child that continuously floods stdout and is terminated, acceptance of a valid output exactly at 16 KiB, a bounded timeout/termination case, and checks that a private marker does not appear in returned diagnostics. No NVIDIA hardware or driver operation is involved.

The review's scope concern is retained as an integration constraint. Repository search still finds no production caller of `ResourceSnapshotCollector`, `admit_resources`, or `ResourceReservationBook`; this work remains inactive and is not approved as a reusable or production admission authority. Before T10 connects it, the existing host lifecycle owner must establish the owner-facing contract and may reduce or reshape this proposed API: an atomic reservation tied to an existing host-owned operation; authenticated process identity from that owner; fresh monotonic per-reservation RAM, commit, CPU, and GPU observations; reflection reconciliation that subtracts only demand not already reflected in operating-system counters; and release only after the owner confirms child completion. Missing or stale evidence must remain UNKNOWN and deny affected local work. T10 must not infer identity from process names, configured model labels, or unverified PIDs, and must keep production admission disabled until the measured producer and lifecycle contract exist. Current thresholds and review tests remain synthetic assumptions.

Follow-up checks: `uv run --frozen --extra dev python -m pytest tests/downstream/test_resource_admission.py tests/downstream/test_windows_contracts.py -q` passed 56 tests; Ruff and ty passed on the changed test and production paths; `git diff --check` passed. A pinned `npx --yes @colbymchenry/codegraph@1.6.0 --version` reported 1.6.0 using an H-local npm cache. The follow-up CodeGraph after-sync remains pending until the serialized slot is released; the older receipt's version field does not itself prove which executable ran.
