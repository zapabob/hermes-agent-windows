**Exploration: plugins/platforms/email/adapter.py**

Found 59 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/email/adapter.py`** — calls(calls), _get_secret(calls), instantiates(instantiates), _safe_decode(calls), _domain_of(calls), _connect_smtp(calls), references(references), _domains_aligned(calls), _decode_header_value(calls), _esecret_int(calls), _trim_seen_uids(calls), _message_id_domain(calls), _get_esecret(calls), _get_socket(method), _create_ipv4_connection(calls), +80 more

```python
49	from gateway.config import Platform, PlatformConfig
50	from utils import is_truthy_value
51
52	logger = logging.getLogger(__name__)
53
54
55	def _get_esecret(name: str, default: str = "") -> str:

... (gap) ...

72
73
74	# Backwards-compatible alias for the name used by the original #59076 hunks.
75	_get_secret = _get_esecret
76
77
78	def _esecret_int(name: str, default: int) -> int:
79	    """Scope-aware integer read (``env_int`` variant of ``_get_esecret``)."""
80	    raw = str(_get_esecret(name, "")).strip()
81	    if not raw:
82	        return default
83	    try:
84	        return int(raw)
85	    except (ValueError, TypeError):
86	        return default
87
88
89	def _esecret_bool(name: str, default: bool = False) -> bool:
90	    """Scope-aware boolean read (``env_bool`` variant of ``_get_esecret``)."""
91	    return is_truthy_value(_get_esecret(name, ""), default=default)
92
93
94	# Automated sender patterns — emails from these are silently ignored
95	_NOREPLY_PATTERNS = (
96	    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
97	    "mailer-daemon", "postmaster", "bounce", "notifications@",
98	    "automated@", "auto-confirm", "auto-reply", "automailer",
99	)
100
101	# RFC headers that indicate bulk/automated mail
102	_AUTOMATED_HEADERS = {
103	    "Auto-Submitted": lambda v: v.lower() != "no",
104	    "Precedence": lambda v: v.lower() in {"bulk", "list", "junk"},
105	    "X-Auto-Response-Suppress": lambda v: bool(v),
106	    "List-Unsubscribe": lambda v: bool(v),
107	}
108
109	# Gmail-safe max length per email body
110	MAX_MESSAGE_LENGTH = 50_000
111
112	SMTP_CONNECT_TIMEOUT = 30
113
114
115	def _close_imap(imap: "imaplib.IMAP4") -> None:

... (gap) ...

