**Exploration: _make_run_env**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `run` (apps/desktop/scripts/run-short-session-hang-repro.mjs:139) — 5 callers in `apps/desktop/scripts/run-short-session-hang-repro.mjs`; tested via callers: `apps/desktop/scripts/run-short-session-hang-repro.test.mjs`
- `run` (batch_runner.py:850) — 6 callers in `batch_runner.py`; tests: `tests/integration/test_checkpoint_resumption.py`, `tests/run_agent/test_callable_api_key.py`, `tests/test_batch_runner_discard_resume.py`, `tests/test_batch_runner_durability.py`
- `run` (agent/lsp/manager.py:101) — 13 callers in `acp_adapter/server.py`, `agent/lsp/manager.py`, `agent/relay_llm.py`, `agent/relay_tools.py` +3 more; tested via callers: `tests/acp/test_server.py`, `tests/agent/lsp/test_broken_set.py` +2
- `run` (agent/tool_executor.py:536) — 6 callers in `agent/tool_executor.py`; tests: `tests/run_agent/test_authorization_gate.py`

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
- transcriptTextOrder → trim
- transcriptMessageOrder → trim
- resolveElectronBinary → trim
- findHermesBinary → trim
- transcriptMessageOrder → trim
- installErrorBannerGuard → trim
- ... and 210 more

**references:**
- run → REPO_ROOT
- run → ALL_POSSIBLE_TOOLS
- run → _process_batch_worker
- run → t
- run → t
- run → PLATFORM
- run → DESKTOP_ROOT
- ensurePackagedApp → APP
- ensureDmg → PLATFORM
- ensureNsis → PLATFORM
- openApp → APP
- openApp → PLATFORM
- openDmg → PLATFORM
- APP → PLATFORM
- DEFAULT_HERMES_HOME → PLATFORM
- ... and 22 more

**instantiates:**
- run → Progress
- main → BatchRunner
- test_current_implementation → BatchRunner
- test_interruption_and_resume → BatchRunner
- __init__ → _BackgroundLoop
- _run_sequential_tool_execution_middleware → _ConcurrentToolAuthorizationGate
- execute_tool_calls_concurrent → _ConcurrentToolAuthorizationGate
- _make_gate → _ConcurrentToolAuthorizationGate

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _make_run_env(function)

```python
1623	    return None
1624
1625
1626	def _make_run_env(env: dict) -> dict:
1627	    """Build a run environment with a sane PATH and provider-var stripping."""
1628	    try:
1629	        from tools.env_passthrough import (
1630	            is_env_passthrough as _is_passthrough,
1631	            resolve_passthrough_value as _resolve_passthrough_value,
1632	        )
1633	    except Exception:
1634	        _is_passthrough = lambda _: False  # noqa: E731
1635	        _resolve_passthrough_value = lambda _name, fallback: fallback  # noqa: E731
1636
1637	    merged = _profile_child_base(os.environ, extra=env)
1638	    run_env = {}
1639	    plugin_strip = {key.upper() for key in _plugin_terminal_env_strip_keys()}
1640	    provider_strip = _provider_secret_env()
1641	    for k, v in merged.items():
1642	        if k.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
1643	            real_key = k[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
1644	            if _is_hermes_internal_secret(real_key) or real_key.upper() in plugin_strip:
1645	                continue
1646	            run_env[real_key] = v
1647	        elif _is_hermes_internal_secret(k) or k.upper() in plugin_strip:
1648	            continue
1649	        else:
1650	            passthrough = _is_passthrough(k)
1651	            if k.upper() in provider_strip and not passthrough:
1652	                continue
1653	            value = _resolve_passthrough_value(k, v) if passthrough and (
1654	                k not in env or _CREDENTIAL_ENV_NAME_RE.search(k)
1655	            ) else v
1656	            if value is not None:
1657	                run_env[k] = value
1658	    path_key = _path_env_key(run_env)
1659	    if path_key is not None:
1660	        new_path = _append_missing_sane_path_entries(run_env.get(path_key, ""))
1661	        # On Windows, ensure Git Bash's coreutils dirs (…\usr\bin etc.) are on
1662	        # PATH.  A non-login ``bash -c`` fallback (used when ``bash -l`` is
1663	        # broken) never sources /etc/profile, so without this cat/mktemp/mv and
1664	        # friends are missing and every write_file/terminal call fails (empty
1665	        # error / exit 127).  No-op off Windows and when a login snapshot is
1666	        # healthy (the snapshot re-exports the full PATH inside the shell).
1667	        new_path = _prepend_git_bash_dirs(new_path)
1668	        # Ensure the hermes install dir is reachable so plugins can shell out
1669	        # to bare ``hermes`` via the terminal tool even when the gateway was
1670	        # launched without it on PATH (systemd, service managers, cron, etc.).
1671	        run_env[path_key] = _prepend_hermes_bin_dir(new_path)
1672
1673	    _inject_context_hermes_home(run_env)
1674
1675	    from hermes_constants import apply_subprocess_home_env
1676	    apply_subprocess_home_env(run_env)
1677
1678	    # Bridge ContextVar-based session vars into the subprocess env (with the
1679	    # cross-session leak guard — strips _UNSET vars when a concurrent host is
1680	    # engaged so a sibling session's os.environ mirror can't leak in).
1681	    _inject_session_context_env(run_env)
1682
1683	    _strip_hermes_owned_pythonpath_and_runtime_markers(run_env)
1684
1685	    _apply_windows_msys_bash_env_defaults(run_env)
1686
1687	    run_env = _scrub_delegated_child_kanban_env(run_env)
1688
1689	    return run_env
1690
1691
1692	def _same_path(left: Path, right: Path) -> bool:
```

**Not shown above — explore these names for their source**

- apps/desktop/scripts/test-desktop.mjs: run:70, die:65, ensurePackagedApp:117, ensureDmg:161, ensureNsis:171, openApp:181, +17 more
- apps/desktop/scripts/run-short-session-hang-repro.mjs: run:139, resolveRef:190, readTargetMetadata:226, readJournalContract:241, prepareTarget:280, main:1556, +1 more
- batch_runner.py: run:850, BatchRunner:569, _scan_completed_prompts_by_content:774, _filter_dataset_by_completed:816, _load_checkpoint:730, _save_checkpoint:757, +4 more
- agent/lsp/manager.py: run:101, _BackgroundLoop:65, __init__:147, snapshot_baseline:297, get_diagnostics_sync:321, _mark_broken_for_file:416, +5 more
- agent/tool_executor.py: run:536, _ConcurrentToolAuthorizationGate:477, _authorized_dispatch:643, __init__:499, _human_wait_seconds:528, excluded_seconds:551, +2 more
- apps/desktop/electron/backend-dial-claim.ts: run:28, BackendDialClaims:20, inFlight:24
- apps/desktop/electron/main.ts: registerMediaProtocol:1344, ensureTerminalBackend:9868, exitAfterBackendShutdown:12105, redialPoolBackendAfterResume:14212, enumerateRegistryAgentSources:14845, dispatchRegistryApiRequest:15771, +9 more
- apps/desktop/electron/remote-liveness.ts: run:48, RemoteRevalidationCoordinator:45
- agent/relay_runtime.py: acquire:271, release:251, _ProcessRelayPluginConfiguration:260, _clear_active:410, _remember:374, _configured_plugin_inputs:1984, +1 more
- agent/relay_llm.py: invoke:130, invoke:222, run_callback:488
- ... and 60 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
