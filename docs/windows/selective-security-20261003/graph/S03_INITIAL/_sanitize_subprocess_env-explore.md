**Exploration: _sanitize_subprocess_env**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `sanitize` (plugins/memory_llm_wiki/core.py:105) — 7 callers in `apps/desktop/src/app/right-sidebar/files/use-project-tree.ts`, `apps/desktop/src/components/ui/sanitized-input.tsx`, `apps/desktop/src/lib/persisted.ts`, `apps/desktop/src/store/session.ts` +1 more; tests: `tests/plugins/test_memory_llm_wiki.py`

**Relationships**

**calls:**
- fallbackRootFor → sanitize
- SanitizedInput → sanitize
- json → sanitize
- ensureDefaultWorkspaceCwd → sanitize
- _read_entries → sanitize
- read_ebbinghaus_items → sanitize
- test_export_splits_and_sanitizes_memory → sanitize
- loadRoot → fallbackRootFor
- SanitizedInput → Input
- WorktreeDialog → SanitizedInput
- CreateProfileDialog → SanitizedInput
- RenameProfileDialog → SanitizedInput
- fetchJSON → json
- ensureDefaultWorkspaceCwd → syncConfiguredDefaultProjectDir
- ensureDefaultWorkspaceCwd → getConfiguredDefaultProjectDir

**references:**
- sanitize → LONG_TOKEN_RE
- sanitize → IP_RE
- sanitize → MSYS_HOME_RE
- sanitize → WIN_HOME_RE
- sanitize → EMAIL_RE
- sanitize → SECRET_RE
- SanitizedInput → SanitizedInputProps
- json → t
- json → Codec
- Codec → t
- fetchJSON → t

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _sanitize_subprocess_env(function)

```python
517	            env.pop(var_name, None)
518
519
520	def _sanitize_subprocess_env(base_env: dict | None, extra_env: dict | None = None) -> dict:
521	    """Filter Hermes-managed secrets from a subprocess environment."""
522	    try:
523	        from tools.env_passthrough import (
524	            is_env_passthrough as _is_passthrough,
525	            resolve_passthrough_value as _resolve_passthrough_value,
526	        )
527	    except Exception:
528	        _is_passthrough = lambda _: False  # noqa: E731
529	        _resolve_passthrough_value = lambda _name, fallback: fallback  # noqa: E731
530
531	    sanitized: dict[str, str] = {}
532	    _plugin_strip = {key.upper() for key in _plugin_terminal_env_strip_keys()}
533	    _provider_strip = {key.upper() for key in _HERMES_PROVIDER_ENV_BLOCKLIST}
534
535	    for key, value in (base_env or {}).items():
536	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
537	            continue
538	        if _is_hermes_internal_secret(key):
539	            continue
540	        if key.upper() in _plugin_strip:
541	            continue
542	        passthrough = _is_passthrough(key)
543	        if key.upper() in _provider_strip and not passthrough:
544	            continue
545	        resolved = _resolve_passthrough_value(key, value) if passthrough else value
546	        if resolved is not None:
547	            sanitized[key] = resolved
548
549	    for key, value in (extra_env or {}).items():
550	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
551	            real_key = key[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
552	            if _is_hermes_internal_secret(real_key):
553	                continue
554	            sanitized[real_key] = value
555	        elif _is_hermes_internal_secret(key):
556	            continue
557	        elif key.upper() in _plugin_strip:
558	            continue
559	        else:
560	            passthrough = _is_passthrough(key)
561	            if key.upper() in _provider_strip and not passthrough:
562	                continue
563	            resolved = _resolve_passthrough_value(key, value) if passthrough else value
564	            if resolved is not None:
565	                sanitized[key] = resolved
566
567	    _inject_context_hermes_home(sanitized)
568
569	    from hermes_constants import apply_subprocess_home_env
570	    apply_subprocess_home_env(sanitized)
571
572	    # Same cross-session leak guard as _make_run_env, for the background/PTY
573	    # spawn path (process_registry.spawn_local builds env via this function).
574	    _inject_session_context_env(sanitized)
575
576	    # Filter PYTHONPATH before removing VIRTUAL_ENV: legacy Windows launchers
577	    # can run the gateway under a base interpreter while VIRTUAL_ENV identifies
578	    # the separate Hermes runtime venv.  The filter validates that relationship
579	    # against the repo layout before trusting it.
580	    _strip_hermes_owned_pythonpath_and_runtime_markers(sanitized)
581
582	    # Keep bare ``hermes`` invocations available to child jobs even when the
583	    # gateway was launched by a service manager or cron without the console
584	    # script's directory on PATH.  The terminal environment already applies
585	    # this invariant; Cron scripts use this sanitizer directly (#92998).
586	    path_key = _path_env_key(sanitized)
587	    if path_key is not None:
588	        sanitized[path_key] = _prepend_hermes_bin_dir(sanitized.get(path_key, ""))
589
590	    _apply_windows_msys_bash_env_defaults(sanitized)
591
592	    sanitized = _scrub_delegated_child_kanban_env(sanitized)
593
594	    return sanitized
595
596
597	def _scrub_delegated_child_kanban_env(env: dict[str, str]) -> dict[str, str]:
```

**Not shown above — explore these names for their source**

- nix/moduleCommon.nix: env:52, env:188, mcpServersToConfig:182, command:187, args:187, url:190, +17 more
- plugins/memory_llm_wiki/core.py: sanitize:105, _read_entries:165, read_ebbinghaus_items:214, LONG_TOKEN_RE:35, IP_RE:39, MSYS_HOME_RE:38, +3 more
- nix/homeManagerModules.nix: env:386, flake.homeManagerModules.default:47, cfg:57, cfgPrograms:58, common:59, lib:59, +19 more
- nix/nixosModules.nix: env:474, flake.nixosModules.default:34, cfg:44, common:45, lib:45, effectivePackage:47, +19 more
- apps/desktop/src/store/session.ts: ensureDefaultWorkspaceCwd:254, syncConfiguredDefaultProjectDir:231, getConfiguredDefaultProjectDir:229
- apps/desktop/src/app/right-sidebar/files/use-project-tree.ts: fallbackRootFor:163, loadRoot:183
- apps/desktop/src/components/ui/sanitized-input.tsx: SanitizedInput:15, SanitizedInputProps:5
- apps/desktop/src/lib/persisted.ts: json:49, Codec:13
- tests/plugins/test_memory_llm_wiki.py: test_export_splits_and_sanitizes_memory:31
- apps/desktop/src/components/ui/input.tsx: Input:19
- ... and 8 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,016 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
