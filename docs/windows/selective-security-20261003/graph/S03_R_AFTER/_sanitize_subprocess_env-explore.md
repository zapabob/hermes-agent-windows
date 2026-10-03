**Exploration: _sanitize_subprocess_env**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `ENV` (evals/codebase_navigability/runtime_bench.py:14) — 3 callers in `evals/codebase_navigability/runtime_bench.py`; no tests found within 3 caller hops

**Relationships**

**references:**
- ENV → HOME
- run → ENV
- warm_pyc → ENV
- r → ENV

**calls:**
- perSystem → tryEvalPkg
- perSystem → evalHomeSplit
- perSystem → moduleOptionNames
- perSystem → evalNixosModule
- perSystem → evalHomeModule

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _sanitize_subprocess_env(function)

```python
297	    return _finalize_child_env(out)
298
299
300	def _sanitize_subprocess_env(base_env: dict | None, extra_env: dict | None = None) -> dict:
301	    """Filter Hermes-managed secrets from a subprocess environment (background/PTY
302	    spawn path, search workers, computer-use driver, user-script runners)."""
303	    return _scrubbed_env([(base_env or {}, False), (extra_env or {}, True)],
304	                         _plugin_terminal_env_strip_keys(), lambda p: p)
305
306
307	def hermes_subprocess_env(*, inherit_credentials: bool = False) -> dict[str, str]:
```

**Not shown above — explore these names for their source**

- nix/checks.nix: env:205, env:210, perSystem:7, hermes-agent:9, hermesVenv:10, configMergeScript:12, +20 more
- evals/codebase_navigability/runtime_bench.py: ENV:14, HOME:11, run:19, warm_pyc:24, r:62
- nix/homeManagerModules.nix: env:386, flake.homeManagerModules.default:47, cfg:57, cfgPrograms:58, common:59, lib:59, +19 more
- nix/nixosModules.nix: env:474, flake.nixosModules.default:34, cfg:44, common:45, lib:45, effectivePackage:47, +19 more
- ui-tui/packages/hermes-ink/src/utils/env.ts: env:39
- evals/browser_use/orchestrate_cloud.py: env:139
- nix/moduleCommon.nix: env:52

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
