**Exploration: hermes_subprocess_env**

Found 14 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `hermes_subprocess_env` (tools/environments/local.py:777) — 56 callers in `agent/chat_completion_helpers.py`, `agent/copilot_acp_client.py`, `agent/lsp/client.py`, `agent/lsp/install.py` +20 more; tests: `tests/tools/test_build_subprocess_env.py`, `tests/tools/test_hermes_subprocess_env.py`, `tests/tools/test_local_env_session_leak.py`, `tests/tools/test_local_env_windows_msys.py` +2

**Relationships**

**calls:**
- hermes_subprocess_env → items
- hermes_subprocess_env → search
- hermes_subprocess_env → copy
- hermes_subprocess_env → _plugin_terminal_env_strip_keys
- hermes_subprocess_env → _is_hermes_internal_secret
- hermes_subprocess_env → _profile_child_base
- hermes_subprocess_env → _inject_context_hermes_home
- hermes_subprocess_env → apply_subprocess_home_env
- hermes_subprocess_env → _strip_hermes_owned_pythonpath_and_runtime_markers
- hermes_subprocess_env → _apply_windows_msys_bash_env_defaults
- hermes_subprocess_env → _inject_session_context_env
- hermes_subprocess_env → _scrub_delegated_child_kanban_env
- _run_fallback_start_command → hermes_subprocess_env
- _build_subprocess_env → hermes_subprocess_env
- _spawn → hermes_subprocess_env
- ... and 11 more

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), items(calls), search(calls), _plugin_terminal_env_strip_keys(calls), _is_hermes_internal_secret(calls), _HERMES_PROVIDER_ENV_FORCE_PREFIX(variable), _HERMES_PROVIDER_ENV_BLOCKLIST(variable), _is_hermes_internal_secret(function), _plugin_terminal_env_strip_keys(function), _inject_context_hermes_home(function), _profile_child_base(function), references(references), instantiates(instantiates), _inject_session_context_env(function), _scrub_delegated_child_kanban_env(function), +13 more

