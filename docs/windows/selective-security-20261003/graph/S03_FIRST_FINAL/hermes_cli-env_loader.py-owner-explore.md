**Exploration: hermes_cli/env_loader.py**

Found 34 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`hermes_cli/env_loader.py`** — calls(calls), _load_dotenv_with_fallback(calls), _sanitize_env_file_if_needed(calls), _remember_loaded_env_keys(calls), _env_keys_defined_in_dotenv(calls), _load_secrets_config(calls), _sanitize_loaded_credentials(calls), _process_hermes_home(calls), _CREDENTIAL_SUFFIXES(variable), _WARNED_KEYS(variable), _WARNED_UTF32_PATHS(variable), _SECRET_SOURCES(variable), _SECRET_SOURCE_VALUES_BY_HOME(variable), _DOTENV_KEYS_BY_HOME(variable), _LAUNCH_PROFILE_HOME(variable), +37 more

```python
17	# only env vars whose values we sanitize on load — we must not silently
18	# alter arbitrary user env vars, but credentials are known to require
19	# pure ASCII (they become HTTP header values).
20	_CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_KEY")
21
22	# Names we've already warned about during this process, so repeated
23	# load_hermes_dotenv() calls (user env + project env, gateway hot-reload,
24	# tests) don't spam the same warning multiple times.
25	_WARNED_KEYS: set[str] = set()
26
27	# Paths we've already emitted a UTF-32 refuse-to-mangle warning for.
28	# load_hermes_dotenv can call _sanitize_env_file_if_needed multiple times
29	# for the same file (user env + project env + hot-reload); once per path
30	# is enough.
31	_WARNED_UTF32_PATHS: set[str] = set()
32
33	# Map of env-var name → source label ("bitwarden", etc.) for credentials
34	# that were injected by an external secret source during load_hermes_dotenv().
35	# Used by setup / `hermes model` flows to label detected credentials so
36	# users understand WHERE a key came from when their .env doesn't contain it
37	# directly (otherwise the "credentials detected ✓" line looks identical to
38	# the .env case and they don't know Bitwarden is wired up).
39	_SECRET_SOURCES: dict[str, str] = {}
40	# Applied values are immutable per-home snapshots.  ``os.environ`` is shared
41	# across profiles and may be overwritten by a later home's source apply.
42	_SECRET_SOURCE_VALUES_BY_HOME: dict[str, dict[str, str]] = {}
43	_DOTENV_KEYS_BY_HOME: dict[str, set[str]] = {}
44	_LAUNCH_PROFILE_HOME: Path | None = None
45
46
47	def remember_launch_profile_home(home: str | os.PathLike) -> None:
48	    """Bind process ownership after CLI profile selection, before routing."""
49	    global _LAUNCH_PROFILE_HOME
50	    with _SECRET_SOURCE_CACHE_LOCK:
51	        if _LAUNCH_PROFILE_HOME is None:
52	            _LAUNCH_PROFILE_HOME = Path(home).resolve()
53
54
55	def launch_profile_home() -> Path:
56	    """Return the launch identity even while cron changes process HERMES_HOME."""
57	    from hermes_constants import get_process_hermes_home
58	    return _LAUNCH_PROFILE_HOME or get_process_hermes_home()
59
60
61	def _remember_loaded_env_keys(home: Path, path: Path) -> None:
62	    key = os.path.normcase(str(home.resolve()))
63	    with _SECRET_SOURCE_CACHE_LOCK:
64	        _DOTENV_KEYS_BY_HOME.setdefault(key, set()).update(_env_keys_defined_in_dotenv(path))
65
66
67	def loaded_profile_env_keys(hermes_home: str | os.PathLike) -> frozenset[str]:
68	    """Names loaded for a home, retained across dotenv removal and reload."""
69	    key = os.path.normcase(str(Path(hermes_home).resolve()))
70	    with _SECRET_SOURCE_CACHE_LOCK:
71	        return frozenset(_DOTENV_KEYS_BY_HOME.get(key, ()))
72
73	# HERMES_HOME paths we've already pulled external secrets for during this
74	# process.  ``load_hermes_dotenv()`` is called at module-import time from
75	# several hot modules (cli.py, hermes_cli/main.py, run_agent.py,
76	# trajectory_compressor.py, gateway/run.py, ...), so without this guard the
77	# Bitwarden status line gets printed 3-5x per startup.  Bitwarden's own
78	# in-process cache prevents redundant network calls, but the print, the
79	# config re-parse, and the ASCII sanitization sweep still ran every time.
80	_APPLIED_HOMES: set[str] = set()
81	_SECRET_SOURCE_CACHE_LOCK = threading.RLock()
82
83
84	def _known_hermes_env_keys() -> set[str]:
85	    """Return the combined set of known Hermes env-var keys.
86
87	    Includes both ``OPTIONAL_ENV_VARS`` (setup-flow vars with metadata) and
88	    ``_EXTRA_ENV_KEYS`` (provider/platform keys managed outside the setup
89	    wizard).  Lazy-imported to avoid circular-dependency during early-bootstrap
90	    ``load_hermes_dotenv()`` calls.
91	    """
92	    from hermes_cli.config import _EXTRA_ENV_KEYS
93	    from hermes_cli.config_defaults import OPTIONAL_ENV_VARS
94
95	    return set(OPTIONAL_ENV_VARS.keys()) | set(_EXTRA_ENV_KEYS)
96
97
98	# Behavioral routing keys a parent Hermes process injects into child env and
99	# that silently redirect a profile onto the wrong provider path (ACP auth
100	# method, copilot-ACP endpoints). These — and ONLY these — are scrubbed from
101	# os.environ at startup when absent from the profile's .env. Credential keys
102	# (API keys/tokens) are excluded: shell exports are a legitimate,
103	# documented way to supply them, and read-time secret-scope checks
104	# (agent/secret_scope.py) own cross-profile credential isolation.
105	_PROFILE_MANAGED_ENV_KEYS: frozenset[str] = frozenset({
106	    "HERMES_ACP_AUTH_METHOD",
107	    "HERMES_ACP_AUTO_APPROVE",
108	    "HERMES_COPILOT_ACP_COMMAND",
109	    "HERMES_COPILOT_ACP_ARGS",
110	    "COPILOT_CLI_PATH",
111	    "COPILOT_ACP_BASE_URL",
112	})
113
114
115	def _env_keys_defined_in_dotenv(path: Path) -> set[str]:
116	    """Return KEY names assigned in a dotenv file (including empty ``KEY=``).
117
118	    Uses a fast line scanner rather than full dotenv parsing so it works
119	    during early bootstrap without importing python-dotenv.  Ignores comment
120	    and blank lines.  Non-ASCII encoding errors fall back to ``latin-1``,
121	    matching ``_load_dotenv_with_fallback``.
122	    """
123	    keys: set[str] = set()
124	    try:
125	        text = path.read_text(encoding="utf-8", errors="replace")
126	    except Exception:
127	        try:
128	            text = path.read_text(encoding="latin-1", errors="replace")
129	        except Exception:
130	            return keys
131	    for line in text.splitlines():
132	        line = line.strip()
133	        if not line or line.startswith("#") or "=" not in line:
134	            continue
135	        if line.startswith("export "):
136	            line = line[7:]
137	        key = line.split("=", 1)[0].strip()
138	        if key:
139	            keys.add(key)
140	    return keys
141
142
143	def _clear_known_keys_missing_from_dotenv(path: Path) -> None:

... (gap) ...

166	    Does **not** run when the ``.env`` file does not exist (bare-profile
167	    case, which follows ``#66930`` / ``#67027`` semantics).
168	    """
169	    if not path.exists():
170	        return
171	    defined = _env_keys_defined_in_dotenv(path)
172	    for key in _PROFILE_MANAGED_ENV_KEYS:
173	        if key not in defined and key in os.environ:
174	            del os.environ[key]
175
176
177	def get_secret_source(env_var: str) -> str | None:
178	    """Return the label of the secret source that supplied ``env_var``, if any.
179
180	    Returns ``"bitwarden"`` for keys pulled from Bitwarden Secrets Manager
181	    during the current process's ``load_hermes_dotenv()`` call.  Returns
182	    ``None`` for keys that came from ``.env``, the shell environment, or
183	    aren't tracked.  The returned label is metadata only: credential-pool
184	    persistence may store it to explain the origin of a borrowed secret, but
185	    must never treat it as authorization to persist the raw value.
186	    """
187	    return _SECRET_SOURCES.get(env_var)
188
189
190	def get_secret_source_values(
191	    hermes_home: str | os.PathLike,
192	) -> dict[str, str]:
193	    """Return the external-secret value snapshot for ``hermes_home``."""
194	    home_key = str(Path(hermes_home).resolve())
195	    return dict(_SECRET_SOURCE_VALUES_BY_HOME.get(home_key, {}))
196
197
198	def hydrate_profile_secret_sources(
199	    hermes_home: str | os.PathLike,
200	) -> dict[str, str]:
201	    """Resolve one profile's configured sources without mutating ``os.environ``.
202
203	    Multiplex gateways can route a first turn to a secondary profile that has
204	    never run the process-global dotenv startup path.  Resolve that profile's
205	    sources against a private mapping seeded from its own ``.env`` and record
206	    the usual per-home snapshot for ``build_profile_secret_scope()``.
207
208	    Fail-open and once-per-home semantics intentionally mirror
209	    ``_apply_external_secret_sources``.  The returned mapping contains only
210	    values actually contributed by external sources, never the profile's
211	    plaintext ``.env`` entries.
212	    """
213	    with _SECRET_SOURCE_CACHE_LOCK:
214	        return _hydrate_profile_secret_sources(Path(hermes_home))
215
216
217	def _hydrate_profile_secret_sources(home: Path) -> dict[str, str]:
218	    """Locked implementation for :func:`hydrate_profile_secret_sources`."""
219	    home_key = str(home.resolve())
220	    if home_key in _APPLIED_HOMES:
221	        return get_secret_source_values(home)
222
223	    try:
224	        cfg = _load_secrets_config(home)
225	    except Exception:  # noqa: BLE001 — external sources must not block routing
226	        return {}
227	    if not cfg:
228	        return {}
229
230	    try:
231	        from agent.secret_scope import _is_global_env, load_env_file
232	        from agent.secret_sources.registry import apply_all
233
234	        local_env = {
235	            name: value
236	            for name, value in os.environ.items()
237	            if _is_global_env(name)
238	        }
239	        local_env.update(load_env_file(home / ".env"))
240	        # Mirror load_hermes_dotenv()'s .op.env bootstrap: the 1Password
241	        # service-account token lives in <home>/.op.env (gitignored), not
242	        # .env. Without seeding it here a cold profile configured for the
243	        # supported .op.env flow fails 1Password hydration (sweeper review
244	        # on #74549). .env values win — never override an existing key.
245	        op_env = home / ".op.env"
246	        if op_env.exists():
247	            for _name, _value in load_env_file(op_env).items():
248	                local_env.setdefault(_name, _value)
249	        local_env["HERMES_HOME"] = str(home)
250	        report = apply_all(cfg, home, environ=local_env)
251	    except Exception:  # noqa: BLE001 — preserve fail-open startup behavior
252	        return {}
253
254	    if not report.sources:
255	        return {}
256
257	    _APPLIED_HOMES.add(home_key)
258	    values: dict[str, str] = {}
259	    for name, applied in report.provenance.items():
260	        value = local_env.get(name)
261	        if value is None:
262	            continue
263	        _SECRET_SOURCES[name] = applied.source
264	        values[name] = value
265	    if values:
266	        _SECRET_SOURCE_VALUES_BY_HOME[home_key] = values
267	    return dict(values)
268
269
270	def reset_secret_source_cache() -> None:
271	    """Forget which HERMES_HOME paths have already had external secrets applied.
272
273	    The first call to ``_apply_external_secret_sources(home_path)`` in a
274	    process pulls from Bitwarden (or other configured backend), records the
275	    applied keys in ``_SECRET_SOURCES``, and remembers ``home_path`` so
276	    subsequent calls in the same process are no-ops.  Call this to force the
277	    next call to re-pull — useful for tests, and for long-running processes
278	    that want to refresh after a config change.
279	    """
280	    _APPLIED_HOMES.clear()
281	    _SECRET_SOURCES.clear()
282	    _SECRET_SOURCE_VALUES_BY_HOME.clear()
283
284
285	def format_secret_source_suffix(env_var: str) -> str:
286	    """Return a human-readable suffix like ``" (from Bitwarden)"`` or ``""``.
287
288	    Use this when printing a detected credential so the user can see where
289	    it came from.  Empty string when the credential came from ``.env`` or
290	    the shell — those are the implicit / "default" cases users already
291	    understand.
292	    """
293	    source = get_secret_source(env_var)
294	    if not source:
295	        return ""
296	    if source == "bitwarden":
297	        return " (from Bitwarden)"
298	    # Ask the registry for the source's human label (e.g. "1Password").
299	    # Fall back to the raw source name for labels the registry doesn't
300	    # know (stale provenance from an uninstalled plugin, tests).
301	    try:
302	        from agent.secret_sources.registry import get_source
303
304	        registered = get_source(source)
305	        if registered is not None and registered.label:
306	            return f" (from {registered.label})"
307	    except Exception:  # noqa: BLE001 — label lookup must never raise
308	        pass
309	    return f" (from {source})"
310
311
312	def _format_offending_chars(value: str, limit: int = 3) -> str:
313	    """Return a compact 'U+XXXX ('c'), ...' summary of non-ASCII codepoints."""
314	    seen: list[str] = []
315	    for ch in value:
316	        if ord(ch) > 127:
317	            label = f"U+{ord(ch):04X}"
318	            if ch.isprintable():
319	                label += f" ({ch!r})"
320	            if label not in seen:
321	                seen.append(label)
322	            if len(seen) >= limit:
323	                break
324	    return ", ".join(seen)
325
326
327	def _sanitize_loaded_credentials() -> None:
328	    """Strip non-ASCII characters from credential env vars in os.environ.
329
330	    Called after dotenv loads so the rest of the codebase never sees
331	    non-ASCII API keys.  Only touches env vars whose names end with
332	    known credential suffixes (``_API_KEY``, ``_TOKEN``, etc.).
333
334	    Emits a one-line warning to stderr when characters are stripped.
335	    Silent stripping would mask copy-paste corruption (Unicode lookalike
336	    glyphs from PDFs / rich-text editors, ZWSP from web pages) as opaque
337	    provider-side "invalid API key" errors (see #6843).
338	    """
339	    for key, value in list(os.environ.items()):
340	        if not any(key.endswith(suffix) for suffix in _CREDENTIAL_SUFFIXES):
341	            continue
342	        try:
343	            value.encode("ascii")
344	            continue
345	        except UnicodeEncodeError:
346	            pass
347	        cleaned = value.encode("ascii", errors="ignore").decode("ascii")
348	        os.environ[key] = cleaned
349	        if key in _WARNED_KEYS:
350	            continue
351	        _WARNED_KEYS.add(key)
352	        stripped = len(value) - len(cleaned)
353	        detail = _format_offending_chars(value) or "non-printable"
354	        print(
355	            f"  Warning: {key} contained {stripped} non-ASCII character"
356	            f"{'s' if stripped != 1 else ''} ({detail}) — stripped so the "

... (gap) ...

368	        )
369
370
371	def _load_dotenv_with_fallback(path: Path, *, override: bool) -> None:
372	    try:
373	        # utf-8-sig strips a leading UTF-8 BOM if present (PowerShell 5.1
374	        # Set-Content -Encoding UTF8 / Notepad) and is a no-op for BOM-less
375	        # UTF-8. Plain "utf-8" would keep U+FEFF on the first key name and
376	        # silently drop it from os.environ under its canonical name.
377	        load_dotenv(dotenv_path=path, override=override, encoding="utf-8-sig")
378	    except UnicodeDecodeError:
379	        # utf-8-sig can't strip a BOM once we fall back to latin-1 decode.
380	        raw = path.read_bytes()
381	        if raw.startswith(codecs.BOM_UTF8):
382	            raw = raw[len(codecs.BOM_UTF8) :]
383	        load_dotenv(stream=io.StringIO(raw.decode("latin-1")), override=override)
384	    # Strip non-ASCII characters from credential env vars that were just
385	    # loaded.  API keys must be pure ASCII since they're sent as HTTP
386	    # header values (httpx encodes headers as ASCII).  Non-ASCII chars
387	    # typically come from copy-pasting keys from PDFs or rich-text editors
388	    # that substitute Unicode lookalike glyphs (e.g. ʋ U+028B for v).
389	    _sanitize_loaded_credentials()
390
391
392	def _sanitize_env_file_if_needed(path: Path) -> None:

... (gap) ...

405	    ``hermes_cli.config._sanitize_env_lines`` normalizes line endings while
406	    treating content after the first ``=`` as opaque for boundary discovery.
407	    """
408	    if not path.exists():
409	        return
410	    try:
411	        from hermes_cli.config import _sanitize_env_lines

... (gap) ...

430	            _WARNED_UTF32_PATHS.add(path_key)
431	            import logging
432
433	            logging.getLogger(__name__).warning(
434	                "Skipping .env sanitize for %s: UTF-32 BOM detected; "
435	                "leaving file untouched to avoid corruption",
436	                path,

... (gap) ...

473	        # reach python-dotenv (which passes them to os.environ and
474	        # crashes with ValueError). Also intentionally repairs
475	        # BOM-less UTF-16 (NUL-padded ASCII) into clean UTF-8.
476	        stripped = [line.replace("\x00", "") for line in original]
477	        sanitized = _sanitize_env_lines(stripped)
478	        if sanitized != original or force_utf8_rewrite:
479	            import tempfile
480	            fd, tmp = tempfile.mkstemp(
481	                dir=str(path.parent), suffix=".tmp", prefix=".env_"
482	            )
483	            try:
484	                with os.fdopen(fd, "w", encoding="utf-8") as f:
485	                    f.writelines(sanitized)
486	                    f.flush()
487	                    os.fsync(f.fileno())
488	                atomic_replace(tmp, path)
489	            except BaseException:
490	                try:
491	                    os.unlink(tmp)

... (gap) ...

515	    """
516	    loaded: list[Path] = []
517
518	    home_path = Path(hermes_home or os.getenv("HERMES_HOME", Path.home() / ".hermes"))
519	    remember_launch_profile_home(home_path)
520	    user_env = home_path / ".env"
521	    project_env_path = Path(project_env) if project_env else None
522
523	    # Normalize safe formatting and remove invalid NUL bytes before parsing.
524	    if user_env.exists():
525	        _sanitize_env_file_if_needed(user_env)
526	    if project_env_path and project_env_path.exists():
527	        _sanitize_env_file_if_needed(project_env_path)
528
529	    if user_env.exists():
530	        _remember_loaded_env_keys(home_path, user_env)
531	        _load_dotenv_with_fallback(user_env, override=True)
532	        loaded.append(user_env)
533	        # Mirror reload_env() known-key cleanup so inherited Hermes keys
534	        # absent from this profile's .env do not leak into the runtime.
535	        _clear_known_keys_missing_from_dotenv(user_env)
536
537	    # Load .op.env AFTER .env so that .env values win, but the bootstrap
538	    # token (OP_SERVICE_ACCOUNT_TOKEN) becomes available for
539	    # apply_onepassword_secrets() even in cron / subprocess environments
540	    # that inherit no shell state (no systemd EnvironmentFile, no op run).
541	    # .op.env is gitignored — the service-account token never enters the
542	    # committed .env file.
543	    # Users on systemd can alternatively use:
544	    #   EnvironmentFile=-/path/to/.hermes/.op.env
545	    # in their gateway unit, which takes precedence (override=False below
546	    # ensures .op.env never clobbers a token already in the environment).
547	    op_env = home_path / ".op.env"
548	    if op_env.exists() and not os.environ.get("OP_SERVICE_ACCOUNT_TOKEN"):
549	        _remember_loaded_env_keys(home_path, op_env)
550	        _load_dotenv_with_fallback(op_env, override=False)
551
552	    if project_env_path and project_env_path.exists():
553	        _remember_loaded_env_keys(home_path, project_env_path)
554	        _load_dotenv_with_fallback(project_env_path, override=not loaded)
555	        loaded.append(project_env_path)
556
557	    # External secret sources are skipped in two updater situations:

... (gap) ...

567	    # resolution is unnecessary for the updater.
568	    from hermes_cli import _early_recovery
569
570	    if load_external_secrets and not _early_recovery._should_skip_external_secret_sources():
571	        _apply_external_secret_sources(home_path)
572	    _apply_managed_env()
573
574	    # config.yaml is the documented source of truth for terminal.* settings,
575	    # but the dotenv loads above run with override=True — so a stale
576	    # TERMINAL_ENV=docker left in ~/.hermes/.env (e.g. written by an older
577	    # `hermes setup` before the user switched terminal.backend in config.yaml)
578	    # silently wins again on every reload. Startup launchers bridge
579	    # config→env once, but long-lived processes (gateway per-turn reload,
580	    # cron standalone runs) call load_hermes_dotenv() repeatedly and used to
581	    # flip the effective backend back to the stale .env value mid-session
582	    # (#29186, #67323). Re-apply config.yaml's explicit terminal keys last so
583	    # the documented config path always wins. Runs after _apply_managed_env()
584	    # so the merged config (which already carries the managed overlay) is
585	    # what lands in the env.
586	    _reapply_terminal_config_bridge(home_path)
587
588	    return loaded
589
590
591	def _reapply_terminal_config_bridge(home_path: Path) -> None:
592	    """Re-assert config.yaml's explicit ``terminal.*`` keys over reloaded .env.
593
594	    Delegates to ``hermes_cli.config.apply_terminal_config_to_env`` — the
595	    single shared bridge (same one terminal_tool's fallback and the TUI/
596	    dashboard launchers use) — so key coverage, explicit-keys-only override
597	    semantics, cwd placeholder handling, and the managed-scope overlay can't
598	    drift from the other bridge sites. Only keys the user actually wrote in
599	    config.yaml's ``terminal`` section override env values; a config.yaml
600	    without a terminal section leaves .env/shell selections untouched.
601
602	    Scoped to the process HERMES_HOME: the shared bridge reads the
603	    process-global config, so re-applying it for a *different* profile's
604	    ``load_hermes_dotenv(hermes_home=...)`` call would bridge the wrong
605	    profile's config. Fail-open — a config problem must never break dotenv
606	    loading (the historical env-driven behavior still applies).
607	    """
608	    try:
609	        if Path(home_path).resolve() != _process_hermes_home().resolve():
610	            return
611	        from hermes_cli.config import apply_terminal_config_to_env
612
613	        apply_terminal_config_to_env(env=None)
614	    except Exception:  # noqa: BLE001 — early bootstrap / malformed config
615	        pass
616
617
618	def _apply_managed_env() -> None:

... (gap) ...

635	    try:
636	        from hermes_cli import managed_scope
637
638	        managed_dir = managed_scope.get_managed_dir()
639	    except Exception:  # noqa: BLE001 — managed scope must never block startup
640	        return
641	    if managed_dir is None:
642	        return
643	    managed_env = managed_dir / ".env"
644	    if not managed_env.exists():
645	        return
646	    _sanitize_env_file_if_needed(managed_env)
647	    _load_dotenv_with_fallback(managed_env, override=True)
648
649
650	def _apply_external_secret_sources(home_path: Path) -> None:

... (gap) ...

670	    ``reset_secret_source_cache()`` if you need to force a re-pull
671	    (tests, long-running processes after a config change).
672	    """
673	    home_key = str(Path(home_path).resolve())
674	    if home_key in _APPLIED_HOMES:
675	        return
676
677	    try:
678	        cfg = _load_secrets_config(home_path)
679	    except Exception:  # noqa: BLE001 — config errors must not block startup
680	        # Deliberately NOT marked applied: a malformed config.yaml would
681	        # otherwise permanently disable secret loading for this process

... (gap) ...

711	        return
712
713	    try:
714	        report = apply_all(cfg, home_path)
715	    except Exception:  # noqa: BLE001 — belt-and-braces; apply_all shouldn't raise
716	        return
717
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.