165	    raise OSError(f"No IPv4 address found for {host}:{port}")
166
167
168	class _IPv4SMTP(smtplib.SMTP):
169	    def _get_socket(self, host, port, timeout):  # type: ignore[override]
170	        return _create_ipv4_connection(
171	            host,
172	            port,
173	            timeout,
174	            source_address=self.source_address,
175	        )
176
177
178	class _IPv4SMTP_SSL(smtplib.SMTP_SSL):
179	    def _get_socket(self, host, port, timeout):  # type: ignore[override]
180	        raw_sock = _create_ipv4_connection(
181	            host,
182	            port,
183	            timeout,
184	            source_address=self.source_address,
185	        )
186	        return self.context.wrap_socket(
187	            raw_sock,
188	            server_hostname=getattr(self, "_host", host),
189	        )
190
191	# Supported image extensions for inline detection
192	_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
193
194	def _send_imap_id(imap: "imaplib.IMAP4") -> None:
195	    """Send RFC 2971 IMAP ID command identifying this client.

... (gap) ...

214	        logger.debug("[Email] IMAP ID command not accepted: %s", e)
215
216
217	def _is_automated_sender(address: str, headers: dict) -> bool:
218	    """Return True if this email is from an automated/noreply source."""
219	    addr = address.lower()
220	    if any(pattern in addr for pattern in _NOREPLY_PATTERNS):
221	        return True
222	    for header, check in _AUTOMATED_HEADERS.items():
223	        value = headers.get(header, "")
224	        if value and check(value):
225	            return True
226	    return False
227
228	def check_email_requirements() -> bool:
229	    """Check if email platform settings are available and non-blank.
230
231	    Treats blank/whitespace-only values as missing so an abandoned setup that
232	    left empty ``EMAIL_*`` keys in ``.env`` does not enable the platform (#40715).
233	    """
234	    addr = _get_secret("EMAIL_ADDRESS", "").strip()
235	    pwd = _get_secret("EMAIL_PASSWORD", "").strip()
236	    imap = _get_secret("EMAIL_IMAP_HOST", "").strip()
237	    smtp = _get_secret("EMAIL_SMTP_HOST", "").strip()
238	    return all([addr, pwd, imap, smtp])
239
240

... (gap) ...

264	    message in the batch (#35901, #55381, #55383). Fall back through a small
265	    alias table, then UTF-8, then latin-1 (which never fails).
266	    """
267	    label = (charset or "utf-8").strip().strip("\"'").lower() or "utf-8"
268	    label = _CHARSET_ALIASES.get(label, label)
269	    for candidate in (label, "utf-8"):
270	        try:

... (gap) ...

287	    decoded = []
288	    for part, charset in parts:
289	        if isinstance(part, bytes):
290	            decoded.append(_safe_decode(part, charset))
291	        else:
292	            decoded.append(part)
293	    return " ".join(decoded)

... (gap) ...

305	            if content_type == "text/plain":
306	                payload = part.get_payload(decode=True)
307	                if payload:
308	                    return _safe_decode(payload, part.get_content_charset())
309	        # Fallback: try text/html and strip tags
310	        for part in msg.walk():
311	            content_type = part.get_content_type()
312	            disposition = str(part.get("Content-Disposition", ""))
313	            if "attachment" in disposition:
314	                continue
315	            if content_type == "text/html":
316	                payload = part.get_payload(decode=True)
317	                if payload:
318	                    html = _safe_decode(payload, part.get_content_charset())
319	                    return _strip_html(html)
320	        return ""
321	    else:
322	        payload = msg.get_payload(decode=True)
323	        if payload:
324	            text = _safe_decode(payload, msg.get_content_charset())
325	            if msg.get_content_type() == "text/html":
326	                return _strip_html(text)
327	            return text
328	        return ""
329
330
331	def _strip_html(html: str) -> str:
332	    """Naive HTML tag stripper for fallback text extraction."""
333	    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
334	    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
335	    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
336	    text = re.sub(r"<[^>]+>", "", text)
337	    text = re.sub(r"&nbsp;", " ", text)
338	    text = re.sub(r"&amp;", "&", text)
339	    text = re.sub(r"&lt;", "<", text)
340	    text = re.sub(r"&gt;", ">", text)
341	    text = re.sub(r"\n{3,}", "\n\n", text)
342	    return text.strip()
343
344
345	def _extract_email_address(raw: str) -> str:
346	    """Extract bare email address from 'Name <addr>' format."""
347	    match = re.search(r"<([^>]+)>", raw)
348	    if match:
349	        return match.group(1).strip().lower()
350	    return raw.strip().lower()
351
352
353	def _domain_of(address: str) -> str:
354	    """Return the lowercased domain part of an email address, or ''."""
355	    _, _, domain = address.rpartition("@")
356	    return domain.strip().lower()
357
358
359	def _domains_aligned(a: str, b: str) -> bool:
360	    """Return True if two domains are equal or in an organizational
361	    parent/subdomain relationship (relaxed DMARC alignment).
362
363	    DMARC relaxed alignment treats ``mail.example.com`` as aligned with
364	    ``example.com``. We approximate organizational alignment by checking
365	    exact equality or that one domain is a dot-suffix of the other.
366	    """
367	    a = (a or "").strip().lower().rstrip(".")
368	    b = (b or "").strip().lower().rstrip(".")
369	    if not a or not b:
370	        return False
371	    if a == b:
372	        return True
373	    return a.endswith("." + b) or b.endswith("." + a)
374
375
376	# Match a single "method=result" token in an Authentication-Results header,
377	# e.g. ``dmarc=pass`` or ``spf=fail``.
378	_AUTH_METHOD_RE = re.compile(
379	    r"\b(dmarc|dkim|spf)\s*=\s*([a-z]+)", re.IGNORECASE
380	)
381	# Match a property value like ``header.from=example.com`` or
382	# ``smtp.mailfrom=user@example.com``.
383	_AUTH_PROP_RE = re.compile(
384	    r"\b(header\.from|header\.d|smtp\.mailfrom|smtp\.from|envelope-from)\s*=\s*([^\s;]+)",
385	    re.IGNORECASE,
386	)
387
388
389	def _verify_sender_authentication(

... (gap) ...

413	    whose mail server does not stamp this header can opt out of the check
414	    (see ``EmailAdapter._require_authenticated_sender``).
415	    """
416	    from_domain = _domain_of(from_addr)
417	    if not from_domain:
418	        return False, "missing From domain"
419
420	    # get_all preserves header order; the receiving server prepends its result,
421	    # so the FIRST Authentication-Results is the trusted one. We pin to the
422	    # configured authserv-id when provided to defend against an injected header
423	    # that happens to sort first.
424	    headers = msg.get_all("Authentication-Results") or []
425	    if not headers:
426	        return False, "no Authentication-Results header"
427
428	    trusted = None
429	    for raw in headers:
430	        value = " ".join(str(raw).split())
431	        if authserv_id:
432	            # authserv-id is the first token before the first ';'
433	            serv = value.split(";", 1)[0].strip().lower()
434	            if not _domains_aligned(serv, authserv_id) and serv != authserv_id.lower():
435	                continue
436	        trusted = value
437	        break
438	    if trusted is None:
439	        return False, "no Authentication-Results from trusted authserv-id"
440
441	    methods = {m.lower(): r.lower() for m, r in _AUTH_METHOD_RE.findall(trusted)}
442	    props = {p.lower(): v.strip().strip('"') for p, v in _AUTH_PROP_RE.findall(trusted)}
443
444	    # 1) DMARC pass is the strongest signal — DMARC already enforces From
445	    #    alignment, so a pass means the From domain is authenticated.
446	    if methods.get("dmarc") == "pass":
447	        return True, "dmarc=pass"
448
449	    # 2) SPF pass aligned with the From domain (the envelope/MAIL FROM domain
450	    #    must match the From domain).
451	    if methods.get("spf") == "pass":
452	        spf_domain = _domain_of(props.get("smtp.mailfrom", "")) or props.get(
453	            "smtp.from", ""
454	        ) or props.get("envelope-from", "")
455	        spf_domain = _domain_of(spf_domain) if "@" in spf_domain else spf_domain
456	        if _domains_aligned(spf_domain, from_domain):
457	            return True, "spf=pass aligned"
458
459	    # 3) DKIM pass aligned with the From domain (the signing domain header.d
460	    #    must align with the From domain).
461	    if methods.get("dkim") == "pass":
462	        dkim_domain = props.get("header.d", "") or _domain_of(props.get("header.from", ""))
463	        if _domains_aligned(dkim_domain, from_domain):
464	            return True, "dkim=pass aligned"
465
466	    return False, f"authentication failed ({trusted[:120]})"

... (gap) ...

492
493	        filename = part.get_filename()
494	        if filename:
495	            filename = _decode_header_value(filename)
496	        else:
497	            ext = part.get_content_subtype() or "bin"
498	            filename = f"attachment.{ext}"
499
500	        payload = part.get_payload(decode=True)
501	        if not payload:
502	            continue
503
504	        ext = Path(filename).suffix.lower()
505	        if ext in _IMAGE_EXTS:
506	            try:
507	                cached_path = cache_image_from_bytes(payload, ext)
508	            except ValueError:
509	                logger.debug("Skipping non-image attachment %s (invalid magic bytes)", filename)
510	                continue
511	            attachments.append({
512	                "path": cached_path,
513	                "filename": filename,
514	                "type": "image",
515	                "media_type": content_type,
516	            })
517	        else:
518	            cached_path = cache_document_from_bytes(payload, filename)
519	            attachments.append({
520	                "path": cached_path,
521	                "filename": filename,
522	                "type": "document",
523	                "media_type": content_type,
524	            })
525
526	    return attachments
527
528
529	class EmailAdapter(BasePlatformAdapter):
530	    """Email gateway adapter using IMAP (receive) and SMTP (send)."""
531
532	    # Per-account snapshot of seen UIDs, surviving adapter recreation.

... (gap) ...

550	        # misleading ``[Errno 8] nodename nor servname`` (an unresolvable name)
551	        # instead of an obvious "host not set" error.
552	        extra = config.extra or {}
553	        self._address = (_get_secret("EMAIL_ADDRESS", "") or extra.get("address", "")).strip()
554	        self._password = _get_secret("EMAIL_PASSWORD", "")
555	        self._imap_host = (_get_secret("EMAIL_IMAP_HOST", "") or extra.get("imap_host", "")).strip()
556	        self._imap_port = _esecret_int("EMAIL_IMAP_PORT", 993)
557	        self._smtp_host = (_get_secret("EMAIL_SMTP_HOST", "") or extra.get("smtp_host", "")).strip()
558	        self._smtp_port = _esecret_int("EMAIL_SMTP_PORT", 587)
559	        self._poll_interval = _esecret_int("EMAIL_POLL_INTERVAL", 15)
560
561	        # Skip attachments — configured via config.yaml:
562	        #   platforms:

... (gap) ...

580	        # gate below is skipped.
581	        if "require_authenticated_sender" in extra:
582	            self._require_authenticated_sender = bool(extra["require_authenticated_sender"])
583	        elif _esecret_bool("EMAIL_TRUST_FROM_HEADER", False):
584	            self._require_authenticated_sender = False
585	        else:
586	            self._require_authenticated_sender = True
587
588	        # Optional authserv-id to pin Authentication-Results to the operator's
589	        # own receiving server (defends against an injected header that sorts
590	        # first). Defaults to the From-domain of the agent's own address.
591	        self._authserv_id = (
592	            extra.get("authserv_id", "") or _get_secret("EMAIL_AUTHSERV_ID", "")
593	        ).strip().lower()
594
595	        # Track message IDs we've already processed to avoid duplicates

... (gap) ...

654	                return smtp_ssl_cls(host, port, timeout=SMTP_CONNECT_TIMEOUT, context=ctx)
655	            smtp = smtp_cls(host, port, timeout=SMTP_CONNECT_TIMEOUT)
656	            try:
657	                smtp.starttls(context=ctx)
658	            except Exception:
659	                smtp.close()
660	                raise
661	            return smtp
662
663	        try:
664	            return _connect()
665	        except (socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
666	            if isinstance(exc, ssl.SSLError):
667	                raise
668	            # Connection-level failure (may be unreachable IPv6).
669	            # Retry with IPv4 only.
670	            return _connect(ipv4_only=True)
671
672	    async def connect(self, *, is_reconnect: bool = False) -> bool:
673	        """Connect to the IMAP server and start polling for new messages."""

... (gap) ...

696	            # an empty host. A blank-but-present env var (e.g. ``EMAIL_IMAP_HOST=``)
697	            # used to slip past the startup gate and drive an indefinite retry
698	            # loop that leaked memory until the host OOM-killed (#40715).
699	            self._set_fatal_error(
700	                "email_missing_configuration", message, retryable=False
701	            )
702	            return False

... (gap) ...

713	            try:
714	                imap = imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=30)
715	                imap.login(self._address, self._password)
716	                _send_imap_id(imap)
717	                imap.select("INBOX")
718	                snapshot = self._seen_uids_snapshot.get(self._address)
719	                if is_reconnect and snapshot is not None:
720	                    # Reconnect within the same process: restore the previous
721	                    # adapter's seen-UID baseline instead of re-marking the whole
722	                    # mailbox. Mail that arrived during the outage stays UNSEEN
723	                    # relative to the baseline and is dispatched by the next poll
724	                    # instead of being silently skipped.
725	                    self._seen_uids = set(snapshot)
726	                    self._trim_seen_uids()
727	                    logger.info(
728	                        "[Email] IMAP reconnect test passed. Restored %d seen UIDs; "
729	                        "messages received during the outage will be processed.",
730	                        len(self._seen_uids),
731	                    )
732	                else:
733	                    # First connect (or no snapshot): mark all existing messages as
734	                    # seen so we only process new ones.
735	                    status, data = imap.uid("search", None, "ALL")
736	                    if status == "OK" and data and data[0]:
737	                        for uid in data[0].split():
738	                            self._seen_uids.add(uid)
739	                    # Keep only the most recent UIDs to prevent unbounded growth
740	                    self._trim_seen_uids()
741	                    logger.info("[Email] IMAP connection test passed. %d existing messages skipped.", len(self._seen_uids))
742	            finally:
743	                if imap is not None:
744	                    _close_imap(imap)
745	            self._seen_uids_snapshot[self._address] = set(self._seen_uids)
746	        except Exception as e:
747	            logger.error("[Email] IMAP connection failed: %s", e)
748	            # Always set an explicit fatal code (OOF-156): returning False
749	            # with no error info made the gateway treat every IMAP failure —
750	            # including permanently bad credentials — as transient, retrying
751	            # forever with zero owner signal ("stuck retrying 22h").
752	            # Kept retryable=True deliberately: imaplib raises the same
753	            # generic IMAP4.error for bad credentials AND transient server
754	            # NOs (e.g. Gmail's "too many simultaneous connections"), so a
755	            # type-based terminal classification isn't safe here. Long-lived
756	            # loops surface via the reconnect watcher's NEEDS_ATTENTION
757	            # escalation instead.
758	            self._set_fatal_error(
759	                "email_imap_connect_error",
760	                f"IMAP connection to {self._imap_host}:{self._imap_port} failed: {e}",
761	                retryable=True,
762	            )
763	            return False
764
765	        try:
766	            # Test SMTP connection
767	            smtp = self._connect_smtp()
768	            try:
769	                smtp.login(self._address, self._password)
770	            finally:
771	                smtp.quit()
772	            logger.info("[Email] SMTP connection test passed.")
773	        except smtplib.SMTPAuthenticationError as e:
774	            logger.error("[Email] SMTP authentication failed: %s", e)
775	            # Typed auth failure (535 & friends): bad or revoked credentials
776	            # can never self-heal, so drop out of the reconnect queue instead
777	            # of retrying a dead password forever (OOF-156). Type-based only —
778	            # SMTPAuthenticationError is unambiguous, unlike IMAP4.error above.
779	            self._set_fatal_error(
780	                "email_auth_error",
781	                f"SMTP authentication failed for {self._address}: {e}. "
782	                "Check EMAIL_PASSWORD (for Gmail/Outlook this must be an "
783	                "app password, not the account password).",
784	                retryable=False,
785	            )
786	            return False
787	        except Exception as e:
788	            logger.error("[Email] SMTP connection failed: %s", e)
789	            self._set_fatal_error(
790	                "email_smtp_connect_error",
791	                f"SMTP connection to {self._smtp_host} failed: {e}",
792	                retryable=True,
793	            )
794	            return False
795
796	        self._running = True
797	        self._poll_task = asyncio.create_task(self._poll_loop())
798	        print(f"[Email] Connected as {self._address}")
799	        # Plugin-registered native handlers (ctx.register_platform_handler).
800	        self._wire_plugin_handlers(None)
801	        return True
802
803	    async def disconnect(self) -> None:
804	        """Stop polling and disconnect."""
805	        self._running = False
806	        if self._poll_task:
807	            self._poll_task.cancel()
808	            try:
809	                await self._poll_task
810	            except asyncio.CancelledError:
811	                pass
812	            self._poll_task = None
813	        logger.info("[Email] Disconnected.")
814
815	    async def _poll_loop(self) -> None:
816	        """Poll IMAP for new messages at regular intervals."""
817	        while self._running:
818	            try:
819	                await self._check_inbox()
820	            except asyncio.CancelledError:
821	                break
822	            except Exception as e:
823	                logger.error("[Email] Poll error: %s", e)
824	            await asyncio.sleep(self._poll_interval)
825
826	    async def _check_inbox(self) -> None:
827	        """Check INBOX for unseen messages and dispatch them."""
828	        # Run IMAP operations in a thread to avoid blocking the event loop
829	        loop = asyncio.get_running_loop()
830	        messages = await loop.run_in_executor(None, self._fetch_new_messages)
831	        # Dispatch whatever the fetch managed to return BEFORE escalating a
832	        # failure: on a mid-batch exception _fetch_new_messages returns the
833	        # partial results, and dropping them here would lose those messages
834	        # (their processing already marked them seen).
835	        for msg_data in messages:
836	            await self._dispatch_message(msg_data)
837	        if self._last_fetch_failed:
838	            # The IMAP check itself failed (connect/login/select/search/fetch),
839	            # not just an empty inbox. Surface it through the fatal-error hook
840	            # so the gateway's existing reconnect/backoff/status machinery
841	            # re-establishes the mailbox instead of silently treating every
842	            # failed check as "nothing new" (#80016). The handler runs in a
843	            # detached task (gateway/run.py), so awaiting it from our own poll
844	            # task is safe even though teardown cancels this task.
845	            self._last_fetch_failed = False
846	            self._set_fatal_error(
847	                "email_imap_fetch_failed",
848	                self._last_fetch_error or "IMAP fetch failed",
849	                retryable=True,
850	            )
851	            await self._notify_fatal_error()
852
853	    def _fetch_new_messages(self) -> List[Dict[str, Any]]:
854	        """Fetch new (unseen) messages from IMAP. Runs in executor thread."""
855	        results = []
856	        imap: Optional[imaplib.IMAP4] = None
857	        try:
858	            imap = imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=30)
859	            try:
860	                imap.login(self._address, self._password)
861	                _send_imap_id(imap)
862	                imap.select("INBOX")
863
864	                status, data = imap.uid("search", None, "UNSEEN")
865	                if status != "OK" or not data or not data[0]:
866	                    return results
867
868	                for uid in data[0].split():
869	                    if uid in self._seen_uids:
870	                        continue
871
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.
