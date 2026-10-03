**Exploration: hermes_subprocess_env**

Found 13 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `hermes_subprocess_env` (tools/environments/local.py:715) — 51 callers in `agent/chat_completion_helpers.py`, `agent/copilot_acp_client.py`, `agent/lsp/client.py`, `agent/lsp/install.py` +18 more; tests: `tests/tools/test_build_subprocess_env.py`, `tests/tools/test_hermes_subprocess_env.py`, `tests/tools/test_local_env_session_leak.py`, `tests/tools/test_local_env_windows_msys.py`

**Relationships**

**calls:**
- hermes_subprocess_env → items
- hermes_subprocess_env → search
- hermes_subprocess_env → copy
- hermes_subprocess_env → _plugin_terminal_env_strip_keys
- hermes_subprocess_env → _is_hermes_internal_secret
- hermes_subprocess_env → _inject_context_hermes_home
- hermes_subprocess_env → apply_subprocess_home_env
- hermes_subprocess_env → _strip_hermes_owned_pythonpath_and_runtime_markers
- hermes_subprocess_env → _apply_windows_msys_bash_env_defaults
- hermes_subprocess_env → _inject_session_context_env
- hermes_subprocess_env → _scrub_delegated_child_kanban_env
- _run_fallback_start_command → hermes_subprocess_env
- _build_subprocess_env → hermes_subprocess_env
- _spawn → hermes_subprocess_env
- _install_npm → hermes_subprocess_env
- ... and 10 more

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), items(calls), search(calls), _plugin_terminal_env_strip_keys(calls), _is_hermes_internal_secret(calls), _HERMES_PROVIDER_ENV_FORCE_PREFIX(variable), _HERMES_PROVIDER_ENV_BLOCKLIST(variable), _is_hermes_internal_secret(function), _plugin_terminal_env_strip_keys(function), _inject_context_hermes_home(function), _inject_session_context_env(function), _scrub_delegated_child_kanban_env(function), _ALWAYS_STRIP_KEYS(variable), _STRICT_SUBPROCESS_ENV_KEYS(variable), _CREDENTIAL_ENV_NAME_RE(variable), +10 more

