**Exploration: tools/environments/local.py**

Found 83 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _is_hermes_internal_secret(calls), _same_path(calls), _plugin_terminal_env_strip_keys(calls), _inject_context_hermes_home(calls), add(calls), _sweep_escaped_descendants(calls), _profile_child_base(calls), _inject_session_context_env(calls), _strip_hermes_owned_pythonpath_and_runtime_markers(calls), _apply_windows_msys_bash_env_defaults(calls), _scrub_delegated_child_kanban_env(calls), _find_bash(calls), _child_policy_home(calls), references(references), +100 more

```python
398	# PYTHONPATH is NOT included here — it's handled by
399	# _strip_hermes_owned_pythonpath() which removes only Hermes-owned entries,
400	# preserving user-set paths.
401	_ACTIVE_VENV_MARKER_VARS = ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME")
402
403
404	def _is_hermes_internal_secret(key: str) -> bool:

... (gap) ...

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
528	        owned.update(platform_manifest_secret_envs(launch))
529	        owned.update(name.upper() for name in _HERMES_PROVIDER_ENV_BLOCKLIST)
530	        for name in list(env):
531	            upper = name.upper()
532	            real = upper.removeprefix(_HERMES_PROVIDER_ENV_FORCE_PREFIX.upper())
533	            if real in owned:
534	                env.pop(name)
535	        values = dict(scope) if scope is not None else build_profile_secret_scope(target)
536	        for name, value in values.items():
537	            if value is not None and not _is_global_env(name):
538	                env[name] = value
539	    for name, value in (extra or {}).items():
540	        real = name.upper().removeprefix(_HERMES_PROVIDER_ENV_FORCE_PREFIX.upper())
541	        if real not in owned:
542	            env[name] = value

... (gap) ...

578	    except Exception:
579	        return
580
581	    _engaged = session_context_engaged()
582	    for var_name, var in _VAR_MAP.items():
583	        value = var.get()
584	        if value is not _UNSET:

... (gap) ...

602	        _resolve_passthrough_value = lambda _name, fallback: fallback  # noqa: E731
603
604	    sanitized: dict[str, str] = {}
605	    _plugin_strip = {key.upper() for key in _plugin_terminal_env_strip_keys()}
606	    _provider_strip = {key.upper() for key in _HERMES_PROVIDER_ENV_BLOCKLIST}
607
608	    effective = _profile_child_base(base_env or {}, extra=extra_env)
609	    for key, value in effective.items():
610	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
611	            if key not in (extra_env or {}):
612	                continue
613	            real_key = key[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
614	            if _is_hermes_internal_secret(real_key) or real_key.upper() in _plugin_strip:
615	                continue
616	            sanitized[real_key] = value
617	            continue
618	        if _is_hermes_internal_secret(key):
619	            continue
620	        if key.upper() in _plugin_strip:
621	            continue
622	        passthrough = _is_passthrough(key)
623	        if key.upper() in _provider_strip and not passthrough:
624	            continue
625	        resolved = _resolve_passthrough_value(key, value) if passthrough else value
626	        if resolved is not None:
627	            sanitized[key] = resolved
628
629	    _inject_context_hermes_home(sanitized)
630
631	    from hermes_constants import apply_subprocess_home_env
632	    apply_subprocess_home_env(sanitized)
633
634	    # Same cross-session leak guard as _make_run_env, for the background/PTY
635	    # spawn path (process_registry.spawn_local builds env via this function).
636	    _inject_session_context_env(sanitized)
637
638	    # Filter PYTHONPATH before removing VIRTUAL_ENV: legacy Windows launchers
639	    # can run the gateway under a base interpreter while VIRTUAL_ENV identifies
640	    # the separate Hermes runtime venv.  The filter validates that relationship
641	    # against the repo layout before trusting it.
642	    _strip_hermes_owned_pythonpath_and_runtime_markers(sanitized)
643
644	    # Keep bare ``hermes`` invocations available to child jobs even when the
645	    # gateway was launched by a service manager or cron without the console
646	    # script's directory on PATH.  The terminal environment already applies
647	    # this invariant; Cron scripts use this sanitizer directly (#92998).
648	    path_key = _path_env_key(sanitized)
649	    if path_key is not None:
650	        sanitized[path_key] = _prepend_hermes_bin_dir(sanitized.get(path_key, ""))
651
652	    _apply_windows_msys_bash_env_defaults(sanitized)
653
654	    sanitized = _scrub_delegated_child_kanban_env(sanitized)
655
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

... (gap) ...

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

... (gap) ...

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

... (gap) ...

950	        # _sanitize_subprocess_env already performs HERMES_HOME override
951	        # bridging + apply_subprocess_home_env unconditionally; delegating
952	        # wholesale keeps one owner and zero drift.
953	        return _sanitize_subprocess_env(
954	            dict(base) if base is not None else os.environ.copy(),
955	            dict(extra) if extra else None,
956	        )
957
958	    env: dict[str, str] = dict(base) if base is not None else os.environ.copy()
959	    if inherit_profile_home:
960	        _inject_context_hermes_home(env)
961	        from hermes_constants import apply_subprocess_home_env
962	        apply_subprocess_home_env(env)
963	    if extra:
964	        env.update(extra)
965	    return env

... (gap) ...

981	    except (OSError, ValueError):
982	        resolved = os.path.normcase(str(candidate))
983
984	    windows_dir = ntpath.normcase(os.environ.get("WINDIR", r"C:\Windows"))
985	    windows_apps = ntpath.normcase(os.environ.get("LOCALAPPDATA", ""))
986	    stubs = {ntpath.normcase(ntpath.join(windows_dir, "System32", "bash.exe"))}
987	    if windows_apps:
988	        stubs.add(ntpath.normcase(ntpath.join(windows_apps, "Microsoft", "WindowsApps", "bash.exe")))
989	    return resolved in stubs
990
991
992	def _find_bash() -> str:
993	    """Find bash for command execution."""
994	    if not _IS_WINDOWS:
995	        return (
996	            shutil.which("bash")
997	            or ("/usr/bin/bash" if os.path.isfile("/usr/bin/bash") else None)
998	            or ("/bin/bash" if os.path.isfile("/bin/bash") else None)
999	            or os.environ.get("SHELL")
1000	            or "/bin/sh"
1001	        )
1002
1003	    candidates: list[str] = []
1004
1005	    custom = os.environ.get("HERMES_GIT_BASH_PATH")
1006	    if custom and os.path.isfile(custom):
1007	        candidates.append(custom)
1008
1009	    # Prefer our own portable Git install — a broken or partially-uninstalled
1010	    # system Git (or a stale HERMES_GIT_BASH_PATH pointing at one) must not
1011	    # brick the terminal.  install.ps1 drops PortableGit here when needed.
1012	    #
1013	    # Layouts (both checked so upgrades between MinGit and PortableGit
1014	    # installs work transparently):
1015	    #   PortableGit: %LOCALAPPDATA%\hermes\git\bin\bash.exe   (primary)
1016	    #   MinGit:      %LOCALAPPDATA%\hermes\git\usr\bin\bash.exe (legacy/32-bit fallback)
1017	    _local_appdata = os.environ.get("LOCALAPPDATA", "")
1018	    _hermes_portable_git = os.path.join(_local_appdata, "hermes", "git") if _local_appdata else ""
1019	    if _hermes_portable_git:
1020	        for candidate in (
1021	            os.path.join(_hermes_portable_git, "bin", "bash.exe"),        # PortableGit (primary)
1022	            os.path.join(_hermes_portable_git, "usr", "bin", "bash.exe"), # MinGit fallback
1023	        ):
1024	            if os.path.isfile(candidate) and candidate not in candidates:
1025	                candidates.append(candidate)
1026
1027	    # Check known Git for Windows install locations before PATH lookup.
1028	    # On machines with both WSL and Git for Windows, shutil.which("bash")
1029	    # may return WSL's bash (which doesn't understand Windows paths and
1030	    # will fail silently).  Explicit Git-for-Windows paths avoid that.
1031	    for candidate in (
1032	        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"),
1033	        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "bin", "bash.exe"),
1034	        os.path.join(_local_appdata, "Programs", "Git", "bin", "bash.exe") if _local_appdata else "",
1035	    ):
1036	        if candidate and os.path.isfile(candidate) and candidate not in candidates:
1037	            candidates.append(candidate)
1038
1039	    found = shutil.which("bash")
1040	    if found and not _is_wsl_bash_stub(found) and found not in candidates:
1041	        candidates.append(found)
1042
1043	    # Prefer the first candidate that can actually start.  A stale
1044	    # HERMES_GIT_BASH_PATH pointing at a broken Git-for-Windows install
1045	    # (``Directory \\drivers\\etc does not exist``) must not win over a
1046	    # healthy portable Git under %LOCALAPPDATA%\\hermes\\git.
1047	    for candidate in candidates:
1048	        if _bash_starts(candidate):
1049	            if candidate != custom and custom and os.path.isfile(custom):
1050	                logger.warning(
1051	                    "HERMES_GIT_BASH_PATH=%s fails to start; using %s instead",
1052	                    custom,
1053	                    candidate,
1054	                )
1055	            return candidate
1056
1057	    if candidates:
1058	        probe_details = "\n".join(
1059	            detail
1060	            for candidate in candidates
1061	            if (detail := _bash_probe_details_cache.get(candidate))
1062	        )
1063	        if _mandatory_aslr_enabled() is True or _looks_like_msys_spawn_failure(
1064	            probe_details
1065	        ):
1066	            raise RuntimeError(_git_bash_aslr_help(candidates[0], probe_details))
1067
1068	        # Last resort for failures unrelated to the known MSYS/ASLR class:
1069	        # return the first path so the caller still sees the real bash error
1070	        # instead of the less useful "not found" message.
1071	        return candidates[0]
1072
1073	    raise RuntimeError(
1074	        "Git Bash not found. Hermes Agent requires Git for Windows on Windows.\n"
1075	        "Install it from: https://git-scm.com/download/win\n"
1076	        "Or set HERMES_GIT_BASH_PATH to your bash.exe location."
1077	    )
1078
1079
1080	_bash_starts_cache: dict[str, bool] = {}
1081	_bash_probe_details_cache: dict[str, str] = {}
1082	_mandatory_aslr_enabled_cache: "bool | None" = None
1083
1084	_BASH_EXTERNAL_PROGRAM_PROBE = "/usr/bin/true; /usr/bin/cat --version >/dev/null"
1085
1086
1087	def _looks_like_msys_spawn_failure(details: str) -> bool:

... (gap) ...

1117	            capture_output=True,
1118	            text=True, encoding="utf-8", errors="replace",
1119	            timeout=10,
1120	            creationflags=windows_hide_flags(),
1121	            stdin=subprocess.DEVNULL,
1122	        )
1123	        if result.returncode != 0:
1124	            return None
1125	        value = (result.stdout or "").strip().upper()
1126	        if value == "ON":
1127	            _mandatory_aslr_enabled_cache = True
1128	            return True

... (gap) ...

1147
1148	def _git_bash_aslr_help(bash: str, details: str = "") -> str:
1149	    """Build the targeted per-program Mandatory-ASLR remediation."""
1150	    git_root = _git_root_from_bash(bash)
1151	    escaped_root = git_root.replace("'", "''")
1152	    detail_line = f"\nGit Bash probe output: {details[:500]}" if details else ""
1153	    return (

... (gap) ...

1174	    a builtin-only ``exit 0`` probe misses Git-for-Windows fork/spawn failures
1175	    under system-wide Mandatory ASLR. Cached per path for the process lifetime.
1176	    """
1177	    cached = _bash_starts_cache.get(bash)
1178	    if cached is not None:
1179	        return cached
1180
1181	    try:
1182	        result = subprocess.run(
1183	            [bash, "--noprofile", "--norc", "-c", _BASH_EXTERNAL_PROGRAM_PROBE],
1184	            capture_output=True,
1185	            text=True, encoding="utf-8", errors="replace",
1186	            timeout=15,
1187	            creationflags=windows_hide_flags() if _IS_WINDOWS else 0,
1188	            stdin=subprocess.DEVNULL,
1189	        )
1190	        ok = result.returncode == 0

... (gap) ...

1201	    return ok
1202
1203
1204	_git_bash_bin_dirs_cache: "list[str] | None" = None
1205
1206
1207	def _env_path_sep() -> str:

... (gap) ...

1243
1244	    dirs: list[str] = []
1245	    try:
1246	        bash = _find_bash()
1247	    except Exception:
1248	        _git_bash_bin_dirs_cache = []
1249	        return _git_bash_bin_dirs_cache
1250
1251	    bin_dir = os.path.dirname(bash)          # <root>\bin  or  <root>\usr\bin
1252	    parent = os.path.dirname(bin_dir)
1253	    # MinGit ships bash under usr\bin; PortableGit/system Git under bin.
1254	    root = os.path.dirname(parent) if os.path.basename(parent).lower() == "usr" else parent
1255
1256	    # Order mirrors Git-for-Windows /etc/profile so coreutils win over the
1257	    # same-named Windows System32 tools (find.exe, sort.exe) inside the shell.
1258	    for candidate in (
1259	        os.path.join(root, "mingw64", "bin"),
1260	        os.path.join(root, "mingw32", "bin"),
1261	        os.path.join(root, "usr", "local", "bin"),
1262	        os.path.join(root, "usr", "bin"),
1263	        os.path.join(root, "bin"),
1264	    ):
1265	        if os.path.isdir(candidate) and candidate not in dirs:
1266	            dirs.append(candidate)

... (gap) ...

1280	    """
1281	    if not _IS_WINDOWS:
1282	        return existing_path
1283	    git_dirs = _git_bash_bin_dirs()
1284	    if not git_dirs:
1285	        return existing_path
1286	    sep = _env_path_sep()
1287	    entries = [e for e in existing_path.split(sep) if e] if existing_path else []
1288	    missing = [d for d in git_dirs if d not in entries]
1289	    if not missing:
1290	        return existing_path
1291	    return sep.join([*missing, *entries])
1292
1293
1294	# POSIX-sh-family shells that understand the ``[shell, "-lic", "set +m; …"]``
1295	# invocation spawn_local uses. $SHELL values outside this set (fish, csh/tcsh,
1296	# nushell, elvish, xonsh, …) would error on that syntax, so _find_shell falls
1297	# back to bash for them rather than honouring $SHELL. (#42203)
1298	_SPAWN_COMPATIBLE_SHELLS = frozenset({"bash", "zsh", "sh", "dash", "ksh", "mksh"})
1299
1300
1301	def _find_shell() -> str:

... (gap) ...

1329	    unchanged — we fall through to ``_find_bash``.
1330	    """
1331	    if not _IS_WINDOWS:
1332	        user_shell = os.environ.get("SHELL")
1333	        if (
1334	            user_shell
1335	            and os.path.isfile(user_shell)
1336	            and os.access(user_shell, os.X_OK)
1337	            and Path(user_shell).name in _SPAWN_COMPATIBLE_SHELLS
1338	        ):
1339	            return user_shell
1340	    return _find_bash()
1341
1342
1343	# Standard PATH entries for environments with minimal PATH.
1344	_SANE_PATH = (
1345	    "/opt/homebrew/bin:/opt/homebrew/sbin:"
1346	    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
1347	)
1348
1349	# Cached directory containing the ``hermes`` console-script.
1350	# ``_SENTINEL`` distinguishes "not resolved yet" from a resolved ``None``.
1351	_SENTINEL = object()
1352	_HERMES_BIN_DIR: "str | None | object" = _SENTINEL
1353
1354
1355	def _resolve_hermes_bin_dir() -> str | None:

... (gap) ...

1399	        exe_dir = os.path.dirname(sys.executable) if sys.executable else ""
1400	        if exe_dir:
1401	            shim = "hermes.exe" if _IS_WINDOWS else "hermes"
1402	            if os.path.isfile(os.path.join(exe_dir, shim)):
1403	                candidate = exe_dir
1404
1405	    if candidate and not os.path.isdir(candidate):

... (gap) ...

1417	    a PATH that already contains the dir is returned unchanged. Returns the
1418	    input unchanged when the install dir can't be resolved.
1419	    """
1420	    bin_dir = _resolve_hermes_bin_dir()
1421	    if not bin_dir:
1422	        return existing_path
1423	    sep = _env_path_sep()
1424	    entries = [e for e in existing_path.split(sep) if e] if existing_path else []
1425	    if bin_dir in entries:
1426	        return existing_path

... (gap) ...

1454	    try:
1455	        from hermes_constants import get_hermes_home, iter_hermes_node_dirs
1456
1457	        candidates = [*iter_hermes_node_dirs(), get_hermes_home() / "bin"]
1458	        entries = [str(d) for d in candidates if d.is_dir()]
1459	        if _IS_WINDOWS:
1460	            return entries
1461	        # Only a physical Windows host can produce native Windows entries while

... (gap) ...

1501
1502	    sane_entries = [entry for entry in _SANE_PATH.split(":") if entry]
1503	    sane_entries.extend(
1504	        entry for entry in _managed_runtime_path_entries() if entry not in sane_entries
1505	    )
1506	    if not existing_path:
1507	        return ":".join(sane_entries)
```


> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
