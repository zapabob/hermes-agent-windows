**Exploration: _provider_secret_env**

Found 9 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `PROVIDER` (scripts/master-heartbeat.py:23) — 3 callers in `scripts/master-heartbeat.py`; no tests found within 3 caller hops

**Relationships**

**extends:**
- DrainSecretProvider → DashboardAuthProvider
- BasicAuthProvider → DashboardAuthProvider
- NousDashboardAuthProvider → DashboardAuthProvider
- SelfHostedOIDCProvider → DashboardAuthProvider
- StubAuthProvider → DashboardAuthProvider

**references:**
- run_hermes_task → PROVIDER
- persist_results → PROVIDER
- print_report → PROVIDER
- run_hermes_task → MODEL
- run_hermes_task → HERMES_CMD
- persist_results → MODEL
- persist_results → A2A_RESULTS_DIR
- print_report → HERMES_CMD
- print_report → MODEL
- _subprocess_env → CERT_BUNDLE
- _provider_secret_env → _AWS_SDK_CREDENTIAL_ENV_VARS
- _provider_secret_env → _HERMES_PROVIDER_ENV_BLOCKLIST
- list_providers → _scoped_providers
- list_providers → _providers
- list_providers → _lock
- ... and 2 more

**calls:**
- run_hermes_task → _subprocess_env
- run_hermes_task → communicate
- run_hermes_task → classify_output
- run_hermes_task → clip
- run_hermes_task → kill
- run_hermes_task → wait
- run_with_retry → run_hermes_task
- persist_results → write_text
- main → persist_results
- main → print_report
- _subprocess_env → copy
- _run_helper → communicate
- _spawn → communicate
- _convert_to_opus → communicate
- bounded_probe_run → communicate
- ... and 77 more

**instantiates:**
- register → DrainSecretProvider
- verify_token → TokenPrincipal

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _provider_secret_env(calls), is_multiplex_active(calls), _profile_child_base(calls), _registered_adapter_secret_env(calls), _AWS_SDK_CREDENTIAL_ENV_VARS(variable), _HERMES_PROVIDER_ENV_BLOCKLIST(variable), _provider_secret_env(function), list_providers(calls), _registered_adapter_secret_env(function), required_env_names(calls), _profile_child_base(function), references(references), instantiates(instantiates), hermes_home_key(calls), +5 more

