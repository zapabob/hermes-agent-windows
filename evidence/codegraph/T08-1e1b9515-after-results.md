# T08 CodeGraph after findings

- Repository: zapabob/hermes-agent-windows
- Worktree: H:\hermes-control-mcp-t08-resources-20260924
- Branch and implementation SHA: codex/t08-resources-h-20260924 / 1e1b9515f6ee8feedf3a6b754cc5cce22110709e
- CodeGraph: @colbymchenry/codegraph 1.6.0 CLI; sync . exited 0. status . --json reported current with 8,908 indexed files, 190,696 nodes, 610,392 edges, 639,811,584-byte DB, 0 pending changes, 0 pending refs, extraction version 25, and no worktree mismatch.
- Source fingerprint: eef217745ea20f2ab13600b97eab5320545b707feb57dc9a1b688e3558f91e2c, SHA-256 of compact JSON containing the CodeGraph files table ordered by path, with each row [path, content_hash, size].

## Query results

1. impact -p . -d 2 -j ResourceReservationBook found the T08 class and methods, plus its behavioral tests. One graph edge pointed to downstream/delegation/inference_port.py::complete; direct rg found no T08 resource symbol references there, so that edge is treated as a name-based false positive.
2. impact -p . -d 2 -j query_nvidia_gpu_telemetry found the read-only GPU probe, the new collector module, and its probe tests. No runtime producer outside the collector/tests was shown.
3. query ResourceSnapshotCollector confirmed the collector's constructor and collect() method in downstream/delegation/resources.py.
4. Direct rg for ResourceReservationBook, ResourceReflection, and admit_resources found definitions/calls only inside the new resource module and its test file. The feature remains unwired from production delegation.

## Disposition

- The index supports navigation and impact review only; it does not prove live resource values, admission correctness, or runtime integration.
- No actual workstation resource sample was taken. Current tests use synthetic snapshots and fake command/process providers.
- Per-reservation process telemetry remains an integration dependency: T10 must supply fresh RAM, commit, CPU, and GPU usage measurements bound to each host-owned reservation before any production admission is enabled.
