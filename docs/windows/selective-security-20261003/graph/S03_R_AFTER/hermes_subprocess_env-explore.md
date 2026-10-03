**Exploration: hermes_subprocess_env**

Found 2 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `hermes_subprocess_env` (tools/environments/local.py:307) — 25 callers in `agent/copilot_acp_client.py`, `agent/transports/codex_app_server.py`, `hermes_cli/dep_ensure.py`, `tools/browser_tool.py` +7 more; tests: `tests/tools/test_hermes_subprocess_env.py`, `tests/tools/test_local_env_session_leak.py`, `tests/tools/test_local_env_windows_msys.py`
- `ENV` (evals/codebase_navigability/runtime_bench.py:14) — 3 callers in `evals/codebase_navigability/runtime_bench.py`; no tests found within 3 caller hops

**Relationships**

**calls:**
- hermes_subprocess_env → copy
- hermes_subprocess_env → _plugin_terminal_env_strip_keys
- hermes_subprocess_env → _is_hermes_internal_secret
- hermes_subprocess_env → _finalize_child_env
- _build_subprocess_env → hermes_subprocess_env
- __init__ → hermes_subprocess_env
- ensure_dependency → hermes_subprocess_env
- _build → hermes_subprocess_env
- test_browser_keys_recoverable_after_strip → hermes_subprocess_env
- test_delegated_child_context_scrubs_parent_kanban_keys_and_sets_marker → hermes_subprocess_env
- test_hermes_subprocess_env_strips_foreign_session_key_when_engaged → hermes_subprocess_env
- test_hermes_subprocess_env_unengaged_preserves_fallback → hermes_subprocess_env
- test_hermes_subprocess_env_sets_msys_no_pathconv_on_windows → hermes_subprocess_env
- _build_browser_env → hermes_subprocess_env
- _venv_pip_install → hermes_subprocess_env
- ... and 13 more

**references:**
- import_skills → copy
- ENV → HOME
- run → ENV
- warm_pyc → ENV
- r → ENV

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _finalize_child_env(function), hermes_subprocess_env(function), copy(calls), _plugin_terminal_env_strip_keys(calls), _is_hermes_internal_secret(calls), _finalize_child_env(calls)

```python
264	            out[key] = value
265
266
267	def _finalize_child_env(env: dict) -> dict:
268	    """Guards shared by every spawn surface: profile-home propagation, session-context
269	    bridging, Hermes-owned PYTHONPATH + venv-marker strip, MSYS defaults, delegate_task
270	    Kanban scrub. Returns the (possibly new) dict."""
271	    _apply_profile_home(env)
272	    _inject_session_context_env(env)
273	    _strip_hermes_owned_pythonpath_and_runtime_markers(env)
274	    _apply_windows_msys_bash_env_defaults(env)
275	    try:  # strip dispatcher-owned Kanban env from delegate_task child subprocesses
276	        from agent.delegation_context import is_delegated_child_process_context, scrub_kanban_env
277	        if is_delegated_child_process_context():
278	            return scrub_kanban_env(env)
279	    except Exception:
280	        pass
281	    return env
282
283
284	def _scrubbed_env(parts, plugin_strip: frozenset, fix_path) -> dict:

... (gap) ...

304	                         _plugin_terminal_env_strip_keys(), lambda p: p)
305
306
307	def hermes_subprocess_env(*, inherit_credentials: bool = False) -> dict[str, str]:
308	    """Sanitized env for the **non-terminal** spawn surface (browser, ACP/CLI executors,
309	    computer-use driver, TUI Node host). Tier 1 (``_ALWAYS_STRIP_KEYS``, plugin keys,
310	    force-prefixed hints, dynamic internal secrets) is always removed; Tier 2 (the
311	    provider/tool blocklist) unless ``inherit_credentials`` — pass that **only** for
312	    children that legitimately need LLM credentials (user-blessed claude/codex/gemini
313	    CLI, TUI Node host). Terminal/execute_code use ``_sanitize_subprocess_env``."""
314	    env = os.environ.copy()
315	    strip = _ALWAYS_STRIP_KEYS | _plugin_terminal_env_strip_keys()
316	    if not inherit_credentials:
317	        strip |= _HERMES_PROVIDER_ENV_BLOCKLIST
318	    for key in list(env):
319	        if (key in strip or key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX)
320	                or _is_hermes_internal_secret(key)):
321	            del env[key]
322	    env.setdefault("PYTHONUTF8", "1")  # Windows UTF-8 safety for spawned processes
323	    return _finalize_child_env(env)
324
325
326	def build_subprocess_env(
```

**Not shown above — explore these names for their source**

- nix/checks.nix: env:205, env:210, perSystem:7, hermes-agent:9, hermesVenv:10, configMergeScript:12, +20 more
- evals/codebase_navigability/runtime_bench.py: ENV:14, HOME:11, run:19, warm_pyc:24, r:62
- nix/homeManagerModules.nix: env:386, flake.homeManagerModules.default:47, cfg:57, cfgPrograms:58, common:59, lib:59, +19 more
- tools/environments/local_env_policy.py: _plugin_terminal_env_strip_keys:184, _is_hermes_internal_secret:172
- tests/tools/test_hermes_subprocess_env.py: _build:43, test_browser_keys_recoverable_after_strip:128, test_delegated_child_context_scrubs_parent_kanban_keys_and_sets_marker:154, test_hermes_subprocess_env.py:1
- hermes_cli/agent_import.py: copy:503, import_skills:484
- agent/copilot_acp_client.py: _build_subprocess_env:117, copilot_acp_client.py:1
- agent/transports/codex_app_server.py: __init__:45, codex_app_server.py:1
- hermes_cli/dep_ensure.py: ensure_dependency:76, dep_ensure.py:1
- tui_gateway/host_supervisor.py: _spawn_locked:309, host_supervisor.py:1
- ... and 14 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
