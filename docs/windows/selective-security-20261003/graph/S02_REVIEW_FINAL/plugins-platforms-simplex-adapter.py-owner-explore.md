**Exploration: plugins/platforms/simplex/adapter.py**

Found 45 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/simplex/adapter.py`** — calls(calls), instantiates(instantiates), _send_command(calls), _prompt(calls), _redact_id(calls), _handle_chat_item(calls), _make_corr_id(calls), _send_fire_and_forget(calls), _is_audio_ext(calls), _send_ws(calls), send_document(calls), logger(variable), MAX_MESSAGE_LENGTH(variable), WS_RETRY_DELAY_INITIAL(variable), WS_RETRY_DELAY_MAX(variable), +59 more

```python
65	    SendResult,
66	)
67
68	logger = logging.getLogger(__name__)
69
70	# ---------------------------------------------------------------------------
71	# Constants
72	# ---------------------------------------------------------------------------
73	MAX_MESSAGE_LENGTH = 8000  # SimpleX has no hard limit; chunk for sanity
74	WS_RETRY_DELAY_INITIAL = 2.0
75	WS_RETRY_DELAY_MAX = 60.0
76	HEALTH_CHECK_INTERVAL = 30.0
77	HEALTH_CHECK_STALE_THRESHOLD = 300.0
78
79	# Correlation ID prefix for requests we send so we can ignore our own echoes.
80	_CORR_PREFIX = "hermes-"
81
82
83	# ---------------------------------------------------------------------------
84	# Helpers
85	# ---------------------------------------------------------------------------
86
87	def _parse_comma_list(value: str) -> List[str]:
88	    """Split a comma-separated string into a stripped list."""
89	    return [v.strip() for v in value.split(",") if v.strip()]
90
91
92	def _redact_id(contact_id: str) -> str:
93	    """Redact a contact/group ID for logging."""
94	    if not contact_id:
95	        return "<none>"
96	    s = str(contact_id)
97	    if len(s) <= 4:
98	        return s
99	    return s[:2] + "**" + s[-2:]
100
101
102	def _guess_extension(data: bytes) -> str:

... (gap) ...

120	    return ".bin"
121
122
123	def _is_image_ext(ext: str) -> bool:
124	    return ext.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
125
126
127	def _is_audio_ext(ext: str) -> bool:
128	    return ext.lower() in {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".opus"}
129
130
131	# ---------------------------------------------------------------------------
132	# SimpleX Adapter
133	# ---------------------------------------------------------------------------
134
135	class SimplexAdapter(BasePlatformAdapter):
136	    """SimpleX Chat adapter using the simplex-chat daemon WebSocket API.
137
138	    Instantiated by the ``adapter_factory`` passed to
139	    ``ctx.register_platform()`` in :func:`register`.
140	    """
141
142	    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH
143
144	    def __init__(self, config: PlatformConfig, **kwargs):
145	        platform = Platform("simplex")
146	        super().__init__(config=config, platform=platform)
147
148	        extra = getattr(config, "extra", {}) or {}

... (gap) ...

163	        group_allowed_str = os.getenv("SIMPLEX_GROUP_ALLOWED", "") or extra.get(
164	            "group_allowed", ""
165	        )
166	        self.group_allow_from = set(_parse_comma_list(group_allowed_str))
167
168	        # Running state
169	        self._ws = None  # websockets connection

... (gap) ...

232
233	        self._running = True
234	        self._last_ws_activity = time.time()
235	        self._ws_task = asyncio.create_task(self._ws_listener())
236	        self._health_task = asyncio.create_task(self._health_monitor())
237
238	        if hasattr(self, "_mark_connected"):
239	            self._mark_connected()
240	        logger.info("SimpleX: connected to %s", self.ws_url)
241	        # Plugin-registered native handlers (ctx.register_platform_handler).
242	        self._wire_plugin_handlers(None)
243	        return True
244
245	    async def disconnect(self) -> None:
246	        """Stop WebSocket listener and clean up."""
247	        self._running = False
248
249	        if self._ws_task:
250	            self._ws_task.cancel()
251	            try:
252	                await self._ws_task
253	            except asyncio.CancelledError:
254	                pass
255
256	        if self._health_task:
257	            self._health_task.cancel()
258	            try:
259	                await self._health_task
260	            except asyncio.CancelledError:
261	                pass
262
263	        if self._ws:
264	            try:
265	                await self._ws.close()
266	            except Exception:
267	                pass
268	            self._ws = None
269
270	        # Cancel pending text-batch flush timers
271	        for task in list(self._pending_text_batch_tasks.values()):
272	            if not task.done():
273	                task.cancel()
274	        self._pending_text_batch_tasks.clear()
275	        self._pending_text_batches.clear()
276
277	        # Cancel pending command futures
278	        for fut in self._pending_responses.values():
279	            if not fut.done():
280	                fut.cancel()
281	        self._pending_responses.clear()
282
283	        if hasattr(self, "_mark_disconnected"):
284	            self._mark_disconnected()
285	        logger.info("SimpleX: disconnected")
286
287	    # ------------------------------------------------------------------

