**Exploration: hermes_subprocess_env**

Found 4 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `hermes_subprocess_env` (tools/environments/local.py:317) — 37 callers in `agent/copilot_acp_client.py`, `agent/lsp/client.py`, `agent/lsp/install.py`, `agent/transports/codex_app_server.py` +12 more; tests: `tests/tools/test_hermes_subprocess_env.py`, `tests/tools/test_local_env_blocklist.py`, `tests/tools/test_local_env_session_leak.py`, `tests/tools/test_local_env_windows_msys.py`

**Relationships**

**calls:**
- hermes_subprocess_env → copy
- hermes_subprocess_env → _scrub_credentials
- hermes_subprocess_env → _finalize_child_env
- _build_subprocess_env → hermes_subprocess_env
- _spawn → hermes_subprocess_env
- _install_npm → hermes_subprocess_env
- _install_go → hermes_subprocess_env
- __init__ → hermes_subprocess_env
- _gh_env → hermes_subprocess_env
- _start_local_openviking_server → hermes_subprocess_env
- _exec_buzz → hermes_subprocess_env
- _spawn_bridge → hermes_subprocess_env
- _build → hermes_subprocess_env
- test_browser_keys_recoverable_after_strip → hermes_subprocess_env
- test_delegated_child_context_scrubs_parent_kanban_keys_and_sets_marker → hermes_subprocess_env
- ... and 9 more

**references:**
- ENV → HOME
- run → ENV
- warm_pyc → ENV
- r → ENV

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _scrub_credentials(calls), _finalize_child_env(function), hermes_subprocess_env(function), copy(calls), _finalize_child_env(calls), _scrub_credentials(function), served_profile_child_env(function), hermes_subprocess_env(calls), references(references), instantiates(instantiates)

