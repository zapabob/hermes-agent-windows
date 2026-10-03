**Exploration: tools/transcription_tools.py**

Found 134 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/transcription_tools.py`** — calls(calls), _load_stt_config(calls), _find_binary(calls), _normalize_local_model(calls), _validate_audio_file(calls), _get_stt_section(calls), _resolve_openai_audio_client_config(calls), _find_ffmpeg_binary(calls), _run_ffmpeg_stt_encode(calls), _probe_audio_duration(calls), _transcribe_local(calls), _normalize_local_command_model(calls), _transcribe_local_command(calls), _is_local_or_private_url(calls), logger(variable), +96 more

```python
51	    resolve_openai_audio_api_key,
52	)
53
54	logger = logging.getLogger(__name__)
55
56	def get_env_value(name, default=None):
57	    """Read env values through the live config module.
58
59	    Tests may monkeypatch and later restore ``hermes_cli.config.get_env_value``
60	    before this module is imported. Resolve the helper at call time so STT does
61	    not keep a stale imported function for the rest of the test process.
62	    """
63	    try:
64	        from hermes_cli.config import get_env_value as _get_env_value
65	    except ImportError:
66	        return os.getenv(name, default)
67	    value = _get_env_value(name)
68	    return default if value is None else value
69
70
71	def _resolve_provider_key(env_var: str, provider_id: str) -> str:
72	    """Resolve an STT provider API key via the shared voice-key resolver.
73
74	    Delegates to ``tools.tool_backend_helpers.resolve_provider_secret`` —
75	    the single owner of STT/TTS key resolution (config > env/.env > the
76	    credential pool populated by ``hermes auth add <provider_id>``).
77	    Resolved at call time so tests that reload the helpers module see the
78	    live function.
79	    """
80	    try:
81	        from tools.tool_backend_helpers import resolve_provider_secret
82	    except ImportError:  # pragma: no cover — helpers are in-repo
83	        return str(get_env_value(env_var) or "").strip()
84	    return resolve_provider_secret(env_var, provider_id, env_getter=get_env_value)
85
86	# ---------------------------------------------------------------------------
87	# Optional imports — graceful degradation
88	# ---------------------------------------------------------------------------
89
90	import importlib.util as _ilu
91
92
93	def _safe_find_spec(module_name: str) -> bool:
94	    try:
95	        return _ilu.find_spec(module_name) is not None
96	    except (ImportError, ValueError):
97	        return module_name in globals() or module_name in os.sys.modules
98
99
100	_HAS_FASTER_WHISPER = _safe_find_spec("faster_whisper")
101	_HAS_OPENAI = _safe_find_spec("openai")
102	_HAS_MISTRAL = _safe_find_spec("mistralai")
103	_HAS_PILK = _safe_find_spec("pilk")
104
105	# ---------------------------------------------------------------------------
106	# Constants
107	# ---------------------------------------------------------------------------
108
109	DEFAULT_PROVIDER = "local"
110	DEFAULT_LOCAL_MODEL = "base"
111	DEFAULT_LOCAL_STT_LANGUAGE = "en"
112	DEFAULT_STT_MODEL = os.getenv("STT_OPENAI_MODEL", "whisper-1")
113	DEFAULT_GROQ_STT_MODEL = os.getenv("STT_GROQ_MODEL", "whisper-large-v3-turbo")
114	DEFAULT_MISTRAL_STT_MODEL = os.getenv("STT_MISTRAL_MODEL", "voxtral-mini-latest")
115	DEFAULT_ELEVENLABS_STT_MODEL = os.getenv("STT_ELEVENLABS_MODEL", "scribe_v2")
116	LOCAL_STT_COMMAND_ENV = "HERMES_LOCAL_STT_COMMAND"
117	LOCAL_STT_LANGUAGE_ENV = "HERMES_LOCAL_STT_LANGUAGE"
118	COMMON_LOCAL_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
119
120	GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
121	OPENAI_BASE_URL = os.getenv("STT_OPENAI_BASE_URL", "https://api.openai.com/v1")
122	XAI_STT_BASE_URL = os.getenv("XAI_STT_BASE_URL", "https://api.x.ai/v1")
123	ELEVENLABS_STT_BASE_URL = os.getenv("ELEVENLABS_STT_BASE_URL", "https://api.elevenlabs.io/v1")
124	# DeepInfra STT base URL now resolved via hermes_cli.models.deepinfra_base_url (shared).
125
126	SUPPORTED_FORMATS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg", ".oga", ".opus", ".aac", ".flac", ".caf"}
127	LOCAL_NATIVE_AUDIO_FORMATS = {".wav", ".aiff", ".aif"}
128	MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
129
130	# Known model sets for auto-correction
131	OPENAI_MODELS = {"whisper-1", "gpt-4o-mini-transcribe", "gpt-4o-transcribe", "gpt-transcribe"}
132	GROQ_MODELS = {"whisper-large-v3", "whisper-large-v3-turbo", "distil-whisper-large-v3-en"}
133
134	# Singleton for the local model — loaded once, reused across calls
135	_local_model: Optional[object] = None
136	_local_model_name: Optional[str] = None
137	# Guards the check-then-load of the module-global model cache above.
138	# Without it, two concurrent voice messages can both see `_local_model is
139	# None` and download/load the whisper model twice (#24767).
140	_local_model_lock = threading.Lock()
141
142	# --- Idle unload ---------------------------------------------------------------
143	# The model singleton above is loaded once and never released — hundreds of MB
144	# of RAM/VRAM sit idle between voice messages. On long-running gateway
145	# processes (especially with local LLMs competing for the same GPU) this is
146	# wasteful. A single long-lived daemon thread checks _last_transcription_time
147	# and unloads the model after a configurable idle period, then exits. The next
148	# voice message reloads the model and restarts the watcher transparently.
149	_last_transcription_time: float = 0.0
150	_idle_unload_thread: Optional[threading.Thread] = None
151	_idle_unload_stop = threading.Event()
152	# Serializes watcher start checks so two concurrent transcriptions can't
153	# both observe "no watcher alive" and spawn duplicates.
154	_idle_unload_mgmt_lock = threading.Lock()
155
156	_IDLE_UNLOAD_CHECK_INTERVAL = 30  # seconds between idle checks
157
158	# ---------------------------------------------------------------------------
159	# Config helpers
160	# ---------------------------------------------------------------------------
161
162
163
164	def _load_stt_config() -> dict:
165	    """Load the ``stt`` section from user config, falling back to defaults."""
166	    try:
167	        from hermes_cli.config import load_config
168	        return load_config().get("stt") or {}
169	    except Exception:
170	        return {}
171
172
173	def is_stt_enabled(stt_config: Optional[dict] = None) -> bool:
174	    """Return whether STT is enabled in config."""
175	    if stt_config is None:
176	        stt_config = _load_stt_config()
177	    enabled = stt_config.get("enabled", True)
178	    return is_truthy_value(enabled, default=True)
179
180
181	def _resolve_stt_language(
182	    provider_key: str,
183	    stt_config: Optional[Dict[str, Any]] = None,
184	    *,
185	    extra_keys: tuple = (),
186	) -> Optional[str]:
187	    """Resolve the language hint for an STT provider (class-level, all providers).
188
189	    Resolution order (first non-empty wins):
190	      1. ``stt.<provider>.language`` (plus any *extra_keys* aliases, e.g.
191	         ElevenLabs' historical ``language_code``)
192	      2. ``stt.language``           — global default for every provider
193	      3. ``HERMES_LOCAL_STT_LANGUAGE`` env var (legacy escape hatch)
194	      4. ``None``                   — let the provider auto-detect
195
196	    Returns a stripped ISO-639-1-ish code or None. Never returns "".
197	    """
198	    if stt_config is None:
199	        stt_config = _load_stt_config()
200	    provider_cfg = _get_stt_section(stt_config, provider_key)
201	    candidates = [provider_cfg.get("language")]
202	    for key in extra_keys:
203	        candidates.append(provider_cfg.get(key))
204	    if isinstance(stt_config, dict):
205	        candidates.append(stt_config.get("language"))
206	    candidates.append(os.getenv(LOCAL_STT_LANGUAGE_ENV))
207	    for candidate in candidates:
208	        if isinstance(candidate, str) and candidate.strip():
209	            return candidate.strip()
210	    return None
211
212
213	def _has_openai_audio_backend() -> bool:
214	    """Return True when OpenAI audio can use config credentials, env credentials, or the managed gateway."""
215	    try:
216	        _resolve_openai_audio_client_config()
217	        return True
218	    except ValueError:
219	        return False
220
221
222	def _find_binary(binary_name: str) -> Optional[str]:
223	    """Find a local binary, checking common Homebrew/local prefixes as well as PATH."""
224	    for directory in COMMON_LOCAL_BIN_DIRS:
225	        candidate = Path(directory) / binary_name
226	        if candidate.exists() and os.access(candidate, os.X_OK):
227	            return str(candidate)
228	    return shutil.which(binary_name)
229
230
231	def _find_ffmpeg_binary() -> Optional[str]:
232	    return _find_binary("ffmpeg")
233
234
235	# Shared encode profile for every STT-bound m4a we produce (transcode and
236	# silence-trim): 16 kHz mono 32 kbps AAC, faststart. One owner — codec or
237	# bitrate changes must not drift between the two paths.
238	_STT_M4A_ENCODE_ARGS = (
239	    "-vn", "-ac", "1", "-ar", "16000",
240	    "-c:a", "aac", "-b:a", "32k", "-movflags", "+faststart",
241	)
242
243
244	def _run_ffmpeg_stt_encode(
245	    ffmpeg: str, input_path: str, output_path: str, *, audio_filter: Optional[str] = None
246	) -> None:
247	    """Run the shared STT m4a encode, optionally with an ``-af`` filter.
248
249	    Raises on failure (CalledProcessError / TimeoutExpired) — callers own
250	    the error semantics (transcode reports, trim swallows).
251	    """
252	    command = [ffmpeg, "-y", "-i", input_path]
253	    if audio_filter:
254	        command += ["-af", audio_filter]
255	    command += [*_STT_M4A_ENCODE_ARGS, output_path]
256	    subprocess.run(
257	        command, check=True, capture_output=True, text=True,
258	        encoding="utf-8", errors="replace", timeout=120,
259	        stdin=subprocess.DEVNULL, creationflags=windows_hide_flags(),
260	    )
261
262
263	def _transcode_audio_for_stt(file_path: str, work_dir: str) -> tuple[Optional[str], Optional[str]]:
264	    """Transcode ``file_path`` to a compact, broadly-accepted .m4a for STT upload.
265
266	    Newer OpenAI transcription models (``gpt-4o-transcribe``,
267	    ``gpt-4o-mini-transcribe``) reject some containers the legacy ``whisper-1``
268	    endpoint accepted -- notably the Ogg/Opus voice notes messaging apps send --
269	    and gateway downloads occasionally arrive with a misleading extension.
270	    Normalizing to 16 kHz mono AAC/m4a produces a small file the endpoints
271	    accept. Returns ``(converted_path, None)`` on success or ``(None, error)``.
272	    """
273	    ffmpeg = _find_ffmpeg_binary()
274	    if not ffmpeg:
275	        return None, "audio needs transcoding for the STT API, but ffmpeg was not found"
276	    converted_path = os.path.join(work_dir, f"{Path(file_path).stem or 'audio'}-stt.m4a")
277	    try:
278	        _run_ffmpeg_stt_encode(ffmpeg, file_path, converted_path)
279	        return converted_path, None
280	    except subprocess.CalledProcessError as exc:
281	        details = exc.stderr.strip() or exc.stdout.strip() or str(exc)
282	        logger.error("ffmpeg STT transcode failed for %s: %s", file_path, details)
283	        return None, f"failed to transcode audio for the STT API: {details}"
284	    except Exception as exc:  # noqa: BLE001 - transcode is best-effort
285	        logger.error("unexpected STT transcode failure for %s: %s", file_path, exc, exc_info=True)
286	        return None, f"failed to transcode audio for the STT API: {exc}"
287
288
289	def _find_whisper_binary() -> Optional[str]:
290	    return _find_binary("whisper")
291
292
293	def _get_local_command_template() -> Optional[str]:
294	    configured = os.getenv(LOCAL_STT_COMMAND_ENV, "").strip()
295	    if configured:
296	        return configured
297
298	    whisper_binary = _find_whisper_binary()
299	    if whisper_binary:
300	        quoted_binary = shlex.quote(whisper_binary)
301	        return (
302	            f"{quoted_binary} {{input_path}} --model {{model}} --output_format txt "
303	            "--output_dir {output_dir} --language {language}"
304	        )
305	    return None
306
307
308	def _has_local_command() -> bool:
309	    return _get_local_command_template() is not None
310
311
312	def _normalize_local_model(model_name: Optional[str]) -> str:
313	    """Return a valid faster-whisper model size, mapping cloud-only names to the default.
314
315	    Cloud providers like OpenAI use names such as ``whisper-1`` which are not
316	    valid for faster-whisper (which expects ``tiny``, ``base``, ``small``,
317	    ``medium``, or ``large-v*``).  When such a name is detected we fall back to
318	    the default local model and emit a warning so the user knows what happened.
319	    """
320	    if not model_name or model_name in OPENAI_MODELS or model_name in GROQ_MODELS:
321	        if model_name and (model_name in OPENAI_MODELS or model_name in GROQ_MODELS):
322	            logger.warning(
323	                "STT model '%s' is a cloud-only name and cannot be used with the local "
324	                "provider. Falling back to '%s'. Set stt.local.model to a valid "
325	                "faster-whisper size (tiny, base, small, medium, large-v3).",
326	                model_name,
327	                DEFAULT_LOCAL_MODEL,
328	            )
329	        return DEFAULT_LOCAL_MODEL
330	    return model_name
331
332
333	def _normalize_local_command_model(model_name: Optional[str]) -> str:
334	    return _normalize_local_model(model_name)
335
336
337	def _try_lazy_install_stt() -> bool:
338	    """Attempt to lazy-install faster-whisper and return True on success.
339
340	    The module-level ``_HAS_FASTER_WHISPER`` flag is set at import time and
341	    cached. If the package wasn't installed at startup, calling ``ensure()``
342	    installs it. This function re-checks dynamically after installation so
343	    the provider can use it immediately without a process restart.
344	    """
345	    try:
346	        from tools.lazy_deps import ensure
347	        # prompt=False: never raise a blocking input() prompt mid-session.
348	        # Under the interactive CLI prompt_toolkit owns stdin, so a bare
349	        # input() deadlocks the terminal (#40490). The install is already
350	        # gated by security.allow_lazy_installs, so reaching here is opt-in.
351	        ensure("stt.faster_whisper", prompt=False)
352	        # Re-check dynamically after install
353	        import importlib.util as _iu
354	        if _iu.find_spec("faster_whisper"):
355	            return True
356	        logger.warning(
357	            "faster-whisper was installed but importlib still cannot find it "
358	            "(may require Python restart)"
359	        )
360	    except Exception as exc:
361	        logger.warning(
362	            "Lazy install of faster-whisper failed: %s. "
363	            "This is often a permission issue: the Hermes process user cannot "
364	            "write to the virtual environment. Try running manually as the "
365	            "venv owner: `stat -c '%%u' '$(dirname $(dirname $(which python3)))'` "
366	            "then `su - <owner> -c 'VIRTUAL_ENV=/opt/hermes/.venv "
367	            "uv pip install faster-whisper==1.2.1'`",
368	            exc,
369	        )
370	    return False
371
372
373	# Names of the STT providers with native handlers in this module.
374	# Kept in sync with ``agent.transcription_registry._BUILTIN_NAMES`` —
375	# a regression test fails if they drift. The plugin hook from
376	# issue #30398-style follow-up rejects plugins registering under any
377	# of these names; the dispatcher in ``transcribe_audio`` short-circuits
378	# them defensively as well.
379	BUILTIN_STT_PROVIDERS = frozenset({
380	    "local",
381	    "local_command",
382	    "groq",
383	    "openai",
384	    "mistral",
385	    "xai",
386	    "elevenlabs",
387	    "deepinfra",
388	})
389
390
391	# ---------------------------------------------------------------------------

