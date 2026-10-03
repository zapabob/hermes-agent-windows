**Exploration: plugins/platforms/raft/adapter.py**

Found 72 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/raft/adapter.py`** — calls(calls), _safe_scalar(calls), _is_raft_context(calls), _report_activity(calls), _make_activity_event(calls), _has_content_field(calls), _duration_ms(calls), instantiates(instantiates), _validate_bridge_token(calls), _content_string(calls), __init__(method), _forget_raft_context(calls), push(calls), handle_message(calls), logger(variable), +91 more

```python
48	)
49	from gateway.session import build_session_key
50
51	logger = logging.getLogger(__name__)
52
53	DEFAULT_HOST = "127.0.0.1"
54	DEFAULT_PORT = 0
55	DEFAULT_PATH = "/wake"
56	DEFAULT_RUNTIME_SESSION = "default"
57	DEFAULT_MAX_BODY_BYTES = 16_384
58	DEFAULT_ACTIVITY_QUEUE_CAP = 500
59	ACTIVITY_CONTENT_CAP = 4096
60	ACTIVITY_EVENT_SCHEMA = "raft-activity.v1"
61	ACTIVITY_DRAIN_SCHEMA = "raft-activity-drain.v1"
62	BRIDGE_TOKEN_HEADER = "x-raft-bridge-token"
63
64	_CONTENT_FIELD_NAMES = {
65	    "body",
66	    "content",
67	    "message",
68	    "messages",
69	    "preview",
70	    "snippet",
71	    "text",
72	}
73
74	_SAFE_SCALAR_RE = re.compile(r"^[a-zA-Z0-9._:@/ -]+$")
75	_MAX_SCALAR_LENGTH = 120
76	_ACTIVITY_ALLOWED_FIELDS = {
77	    "schema",
78	    "eventId",

... (gap) ...

89	    "errorClass",
90	    "durationMs",
91	}
92	_ACTIVE_ADAPTERS: "weakref.WeakSet[RaftAdapter]" = weakref.WeakSet()
93	_ACTIVE_ADAPTERS_LOCK = threading.Lock()
94	_RAFT_CONTEXT_LOCK = threading.Lock()
95	_RAFT_SESSION_IDS: set[str] = set()
96	_RAFT_TURN_IDS: set[str] = set()
97	_RAFT_PROMPT_TURN_IDS: set[str] = set()
98
99
100	def check_raft_requirements() -> bool:

... (gap) ...

116	    return True
117
118
119	def _path_value(value: Any) -> str:
120	    path = str(value or DEFAULT_PATH).strip() or DEFAULT_PATH
121	    if not path.startswith("/"):
122	        path = f"/{path}"
123	    return path
124
125
126	def _has_content_field(value: Any) -> bool:
127	    if isinstance(value, dict):
128	        for key, nested in value.items():
129	            if str(key).strip().lower() in _CONTENT_FIELD_NAMES:
130	                return True
131	            if _has_content_field(nested):
132	                return True
133	    elif isinstance(value, list):
134	        return any(_has_content_field(item) for item in value)
135	    return False
136
137
138	def _platform_value(value: Any) -> str:
139	    return str(getattr(value, "value", value) or "")
140
141
142	def _safe_scalar(value: Any, default: Optional[str] = None) -> Optional[str]:
143	    if not isinstance(value, str):
144	        return default
145	    if not value or len(value) > _MAX_SCALAR_LENGTH:
146	        return default
147	    if not _SAFE_SCALAR_RE.match(value):
148	        return default
149	    return value
150
151
152	def _now_iso() -> str:
153	    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
154
155
156	def _content_string(value: Any) -> Optional[tuple[str, bool]]:

... (gap) ...