```python
222	# unconditionally — and (b) be unrecoverable, because env_passthrough.py
223	# refuses to re-allow anything in this blocklist (GHSA-rhgp-j443-p4rf).  See
224	# issue #32314 discussion.
225	_AWS_SDK_CREDENTIAL_ENV_VARS = frozenset({
226	    "AWS_BEARER_TOKEN_BEDROCK",
227	})
228
229
230	def _build_provider_env_blocklist() -> frozenset:

... (gap) ...

374	    return frozenset(blocked)
375
376
377	_HERMES_PROVIDER_ENV_BLOCKLIST = _build_provider_env_blocklist()
378
379
380	def _provider_secret_env() -> frozenset[str]:
381	    """Resolve current provider declarations, including late OAuth profiles."""
382	    names = {name.upper() for name in _HERMES_PROVIDER_ENV_BLOCKLIST}
383	    try:
384	        from providers import list_providers
385	        for profile in list_providers():
386	            declared = profile.env_vars
387	            if not isinstance(declared, (tuple, list, set, frozenset)) or any(
388	                not isinstance(name, str) or not name for name in declared
389	            ):
390	                raise ValueError("provider environment declaration is invalid")
391	            if profile.auth_type == "aws_sdk":
392	                names.update(_AWS_SDK_CREDENTIAL_ENV_VARS)
393	            else:
394	                names.update(name.upper() for name in declared if not name.upper().endswith("_URL"))
395	    except Exception as exc:
396	        raise RuntimeError("Cannot resolve provider credential declaration") from exc
397	    # Same operator-owned CLI exemption as the original registry owner.
398	    names.discard("CLAUDE_CODE_OAUTH_TOKEN")
399	    names.update(_registered_adapter_secret_env())
400	    return frozenset(names)
401
402	# Active-virtualenv markers that must NOT leak into terminal subprocesses.
403	# The gateway runs inside its own venv, so its process environment carries

... (gap) ...

498	    return plugin_strip_env_keys() | platform_manifest_secret_envs(_child_policy_home()) | adapter_secrets | _ALWAYS_STRIP_KEYS
499
500
501	def _registered_adapter_secret_env() -> frozenset[str]:
502	    """Unchecked runtime declarations are Tier 2, never core reclassification."""
503	    from gateway.platform_registry import platform_registry
504	    from hermes_cli.config import PLATFORM_SECRET_ENV_SUFFIXES
505	    return frozenset(
506	        name.upper() for name in platform_registry.required_env_names(include_profile=_child_policy_home() is not None)
507	        if name.upper().endswith(PLATFORM_SECRET_ENV_SUFFIXES)
508	    )
509
510
511	def _launch_profile_owned_env_names() -> frozenset[str]:

... (gap) ...

544	        pass
545
546
547	def _profile_child_base(
548	    base: Mapping[str, str], *, inherit_credentials: bool = False,
549	    extra: Mapping[str, str] | None = None,
550	) -> dict:
551	    """Resolve routed profile values before applying the child security tier."""
552	    from agent.secret_scope import (
553	        UnscopedSecretError, _is_global_env, build_profile_secret_scope,
554	        current_secret_scope, is_multiplex_active, load_env_file,
555	    )
556	    from hermes_cli.config import platform_manifest_secret_envs
557	    from hermes_cli.env_loader import get_secret_source_values, loaded_profile_env_keys, launch_profile_home
558	    from hermes_constants import (
559	        get_hermes_home, get_hermes_home_override, get_process_hermes_home, hermes_home_key,
560	    )
561
562	    env = dict(base)
563	    scope = current_secret_scope()
564	    if inherit_credentials and is_multiplex_active() and scope is None and not get_hermes_home_override():
565	        raise UnscopedSecretError("Credential child requires a bound profile")
566	    target = _child_policy_home()
567	    if target is None:
568	        env.update(extra or {})
569	        return env
570	    launch = launch_profile_home() if get_hermes_home_override() or is_multiplex_active() else get_process_hermes_home()
571	    routed = hermes_home_key(launch) != hermes_home_key(target)
572	    scoped_credentials = inherit_credentials and (routed or is_multiplex_active())
573	    owned: set[str] = set()
574	    if routed or scoped_credentials:
575	        launch_names = set(load_env_file(launch / ".env"))
576	        launch_names.update(load_env_file(launch / ".op.env"))
577	        launch_names.update(loaded_profile_env_keys(launch))
578	        launch_names.update(get_secret_source_values(launch))
579	        owned = {name.upper() for name in launch_names if not _is_global_env(name)}
580	        owned.update(platform_manifest_secret_envs(launch))
581	        owned.update(_provider_secret_env())
582	        for name in list(env):
583	            upper = name.upper()
584	            real = upper.removeprefix(_HERMES_PROVIDER_ENV_FORCE_PREFIX.upper())
585	            if real in owned:
586	                env.pop(name)
587	        values = dict(scope) if scope is not None else build_profile_secret_scope(target)
588	        for name, value in values.items():
589	            if value is not None and not _is_global_env(name):
590	                env[name] = value
591	    for name, value in (extra or {}).items():
592	        real = name.upper().removeprefix(_HERMES_PROVIDER_ENV_FORCE_PREFIX.upper())
593	        if real not in owned:
594	            env[name] = value
595	    return env
596
597
598	def _inject_session_context_env(env: dict) -> None:

... (gap) ...

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

... (gap) ...

832	)
833
834
835	def hermes_subprocess_env(
836	    *,
837	    inherit_credentials: bool = False,
838	    allowlist_only: bool = False,
839	    extra: Mapping[str, str] | None = None,
840	    credential_keys: Iterable[str] = (),
841	) -> dict[str, str]:
842	    """Build a sanitized environment dict for a spawned subprocess.
843
844	    Centralized helper for the **non-terminal** spawn surface (browser,
845	    ACP/CLI executors, computer-use driver, dep-ensure, TUI Node host,
846	    detached gateway).  Use this instead of copying ``os.environ`` directly
847	    so strip-by-default is the uniform policy across every spawn site, with a
848	    single source of truth (``_HERMES_PROVIDER_ENV_BLOCKLIST``).  The terminal
849	    / execute_code path keeps using :func:`_sanitize_subprocess_env`, which is
850	    skill-aware (``env_passthrough``); this helper is for spawns that have no
851	    skill-passthrough concept.
852
853	    Two-tier stripping:
854
855	    * **Tier 1 (always):** ``_ALWAYS_STRIP_KEYS`` — gateway bot tokens, GitHub
856	      auth, and remote-compute secrets are removed regardless of
857	      ``inherit_credentials``.  No child Hermes spawns legitimately needs them.
858	    * **Tier 2 (conditional):** the rest of ``_HERMES_PROVIDER_ENV_BLOCKLIST``
859	      (LLM provider API keys, tool secrets) is removed unless the caller passes
860	      ``inherit_credentials=True``.
861
862	    Pass ``inherit_credentials=True`` **only** when the child legitimately
863	    needs LLM provider credentials — a user-blessed ``claude`` / ``codex`` /
864	    ``gemini`` CLI executor, or the TUI Node host that makes model calls.  The
865	    flag is grep-able for audit: ``grep -rn 'inherit_credentials=True'`` lists
866	    every spawn site that still receives provider credentials.
867
868	    Callers that need a *specific* non-provider secret (e.g. the browser worker
869	    needs ``BROWSERBASE_API_KEY`` / ``FIRECRAWL_API_KEY``) should call with
870	    ``inherit_credentials=False`` and copy just those keys back from
871	    ``os.environ`` into the returned dict.
872	    """
873	    approved = {key.upper() for key in credential_keys}
874	    if allowlist_only and (inherit_credentials or approved):
875	        raise ValueError("allowlist_only cannot be combined with inherit_credentials")
876
877	    if allowlist_only:
878	        env = {
879	            key: value

... (gap) ...

1627	    return None
1628
1629
1630	def _make_run_env(env: dict) -> dict:
1631	    """Build a run environment with a sane PATH and provider-var stripping."""
1632	    try:
1633	        from tools.env_passthrough import (
1634	            is_env_passthrough as _is_passthrough,
1635	            resolve_passthrough_value as _resolve_passthrough_value,
1636	        )
1637	    except Exception:
1638	        _is_passthrough = lambda _: False  # noqa: E731
1639	        _resolve_passthrough_value = lambda _name, fallback: fallback  # noqa: E731
1640
1641	    merged = _profile_child_base(os.environ, extra=env)
1642	    run_env = {}
1643	    plugin_strip = {key.upper() for key in _plugin_terminal_env_strip_keys()}
1644	    provider_strip = _provider_secret_env()
1645	    for k, v in merged.items():
1646	        if k.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
1647	            real_key = k[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
1648	            if _is_hermes_internal_secret(real_key) or real_key.upper() in plugin_strip:
1649	                continue
1650	            run_env[real_key] = v
1651	        elif _is_hermes_internal_secret(k) or k.upper() in plugin_strip:
1652	            continue
1653	        else:
1654	            passthrough = _is_passthrough(k)
1655	            if k.upper() in provider_strip and not passthrough:
1656	                continue
1657	            value = _resolve_passthrough_value(k, v) if passthrough and (
1658	                k not in env or _CREDENTIAL_ENV_NAME_RE.search(k)
1659	            ) else v
1660	            if value is not None:
1661	                run_env[k] = value
1662	    path_key = _path_env_key(run_env)
1663	    if path_key is not None:
1664	        new_path = _append_missing_sane_path_entries(run_env.get(path_key, ""))
1665	        # On Windows, ensure Git Bash's coreutils dirs (…\usr\bin etc.) are on
1666	        # PATH.  A non-login ``bash -c`` fallback (used when ``bash -l`` is
1667	        # broken) never sources /etc/profile, so without this cat/mktemp/mv and
1668	        # friends are missing and every write_file/terminal call fails (empty
1669	        # error / exit 127).  No-op off Windows and when a login snapshot is
1670	        # healthy (the snapshot re-exports the full PATH inside the shell).
1671	        new_path = _prepend_git_bash_dirs(new_path)
1672	        # Ensure the hermes install dir is reachable so plugins can shell out
1673	        # to bare ``hermes`` via the terminal tool even when the gateway was
1674	        # launched without it on PATH (systemd, service managers, cron, etc.).
1675	        run_env[path_key] = _prepend_hermes_bin_dir(new_path)
1676
1677	    _inject_context_hermes_home(run_env)
1678
1679	    from hermes_constants import apply_subprocess_home_env
1680	    apply_subprocess_home_env(run_env)
1681
1682	    # Bridge ContextVar-based session vars into the subprocess env (with the
1683	    # cross-session leak guard — strips _UNSET vars when a concurrent host is
1684	    # engaged so a sibling session's os.environ mirror can't leak in).
1685	    _inject_session_context_env(run_env)
1686
1687	    _strip_hermes_owned_pythonpath_and_runtime_markers(run_env)
1688
1689	    _apply_windows_msys_bash_env_defaults(run_env)
1690
1691	    run_env = _scrub_delegated_child_kanban_env(run_env)
1692
1693	    return run_env
1694
1695
1696	def _same_path(left: Path, right: Path) -> bool:

... (gap) ...

2079	            raise RuntimeError("Invalid protected environment identifier")
2080	        return tuple(sorted(excluded))
2081
2082	    def _additional_profile_scoped_passthrough_names(self) -> set[str]:
2083	        """Restore current authority after sourcing an older shell snapshot."""
2084	        from agent.secret_scope import _is_global_env, current_secret_scope
2085	        names = set(_provider_secret_env()) | set(_plugin_terminal_env_strip_keys())
2086	        names.update(_registered_adapter_secret_env())
2087	        names.update(_launch_profile_owned_env_names())
2088	        names.update(name for name in (current_secret_scope() or {}) if not _is_global_env(name))
2089	        visible = set(os.environ) | set(self.env)
2090	        snapshot = getattr(getattr(self, "_snapshot_read_context", None), "text", None)
2091	        if snapshot is None:
2092	            try:
2093	                snapshot = Path(self._snapshot_path).read_text(encoding="utf-8")
2094	            except FileNotFoundError:
2095	                snapshot = ""
2096	        declarations = re.findall(r"^declare -([A-Za-z]+) ([A-Za-z_][A-Za-z0-9_]*)(?:=|$)", snapshot, re.MULTILINE)
2097	        visible.update(name for flags, name in declarations if "x" in flags)
2098	        protected = {name.upper() for name in names}
2099	        if any("r" in flags and "x" in flags and
2100	               (name.upper() in protected or _is_hermes_internal_secret(name))
2101	               for flags, name in declarations):
2102	            # A readonly value cannot be removed after source. Refuse without
2103	            # rewriting shell syntax or publishing a partial snapshot.
2104	            raise RuntimeError("Protected readonly export in terminal snapshot")
2105	        # Restoring every possible provider name exceeds Windows' argv limit.
2106	        # Read only snapshot identifiers; values never enter command arguments.
2107	        return {name for name in visible if name.upper() in protected or _is_hermes_internal_secret(name)}
2108
2109	    def __init__(self, cwd: str = "", timeout: int = 60, env: dict = None):
2110	        cwd = _resolve_local_initial_cwd(cwd)
```

**Not shown above — explore these names for their source**

- scripts/master-heartbeat.py: PROVIDER:23, run_hermes_task:143, persist_results:220, print_report:243, _subprocess_env:114, classify_output:124, +7 more
- plugins/dashboard_auth/drain/__init__.py: DrainSecretProvider:140, __init__:148, verify_token:160, start_login:179, complete_login:185, verify_session:192, +4 more
- tools/tool_backend_helpers.py: resolve_provider_secret:163, _scoped_credential:149, resolve_openai_audio_api_key:260
- agent/credential_pool.py: load_pool:3598, has_credentials:805, peek:2454
- hermes_cli/dashboard_auth/base.py: DashboardAuthProvider:113, TokenPrincipal:29, start_login:196, complete_login:199, verify_session:209, refresh_session:212, +3 more
- tools/xai_http.py: _resolve_explicit_xai_api_key:257, resolve_xai_http_credentials:296
- agent/browser_registry.py: list_providers:93, _scoped_providers:50, _providers:49, _lock:53
- tools/tts_tool.py: provider:4485, _resolve_provider_key:79
- tools/env_passthrough.py: _is_hermes_provider_credential:50
- agent/secret_scope.py: is_multiplex_active:50
- ... and 35 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