```python
202
203
204	# Hermes-internal env vars that should NOT leak into terminal subprocesses.
205	_HERMES_PROVIDER_ENV_FORCE_PREFIX = "_HERMES_FORCE_"
206
207	# Hermes-managed AWS *inference* credentials for ``auth_type="aws_sdk"``
208	# providers (Bedrock).  Scoped DELIBERATELY NARROW: this lists only the

... (gap) ...

373	    return frozenset(blocked)
374
375
376	_HERMES_PROVIDER_ENV_BLOCKLIST = _build_provider_env_blocklist()
377
378	# Active-virtualenv markers that must NOT leak into terminal subprocesses.
379	# The gateway runs inside its own venv, so its process environment carries

... (gap) ...

456	    return False
457
458
459	def _plugin_terminal_env_strip_keys() -> frozenset:
460	    """Credential env keys owned by plugin-registered terminal backends.
461
462	    Computed at call time (not import time) because plugins register after
463	    this module is imported. Treated as Tier-1: stripped from every spawned
464	    subprocess unconditionally, exactly like MODAL_*/DAYTONA_API_KEY in
465	    ``_ALWAYS_STRIP_KEYS``. An unreadable security declaration blocks spawn.
466	    """
467	    from agent.terminal_env_registry import plugin_strip_env_keys
468	    from hermes_cli.config import platform_manifest_secret_envs
469
470	    return plugin_strip_env_keys() | platform_manifest_secret_envs(_child_policy_home())
471
472
473	def _child_policy_home() -> Path | None:
474	    """A minimal OS environment may have no resolvable profile directory."""
475	    from hermes_constants import get_hermes_home, get_hermes_home_override
476
477	    home_names = ("HERMES_HOME", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE") if _IS_WINDOWS else ("HERMES_HOME", "HOME")
478	    if get_hermes_home_override() or any(os.environ.get(name) for name in home_names):
479	        return get_hermes_home()
480	    return None
481
482
483	def _inject_context_hermes_home(env: dict) -> None:
484	    """Bridge the context-local Hermes home override into subprocess env."""
485	    try:
486	        from hermes_constants import get_hermes_home_override
487
488	        value = get_hermes_home_override()
489	        if value:
490	            env["HERMES_HOME"] = value
491	    except Exception:
492	        pass
493
494
495	def _profile_child_base(

... (gap) ...

507	        get_hermes_home, get_hermes_home_override, get_process_hermes_home, hermes_home_key,
508	    )
509
510	    env = dict(base)
511	    scope = current_secret_scope()
512	    if inherit_credentials and is_multiplex_active() and scope is None and not get_hermes_home_override():
513	        raise UnscopedSecretError("Credential child requires a bound profile")
514	    target = _child_policy_home()
515	    if target is None:
516	        env.update(extra or {})
517	        return env
518	    launch = launch_profile_home() if get_hermes_home_override() or is_multiplex_active() else get_process_hermes_home()
519	    routed = hermes_home_key(launch) != hermes_home_key(target)
520	    scoped_credentials = inherit_credentials and (routed or is_multiplex_active())
521	    owned: set[str] = set()
522	    if routed or scoped_credentials:
523	        launch_names = set(load_env_file(launch / ".env"))
524	        launch_names.update(load_env_file(launch / ".op.env"))
525	        launch_names.update(loaded_profile_env_keys(launch))
526	        launch_names.update(get_secret_source_values(launch))
527	        owned = {name.upper() for name in launch_names if not _is_global_env(name)}

... (gap) ...

543	    return env
544
545
546	def _inject_session_context_env(env: dict) -> None:
547	    """Bridge gateway session ContextVars into a subprocess environment dict.
548
549	    ContextVars don't propagate to child processes, so the live session vars
550	    (HERMES_SESSION_*) are bridged onto the child env here.
551
552	    🔴 Cross-session leak guard. The session vars also have a process-global
553	    os.environ mirror (written last-writer-wins as a CLI/cron fallback, never
554	    cleared). Under a concurrent multi-session host (the messaging gateway, ACP
555	    adapter, API server, TUI) that global belongs to *whichever turn wrote it
556	    last* — NOT necessarily this task. A subprocess spawned from a task whose
557	    ContextVar is _UNSET (e.g. a sibling message task that never bound, or one
558	    that inherited another session's context) would otherwise inherit the
559	    FOREIGN global and act on another session's identity.
560
561	    So once the session-context machinery is engaged in this process (any host
562	    has called set_session_vars), the session vars are ContextVar-authoritative:
563	    - ContextVar set (incl. explicitly-empty "") → that value wins, overriding
564	      any stale snapshot/global value.
565	    - ContextVar _UNSET → STRIP the var from the child env rather than inherit
566	      the possibly-foreign process-global.
567	    In a pure single-process CLI/one-shot that never engaged the session-context
568	    system there is no concurrency to leak across, so the inherited fallback is
569	    kept. See gateway/session_context.session_context_engaged and
570	    tests/tools/test_local_env_session_leak.py.
571	    """
572	    try:
573	        from gateway.session_context import (
574	            _UNSET,
575	            _VAR_MAP,
576	            session_context_engaged,
577	        )
578	    except Exception:
579	        return
580
581	    _engaged = session_context_engaged()
582	    for var_name, var in _VAR_MAP.items():
583	        value = var.get()
584	        if value is not _UNSET:
585	            # Explicitly bound (including "") — authoritative for this task.

... (gap) ...

656	    return sanitized
657
658
659	def _scrub_delegated_child_kanban_env(env: dict[str, str]) -> dict[str, str]:
660	    """Strip dispatcher-owned Kanban env from delegate_task child subprocesses."""
661	    try:
662	        from agent.delegation_context import (
663	            is_delegated_child_process_context,
664	            scrub_kanban_env,
665	        )
666
667	        if is_delegated_child_process_context():
668	            return scrub_kanban_env(env)
669	    except Exception:
670	        pass
671	    return env
672
673
674	# Tier-1 secrets: stripped from EVERY spawned subprocess unconditionally —
675	# even when the caller opts into credential inheritance for a model-driving
676	# CLI (claude / codex / gemini).  These are not LLM provider credentials; no
677	# legitimate child Hermes spawns needs them, and they are the highest-value
678	# secrets to keep out of a compromised dependency's reach (gateway bot tokens,
679	# GitHub auth, remote-compute tokens, dashboard session secret).  The set is a
680	# narrow subset of _HERMES_PROVIDER_ENV_BLOCKLIST; provider keys are handled by
681	# the conditional Tier-2 strip in hermes_subprocess_env().
682	_ALWAYS_STRIP_KEYS: frozenset[str] = frozenset({
683	    # GitHub auth
684	    "GH_TOKEN",
685	    "GITHUB_TOKEN",
686	    "GITHUB_APP_ID",
687	    "GITHUB_APP_PRIVATE_KEY_PATH",
688	    "GITHUB_APP_INSTALLATION_ID",
689	    # Gateway / messaging bot tokens and access control
690	    "TELEGRAM_BOT_TOKEN",
691	    "DISCORD_BOT_TOKEN",
692	    "SLACK_BOT_TOKEN",
693	    "SLACK_APP_TOKEN",
694	    "SLACK_SIGNING_SECRET",
695	    "GATEWAY_ALLOWED_USERS",
696	    "GATEWAY_ALLOW_ALL_USERS",
697	    # Gateway relay auth — the ID/secret/delivery-key triplet the gateway
698	    # provisions and persists to the 0600 .env. Stripped unconditionally on
699	    # EVERY spawn surface (terminal + model-driving CLIs) so it can't drift
700	    # between paths: _SECRET / _DELIVERY_KEY are also matched by
701	    # _is_hermes_internal_secret, but _ID has no secret suffix, so it must be
702	    # enumerated here to stay stripped on the inherit_credentials=True path
703	    # (codex / copilot), which skips the Tier-2 blocklist.
704	    "GATEWAY_RELAY_ID",
705	    "GATEWAY_RELAY_SECRET",
706	    "GATEWAY_RELAY_DELIVERY_KEY",
707	    "HASS_TOKEN",
708	    "EMAIL_PASSWORD",
709	    "HERMES_DASHBOARD_SESSION_TOKEN",
710	    # Remote-compute / infrastructure secrets
711	    "MODAL_TOKEN_ID",
712	    "MODAL_TOKEN_SECRET",
713	    "DAYTONA_API_KEY",
714	})
715
716
717	_STRICT_SUBPROCESS_ENV_KEYS: frozenset[str] = frozenset({
718	    "APPDATA",
719	    "CHERE_INVOKING",
720	    "CODEX_HOME",
721	    "COLORTERM",
722	    "COMSPEC",
723	    "FORCE_COLOR",
724	    "GOBIN",
725	    "HERMES_DELEGATED_CHILD_CONTEXT",
726	    "HERMES_HOME",
727	    "HERMES_KANBAN_DB",
728	    "HERMES_KANBAN_ROOT",
729	    "HERMES_KANBAN_RUN_ID",
730	    "HERMES_KANBAN_TASK",
731	    "HERMES_KANBAN_WORKSPACE",
732	    "HOME",
733	    "HOMEDRIVE",
734	    "HOMEPATH",
735	    "LANG",
736	    "LANGUAGE",
737	    "LOCALAPPDATA",
738	    "LOGNAME",
739	    "MSYSTEM",
740	    "NO_COLOR",
741	    "NUMBER_OF_PROCESSORS",
742	    "OS",
743	    "PATH",
744	    "PATHEXT",
745	    "PROCESSOR_ARCHITECTURE",
746	    "PROCESSOR_IDENTIFIER",
747	    "PROCESSOR_LEVEL",
748	    "PROCESSOR_REVISION",
749	    "PROGRAMDATA",
750	    "PROGRAMFILES",
751	    "PROGRAMFILES(X86)",
752	    "PROGRAMW6432",
753	    "PYTHONIOENCODING",
754	    "PYTHONUTF8",
755	    "SHELL",
756	    "SYSTEMDRIVE",
757	    "SYSTEMROOT",
758	    "TEMP",
759	    "TERM",
760	    "TMP",
761	    "TMPDIR",
762	    "USER",
763	    "USERNAME",
764	    "USERPROFILE",
765	    "WINDIR",
766	    "XDG_CACHE_HOME",
767	    "XDG_CONFIG_HOME",
768	    "XDG_DATA_HOME",
769	})
770
771	_CREDENTIAL_ENV_NAME_RE = re.compile(
772	    r"(?:^|_)(?:API_KEY|ACCESS_KEY|AUTH|CREDENTIALS?|PASSWORD|PRIVATE_KEY|SECRET|TOKEN)(?:$|_)",
773	    re.IGNORECASE,
774	)
775
776
777	def hermes_subprocess_env(
778	    *,
779	    inherit_credentials: bool = False,
780	    allowlist_only: bool = False,
781	    extra: Mapping[str, str] | None = None,
782	) -> dict[str, str]:
783	    """Build a sanitized environment dict for a spawned subprocess.
784
785	    Centralized helper for the **non-terminal** spawn surface (browser,
786	    ACP/CLI executors, computer-use driver, dep-ensure, TUI Node host,
787	    detached gateway).  Use this instead of copying ``os.environ`` directly
788	    so strip-by-default is the uniform policy across every spawn site, with a
789	    single source of truth (``_HERMES_PROVIDER_ENV_BLOCKLIST``).  The terminal
790	    / execute_code path keeps using :func:`_sanitize_subprocess_env`, which is
791	    skill-aware (``env_passthrough``); this helper is for spawns that have no
792	    skill-passthrough concept.
793
794	    Two-tier stripping:
795
796	    * **Tier 1 (always):** ``_ALWAYS_STRIP_KEYS`` — gateway bot tokens, GitHub
797	      auth, and remote-compute secrets are removed regardless of
798	      ``inherit_credentials``.  No child Hermes spawns legitimately needs them.
799	    * **Tier 2 (conditional):** the rest of ``_HERMES_PROVIDER_ENV_BLOCKLIST``
800	      (LLM provider API keys, tool secrets) is removed unless the caller passes
801	      ``inherit_credentials=True``.
802
803	    Pass ``inherit_credentials=True`` **only** when the child legitimately
804	    needs LLM provider credentials — a user-blessed ``claude`` / ``codex`` /
805	    ``gemini`` CLI executor, or the TUI Node host that makes model calls.  The
806	    flag is grep-able for audit: ``grep -rn 'inherit_credentials=True'`` lists
807	    every spawn site that still receives provider credentials.
808
809	    Callers that need a *specific* non-provider secret (e.g. the browser worker
810	    needs ``BROWSERBASE_API_KEY`` / ``FIRECRAWL_API_KEY``) should call with
811	    ``inherit_credentials=False`` and copy just those keys back from
812	    ``os.environ`` into the returned dict.
813	    """
814	    if allowlist_only and inherit_credentials:
815	        raise ValueError("allowlist_only cannot be combined with inherit_credentials")
816
817	    if allowlist_only:
818	        env = {
819	            key: value
820	            for key, value in os.environ.items()
821	            if key.upper() in _STRICT_SUBPROCESS_ENV_KEYS
822	            or (
823	                key.upper().startswith("LC_")
824	                and not _CREDENTIAL_ENV_NAME_RE.search(key.upper())
825	            )
826	        }
827	    else:
828	        env = os.environ.copy()
829
830	    for key, value in (extra or {}).items():
831	        upper = key.upper()
832	        if allowlist_only and (
833	            key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX)
834	            or upper in _ALWAYS_STRIP_KEYS
835	            or upper in _HERMES_PROVIDER_ENV_BLOCKLIST
836	            or key in _plugin_terminal_env_strip_keys()
837	            or _is_hermes_internal_secret(key)
838	            or _CREDENTIAL_ENV_NAME_RE.search(upper)
839	        ):
840	            raise ValueError(f"credential-shaped environment key is not allowed: {key}")
841
842	    env = _profile_child_base(env, inherit_credentials=inherit_credentials, extra=extra)
843	    if allowlist_only:
844	        env = {
845	            key: value for key, value in env.items()
846	            if key in (extra or {}) or key.upper() in _STRICT_SUBPROCESS_ENV_KEYS
847	            or (key.upper().startswith("LC_") and not _CREDENTIAL_ENV_NAME_RE.search(key))
848	        }
849
850	    # Compare names case-insensitively even when the host uses a plain dict.
851	    # A POSIX caller can pass Windows-style case variants to a child.
852	    always_strip = {key.upper() for key in _ALWAYS_STRIP_KEYS}
853	    always_strip.update(key.upper() for key in _plugin_terminal_env_strip_keys())
854	    provider_strip = {key.upper() for key in _HERMES_PROVIDER_ENV_BLOCKLIST}
855	    for key in list(env):
856	        upper = key.upper()
857	        if upper in always_strip or (not inherit_credentials and upper in provider_strip):
858	            env.pop(key, None)
859	    # Internal routing hints and Hermes-internal dynamic secrets
860	    # (``AUXILIARY_<TASK>_API_KEY`` / ``_BASE_URL`` side-LLM credentials,
861	    # ``GATEWAY_RELAY_*`` relay-auth material) must never reach a child,
862	    # regardless of ``inherit_credentials`` — a model-driving CLI has no
863	    # legitimate use for them. See :func:`_is_hermes_internal_secret`.
864	    for key in list(env):
865	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
866	            env.pop(key, None)
867	        elif _is_hermes_internal_secret(key):
868	            env.pop(key, None)
869
870	    if not inherit_credentials:
871	        # Tier 2 — strip provider/tool credentials unless explicitly inherited.
872	        for key in _HERMES_PROVIDER_ENV_BLOCKLIST:
873	            env.pop(key, None)
874
875	    # Windows UTF-8 safety for spawned processes (#31420).
876	    env.setdefault("PYTHONUTF8", "1")
877
878	    _inject_context_hermes_home(env)
879	    from hermes_constants import apply_subprocess_home_env
880	    apply_subprocess_home_env(env)
881
882	    _strip_hermes_owned_pythonpath_and_runtime_markers(env)
883
884	    _apply_windows_msys_bash_env_defaults(env)
885
886	    # Cross-session leak guard, same as the terminal spawn paths: this helper
887	    # copies os.environ, whose HERMES_SESSION_* mirror is a last-writer-wins
888	    # global under a concurrent multi-session host. A caller that re-binds the
889	    # session identity explicitly (slash_worker/ACP via --session-key argv) is
890	    # unaffected — bound ContextVars win here — but a caller that spawns without
891	    # re-binding (e.g. tui_gateway cli.exec) would otherwise inherit a FOREIGN
892	    # session's identity. Strip _UNSET session vars when engaged so that can't
893	    # happen; single uniform policy across every spawn surface.
894	    _inject_session_context_env(env)
895
896	    # Non-terminal subprocess helpers (browser, lazy-deps, TUI/ACP hosts, etc.)
897	    # also need the delegate_task child lineage marker.  Otherwise a child
898	    # context that later imports Kanban DB code in the spawned process would
899	    # still see the parent's HERMES_HOME but lose the DB mutation guard.
900	    env = _scrub_delegated_child_kanban_env(env)
901
902	    return env
903
904
905	def build_subprocess_env(

... (gap) ...

1814	    return result
1815
1816
1817	def _strip_hermes_owned_pythonpath_and_runtime_markers(env: dict) -> None:
1818	    """Strip Hermes-owned PYTHONPATH entries, then the runtime marker vars.
1819
1820	    Ordering is load-bearing: PYTHONPATH filtering must run BEFORE the
1821	    markers are removed so a validated Windows base-interpreter launch
1822	    (VIRTUAL_ENV -> <repo>/venv) can still prove ownership.
1823	    """
1824	    _strip_hermes_owned_pythonpath(env)
1825	    for _marker in _ACTIVE_VENV_MARKER_VARS:
1826	        env.pop(_marker, None)
1827
1828
1829	def _strip_hermes_owned_pythonpath(env: dict) -> None:
```

**Not shown above — explore these names for their source**

- nix/moduleCommon.nix: env:52, env:188, mcpServersToConfig:182, command:187, args:187, url:190, +17 more
- nix/homeManagerModules.nix: env:386, flake.homeManagerModules.default:47, cfg:57, cfgPrograms:58, common:59, lib:59, +19 more
- nix/nixosModules.nix: env:474, flake.nixosModules.default:34, cfg:44, common:45, lib:45, effectivePackage:47, +19 more
- agent/lsp/install.py: _install_npm:238, _install_go:308, install.py:1
- agent/transports/codex_app_server.py: __init__:71, check_codex_binary:378, codex_app_server.py:1
- agent/copilot_acp_client.py: _build_subprocess_env:155, copilot_acp_client.py:1
- agent/lsp/client.py: _spawn:308, client.py:1
- agent/skill_preprocessing.py: run_inline_shell:66, skill_preprocessing.py:1
- downstream/security/cli.py: _spawn_watcher:90, cli.py:1
- hermes_cli/dep_ensure.py: ensure_dependency:159, dep_ensure.py:1
- ... and 10 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
