**Exploration: _provider_secret_env**

Found 11 symbols across 1 file.

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
- _provider_secret_env → _HERMES_PROVIDER_ENV_BLOCKLIST
- _provider_secret_env → _CHILD_SECRET_POLICY
- list_providers → _lock
- main → HERMES_CMD
- hermes_subprocess_env → _HERMES_PROVIDER_ENV_BLOCKLIST
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
- ... and 68 more

**instantiates:**
- register → DrainSecretProvider
- verify_token → TokenPrincipal

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _provider_secret_env(calls), _plugin_terminal_env_strip_keys(calls), get(calls), _registered_adapter_secret_env(calls), platform_manifest_secret_envs(calls), _profile_child_base(calls), _HERMES_PROVIDER_ENV_BLOCKLIST(variable), _CHILD_SECRET_POLICY(variable), _provider_secret_env(function), provider_profile_secret_envs(calls), _plugin_terminal_env_strip_keys(function), _registered_adapter_secret_env(function), _profile_child_base(function), references(references), +5 more

```python
375	    return frozenset(blocked)
376
377
378	_HERMES_PROVIDER_ENV_BLOCKLIST = _build_provider_env_blocklist()
379	_CHILD_SECRET_POLICY: ContextVar[tuple[frozenset[str], frozenset[str]] | None] = ContextVar(
380	    "local_child_secret_policy", default=None,
381	)
382
383
384	def _provider_secret_env() -> frozenset[str]:
385	    """Resolve current provider declarations, including late OAuth profiles."""
386	    policy = _CHILD_SECRET_POLICY.get()
387	    if policy is not None:
388	        return policy[1]
389	    from hermes_cli.config import provider_profile_secret_envs
390	    names = {name.upper() for name in _HERMES_PROVIDER_ENV_BLOCKLIST}
391	    names.update(provider_profile_secret_envs())
392	    names.update(_registered_adapter_secret_env())
393	    return frozenset(names)
394
395	# Active-virtualenv markers that must NOT leak into terminal subprocesses.
396	# The gateway runs inside its own venv, so its process environment carries

... (gap) ...

473	    return False
474
475
476	def _plugin_terminal_env_strip_keys() -> frozenset:
477	    """Credential env keys owned by plugin-registered terminal backends.
478
479	    Computed at call time (not import time) because plugins register after
480	    this module is imported. Treated as Tier-1: stripped from every spawned
481	    subprocess unconditionally, exactly like MODAL_*/DAYTONA_API_KEY in
482	    ``_ALWAYS_STRIP_KEYS``. An unreadable security declaration blocks spawn.
483	    """
484	    policy = _CHILD_SECRET_POLICY.get()
485	    if policy is not None:
486	        return policy[0]
487	    from agent.terminal_env_registry import plugin_strip_env_keys
488	    from hermes_cli.config import OPTIONAL_ENV_VARS, platform_manifest_secret_envs
489
490	    adapter_secrets = frozenset(
491	        name.upper() for name, meta in OPTIONAL_ENV_VARS.items()
492	        if meta.get("category") == "messaging" and meta.get("password")
493	    )
494	    return plugin_strip_env_keys() | platform_manifest_secret_envs(_child_policy_home()) | adapter_secrets | _ALWAYS_STRIP_KEYS
495
496
497	def _registered_adapter_secret_env() -> frozenset[str]:
498	    """Unchecked runtime declarations are Tier 2, never core reclassification."""
499	    from gateway.platform_registry import platform_registry
500	    from hermes_cli.config import PLATFORM_SECRET_ENV_SUFFIXES
501	    return frozenset(
502	        name.upper() for name in platform_registry.required_env_names(include_profile=_child_policy_home() is not None)
503	        if name.upper().endswith(PLATFORM_SECRET_ENV_SUFFIXES)
504	    )
505
506
507	def _launch_profile_owned_env_names() -> frozenset[str]:

... (gap) ...

540	        pass
541
542
543	def _profile_child_base(
544	    base: Mapping[str, str], *, inherit_credentials: bool = False,
545	    extra: Mapping[str, str] | None = None,
546	) -> dict:
547	    """Resolve routed profile values before applying the child security tier."""
548	    from agent.secret_scope import (
549	        UnscopedSecretError, _is_global_env, build_profile_secret_scope,
550	        current_secret_scope, is_multiplex_active, load_env_file,
551	    )
552	    from hermes_cli.config import platform_manifest_secret_envs
553	    from hermes_cli.env_loader import get_secret_source_values, loaded_profile_env_keys, launch_profile_home
554	    from hermes_constants import (
555	        get_hermes_home, get_hermes_home_override, get_process_hermes_home, hermes_home_key,
556	    )
557
558	    env = dict(base)
559	    scope = current_secret_scope()
560	    if inherit_credentials and is_multiplex_active() and scope is None and not get_hermes_home_override():
561	        raise UnscopedSecretError("Credential child requires a bound profile")
562	    target = _child_policy_home()
563	    if target is None:
564	        env.update(extra or {})
565	        return env
566	    launch = launch_profile_home() if get_hermes_home_override() or is_multiplex_active() else get_process_hermes_home()
567	    routed = hermes_home_key(launch) != hermes_home_key(target)
568	    scoped_credentials = inherit_credentials and (routed or is_multiplex_active())
569	    owned: set[str] = set()
570	    if routed or scoped_credentials:
571	        launch_names = set(load_env_file(launch / ".env"))
572	        launch_names.update(load_env_file(launch / ".op.env"))
573	        launch_names.update(loaded_profile_env_keys(launch))
574	        launch_names.update(get_secret_source_values(launch))
575	        owned = {name.upper() for name in launch_names if not _is_global_env(name)}
576	        owned.update(platform_manifest_secret_envs(launch))
577	        owned.update(_provider_secret_env())
578	        for name in list(env):
579	            upper = name.upper()
580	            real = upper.removeprefix(_HERMES_PROVIDER_ENV_FORCE_PREFIX.upper())
581	            if real in owned:
582	                env.pop(name)
583	        values = dict(scope) if scope is not None else build_profile_secret_scope(target)
584	        for name, value in values.items():
585	            if value is not None and not _is_global_env(name):
586	                env[name] = value
587	    for name, value in (extra or {}).items():
588	        real = name.upper().removeprefix(_HERMES_PROVIDER_ENV_FORCE_PREFIX.upper())
589	        if real not in owned:
590	            env[name] = value
591	    return env
592
593
594	def _inject_session_context_env(env: dict) -> None:

... (gap) ...

638	            env.pop(var_name, None)
639
640
641	def _sanitize_subprocess_env(base_env: dict | None, extra_env: dict | None = None) -> dict:
642	    """Filter Hermes-managed secrets from a subprocess environment."""
643	    try:
644	        from tools.env_passthrough import (
645	            is_env_passthrough as _is_passthrough,
646	            resolve_passthrough_value as _resolve_passthrough_value,
647	        )
648	    except Exception:
649	        _is_passthrough = lambda _: False  # noqa: E731
650	        _resolve_passthrough_value = lambda _name, fallback: fallback  # noqa: E731
651
652	    sanitized: dict[str, str] = {}
653	    _plugin_strip = {key.upper() for key in _plugin_terminal_env_strip_keys()}
654	    _provider_strip = _provider_secret_env()
655
656	    effective = _profile_child_base(base_env or {}, extra=extra_env)
657	    for key, value in effective.items():
658	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
659	            if key not in (extra_env or {}):
660	                continue
661	            real_key = key[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
662	            if _is_hermes_internal_secret(real_key) or real_key.upper() in _plugin_strip:
663	                continue
664	            sanitized[real_key] = value
665	            continue
666	        if _is_hermes_internal_secret(key):
667	            continue
668	        if key.upper() in _plugin_strip:
669	            continue
670	        passthrough = _is_passthrough(key)
671	        if key.upper() in _provider_strip and not passthrough:
672	            continue
673	        resolved = _resolve_passthrough_value(key, value) if passthrough and (
674	            key not in (extra_env or {}) or _CREDENTIAL_ENV_NAME_RE.search(key)
675	        ) else value
676	        if resolved is not None:
677	            sanitized[key] = resolved
678
679	    _inject_context_hermes_home(sanitized)
680
681	    from hermes_constants import apply_subprocess_home_env
682	    apply_subprocess_home_env(sanitized)
683
684	    # Same cross-session leak guard as _make_run_env, for the background/PTY
685	    # spawn path (process_registry.spawn_local builds env via this function).
686	    _inject_session_context_env(sanitized)
687
688	    # Filter PYTHONPATH before removing VIRTUAL_ENV: legacy Windows launchers
689	    # can run the gateway under a base interpreter while VIRTUAL_ENV identifies
690	    # the separate Hermes runtime venv.  The filter validates that relationship
691	    # against the repo layout before trusting it.
692	    _strip_hermes_owned_pythonpath_and_runtime_markers(sanitized)
693
694	    # Keep bare ``hermes`` invocations available to child jobs even when the
695	    # gateway was launched by a service manager or cron without the console
696	    # script's directory on PATH.  The terminal environment already applies
697	    # this invariant; Cron scripts use this sanitizer directly (#92998).
698	    path_key = _path_env_key(sanitized)
699	    if path_key is not None:
700	        sanitized[path_key] = _prepend_hermes_bin_dir(sanitized.get(path_key, ""))
701
702	    _apply_windows_msys_bash_env_defaults(sanitized)
703
704	    sanitized = _scrub_delegated_child_kanban_env(sanitized)
705
706	    return sanitized
707
708
709	def _scrub_delegated_child_kanban_env(env: dict[str, str]) -> dict[str, str]:

... (gap) ...

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

... (gap) ...

2075	            raise RuntimeError("Invalid protected environment identifier")
2076	        return tuple(sorted(excluded))
2077
2078	    def _additional_profile_scoped_passthrough_names(self) -> set[str]:
2079	        """Restore current authority after sourcing an older shell snapshot."""
2080	        from agent.secret_scope import _is_global_env, current_secret_scope
2081	        names = set(_provider_secret_env()) | set(_plugin_terminal_env_strip_keys())
2082	        names.update(_registered_adapter_secret_env())
2083	        names.update(_launch_profile_owned_env_names())
2084	        names.update(name for name in (current_secret_scope() or {}) if not _is_global_env(name))
2085	        visible = set(os.environ) | set(self.env)
2086	        snapshot = getattr(getattr(self, "_snapshot_read_context", None), "text", None)
2087	        if snapshot is None:
2088	            try:
2089	                snapshot = Path(self._snapshot_path).read_text(encoding="utf-8")
2090	            except FileNotFoundError:
2091	                snapshot = ""
2092	        declarations = re.findall(r"^declare -([A-Za-z]+) ([A-Za-z_][A-Za-z0-9_]*)(?:=|$)", snapshot, re.MULTILINE)
2093	        visible.update(name for flags, name in declarations if "x" in flags)
2094	        protected = {name.upper() for name in names}
2095	        if hasattr(getattr(self, "_snapshot_read_context", None), "text"):
2096	            # Compare this operation's declarations, not shared restoration
2097	            # history accumulated by other concurrently served profiles.
2098	            self._snapshot_read_context.authority = frozenset(
2099	                protected | {name.upper() for name in visible if _is_hermes_internal_secret(name)}
2100	            )
2101	        readonly_protected = protected | {name.upper() for name in self._snapshot_passthrough_names}
2102	        if any("r" in flags and "x" in flags and
2103	               (name.upper() in readonly_protected or _is_hermes_internal_secret(name))
2104	               for flags, name in declarations):
2105	            # A readonly value cannot be removed after source. Refuse without
2106	            # rewriting shell syntax or publishing a partial snapshot.
2107	            raise RuntimeError("Protected readonly export in terminal snapshot")
2108	        # Restoring every possible provider name exceeds Windows' argv limit.
2109	        # Read only snapshot identifiers; values never enter command arguments.
2110	        return {name for name in visible if name.upper() in protected or _is_hermes_internal_secret(name)}
2111
2112	    def __init__(self, cwd: str = "", timeout: int = 60, env: dict = None):
2113	        cwd = _resolve_local_initial_cwd(cwd)

... (gap) ...

2219	        """Rewrite native/mixed Windows paths before quoting for Git Bash."""
2220	        return _quote_bash_path(path)
2221
2222	    def _run_bash(self, cmd_string: str, *, login: bool = False,
2223	                  timeout: int = 120,
2224	                  stdin_data: str | None = None) -> subprocess.Popen:
2225	        lock = getattr(self, "_snapshot_copy_lock", None)
2226	        snapshot = None
2227	        if lock is not None:
2228	            with lock:
2229	                snapshot = self._snapshot_copies.pop(cmd_string, None)
2230	        pinned = snapshot[0] if snapshot else None
2231	        policy_token = None
2232	        try:
2233	            # One immutable policy for this spawn's wrapper and environment.
2234	            # Concurrent registration after this boundary belongs to the next
2235	            # operation; it cannot make these two consumers disagree.
2236	            policy = (_plugin_terminal_env_strip_keys(), _provider_secret_env())
2237	            policy_token = _CHILD_SECRET_POLICY.set(policy)
2238	            if snapshot:
2239	                self._snapshot_read_context.text = Path(pinned).read_text(encoding="utf-8")
2240	                try:
2241	                    self._snapshot_excluded_passthrough_names()
2242	                    current = self._snapshot_read_context.authority
2243	                finally:
2244	                    del self._snapshot_read_context.text
2245	                    if hasattr(self._snapshot_read_context, "authority"):
2246	                        del self._snapshot_read_context.authority
2247	                if current != snapshot[1]:
2248	                    raise RuntimeError("Terminal credential declaration authority changed before spawn")
```

