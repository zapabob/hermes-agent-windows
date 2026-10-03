**Exploration: tools/environments/local.py**

Found 92 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _is_hermes_internal_secret(calls), _provider_secret_env(calls), _plugin_terminal_env_strip_keys(calls), _same_path(calls), _child_policy_home(calls), _inject_context_hermes_home(calls), add(calls), _sweep_escaped_descendants(calls), _profile_child_base(calls), _inject_session_context_env(calls), _strip_hermes_owned_pythonpath_and_runtime_markers(calls), _apply_windows_msys_bash_env_defaults(calls), _scrub_delegated_child_kanban_env(calls), _find_bash(calls), +116 more

```python
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
508	    from agent.secret_scope import _is_global_env, load_env_file
509	    from hermes_cli.config import platform_manifest_secret_envs
510	    from hermes_cli.env_loader import get_secret_source_values, loaded_profile_env_keys, launch_profile_home
511
512	    if _child_policy_home() is None:
513	        return frozenset()
514	    launch = launch_profile_home()
515	    names = set(load_env_file(launch / ".env")) | set(load_env_file(launch / ".op.env"))
516	    names.update(loaded_profile_env_keys(launch))
517	    names.update(get_secret_source_values(launch))
518	    return frozenset(name.upper() for name in names if not _is_global_env(name)) | platform_manifest_secret_envs(launch)
519
520
521	def _child_policy_home() -> Path | None:
522	    """A minimal OS environment may have no resolvable profile directory."""
523	    from hermes_constants import get_hermes_home, get_hermes_home_override
524
525	    home_names = ("HERMES_HOME", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE") if _IS_WINDOWS else ("HERMES_HOME", "HOME")
526	    if get_hermes_home_override() or any(os.environ.get(name) for name in home_names):
527	        return get_hermes_home()
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

... (gap) ...

626	    except Exception:
627	        return
628
629	    _engaged = session_context_engaged()
630	    for var_name, var in _VAR_MAP.items():
631	        value = var.get()
632	        if value is not _UNSET:

... (gap) ...

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

... (gap) ...

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

... (gap) ...

1007	        # _sanitize_subprocess_env already performs HERMES_HOME override
1008	        # bridging + apply_subprocess_home_env unconditionally; delegating
1009	        # wholesale keeps one owner and zero drift.
1010	        return _sanitize_subprocess_env(
1011	            dict(base) if base is not None else os.environ.copy(),
1012	            dict(extra) if extra else None,
1013	        )
1014
1015	    env: dict[str, str] = dict(base) if base is not None else os.environ.copy()
1016	    if inherit_profile_home:
1017	        _inject_context_hermes_home(env)
1018	        from hermes_constants import apply_subprocess_home_env
1019	        apply_subprocess_home_env(env)
1020	    if extra:
1021	        env.update(extra)
1022	    return env

... (gap) ...

1038	    except (OSError, ValueError):
1039	        resolved = os.path.normcase(str(candidate))
1040
1041	    windows_dir = ntpath.normcase(os.environ.get("WINDIR", r"C:\Windows"))
1042	    windows_apps = ntpath.normcase(os.environ.get("LOCALAPPDATA", ""))
1043	    stubs = {ntpath.normcase(ntpath.join(windows_dir, "System32", "bash.exe"))}
1044	    if windows_apps:
1045	        stubs.add(ntpath.normcase(ntpath.join(windows_apps, "Microsoft", "WindowsApps", "bash.exe")))
1046	    return resolved in stubs
1047
1048
1049	def _find_bash() -> str:
1050	    """Find bash for command execution."""
1051	    if not _IS_WINDOWS:
1052	        return (
1053	            shutil.which("bash")
1054	            or ("/usr/bin/bash" if os.path.isfile("/usr/bin/bash") else None)
1055	            or ("/bin/bash" if os.path.isfile("/bin/bash") else None)
1056	            or os.environ.get("SHELL")
1057	            or "/bin/sh"
1058	        )
1059
1060	    candidates: list[str] = []
1061
1062	    custom = os.environ.get("HERMES_GIT_BASH_PATH")
1063	    if custom and os.path.isfile(custom):
1064	        candidates.append(custom)
1065
1066	    # Prefer our own portable Git install — a broken or partially-uninstalled
1067	    # system Git (or a stale HERMES_GIT_BASH_PATH pointing at one) must not
1068	    # brick the terminal.  install.ps1 drops PortableGit here when needed.
1069	    #
1070	    # Layouts (both checked so upgrades between MinGit and PortableGit
1071	    # installs work transparently):
1072	    #   PortableGit: %LOCALAPPDATA%\hermes\git\bin\bash.exe   (primary)
1073	    #   MinGit:      %LOCALAPPDATA%\hermes\git\usr\bin\bash.exe (legacy/32-bit fallback)
1074	    _local_appdata = os.environ.get("LOCALAPPDATA", "")
1075	    _hermes_portable_git = os.path.join(_local_appdata, "hermes", "git") if _local_appdata else ""
1076	    if _hermes_portable_git:
1077	        for candidate in (
1078	            os.path.join(_hermes_portable_git, "bin", "bash.exe"),        # PortableGit (primary)
1079	            os.path.join(_hermes_portable_git, "usr", "bin", "bash.exe"), # MinGit fallback
1080	        ):
1081	            if os.path.isfile(candidate) and candidate not in candidates:
1082	                candidates.append(candidate)
1083
1084	    # Check known Git for Windows install locations before PATH lookup.
1085	    # On machines with both WSL and Git for Windows, shutil.which("bash")
1086	    # may return WSL's bash (which doesn't understand Windows paths and
1087	    # will fail silently).  Explicit Git-for-Windows paths avoid that.
1088	    for candidate in (
1089	        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"),
1090	        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "bin", "bash.exe"),
1091	        os.path.join(_local_appdata, "Programs", "Git", "bin", "bash.exe") if _local_appdata else "",
1092	    ):
1093	        if candidate and os.path.isfile(candidate) and candidate not in candidates:
1094	            candidates.append(candidate)
1095
1096	    found = shutil.which("bash")
1097	    if found and not _is_wsl_bash_stub(found) and found not in candidates:
1098	        candidates.append(found)
1099
1100	    # Prefer the first candidate that can actually start.  A stale
1101	    # HERMES_GIT_BASH_PATH pointing at a broken Git-for-Windows install
1102	    # (``Directory \\drivers\\etc does not exist``) must not win over a
1103	    # healthy portable Git under %LOCALAPPDATA%\\hermes\\git.
1104	    for candidate in candidates:
1105	        if _bash_starts(candidate):
1106	            if candidate != custom and custom and os.path.isfile(custom):
1107	                logger.warning(
1108	                    "HERMES_GIT_BASH_PATH=%s fails to start; using %s instead",
1109	                    custom,
1110	                    candidate,
1111	                )
1112	            return candidate
1113
1114	    if candidates:
1115	        probe_details = "\n".join(
1116	            detail
1117	            for candidate in candidates
1118	            if (detail := _bash_probe_details_cache.get(candidate))
1119	        )
1120	        if _mandatory_aslr_enabled() is True or _looks_like_msys_spawn_failure(
1121	            probe_details
1122	        ):
1123	            raise RuntimeError(_git_bash_aslr_help(candidates[0], probe_details))
1124
1125	        # Last resort for failures unrelated to the known MSYS/ASLR class:
1126	        # return the first path so the caller still sees the real bash error

... (gap) ...

1174	            capture_output=True,
1175	            text=True, encoding="utf-8", errors="replace",
1176	            timeout=10,
1177	            creationflags=windows_hide_flags(),
1178	            stdin=subprocess.DEVNULL,
1179	        )
1180	        if result.returncode != 0:
1181	            return None
1182	        value = (result.stdout or "").strip().upper()
1183	        if value == "ON":
1184	            _mandatory_aslr_enabled_cache = True
1185	            return True

... (gap) ...

1204
1205	def _git_bash_aslr_help(bash: str, details: str = "") -> str:
1206	    """Build the targeted per-program Mandatory-ASLR remediation."""
1207	    git_root = _git_root_from_bash(bash)
1208	    escaped_root = git_root.replace("'", "''")
1209	    detail_line = f"\nGit Bash probe output: {details[:500]}" if details else ""
1210	    return (

... (gap) ...

1231	    a builtin-only ``exit 0`` probe misses Git-for-Windows fork/spawn failures
1232	    under system-wide Mandatory ASLR. Cached per path for the process lifetime.
1233	    """
1234	    cached = _bash_starts_cache.get(bash)
1235	    if cached is not None:
1236	        return cached
1237
1238	    try:
1239	        result = subprocess.run(
1240	            [bash, "--noprofile", "--norc", "-c", _BASH_EXTERNAL_PROGRAM_PROBE],
1241	            capture_output=True,
1242	            text=True, encoding="utf-8", errors="replace",
1243	            timeout=15,
1244	            creationflags=windows_hide_flags() if _IS_WINDOWS else 0,
1245	            stdin=subprocess.DEVNULL,
1246	        )
1247	        ok = result.returncode == 0

... (gap) ...

1300
1301	    dirs: list[str] = []
1302	    try:
1303	        bash = _find_bash()
1304	    except Exception:
1305	        _git_bash_bin_dirs_cache = []
1306	        return _git_bash_bin_dirs_cache
1307
1308	    bin_dir = os.path.dirname(bash)          # <root>\bin  or  <root>\usr\bin
1309	    parent = os.path.dirname(bin_dir)
1310	    # MinGit ships bash under usr\bin; PortableGit/system Git under bin.
1311	    root = os.path.dirname(parent) if os.path.basename(parent).lower() == "usr" else parent
1312
1313	    # Order mirrors Git-for-Windows /etc/profile so coreutils win over the
1314	    # same-named Windows System32 tools (find.exe, sort.exe) inside the shell.
1315	    for candidate in (
1316	        os.path.join(root, "mingw64", "bin"),
1317	        os.path.join(root, "mingw32", "bin"),
1318	        os.path.join(root, "usr", "local", "bin"),
1319	        os.path.join(root, "usr", "bin"),
1320	        os.path.join(root, "bin"),
1321	    ):
1322	        if os.path.isdir(candidate) and candidate not in dirs:
1323	            dirs.append(candidate)

... (gap) ...

1337	    """
1338	    if not _IS_WINDOWS:
1339	        return existing_path
1340	    git_dirs = _git_bash_bin_dirs()
1341	    if not git_dirs:
1342	        return existing_path
1343	    sep = _env_path_sep()
1344	    entries = [e for e in existing_path.split(sep) if e] if existing_path else []
1345	    missing = [d for d in git_dirs if d not in entries]
1346	    if not missing:

... (gap) ...

1386	    unchanged — we fall through to ``_find_bash``.
1387	    """
1388	    if not _IS_WINDOWS:
1389	        user_shell = os.environ.get("SHELL")
1390	        if (
1391	            user_shell
1392	            and os.path.isfile(user_shell)
1393	            and os.access(user_shell, os.X_OK)
1394	            and Path(user_shell).name in _SPAWN_COMPATIBLE_SHELLS
1395	        ):
1396	            return user_shell
1397	    return _find_bash()
1398
1399
1400	# Standard PATH entries for environments with minimal PATH.

... (gap) ...

1456	        exe_dir = os.path.dirname(sys.executable) if sys.executable else ""
1457	        if exe_dir:
1458	            shim = "hermes.exe" if _IS_WINDOWS else "hermes"
1459	            if os.path.isfile(os.path.join(exe_dir, shim)):
1460	                candidate = exe_dir
1461
1462	    if candidate and not os.path.isdir(candidate):

... (gap) ...

1474	    a PATH that already contains the dir is returned unchanged. Returns the
1475	    input unchanged when the install dir can't be resolved.
1476	    """
1477	    bin_dir = _resolve_hermes_bin_dir()
1478	    if not bin_dir:
1479	        return existing_path
1480	    sep = _env_path_sep()
1481	    entries = [e for e in existing_path.split(sep) if e] if existing_path else []
1482	    if bin_dir in entries:
1483	        return existing_path

... (gap) ...

1511	    try:
1512	        from hermes_constants import get_hermes_home, iter_hermes_node_dirs
1513
1514	        candidates = [*iter_hermes_node_dirs(), get_hermes_home() / "bin"]
1515	        entries = [str(d) for d in candidates if d.is_dir()]
1516	        if _IS_WINDOWS:
1517	            return entries
1518	        # Only a physical Windows host can produce native Windows entries while

... (gap) ...

1558
1559	    sane_entries = [entry for entry in _SANE_PATH.split(":") if entry]
1560	    sane_entries.extend(
1561	        entry for entry in _managed_runtime_path_entries() if entry not in sane_entries
1562	    )
1563	    if not existing_path:
1564	        return ":".join(sane_entries)
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
