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
642	            env.pop(var_name, None)
643
644
645	def _sanitize_subprocess_env(base_env: dict | None, extra_env: dict | None = None) -> dict:
646	    """Filter Hermes-managed secrets from a subprocess environment."""
647	    try:
648	        from tools.env_passthrough import (
649	            is_env_passthrough as _is_passthrough,
650	            resolve_passthrough_value as _resolve_passthrough_value,
651	        )
652	    except Exception:
653	        _is_passthrough = lambda _: False  # noqa: E731
654	        _resolve_passthrough_value = lambda _name, fallback: fallback  # noqa: E731
655
656	    sanitized: dict[str, str] = {}
657	    _plugin_strip = {key.upper() for key in _plugin_terminal_env_strip_keys()}
658	    _provider_strip = _provider_secret_env()
659
660	    effective = _profile_child_base(base_env or {}, extra=extra_env)
661	    for key, value in effective.items():
662	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
663	            if key not in (extra_env or {}):
664	                continue
665	            real_key = key[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
666	            if _is_hermes_internal_secret(real_key) or real_key.upper() in _plugin_strip:
667	                continue
668	            sanitized[real_key] = value
669	            continue
670	        if _is_hermes_internal_secret(key):
671	            continue
672	        if key.upper() in _plugin_strip:
673	            continue
674	        passthrough = _is_passthrough(key)
675	        if key.upper() in _provider_strip and not passthrough:
676	            continue
677	        resolved = _resolve_passthrough_value(key, value) if passthrough and (
678	            key not in (extra_env or {}) or _CREDENTIAL_ENV_NAME_RE.search(key)
679	        ) else value
680	        if resolved is not None:
681	            sanitized[key] = resolved
682
683	    _inject_context_hermes_home(sanitized)
684
685	    from hermes_constants import apply_subprocess_home_env
686	    apply_subprocess_home_env(sanitized)
687
688	    # Same cross-session leak guard as _make_run_env, for the background/PTY
689	    # spawn path (process_registry.spawn_local builds env via this function).
690	    _inject_session_context_env(sanitized)
691
692	    # Filter PYTHONPATH before removing VIRTUAL_ENV: legacy Windows launchers
693	    # can run the gateway under a base interpreter while VIRTUAL_ENV identifies
694	    # the separate Hermes runtime venv.  The filter validates that relationship
695	    # against the repo layout before trusting it.
696	    _strip_hermes_owned_pythonpath_and_runtime_markers(sanitized)
697
698	    # Keep bare ``hermes`` invocations available to child jobs even when the
699	    # gateway was launched by a service manager or cron without the console
700	    # script's directory on PATH.  The terminal environment already applies
701	    # this invariant; Cron scripts use this sanitizer directly (#92998).
702	    path_key = _path_env_key(sanitized)
703	    if path_key is not None:
704	        sanitized[path_key] = _prepend_hermes_bin_dir(sanitized.get(path_key, ""))
705
706	    _apply_windows_msys_bash_env_defaults(sanitized)
707
708	    sanitized = _scrub_delegated_child_kanban_env(sanitized)
709
710	    return sanitized
711
712
713	def _scrub_delegated_child_kanban_env(env: dict[str, str]) -> dict[str, str]:
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

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
