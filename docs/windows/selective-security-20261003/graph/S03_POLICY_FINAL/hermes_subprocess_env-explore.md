**Exploration: hermes_subprocess_env**

Found 15 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `hermes_subprocess_env` (tools/environments/local.py:831) — 57 callers in `agent/chat_completion_helpers.py`, `agent/copilot_acp_client.py`, `agent/lsp/client.py`, `agent/lsp/install.py` +21 more; tests: `tests/tools/test_build_subprocess_env.py`, `tests/tools/test_hermes_subprocess_env.py`, `tests/tools/test_local_env_session_leak.py`, `tests/tools/test_child_credential_boundary.py` +2

**Relationships**

**calls:**
- hermes_subprocess_env → items
- hermes_subprocess_env → search
- hermes_subprocess_env → copy
- hermes_subprocess_env → _plugin_terminal_env_strip_keys
- hermes_subprocess_env → _is_hermes_internal_secret
- hermes_subprocess_env → _profile_child_base
- hermes_subprocess_env → _provider_secret_env
- hermes_subprocess_env → _inject_context_hermes_home
- hermes_subprocess_env → apply_subprocess_home_env
- hermes_subprocess_env → _strip_hermes_owned_pythonpath_and_runtime_markers
- hermes_subprocess_env → _apply_windows_msys_bash_env_defaults
- hermes_subprocess_env → _inject_session_context_env
- hermes_subprocess_env → _scrub_delegated_child_kanban_env
- _run_fallback_start_command → hermes_subprocess_env
- _build_subprocess_env → hermes_subprocess_env
- ... and 12 more

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), items(calls), search(calls), _provider_secret_env(calls), _plugin_terminal_env_strip_keys(calls), _is_hermes_internal_secret(calls), _HERMES_PROVIDER_ENV_FORCE_PREFIX(variable), _HERMES_PROVIDER_ENV_BLOCKLIST(variable), _provider_secret_env(function), _inject_context_hermes_home(function), _profile_child_base(function), references(references), instantiates(instantiates), _inject_session_context_env(function), _scrub_delegated_child_kanban_env(function), +12 more

