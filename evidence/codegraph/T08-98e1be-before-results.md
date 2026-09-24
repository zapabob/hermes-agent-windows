# T08 CodeGraph before findings

- Repository: `zapabob/hermes-agent-windows`
- Worktree: `H:\hermes-control-mcp-t08-resources-20260924`
- Branch and source SHA: `codex/t08-resources-h-20260924` / `98e1be6e94bab5cc0d70d4a827f826e3a6a020b2`
- CodeGraph: `@colbymchenry/codegraph` 1.6.0, CLI; index path `.codegraph`, status reported current with 8,906 files, 190,577 nodes, 609,972 edges.

## Query results

1. `explore --max-files 8 resource monitoring owner for system RAM, commit headroom, CPU, GPU UUID and free VRAM, local inference and embedding residency` returned 76 symbols but its leading results were unrelated TypeScript helpers. This broad lexical result is not treated as evidence for a resource owner.
2. `impact -p . -d 2 -j _get_rss_mb` mapped `_get_rss_mb` only through `gateway/memory_monitor.py` process RSS logging (`log_memory_usage`, `_monitor_loop`, `start_memory_monitoring`, `stop_memory_monitoring`). It is not a host-wide budget authority.
3. `impact -p . -d 2 -j visible_cuda_devices` mapped `downstream/platform/windows/gpu.py` to its strict CUDA-visible-device parser and `tests/downstream/test_windows_contracts.py`; no production runtime caller appeared in the impact result.
4. `explore --max-files 8 delegate_task subagent lifecycle child wait cancellation resource owner` mapped `tools/delegate_tool.py::delegate_task` into child lifecycle functions and `agent/subagent_lifecycle.py::SubagentLifecycleService`; the latter owns launch/status/wait/cancel through the existing executor and registry. The query also reported broad lexical false positives.

## Direct checks required before implementation

- Inspect current status/performance and local inference/embedding owners to identify safe reuse points; do not infer residency from process names or configured model labels.
- Verify whether current telemetry providers expose actual commit headroom and per-device memory, and define sanitized missing/stale error codes.
- Keep new admission logic proposed and unwired until T06/T10 qualification; keep every resident child reservation charged until confirmed quiescence.
- Add behavior tests for stale/missing GPU, RAM/commit pressure, embedding occupancy, suspended-child memory, hysteresis, and atomic competing reservations.