```python
202
203
204	# Hermes-internal env vars that should NOT leak into terminal subprocesses.
205	_HERMES_PROVIDER_ENV_FORCE_PREFIX = "_HERMES_FORCE_"
206
207	# Hermes-managed AWS *inference* credentials for ``auth_type="aws_sdk"``
208	# providers (Bedrock).  Scoped DELIBERATELY NARROW: this lists only the

... (gap) ...

369	    return frozenset(blocked)
370
371
372	_HERMES_PROVIDER_ENV_BLOCKLIST = _build_provider_env_blocklist()
373
374	# Active-virtualenv markers that must NOT leak into terminal subprocesses.
375	# The gateway runs inside its own venv, so its process environment carries

... (gap) ...

397	_ACTIVE_VENV_MARKER_VARS = ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME")
398
399
400	def _is_hermes_internal_secret(key: str) -> bool:
401	    """Return True for Hermes-internal secrets injected under *dynamic* names.
402
403	    ``_HERMES_PROVIDER_ENV_BLOCKLIST`` is name-based and derived from the
404	    provider/tool registries, but the gateway and CLI also inject secrets into
405	    ``os.environ`` at runtime under names no static registry knows about:
406
407	    - ``AUXILIARY_<TASK>_API_KEY`` / ``AUXILIARY_<TASK>_BASE_URL`` — per-task
408	      side-LLM credentials bridged from ``config.yaml[auxiliary]`` by
409	      ``gateway/run.py`` and ``cli.py`` (vision, web_extract, approval,
410	      compression, and any plugin-registered auxiliary task). These are
411	      separate, often higher-spend API keys plus base URLs that may point at
412	      private endpoints; a model-authored shell command must never see them.
413	    - ``GATEWAY_RELAY_*_SECRET`` / ``GATEWAY_RELAY_*_KEY`` /
414	      ``GATEWAY_RELAY_*_TOKEN`` — relay-auth material provisioned by the
415	      gateway (``GATEWAY_RELAY_SECRET``, ``GATEWAY_RELAY_DELIVERY_KEY``).
416	      These are Tier-1 gateway secrets, like the messaging bot tokens in
417	      ``_ALWAYS_STRIP_KEYS``. Non-secret ``GATEWAY_RELAY_*`` routing hints
418	      (``GATEWAY_RELAY_URL``, ``GATEWAY_RELAY_PLATFORMS``, …) are NOT matched
419	      and remain visible.
420
421	    ``code_execution_tool.py`` already catches these via substring matching on
422	    ``KEY`` / ``SECRET`` / ``TOKEN``; the terminal backend's narrower name-based
423	    blocklist did not, which is the leak this predicate closes.
424
425	    This is the single source of truth for "Hermes-internal dynamic secret"
426	    across every spawn path — the terminal ``_make_run_env`` /
427	    ``_sanitize_subprocess_env`` filters, the Docker passthrough filter, and the
428	    non-terminal :func:`hermes_subprocess_env` helper all call it, so the
429	    dynamic patterns are stripped **unconditionally** regardless of
430	    ``env_passthrough`` skill registration or ``inherit_credentials``. Nothing
431	    a model-driving CLI legitimately needs matches these patterns.
432	    """
433	    upper = key.upper()
434	    if upper.startswith("AUXILIARY_") and (
435	        upper.endswith("_API_KEY") or upper.endswith("_BASE_URL")
436	    ):
437	        return True
438	    if upper.startswith("GATEWAY_RELAY_") and (
439	        upper.endswith("_SECRET") or upper.endswith("_KEY") or upper.endswith("_TOKEN")
440	    ):
441	        return True
442	    return False
443
444
445	def _plugin_terminal_env_strip_keys() -> frozenset:
446	    """Credential env keys owned by plugin-registered terminal backends.
447
448	    Computed at call time (not import time) because plugins register after
449	    this module is imported. Treated as Tier-1: stripped from every spawned
450	    subprocess unconditionally, exactly like MODAL_*/DAYTONA_API_KEY in
451	    ``_ALWAYS_STRIP_KEYS``. Fail-soft to an empty set.
452	    """
453	    try:
454	        from agent.terminal_env_registry import plugin_strip_env_keys
455
456	        return plugin_strip_env_keys()
457	    except Exception:
458	        return frozenset()
459
460
461	def _inject_context_hermes_home(env: dict) -> None:
462	    """Bridge the context-local Hermes home override into subprocess env."""
463	    try:
464	        from hermes_constants import get_hermes_home_override
465
466	        value = get_hermes_home_override()
467	        if value:
468	            env["HERMES_HOME"] = value
469	    except Exception:
470	        pass
471
472
473	def _inject_session_context_env(env: dict) -> None:

... (gap) ...

505	    except Exception:
506	        return
507
508	    _engaged = session_context_engaged()
509	    for var_name, var in _VAR_MAP.items():
510	        value = var.get()
511	        if value is not _UNSET:

... (gap) ...

594	    return sanitized
595
596
597	def _scrub_delegated_child_kanban_env(env: dict[str, str]) -> dict[str, str]:
598	    """Strip dispatcher-owned Kanban env from delegate_task child subprocesses."""
599	    try:
600	        from agent.delegation_context import (
601	            is_delegated_child_process_context,
602	            scrub_kanban_env,
603	        )
604
605	        if is_delegated_child_process_context():
606	            return scrub_kanban_env(env)
607	    except Exception:
608	        pass
609	    return env
610
611
612	# Tier-1 secrets: stripped from EVERY spawned subprocess unconditionally —
613	# even when the caller opts into credential inheritance for a model-driving
614	# CLI (claude / codex / gemini).  These are not LLM provider credentials; no
615	# legitimate child Hermes spawns needs them, and they are the highest-value
616	# secrets to keep out of a compromised dependency's reach (gateway bot tokens,
617	# GitHub auth, remote-compute tokens, dashboard session secret).  The set is a
618	# narrow subset of _HERMES_PROVIDER_ENV_BLOCKLIST; provider keys are handled by
619	# the conditional Tier-2 strip in hermes_subprocess_env().
620	_ALWAYS_STRIP_KEYS: frozenset[str] = frozenset({
621	    # GitHub auth
622	    "GH_TOKEN",
623	    "GITHUB_TOKEN",
624	    "GITHUB_APP_ID",
625	    "GITHUB_APP_PRIVATE_KEY_PATH",
626	    "GITHUB_APP_INSTALLATION_ID",
627	    # Gateway / messaging bot tokens and access control
628	    "TELEGRAM_BOT_TOKEN",
629	    "DISCORD_BOT_TOKEN",
630	    "SLACK_BOT_TOKEN",
631	    "SLACK_APP_TOKEN",
632	    "SLACK_SIGNING_SECRET",
633	    "GATEWAY_ALLOWED_USERS",
634	    "GATEWAY_ALLOW_ALL_USERS",
635	    # Gateway relay auth — the ID/secret/delivery-key triplet the gateway
636	    # provisions and persists to the 0600 .env. Stripped unconditionally on
637	    # EVERY spawn surface (terminal + model-driving CLIs) so it can't drift
638	    # between paths: _SECRET / _DELIVERY_KEY are also matched by
639	    # _is_hermes_internal_secret, but _ID has no secret suffix, so it must be
640	    # enumerated here to stay stripped on the inherit_credentials=True path
641	    # (codex / copilot), which skips the Tier-2 blocklist.
642	    "GATEWAY_RELAY_ID",
643	    "GATEWAY_RELAY_SECRET",
644	    "GATEWAY_RELAY_DELIVERY_KEY",
645	    "HASS_TOKEN",
646	    "EMAIL_PASSWORD",
647	    "HERMES_DASHBOARD_SESSION_TOKEN",
648	    # Remote-compute / infrastructure secrets
649	    "MODAL_TOKEN_ID",
650	    "MODAL_TOKEN_SECRET",
651	    "DAYTONA_API_KEY",
652	})
653
654
655	_STRICT_SUBPROCESS_ENV_KEYS: frozenset[str] = frozenset({
656	    "APPDATA",
657	    "CHERE_INVOKING",
658	    "CODEX_HOME",
659	    "COLORTERM",
660	    "COMSPEC",
661	    "FORCE_COLOR",
662	    "GOBIN",
663	    "HERMES_DELEGATED_CHILD_CONTEXT",
664	    "HERMES_HOME",
665	    "HERMES_KANBAN_DB",
666	    "HERMES_KANBAN_ROOT",
667	    "HERMES_KANBAN_RUN_ID",
668	    "HERMES_KANBAN_TASK",
669	    "HERMES_KANBAN_WORKSPACE",
670	    "HOME",
671	    "HOMEDRIVE",
672	    "HOMEPATH",
673	    "LANG",
674	    "LANGUAGE",
675	    "LOCALAPPDATA",
676	    "LOGNAME",
677	    "MSYSTEM",
678	    "NO_COLOR",
679	    "NUMBER_OF_PROCESSORS",
680	    "OS",
681	    "PATH",
682	    "PATHEXT",
683	    "PROCESSOR_ARCHITECTURE",
684	    "PROCESSOR_IDENTIFIER",
685	    "PROCESSOR_LEVEL",
686	    "PROCESSOR_REVISION",
687	    "PROGRAMDATA",
688	    "PROGRAMFILES",
689	    "PROGRAMFILES(X86)",
690	    "PROGRAMW6432",
691	    "PYTHONIOENCODING",
692	    "PYTHONUTF8",
693	    "SHELL",
694	    "SYSTEMDRIVE",
695	    "SYSTEMROOT",
696	    "TEMP",
697	    "TERM",
698	    "TMP",
699	    "TMPDIR",
700	    "USER",
701	    "USERNAME",
702	    "USERPROFILE",
703	    "WINDIR",
704	    "XDG_CACHE_HOME",
705	    "XDG_CONFIG_HOME",
706	    "XDG_DATA_HOME",
707	})
708
709	_CREDENTIAL_ENV_NAME_RE = re.compile(
710	    r"(?:^|_)(?:API_KEY|ACCESS_KEY|AUTH|CREDENTIALS?|PASSWORD|PRIVATE_KEY|SECRET|TOKEN)(?:$|_)",
711	    re.IGNORECASE,
712	)
713
714
715	def hermes_subprocess_env(
716	    *,
717	    inherit_credentials: bool = False,
718	    allowlist_only: bool = False,
719	    extra: Mapping[str, str] | None = None,
720	) -> dict[str, str]:
721	    """Build a sanitized environment dict for a spawned subprocess.
722
723	    Centralized helper for the **non-terminal** spawn surface (browser,
724	    ACP/CLI executors, computer-use driver, dep-ensure, TUI Node host,
725	    detached gateway).  Use this instead of copying ``os.environ`` directly
726	    so strip-by-default is the uniform policy across every spawn site, with a
727	    single source of truth (``_HERMES_PROVIDER_ENV_BLOCKLIST``).  The terminal
728	    / execute_code path keeps using :func:`_sanitize_subprocess_env`, which is
729	    skill-aware (``env_passthrough``); this helper is for spawns that have no
730	    skill-passthrough concept.
731
732	    Two-tier stripping:
733
734	    * **Tier 1 (always):** ``_ALWAYS_STRIP_KEYS`` — gateway bot tokens, GitHub
735	      auth, and remote-compute secrets are removed regardless of
736	      ``inherit_credentials``.  No child Hermes spawns legitimately needs them.
737	    * **Tier 2 (conditional):** the rest of ``_HERMES_PROVIDER_ENV_BLOCKLIST``
738	      (LLM provider API keys, tool secrets) is removed unless the caller passes
739	      ``inherit_credentials=True``.
740
741	    Pass ``inherit_credentials=True`` **only** when the child legitimately
742	    needs LLM provider credentials — a user-blessed ``claude`` / ``codex`` /
743	    ``gemini`` CLI executor, or the TUI Node host that makes model calls.  The
744	    flag is grep-able for audit: ``grep -rn 'inherit_credentials=True'`` lists
745	    every spawn site that still receives provider credentials.
746
747	    Callers that need a *specific* non-provider secret (e.g. the browser worker
748	    needs ``BROWSERBASE_API_KEY`` / ``FIRECRAWL_API_KEY``) should call with
749	    ``inherit_credentials=False`` and copy just those keys back from
750	    ``os.environ`` into the returned dict.
751	    """
752	    if allowlist_only and inherit_credentials:
753	        raise ValueError("allowlist_only cannot be combined with inherit_credentials")
754
755	    if allowlist_only:
756	        env = {
757	            key: value
758	            for key, value in os.environ.items()
759	            if key.upper() in _STRICT_SUBPROCESS_ENV_KEYS
760	            or (
761	                key.upper().startswith("LC_")
762	                and not _CREDENTIAL_ENV_NAME_RE.search(key.upper())
763	            )
764	        }
765	    else:
766	        env = os.environ.copy()
767
768	    for key, value in (extra or {}).items():
769	        upper = key.upper()
770	        if allowlist_only and (
771	            key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX)
772	            or upper in _ALWAYS_STRIP_KEYS
773	            or upper in _HERMES_PROVIDER_ENV_BLOCKLIST
774	            or key in _plugin_terminal_env_strip_keys()
775	            or _is_hermes_internal_secret(key)
776	            or _CREDENTIAL_ENV_NAME_RE.search(upper)
777	        ):
778	            raise ValueError(f"credential-shaped environment key is not allowed: {key}")
779	        env[key] = value
780
781	    # Compare names case-insensitively even when the host uses a plain dict.
782	    # A POSIX caller can pass Windows-style case variants to a child.
783	    always_strip = {key.upper() for key in _ALWAYS_STRIP_KEYS}
784	    always_strip.update(key.upper() for key in _plugin_terminal_env_strip_keys())
785	    provider_strip = {key.upper() for key in _HERMES_PROVIDER_ENV_BLOCKLIST}
786	    for key in list(env):
787	        upper = key.upper()
788	        if upper in always_strip or (not inherit_credentials and upper in provider_strip):
789	            env.pop(key, None)
790	    # Internal routing hints and Hermes-internal dynamic secrets
791	    # (``AUXILIARY_<TASK>_API_KEY`` / ``_BASE_URL`` side-LLM credentials,
792	    # ``GATEWAY_RELAY_*`` relay-auth material) must never reach a child,
793	    # regardless of ``inherit_credentials`` — a model-driving CLI has no
794	    # legitimate use for them. See :func:`_is_hermes_internal_secret`.
795	    for key in list(env):
796	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
797	            env.pop(key, None)
798	        elif _is_hermes_internal_secret(key):
799	            env.pop(key, None)
800
801	    if not inherit_credentials:
802	        # Tier 2 — strip provider/tool credentials unless explicitly inherited.
803	        for key in _HERMES_PROVIDER_ENV_BLOCKLIST:
804	            env.pop(key, None)
805
806	    # Windows UTF-8 safety for spawned processes (#31420).
807	    env.setdefault("PYTHONUTF8", "1")
808
809	    _inject_context_hermes_home(env)
810	    from hermes_constants import apply_subprocess_home_env
811	    apply_subprocess_home_env(env)
812
813	    _strip_hermes_owned_pythonpath_and_runtime_markers(env)
814
815	    _apply_windows_msys_bash_env_defaults(env)
816
817	    # Cross-session leak guard, same as the terminal spawn paths: this helper
818	    # copies os.environ, whose HERMES_SESSION_* mirror is a last-writer-wins
819	    # global under a concurrent multi-session host. A caller that re-binds the
820	    # session identity explicitly (slash_worker/ACP via --session-key argv) is
821	    # unaffected — bound ContextVars win here — but a caller that spawns without
822	    # re-binding (e.g. tui_gateway cli.exec) would otherwise inherit a FOREIGN
823	    # session's identity. Strip _UNSET session vars when engaged so that can't
824	    # happen; single uniform policy across every spawn surface.
825	    _inject_session_context_env(env)
826
827	    # Non-terminal subprocess helpers (browser, lazy-deps, TUI/ACP hosts, etc.)
828	    # also need the delegate_task child lineage marker.  Otherwise a child
829	    # context that later imports Kanban DB code in the spawned process would
830	    # still see the parent's HERMES_HOME but lose the DB mutation guard.
831	    env = _scrub_delegated_child_kanban_env(env)
832
833	    return env
834
835
836	def build_subprocess_env(

... (gap) ...

1456	    return ":".join(ordered_entries)
1457
1458
1459	def _apply_windows_msys_bash_env_defaults(env: dict) -> None:
1460	    """Disable MSYS argument path conversion for Git Bash subprocesses.
1461
1462	    Git Bash rewrites arguments that look like Unix paths (``/FO``, ``/TN``,
1463	    ``/Create``) into ``C:/.../git/FO``-style paths, which breaks native
1464	    Windows commands such as ``tasklist``, ``schtasks``, and ``wmic``.  Hermes
1465	    runs terminal commands through bash on Windows, so set the standard MSYS
1466	    opt-out by default.  Users who need conversion can override in their env.
1467	    Refs #56700.
1468
1469	    ``MSYS_NO_PATHCONV`` is honored by Git for Windows bash only.  MSYS2-proper
1470	    and Cygwin bash (which ``_find_bash`` can still return via the final
1471	    ``shutil.which`` fallback) ignore it and honor ``MSYS2_ARG_CONV_EXCL``
1472	    instead, so set both.  ``*`` disables all argv conversion — the semantic
1473	    equivalent of ``MSYS_NO_PATHCONV=1``.  Also fixes ``cmd /c`` mangling
1474	    (#56147).
1475	    """
1476	    if not _IS_WINDOWS:
1477	        return
1478	    env.setdefault("MSYS_NO_PATHCONV", "1")
1479	    env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
1480
1481
1482	def _path_env_key(run_env: dict) -> str | None:

... (gap) ...

1743	    return result
1744
1745
1746	def _strip_hermes_owned_pythonpath_and_runtime_markers(env: dict) -> None:
1747	    """Strip Hermes-owned PYTHONPATH entries, then the runtime marker vars.
1748
1749	    Ordering is load-bearing: PYTHONPATH filtering must run BEFORE the
1750	    markers are removed so a validated Windows base-interpreter launch
1751	    (VIRTUAL_ENV -> <repo>/venv) can still prove ownership.
1752	    """
1753	    _strip_hermes_owned_pythonpath(env)
1754	    for _marker in _ACTIVE_VENV_MARKER_VARS:
1755	        env.pop(_marker, None)
1756
1757
1758	def _strip_hermes_owned_pythonpath(env: dict) -> None:
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
- ... and 11 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,014 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
