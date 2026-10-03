**Exploration: hermes_subprocess_env**

Found 15 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `hermes_subprocess_env` (tools/environments/local.py:835) — 57 callers in `agent/chat_completion_helpers.py`, `agent/copilot_acp_client.py`, `agent/lsp/client.py`, `agent/lsp/install.py` +21 more; tests: `tests/tools/test_build_subprocess_env.py`, `tests/tools/test_hermes_subprocess_env.py`, `tests/tools/test_local_env_session_leak.py`, `tests/tools/test_local_env_windows_msys.py` +2

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
203
204
205	# Hermes-internal env vars that should NOT leak into terminal subprocesses.
206	_HERMES_PROVIDER_ENV_FORCE_PREFIX = "_HERMES_FORCE_"
207
208	# Hermes-managed AWS *inference* credentials for ``auth_type="aws_sdk"``
209	# providers (Bedrock).  Scoped DELIBERATELY NARROW: this lists only the

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

532	    return None
533
534
535	def _inject_context_hermes_home(env: dict) -> None:
536	    """Bridge the context-local Hermes home override into subprocess env."""
537	    try:
538	        from hermes_constants import get_hermes_home_override
539
540	        value = get_hermes_home_override()
541	        if value:
542	            env["HERMES_HOME"] = value
543	    except Exception:
544	        pass
545
546
547	def _profile_child_base(

... (gap) ...

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

... (gap) ...

595	    return env
596
597
598	def _inject_session_context_env(env: dict) -> None:
599	    """Bridge gateway session ContextVars into a subprocess environment dict.
600
601	    ContextVars don't propagate to child processes, so the live session vars
602	    (HERMES_SESSION_*) are bridged onto the child env here.
603
604	    🔴 Cross-session leak guard. The session vars also have a process-global
605	    os.environ mirror (written last-writer-wins as a CLI/cron fallback, never
606	    cleared). Under a concurrent multi-session host (the messaging gateway, ACP
607	    adapter, API server, TUI) that global belongs to *whichever turn wrote it
608	    last* — NOT necessarily this task. A subprocess spawned from a task whose
609	    ContextVar is _UNSET (e.g. a sibling message task that never bound, or one
610	    that inherited another session's context) would otherwise inherit the
611	    FOREIGN global and act on another session's identity.
612
613	    So once the session-context machinery is engaged in this process (any host
614	    has called set_session_vars), the session vars are ContextVar-authoritative:
615	    - ContextVar set (incl. explicitly-empty "") → that value wins, overriding
616	      any stale snapshot/global value.
617	    - ContextVar _UNSET → STRIP the var from the child env rather than inherit
618	      the possibly-foreign process-global.
619	    In a pure single-process CLI/one-shot that never engaged the session-context
620	    system there is no concurrency to leak across, so the inherited fallback is
621	    kept. See gateway/session_context.session_context_engaged and
622	    tests/tools/test_local_env_session_leak.py.
623	    """
624	    try:
625	        from gateway.session_context import (
626	            _UNSET,
627	            _VAR_MAP,
628	            session_context_engaged,
629	        )
630	    except Exception:
631	        return
632
633	    _engaged = session_context_engaged()
634	    for var_name, var in _VAR_MAP.items():
635	        value = var.get()
636	        if value is not _UNSET:
637	            # Explicitly bound (including "") — authoritative for this task.
638	            env[var_name] = "" if value is None else str(value)
639	        elif _engaged:
640	            # Unset for THIS task while a concurrent host is engaged: drop any

... (gap) ...

710	    return sanitized
711
712
713	def _scrub_delegated_child_kanban_env(env: dict[str, str]) -> dict[str, str]:
714	    """Strip dispatcher-owned Kanban env from delegate_task child subprocesses."""
715	    try:
716	        from agent.delegation_context import (
717	            is_delegated_child_process_context,
718	            scrub_kanban_env,
719	        )
720
721	        if is_delegated_child_process_context():
722	            return scrub_kanban_env(env)
723	    except Exception:
724	        pass
725	    return env
726
727
728	# Tier-1 secrets: stripped from EVERY spawned subprocess unconditionally —
729	# even when the caller opts into credential inheritance for a model-driving
730	# CLI (claude / codex / gemini).  These are not LLM provider credentials; no
731	# legitimate child Hermes spawns needs them, and they are the highest-value
732	# secrets to keep out of a compromised dependency's reach (gateway bot tokens,
733	# GitHub auth, remote-compute tokens, dashboard session secret).  The set is a
734	# narrow subset of _HERMES_PROVIDER_ENV_BLOCKLIST; provider keys are handled by
735	# the conditional Tier-2 strip in hermes_subprocess_env().
736	_ALWAYS_STRIP_KEYS: frozenset[str] = frozenset({
737	    # GitHub auth
738	    "GH_TOKEN",
739	    "GITHUB_TOKEN",
740	    "GITHUB_APP_ID",
741	    "GITHUB_APP_PRIVATE_KEY_PATH",
742	    "GITHUB_APP_INSTALLATION_ID",
743	    # Gateway / messaging bot tokens and access control
744	    "TELEGRAM_BOT_TOKEN",
745	    "DISCORD_BOT_TOKEN",
746	    "SLACK_BOT_TOKEN",
747	    "SLACK_APP_TOKEN",
748	    "SLACK_SIGNING_SECRET",
749	    "GATEWAY_ALLOWED_USERS",
750	    "GATEWAY_ALLOW_ALL_USERS",
751	    # Gateway relay auth — the ID/secret/delivery-key triplet the gateway
752	    # provisions and persists to the 0600 .env. Stripped unconditionally on
753	    # EVERY spawn surface (terminal + model-driving CLIs) so it can't drift
754	    # between paths: _SECRET / _DELIVERY_KEY are also matched by
755	    # _is_hermes_internal_secret, but _ID has no secret suffix, so it must be
756	    # enumerated here to stay stripped on the inherit_credentials=True path
757	    # (codex / copilot), which skips the Tier-2 blocklist.
758	    "GATEWAY_RELAY_ID",
759	    "GATEWAY_RELAY_SECRET",
760	    "GATEWAY_RELAY_DELIVERY_KEY",
761	    "HASS_TOKEN",
762	    "EMAIL_PASSWORD",
763	    "HERMES_DASHBOARD_SESSION_TOKEN",
764	    "MSGRAPH_CLIENT_SECRET",
765	    "MSGRAPH_WEBHOOK_CLIENT_STATE",
766	    "QQ_STT_API_KEY",
767	    "RAFT_CHANNEL_TOKEN",
768	    # Remote-compute / infrastructure secrets
769	    "MODAL_TOKEN_ID",
770	    "MODAL_TOKEN_SECRET",
771	    "DAYTONA_API_KEY",
772	})
773
774
775	_STRICT_SUBPROCESS_ENV_KEYS: frozenset[str] = frozenset({
776	    "APPDATA",
777	    "CHERE_INVOKING",
778	    "CODEX_HOME",
779	    "COLORTERM",
780	    "COMSPEC",
781	    "FORCE_COLOR",
782	    "GOBIN",
783	    "HERMES_DELEGATED_CHILD_CONTEXT",
784	    "HERMES_HOME",
785	    "HERMES_KANBAN_DB",
786	    "HERMES_KANBAN_ROOT",
787	    "HERMES_KANBAN_RUN_ID",
788	    "HERMES_KANBAN_TASK",
789	    "HERMES_KANBAN_WORKSPACE",
790	    "HOME",
791	    "HOMEDRIVE",
792	    "HOMEPATH",
793	    "LANG",
794	    "LANGUAGE",
795	    "LOCALAPPDATA",
796	    "LOGNAME",
797	    "MSYSTEM",
798	    "NO_COLOR",
799	    "NUMBER_OF_PROCESSORS",
800	    "OS",
801	    "PATH",
802	    "PATHEXT",
803	    "PROCESSOR_ARCHITECTURE",
804	    "PROCESSOR_IDENTIFIER",
805	    "PROCESSOR_LEVEL",
806	    "PROCESSOR_REVISION",
807	    "PROGRAMDATA",
808	    "PROGRAMFILES",
809	    "PROGRAMFILES(X86)",
810	    "PROGRAMW6432",
811	    "PYTHONIOENCODING",
812	    "PYTHONUTF8",
813	    "SHELL",
814	    "SYSTEMDRIVE",
815	    "SYSTEMROOT",
816	    "TEMP",
817	    "TERM",
818	    "TMP",
819	    "TMPDIR",
820	    "USER",
821	    "USERNAME",
822	    "USERPROFILE",
823	    "WINDIR",
824	    "XDG_CACHE_HOME",
825	    "XDG_CONFIG_HOME",
826	    "XDG_DATA_HOME",
827	})
828
829	_CREDENTIAL_ENV_NAME_RE = re.compile(
830	    r"(?:^|_)(?:API_KEY|ACCESS_KEY|AUTH|CREDENTIALS?|PASSWORD|PRIVATE_KEY|SECRET|TOKEN)(?:$|_)",
831	    re.IGNORECASE,
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
880	            for key, value in os.environ.items()
881	            if key.upper() in _STRICT_SUBPROCESS_ENV_KEYS
882	            or (
883	                key.upper().startswith("LC_")
884	                and not _CREDENTIAL_ENV_NAME_RE.search(key.upper())
885	            )
886	        }
887	    else:
888	        env = os.environ.copy()
889
890	    for key, value in (extra or {}).items():
891	        upper = key.upper()
892	        if allowlist_only and (
893	            key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX)
894	            or upper in _ALWAYS_STRIP_KEYS
895	            or upper in _HERMES_PROVIDER_ENV_BLOCKLIST
896	            or key in _plugin_terminal_env_strip_keys()
897	            or _is_hermes_internal_secret(key)
898	            or _CREDENTIAL_ENV_NAME_RE.search(upper)
899	        ):
900	            raise ValueError(f"credential-shaped environment key is not allowed: {key}")
901
902	    env = _profile_child_base(env, inherit_credentials=inherit_credentials or bool(approved), extra=extra)
903	    if allowlist_only:
904	        env = {
905	            key: value for key, value in env.items()
906	            if key in (extra or {}) or key.upper() in _STRICT_SUBPROCESS_ENV_KEYS
907	            or (key.upper().startswith("LC_") and not _CREDENTIAL_ENV_NAME_RE.search(key))
908	        }
909
910	    # Compare names case-insensitively even when the host uses a plain dict.
911	    # A POSIX caller can pass Windows-style case variants to a child.
912	    always_strip = {key.upper() for key in _ALWAYS_STRIP_KEYS}
913	    always_strip.update(key.upper() for key in _plugin_terminal_env_strip_keys())
914	    provider_strip = _provider_secret_env()
915	    for key in list(env):
916	        upper = key.upper()
917	        if upper in always_strip or (not inherit_credentials and upper in provider_strip and upper not in approved):
918	            env.pop(key, None)
919	    # Internal routing hints and Hermes-internal dynamic secrets
920	    # (``AUXILIARY_<TASK>_API_KEY`` / ``_BASE_URL`` side-LLM credentials,
921	    # ``GATEWAY_RELAY_*`` relay-auth material) must never reach a child,
922	    # regardless of ``inherit_credentials`` — a model-driving CLI has no
923	    # legitimate use for them. See :func:`_is_hermes_internal_secret`.
924	    for key in list(env):
925	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
926	            env.pop(key, None)
927	        elif _is_hermes_internal_secret(key):
928	            env.pop(key, None)
929
930	    if not inherit_credentials:
931	        # Tier 2 — strip provider/tool credentials unless explicitly inherited.
932	        for key in _HERMES_PROVIDER_ENV_BLOCKLIST:
933	            if key.upper() not in approved:
934	                env.pop(key, None)
935
936	    # Windows UTF-8 safety for spawned processes (#31420).
937	    env.setdefault("PYTHONUTF8", "1")
938
939	    _inject_context_hermes_home(env)
940	    from hermes_constants import apply_subprocess_home_env
941	    apply_subprocess_home_env(env)
942
943	    _strip_hermes_owned_pythonpath_and_runtime_markers(env)
944
945	    _apply_windows_msys_bash_env_defaults(env)
946
947	    # Cross-session leak guard, same as the terminal spawn paths: this helper
948	    # copies os.environ, whose HERMES_SESSION_* mirror is a last-writer-wins
949	    # global under a concurrent multi-session host. A caller that re-binds the
950	    # session identity explicitly (slash_worker/ACP via --session-key argv) is
951	    # unaffected — bound ContextVars win here — but a caller that spawns without
952	    # re-binding (e.g. tui_gateway cli.exec) would otherwise inherit a FOREIGN
953	    # session's identity. Strip _UNSET session vars when engaged so that can't
954	    # happen; single uniform policy across every spawn surface.
955	    _inject_session_context_env(env)
956
957	    # Non-terminal subprocess helpers (browser, lazy-deps, TUI/ACP hosts, etc.)
958	    # also need the delegate_task child lineage marker.  Otherwise a child
959	    # context that later imports Kanban DB code in the spawned process would
960	    # still see the parent's HERMES_HOME but lose the DB mutation guard.
961	    env = _scrub_delegated_child_kanban_env(env)
962
963	    return env
964
965
966	def build_subprocess_env(
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
