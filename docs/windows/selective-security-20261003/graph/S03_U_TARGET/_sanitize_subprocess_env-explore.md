**Exploration: _sanitize_subprocess_env**

Found 1 symbol across 1 file.

**Relationships**

**references:**
- ENV → HOME
- run → ENV
- warm_pyc → ENV
- r → ENV

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _sanitize_subprocess_env(function)

```python
307	    return _finalize_child_env(out)
308
309
310	def _sanitize_subprocess_env(base_env: dict | None, extra_env: dict | None = None) -> dict:
311	    """Filter Hermes-managed secrets from a subprocess environment (background/PTY
312	    spawn path, search workers, computer-use driver, user-script runners)."""
313	    return _scrubbed_env([(base_env or {}, False), (extra_env or {}, True)],
314	                         _plugin_terminal_env_strip_keys(), lambda p: p)
315
316
317	def hermes_subprocess_env(
```

**Not shown above — explore these names for their source**

- evals/codebase_navigability/runtime_bench.py: ENV:14, HOME:11, run:19, warm_pyc:24, r:62
- ui-tui/packages/hermes-ink/src/utils/env.ts: env:39
- apps/desktop/scripts/connector-rehearsal.mjs: env:28
- apps/desktop/scripts/verify-side-by-side-macos.mjs: env:38
- evals/desktop_bug_campaign/native_ready_probe.mjs: env:14
- evals/browser_use/orchestrate_cloud.py: env:139
- evals/desktop_bug_campaign/history_live.py: env:36
- evals/desktop_bug_campaign/hooks_live.py: env:77

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