**Not shown above — explore these names for their source**

- scripts/master-heartbeat.py: PROVIDER:23, run_hermes_task:143, persist_results:220, print_report:243, _subprocess_env:114, classify_output:124, +7 more
- plugins/dashboard_auth/drain/__init__.py: DrainSecretProvider:140, __init__:148, verify_token:160, start_login:179, complete_login:185, verify_session:192, +4 more
- hermes_cli/config.py: provider_profile_secret_envs:6217, platform_manifest_secret_envs:6236, _inject_profile_env_vars:6154
- hermes_cli/dashboard_auth/base.py: DashboardAuthProvider:113, TokenPrincipal:29, start_login:196, complete_login:199, verify_session:209, refresh_session:212, +3 more
- hermes_cli/dashboard_auth/registry.py: list_providers:98, _merged:25, list_token_providers:104, list_session_providers:117, _lock:20
- hermes_cli/tools_config.py: _reap_after_timeout:1835, _run_cua_driver_installer:1619, _plugin_image_gen_providers:3273, _plugin_video_gen_providers:3313, _plugin_tts_providers:3502, _toolset_needs_configuration_prompt:3881
- tools/env_passthrough.py: _is_hermes_provider_credential:50
- tests/plugins/test_scrapling_feeds.py: get:98, _Fetcher:96
- plugins/shinka-osint/policy.py: is_scenario_permitted:102, ensure_priority_in_selection:171
- tools/website_policy.py: load_website_blocklist:131, check_website_access:233
- ... and 34 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
