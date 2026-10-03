**Exploration: tools/environments/local.py**

Found 66 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _msys_to_windows_path(calls), _default_terminal_temp_dir(calls), _find_bash(calls), _posix(calls), _windows_to_msys_path(calls), _cwd_usable(calls), _apply_profile_home(calls), _finalize_child_env(calls), _scrubbed_env(calls), _prepend_missing_path_entries(calls), _wait_for_group_exit(calls), _prune_terminal_temp_once(calls), _IS_WINDOWS(variable), logger(variable), +91 more

```python
31	    _build_hermes_repo_root_aliases, _strip_hermes_owned_pythonpath_and_runtime_markers)
32
33
34	_IS_WINDOWS = platform.system() == "Windows"
35
36	logger = logging.getLogger(__name__)
37
38	# --- Terminal temp-cache pruning ---
39	# get_temp_dir() defaults to HERMES_HOME/cache/terminal (real storage, not tmpfs), so
40	# stale artifacts don't vanish on reboot: the gateway housekeeping loop prunes hourly
41	# and a once-per-process sweep covers CLI-only installs.
42	TERMINAL_TEMP_MAX_AGE_HOURS = 72
43	_terminal_temp_prune_lock = threading.Lock()
44	_terminal_temp_pruned_once = False
45	# Background artifacts come in triplets (hermes_bg_<id>.log/.pid/.exit). A live
46	# server's .pid never changes mtime while its .log does, so age is judged per
47	# GROUP (newest mtime sharing a stem) to keep pid/exit files of live sessions.
48	_BG_GROUP_RE = re.compile(r"^(hermes_bg_[A-Za-z0-9_-]+)\.(log|pid|exit)$")
49
50
51	def _default_terminal_temp_dir() -> "Path | None":
52	    """Return HERMES_HOME/cache/terminal, or None if unresolvable."""
53	    try:
54	        from hermes_constants import get_hermes_home
55	        return get_hermes_home() / "cache" / "terminal"
56	    except Exception:
57	        return None
58
59
60	def cleanup_terminal_temp_cache(max_age_hours: int = TERMINAL_TEMP_MAX_AGE_HOURS) -> int:
61	    """Delete session temp artifacts older than *max_age_hours*; return count.
62	    Only the managed default dir is pruned — never a user-pointed ``terminal.temp_dir``."""
63	    root = _default_terminal_temp_dir()
64	    if root is None:
65	        return 0
66	    cutoff = time.time() - (max_age_hours * 3600)

... (gap) ...

76	            mtimes[f] = mt = f.stat().st_mtime
77	        except OSError:
78	            continue
79	        if m := _BG_GROUP_RE.match(f.name):
80	            group_newest[m.group(1)] = max(group_newest.get(m.group(1), 0.0), mt)
81
82	    removed = 0
83	    for f, mt in mtimes.items():
84	        m = _BG_GROUP_RE.match(f.name)
85	        if (group_newest[m.group(1)] if m else mt) >= cutoff:
86	            continue
87	        try:

... (gap) ...

100	            return
101	        _terminal_temp_pruned_once = True
102	    try:
103	        cleanup_terminal_temp_cache()
104	    except Exception as exc:
105	        logger.debug("Terminal temp prune failed: %s", exc)
106
107
108	# --- Windows / MSYS path translation ---
109	def _msys_to_windows_path(cwd: str) -> str:
110	    """``/c/Users/x`` / ``/cygdrive/c/..`` / ``/mnt/c/..`` -> native ``C:\\Users\\x`` so
111	    ``isdir``/``Popen(cwd=)`` find it. No-op off Windows, for empty input and for
112	    multi-segment POSIX paths like ``/home/x``; idempotent on native paths."""
113	    m = _IS_WINDOWS and cwd and re.match(r'^/(?:(?:cygdrive|mnt)/)?([a-zA-Z])(/.*)?$', cwd)
114	    if not m:
115	        return cwd
116	    tail = (m.group(2) or "").replace('/', '\\')
117	    return f"{m.group(1).upper()}:{tail or chr(92)}"  # chr(92) = backslash
118
119
120	def _resolve_local_initial_cwd(cwd: str) -> str:
121	    """Resolve the initial cwd to an absolute host path. A relative ``TERMINAL_CWD``
122	    naming the launch directory would otherwise make the wrapper ``cd`` *inside*
123	    the project; anchor it once so ``Popen(cwd=)`` and the in-shell ``cd`` agree."""
124	    expanded = os.path.expanduser(cwd) if cwd else os.getcwd()
125	    if _IS_WINDOWS:
126	        expanded = _msys_to_windows_path(expanded)
127	        # ntpath explicitly: with _IS_WINDOWS patched on a POSIX host,
128	        # os.path.isabs would reject ``C:\Users\x`` and mangle it below.
129	        if ntpath.isabs(expanded):

... (gap) ...

140	    return candidate
141
142
143	def _windows_to_msys_path(cwd: str) -> str:
144	    """Native ``C:\\Users\\x`` -> Git Bash ``/c/Users/x`` so ``builtin cd`` resolves
145	    it. No-op off Windows / for non-drive paths."""
146	    m = _IS_WINDOWS and cwd and re.match(r'^([a-zA-Z]):[\\/]*(.*)$', cwd)
147	    if not m:
148	        return cwd
149	    tail = (m.group(2) or "").replace('\\', '/').lstrip('/')
150	    return f"/{m.group(1).lower()}/{tail}"
151
152
153	def _bash_safe_path(path: str) -> str:
154	    """*path* safe to embed in a Git Bash script: ``C:\\Users\\x`` / ``C:/Users/x``
155	    become ``/c/Users/x`` (MSYS argument conversion mangles ``C:/`` forms) and
156	    leftover backslashes are normalized so bash does not eat ``\\U``. No-op off Windows."""
157	    return _windows_to_msys_path(path).replace("\\", "/") if _IS_WINDOWS and path else path
158
159
160	def _quote_bash_path(path: str) -> str:
161	    """Quote *path* for safe interpolation into a Git Bash script on Windows."""
162	    import shlex
163	    return shlex.quote(_bash_safe_path(path))
164
165
166	def _cwd_usable(path: str) -> bool:
167	    """True when *path* is a directory this process can actually chdir into
168	    (``isdir`` alone passes ``/root`` for a non-root user; ``Popen(cwd=)`` then dies)."""
169	    return os.path.isdir(path) and os.access(path, os.X_OK)
170
171
172	def _resolve_safe_cwd(cwd: str) -> str:
173	    """``cwd`` if enterable, else the nearest usable ancestor, else
174	    ``tempfile.gettempdir()``. MSYS paths are normalized first on Windows so a valid
175	    ``pwd -P`` result is not rejected. Lets ``_run_bash`` recover from a deleted or
176	    inaccessible cwd instead of ``Popen`` raising and wedging every later call.
177
178	    Used by ``_run_bash`` to recover when the configured cwd is gone — most commonly because a previous tool
179	    call deleted its own working directory (issue #17558) — or inaccessible to this user, e.g. ``/root``
180	    leaking from a root-launched CLI session into a non-root gateway's cron jobs (issue #65583). Without
181	    this guard, ``subprocess.Popen(..., cwd=...)`` raises ``FileNotFoundError``/``PermissionError`` before
182	    bash starts, wedging every subsequent terminal call until the gateway restarts.
183	    """
184	    cwd = _msys_to_windows_path(cwd)
185	    if cwd and _cwd_usable(cwd):
186	        return cwd
187	    if cwd and os.path.isdir(cwd):
188	        logger.warning(
189	            "Configured terminal cwd %r exists but is not accessible to "
190	            "this user (uid=%s) — falling back to the nearest usable "
191	            "directory. If this is a gateway/cron process, check for "
192	            "root-owned paths leaking into terminal.cwd / TERMINAL_CWD "
193	            "(#65583).",
194	            cwd, getattr(os, "getuid", lambda: "?")())
195	    parent = os.path.dirname(cwd) if cwd else ""
196	    while parent and not _cwd_usable(parent):
197	        next_parent = os.path.dirname(parent)
198	        if next_parent == parent:
199	            return tempfile.gettempdir()  # filesystem root itself is unusable
200	        parent = next_parent
201	    return parent or tempfile.gettempdir()
202
203
204	# --- Child-process environment construction ---
205	def _apply_profile_home(env: dict) -> None:
206	    """Bridge the context-local HERMES_HOME override, then the subprocess HOME contract."""
207	    from hermes_constants import apply_subprocess_home_env, get_hermes_home_override
208	    try:
209	        if value := get_hermes_home_override():
210	            env["HERMES_HOME"] = value
211	    except Exception:
212	        pass
213	    apply_subprocess_home_env(env)
214
215
216	def _inject_session_context_env(env: dict) -> None:
217	    """Bridge gateway session ContextVars (HERMES_SESSION_*) into a child env.
218	    Cross-session leak guard: the vars' last-writer-wins ``os.environ`` mirror may
219	    belong to another turn on a concurrent multi-session host, so once the session
220	    context is engaged ContextVars are authoritative — a bound value (incl. "") wins
221	    and an _UNSET var is STRIPPED, not inherited. An unengaged CLI keeps the mirror."""
222	    try:
223	        from gateway.session_context import _UNSET, _VAR_MAP, session_context_engaged
224	    except Exception:
225	        return
226	    _engaged = session_context_engaged()
227	    for var_name, var in _VAR_MAP.items():
228	        value = var.get()
229	        if value is not _UNSET:

... (gap) ...

249	            if not unwrap_force:
250	                continue
251	            key = key[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
252	            if not _is_hermes_internal_secret(key):
253	                out[key] = value
254	            continue
255	        if _is_hermes_internal_secret(key) or key in plugin_strip:
256	            continue
257	        first_party = _is_terminal_first_party_env(key)
258	        passthrough = is_env_passthrough(key)
259	        if key in _HERMES_PROVIDER_ENV_BLOCKLIST and not (passthrough or first_party):
260	            continue
261	        if passthrough and not first_party:
262	            value = resolve_passthrough_value(key, value)
263	        if value is not None:
264	            out[key] = value
265
266
267	def _finalize_child_env(env: dict) -> dict:
268	    """Guards shared by every spawn surface: profile-home propagation, session-context
269	    bridging, Hermes-owned PYTHONPATH + venv-marker strip, MSYS defaults, delegate_task
270	    Kanban scrub. Returns the (possibly new) dict."""
271	    _apply_profile_home(env)
272	    _inject_session_context_env(env)
273	    _strip_hermes_owned_pythonpath_and_runtime_markers(env)
274	    _apply_windows_msys_bash_env_defaults(env)
275	    try:  # strip dispatcher-owned Kanban env from delegate_task child subprocesses
276	        from agent.delegation_context import is_delegated_child_process_context, scrub_kanban_env
277	        if is_delegated_child_process_context():
278	            return scrub_kanban_env(env)
279	    except Exception:
280	        pass
281	    return env
282
283
284	def _scrubbed_env(parts, plugin_strip: frozenset, fix_path) -> dict:
285	    """Filter each ``(items, unwrap_force)`` in *parts* into one env, rewrite PATH via
286	    *fix_path* (always prepending the hermes install dir so bare ``hermes`` resolves
287	    for children of a systemd/cron-launched gateway), then apply the shared guards."""
288	    out: dict[str, str] = {}
289	    for items, unwrap_force in parts:
290	        _filter_secret_env(items, out, unwrap_force=unwrap_force, plugin_strip=plugin_strip)
291	    path_key = _path_env_key(out)
292	    # Keep bare ``hermes`` invocations available to child jobs even when the gateway was launched by a
293	    # service manager or cron without the console script's directory on PATH. The terminal environment
294	    # already applies this invariant; Cron scripts use this sanitizer directly (#92998).
295	    if path_key is not None:
296	        out[path_key] = _prepend_hermes_bin_dir(fix_path(out.get(path_key, "")))
297	    return _finalize_child_env(out)
298
299
300	def _sanitize_subprocess_env(base_env: dict | None, extra_env: dict | None = None) -> dict:
301	    """Filter Hermes-managed secrets from a subprocess environment (background/PTY
302	    spawn path, search workers, computer-use driver, user-script runners)."""
303	    return _scrubbed_env([(base_env or {}, False), (extra_env or {}, True)],
304	                         _plugin_terminal_env_strip_keys(), lambda p: p)
305
306
307	def hermes_subprocess_env(*, inherit_credentials: bool = False) -> dict[str, str]:
308	    """Sanitized env for the **non-terminal** spawn surface (browser, ACP/CLI executors,
309	    computer-use driver, TUI Node host). Tier 1 (``_ALWAYS_STRIP_KEYS``, plugin keys,
310	    force-prefixed hints, dynamic internal secrets) is always removed; Tier 2 (the
311	    provider/tool blocklist) unless ``inherit_credentials`` — pass that **only** for
312	    children that legitimately need LLM credentials (user-blessed claude/codex/gemini
313	    CLI, TUI Node host). Terminal/execute_code use ``_sanitize_subprocess_env``."""
314	    env = os.environ.copy()
315	    strip = _ALWAYS_STRIP_KEYS | _plugin_terminal_env_strip_keys()
316	    if not inherit_credentials:
317	        strip |= _HERMES_PROVIDER_ENV_BLOCKLIST
318	    for key in list(env):
319	        if (key in strip or key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX)
320	                or _is_hermes_internal_secret(key)):
321	            del env[key]
322	    env.setdefault("PYTHONUTF8", "1")  # Windows UTF-8 safety for spawned processes
323	    return _finalize_child_env(env)
324
325
326	def build_subprocess_env(
327	    base: "Mapping[str, str] | None" = None, *, inherit_profile_home: bool = True,
328	    scrub_secrets: bool = True, extra: "Mapping[str, str] | None" = None) -> dict[str, str]:
329	    """Single factory for child-process envs. ``base=None`` snapshots ``os.environ``.
330	    ``scrub_secrets=True`` -> :func:`_sanitize_subprocess_env` (profile home inherent,
331	    ``inherit_profile_home`` ignored). ``scrub_secrets=False`` keeps the base
332	    byte-for-byte (git credential flows, ``bws``/``op``); ``inherit_profile_home``
333	    bridges HERMES_HOME + HOME and ``extra`` is applied last so caller overrides win."""
334	    env: dict[str, str] = dict(base) if base is not None else os.environ.copy()
335	    if scrub_secrets:
336	        return _sanitize_subprocess_env(env, dict(extra) if extra else None)
337	    if inherit_profile_home:
338	        _apply_profile_home(env)
339	    if extra:
340	        env.update(extra)
341	    return env
342
343
344	# --- Shell discovery ---
345	def _windows_bash_candidates(custom: "str | None") -> list[str]:
346	    """Ordered bash.exe candidates on Windows: HERMES_GIT_BASH_PATH, our portable Git
347	    under %LOCALAPPDATA%\\hermes\\git (PortableGit ``bin`` and MinGit ``usr\\bin``),
348	    known Git-for-Windows dirs, then PATH last — ``shutil.which`` may return WSL's
349	    bash, which fails silently on Windows paths."""
350	    getenv = os.environ.get
351	    lad = getenv("LOCALAPPDATA", "")
352	    roots = [
353	        lad and os.path.join(lad, "hermes", "git", "bin"),
354	        lad and os.path.join(lad, "hermes", "git", "usr", "bin"),
355	        os.path.join(getenv("ProgramFiles", r"C:\Program Files"), "Git", "bin"),
356	        os.path.join(getenv("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "bin"),
357	        lad and os.path.join(lad, "Programs", "Git", "bin"),
358	    ]
359	    raw = [custom or "", *(os.path.join(r, "bash.exe") for r in roots if r)]
360	    candidates = list(dict.fromkeys(c for c in raw if c and os.path.isfile(c)))
361	    found = shutil.which("bash")
362	    if found and found not in candidates:
363	        candidates.append(found)
364	    return candidates
365
366
367	def _find_bash() -> str:
368	    """Find bash for command execution."""
369	    if not _IS_WINDOWS:
370	        return (shutil.which("bash")
371	                or next((p for p in ("/usr/bin/bash", "/bin/bash") if os.path.isfile(p)), None)
372	                or os.environ.get("SHELL") or "/bin/sh")
373	    custom = os.environ.get("HERMES_GIT_BASH_PATH")
374	    candidates = _windows_bash_candidates(custom)
375	    # First candidate that can actually start wins: a stale HERMES_GIT_BASH_PATH
376	    # pointing at a broken install must not beat a healthy portable Git.
377	    for candidate in candidates:
378	        if _bash_starts(candidate):
379	            if candidate != custom and custom and os.path.isfile(custom):
380	                logger.warning(
381	                    "HERMES_GIT_BASH_PATH=%s fails to start; using %s instead", custom, candidate)
382	            return candidate
383	    if candidates:
384	        probe_details = "\n".join(
385	            detail for c in candidates if (detail := _bash_probe_details_cache.get(c)))
386	        if _mandatory_aslr_enabled() is True or _looks_like_msys_spawn_failure(probe_details):
387	            raise RuntimeError(_git_bash_aslr_help(candidates[0], probe_details))
388	        # Unknown failure class: return the first path so the caller sees the
389	        # real bash error instead of a less useful "not found".
390	        return candidates[0]
391	    raise RuntimeError(
392	        "Git Bash not found. Hermes Agent requires Git for Windows on Windows.\n"
393	        "Install it from: https://git-scm.com/download/win\n"
394	        "Or set HERMES_GIT_BASH_PATH to your bash.exe location.")
395
396
397	_git_bash_bin_dirs_cache: "list[str] | None" = None
398
399
400	def _git_bash_bin_dirs() -> list[str]:
401	    """Git Bash's coreutils dirs in ``/etc/profile`` order (mingw first so coreutils
402	    beat System32 lookalikes); ``[]`` off Windows. A non-login ``bash -c`` (fallback
403	    when ``bash -l`` is broken) never sources ``/etc/profile``, so without these
404	    ``cat``/``mktemp``/``mv`` are missing and commands exit 127."""
405	    global _git_bash_bin_dirs_cache
406	    if _git_bash_bin_dirs_cache is None:
407	        _git_bash_bin_dirs_cache = _compute_git_bash_bin_dirs() if _IS_WINDOWS else []
408	    return _git_bash_bin_dirs_cache
409
410
411	def _compute_git_bash_bin_dirs() -> list[str]:
412	    try:
413	        bash = _find_bash()
414	    except Exception:
415	        return []
416	    parent = os.path.dirname(os.path.dirname(bash))  # bash in <root>\bin or <root>\usr\bin (MinGit)
417	    root = os.path.dirname(parent) if os.path.basename(parent).lower() == "usr" else parent
418	    subs = ("mingw64/bin", "mingw32/bin", "usr/local/bin", "usr/bin", "bin")
419	    dirs = (os.path.join(root, *sub.split("/")) for sub in subs)
420	    return list(dict.fromkeys(d for d in dirs if os.path.isdir(d)))
421
422
423	def _prepend_missing_path_entries(existing_path: str, dirs: list[str]) -> str:
424	    """Prepend *dirs* missing from *existing_path* (``os.pathsep``); an already-listed
425	    dir keeps its position; unchanged input when nothing is missing."""
426	    entries = [e for e in existing_path.split(os.pathsep) if e]
427	    missing = [d for d in dirs if d not in entries]
428	    return os.pathsep.join([*missing, *entries]) if missing else existing_path
429
430
431	def _prepend_git_bash_dirs(existing_path: str) -> str:
432	    """Prepend Git Bash's binary dirs if missing (no-op off Windows), so the
433	    non-login ``bash -c`` fallback can find coreutils."""
434	    return _prepend_missing_path_entries(existing_path, _git_bash_bin_dirs())
435
436
437	# POSIX-sh-family shells that understand spawn_local's ``[shell, "-lic", "set +m; …"]``
438	# invocation; fish, csh/tcsh, nushell, elvish, xonsh would error, so _find_shell
439	# falls back to bash for them.
440	# (#42203)
441	_SPAWN_COMPATIBLE_SHELLS = frozenset({"bash", "zsh", "sh", "dash", "ksh", "mksh"})
442
443
444	def _find_shell() -> str:
445	    """User's login shell for background spawning: ``$SHELL`` on POSIX when it is an
446	    executable sh-family shell, else ``_find_bash``. macOS's system bash 3.2 under
447	    ``-l`` with stdin ``/dev/null`` sources ``~/.bash_profile``, which often
448	    ``exec /bin/zsh -l`` and drops ``-c`` — the command silently never runs."""
449	    user_shell = "" if _IS_WINDOWS else os.environ.get("SHELL")
450	    if (user_shell and os.path.isfile(user_shell) and os.access(user_shell, os.X_OK)
451	            and Path(user_shell).name in _SPAWN_COMPATIBLE_SHELLS):
452	        return user_shell
453	    return _find_bash()
454
455
456	# --- PATH completion for the terminal subshell ---
457
458	# Standard PATH entries for environments with minimal PATH.
459	_SANE_PATH = ("/opt/homebrew/bin:/opt/homebrew/sbin:"
460	              "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
461
462	# Cached directory containing the ``hermes`` console-script.
463	# ``_SENTINEL`` distinguishes "not resolved yet" from a resolved ``None``.
464	_SENTINEL = object()
465	_HERMES_BIN_DIR: "str | None | object" = _SENTINEL
466
467
468	def _resolve_hermes_bin_dir() -> str | None:

... (gap) ...

484	            and os.path.isfile(argv0)):
485	        candidate = os.path.dirname(argv0)
486	    else:
487	        candidate = exe_dir if exe_dir and os.path.isfile(os.path.join(exe_dir, shim)) else None
488	    _HERMES_BIN_DIR = candidate if candidate and os.path.isdir(candidate) else None
489	    return _HERMES_BIN_DIR
490
491
492	def _prepend_hermes_bin_dir(existing_path: str) -> str:
493	    """Prepend the hermes install dir to ``existing_path`` if missing."""
494	    bin_dir = _resolve_hermes_bin_dir()
495	    return _prepend_missing_path_entries(existing_path, [bin_dir] if bin_dir else [])
496
497
498	def _managed_runtime_path_entries() -> list[str]:
499	    """Existing Hermes-managed runtime dirs: ``$HERMES_HOME/node`` (+``/bin``) and
500	    ``$HERMES_HOME/bin`` (managed ``uv``). Per call, not cached: home is
501	    profile-scoped and a managed tree can appear mid-process."""
502	    try:
503	        from hermes_constants import get_hermes_home, iter_hermes_node_dirs
504	        return [str(d) for d in (*iter_hermes_node_dirs(), get_hermes_home() / "bin") if d.is_dir()]
505	    except Exception:
506	        return []
507
508
509	def _append_missing_sane_path_entries(existing_path: str) -> str:
510	    """Normalised POSIX PATH with missing sane entries appended: empty entries
511	    dropped (shells read them as cwd), duplicates collapsed (first wins), then
512	    missing ``_SANE_PATH`` / managed-runtime dirs appended so user entries keep
513	    precedence. Windows is a no-op passthrough (native ``;`` PATH untouched)."""
514	    if _IS_WINDOWS:
515	        return existing_path
516	    # dict preserves first-occurrence order; empty entries dropped.
517	    ordered = dict.fromkeys(entry for entry in existing_path.split(":") if entry)
518	    ordered.update(dict.fromkeys([*_SANE_PATH.split(":"), *_managed_runtime_path_entries()]))
519	    return ":".join(ordered)
520
521

... (gap) ...

537	        env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
538
539
540	def _path_env_key(run_env: dict) -> str | None:
541	    """PATH env key to update without altering Windows casing (``Path`` vs ``PATH``);
542	    None when a Windows env has no PATH key at all."""
543	    return next((k for k in run_env if k.upper() == "PATH"), None) if _IS_WINDOWS else "PATH"
544
545
546	def _make_run_env(env: dict) -> dict:
547	    """Build a run environment with a sane PATH and provider-var stripping."""
548	    return _scrubbed_env([(dict(os.environ | env), True)], frozenset(),
549	                         lambda p: _prepend_git_bash_dirs(_append_missing_sane_path_entries(p)))
550
551
552	# --- Hermes venv / repo-root detection (module-level, computed once) ---
553	# Owned here; read lazily by tools.environments.local_pythonpath (tests patch here).
554	# The Electron app prepends the repo root to PYTHONPATH so the backend can ``import
555	# tools``; other subprocesses must not inherit it. Aliases: launchers may emit other
556	# spellings — the Windows gateway launcher renders Hermes-owned paths under the
557	# configured HERMES_HOME spelling (possibly a junction to another drive).
558	_hermes_repo_root: Path = Path(__file__).resolve().parents[2]
559	_hermes_repo_root_aliases: tuple[Path, ...] = _build_hermes_repo_root_aliases(
560	    _hermes_repo_root, Path(__file__).absolute().parents[2], get_process_hermes_home())
561	_in_venv: bool = (getattr(sys, "base_prefix", sys.prefix) != sys.prefix
562	                  or hasattr(sys, "real_prefix"))  # real_prefix: virtualenv<20
563	_hermes_site_packages: list[Path] | None = None  # lazily cached by local_pythonpath
564
565
566	# --- Login-shell init files ---
567	def _read_terminal_shell_init_config() -> tuple[list[str], bool]:
568	    """(shell_init_files, auto_source_bashrc) from config.yaml; defaults on any
569	    failure so terminal execution never breaks."""
570	    try:
571	        from hermes_cli.config import load_config
```


> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