```python
204
205
206	# Hermes-internal env vars that should NOT leak into terminal subprocesses.
207	_HERMES_PROVIDER_ENV_FORCE_PREFIX = "_HERMES_FORCE_"
208
209	# Hermes-managed AWS *inference* credentials for ``auth_type="aws_sdk"``
210	# providers (Bedrock).  Scoped DELIBERATELY NARROW: this lists only the

... (gap) ...

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

528	    return None
529
530
531	def _inject_context_hermes_home(env: dict) -> None:
532	    """Bridge the context-local Hermes home override into subprocess env."""
533	    try:
534	        from hermes_constants import get_hermes_home_override
535
536	        value = get_hermes_home_override()
537	        if value:
538	            env["HERMES_HOME"] = value
539	    except Exception:
540	        pass
541
542
543	def _profile_child_base(

... (gap) ...

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
595	    """Bridge gateway session ContextVars into a subprocess environment dict.
596
597	    ContextVars don't propagate to child processes, so the live session vars
598	    (HERMES_SESSION_*) are bridged onto the child env here.
599
600	    🔴 Cross-session leak guard. The session vars also have a process-global
601	    os.environ mirror (written last-writer-wins as a CLI/cron fallback, never
602	    cleared). Under a concurrent multi-session host (the messaging gateway, ACP
603	    adapter, API server, TUI) that global belongs to *whichever turn wrote it
604	    last* — NOT necessarily this task. A subprocess spawned from a task whose
605	    ContextVar is _UNSET (e.g. a sibling message task that never bound, or one
606	    that inherited another session's context) would otherwise inherit the
607	    FOREIGN global and act on another session's identity.
608
609	    So once the session-context machinery is engaged in this process (any host
610	    has called set_session_vars), the session vars are ContextVar-authoritative:
611	    - ContextVar set (incl. explicitly-empty "") → that value wins, overriding
612	      any stale snapshot/global value.
613	    - ContextVar _UNSET → STRIP the var from the child env rather than inherit
614	      the possibly-foreign process-global.
615	    In a pure single-process CLI/one-shot that never engaged the session-context
616	    system there is no concurrency to leak across, so the inherited fallback is
617	    kept. See gateway/session_context.session_context_engaged and
618	    tests/tools/test_local_env_session_leak.py.
619	    """
620	    try:
621	        from gateway.session_context import (
622	            _UNSET,
623	            _VAR_MAP,
624	            session_context_engaged,
625	        )
626	    except Exception:
627	        return
628
629	    _engaged = session_context_engaged()
630	    for var_name, var in _VAR_MAP.items():
631	        value = var.get()
632	        if value is not _UNSET:
633	            # Explicitly bound (including "") — authoritative for this task.
634	            env[var_name] = "" if value is None else str(value)
635	        elif _engaged:

... (gap) ...

706	    return sanitized
707
708
709	def _scrub_delegated_child_kanban_env(env: dict[str, str]) -> dict[str, str]:
710	    """Strip dispatcher-owned Kanban env from delegate_task child subprocesses."""
711	    try:
712	        from agent.delegation_context import (
713	            is_delegated_child_process_context,
714	            scrub_kanban_env,
715	        )
716
717	        if is_delegated_child_process_context():
718	            return scrub_kanban_env(env)
719	    except Exception:
720	        pass
721	    return env
722
723
724	# Tier-1 secrets: stripped from EVERY spawned subprocess unconditionally —
725	# even when the caller opts into credential inheritance for a model-driving
726	# CLI (claude / codex / gemini).  These are not LLM provider credentials; no
727	# legitimate child Hermes spawns needs them, and they are the highest-value
728	# secrets to keep out of a compromised dependency's reach (gateway bot tokens,
729	# GitHub auth, remote-compute tokens, dashboard session secret).  The set is a
730	# narrow subset of _HERMES_PROVIDER_ENV_BLOCKLIST; provider keys are handled by
731	# the conditional Tier-2 strip in hermes_subprocess_env().
732	_ALWAYS_STRIP_KEYS: frozenset[str] = frozenset({
733	    # GitHub auth
734	    "GH_TOKEN",
735	    "GITHUB_TOKEN",
736	    "GITHUB_APP_ID",
737	    "GITHUB_APP_PRIVATE_KEY_PATH",
738	    "GITHUB_APP_INSTALLATION_ID",
739	    # Gateway / messaging bot tokens and access control
740	    "TELEGRAM_BOT_TOKEN",
741	    "DISCORD_BOT_TOKEN",
742	    "SLACK_BOT_TOKEN",
743	    "SLACK_APP_TOKEN",
744	    "SLACK_SIGNING_SECRET",
745	    "GATEWAY_ALLOWED_USERS",
746	    "GATEWAY_ALLOW_ALL_USERS",
747	    # Gateway relay auth — the ID/secret/delivery-key triplet the gateway
748	    # provisions and persists to the 0600 .env. Stripped unconditionally on
749	    # EVERY spawn surface (terminal + model-driving CLIs) so it can't drift
750	    # between paths: _SECRET / _DELIVERY_KEY are also matched by
751	    # _is_hermes_internal_secret, but _ID has no secret suffix, so it must be
752	    # enumerated here to stay stripped on the inherit_credentials=True path
753	    # (codex / copilot), which skips the Tier-2 blocklist.
754	    "GATEWAY_RELAY_ID",
755	    "GATEWAY_RELAY_SECRET",
756	    "GATEWAY_RELAY_DELIVERY_KEY",
757	    "HASS_TOKEN",
758	    "EMAIL_PASSWORD",
759	    "HERMES_DASHBOARD_SESSION_TOKEN",
760	    "MSGRAPH_CLIENT_SECRET",
761	    "MSGRAPH_WEBHOOK_CLIENT_STATE",
762	    "QQ_STT_API_KEY",
763	    "RAFT_CHANNEL_TOKEN",
764	    # Remote-compute / infrastructure secrets
765	    "MODAL_TOKEN_ID",
766	    "MODAL_TOKEN_SECRET",
767	    "DAYTONA_API_KEY",
768	})
769
770
771	_STRICT_SUBPROCESS_ENV_KEYS: frozenset[str] = frozenset({
772	    "APPDATA",
773	    "CHERE_INVOKING",
774	    "CODEX_HOME",
775	    "COLORTERM",
776	    "COMSPEC",
777	    "FORCE_COLOR",
778	    "GOBIN",
779	    "HERMES_DELEGATED_CHILD_CONTEXT",
780	    "HERMES_HOME",
781	    "HERMES_KANBAN_DB",
782	    "HERMES_KANBAN_ROOT",
783	    "HERMES_KANBAN_RUN_ID",
784	    "HERMES_KANBAN_TASK",
785	    "HERMES_KANBAN_WORKSPACE",
786	    "HOME",
787	    "HOMEDRIVE",
788	    "HOMEPATH",
789	    "LANG",
790	    "LANGUAGE",
791	    "LOCALAPPDATA",
792	    "LOGNAME",
793	    "MSYSTEM",
794	    "NO_COLOR",
795	    "NUMBER_OF_PROCESSORS",
796	    "OS",
797	    "PATH",
798	    "PATHEXT",
799	    "PROCESSOR_ARCHITECTURE",
800	    "PROCESSOR_IDENTIFIER",
801	    "PROCESSOR_LEVEL",
802	    "PROCESSOR_REVISION",
803	    "PROGRAMDATA",
804	    "PROGRAMFILES",
805	    "PROGRAMFILES(X86)",
806	    "PROGRAMW6432",
807	    "PYTHONIOENCODING",
808	    "PYTHONUTF8",
809	    "SHELL",
810	    "SYSTEMDRIVE",
811	    "SYSTEMROOT",
812	    "TEMP",
813	    "TERM",
814	    "TMP",
815	    "TMPDIR",
816	    "USER",
817	    "USERNAME",
818	    "USERPROFILE",
819	    "WINDIR",
820	    "XDG_CACHE_HOME",
821	    "XDG_CONFIG_HOME",
822	    "XDG_DATA_HOME",
823	})
824
825	_CREDENTIAL_ENV_NAME_RE = re.compile(
826	    r"(?:^|_)(?:API_KEY|ACCESS_KEY|AUTH|CREDENTIALS?|PASSWORD|PRIVATE_KEY|SECRET|TOKEN)(?:$|_)",
827	    re.IGNORECASE,
828	)
829
830
831	def hermes_subprocess_env(
832	    *,
833	    inherit_credentials: bool = False,
834	    allowlist_only: bool = False,
835	    extra: Mapping[str, str] | None = None,
836	    credential_keys: Iterable[str] = (),
837	) -> dict[str, str]:
838	    """Build a sanitized environment dict for a spawned subprocess.
839
840	    Centralized helper for the **non-terminal** spawn surface (browser,
841	    ACP/CLI executors, computer-use driver, dep-ensure, TUI Node host,
842	    detached gateway).  Use this instead of copying ``os.environ`` directly
843	    so strip-by-default is the uniform policy across every spawn site, with a
844	    single source of truth (``_HERMES_PROVIDER_ENV_BLOCKLIST``).  The terminal
845	    / execute_code path keeps using :func:`_sanitize_subprocess_env`, which is
846	    skill-aware (``env_passthrough``); this helper is for spawns that have no
847	    skill-passthrough concept.
848
849	    Two-tier stripping:
850
851	    * **Tier 1 (always):** ``_ALWAYS_STRIP_KEYS`` — gateway bot tokens, GitHub
852	      auth, and remote-compute secrets are removed regardless of
853	      ``inherit_credentials``.  No child Hermes spawns legitimately needs them.
854	    * **Tier 2 (conditional):** the rest of ``_HERMES_PROVIDER_ENV_BLOCKLIST``
855	      (LLM provider API keys, tool secrets) is removed unless the caller passes
856	      ``inherit_credentials=True``.
857
858	    Pass ``inherit_credentials=True`` **only** when the child legitimately
859	    needs LLM provider credentials — a user-blessed ``claude`` / ``codex`` /
860	    ``gemini`` CLI executor, or the TUI Node host that makes model calls.  The
861	    flag is grep-able for audit: ``grep -rn 'inherit_credentials=True'`` lists
862	    every spawn site that still receives provider credentials.
863
864	    Callers that need a *specific* non-provider secret (e.g. the browser worker
865	    needs ``BROWSERBASE_API_KEY`` / ``FIRECRAWL_API_KEY``) should call with
866	    ``inherit_credentials=False`` and copy just those keys back from
867	    ``os.environ`` into the returned dict.
868	    """
869	    approved = {key.upper() for key in credential_keys}
870	    if allowlist_only and (inherit_credentials or approved):
871	        raise ValueError("allowlist_only cannot be combined with inherit_credentials")
872
873	    if allowlist_only:
874	        env = {
875	            key: value
876	            for key, value in os.environ.items()
877	            if key.upper() in _STRICT_SUBPROCESS_ENV_KEYS
878	            or (
879	                key.upper().startswith("LC_")
880	                and not _CREDENTIAL_ENV_NAME_RE.search(key.upper())
881	            )
882	        }
883	    else:
884	        env = os.environ.copy()
885
886	    for key, value in (extra or {}).items():
887	        upper = key.upper()
888	        if allowlist_only and (
889	            key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX)
890	            or upper in _ALWAYS_STRIP_KEYS
891	            or upper in _HERMES_PROVIDER_ENV_BLOCKLIST
892	            or key in _plugin_terminal_env_strip_keys()
893	            or _is_hermes_internal_secret(key)
894	            or _CREDENTIAL_ENV_NAME_RE.search(upper)
895	        ):
896	            raise ValueError(f"credential-shaped environment key is not allowed: {key}")
897
898	    env = _profile_child_base(env, inherit_credentials=inherit_credentials or bool(approved), extra=extra)
899	    if allowlist_only:
900	        env = {
901	            key: value for key, value in env.items()
902	            if key in (extra or {}) or key.upper() in _STRICT_SUBPROCESS_ENV_KEYS
903	            or (key.upper().startswith("LC_") and not _CREDENTIAL_ENV_NAME_RE.search(key))
904	        }
905
906	    # Compare names case-insensitively even when the host uses a plain dict.
907	    # A POSIX caller can pass Windows-style case variants to a child.
908	    always_strip = {key.upper() for key in _ALWAYS_STRIP_KEYS}
909	    always_strip.update(key.upper() for key in _plugin_terminal_env_strip_keys())
910	    provider_strip = _provider_secret_env()
911	    for key in list(env):
912	        upper = key.upper()
913	        if upper in always_strip or (not inherit_credentials and upper in provider_strip and upper not in approved):
914	            env.pop(key, None)
915	    # Internal routing hints and Hermes-internal dynamic secrets
916	    # (``AUXILIARY_<TASK>_API_KEY`` / ``_BASE_URL`` side-LLM credentials,
917	    # ``GATEWAY_RELAY_*`` relay-auth material) must never reach a child,
918	    # regardless of ``inherit_credentials`` — a model-driving CLI has no
919	    # legitimate use for them. See :func:`_is_hermes_internal_secret`.
920	    for key in list(env):
921	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
922	            env.pop(key, None)
923	        elif _is_hermes_internal_secret(key):
924	            env.pop(key, None)
925
926	    if not inherit_credentials:
927	        # Tier 2 — strip provider/tool credentials unless explicitly inherited.
928	        for key in _HERMES_PROVIDER_ENV_BLOCKLIST:
929	            if key.upper() not in approved:
930	                env.pop(key, None)
931
932	    # Windows UTF-8 safety for spawned processes (#31420).
933	    env.setdefault("PYTHONUTF8", "1")
934
935	    _inject_context_hermes_home(env)
936	    from hermes_constants import apply_subprocess_home_env
937	    apply_subprocess_home_env(env)
938
939	    _strip_hermes_owned_pythonpath_and_runtime_markers(env)
940
941	    _apply_windows_msys_bash_env_defaults(env)
942
943	    # Cross-session leak guard, same as the terminal spawn paths: this helper
944	    # copies os.environ, whose HERMES_SESSION_* mirror is a last-writer-wins
945	    # global under a concurrent multi-session host. A caller that re-binds the
946	    # session identity explicitly (slash_worker/ACP via --session-key argv) is
947	    # unaffected — bound ContextVars win here — but a caller that spawns without
948	    # re-binding (e.g. tui_gateway cli.exec) would otherwise inherit a FOREIGN
949	    # session's identity. Strip _UNSET session vars when engaged so that can't
950	    # happen; single uniform policy across every spawn surface.
951	    _inject_session_context_env(env)
952
953	    # Non-terminal subprocess helpers (browser, lazy-deps, TUI/ACP hosts, etc.)
954	    # also need the delegate_task child lineage marker.  Otherwise a child
955	    # context that later imports Kanban DB code in the spawned process would
956	    # still see the parent's HERMES_HOME but lose the DB mutation guard.
957	    env = _scrub_delegated_child_kanban_env(env)
958
959	    return env
960
961
962	def build_subprocess_env(
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
- hermes_cli/nous_subscription.py: items:128
- ... and 9 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
