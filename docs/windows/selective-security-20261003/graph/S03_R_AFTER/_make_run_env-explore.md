**Exploration: _make_run_env**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `run` (apps/desktop/scripts/run-short-session-hang-repro.mjs:139) — 5 callers in `apps/desktop/scripts/run-short-session-hang-repro.mjs`; tested via callers: `apps/desktop/scripts/run-short-session-hang-repro.test.mjs`
- `run` (batch_runner.py:777) — 5 callers in `batch_runner.py`; tests: `tests/integration/test_checkpoint_resumption.py`, `tests/test_batch_runner_discard_resume.py`, `tests/test_batch_runner_durability.py`
- `make` (hermes_cli/cli_loops_mixin.py:330) — 1 caller in `hermes_cli/cli_loops_mixin.py`; no tests found within 3 caller hops
- `make` (hermes_cli/config_defaults.py:2327) — 1 caller in `hermes_cli/config_defaults.py`; no tests found within 3 caller hops

**Relationships**

**calls:**
- run → trim
- resolveRef → run
- readTargetMetadata → run
- readJournalContract → run
- prepareTarget → run
- main → run
- resolve_branch_pin → trim
- locate_git_dir → trim
- live_marker_owner → trim
- mainStripTabTitles → trim
- layout → trim
- transcriptTextOrder → trim
- transcriptMessageOrder → trim
- resolveElectronBinary → trim
- findHermesBinary → trim
- ... and 153 more

**references:**
- run → REPO_ROOT
- run → _REASONING_KEYS
- load → make
- _get_goal_manager → load
- _get_heartbeat_manager → load
- _get_loop_manager → load
- make → _OMIT
- _category → make
- _category → _OMIT
- resolveRef → REPO_ROOT
- main → REPO_ROOT
- test_lock_timeout_degrades_to_unserialized → _second
- _anthropic_aux_stream_event_hook → _on_event

**instantiates:**
- main → BatchRunner
- test_current_implementation → BatchRunner
- test_interruption_and_resume → BatchRunner
- make → GoalManager
- __init__ → _BackgroundLoop
- _run_sequential_tool_execution_middleware → _ConcurrentToolAuthorizationGate
- __init__ → _ConcurrentToolAuthorizationGate
- _make_gate → _ConcurrentToolAuthorizationGate
- run → DaemonThreadPoolExecutor
- execute_tool_calls_concurrent → _ConcurrentBatch

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _make_run_env(function)

```python
543	    return next((k for k in run_env if k.upper() == "PATH"), None) if _IS_WINDOWS else "PATH"
544
545
546	def _make_run_env(env: dict) -> dict:
547	    """Build a run environment with a sane PATH and provider-var stripping."""
548	    return _scrubbed_env([(dict(os.environ | env), True)], frozenset(),
549	                         lambda p: _prepend_git_bash_dirs(_append_missing_sane_path_entries(p)))
550
551
552	# --- Hermes venv / repo-root detection (module-level, computed once) ---
```

**Not shown above — explore these names for their source**

- agent/tool_executor.py: run:495, run:1303, _ConcurrentToolAuthorizationGate:448, _dispatch_authorized_once:628, __init__:468, _human_wait_seconds:487, +12 more
- hermes_cli/config_defaults.py: make:2327, _category:2321, _OMIT:2318
- batch_runner.py: run:777, BatchRunner:408, _banner:397, _apply_resume:581, _load_checkpoint:503, _empty_checkpoint:500, +12 more
- apps/desktop/scripts/run-short-session-hang-repro.mjs: run:139, resolveRef:190, readTargetMetadata:226, readJournalContract:241, prepareTarget:280, main:1556, +1 more
- agent/lsp/manager.py: run:68, _BackgroundLoop:41, __init__:99, snapshot_baseline:199, get_diagnostics_sync:214, _apply_delta:254, +6 more
- hermes_cli/cli_loops_mixin.py: make:330, load:326, _get_goal_manager:324, _get_heartbeat_manager:340, _get_loop_manager:347
- tests/run_agent/test_authorization_gate.py: test_serializes_callbacks:141, test_lock_timeout_degrades_to_unserialized:168, _second:185, test_wedged_callback_contributes_nothing_to_exclusion:198, test_deadline_arithmetic_converges_with_wedged_worker:217, _make_gate:45
- agent/relay_runtime.py: acquire:213, _ProcessRelayPluginConfiguration:203, _preflight:237, _activate:226
- agent/conversation_compression.py: release:2327, try_cancel_before_commit:454, begin_commit:465, revoke_commit_admission:522
- hermes_cli/models_reasoning_caps.py: get:174, _CapsSource:160, _origin:33
- ... and 51 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
