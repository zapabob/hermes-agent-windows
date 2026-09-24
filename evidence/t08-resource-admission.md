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
