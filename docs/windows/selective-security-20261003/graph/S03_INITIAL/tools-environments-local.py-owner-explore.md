**Exploration: tools/environments/local.py**

Found 81 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _is_hermes_internal_secret(calls), _same_path(calls), _inject_context_hermes_home(calls), add(calls), _sweep_escaped_descendants(calls), _plugin_terminal_env_strip_keys(calls), _inject_session_context_env(calls), _strip_hermes_owned_pythonpath_and_runtime_markers(calls), _apply_windows_msys_bash_env_defaults(calls), _scrub_delegated_child_kanban_env(calls), _find_bash(calls), _path_env_key(calls), _prepend_hermes_bin_dir(calls), _env_path_sep(calls), +95 more

```python
394	# PYTHONPATH is NOT included here — it's handled by
395	# _strip_hermes_owned_pythonpath() which removes only Hermes-owned entries,
396	# preserving user-set paths.
397	_ACTIVE_VENV_MARKER_VARS = ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME")
398
399
400	def _is_hermes_internal_secret(key: str) -> bool:

... (gap) ...

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

529	        _resolve_passthrough_value = lambda _name, fallback: fallback  # noqa: E731
530
531	    sanitized: dict[str, str] = {}
532	    _plugin_strip = {key.upper() for key in _plugin_terminal_env_strip_keys()}
533	    _provider_strip = {key.upper() for key in _HERMES_PROVIDER_ENV_BLOCKLIST}
534
535	    for key, value in (base_env or {}).items():
536	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
537	            continue
538	        if _is_hermes_internal_secret(key):
539	            continue
540	        if key.upper() in _plugin_strip:
541	            continue
542	        passthrough = _is_passthrough(key)
543	        if key.upper() in _provider_strip and not passthrough:
544	            continue
545	        resolved = _resolve_passthrough_value(key, value) if passthrough else value
546	        if resolved is not None:
547	            sanitized[key] = resolved
548
549	    for key, value in (extra_env or {}).items():
550	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
551	            real_key = key[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
552	            if _is_hermes_internal_secret(real_key):
553	                continue
554	            sanitized[real_key] = value
555	        elif _is_hermes_internal_secret(key):
556	            continue
557	        elif key.upper() in _plugin_strip:
558	            continue
559	        else:
560	            passthrough = _is_passthrough(key)
561	            if key.upper() in _provider_strip and not passthrough:
562	                continue
563	            resolved = _resolve_passthrough_value(key, value) if passthrough else value
564	            if resolved is not None:
565	                sanitized[key] = resolved
566
567	    _inject_context_hermes_home(sanitized)
568
569	    from hermes_constants import apply_subprocess_home_env
570	    apply_subprocess_home_env(sanitized)
571
572	    # Same cross-session leak guard as _make_run_env, for the background/PTY
573	    # spawn path (process_registry.spawn_local builds env via this function).
574	    _inject_session_context_env(sanitized)
575
576	    # Filter PYTHONPATH before removing VIRTUAL_ENV: legacy Windows launchers
577	    # can run the gateway under a base interpreter while VIRTUAL_ENV identifies
578	    # the separate Hermes runtime venv.  The filter validates that relationship
579	    # against the repo layout before trusting it.
580	    _strip_hermes_owned_pythonpath_and_runtime_markers(sanitized)
581
582	    # Keep bare ``hermes`` invocations available to child jobs even when the
583	    # gateway was launched by a service manager or cron without the console
584	    # script's directory on PATH.  The terminal environment already applies
585	    # this invariant; Cron scripts use this sanitizer directly (#92998).
586	    path_key = _path_env_key(sanitized)
587	    if path_key is not None:
588	        sanitized[path_key] = _prepend_hermes_bin_dir(sanitized.get(path_key, ""))
589
590	    _apply_windows_msys_bash_env_defaults(sanitized)
591
592	    sanitized = _scrub_delegated_child_kanban_env(sanitized)
593
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

... (gap) ...

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

... (gap) ...

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

... (gap) ...

881	        # _sanitize_subprocess_env already performs HERMES_HOME override
882	        # bridging + apply_subprocess_home_env unconditionally; delegating
883	        # wholesale keeps one owner and zero drift.
884	        return _sanitize_subprocess_env(
885	            dict(base) if base is not None else os.environ.copy(),
886	            dict(extra) if extra else None,
887	        )
888
889	    env: dict[str, str] = dict(base) if base is not None else os.environ.copy()
890	    if inherit_profile_home:
891	        _inject_context_hermes_home(env)
892	        from hermes_constants import apply_subprocess_home_env
893	        apply_subprocess_home_env(env)
894	    if extra:
895	        env.update(extra)
896	    return env

... (gap) ...

912	    except (OSError, ValueError):
913	        resolved = os.path.normcase(str(candidate))
914
915	    windows_dir = ntpath.normcase(os.environ.get("WINDIR", r"C:\Windows"))
916	    windows_apps = ntpath.normcase(os.environ.get("LOCALAPPDATA", ""))
917	    stubs = {ntpath.normcase(ntpath.join(windows_dir, "System32", "bash.exe"))}
918	    if windows_apps:
919	        stubs.add(ntpath.normcase(ntpath.join(windows_apps, "Microsoft", "WindowsApps", "bash.exe")))
920	    return resolved in stubs
921
922
923	def _find_bash() -> str:
924	    """Find bash for command execution."""
925	    if not _IS_WINDOWS:
926	        return (
927	            shutil.which("bash")
928	            or ("/usr/bin/bash" if os.path.isfile("/usr/bin/bash") else None)
929	            or ("/bin/bash" if os.path.isfile("/bin/bash") else None)
930	            or os.environ.get("SHELL")
931	            or "/bin/sh"
932	        )
933
934	    candidates: list[str] = []
935
936	    custom = os.environ.get("HERMES_GIT_BASH_PATH")
937	    if custom and os.path.isfile(custom):
938	        candidates.append(custom)
939
940	    # Prefer our own portable Git install — a broken or partially-uninstalled
941	    # system Git (or a stale HERMES_GIT_BASH_PATH pointing at one) must not
942	    # brick the terminal.  install.ps1 drops PortableGit here when needed.
943	    #
944	    # Layouts (both checked so upgrades between MinGit and PortableGit
945	    # installs work transparently):
946	    #   PortableGit: %LOCALAPPDATA%\hermes\git\bin\bash.exe   (primary)
947	    #   MinGit:      %LOCALAPPDATA%\hermes\git\usr\bin\bash.exe (legacy/32-bit fallback)
948	    _local_appdata = os.environ.get("LOCALAPPDATA", "")
949	    _hermes_portable_git = os.path.join(_local_appdata, "hermes", "git") if _local_appdata else ""
950	    if _hermes_portable_git:
951	        for candidate in (
952	            os.path.join(_hermes_portable_git, "bin", "bash.exe"),        # PortableGit (primary)
953	            os.path.join(_hermes_portable_git, "usr", "bin", "bash.exe"), # MinGit fallback
954	        ):
955	            if os.path.isfile(candidate) and candidate not in candidates:
956	                candidates.append(candidate)
957
958	    # Check known Git for Windows install locations before PATH lookup.
959	    # On machines with both WSL and Git for Windows, shutil.which("bash")
960	    # may return WSL's bash (which doesn't understand Windows paths and
961	    # will fail silently).  Explicit Git-for-Windows paths avoid that.
962	    for candidate in (
963	        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"),
964	        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "bin", "bash.exe"),
965	        os.path.join(_local_appdata, "Programs", "Git", "bin", "bash.exe") if _local_appdata else "",
966	    ):
967	        if candidate and os.path.isfile(candidate) and candidate not in candidates:
968	            candidates.append(candidate)
969
970	    found = shutil.which("bash")
971	    if found and not _is_wsl_bash_stub(found) and found not in candidates:
972	        candidates.append(found)
973
974	    # Prefer the first candidate that can actually start.  A stale
975	    # HERMES_GIT_BASH_PATH pointing at a broken Git-for-Windows install
976	    # (``Directory \\drivers\\etc does not exist``) must not win over a
977	    # healthy portable Git under %LOCALAPPDATA%\\hermes\\git.
978	    for candidate in candidates:
979	        if _bash_starts(candidate):
980	            if candidate != custom and custom and os.path.isfile(custom):
981	                logger.warning(
982	                    "HERMES_GIT_BASH_PATH=%s fails to start; using %s instead",
983	                    custom,
984	                    candidate,
985	                )
986	            return candidate
987
988	    if candidates:
989	        probe_details = "\n".join(
990	            detail
991	            for candidate in candidates
992	            if (detail := _bash_probe_details_cache.get(candidate))
993	        )
994	        if _mandatory_aslr_enabled() is True or _looks_like_msys_spawn_failure(
995	            probe_details
996	        ):
997	            raise RuntimeError(_git_bash_aslr_help(candidates[0], probe_details))
998
999	        # Last resort for failures unrelated to the known MSYS/ASLR class:
1000	        # return the first path so the caller still sees the real bash error
1001	        # instead of the less useful "not found" message.
1002	        return candidates[0]
1003
1004	    raise RuntimeError(
1005	        "Git Bash not found. Hermes Agent requires Git for Windows on Windows.\n"
1006	        "Install it from: https://git-scm.com/download/win\n"
1007	        "Or set HERMES_GIT_BASH_PATH to your bash.exe location."
1008	    )
1009
1010
1011	_bash_starts_cache: dict[str, bool] = {}
1012	_bash_probe_details_cache: dict[str, str] = {}
1013	_mandatory_aslr_enabled_cache: "bool | None" = None
1014
1015	_BASH_EXTERNAL_PROGRAM_PROBE = "/usr/bin/true; /usr/bin/cat --version >/dev/null"
1016
1017
1018	def _looks_like_msys_spawn_failure(details: str) -> bool:
1019	    """Match Git-for-Windows child-launch failures associated with ASLR."""
1020	    lowered = details.lower()
1021	    return any(
1022	        marker in lowered
1023	        for marker in (
1024	            "dofork:",
1025	            "child_copy:",
1026	            "0xc0000142",
1027	            "0xc0000005",
1028	        )
1029	    )
1030
1031
1032	def _mandatory_aslr_enabled() -> "bool | None":

... (gap) ...

1048	            capture_output=True,
1049	            text=True, encoding="utf-8", errors="replace",
1050	            timeout=10,
1051	            creationflags=windows_hide_flags(),
1052	            stdin=subprocess.DEVNULL,
1053	        )
1054	        if result.returncode != 0:
1055	            return None
1056	        value = (result.stdout or "").strip().upper()
1057	        if value == "ON":
1058	            _mandatory_aslr_enabled_cache = True
1059	            return True
1060	        if value in {"OFF", "NOTSET"}:
1061	            _mandatory_aslr_enabled_cache = False
1062	            return False
1063	    except Exception as exc:
1064	        logger.debug("Could not query Windows Mandatory ASLR state: %s", exc)
1065	    return None
1066
1067
1068	def _git_root_from_bash(bash: str) -> str:
1069	    """Resolve Git's root from either <root>/bin or <root>/usr/bin bash."""
1070	    bin_dir = ntpath.dirname(ntpath.normpath(bash))
1071	    if ntpath.basename(bin_dir).lower() != "bin":
1072	        return ntpath.dirname(bin_dir)
1073	    parent = ntpath.dirname(bin_dir)
1074	    if ntpath.basename(parent).lower() == "usr":
1075	        return ntpath.dirname(parent)
1076	    return parent
1077
1078
1079	def _git_bash_aslr_help(bash: str, details: str = "") -> str:
1080	    """Build the targeted per-program Mandatory-ASLR remediation."""
1081	    git_root = _git_root_from_bash(bash)
1082	    escaped_root = git_root.replace("'", "''")
1083	    detail_line = f"\nGit Bash probe output: {details[:500]}" if details else ""
1084	    return (

... (gap) ...

1105	    a builtin-only ``exit 0`` probe misses Git-for-Windows fork/spawn failures
1106	    under system-wide Mandatory ASLR. Cached per path for the process lifetime.
1107	    """
1108	    cached = _bash_starts_cache.get(bash)
1109	    if cached is not None:
1110	        return cached
1111
1112	    try:
1113	        result = subprocess.run(
1114	            [bash, "--noprofile", "--norc", "-c", _BASH_EXTERNAL_PROGRAM_PROBE],
1115	            capture_output=True,
1116	            text=True, encoding="utf-8", errors="replace",
1117	            timeout=15,
1118	            creationflags=windows_hide_flags() if _IS_WINDOWS else 0,
1119	            stdin=subprocess.DEVNULL,
1120	        )
1121	        ok = result.returncode == 0

... (gap) ...

1132	    return ok
1133
1134
1135	_git_bash_bin_dirs_cache: "list[str] | None" = None
1136
1137
1138	def _env_path_sep() -> str:
1139	    """PATH separator for the *logical* platform (honours ``_IS_WINDOWS`` patches).
1140
1141	    Tests monkeypatch ``_IS_WINDOWS`` to exercise Unix/Windows PATH branches on
1142	    a single host. Using bare ``os.pathsep`` there mixes ``;`` into ``:``-joined
1143	    PATH strings (and the reverse), which corrupts entries such as
1144	    ``C:\\Program Files\\…`` when later split on ``:``.
1145	    """
1146	    return ";" if _IS_WINDOWS else ":"
1147
1148
1149	def _git_bash_bin_dirs() -> list[str]:

... (gap) ...

1174
1175	    dirs: list[str] = []
1176	    try:
1177	        bash = _find_bash()
1178	    except Exception:
1179	        _git_bash_bin_dirs_cache = []
1180	        return _git_bash_bin_dirs_cache
1181
1182	    bin_dir = os.path.dirname(bash)          # <root>\bin  or  <root>\usr\bin
1183	    parent = os.path.dirname(bin_dir)
1184	    # MinGit ships bash under usr\bin; PortableGit/system Git under bin.
1185	    root = os.path.dirname(parent) if os.path.basename(parent).lower() == "usr" else parent
1186
1187	    # Order mirrors Git-for-Windows /etc/profile so coreutils win over the
1188	    # same-named Windows System32 tools (find.exe, sort.exe) inside the shell.
1189	    for candidate in (
1190	        os.path.join(root, "mingw64", "bin"),
1191	        os.path.join(root, "mingw32", "bin"),
1192	        os.path.join(root, "usr", "local", "bin"),
1193	        os.path.join(root, "usr", "bin"),
1194	        os.path.join(root, "bin"),
1195	    ):
1196	        if os.path.isdir(candidate) and candidate not in dirs:
1197	            dirs.append(candidate)

... (gap) ...

1211	    """
1212	    if not _IS_WINDOWS:
1213	        return existing_path
1214	    git_dirs = _git_bash_bin_dirs()
1215	    if not git_dirs:
1216	        return existing_path
1217	    sep = _env_path_sep()
1218	    entries = [e for e in existing_path.split(sep) if e] if existing_path else []
1219	    missing = [d for d in git_dirs if d not in entries]
1220	    if not missing:
1221	        return existing_path
1222	    return sep.join([*missing, *entries])
1223
1224
1225	# POSIX-sh-family shells that understand the ``[shell, "-lic", "set +m; …"]``
1226	# invocation spawn_local uses. $SHELL values outside this set (fish, csh/tcsh,
1227	# nushell, elvish, xonsh, …) would error on that syntax, so _find_shell falls
1228	# back to bash for them rather than honouring $SHELL. (#42203)
1229	_SPAWN_COMPATIBLE_SHELLS = frozenset({"bash", "zsh", "sh", "dash", "ksh", "mksh"})
1230
1231
1232	def _find_shell() -> str:

... (gap) ...

1260	    unchanged — we fall through to ``_find_bash``.
1261	    """
1262	    if not _IS_WINDOWS:
1263	        user_shell = os.environ.get("SHELL")
1264	        if (
1265	            user_shell
1266	            and os.path.isfile(user_shell)
1267	            and os.access(user_shell, os.X_OK)
1268	            and Path(user_shell).name in _SPAWN_COMPATIBLE_SHELLS
1269	        ):
1270	            return user_shell
1271	    return _find_bash()
1272
1273
1274	# Standard PATH entries for environments with minimal PATH.
1275	_SANE_PATH = (
1276	    "/opt/homebrew/bin:/opt/homebrew/sbin:"
1277	    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
1278	)
1279
1280	# Cached directory containing the ``hermes`` console-script.
1281	# ``_SENTINEL`` distinguishes "not resolved yet" from a resolved ``None``.
1282	_SENTINEL = object()
1283	_HERMES_BIN_DIR: "str | None | object" = _SENTINEL
1284
1285
1286	def _resolve_hermes_bin_dir() -> str | None:

... (gap) ...

1330	        exe_dir = os.path.dirname(sys.executable) if sys.executable else ""
1331	        if exe_dir:
1332	            shim = "hermes.exe" if _IS_WINDOWS else "hermes"
1333	            if os.path.isfile(os.path.join(exe_dir, shim)):
1334	                candidate = exe_dir
1335
1336	    if candidate and not os.path.isdir(candidate):

... (gap) ...

1348	    a PATH that already contains the dir is returned unchanged. Returns the
1349	    input unchanged when the install dir can't be resolved.
1350	    """
1351	    bin_dir = _resolve_hermes_bin_dir()
1352	    if not bin_dir:
1353	        return existing_path
1354	    sep = _env_path_sep()
1355	    entries = [e for e in existing_path.split(sep) if e] if existing_path else []
1356	    if bin_dir in entries:
1357	        return existing_path

... (gap) ...

1385	    try:
1386	        from hermes_constants import get_hermes_home, iter_hermes_node_dirs
1387
1388	        candidates = [*iter_hermes_node_dirs(), get_hermes_home() / "bin"]
1389	        entries = [str(d) for d in candidates if d.is_dir()]
1390	        if _IS_WINDOWS:
1391	            return entries
1392	        # Only a physical Windows host can produce native Windows entries while

... (gap) ...

1432
1433	    sane_entries = [entry for entry in _SANE_PATH.split(":") if entry]
1434	    sane_entries.extend(
1435	        entry for entry in _managed_runtime_path_entries() if entry not in sane_entries
1436	    )
1437	    if not existing_path:
1438	        return ":".join(sane_entries)

... (gap) ...

1513	    for k, v in merged.items():
1514	        if k.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
1515	            real_key = k[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
1516	            if _is_hermes_internal_secret(real_key):
1517	                continue
1518	            run_env[real_key] = v
1519	        elif _is_hermes_internal_secret(k):
1520	            continue
1521	        else:
1522	            passthrough = _is_passthrough(k)
1523	            if k in _HERMES_PROVIDER_ENV_BLOCKLIST and not passthrough:
1524	                continue
1525	            value = _resolve_passthrough_value(k, v) if passthrough else v
1526	            if value is not None:
1527	                run_env[k] = value
1528	    path_key = _path_env_key(run_env)
1529	    if path_key is not None:
1530	        new_path = _append_missing_sane_path_entries(run_env.get(path_key, ""))
```
