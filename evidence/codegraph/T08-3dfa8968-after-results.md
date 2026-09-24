# T08 CodeGraph after findings

- Repository: `zapabob/hermes-agent-windows`
- Worktree: `H:\hermes-control-mcp-t08-resources-20260924`
- Source branch and commit: `codex/t08-resources-h-20260924` / `3dfa896847760763cfa79af04f360f433c2a2198`
- Exact CLI: `@colbymchenry/codegraph` 1.6.0, invoked with `npx --yes @colbymchenry/codegraph@1.6.0`; the separate `--version` command printed `1.6.0`.
- Sync: `npx --yes @colbymchenry/codegraph@1.6.0 sync .` exited 0, reported two changed files and 95 modified nodes, then `Done`.
- Immediate status: 8,908 files, 190,728 nodes, 610,466 edges, 643,559,424-byte DB, zero pending added/modified/removed files, zero pending refs, extraction version 25, state `complete`, and no worktree mismatch. H had 28,133,789,696 free bytes after sync (about 26.2 GiB), above the 8 GiB floor. The sync/status processes had exited; no CodeGraph process remained in the targeted process query.
- Source fingerprint: `12425dc8023e3b1f010f2c2a097d793ef708ce4f23ede7effd8f39ba36518640`, SHA-256 of compact JSON over the ordered CodeGraph files manifest rows `[path, content_hash, size]`.

## GPU probe impact

`impact -p . -d 2 -j query_nvidia_gpu_telemetry` returned eight nodes/eight edges. It identifies the probe in `downstream/platform/windows/gpu.py`, its collector dependency, and the focused tests, including the new streaming-flood, exact-limit, real-child-termination, and timeout cases. No production runtime consumer appeared.

## Reservation impact

`impact -p . -d 2 -j ResourceReservationBook` returned 20 nodes/43 edges, covering the reservation methods and behavioral tests. One edge points to `downstream/delegation/inference_port.py::complete`; direct source search found no references there to `ResourceReservationBook`, `ResourceReflection`, or `admit_resources`, so this is a name-based false positive. The API remains unwired.

## Collector query and direct search

`query ResourceSnapshotCollector` maps its constructor and `collect()` implementation in `downstream/delegation/resources.py`, plus its test import. Direct `rg` shows the new resource API is called by its tests and definitions only; there is no production caller. T10 still owns the future lifecycle composition and must supply authenticated process identity and measured per-reservation reflection before local admission can be enabled.

This index confirms navigation and static impact only. It does not establish real GPU/commit telemetry, hardware capacity, or live delegation behavior. Policy values and tests remain synthetic; no Docker workload or stress benchmark was run.
