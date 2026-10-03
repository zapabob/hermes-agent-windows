**Exploration: plugins/platforms/simplex/adapter.py**

Found 45 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/simplex/adapter.py`** — calls(calls), instantiates(instantiates), _send_command(calls), _prompt(calls), _redact_id(calls), _handle_chat_item(calls), _make_corr_id(calls), _send_fire_and_forget(calls), _is_audio_ext(calls), _send_ws(calls), send_document(calls), logger(variable), MAX_MESSAGE_LENGTH(variable), WS_RETRY_DELAY_INITIAL(variable), WS_RETRY_DELAY_MAX(variable), +59 more

```python
67	    SendResult,
68	)
69
70	logger = logging.getLogger(__name__)
71
72	# ---------------------------------------------------------------------------
73	# Constants
74	# ---------------------------------------------------------------------------
75	MAX_MESSAGE_LENGTH = 8000  # SimpleX has no hard limit; chunk for sanity
76	WS_RETRY_DELAY_INITIAL = 2.0
77	WS_RETRY_DELAY_MAX = 60.0
78	HEALTH_CHECK_INTERVAL = 30.0
79	HEALTH_CHECK_STALE_THRESHOLD = 300.0
80
81	# Correlation ID prefix for requests we send so we can ignore our own echoes.
82	_CORR_PREFIX = "hermes-"
83
84
85	# ---------------------------------------------------------------------------
86	# Helpers
87	# ---------------------------------------------------------------------------
88
89	def _parse_comma_list(value: str) -> List[str]:
90	    """Split a comma-separated string into a stripped list."""
91	    return [v.strip() for v in value.split(",") if v.strip()]
92
93
94	def _redact_id(contact_id: str) -> str:
95	    """Redact a contact/group ID for logging."""
96	    if not contact_id:
97	        return "<none>"
98	    s = str(contact_id)
99	    if len(s) <= 4:
100	        return s
101	    return s[:2] + "**" + s[-2:]
102
103
104	def _guess_extension(data: bytes) -> str:

... (gap) ...

122	    return ".bin"
123
124
125	def _is_image_ext(ext: str) -> bool:
126	    return ext.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
127
128
129	def _is_audio_ext(ext: str) -> bool:
130	    return ext.lower() in {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".opus"}
131
132
133	# ---------------------------------------------------------------------------
134	# SimpleX Adapter
135	# ---------------------------------------------------------------------------
136
137	class SimplexAdapter(BasePlatformAdapter):
138	    """SimpleX Chat adapter using the simplex-chat daemon WebSocket API.
139
140	    Instantiated by the ``adapter_factory`` passed to
141	    ``ctx.register_platform()`` in :func:`register`.
142	    """
143
144	    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH
145
146	    def __init__(self, config: PlatformConfig, **kwargs):
147	        platform = Platform("simplex")
148	        super().__init__(config=config, platform=platform)
149
150	        extra = getattr(config, "extra", {}) or {}

... (gap) ...

165	        group_allowed_str = os.getenv("SIMPLEX_GROUP_ALLOWED", "") or extra.get(
166	            "group_allowed", ""
167	        )
168	        self.group_allow_from = set(_parse_comma_list(group_allowed_str))
169
170	        # Running state
171	        self._ws = None  # websockets connection

... (gap) ...

234
235	        self._running = True
236	        self._last_ws_activity = time.time()
237	        self._ws_task = asyncio.create_task(self._ws_listener())
238	        self._health_task = asyncio.create_task(self._health_monitor())
239
240	        if hasattr(self, "_mark_connected"):
241	            self._mark_connected()
242	        logger.info("SimpleX: connected to %s", self.ws_url)
243	        # Plugin-registered native handlers (ctx.register_platform_handler).
244	        self._wire_plugin_handlers(None)
245	        return True
246
247	    async def disconnect(self) -> None:
248	        """Stop WebSocket listener and clean up."""
249	        self._running = False
250
251	        if self._ws_task:
252	            self._ws_task.cancel()
253	            try:
254	                await self._ws_task
255	            except asyncio.CancelledError:
256	                pass
257
258	        if self._health_task:
259	            self._health_task.cancel()
260	            try:
261	                await self._health_task
262	            except asyncio.CancelledError:
263	                pass
264
265	        if self._ws:
266	            try:
267	                await self._ws.close()
268	            except Exception:
269	                pass
270	            self._ws = None
271
272	        # Cancel pending text-batch flush timers
273	        for task in list(self._pending_text_batch_tasks.values()):
274	            if not task.done():
275	                task.cancel()
276	        self._pending_text_batch_tasks.clear()
277	        self._pending_text_batches.clear()
278
279	        # Cancel pending command futures
280	        for fut in self._pending_responses.values():
281	            if not fut.done():
282	                fut.cancel()
283	        self._pending_responses.clear()
284
285	        if hasattr(self, "_mark_disconnected"):
286	            self._mark_disconnected()
287	        logger.info("SimpleX: disconnected")
288
289	    # ------------------------------------------------------------------