```python
273	            out[key] = value
274
275
276	def _finalize_child_env(env: dict) -> dict:
277	    """Guards shared by every spawn surface: profile-home propagation, session-context
278	    bridging, Hermes-owned PYTHONPATH + venv-marker strip, MSYS defaults, delegate_task
279	    Kanban scrub. Returns the (possibly new) dict."""
280	    _apply_profile_home(env)
281	    _inject_session_context_env(env)
282	    _strip_hermes_owned_pythonpath_and_runtime_markers(env)
283	    _apply_windows_msys_bash_env_defaults(env)
284	    from agent.delegation_context import delegated_child_subprocess_env
285	    return delegated_child_subprocess_env(env)
286
287
288	def _scrubbed_env(parts, plugin_strip: frozenset, fix_path) -> dict:

... (gap) ...

314	                         _plugin_terminal_env_strip_keys(), lambda p: p)
315
316
317	def hermes_subprocess_env(
318	    *, inherit_credentials: bool = False, base_env: dict[str, str] | None = None
319	) -> dict[str, str]:
320	    """Sanitize a non-terminal child's environment (no skill passthrough).
321
322	    Bot, GitHub and remote-compute secrets never pass through; provider/tool
323	    credentials pass only with ``inherit_credentials=True`` for children that
324	    need them. Callers needing one other secret should add only that key back.
325	    ``base_env`` lets an already curated environment use the same policy.
326	    Terminal and execute_code spawns use the skill-aware sanitizer instead.
327	    """
328	    env = dict(base_env) if base_env is not None else os.environ.copy()
329	    env = _scrub_credentials(env, inherit_credentials=inherit_credentials)
330	    env.setdefault("PYTHONUTF8", "1")  # Windows UTF-8 safety for spawned processes
331	    return _finalize_child_env(env)
332
333
334	def _scrub_credentials(env: dict, *, inherit_credentials: bool) -> dict:
335	    """Tier 1 (always) and, unless ``inherit_credentials``, Tier 2 provider/tool credentials, in place."""
336	    # Credential names fold to uppercase for membership: on Windows the env block
337	    # itself is case-insensitive, so a lowercase-stored ``gh_token`` IS GH_TOKEN.
338	    home_secrets = _home_adapter_secret_env()  # one manifest stamp per scrub
339	    strip_folded = _ALWAYS_STRIP_FOLDED | {k.upper() for k in _plugin_terminal_env_strip_keys()} | home_secrets
340	    registered = _registry_adapter_secret_env()  # home_secrets already strip above
341	    for key in list(env):
342	        if (key.upper() in strip_folded
343	                or (not inherit_credentials and _is_provider_env_blocklisted(key, registered))
344	                or key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX)
345	                or _is_hermes_internal_secret(key)):
346	            del env[key]
347	    return env
348
349
350	def build_subprocess_env(

... (gap) ...

383	    return delegated_child_subprocess_env(env)
384
385
386	def served_profile_child_env(
387	    base: "Mapping[str, str] | None" = None, *, target_home: "str | Path | None" = None,
388	    inherit_credentials: bool = False,
389	) -> dict[str, str]:
390	    """Child env for a process that acts FOR the active (possibly served) profile: ``hermes -p X``
391	    workers, ``key_cmd`` helpers, browser drivers. The process env is the LAUNCH profile's. When the
392	    target is a ROUTED home (not the launch profile's — under multiplex or a Desktop/dashboard backend
393	    serving ``?profile=`` with the flag off) the launch ``.env`` residue and bridged ``TERMINAL_*`` are
394	    dropped (``strip_launch_profile_env``) AND every provider/tool credential is scrubbed from the base
395	    regardless of provenance: a key systemd / Compose / the shell injected into the launch process was
396	    never recorded in ``.env`` or a source snapshot, so a name-based strip cannot see it and the target
397	    overlay cannot remove it. ``inherit_credentials=True`` is for children that legitimately run with
398	    the profile's credentials (they run the agent or mint its token): the target profile's own secrets
399	    (its ``.env`` + hydrated sources, what a standalone ``hermes -p X`` loads itself) are overlaid — never
400	    a sibling profile's. Under multiplex with neither a target nor a bound scope the call raises
401	    (``get_secret``'s fail-closed contract): minting with the launch environ would sign in as the wrong
402	    profile. ``False`` keeps the provider scrub; the caller re-adds the few keys the child needs via
403	    ``get_secret``. ``target_home`` defaults to the active override; ``base`` replaces the
404	    ``hermes_subprocess_env`` snapshot."""
405	    from agent.secret_scope import (
406	        UnscopedSecretError, build_profile_secret_scope, current_secret_scope, is_multiplex_active)
407	    from hermes_constants import apply_scratch_tmp_env, get_hermes_home_override
408	    env = dict(base) if base is not None else hermes_subprocess_env(inherit_credentials=inherit_credentials)
409	    target = str(target_home or get_hermes_home_override() or "")
410	    if target:
411	        env["HERMES_HOME"] = target
412	        apply_scratch_tmp_env(env)  # TMPDIR follows the served home, like HOME does
413	        if _is_routed_home(target):
414	            strip_launch_profile_env(env, target)
415	            _scrub_credentials(env, inherit_credentials=False)
416	    if inherit_credentials:
417	        if target:
418	            secrets = build_profile_secret_scope(Path(target))
419	        else:
420	            secrets = current_secret_scope()
421	            if secrets is None and is_multiplex_active():
422	                raise UnscopedSecretError(
423	                    "", "served_profile_child_env(inherit_credentials=True) called with no target home and "
424	                    "no profile secret scope bound while multiplexing is on; the child would inherit the "
425	                    "launch profile's credentials. Bind the profile scope (or pass target_home) at the spawn site.")
426	        env.update((k, v) for k, v in (secrets or {}).items() if v is not None)
427	    return env
428
429
430	def host_gateway_child_env(
```

**Not shown above — explore these names for their source**

- evals/codebase_navigability/runtime_bench.py: ENV:14, HOME:11, run:19, warm_pyc:24, r:62
- agent/lsp/install.py: _install_npm:239, _install_go:278
- tests/tools/test_hermes_subprocess_env.py: _build:43, test_browser_keys_recoverable_after_strip:133, test_delegated_child_context_scrubs_parent_kanban_keys_and_sets_marker:159, test_hermes_subprocess_env.py:1
- agent/copilot_acp_client.py: _build_subprocess_env:125, copilot_acp_client.py:1
- agent/transports/codex_app_server.py: __init__:91, codex_app_server.py:1
- hermes_cli/anon_sign_in.py: copy:81
- agent/lsp/client.py: _spawn:249
- hermes_cli/kanban_pr_acceptance.py: _gh_env:64
- plugins/memory/openviking/__init__.py: _start_local_openviking_server:956
- plugins/platforms/buzz/adapter.py: _exec_buzz:390
- ... and 8 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
