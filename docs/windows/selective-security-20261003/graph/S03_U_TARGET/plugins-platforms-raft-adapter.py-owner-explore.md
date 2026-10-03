**Exploration: plugins/platforms/raft/adapter.py**

Found 73 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/raft/adapter.py`** — calls(calls), _error_response(calls), _raft_hook(decorates), _emit(calls), _safe_scalar(calls), _has_content_field(calls), instantiates(instantiates), _resolve_raft_profile(calls), handle_message(calls), AIOHTTP_AVAILABLE(variable), _duration_ms(calls), __init__(method), _forget_raft_context(calls), _authorized(calls), _read_bridge_body(calls), +86 more

```python
29
30	try:
31	    from aiohttp import web
32	    AIOHTTP_AVAILABLE = True
33	except ImportError:
34	    AIOHTTP_AVAILABLE = False
35	    web = None  # type: ignore[assignment]
36
37	sys.path.insert(0, str(_Path(__file__).resolve().parents[3]))
38
39	from gateway.config import Platform, PlatformConfig
40	from gateway.platforms.base import BasePlatformAdapter, SendResult, merge_pending_message_event
41	from gateway.platforms.event import MessageEvent, MessageType
42	from gateway.platforms._shared import coerce_port, profile_scoped as _profile_scoped
43
44	logger = logging.getLogger(__name__)
45
46	DEFAULT_HOST = "127.0.0.1"
47	DEFAULT_PORT = 0
48	DEFAULT_PATH = "/wake"
49	DEFAULT_RUNTIME_SESSION = "default"
50	DEFAULT_MAX_BODY_BYTES = 16_384
51	DEFAULT_ACTIVITY_QUEUE_CAP = 500
52	ACTIVITY_CONTENT_CAP = 4096
53	ACTIVITY_EVENT_SCHEMA = "raft-activity.v1"
54	ACTIVITY_DRAIN_SCHEMA = "raft-activity-drain.v1"
55	BRIDGE_TOKEN_HEADER = "x-raft-bridge-token"
56	_WAKE_ID_KEYS = ("eventId", "attemptId", "messageId", "delivery_id", "wake_id", "id")
57	_WAKE_PROMPT = (
58	    "Raft wake hint received. New Raft messages may be pending. "
59	    "If you have not read the Raft manual in this session, run "
60	    "`raft manual get raft-cli-overview` before using Raft commands.")
61
62	_CONTENT_FIELD_NAMES = {"body", "content", "message", "messages", "preview", "snippet", "text"}
63	_SAFE_SCALAR_RE = re.compile(r"^[a-zA-Z0-9._:@/ -]+$")
64	_MAX_SCALAR_LENGTH = 120
65	_ACTIVITY_ALLOWED_FIELDS = set(
66	    "schema eventId sessionId hookEventName status occurredAt toolName toolInput toolOutput "
67	    "toolInputTruncated toolOutputTruncated truncated errorClass durationMs".split())
68	_ACTIVE_ADAPTERS: "weakref.WeakSet[RaftAdapter]" = weakref.WeakSet()
69	_ACTIVE_ADAPTERS_LOCK = threading.Lock()
70	_RAFT_CONTEXT_LOCK = threading.Lock()
71	_RAFT_SESSION_IDS: set[str] = set()
72	_RAFT_TURN_IDS: set[str] = set()
73	_RAFT_PROMPT_TURN_IDS: set[str] = set()
74
75
76	def _resolve_raft_profile() -> str:
77	    """Scope-aware ``RAFT_PROFILE``: a secondary multiplex profile configures Raft only via its own ``.env``
78	    (secret scope) — ``os.environ`` would return the DEFAULT profile's value. Unscoped ``get_secret()`` raises."""
79	    if _profile_scoped():
80	        try:
81	            from agent.secret_scope import get_secret
82	            return (get_secret("RAFT_PROFILE") or "").strip()
83	        except Exception:
84	            return ""
85	    return os.environ.get("RAFT_PROFILE", "").strip()
86
87
88	def check_raft_requirements() -> bool:
89	    """Passive ``check_fn`` probe: intentionally silent — it runs on every
90	    ``load_gateway_config()``; ``create_adapter()`` warns when an adapter is requested."""
91	    return bool(AIOHTTP_AVAILABLE and shutil.which("raft"))
92
93
94	def _has_content_field(value: Any) -> bool:
95	    if isinstance(value, dict):
96	        return any(str(k).strip().lower() in _CONTENT_FIELD_NAMES or _has_content_field(v) for k, v in value.items())
97	    return isinstance(value, list) and any(_has_content_field(item) for item in value)
98
99
100	def _safe_scalar(value: Any, default: Optional[str] = None) -> Optional[str]:
101	    ok = isinstance(value, str) and 0 < len(value) <= _MAX_SCALAR_LENGTH and _SAFE_SCALAR_RE.match(value)
102	    return value if ok else default
103
104
105	def _content_string(value: Any) -> Optional[tuple[str, bool]]:
106	    if value is None:
107	        return None
108	    try:
109	        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
110	    except Exception:
111	        return None
112	    return (text[:ACTIVITY_CONTENT_CAP], len(text) > ACTIVITY_CONTENT_CAP) if text else None
113
114
115	def _duration_ms(value: Any) -> Optional[int]:
116	    if not isinstance(value, (int, float)) or isinstance(value, bool) or int(value) < 0:
117	        return None
118	    return int(value)
119
120
121	def _make_activity_event(*, hook_event_name: str, session_id: Any, status: str = "ok", tool_name: Any = None,
122	                         tool_input: Any = None, tool_output: Any = None, error_class: Any = None,
123	                         duration_ms: Any = None) -> Dict[str, Any]:
124	    event: Dict[str, Any] = {"schema": ACTIVITY_EVENT_SCHEMA, "eventId": f"hermes-{uuid.uuid4()}",
125	                             "sessionId": _safe_scalar(session_id, "unknown") or "unknown",
126	                             "hookEventName": hook_event_name, "status": "error" if status == "error" else "ok",
127	                             "occurredAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
128	    for key, raw in (("toolName", tool_name), ("errorClass", error_class)):
129	        if safe := _safe_scalar(raw):
130	            event[key] = safe
131	    if (safe_duration_ms := _duration_ms(duration_ms)) is not None:
132	        event["durationMs"] = safe_duration_ms
133	    for key, raw in (("toolInput", tool_input), ("toolOutput", tool_output)):
134	        if content := _content_string(raw):
135	            event[key], was_truncated = content
136	            if was_truncated:
137	                event[f"{key}Truncated"] = event["truncated"] = True
138	    return event
139
140
141	_OPTIONAL_FIELD_RULES = (  # checked in this order; first failure wins
142	    (("toolName", "errorClass"), _safe_scalar, "a safe string"),
143	    (("durationMs",), lambda v: _duration_ms(v) is not None, "a non-negative number"),
144	    (("truncated", "toolInputTruncated", "toolOutputTruncated"), lambda v: isinstance(v, bool), "a boolean"))
145
146
147	def _validate_activity_event(value: Any) -> Dict[str, Any]:
148	    if not isinstance(value, dict):
149	        raise ValueError("activity event must be an object")
150	    if value.get("schema") != ACTIVITY_EVENT_SCHEMA:
151	        raise ValueError("unsupported activity event schema")
152	    if unknown := set(value) - _ACTIVITY_ALLOWED_FIELDS:
153	        raise ValueError(f"activity event field {sorted(unknown)[0]} is not allowed")
154	    for key in ("eventId", "sessionId", "hookEventName", "occurredAt"):
155	        if not _safe_scalar(value.get(key)):
156	            raise ValueError(f"activity event {key} must be a safe non-empty string")
157	    if value.get("status") not in {"ok", "error"}:
158	        raise ValueError("activity event status must be ok|error")
159	    for keys, ok, what in _OPTIONAL_FIELD_RULES:  # optional fields: None passes, anything else must satisfy ``ok``
160	        for key in keys:
161	            if value.get(key) is not None and not ok(value.get(key)):
162	                raise ValueError(f"activity event {key} must be {what}")
163	    event = dict(value)
164	    if event.get("durationMs") is not None:
165	        event["durationMs"] = _duration_ms(event["durationMs"])
166	    for key in ("toolInput", "toolOutput"):
167	        content = event.get(key)
168	        if content is not None and not isinstance(content, str):
169	            raise ValueError(f"activity event {key} must be a string")
170	        if content is not None and len(content) > ACTIVITY_CONTENT_CAP:
171	            event[key] = content[:ACTIVITY_CONTENT_CAP]
172	            event["truncated"] = event[f"{key}Truncated"] = True
173	    return event
174
175
176	class ActivityQueue:
177	    """Bounded at-most-once queue for Raft external activity telemetry."""
178
179	    def __init__(self, cap: int = DEFAULT_ACTIVITY_QUEUE_CAP):
180	        self._cap = max(1, int(cap or DEFAULT_ACTIVITY_QUEUE_CAP))
181	        self._events: Deque[Dict[str, Any]] = deque()
182	        self._dropped_since_drain = 0
183	        self._lock = threading.Lock()
184
185	    def push(self, event: Dict[str, Any]) -> None:
186	        validated = _validate_activity_event(event)
187	        with self._lock:
188	            self._events.append(validated)
189	            while len(self._events) > self._cap:
190	                self._events.popleft()
191	                self._dropped_since_drain += 1
192
193	    def drain(self, max_events: int = 200) -> Dict[str, Any]:
194	        limit = max(1, int(max_events or 200))
195	        with self._lock:
196	            events = [self._events.popleft() for _ in range(min(limit, len(self._events)))]
197	            dropped, self._dropped_since_drain = self._dropped_since_drain, 0
198	        return {"schema": ACTIVITY_DRAIN_SCHEMA, "events": events, "dropped": dropped}
199
200	    @property
201	    def size(self) -> int:
202	        with self._lock:
203	            return len(self._events)
204
205
206	def _forget_raft_context(session_id: Any, turn_id: Any = None, *, forget_session: bool = False) -> None:
207	    safe_session_id, safe_turn_id = _safe_scalar(session_id), _safe_scalar(turn_id)
208	    with _RAFT_CONTEXT_LOCK:
209	        if safe_turn_id:
210	            _RAFT_TURN_IDS.discard(safe_turn_id)
211	            _RAFT_PROMPT_TURN_IDS.discard(safe_turn_id)
212	        if forget_session and safe_session_id:
213	            _RAFT_SESSION_IDS.discard(safe_session_id)
214
215
216	def _is_raft_context(**kwargs: Any) -> bool:
217	    """True for Raft hook payloads; an explicit platform="raft" also learns the session/turn ids."""
218	    platform = kwargs.get("platform")
219	    safe_session_id, safe_turn_id = _safe_scalar(kwargs.get("session_id")), _safe_scalar(kwargs.get("turn_id"))
220	    with _RAFT_CONTEXT_LOCK:
221	        if str(getattr(platform, "value", platform) or "") == "raft":
222	            if safe_session_id:
223	                _RAFT_SESSION_IDS.add(safe_session_id)
224	            if safe_turn_id:
225	                _RAFT_TURN_IDS.add(safe_turn_id)
226	            return True
227	        return bool((safe_turn_id and safe_turn_id in _RAFT_TURN_IDS)
228	                    or (safe_session_id and safe_session_id in _RAFT_SESSION_IDS))
229
230
231	def _emit(hook_event_name: str, kwargs: Dict[str, Any], **fields: Any) -> None:
232	    """Build an activity event for the hook's session and fan it out to every live adapter."""
233	    event = _make_activity_event(hook_event_name=hook_event_name, session_id=kwargs.get("session_id"), **fields)
234	    with _ACTIVE_ADAPTERS_LOCK:
235	        adapters = list(_ACTIVE_ADAPTERS)
236	    for adapter in adapters:
237	        adapter.report_activity(event)
238
239
240	def _raft_hook(fn):
241	    """Run the hook body only for Raft sessions."""
242	    @functools.wraps(fn)
243	    def wrapper(**kwargs: Any) -> None:
244	        if _is_raft_context(**kwargs):
245	            fn(**kwargs)
246	    return wrapper
247
248
249	@_raft_hook
250	def _on_session_start(**kwargs: Any) -> None:
251	    try:
252	        from tools.env_passthrough import register_env_passthrough
253	        register_env_passthrough(["RAFT_PROFILE"])
254	    except Exception:
255	        logger.debug("[raft] failed to register RAFT_PROFILE env passthrough", exc_info=True)
256	    _emit("SessionStart", kwargs)
257
258
259	@_raft_hook
260	def _on_pre_llm_call(**kwargs: Any) -> None:
261	    if safe_turn_id := _safe_scalar(kwargs.get("turn_id")):
262	        with _RAFT_CONTEXT_LOCK:
263	            if safe_turn_id in _RAFT_PROMPT_TURN_IDS:
264	                return
265	            _RAFT_PROMPT_TURN_IDS.add(safe_turn_id)
266	    _emit("UserPromptSubmit", kwargs)
267
268
269	@_raft_hook
270	def _on_pre_tool_call(**kwargs: Any) -> None:
271	    _emit("PreToolUse", kwargs, tool_name=kwargs.get("tool_name"), tool_input=kwargs.get("args"))
272
273
274	@_raft_hook
275	def _on_post_tool_call(**kwargs: Any) -> None:
276	    status = "error" if kwargs.get("status") in {"error", "blocked"} or kwargs.get("error_type") else "ok"
277	    _emit("PostToolUseFailure" if status == "error" else "PostToolUse", kwargs, status=status,
278	          tool_name=kwargs.get("tool_name"), tool_input=kwargs.get("args"),
279	          tool_output=kwargs.get("error_message") or kwargs.get("result"),
280	          error_class=kwargs.get("error_type") or ("tool_failure" if status == "error" else None),
281	          duration_ms=kwargs.get("duration_ms"))
282
283
284	@_raft_hook
285	def _on_post_llm_call(**kwargs: Any) -> None:
286	    _emit("Stop", kwargs)
287
288
289	@_raft_hook
290	def _on_session_end(**kwargs: Any) -> None:
291	    if kwargs.get("interrupted") or kwargs.get("completed") is False:
292	        _emit("Stop", kwargs, status="error", error_class="interrupted" if kwargs.get("interrupted") else "incomplete")
293	    _forget_raft_context(kwargs.get("session_id"), kwargs.get("turn_id"))
294
295
296	@_raft_hook
297	def _on_session_finalize(**kwargs: Any) -> None:
298	    _emit("SessionEnd", kwargs)
299	    _forget_raft_context(kwargs.get("session_id"), kwargs.get("turn_id"), forget_session=True)
300
301
302	def _error_response(error: str, status: int) -> "web.Response":
303	    return web.json_response({"ok": False, "error": error}, status=status)
304
305
306	class RaftAdapter(BasePlatformAdapter):
307	    """Local HTTP endpoint for Raft channel bridge delivery."""
308
309	    def __init__(self, config: PlatformConfig):
310	        super().__init__(config, Platform("raft"))
311	        extra = config.extra or {}
312	        self._host: str = str(extra.get("host", DEFAULT_HOST))
313	        self._port: int = int(extra.get("port", DEFAULT_PORT))
314	        path = str(extra.get("path", DEFAULT_PATH) or DEFAULT_PATH).strip() or DEFAULT_PATH
315	        self._path: str = path if path.startswith("/") else f"/{path}"
316	        self._bridge_token: str = str(extra.get("bridge_token", ""))
317	        self._runtime_session: str = str(extra.get("runtime_session", DEFAULT_RUNTIME_SESSION) or DEFAULT_RUNTIME_SESSION)
318	        self._max_body_bytes: int = int(extra.get("max_body_bytes", DEFAULT_MAX_BODY_BYTES))
319	        self._runner = None
320	        self._bridge_process: Optional[subprocess.Popen] = None
321	        self._activity_queue = ActivityQueue()
322
323	    async def connect(self, *, is_reconnect: bool = False) -> bool:
324	        if not self._bridge_token:

... (gap) ...

341	            except (ConnectionRefusedError, OSError):
342	                pass
343	        self._runner = web.AppRunner(app)
344	        await self._runner.setup()
345	        site = web.TCPSite(self._runner, self._host, self._port)
346	        await site.start()
347	        bound_port = self._port
348	        if bound_port == 0 and site._server and site._server.sockets:
349	            bound_port = site._server.sockets[0].getsockname()[1]
350	        self._mark_connected()
351	        with _ACTIVE_ADAPTERS_LOCK:
352	            _ACTIVE_ADAPTERS.add(self)
353	        logger.info("[raft] Raft channel listening on %s:%d%s", self._host, bound_port, self._path)
354	        self._spawn_bridge(bound_port)
355	        self._wire_plugin_handlers(None)  # plugin-registered native handlers
356	        return True
357
358	    async def disconnect(self) -> None:
359	        self._stop_bridge()
360	        if self._runner:
361	            await self._runner.cleanup()
362	            self._runner = None
363	        with _ACTIVE_ADAPTERS_LOCK:
364	            _ACTIVE_ADAPTERS.discard(self)
365	        self._mark_disconnected()
366	        logger.info("[raft] Disconnected")
367
368	    def _spawn_bridge(self, port: int) -> None:
369	        if not (raft_bin := shutil.which("raft")):
370	            logger.warning("[raft] raft CLI not found in PATH; bridge not spawned — wake-only polling mode")
371	            return
372	        if not (profile := _resolve_raft_profile()):
373	            logger.warning("[raft] RAFT_PROFILE not set; bridge not spawned")
374	            return
375	        endpoint = f"http://{self._host}:{port}{self._path}"
376	        cmd: List[str] = [raft_bin, "--profile", profile, "agent", "bridge", "--wake-adapter", "wake-channel",
377	                          "--wake-channel-endpoint", endpoint]
378	        from tools.environments.local import hermes_subprocess_env
379	        # The raft CLI needs its own profile and channel token, never Hermes' credentials.
380	        env = {**hermes_subprocess_env(), "RAFT_PROFILE": profile, "RAFT_CHANNEL_TOKEN": self._bridge_token}
381	        env["HOME"] = env["HERMES_REAL_HOME"]  # the raft CLI's own login lives under the user's HOME
382	        try:
383	            self._bridge_process = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL)
384	            logger.info("[raft] Spawned bridge pid=%d profile=%s endpoint=%s", self._bridge_process.pid, profile, endpoint)
385	        except Exception:
386	            logger.exception("[raft] Failed to spawn bridge")
387
388	    def _stop_bridge(self) -> None:
389	        proc, self._bridge_process = self._bridge_process, None
390	        if proc is None:
391	            return
392	        try:
393	            proc.terminate()
394	            proc.wait(timeout=5)
395	            logger.info("[raft] Bridge process terminated (pid=%d)", proc.pid)
396	        except subprocess.TimeoutExpired:
397	            proc.kill()
398	            logger.warning("[raft] Bridge process killed after timeout (pid=%d)", proc.pid)
399	        except Exception:
400	            logger.exception("[raft] Error stopping bridge")
401
402	    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
403	                   metadata: Optional[Dict[str, Any]] = None) -> SendResult:
404	        logger.debug("[raft] adapter send is a no-op; agent delivers via raft CLI")
405	        return SendResult(success=True)
406
407	    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
408	        return {"name": f"raft/{chat_id}", "type": "raft"}
409
410	    async def _handle_health(self, request: "web.Request") -> "web.Response":
411	        activity = {"queueSize": self._activity_queue.size, "endpoint": "/activity", "drainEndpoint": "/activity/drain"}
412	        return web.json_response(
413	            {"status": "ok", "platform": "raft", "runtimeSession": self._runtime_session, "activity": activity})
414
415	    def _authorized(self, request: "web.Request") -> bool:
416	        token = request.headers.get(BRIDGE_TOKEN_HEADER, "")
417	        # Compare as bytes: compare_digest raises TypeError on a non-ASCII str header.
418	        return bool(self._bridge_token and token) and hmac.compare_digest(token.encode(), self._bridge_token.encode())
419
420	    async def _read_bridge_body(self, request: "web.Request", *, text: bool) -> tuple[Any, Optional["web.Response"]]:
421	        """Auth + size-capped body read for wake/activity -> ``(body, None)`` or ``(None, error)``.
422	        ``text=True``: ``request.text()``, utf-8 length check, exception text in the 400 body; else raw bytes."""
423	        if not self._authorized(request):
424	            return None, _error_response("unauthorized", 401)
425	        if (request.content_length or 0) > self._max_body_bytes:
426	            return None, _error_response("payload_too_large", 413)
427	        try:
428	            body = await (request.text() if text else request.read())
429	        except web.HTTPRequestEntityTooLarge:
430	            # client_max_size tripped — chunked or lying Content-Length. Same 413 as above.
431	            return None, _error_response("payload_too_large", 413)
432	        except Exception as exc:
433	            return None, _error_response(str(exc) if text else "bad_request", 400)
434	        # Defense in depth: cap the actual bytes read even if the server-level limit was bypassed.
435	        if (len(body.encode("utf-8")) if text else len(body)) > self._max_body_bytes:
436	            return None, _error_response("payload_too_large", 413)
437	        return body, None
438
439	    async def _handle_wake(self, request: "web.Request") -> "web.Response":
440	        raw_body, error = await self._read_bridge_body(request, text=False)
441	        if error is not None:
442	            return error
443	        try:
444	            payload = json.loads(raw_body) if raw_body.strip() else {}
445	        except json.JSONDecodeError:
446	            return _error_response("invalid_json", 400)
447	        if not isinstance(payload, dict):
448	            return _error_response("invalid_payload", 400)
449	        # No payload["schema"] gate: the bridge owns schema evolution; Hermes only checks content-free.
450	        if _has_content_field(payload):
451	            return _error_response("content_not_allowed", 400)
452	        not_ready = {"ok": False, "error": "not_ready", "runtimeSession": self._runtime_session}
453	        if not self._message_handler:
454	            logger.warning("[raft] Wake received before gateway message handler was attached")
455	            return web.json_response(not_ready, status=503)
456	        delivery_id = str(
457	            next((payload.get(k) for k in _WAKE_ID_KEYS if payload.get(k)), None)
458	            or f"raft-wake-{int(time.time() * 1000)}")
459	        source = self.build_source(chat_id=self._runtime_session, chat_name="Raft channel", chat_type="dm",
460	                                   user_id="raft-bridge", user_name="Raft Bridge")
461	        event = MessageEvent(text=_WAKE_PROMPT, message_type=MessageType.TEXT, source=source,
462	                             raw_message=payload, message_id=delivery_id, internal=True)
463	        try:
464	            await self.handle_message(event)
465	        except Exception:
466	            logger.exception("[raft] Failed to inject wake event")
467	            return web.json_response(not_ready, status=503)
468	        return web.json_response({"ok": True, "runtimeSession": self._runtime_session}, status=202)
469
470	    async def _handle_activity(self, request: "web.Request") -> "web.Response":
471	        raw_text, error = await self._read_bridge_body(request, text=True)
472	        if error is not None:
473	            return error
474	        try:
475	            self._activity_queue.push(json.loads(raw_text))
476	        except json.JSONDecodeError:
477	            return _error_response("invalid_json", 400)
478	        except Exception as exc:
479	            return _error_response(str(exc), 400)
480	        return web.json_response({"ok": True}, status=202)
481
482	    async def _handle_activity_drain(self, request: "web.Request") -> "web.Response":
483	        if not self._authorized(request):
484	            return _error_response("unauthorized", 401)
485	        max_events = coerce_port(request.query.get("max", "200"), 200)  # int-or-default
486	        return web.json_response(self._activity_queue.drain(max_events))
487
488	    async def handle_message(self, event: MessageEvent) -> None:
489	        """Accept Raft wake hints without interrupting an active Hermes turn."""
490	        if event.internal:
491	            # Durable gateway wakes need the base session fence and admission receipt.
492	            await super().handle_message(event)
493	            return
494	        if not self._message_handler:
495	            return
496	        session_key = self._event_session_key(event)
497	        if session_key in self._active_sessions:
498	            logger.debug("[raft] Wake queued for busy session %s", session_key)
499	            merge_pending_message_event(self._pending_messages, session_key, event)
500	            return
501	        await super().handle_message(event)
502
503	    def report_activity(self, event: Dict[str, Any]) -> None:
504	        try:
505	            self._activity_queue.push(event)
506	        except Exception:
507	            logger.debug("[raft] activity event dropped during validation", exc_info=True)
508
509
510	def _is_connected(config: PlatformConfig) -> bool:
511	    extra = config.extra or {}
512	    return bool(extra.get("enabled") or extra.get("bridge_token"))
513
514
```