... (gap) ...

2799
2800
2801	def _find_ffprobe_binary() -> Optional[str]:
2802	    return _find_binary("ffprobe")
2803
2804
2805	def _probe_audio_duration(file_path: str) -> Optional[float]:
2806	    """Return the audio duration in seconds via ffprobe, or None.
2807
2808	    Canonical sync seconds-probe. ``gateway/run.py._probe_audio_duration``
2809	    (async, returns a display string) and the Telegram adapter's
2810	    ``_probe_voice_duration_seconds`` carry local variants of the same
2811	    ffprobe invocation — keep the command shape in sync.
2812	    """
2813	    ffprobe = _find_ffprobe_binary()
2814	    if not ffprobe:
2815	        return None
2816	    command = [
2817	        ffprobe, "-v", "error",
2818	        "-show_entries", "format=duration",
2819	        "-of", "default=noprint_wrappers=1:nokey=1",
2820	        file_path,
2821	    ]
2822	    try:
2823	        result = subprocess.run(
2824	            command, check=True, capture_output=True, text=True,
2825	            encoding="utf-8", errors="replace", timeout=30,
2826	            stdin=subprocess.DEVNULL, creationflags=windows_hide_flags(),
2827	        )
2828	        return float(result.stdout.strip())
2829	    except Exception:  # noqa: BLE001 - probe is best-effort
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,021 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