... (gap) ...

315	                        self._last_ws_activity = time.time()
316	                        try:
317	                            msg = json.loads(raw)
318	                            await self._handle_event(msg)
319	                        except json.JSONDecodeError:
320	                            logger.debug("SimpleX WS: invalid JSON: %.100s", raw)
321	                        except Exception:
322	                            logger.exception("SimpleX WS: error handling event")
323
324	            except asyncio.CancelledError:
325	                break
326	            except ConnectionClosed as e:
327	                if self._running:
328	                    logger.warning(
329	                        "SimpleX WS: connection closed: %s (reconnecting in %.0fs)",
330	                        e, backoff,
331	                    )
332	            except Exception as e:
333	                if self._running:
334	                    logger.warning(
335	                        "SimpleX WS: unexpected error: %s (reconnecting in %.0fs)",
336	                        e, backoff,
337	                    )
338	            finally:
339	                self._ws = None
340
341	            if self._running:
342	                jitter = backoff * 0.2 * random.random()
343	                await asyncio.sleep(backoff + jitter)
344	                backoff = min(backoff * 2, WS_RETRY_DELAY_MAX)
345
346	    # ------------------------------------------------------------------
347	    # Health monitor
348	    # ------------------------------------------------------------------
349
350	    async def _health_monitor(self) -> None:
351	        """Observe WebSocket idleness without reconnecting healthy quiet links.
352
353	        simplex-chat can legitimately stay application-silent for long periods
354	        when no messages arrive. The websockets client already sends protocol
355	        pings (see _ws_listener ping_interval/ping_timeout), so treating lack of
356	        chat events as a stale connection causes needless reconnect churn.
357	        """
358	        while self._running:
359	            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
360	            if not self._running:
361	                break
362	            elapsed = time.time() - self._last_ws_activity
363	            if elapsed > HEALTH_CHECK_STALE_THRESHOLD:
364	                logger.debug("SimpleX: WS application-idle for %.0fs", elapsed)
365
366	    # ------------------------------------------------------------------
367	    # Inbound event handling
368	    # ------------------------------------------------------------------
369
370	    async def _handle_event(self, event: dict) -> None:
371	        """Dispatch a daemon event to the appropriate handler."""
372	        # simplex-chat WebSocket messages are usually shaped as:
373	        #   {"corrId": "...", "resp": {"type": "newChatItems", ...}}
374	        # Older/examples may put the response fields at top-level. Normalize
375	        # both forms before dispatching, otherwise inbound chatItems are lost.
376	        resp = event.get("resp") if isinstance(event.get("resp"), dict) else event
377	        corr_id = event.get("corrId")
378
379	        # Handle correlated responses (replies to our own commands)
380	        if corr_id and corr_id in self._pending_responses:
381	            fut = self._pending_responses.pop(corr_id)
382	            if not fut.done():
383	                fut.set_result(resp)
384	            return
385
386	        # Cosmetic echo filter: prefixed corrIds are ours but didn't make it
387	        # into _pending_responses (e.g. fire-and-forget).
388	        if corr_id and isinstance(corr_id, str) and corr_id.startswith(_CORR_PREFIX):
389	            self._pending_corr_ids.discard(corr_id)
390	            return
391
392	        resp_type = resp.get("type") or event.get("type", "")
393
394	        # Auto-accept contact requests
395	        if resp_type == "contactRequest" and self.auto_accept:
396	            contact_req = resp.get("contactRequest", {}) or {}
397	            contact_req_id = contact_req.get("contactRequestId")
398	            if contact_req_id is not None:
399	                logger.info(
400	                    "SimpleX: auto-accepting contact request %s",
401	                    _redact_id(str(contact_req_id)),
402	                )
403	                await self._send_command(f"/accept {contact_req_id}")
404	            return
405
406	        # Early file-descriptor ready: simplex fires this before newChatItems
407	        # for some file types (especially large files and voice messages
408	        # transferred via XFTP). Send /freceive immediately so the download
409	        # starts; the chat item arrives in a subsequent newChatItems event.
410	        if resp_type == "rcvFileDescrReady":
411	            rcv_file = resp.get("rcvFileTransfer", {}) or {}
412	            file_id = rcv_file.get("fileId") if isinstance(rcv_file, dict) else None
413	            if file_id is not None:
414	                logger.debug(
415	                    "SimpleX: rcvFileDescrReady for fileId=%s — sending /freceive",
416	                    file_id,
417	                )
418	                await self._send_fire_and_forget(f"/freceive {file_id}")
419	            return
420
421	        # New messages — simplex-chat sends "newChatItems" with an array
422	        if resp_type == "newChatItems":
423	            chat_items = resp.get("chatItems", []) or []
424	            if not isinstance(chat_items, list):
425	                chat_items = [chat_items]
426	            for item in chat_items:
427	                try:
428	                    await self._handle_chat_item(item)
429	                except Exception:
430	                    logger.exception("SimpleX: error processing chat item")
431	            return
432
433	        # Singular variant — some daemon versions emit this
434	        if resp_type == "newChatItem":
435	            try:
436	                await self._handle_chat_item(resp)
437	            except Exception:
438	                logger.exception("SimpleX: error processing chat item")
439	            return
440
441	        # File transfer completion — deliver any deferred chat item
442	        if resp_type == "rcvFileComplete":
443	            chat_item = resp.get("chatItem", {}) or {}
444	            chat_item_data = chat_item.get("chatItem", {}) or {}
445	            file_info = chat_item_data.get("file", {}) or {}
446	            file_id = file_info.get("fileId") if isinstance(file_info, dict) else None
447	            if file_id is not None and file_id in self._pending_file_transfers:
448	                pending = self._pending_file_transfers.pop(file_id)
449	                file_source = file_info.get("fileSource", {}) or {}
450	                file_path = (
451	                    file_source.get("filePath")
452	                    if isinstance(file_source, dict)
453	                    else None
454	                )
455	                if file_path:
456	                    pending_item_data = pending.get("chatItem", {}) or {}
457	                    pending_item_data.setdefault("file", {})["fileSource"] = {
458	                        "filePath": file_path
459	                    }
460	                    pending["chatItem"] = pending_item_data
461	                    try:
462	                        await self._handle_chat_item(pending)
463	                    except Exception:
464	                        logger.exception(
465	                            "SimpleX: error processing deferred file message"

... (gap) ...

513	        if chat_type == "direct":
514	            contact = chat_info.get("contact", {}) or {}
515	            sender_id = str(contact.get("contactId", ""))
516	            sender_name = contact.get("localDisplayName", "") or contact.get(
517	                "profile", {}
518	            ).get("displayName", "")
519	            chat_id = sender_id
520	        elif chat_type == "group":
521	            group_info = chat_info.get("groupInfo", {}) or {}
522	            group_id = str(group_info.get("groupId", ""))
523	            chat_id = f"group:{group_id}"
524	            is_group = True
525
526	            member = item_direction.get("groupMember", {}) or {}
527	            sender_id = str(member.get("memberId", ""))
528	            sender_name = member.get("localDisplayName", "") or member.get(
529	                "memberProfile", {}
530	            ).get("displayName", "")
531
532	            # Group allowlist
533	            if self.group_allow_from:
534	                if (
535	                    "*" not in self.group_allow_from
536	                    and group_id not in self.group_allow_from
537	                ):
538	                    logger.debug(
539	                        "SimpleX: group %s not in allowlist",
540	                        _redact_id(group_id),
541	                    )
542	                    return
543	            else:

... (gap) ...

577
578	            # Voice notes typically arrive before the file finishes
579	            # downloading. Defer the message until rcvFileComplete fires.
580	            if not file_path and _is_audio_ext(ext) and file_id is not None:
581	                logger.info(
582	                    "SimpleX: voice file %d not yet received, accepting transfer",
583	                    file_id,
584	                )
585	                self._pending_file_transfers[file_id] = chat_item
586	                # Fire-and-forget: simplex-chat does not return a corrId reply
587	                # for /freceive, so awaiting one would block the event loop.
588	                await self._send_fire_and_forget(f"/freceive {file_id}")
589	                return
590
591	            if file_path:
592	                ext = Path(file_path).suffix.lower() or (
593	                    Path(file_name).suffix.lower() if file_name else ""
594	                )
595	                if _is_image_ext(ext):
596	                    media_urls.append(file_path)
597	                    media_types.append(f"image/{ext.lstrip('.')}")
598	                elif _is_audio_ext(ext):
599	                    media_urls.append(file_path)
600	                    media_types.append(f"audio/{ext.lstrip('.')}")
601	                else:
602	                    media_urls.append(file_path)
603	                    media_types.append("application/octet-stream")
604
605	        # Source
606	        chat_name = sender_name
607	        if is_group:
608	            group_info = chat_info.get("groupInfo", {}) or {}
609	            chat_name = group_info.get("localDisplayName", "") or group_info.get(
610	                "groupProfile", {}
611	            ).get("displayName", chat_id)
612
613	        source = self.build_source(
614	            chat_id=chat_id,
615	            chat_name=chat_name,
616	            chat_type="group" if is_group else "dm",

... (gap) ...

637	            if ts_str:
638	                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
639	            else:
640	                timestamp = datetime.now(tz=timezone.utc)
641	        except (ValueError, AttributeError):
642	            timestamp = datetime.now(tz=timezone.utc)
643
644	        msg_event = MessageEvent(
645	            source=source,
646	            text=text or "",
647	            message_type=msg_type,
648	            media_urls=media_urls,
649	            media_types=media_types,
650	            timestamp=timestamp,
651	            raw_message=chat_item,
652	        )
653
654	        logger.debug(
655	            "SimpleX: message from %s in %s: %s",
656	            _redact_id(sender_id),
657	            chat_id[:20],
658	            (text or "")[:50],
659	        )
660
661	        # Batch consecutive text messages so the agent sees one combined
662	        # message instead of dropping earlier ones when the user pastes
663	        # several lines in quick succession.
664	        if msg_type == MessageType.TEXT and text:
665	            self._enqueue_text_event(msg_event)
666	        else:
667	            await self.handle_message(msg_event)
668
669	    # ------------------------------------------------------------------
670	    # Text message batching
671	    # ------------------------------------------------------------------
672
673	    def _text_batch_key(self, event: MessageEvent) -> str:
674	        """Session-scoped key for text message batching."""
675	        return f"{event.source.platform.value}:{event.source.chat_id}"
676
677	    def _enqueue_text_event(self, event: MessageEvent) -> None:
678	        """Buffer a text event and reset the flush timer."""
679	        key = self._text_batch_key(event)
680	        existing = self._pending_text_batches.get(key)
681	        if existing is None:
682	            self._pending_text_batches[key] = event
683	        else:
684	            if event.text:
685	                existing.text = (
686	                    f"{existing.text}\n{event.text}" if existing.text else event.text
687	                )
688	            if event.media_urls:
689	                existing.media_urls.extend(event.media_urls)
690	                existing.media_types.extend(event.media_types)
691
692	        prior_task = self._pending_text_batch_tasks.get(key)
693	        if prior_task and not prior_task.done():
694	            prior_task.cancel()
695	        self._pending_text_batch_tasks[key] = asyncio.create_task(
696	            self._flush_text_batch(key)
697	        )
698
699	    async def _flush_text_batch(self, key: str) -> None:
700	        """Wait for the quiet period then dispatch the aggregated text."""
701	        current_task = asyncio.current_task()
702	        try:
703	            await asyncio.sleep(self._text_batch_delay)
704	            event = self._pending_text_batches.pop(key, None)
705	            if not event:
706	                return
707	            logger.info(
708	                "[SimpleX] Flushing text batch %s (%d chars)",
709	                key,
710	                len(event.text or ""),
711	            )
712	            await self.handle_message(event)
713	        finally:
714	            if self._pending_text_batch_tasks.get(key) is current_task:
715	                self._pending_text_batch_tasks.pop(key, None)
716
717	    # ------------------------------------------------------------------
718	    # Command interface

... (gap) ...

729	        """
730	        self._corr_counter += 1
731	        corr_id = f"{_CORR_PREFIX}{self._corr_counter}-{int(time.time() * 1000)}"
732	        self._pending_corr_ids.add(corr_id)
733	        if len(self._pending_corr_ids) > self._max_pending_corr:
734	            overflow = len(self._pending_corr_ids) - self._max_pending_corr
735	            for _ in range(overflow):
736	                try:
737	                    self._pending_corr_ids.pop()
738	                except KeyError:
739	                    break
740	        return corr_id
741
742	    async def _send_ws(self, payload: dict) -> None:
743	        """Fire-and-forget JSON payload write.
744
745	        Drops cleanly when the WebSocket is missing or already closed; the
746	        caller never has to handle reconnection — the ``_ws_listener``
747	        loop does that out of band.
748	        """
749	        ws = self._ws
750	        if not ws:
751	            logger.debug("SimpleX: WS send dropped (not connected)")
752	            return
753	        try:
754	            await ws.send(json.dumps(payload))
755	        except Exception as e:
756	            logger.warning("SimpleX: WS send error: %s", e)
757
758	    async def _send_command(
759	        self, command: str, timeout: float = 30.0
760	    ) -> Optional[dict]:
761	        """Send a command and await the correlated response."""
762	        ws = self._ws
763	        if not ws:
764	            logger.warning("SimpleX: command sent but WebSocket not connected")
765	            return None
766
767	        corr_id = self._make_corr_id()
768	        payload = json.dumps({"corrId": corr_id, "cmd": command})
769
770	        loop = asyncio.get_event_loop()
771	        fut: asyncio.Future = loop.create_future()
772	        self._pending_responses[corr_id] = fut
773
774	        try:
775	            await ws.send(payload)
776	            result = await asyncio.wait_for(fut, timeout=timeout)
777	            return result
778	        except asyncio.TimeoutError:
779	            logger.warning("SimpleX: command timed out: %s", command[:50])
780	            self._pending_responses.pop(corr_id, None)
781	            return None
782	        except Exception as e:
783	            logger.warning("SimpleX: command failed: %s — %s", command[:50], e)
784	            self._pending_responses.pop(corr_id, None)
785	            return None
786
787	    async def _send_fire_and_forget(self, command: str) -> None:
788	        """Send a command without waiting for a correlated response.
789
790	        Use this for commands the daemon never sends a corrId reply for,
791	        such as ``/freceive``. Awaiting a corr-id reply on those would
792	        stall the event loop for the full command timeout.
793	        """
794	        corr_id = self._make_corr_id()
795	        await self._send_ws({"corrId": corr_id, "cmd": command})
796
797	    # ------------------------------------------------------------------
798	    # Outbound — text

... (gap) ...

826	        _voice_exts = {".ogg", ".mp3", ".wav", ".m4a", ".opus"}
827	        media_paths = re.findall(r"MEDIA:(\S+)", content)
828	        if media_paths:
829	            content = re.sub(r"MEDIA:\S+", "", content).strip()
830
831	        if content:
832	            corr_id = self._make_corr_id()
833	            # Structured form: addresses by ID, and json.dumps escapes
834	            # newlines + special chars correctly.  The bare @id text
835	            # syntax is unreliable for DMs — the daemon silently drops
836	            # messages when it cannot resolve the display name.
837	            composed = json.dumps(
838	                [{"msgContent": {"type": "text", "text": content}}]
839	            )
840	            if chat_id.startswith("group:"):
841	                cmd_str = f"/_send #{chat_id[6:]} json {composed}"
842	            else:
843	                cmd_str = f"/_send @{chat_id} json {composed}"
844
845	            await self._send_ws({"corrId": corr_id, "cmd": cmd_str})
846
847	        for path in media_paths:
848	            is_voice = os.path.splitext(path)[1].lower() in _voice_exts
849	            if is_voice:
850	                media_result = await self.send_voice(chat_id, path)
851	            else:
852	                media_result = await self.send_document(chat_id, path)
853	            if not media_result.success:
854	                return media_result
855
856	        return SendResult(success=True)
857
858	    # ------------------------------------------------------------------
859	    # Channel directory enumeration
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.
