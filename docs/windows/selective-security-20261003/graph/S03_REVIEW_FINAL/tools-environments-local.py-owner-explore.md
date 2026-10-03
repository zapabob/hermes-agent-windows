**Exploration: tools/environments/local.py**

Found 91 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _is_hermes_internal_secret(calls), _provider_secret_env(calls), _plugin_terminal_env_strip_keys(calls), _same_path(calls), _child_policy_home(calls), _inject_context_hermes_home(calls), add(calls), _sweep_escaped_descendants(calls), _profile_child_base(calls), _inject_session_context_env(calls), _strip_hermes_owned_pythonpath_and_runtime_markers(calls), _apply_windows_msys_bash_env_defaults(calls), _scrub_delegated_child_kanban_env(calls), _find_bash(calls), +116 more

```python
495	        name.upper() for name, meta in OPTIONAL_ENV_VARS.items()
496	        if meta.get("category") == "messaging" and meta.get("password")
497	    )
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
512	    from agent.secret_scope import _is_global_env, load_env_file
513	    from hermes_cli.config import platform_manifest_secret_envs
514	    from hermes_cli.env_loader import get_secret_source_values, loaded_profile_env_keys, launch_profile_home
515
516	    if _child_policy_home() is None:
517	        return frozenset()
518	    launch = launch_profile_home()
519	    names = set(load_env_file(launch / ".env")) | set(load_env_file(launch / ".op.env"))
520	    names.update(loaded_profile_env_keys(launch))
521	    names.update(get_secret_source_values(launch))
522	    return frozenset(name.upper() for name in names if not _is_global_env(name)) | platform_manifest_secret_envs(launch)
523
524
525	def _child_policy_home() -> Path | None:
526	    """A minimal OS environment may have no resolvable profile directory."""
527	    from hermes_constants import get_hermes_home, get_hermes_home_override
528
529	    home_names = ("HERMES_HOME", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE") if _IS_WINDOWS else ("HERMES_HOME", "HOME")
530	    if get_hermes_home_override() or any(os.environ.get(name) for name in home_names):
531	        return get_hermes_home()
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

... (gap) ...

630	    except Exception:
631	        return
632
633	    _engaged = session_context_engaged()
634	    for var_name, var in _VAR_MAP.items():
635	        value = var.get()
636	        if value is not _UNSET:

... (gap) ...

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

... (gap) ...

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

... (gap) ...

1011	        # _sanitize_subprocess_env already performs HERMES_HOME override
1012	        # bridging + apply_subprocess_home_env unconditionally; delegating
1013	        # wholesale keeps one owner and zero drift.
1014	        return _sanitize_subprocess_env(
1015	            dict(base) if base is not None else os.environ.copy(),
1016	            dict(extra) if extra else None,
1017	        )
1018
1019	    env: dict[str, str] = dict(base) if base is not None else os.environ.copy()
1020	    if inherit_profile_home:
1021	        _inject_context_hermes_home(env)
1022	        from hermes_constants import apply_subprocess_home_env
1023	        apply_subprocess_home_env(env)
1024	    if extra:
1025	        env.update(extra)
1026	    return env

... (gap) ...

1042	    except (OSError, ValueError):
1043	        resolved = os.path.normcase(str(candidate))
1044
1045	    windows_dir = ntpath.normcase(os.environ.get("WINDIR", r"C:\Windows"))
1046	    windows_apps = ntpath.normcase(os.environ.get("LOCALAPPDATA", ""))
1047	    stubs = {ntpath.normcase(ntpath.join(windows_dir, "System32", "bash.exe"))}
1048	    if windows_apps:
1049	        stubs.add(ntpath.normcase(ntpath.join(windows_apps, "Microsoft", "WindowsApps", "bash.exe")))
1050	    return resolved in stubs
1051
1052
1053	def _find_bash() -> str:
1054	    """Find bash for command execution."""
1055	    if not _IS_WINDOWS:
1056	        return (
1057	            shutil.which("bash")
1058	            or ("/usr/bin/bash" if os.path.isfile("/usr/bin/bash") else None)
1059	            or ("/bin/bash" if os.path.isfile("/bin/bash") else None)
1060	            or os.environ.get("SHELL")
1061	            or "/bin/sh"
1062	        )
1063
1064	    candidates: list[str] = []
1065
1066	    custom = os.environ.get("HERMES_GIT_BASH_PATH")
1067	    if custom and os.path.isfile(custom):
1068	        candidates.append(custom)
1069
1070	    # Prefer our own portable Git install — a broken or partially-uninstalled
1071	    # system Git (or a stale HERMES_GIT_BASH_PATH pointing at one) must not
1072	    # brick the terminal.  install.ps1 drops PortableGit here when needed.
1073	    #
1074	    # Layouts (both checked so upgrades between MinGit and PortableGit
1075	    # installs work transparently):
1076	    #   PortableGit: %LOCALAPPDATA%\hermes\git\bin\bash.exe   (primary)
1077	    #   MinGit:      %LOCALAPPDATA%\hermes\git\usr\bin\bash.exe (legacy/32-bit fallback)
1078	    _local_appdata = os.environ.get("LOCALAPPDATA", "")
1079	    _hermes_portable_git = os.path.join(_local_appdata, "hermes", "git") if _local_appdata else ""
1080	    if _hermes_portable_git:
1081	        for candidate in (
1082	            os.path.join(_hermes_portable_git, "bin", "bash.exe"),        # PortableGit (primary)
1083	            os.path.join(_hermes_portable_git, "usr", "bin", "bash.exe"), # MinGit fallback
1084	        ):
1085	            if os.path.isfile(candidate) and candidate not in candidates:
1086	                candidates.append(candidate)
1087
1088	    # Check known Git for Windows install locations before PATH lookup.
1089	    # On machines with both WSL and Git for Windows, shutil.which("bash")
1090	    # may return WSL's bash (which doesn't understand Windows paths and
1091	    # will fail silently).  Explicit Git-for-Windows paths avoid that.
1092	    for candidate in (
1093	        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"),
1094	        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "bin", "bash.exe"),
1095	        os.path.join(_local_appdata, "Programs", "Git", "bin", "bash.exe") if _local_appdata else "",
1096	    ):
1097	        if candidate and os.path.isfile(candidate) and candidate not in candidates:
1098	            candidates.append(candidate)
1099
1100	    found = shutil.which("bash")
1101	    if found and not _is_wsl_bash_stub(found) and found not in candidates:
1102	        candidates.append(found)
1103
1104	    # Prefer the first candidate that can actually start.  A stale
1105	    # HERMES_GIT_BASH_PATH pointing at a broken Git-for-Windows install
1106	    # (``Directory \\drivers\\etc does not exist``) must not win over a
1107	    # healthy portable Git under %LOCALAPPDATA%\\hermes\\git.
1108	    for candidate in candidates:
1109	        if _bash_starts(candidate):
1110	            if candidate != custom and custom and os.path.isfile(custom):
1111	                logger.warning(
1112	                    "HERMES_GIT_BASH_PATH=%s fails to start; using %s instead",
1113	                    custom,
1114	                    candidate,
1115	                )
1116	            return candidate
1117
1118	    if candidates:
1119	        probe_details = "\n".join(
1120	            detail
1121	            for candidate in candidates
1122	            if (detail := _bash_probe_details_cache.get(candidate))
1123	        )
1124	        if _mandatory_aslr_enabled() is True or _looks_like_msys_spawn_failure(
1125	            probe_details
1126	        ):
1127	            raise RuntimeError(_git_bash_aslr_help(candidates[0], probe_details))
1128
1129	        # Last resort for failures unrelated to the known MSYS/ASLR class:
1130	        # return the first path so the caller still sees the real bash error

... (gap) ...

1178	            capture_output=True,
1179	            text=True, encoding="utf-8", errors="replace",
1180	            timeout=10,
1181	            creationflags=windows_hide_flags(),
1182	            stdin=subprocess.DEVNULL,
1183	        )
1184	        if result.returncode != 0:
1185	            return None
1186	        value = (result.stdout or "").strip().upper()
1187	        if value == "ON":
1188	            _mandatory_aslr_enabled_cache = True
1189	            return True

... (gap) ...

1208
1209	def _git_bash_aslr_help(bash: str, details: str = "") -> str:
1210	    """Build the targeted per-program Mandatory-ASLR remediation."""
1211	    git_root = _git_root_from_bash(bash)
1212	    escaped_root = git_root.replace("'", "''")
1213	    detail_line = f"\nGit Bash probe output: {details[:500]}" if details else ""
1214	    return (

... (gap) ...

1235	    a builtin-only ``exit 0`` probe misses Git-for-Windows fork/spawn failures
1236	    under system-wide Mandatory ASLR. Cached per path for the process lifetime.
1237	    """
1238	    cached = _bash_starts_cache.get(bash)
1239	    if cached is not None:
1240	        return cached
1241
1242	    try:
1243	        result = subprocess.run(
1244	            [bash, "--noprofile", "--norc", "-c", _BASH_EXTERNAL_PROGRAM_PROBE],
1245	            capture_output=True,
1246	            text=True, encoding="utf-8", errors="replace",
1247	            timeout=15,
1248	            creationflags=windows_hide_flags() if _IS_WINDOWS else 0,
1249	            stdin=subprocess.DEVNULL,
1250	        )
1251	        ok = result.returncode == 0

... (gap) ...

1304
1305	    dirs: list[str] = []
1306	    try:
1307	        bash = _find_bash()
1308	    except Exception:
1309	        _git_bash_bin_dirs_cache = []
1310	        return _git_bash_bin_dirs_cache
1311
1312	    bin_dir = os.path.dirname(bash)          # <root>\bin  or  <root>\usr\bin
1313	    parent = os.path.dirname(bin_dir)
1314	    # MinGit ships bash under usr\bin; PortableGit/system Git under bin.
1315	    root = os.path.dirname(parent) if os.path.basename(parent).lower() == "usr" else parent
1316
1317	    # Order mirrors Git-for-Windows /etc/profile so coreutils win over the
1318	    # same-named Windows System32 tools (find.exe, sort.exe) inside the shell.
1319	    for candidate in (
1320	        os.path.join(root, "mingw64", "bin"),
1321	        os.path.join(root, "mingw32", "bin"),
1322	        os.path.join(root, "usr", "local", "bin"),
1323	        os.path.join(root, "usr", "bin"),
1324	        os.path.join(root, "bin"),
1325	    ):
1326	        if os.path.isdir(candidate) and candidate not in dirs:
1327	            dirs.append(candidate)

... (gap) ...

1341	    """
1342	    if not _IS_WINDOWS:
1343	        return existing_path
1344	    git_dirs = _git_bash_bin_dirs()
1345	    if not git_dirs:
1346	        return existing_path
1347	    sep = _env_path_sep()
1348	    entries = [e for e in existing_path.split(sep) if e] if existing_path else []
1349	    missing = [d for d in git_dirs if d not in entries]
1350	    if not missing:

... (gap) ...

1390	    unchanged — we fall through to ``_find_bash``.
1391	    """
1392	    if not _IS_WINDOWS:
1393	        user_shell = os.environ.get("SHELL")
1394	        if (
1395	            user_shell
1396	            and os.path.isfile(user_shell)
1397	            and os.access(user_shell, os.X_OK)
1398	            and Path(user_shell).name in _SPAWN_COMPATIBLE_SHELLS
1399	        ):
1400	            return user_shell
1401	    return _find_bash()
1402
1403
1404	# Standard PATH entries for environments with minimal PATH.

... (gap) ...

1460	        exe_dir = os.path.dirname(sys.executable) if sys.executable else ""
1461	        if exe_dir:
1462	            shim = "hermes.exe" if _IS_WINDOWS else "hermes"
1463	            if os.path.isfile(os.path.join(exe_dir, shim)):
1464	                candidate = exe_dir
1465
1466	    if candidate and not os.path.isdir(candidate):

... (gap) ...

1478	    a PATH that already contains the dir is returned unchanged. Returns the
1479	    input unchanged when the install dir can't be resolved.
1480	    """
1481	    bin_dir = _resolve_hermes_bin_dir()
1482	    if not bin_dir:
1483	        return existing_path
1484	    sep = _env_path_sep()
1485	    entries = [e for e in existing_path.split(sep) if e] if existing_path else []
1486	    if bin_dir in entries:
1487	        return existing_path

... (gap) ...

1515	    try:
1516	        from hermes_constants import get_hermes_home, iter_hermes_node_dirs
1517
1518	        candidates = [*iter_hermes_node_dirs(), get_hermes_home() / "bin"]
1519	        entries = [str(d) for d in candidates if d.is_dir()]
1520	        if _IS_WINDOWS:
1521	            return entries
1522	        # Only a physical Windows host can produce native Windows entries while

... (gap) ...

1562
1563	    sane_entries = [entry for entry in _SANE_PATH.split(":") if entry]
1564	    sane_entries.extend(
1565	        entry for entry in _managed_runtime_path_entries() if entry not in sane_entries
1566	    )
1567	    if not existing_path:
1568	        return ":".join(sane_entries)

... (gap) ...

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
```