170	    return text, False
171
172
173	def _duration_ms(value: Any) -> Optional[int]:
174	    if not isinstance(value, (int, float)) or isinstance(value, bool):
175	        return None
176	    duration = int(value)
177	    if duration < 0:
178	        return None
179	    return duration
180
181
182	def _make_activity_event(

... (gap) ...

193	    event: Dict[str, Any] = {
194	        "schema": ACTIVITY_EVENT_SCHEMA,
195	        "eventId": f"hermes-{uuid.uuid4()}",
196	        "sessionId": _safe_scalar(session_id, "unknown") or "unknown",
197	        "hookEventName": hook_event_name,
198	        "status": "error" if status == "error" else "ok",
199	        "occurredAt": _now_iso(),
200	    }
201	    safe_tool_name = _safe_scalar(tool_name)
202	    if safe_tool_name:
203	        event["toolName"] = safe_tool_name
204	    safe_error_class = _safe_scalar(error_class)
205	    if safe_error_class:
206	        event["errorClass"] = safe_error_class
207	    safe_duration_ms = _duration_ms(duration_ms)
208	    if safe_duration_ms is not None:
209	        event["durationMs"] = safe_duration_ms
210
211	    truncated = False
212	    input_value = _content_string(tool_input)
213	    if input_value:
214	        event["toolInput"], input_truncated = input_value
215	        if input_truncated:
216	            event["toolInputTruncated"] = True
217	            truncated = True
218	    output_value = _content_string(tool_output)
219	    if output_value:
220	        event["toolOutput"], output_truncated = output_value
221	        if output_truncated:

... (gap) ...

235	    if unknown:
236	        raise ValueError(f"activity event field {sorted(unknown)[0]} is not allowed")
237	    for key in ("eventId", "sessionId", "hookEventName", "occurredAt"):
238	        if not _safe_scalar(value.get(key)):
239	            raise ValueError(f"activity event {key} must be a safe non-empty string")
240	    if value.get("status") not in {"ok", "error"}:
241	        raise ValueError("activity event status must be ok|error")
242	    if value.get("toolName") is not None and not _safe_scalar(value.get("toolName")):
243	        raise ValueError("activity event toolName must be a safe string")
244	    if value.get("errorClass") is not None and not _safe_scalar(value.get("errorClass")):
245	        raise ValueError("activity event errorClass must be a safe string")
246	    if value.get("durationMs") is not None and _duration_ms(value.get("durationMs")) is None:
247	        raise ValueError("activity event durationMs must be a non-negative number")
248	    for key in ("truncated", "toolInputTruncated", "toolOutputTruncated"):
249	        if value.get(key) is not None and not isinstance(value.get(key), bool):
250	            raise ValueError(f"activity event {key} must be a boolean")
251
252	    event = dict(value)
253	    if event.get("durationMs") is not None:
254	        event["durationMs"] = _duration_ms(event["durationMs"])
255	    for key in ("toolInput", "toolOutput"):
256	        content = event.get(key)
257	        if content is None:
258	            continue
259	        if not isinstance(content, str):
260	            raise ValueError(f"activity event {key} must be a string")
261	        if len(content) > ACTIVITY_CONTENT_CAP:
262	            event[key] = content[:ACTIVITY_CONTENT_CAP]
263	            event["truncated"] = True
264	            event[f"{key}Truncated"] = True
265	    return event
266
267
268	class ActivityQueue:
269	    """Bounded at-most-once queue for Raft external activity telemetry."""
270
271	    def __init__(self, cap: int = DEFAULT_ACTIVITY_QUEUE_CAP):
272	        self._cap = max(1, int(cap or DEFAULT_ACTIVITY_QUEUE_CAP))
273	        self._events: Deque[Dict[str, Any]] = deque()
274	        self._dropped_since_drain = 0
275	        self._lock = threading.Lock()
276
277	    def push(self, event: Dict[str, Any]) -> None:
278	        validated = _validate_activity_event(event)
279	        with self._lock:
280	            self._events.append(validated)
281	            while len(self._events) > self._cap:
282	                self._events.popleft()
283	                self._dropped_since_drain += 1
284
285	    def drain(self, max_events: int = 200) -> Dict[str, Any]:
286	        limit = max(1, int(max_events or 200))
287	        with self._lock:
288	            events: List[Dict[str, Any]] = []
289	            while self._events and len(events) < limit:
290	                events.append(self._events.popleft())
291	            dropped = self._dropped_since_drain
292	            self._dropped_since_drain = 0
293	        return {"schema": ACTIVITY_DRAIN_SCHEMA, "events": events, "dropped": dropped}
294
295	    @property
296	    def size(self) -> int:
297	        with self._lock:
298	            return len(self._events)
299
300
301	def _remember_raft_context(session_id: Any, turn_id: Any = None) -> None:
302	    safe_session_id = _safe_scalar(session_id)
303	    safe_turn_id = _safe_scalar(turn_id)
304	    with _RAFT_CONTEXT_LOCK:
305	        if safe_session_id:
306	            _RAFT_SESSION_IDS.add(safe_session_id)
307	        if safe_turn_id:
308	            _RAFT_TURN_IDS.add(safe_turn_id)
309
310
311	def _forget_raft_context(session_id: Any, turn_id: Any = None, *, forget_session: bool = False) -> None:
312	    safe_session_id = _safe_scalar(session_id)
313	    safe_turn_id = _safe_scalar(turn_id)
314	    with _RAFT_CONTEXT_LOCK:
315	        if safe_turn_id:
316	            _RAFT_TURN_IDS.discard(safe_turn_id)
317	            _RAFT_PROMPT_TURN_IDS.discard(safe_turn_id)
318	        if forget_session and safe_session_id:
319	            _RAFT_SESSION_IDS.discard(safe_session_id)
320
321
322	def _is_raft_context(**kwargs: Any) -> bool:
323	    if _platform_value(kwargs.get("platform")) == "raft":
324	        _remember_raft_context(kwargs.get("session_id"), kwargs.get("turn_id"))
325	        return True
326	    safe_session_id = _safe_scalar(kwargs.get("session_id"))
327	    safe_turn_id = _safe_scalar(kwargs.get("turn_id"))
328	    with _RAFT_CONTEXT_LOCK:
329	        return bool(
330	            (safe_turn_id and safe_turn_id in _RAFT_TURN_IDS)
331	            or (safe_session_id and safe_session_id in _RAFT_SESSION_IDS)
332	        )
333
334
335	def _report_activity(event: Dict[str, Any]) -> None:
336	    with _ACTIVE_ADAPTERS_LOCK:
337	        adapters = list(_ACTIVE_ADAPTERS)
338	    for adapter in adapters:
339	        adapter.report_activity(event)
340
341
342	def _on_session_start(**kwargs: Any) -> None:
343	    if not _is_raft_context(**kwargs):
344	        return
345	    try:
346	        from tools.env_passthrough import register_env_passthrough
347
348	        register_env_passthrough(["RAFT_PROFILE"])
349	    except Exception:
350	        logger.debug("[raft] failed to register RAFT_PROFILE env passthrough", exc_info=True)
351	    _report_activity(
352	        _make_activity_event(
353	            hook_event_name="SessionStart",
354	            session_id=kwargs.get("session_id"),
355	        )
356	    )
357
358
359	def _on_pre_llm_call(**kwargs: Any) -> None:
360	    if not _is_raft_context(**kwargs):
361	        return
362	    safe_turn_id = _safe_scalar(kwargs.get("turn_id"))
363	    if safe_turn_id:
364	        with _RAFT_CONTEXT_LOCK:
365	            if safe_turn_id in _RAFT_PROMPT_TURN_IDS:
366	                return
367	            _RAFT_PROMPT_TURN_IDS.add(safe_turn_id)
368	    _report_activity(
369	        _make_activity_event(
370	            hook_event_name="UserPromptSubmit",
371	            session_id=kwargs.get("session_id"),
372	        )
373	    )
374
375
376	def _on_pre_tool_call(**kwargs: Any) -> None:
377	    if not _is_raft_context(**kwargs):
378	        return
379	    _report_activity(
380	        _make_activity_event(
381	            hook_event_name="PreToolUse",
382	            session_id=kwargs.get("session_id"),
383	            tool_name=kwargs.get("tool_name"),
384	            tool_input=kwargs.get("args"),
385	        )
386	    )
387
388
389	def _on_post_tool_call(**kwargs: Any) -> None:
390	    if not _is_raft_context(**kwargs):
391	        return
392	    status = "error" if kwargs.get("status") in {"error", "blocked"} or kwargs.get("error_type") else "ok"
393	    hook_name = "PostToolUseFailure" if status == "error" else "PostToolUse"
394	    _report_activity(
395	        _make_activity_event(
396	            hook_event_name=hook_name,
397	            session_id=kwargs.get("session_id"),
398	            status=status,
399	            tool_name=kwargs.get("tool_name"),
400	            tool_input=kwargs.get("args"),
401	            tool_output=kwargs.get("error_message") or kwargs.get("result"),
402	            error_class=kwargs.get("error_type") or ("tool_failure" if status == "error" else None),
403	            duration_ms=kwargs.get("duration_ms"),
404	        )
405	    )
406
407
408	def _on_post_llm_call(**kwargs: Any) -> None:
409	    if not _is_raft_context(**kwargs):
410	        return
411	    _report_activity(
412	        _make_activity_event(
413	            hook_event_name="Stop",
414	            session_id=kwargs.get("session_id"),
415	        )
416	    )
417
418
419	def _on_session_end(**kwargs: Any) -> None:
420	    if not _is_raft_context(**kwargs):
421	        return
422	    if kwargs.get("interrupted") or kwargs.get("completed") is False:
423	        _report_activity(
424	            _make_activity_event(
425	                hook_event_name="Stop",
426	                session_id=kwargs.get("session_id"),
427	                status="error",
428	                error_class="interrupted" if kwargs.get("interrupted") else "incomplete",
429	            )
430	        )
431	    _forget_raft_context(kwargs.get("session_id"), kwargs.get("turn_id"))
432
433
434	def _on_session_finalize(**kwargs: Any) -> None:
435	    if not _is_raft_context(**kwargs):
436	        return
437	    _report_activity(
438	        _make_activity_event(
439	            hook_event_name="SessionEnd",
440	            session_id=kwargs.get("session_id"),
441	        )
442	    )
443	    _forget_raft_context(kwargs.get("session_id"), kwargs.get("turn_id"), forget_session=True)
444
445
446	class RaftAdapter(BasePlatformAdapter):
447	    """Local HTTP endpoint for Raft channel bridge delivery."""
448
449	    def __init__(self, config: PlatformConfig):
450	        super().__init__(config, Platform("raft"))
451	        extra = config.extra or {}
452	        self._host: str = str(extra.get("host", DEFAULT_HOST))
453	        self._port: int = int(extra.get("port", DEFAULT_PORT))
454	        self._path: str = _path_value(extra.get("path", DEFAULT_PATH))
455	        self._bridge_token: str = str(extra.get("bridge_token", ""))
456	        self._runtime_session: str = str(
457	            extra.get("runtime_session", DEFAULT_RUNTIME_SESSION)
458	            or DEFAULT_RUNTIME_SESSION
459	        )
460	        self._max_body_bytes: int = int(
461	            extra.get("max_body_bytes", DEFAULT_MAX_BODY_BYTES)
462	        )
463	        self._runner = None
464	        self._bridge_process: Optional[subprocess.Popen] = None
465	        self._activity_queue = ActivityQueue()
466
467	    @property
468	    def runtime_session(self) -> str:
469	        return self._runtime_session
470
471	    async def connect(self, *, is_reconnect: bool = False) -> bool:
472	        if not self._bridge_token:

... (gap) ...

499	                pass
500
501	        self._runner = web.AppRunner(app)
502	        await self._runner.setup()
503	        site = web.TCPSite(self._runner, self._host, self._port)
504	        await site.start()
505
506	        bound_port = self._port
507	        if bound_port == 0 and site._server and site._server.sockets:
508	            bound_port = site._server.sockets[0].getsockname()[1]
509
510	        self._mark_connected()
511	        with _ACTIVE_ADAPTERS_LOCK:
512	            _ACTIVE_ADAPTERS.add(self)
513	        logger.info("[raft] Raft channel listening on %s:%d%s", self._host, bound_port, self._path)
514
515	        self._spawn_bridge(bound_port)
516	        # Plugin-registered native handlers (ctx.register_platform_handler).
517	        self._wire_plugin_handlers(None)
518	        return True
519
520	    async def disconnect(self) -> None:
521	        self._stop_bridge()
522	        if self._runner:
523	            await self._runner.cleanup()
524	            self._runner = None
525	        with _ACTIVE_ADAPTERS_LOCK:
526	            _ACTIVE_ADAPTERS.discard(self)
527	        self._mark_disconnected()
528	        logger.info("[raft] Disconnected")
529
530	    def _spawn_bridge(self, port: int) -> None:
531	        raft_bin = shutil.which("raft")
532	        if not raft_bin:
533	            logger.warning("[raft] raft CLI not found in PATH; bridge not spawned — wake-only polling mode")
534	            return
535
536	        profile = os.environ.get("RAFT_PROFILE", "")
537	        if not profile:
538	            logger.warning("[raft] RAFT_PROFILE not set; bridge not spawned")
539	            return
540
541	        endpoint = f"http://{self._host}:{port}{self._path}"

... (gap) ...

560	            return
561	        self._bridge_process = None
562	        try:
563	            proc.terminate()
564	            proc.wait(timeout=5)
565	            logger.info("[raft] Bridge process terminated (pid=%d)", proc.pid)
566	        except subprocess.TimeoutExpired:
567	            proc.kill()
568	            logger.warning("[raft] Bridge process killed after timeout (pid=%d)", proc.pid)
569	        except Exception:
570	            logger.exception("[raft] Error stopping bridge")
571
572	    async def send(
573	        self,
574	        chat_id: str,
575	        content: str,
576	        reply_to: Optional[str] = None,
577	        metadata: Optional[Dict[str, Any]] = None,
578	    ) -> SendResult:
579	        logger.debug("[raft] adapter send is a no-op; agent delivers via raft CLI")
580	        return SendResult(success=True)
581
582	    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
583	        return {"name": f"raft/{chat_id}", "type": "raft"}
584
585	    async def _handle_health(self, request: "web.Request") -> "web.Response":
586	        return web.json_response(

... (gap) ...

597	        )
598
599	    async def _handle_wake(self, request: "web.Request") -> "web.Response":
600	        if not self._validate_bridge_token(request.headers.get(BRIDGE_TOKEN_HEADER, "")):
601	            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
602
603	        content_length = request.content_length or 0
604	        if content_length > self._max_body_bytes:
605	            return web.json_response({"ok": False, "error": "payload_too_large"}, status=413)
606
607	        try:
608	            raw_body = await request.read()
609	        except web.HTTPRequestEntityTooLarge:
610	            # aiohttp's client_max_size tripped — chunked or lying
611	            # Content-Length. Same 413 as the header check above.

... (gap) ...

629
630	        # Do not gate on payload["schema"]: the bridge owns schema evolution;
631	        # Hermes only verifies that wake hints are content-free.
632	        if _has_content_field(payload):
633	            return web.json_response({"ok": False, "error": "content_not_allowed"}, status=400)
634
635	        accepted = await self._accept_wake(payload)
636	        if not accepted:
637	            return web.json_response(
638	                {

... (gap) ...

652	        )
653
654	    async def _handle_activity(self, request: "web.Request") -> "web.Response":
655	        if not self._validate_bridge_token(request.headers.get(BRIDGE_TOKEN_HEADER, "")):
656	            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
657
658	        content_length = request.content_length or 0

... (gap) ...

674
675	        try:
676	            payload = json.loads(raw_text)
677	            self._activity_queue.push(payload)
678	        except json.JSONDecodeError:
679	            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
680	        except Exception as exc:
681	            return web.json_response({"ok": False, "error": str(exc)}, status=400)
682
683	        return web.json_response({"ok": True}, status=202)
684
685	    async def _handle_activity_drain(self, request: "web.Request") -> "web.Response":
686	        if not self._validate_bridge_token(request.headers.get(BRIDGE_TOKEN_HEADER, "")):
687	            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
688	        try:
689	            max_events = int(request.query.get("max", "200"))
690	        except ValueError:
691	            max_events = 200
692	        return web.json_response(self._activity_queue.drain(max_events))
693
694	    def _validate_bridge_token(self, token: str) -> bool:
695	        if not self._bridge_token or not token:
696	            return False
697	        # Compare as bytes: compare_digest raises TypeError on a str with
698	        # non-ASCII characters, and the token is a raw request header.
699	        return hmac.compare_digest(token.encode(), self._bridge_token.encode())
700
701	    async def _accept_wake(self, payload: Dict[str, Any]) -> bool:
702	        if not self._message_handler:
703	            logger.warning("[raft] Wake received before gateway message handler was attached")
704	            return False
705
706	        delivery_id = str(
707	            payload.get("eventId")
708	            or payload.get("attemptId")
709	            or payload.get("messageId")
710	            or payload.get("delivery_id")
711	            or payload.get("wake_id")
712	            or payload.get("id")
713	            or f"raft-wake-{int(time.time() * 1000)}"
714	        )
715	        source = self.build_source(
716	            chat_id=self._runtime_session,
717	            chat_name="Raft channel",
718	            chat_type="dm",
719	            user_id="raft-bridge",
720	            user_name="Raft Bridge",
721	        )
722	        event = MessageEvent(
723	            text=self._wake_prompt(),
724	            message_type=MessageType.TEXT,
725	            source=source,
726	            raw_message=payload,
727	            message_id=delivery_id,
728	            internal=True,
729	        )
730	        try:
731	            await self.handle_message(event)
732	        except Exception:
733	            logger.exception("[raft] Failed to inject wake event")
734	            return False
735	        return True
736
737	    async def handle_message(self, event: MessageEvent) -> None:
738	        """Accept Raft wake hints without interrupting an active Hermes turn."""
739	        if not self._message_handler:
740	            return
741
742	        session_key = build_session_key(
743	            event.source,
744	            group_sessions_per_user=self.config.extra.get("group_sessions_per_user", True),
745	            thread_sessions_per_user=self.config.extra.get("thread_sessions_per_user", False),
746	            profile=self._session_key_profile(event.source),
747	        )
748
749	        if session_key in self._active_sessions:
750	            logger.debug("[raft] Wake queued for busy session %s", session_key)
751	            merge_pending_message_event(self._pending_messages, session_key, event)
752	            return
753
754	        await super().handle_message(event)
755
756	    @staticmethod
757	    def _wake_prompt() -> str:
758	        return (
759	            "Raft wake hint received. New Raft messages may be pending. "
760	            "If you have not read the Raft manual in this session, run "
761	            "`raft manual get raft-cli-overview` before using Raft commands."
762	        )
763
764	    def report_activity(self, event: Dict[str, Any]) -> None:
765	        try:
766	            self._activity_queue.push(event)
767	        except Exception:
768	            logger.debug("[raft] activity event dropped during validation", exc_info=True)
769
770
771	def _is_connected(config: PlatformConfig) -> bool:
772	    extra = config.extra or {}
773	    return bool(extra.get("enabled") or extra.get("bridge_token"))
774
775
776	def _env_enablement() -> Optional[dict]:

... (gap) ...

801	    )
802	    from hermes_cli.config import get_env_value, save_env_value
803
804	    print_header("Raft")
805	    existing_profile = get_env_value("RAFT_PROFILE")
806	    if existing_profile:
807	        print_info(f"Raft: already configured (profile: {existing_profile})")
808	        if not prompt_yes_no("Reconfigure Raft?", False):
809	            print_info(f"Keeping RAFT_PROFILE={existing_profile}.")
810	            return
811
812	    print_info("Connect Hermes to Raft as an external agent.")
813	    print_info("Create the External Agent in Raft first, then run:")
814	    print_info("  raft agent login --server <server-url> --agent <agent-id> --profile-slug <slug>")
815	    print()
816
817	    profile = prompt("Raft profile slug", default=existing_profile or "")
818	    if not profile:
819	        print_warning("Raft profile slug is required; skipping Raft setup")
820	        return
821
822	    save_env_value("RAFT_PROFILE", profile.strip())
823
824	    print()
```


> **Explore budget: 3 calls for this project (9,016 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
