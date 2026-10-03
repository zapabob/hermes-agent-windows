**Exploration: tools/environments/local.py**

Found 74 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _msys_to_windows_path(calls), _default_terminal_temp_dir(calls), references(references), strip_launch_profile_env(calls), _find_bash(calls), _posix(calls), _windows_to_msys_path(calls), _cwd_usable(calls), _apply_profile_home(calls), _finalize_child_env(calls), _scrubbed_env(calls), _scrub_credentials(calls), _is_routed_home(calls), _prepend_missing_path_entries(calls), +108 more

```python
30	    _build_hermes_repo_root_aliases, _strip_hermes_owned_pythonpath_and_runtime_markers)
31
32
33	_IS_WINDOWS = platform.system() == "Windows"
34
35	logger = logging.getLogger(__name__)
36
37	# --- Terminal temp-cache pruning ---
38	# get_temp_dir() defaults to HERMES_HOME/cache/terminal (real storage, not tmpfs), so
39	# stale artifacts don't vanish on reboot: the gateway housekeeping loop prunes hourly
40	# and a once-per-process sweep covers CLI-only installs. Retention is idle-based like
41	# the scratch dir: an entry goes 24h after the last write anywhere inside it.
42	TERMINAL_TEMP_MAX_IDLE_HOURS = 24
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
60	def cleanup_terminal_temp_cache(max_age_hours: float = TERMINAL_TEMP_MAX_IDLE_HOURS) -> int:
61	    """Delete session temp artifacts idle for *max_age_hours* (no write anywhere in a
62	    directory's subtree; the kwarg name is the ``cleanup_*_cache`` signature the gateway
63	    housekeeping loop calls every entry with); return count.
64	    Only the managed default dir is pruned — never a user-pointed ``terminal.temp_dir``."""
65	    from hermes_constants_scratch import subtree_touched_since
66
67	    root = _default_terminal_temp_dir()
68	    if root is None:
69	        return 0
70	    cutoff = time.time() - (max_age_hours * 3600)
71	    try:
72	        entries = list(root.iterdir())
73	    except OSError:
74	        return 0
75
76	    mtimes: dict[Path, float] = {}
77	    group_newest: dict[str, float] = {}
78	    for f in entries:
79	        try:
80	            mtimes[f] = mt = f.stat().st_mtime
81	        except OSError:
82	            continue
83	        if m := _BG_GROUP_RE.match(f.name):
84	            group_newest[m.group(1)] = max(group_newest.get(m.group(1), 0.0), mt)
85
86	    removed = 0
87	    for f, mt in mtimes.items():
88	        m = _BG_GROUP_RE.match(f.name)
89	        if m:
90	            if group_newest[m.group(1)] >= cutoff:
91	                continue
92	        elif subtree_touched_since(f, cutoff):
93	            continue
94	        try:
95	            shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink()
96	            removed += 1
97	        except OSError:
98	            continue
99	    return removed
100
101
102	def _prune_terminal_temp_once() -> None:
103	    """Best-effort prune, at most once per process (CLI-only installs)."""
104	    global _terminal_temp_pruned_once
105	    with _terminal_temp_prune_lock:
106	        if _terminal_temp_pruned_once:
107	            return
108	        _terminal_temp_pruned_once = True
109	    try:
110	        cleanup_terminal_temp_cache()
111	    except Exception as exc:
112	        logger.debug("Terminal temp prune failed: %s", exc)
113
114
115	# --- Windows / MSYS path translation ---
116	def _msys_to_windows_path(cwd: str) -> str:
117	    """``/c/Users/x`` / ``/cygdrive/c/..`` / ``/mnt/c/..`` -> native ``C:\\Users\\x`` so
118	    ``isdir``/``Popen(cwd=)`` find it. No-op off Windows, for empty input and for
119	    multi-segment POSIX paths like ``/home/x``; idempotent on native paths."""
120	    m = _IS_WINDOWS and cwd and re.match(r'^/(?:(?:cygdrive|mnt)/)?([a-zA-Z])(/.*)?$', cwd)
121	    if not m:
122	        return cwd
123	    tail = (m.group(2) or "").replace('/', '\\')
124	    return f"{m.group(1).upper()}:{tail or chr(92)}"  # chr(92) = backslash
125
126
127	def _resolve_local_initial_cwd(cwd: str) -> str:
128	    """Resolve the initial cwd to an absolute host path. A relative ``TERMINAL_CWD``
129	    naming the launch directory would otherwise make the wrapper ``cd`` *inside*
130	    the project; anchor it once so ``Popen(cwd=)`` and the in-shell ``cd`` agree."""
131	    expanded = os.path.expanduser(cwd) if cwd else os.getcwd()
132	    if _IS_WINDOWS:
133	        expanded = _msys_to_windows_path(expanded)
134	        # ntpath explicitly: with _IS_WINDOWS patched on a POSIX host,
135	        # os.path.isabs would reject ``C:\Users\x`` and mangle it below.
136	        if ntpath.isabs(expanded):
137	            return expanded
138	    if os.path.isabs(expanded):
139	        return expanded
140	    candidate = os.path.abspath(expanded)
141	    current = os.getcwd()
142	    # Relative name matching the tail of the current dir: use the current dir.
143	    if not os.path.isdir(candidate):
144	        wanted, have = Path(expanded).parts, Path(current).parts
145	        if wanted and len(wanted) <= len(have) and have[-len(wanted):] == wanted:
146	            return current
147	    return candidate
148
149
150	def _windows_to_msys_path(cwd: str) -> str:
151	    """Native ``C:\\Users\\x`` -> Git Bash ``/c/Users/x`` so ``builtin cd`` resolves
152	    it. No-op off Windows / for non-drive paths."""
153	    m = _IS_WINDOWS and cwd and re.match(r'^([a-zA-Z]):[\\/]*(.*)$', cwd)
154	    if not m:
155	        return cwd
156	    tail = (m.group(2) or "").replace('\\', '/').lstrip('/')
157	    return f"/{m.group(1).lower()}/{tail}"
158
159
160	def _bash_safe_path(path: str) -> str:
161	    """*path* safe to embed in a Git Bash script: ``C:\\Users\\x`` / ``C:/Users/x``
162	    become ``/c/Users/x`` (MSYS argument conversion mangles ``C:/`` forms) and
163	    leftover backslashes are normalized so bash does not eat ``\\U``. No-op off Windows."""
164	    return _windows_to_msys_path(path).replace("\\", "/") if _IS_WINDOWS and path else path
165
166
167	def _quote_bash_path(path: str) -> str:
168	    """Quote *path* for safe interpolation into a Git Bash script on Windows."""
169	    import shlex
170	    return shlex.quote(_bash_safe_path(path))
171
172
173	def _cwd_usable(path: str) -> bool:
174	    """True when *path* is a directory this process can actually chdir into
175	    (``isdir`` alone passes ``/root`` for a non-root user; ``Popen(cwd=)`` then dies)."""
176	    return os.path.isdir(path) and os.access(path, os.X_OK)
177
178
179	def _resolve_safe_cwd(cwd: str) -> str:
180	    """``cwd`` if enterable, else the nearest usable ancestor, else
181	    ``tempfile.gettempdir()``. MSYS paths are normalized first on Windows so a valid
182	    ``pwd -P`` result is not rejected. Lets ``_run_bash`` recover from a deleted or
183	    inaccessible cwd instead of ``Popen`` raising and wedging every later call.
184
185	    Used by ``_run_bash`` to recover when the configured cwd is gone — most commonly because a previous tool
186	    call deleted its own working directory (issue #17558) — or inaccessible to this user, e.g. ``/root``
187	    leaking from a root-launched CLI session into a non-root gateway's cron jobs (issue #65583). Without
188	    this guard, ``subprocess.Popen(..., cwd=...)`` raises ``FileNotFoundError``/``PermissionError`` before
189	    bash starts, wedging every subsequent terminal call until the gateway restarts.
190	    """
191	    cwd = _msys_to_windows_path(cwd)
192	    if cwd and _cwd_usable(cwd):
193	        return cwd
194	    if cwd and os.path.isdir(cwd):
195	        logger.warning(
196	            "Configured terminal cwd %r exists but is not accessible to "
197	            "this user (uid=%s) — falling back to the nearest usable "
198	            "directory. If this is a gateway/cron process, check for "
199	            "root-owned paths leaking into terminal.cwd / TERMINAL_CWD "
200	            "(#65583).",
201	            cwd, getattr(os, "getuid", lambda: "?")())
202	    parent = os.path.dirname(cwd) if cwd else ""
203	    while parent and not _cwd_usable(parent):
204	        next_parent = os.path.dirname(parent)
205	        if next_parent == parent:
206	            return tempfile.gettempdir()  # filesystem root itself is unusable
207	        parent = next_parent
208	    return parent or tempfile.gettempdir()
209
210
211	# --- Child-process environment construction ---
212	def _apply_profile_home(env: dict) -> None:
213	    """Bridge the context-local HERMES_HOME override, then the subprocess HOME contract."""
214	    from hermes_constants import apply_subprocess_home_env, get_hermes_home_override
215	    try:
216	        if value := get_hermes_home_override():
217	            env["HERMES_HOME"] = value
218	    except Exception:
219	        pass
220	    apply_subprocess_home_env(env)
221
222
223	def _inject_session_context_env(env: dict) -> None:
224	    """Bridge gateway session ContextVars (HERMES_SESSION_*) into a child env.
225	    Cross-session leak guard: the vars' last-writer-wins ``os.environ`` mirror may
226	    belong to another turn on a concurrent multi-session host, so once the session
227	    context is engaged ContextVars are authoritative — a bound value (incl. "") wins
228	    and an _UNSET var is STRIPPED, not inherited. An unengaged CLI keeps the mirror."""
229	    try:
230	        from gateway.session_context import _UNSET, _VAR_MAP, session_context_engaged
231	    except Exception:
232	        return
233	    _engaged = session_context_engaged()
234	    for var_name, var in _VAR_MAP.items():
235	        value = var.get()
236	        if value is not _UNSET:

... (gap) ...

252	    except Exception:
253	        is_env_passthrough, resolve_passthrough_value = (lambda _: False), (lambda _n, fb: fb)
254	    plugin_strip_folded = frozenset(k.upper() for k in plugin_strip)
255	    registered = _registered_adapter_secret_env()
256	    for key, value in items.items():
257	        if key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX):
258	            if not unwrap_force:
259	                continue
260	            key = key[len(_HERMES_PROVIDER_ENV_FORCE_PREFIX):]
261	            if not _is_hermes_internal_secret(key):
262	                out[key] = value
263	            continue
264	        if _is_hermes_internal_secret(key) or key.upper() in plugin_strip_folded:
265	            continue
266	        first_party = _is_terminal_first_party_env(key)
267	        passthrough = is_env_passthrough(key)
268	        if _is_provider_env_blocklisted(key, registered) and not (passthrough or first_party):
269	            continue
270	        if passthrough and not first_party:
271	            value = resolve_passthrough_value(key, value)
272	        if value is not None:
273	            out[key] = value
274
275
276	def _finalize_child_env(env: dict) -> dict:
277	    """Guards shared by every spawn surface: profile-home propagation, session-context
278	    bridging, Hermes-owned PYTHONPATH + venv-marker strip, MSYS defaults, delegate_task
279	    Kanban scrub. Returns the (possibly new) dict."""
280	    _apply_profile_home(env)
281	    _inject_session_context_env(env)
282	    _strip_hermes_owned_pythonpath_and_runtime_markers(env)
283	    _apply_windows_msys_bash_env_defaults(env)
284	    from agent.delegation_context import delegated_child_subprocess_env
285	    return delegated_child_subprocess_env(env)
286
287
288	def _scrubbed_env(parts, plugin_strip: frozenset, fix_path) -> dict:
289	    """Filter each ``(items, unwrap_force)`` in *parts* into one env, rewrite PATH via
290	    *fix_path* (always prepending the hermes install dir so bare ``hermes`` resolves
291	    for children of a systemd/cron-launched gateway), then apply the shared guards."""
292	    out: dict[str, str] = {}
293	    for items, unwrap_force in parts:
294	        _filter_secret_env(items, out, unwrap_force=unwrap_force, plugin_strip=plugin_strip)
295	    # Declared names the bound profile scope holds but the process env never did (a routed
296	    # profile's own .env / sources) — the filter above can only see names already present.
297	    # Unguarded on purpose: a scope/config failure here must be loud, not silently drop the
298	    # declared secret again (#114209); _scrub_child_env calls it the same way.
299	    from tools.env_passthrough import scoped_passthrough_additions
300	    out.update((k, v) for k, v in scoped_passthrough_additions(out).items() if k not in plugin_strip)
301	    path_key = _path_env_key(out)
302	    # Keep bare ``hermes`` invocations available to child jobs even when the gateway was launched by a
303	    # service manager or cron without the console script's directory on PATH. The terminal environment
304	    # already applies this invariant; Cron scripts use this sanitizer directly (#92998).
305	    if path_key is not None:
306	        out[path_key] = _prepend_hermes_bin_dir(fix_path(out.get(path_key, "")))
307	    return _finalize_child_env(out)
308
309
310	def _sanitize_subprocess_env(base_env: dict | None, extra_env: dict | None = None) -> dict:
311	    """Filter Hermes-managed secrets from a subprocess environment (background/PTY
312	    spawn path, search workers, computer-use driver, user-script runners)."""
313	    return _scrubbed_env([(base_env or {}, False), (extra_env or {}, True)],
314	                         _plugin_terminal_env_strip_keys(), lambda p: p)
315
316
317	def hermes_subprocess_env(
318	    *, inherit_credentials: bool = False, base_env: dict[str, str] | None = None
319	) -> dict[str, str]:
320	    """Sanitize a non-terminal child's environment (no skill passthrough).
321
322	    Bot, GitHub and remote-compute secrets never pass through; provider/tool
323	    credentials pass only with ``inherit_credentials=True`` for children that
324	    need them. Callers needing one other secret should add only that key back.
325	    ``base_env`` lets an already curated environment use the same policy.
326	    Terminal and execute_code spawns use the skill-aware sanitizer instead.
327	    """
328	    env = dict(base_env) if base_env is not None else os.environ.copy()
329	    env = _scrub_credentials(env, inherit_credentials=inherit_credentials)
330	    env.setdefault("PYTHONUTF8", "1")  # Windows UTF-8 safety for spawned processes
331	    return _finalize_child_env(env)
332
333
334	def _scrub_credentials(env: dict, *, inherit_credentials: bool) -> dict:
335	    """Tier 1 (always) and, unless ``inherit_credentials``, Tier 2 provider/tool credentials, in place."""
336	    # Credential names fold to uppercase for membership: on Windows the env block
337	    # itself is case-insensitive, so a lowercase-stored ``gh_token`` IS GH_TOKEN.
338	    home_secrets = _home_adapter_secret_env()  # one manifest stamp per scrub
339	    strip_folded = _ALWAYS_STRIP_FOLDED | {k.upper() for k in _plugin_terminal_env_strip_keys()} | home_secrets
340	    registered = _registry_adapter_secret_env()  # home_secrets already strip above
341	    for key in list(env):
342	        if (key.upper() in strip_folded
343	                or (not inherit_credentials and _is_provider_env_blocklisted(key, registered))
344	                or key.startswith(_HERMES_PROVIDER_ENV_FORCE_PREFIX)
345	                or _is_hermes_internal_secret(key)):
346	            del env[key]
347	    return env
348

... (gap) ...

362	    Under multiplex semantics it then overlays the bound secret scope (the routed profile's own
363	    ``.env`` + source values, which never enter ``os.environ``) and re-applies the managed keys,
364	    all BEFORE the scrub, so those values pass the same scrub / passthrough rules as any other."""
365	    env: dict[str, str] = dict(base) if base is not None else os.environ.copy()
366	    if strip_launch_profile:
367	        strip_launch_profile_env(env)
368	        from agent.secret_scope import current_secret_scope, is_multiplex_active
369	        if is_multiplex_active():
370	            # Single-profile: the scope IS os.environ, so overlaying it would only re-sanitize
371	            # values the child already inherits byte-identical.
372	            env.update(current_secret_scope() or {})
373	            # Administrator-managed values keep their precedence over the routed profile's own .env,
374	            # exactly as they do in the launch process (``_apply_managed_env`` applies them last).
375	            restore_managed_env(env)
376	    if scrub_secrets:
377	        return _sanitize_subprocess_env(env, dict(extra) if extra else None)
378	    if inherit_profile_home:
379	        _apply_profile_home(env)
380	    if extra:
381	        env.update(extra)
382	    from agent.delegation_context import delegated_child_subprocess_env
383	    return delegated_child_subprocess_env(env)
384
385
386	def served_profile_child_env(

... (gap) ...

405	    from agent.secret_scope import (
406	        UnscopedSecretError, build_profile_secret_scope, current_secret_scope, is_multiplex_active)
407	    from hermes_constants import apply_scratch_tmp_env, get_hermes_home_override
408	    env = dict(base) if base is not None else hermes_subprocess_env(inherit_credentials=inherit_credentials)
409	    target = str(target_home or get_hermes_home_override() or "")
410	    if target:
411	        env["HERMES_HOME"] = target
412	        apply_scratch_tmp_env(env)  # TMPDIR follows the served home, like HOME does
413	        if _is_routed_home(target):
414	            strip_launch_profile_env(env, target)
415	            _scrub_credentials(env, inherit_credentials=False)
416	    if inherit_credentials:
417	        if target:
418	            secrets = build_profile_secret_scope(Path(target))
419	        else:
420	            secrets = current_secret_scope()
421	            if secrets is None and is_multiplex_active():
422	                raise UnscopedSecretError(
423	                    "", "served_profile_child_env(inherit_credentials=True) called with no target home and "
424	                    "no profile secret scope bound while multiplexing is on; the child would inherit the "
425	                    "launch profile's credentials. Bind the profile scope (or pass target_home) at the spawn site.")
426	        env.update((k, v) for k, v in (secrets or {}).items() if v is not None)
427	    return env
428
429
430	def host_gateway_child_env(
431	    base: "Mapping[str, str] | None" = None,
432	) -> dict[str, str]:
433	    """Child env for the host gateway: the default profile's secrets, never the launcher's.
434
435	    ``served_profile_child_env`` — not ``os.environ.copy()``. A profile-scoped parent
436	    (desktop, fleet restart, detached watcher) must not donate its dotenv to the
437	    multiplexer that owns the primary adapter map.
438	    """
439	    from hermes_constants import get_default_hermes_root
440	    return served_profile_child_env(
441	        base=base, target_home=get_default_hermes_root(), inherit_credentials=True,
442	    )
443
444
445	def _is_routed_home(target_home: "str | Path") -> bool:
446	    """True when ``target_home`` is not the process's own (launch) home.
447
448	    Same launch-home identity as ``agent.secret_scope.serves_routed_profile()``: under a host that
449	    mirrors the served profile into ``HERMES_HOME``, the live env var names the served home and the
450	    launch residue would never be stripped from that profile's child env."""
451	    from hermes_constants import get_routing_process_hermes_home
452	    try:
453	        return Path(target_home).resolve() != get_routing_process_hermes_home().resolve()
454	    except OSError:
455	        return True
456

... (gap) ...

467	    installing a HERMES_HOME override without that flag."""
468	    from agent.secret_scope import _is_global_env, load_env_file
469	    from hermes_constants import get_hermes_home_override, get_routing_process_hermes_home
470	    target = target_home or get_hermes_home_override()
471	    if not target or not _is_routed_home(target):
472	        return env
473	    launch_home = get_routing_process_hermes_home()
474	    from hermes_cli.config import TERMINAL_CONFIG_ENV_MAP
475	    # Folded strip: on Windows the env block is case-insensitive, so residue
476	    # stored under a variant casing is the same variable and must go too. The
477	    # selection folds the same way so a lowercase ``path`` in .env is still
478	    # recognized as a global name and left alone.
479	    # Current file AND every key any dotenv load put into os.environ this process lifetime: a key
480	    # removed or renamed in the launch .env after boot is still in os.environ with the old value, and
481	    # a re-parse of the file alone no longer names it (#107695 review). External secret sources
482	    # (vault, 1Password, ...) write their names into the same shared os.environ, and a name the
483	    # LAUNCH profile's source supplied is not the target profile's to see; the caller's scope
484	    # overlay puts back exactly the ones the target's own sources supply. The administrator-managed
485	    # .env is NOT residue: its values are policy for every profile (``_apply_managed_env`` applies
486	    # it last, with override, so it beats the user's own .env) — leave them in place.
487	    from hermes_cli.env_loader import launch_dotenv_keys, managed_dotenv_keys, source_supplied_names
488	    managed_names = {key.upper() for key in managed_dotenv_keys()}
489	    residue_names = {
490	        key.upper() for key in
491	        set(load_env_file(launch_home / ".env")) | set(launch_dotenv_keys())
492	        | set(TERMINAL_CONFIG_ENV_MAP.values()) | set(source_supplied_names())
493	        if not _is_global_env(key.upper()) or key.upper().startswith("TERMINAL_")} - managed_names
494	    for key in [k for k in env if k.upper() in residue_names]:
495	        del env[key]
496	    # Authorization gates are the one residue a name list cannot see: a unit-file ``Environment=``
497	    # or an operator export never appears in the launch ``.env``, the secret scrub ignores
498	    # non-credentials, and the target's own ``.env`` rarely defines the key to overwrite it (#113270).
499	    return strip_profile_gate_env(env)
500
501
502	def restore_managed_env(env: dict) -> dict:
503	    """Re-apply the administrator-managed ``.env`` values over *env* — call AFTER a routed profile's scope
504	    has been overlaid. ``_apply_managed_env`` gives those keys precedence over the user's own ``.env`` in
505	    the launch process; a routed child must see the same precedence, or the routed user's value for a
506	    managed key (``ORG_POLICY_FLAG=user-value``) silently wins over policy."""
507	    from hermes_cli.env_loader import managed_dotenv_keys
508	    for key in managed_dotenv_keys():
509	        if key in os.environ:
510	            env[key] = os.environ[key]
511	    return env
512
513
514	# --- Shell discovery ---
515	def _find_bash() -> str:
516	    """Resolve the shell Hermes runs commands with. Owned by pm (the store
517	    is the authority on bundled bash); this is a thin wrapper over
518	    pm.shell() for callers that need a bash binary."""
519	    import pm.shell
520
521	    bash = pm.shell.bash()
522	    if bash:
523	        return bash
524	    raise RuntimeError(
525	        "No shell found. Hermes needs bash (Git for Windows on Windows). "
526	        "Run `hermes pm install` or reinstall the bundle."
527	    )
528
529
530	_git_bash_bin_dirs_cache: "list[str] | None" = None
531
532
533	def _git_bash_bin_dirs() -> list[str]:
534	    """Git Bash's coreutils dirs in ``/etc/profile`` order (mingw first so coreutils
535	    beat System32 lookalikes); ``[]`` off Windows. A non-login ``bash -c`` (fallback
```


> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