... (gap) ...

317	                        self._last_ws_activity = time.time()
318	                        try:
319	                            msg = json.loads(raw)
320	                            await self._handle_event(msg)
321	                        except json.JSONDecodeError:
322	                            logger.debug("SimpleX WS: invalid JSON: %.100s", raw)
323	                        except Exception:
324	                            logger.exception("SimpleX WS: error handling event")
325
326	            except asyncio.CancelledError:
327	                break
328	            except ConnectionClosed as e:
329	                if self._running:
330	                    logger.warning(
331	                        "SimpleX WS: connection closed: %s (reconnecting in %.0fs)",
332	                        e, backoff,
333	                    )
334	            except Exception as e:
335	                if self._running:
336	                    logger.warning(
337	                        "SimpleX WS: unexpected error: %s (reconnecting in %.0fs)",
338	                        e, backoff,
339	                    )
340	            finally:
341	                self._ws = None
342
343	            if self._running:
344	                jitter = backoff * 0.2 * random.random()
345	                await asyncio.sleep(backoff + jitter)
346	                backoff = min(backoff * 2, WS_RETRY_DELAY_MAX)
347
348	    # ------------------------------------------------------------------
349	    # Health monitor
350	    # ------------------------------------------------------------------
351
352	    async def _health_monitor(self) -> None:
353	        """Observe WebSocket idleness without reconnecting healthy quiet links.
354
355	        simplex-chat can legitimately stay application-silent for long periods
356	        when no messages arrive. The websockets client already sends protocol
357	        pings (see _ws_listener ping_interval/ping_timeout), so treating lack of
358	        chat events as a stale connection causes needless reconnect churn.
359	        """
360	        while self._running:
361	            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
362	            if not self._running:
363	                break
364	            elapsed = time.time() - self._last_ws_activity
365	            if elapsed > HEALTH_CHECK_STALE_THRESHOLD:
366	                logger.debug("SimpleX: WS application-idle for %.0fs", elapsed)
367
368	    # ------------------------------------------------------------------
369	    # Inbound event handling
370	    # ------------------------------------------------------------------
371
372	    async def _handle_event(self, event: dict) -> None:
373	        """Dispatch a daemon event to the appropriate handler."""
374	        # simplex-chat WebSocket messages are usually shaped as:
375	        #   {"corrId": "...", "resp": {"type": "newChatItems", ...}}
376	        # Older/examples may put the response fields at top-level. Normalize
377	        # both forms before dispatching, otherwise inbound chatItems are lost.
378	        resp = event.get("resp") if isinstance(event.get("resp"), dict) else event
379	        corr_id = event.get("corrId")
380
381	        # Handle correlated responses (replies to our own commands)
382	        if corr_id and corr_id in self._pending_responses:
383	            fut = self._pending_responses.pop(corr_id)
384	            if not fut.done():
385	                fut.set_result(resp)
386	            return
387
388	        # Cosmetic echo filter: prefixed corrIds are ours but didn't make it
389	        # into _pending_responses (e.g. fire-and-forget).
390	        if corr_id and isinstance(corr_id, str) and corr_id.startswith(_CORR_PREFIX):
391	            self._pending_corr_ids.discard(corr_id)
392	            return
393
394	        resp_type = resp.get("type") or event.get("type", "")
395
396	        # Auto-accept contact requests
397	        if resp_type == "contactRequest" and self.auto_accept:
398	            contact_req = resp.get("contactRequest", {}) or {}
399	            contact_req_id = contact_req.get("contactRequestId")
400	            if contact_req_id is not None:
401	                logger.info(
402	                    "SimpleX: auto-accepting contact request %s",
403	                    _redact_id(str(contact_req_id)),
404	                )
405	                await self._send_command(f"/accept {contact_req_id}")
406	            return
407
408	        # Early file-descriptor ready: simplex fires this before newChatItems
409	        # for some file types (especially large files and voice messages
410	        # transferred via XFTP). Send /freceive immediately so the download
411	        # starts; the chat item arrives in a subsequent newChatItems event.
412	        if resp_type == "rcvFileDescrReady":
413	            rcv_file = resp.get("rcvFileTransfer", {}) or {}
414	            file_id = rcv_file.get("fileId") if isinstance(rcv_file, dict) else None
415	            if file_id is not None:
416	                logger.debug(
417	                    "SimpleX: rcvFileDescrReady for fileId=%s — sending /freceive",
418	                    file_id,
419	                )
420	                await self._send_fire_and_forget(f"/freceive {file_id}")
421	            return
422
423	        # New messages — simplex-chat sends "newChatItems" with an array
424	        if resp_type == "newChatItems":
425	            chat_items = resp.get("chatItems", []) or []
426	            if not isinstance(chat_items, list):
427	                chat_items = [chat_items]
428	            for item in chat_items:
429	                try:
430	                    await self._handle_chat_item(item)
431	                except Exception:
432	                    logger.exception("SimpleX: error processing chat item")
433	            return
434
435	        # Singular variant — some daemon versions emit this
436	        if resp_type == "newChatItem":
437	            try:
438	                await self._handle_chat_item(resp)
439	            except Exception:
440	                logger.exception("SimpleX: error processing chat item")
441	            return
442
443	        # File transfer completion — deliver any deferred chat item
444	        if resp_type == "rcvFileComplete":
445	            chat_item = resp.get("chatItem", {}) or {}
446	            chat_item_data = chat_item.get("chatItem", {}) or {}
447	            file_info = chat_item_data.get("file", {}) or {}
448	            file_id = file_info.get("fileId") if isinstance(file_info, dict) else None
449	            if file_id is not None and file_id in self._pending_file_transfers:
450	                pending = self._pending_file_transfers.pop(file_id)
451	                file_source = file_info.get("fileSource", {}) or {}
452	                file_path = (
453	                    file_source.get("filePath")
454	                    if isinstance(file_source, dict)
455	                    else None
456	                )
457	                if file_path:
458	                    pending_item_data = pending.get("chatItem", {}) or {}
459	                    pending_item_data.setdefault("file", {})["fileSource"] = {
460	                        "filePath": file_path
461	                    }
462	                    pending["chatItem"] = pending_item_data
463	                    try:
464	                        await self._handle_chat_item(pending)
465	                    except Exception:
466	                        logger.exception(
467	                            "SimpleX: error processing deferred file message"

... (gap) ...

515	        if chat_type == "direct":
516	            contact = chat_info.get("contact", {}) or {}
517	            sender_id = str(contact.get("contactId", ""))
518	            sender_name = contact.get("localDisplayName", "") or contact.get(
519	                "profile", {}
520	            ).get("displayName", "")
521	            chat_id = sender_id
522	        elif chat_type == "group":
523	            group_info = chat_info.get("groupInfo", {}) or {}
524	            group_id = str(group_info.get("groupId", ""))
525	            chat_id = f"group:{group_id}"
526	            is_group = True
527
528	            member = item_direction.get("groupMember", {}) or {}
529	            sender_id = str(member.get("memberId", ""))
530	            sender_name = member.get("localDisplayName", "") or member.get(
531	                "memberProfile", {}
532	            ).get("displayName", "")
533
534	            # Group allowlist
535	            if self.group_allow_from:
536	                if (
537	                    "*" not in self.group_allow_from
538	                    and group_id not in self.group_allow_from
539	                ):
540	                    logger.debug(
541	                        "SimpleX: group %s not in allowlist",
542	                        _redact_id(group_id),
543	                    )
544	                    return
545	            else:

... (gap) ...

579
580	            # Voice notes typically arrive before the file finishes
581	            # downloading. Defer the message until rcvFileComplete fires.
582	            if not file_path and _is_audio_ext(ext) and file_id is not None:
583	                logger.info(
584	                    "SimpleX: voice file %d not yet received, accepting transfer",
585	                    file_id,
586	                )
587	                self._pending_file_transfers[file_id] = chat_item
588	                # Fire-and-forget: simplex-chat does not return a corrId reply
589	                # for /freceive, so awaiting one would block the event loop.
590	                await self._send_fire_and_forget(f"/freceive {file_id}")
591	                return
592
593	            if file_path:
594	                ext = Path(file_path).suffix.lower() or (
595	                    Path(file_name).suffix.lower() if file_name else ""
596	                )
597	                if _is_image_ext(ext):
598	                    media_urls.append(file_path)
599	                    media_types.append(f"image/{ext.lstrip('.')}")
600	                elif _is_audio_ext(ext):
601	                    media_urls.append(file_path)
602	                    media_types.append(f"audio/{ext.lstrip('.')}")
603	                else:
604	                    media_urls.append(file_path)
605	                    media_types.append("application/octet-stream")
606
607	        # Source
608	        chat_name = sender_name
609	        if is_group:
610	            group_info = chat_info.get("groupInfo", {}) or {}
611	            chat_name = group_info.get("localDisplayName", "") or group_info.get(
612	                "groupProfile", {}
613	            ).get("displayName", chat_id)
614
615	        source = self.build_source(
616	            chat_id=chat_id,
617	            chat_name=chat_name,
618	            chat_type="group" if is_group else "dm",

... (gap) ...

639	            if ts_str:
640	                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
641	            else:
642	                timestamp = datetime.now(tz=timezone.utc)
643	        except (ValueError, AttributeError):
644	            timestamp = datetime.now(tz=timezone.utc)
645
646	        msg_event = MessageEvent(
647	            source=source,
648	            text=text or "",
649	            message_type=msg_type,
650	            media_urls=media_urls,
651	            media_types=media_types,
652	            timestamp=timestamp,
653	            raw_message=chat_item,
654	        )
655
656	        logger.debug(
657	            "SimpleX: message from %s in %s: %s",
658	            _redact_id(sender_id),
659	            chat_id[:20],
660	            (text or "")[:50],
661	        )
662
663	        # Batch consecutive text messages so the agent sees one combined
664	        # message instead of dropping earlier ones when the user pastes
665	        # several lines in quick succession.
666	        if msg_type == MessageType.TEXT and text:
667	            self._enqueue_text_event(msg_event)
668	        else:
669	            await self.handle_message(msg_event)
670
671	    # ------------------------------------------------------------------
672	    # Text message batching
673	    # ------------------------------------------------------------------
674
675	    def _text_batch_key(self, event: MessageEvent) -> str:
676	        """Session-scoped key for text message batching."""
677	        return f"{event.source.platform.value}:{event.source.chat_id}"
678
679	    def _enqueue_text_event(self, event: MessageEvent) -> None:
680	        """Buffer a text event and reset the flush timer."""
681	        key = self._text_batch_key(event)
682	        existing = self._pending_text_batches.get(key)
683	        if existing is None:
684	            self._pending_text_batches[key] = event
685	        else:
686	            if event.text:
687	                existing.text = (
688	                    f"{existing.text}\n{event.text}" if existing.text else event.text
689	                )
690	            if event.media_urls:
691	                existing.media_urls.extend(event.media_urls)
692	                existing.media_types.extend(event.media_types)
693
694	        prior_task = self._pending_text_batch_tasks.get(key)
695	        if prior_task and not prior_task.done():
696	            prior_task.cancel()
697	        self._pending_text_batch_tasks[key] = asyncio.create_task(
698	            self._flush_text_batch(key)
699	        )
700
701	    async def _flush_text_batch(self, key: str) -> None:
702	        """Wait for the quiet period then dispatch the aggregated text."""
703	        current_task = asyncio.current_task()
704	        try:
705	            await asyncio.sleep(self._text_batch_delay)
706	            event = self._pending_text_batches.pop(key, None)
707	            if not event:
708	                return
709	            logger.info(
710	                "[SimpleX] Flushing text batch %s (%d chars)",
711	                key,
712	                len(event.text or ""),
713	            )
714	            await self.handle_message(event)
715	        finally:
716	            if self._pending_text_batch_tasks.get(key) is current_task:
717	                self._pending_text_batch_tasks.pop(key, None)
718
719	    # ------------------------------------------------------------------
720	    # Command interface

... (gap) ...

731	        """
732	        self._corr_counter += 1
733	        corr_id = f"{_CORR_PREFIX}{self._corr_counter}-{int(time.time() * 1000)}"
734	        self._pending_corr_ids.add(corr_id)
735	        if len(self._pending_corr_ids) > self._max_pending_corr:
736	            overflow = len(self._pending_corr_ids) - self._max_pending_corr
737	            for _ in range(overflow):
738	                try:
739	                    self._pending_corr_ids.pop()
740	                except KeyError:
741	                    break
742	        return corr_id
743
744	    async def _send_ws(self, payload: dict) -> None:
745	        """Fire-and-forget JSON payload write.
746
747	        Drops cleanly when the WebSocket is missing or already closed; the
748	        caller never has to handle reconnection — the ``_ws_listener``
749	        loop does that out of band.
750	        """
751	        ws = self._ws
752	        if not ws:
753	            logger.debug("SimpleX: WS send dropped (not connected)")
754	            return
755	        try:
756	            await ws.send(json.dumps(payload))
757	        except Exception as e:
758	            logger.warning("SimpleX: WS send error: %s", e)
759
760	    async def _send_command(
761	        self, command: str, timeout: float = 30.0
762	    ) -> Optional[dict]:
763	        """Send a command and await the correlated response."""
764	        ws = self._ws
765	        if not ws:
766	            logger.warning("SimpleX: command sent but WebSocket not connected")
767	            return None
768
769	        corr_id = self._make_corr_id()
770	        payload = json.dumps({"corrId": corr_id, "cmd": command})
771
772	        loop = asyncio.get_event_loop()
773	        fut: asyncio.Future = loop.create_future()
774	        self._pending_responses[corr_id] = fut
775
776	        try:
777	            await ws.send(payload)
778	            result = await asyncio.wait_for(fut, timeout=timeout)
779	            return result
780	        except asyncio.TimeoutError:
781	            logger.warning("SimpleX: command timed out: %s", command[:50])
782	            self._pending_responses.pop(corr_id, None)
783	            return None
784	        except Exception as e:
785	            logger.warning("SimpleX: command failed: %s — %s", command[:50], e)
786	            self._pending_responses.pop(corr_id, None)
787	            return None
788
789	    async def _send_fire_and_forget(self, command: str) -> None:
790	        """Send a command without waiting for a correlated response.
791
792	        Use this for commands the daemon never sends a corrId reply for,
793	        such as ``/freceive``. Awaiting a corr-id reply on those would
794	        stall the event loop for the full command timeout.
795	        """
796	        corr_id = self._make_corr_id()
797	        await self._send_ws({"corrId": corr_id, "cmd": command})
798
799	    # ------------------------------------------------------------------
800	    # Outbound — text

... (gap) ...

828	        _voice_exts = {".ogg", ".mp3", ".wav", ".m4a", ".opus"}
829	        media_paths = re.findall(r"MEDIA:(\S+)", content)
830	        if media_paths:
831	            content = re.sub(r"MEDIA:\S+", "", content).strip()
832
833	        if content:
834	            corr_id = self._make_corr_id()
835	            # Structured form: addresses by ID, and json.dumps escapes
836	            # newlines + special chars correctly.  The bare @id text
837	            # syntax is unreliable for DMs — the daemon silently drops
838	            # messages when it cannot resolve the display name.
839	            composed = json.dumps(
840	                [{"msgContent": {"type": "text", "text": content}}]
841	            )
842	            if chat_id.startswith("group:"):
843	                cmd_str = f"/_send #{chat_id[6:]} json {composed}"
844	            else:
845	                cmd_str = f"/_send @{chat_id} json {composed}"
846
847	            await self._send_ws({"corrId": corr_id, "cmd": cmd_str})
848
849	        for path in media_paths:
850	            is_voice = os.path.splitext(path)[1].lower() in _voice_exts
851	            if is_voice:
852	                media_result = await self.send_voice(chat_id, path)
853	            else:
854	                media_result = await self.send_document(chat_id, path)
855	            if not media_result.success:
856	                return media_result
857
858	        return SendResult(success=True)
859
860	    # ------------------------------------------------------------------
861	    # Channel directory enumeration
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.
