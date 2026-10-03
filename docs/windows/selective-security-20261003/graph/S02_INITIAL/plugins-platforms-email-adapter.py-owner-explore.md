**Exploration: plugins/platforms/email/adapter.py**

Found 63 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/email/adapter.py`** — calls(calls), _get_secret(calls), references(references), instantiates(instantiates), _safe_decode(calls), _connect_smtp(calls), aligned(calls), _decode_header_value(calls), _esecret_int(calls), _trim_seen_uids(calls), _message_id_domain(calls), _get_esecret(calls), _get_socket(method), _create_ipv4_connection(calls), _strip_html(calls), +87 more

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
353	def _ar_clauses(text: str) -> Optional[List[str]]:
354	    """Split an Authentication-Results value on ``;`` outside quoted-strings and (nested) comments; comments are
355	    dropped, quoted-strings kept (``header.from="x"`` stays readable). ``None`` when a quote or comment is unbalanced."""
356	    clauses, cur, depth, quoted, i = [], [], 0, False, 0
357	    while i < len(text):
358	        c = text[i]
359	        if c == "\\" and (quoted or depth):
360	            if quoted:

... (gap) ...

384	    return None if quoted or depth else clauses + ["".join(cur)]
385
386
387	def _auth_props(text: str) -> List[Tuple[str, str]]:
388	    """``(property, value)`` pairs (``header.from=x``) of one comment-free Authentication-Results clause, property
389	    lowercased, surrounding quotes stripped. Quoted-string contents are never scanned for properties."""
390	    return [(p.lower(), v.strip('"')) for p, v in _AUTH_PROP_RE.findall(text) if p]
391
392
393	def _domain_of(address: str) -> str:
394	    """Return the lowercased domain part of an email address, or ''."""
395	    _, _, domain = address.rpartition("@")
396	    return domain.strip().lower()
397
398
399	def _domains_aligned(a: str, b: str) -> bool:
400	    """Return True if two domains are equal or in an organizational
401	    parent/subdomain relationship (relaxed DMARC alignment).
402
403	    DMARC relaxed alignment treats ``mail.example.com`` as aligned with
404	    ``example.com``. We approximate organizational alignment by checking
405	    exact equality or that one domain is a dot-suffix of the other.
406	    """
407	    a = (a or "").strip().lower().rstrip(".")
408	    b = (b or "").strip().lower().rstrip(".")
409	    if not a or not b:
410	        return False
411	    if a == b:
412	        return True
413	    return a.endswith("." + b) or b.endswith("." + a)
414
415
416	# Authentication-Results clause head (``dmarc=pass``), matched only at the start of a clause.
417	_AUTH_METHOD_RE = re.compile(r"\s*(dmarc|dkim|spf)\s*=\s*([a-z]+)(?=\s|$)", re.IGNORECASE)
418	# One token of a clause: a property we read (``header.from=x``; the value may be or contain a quoted-string), or
419	# any other whitespace-delimited token consumed whole, so text inside quotes or other values is never read as a prop.
420	_QUOTED = r'"(?:[^"\\]|\\.)*"'
421	_AUTH_PROP_RE = re.compile(r'(header\.from|header\.d|smtp\.mailfrom|smtp\.from|envelope-from)\s*=\s*((?:%s|[^\s";])+)'
422	                           r'|(?:%s|[^\s"])+' % (_QUOTED, _QUOTED), re.IGNORECASE)
423
424
425	def _verify_sender_authentication(

... (gap) ...

449	    whose mail server does not stamp this header can opt out of the check
450	    (see ``EmailAdapter._require_authenticated_sender``).
451	    """
452	    from_domain = _domain_of(from_addr)
453	    if not from_domain:
454	        return False, "missing From domain"
455
456	    # get_all preserves header order; the receiving server prepends its result,
457	    # so the FIRST Authentication-Results is the trusted one. We pin to the
458	    # configured authserv-id when provided to defend against an injected header
459	    # that happens to sort first.
460	    headers = msg.get_all("Authentication-Results") or []
461	    if not headers:
462	        return False, "no Authentication-Results header"
463
464	    trusted = None
465	    for raw in headers:
466	        value = " ".join(str(raw).split())
467	        if authserv_id:
468	            # authserv-id is the first token before the first ';'
469	            serv = value.split(";", 1)[0].strip().lower()
470	            if not _domains_aligned(serv, authserv_id) and serv != authserv_id.lower():
471	                continue
472	        trusted = value
473	        break
474	    if trusted is None:
475	        return False, "no Authentication-Results from trusted authserv-id"
476
477	    # Each verdict comes from the head of its own clause (split outside quotes/comments) and its domains only from that
478	    # clause: a quoted local part or comment can otherwise smuggle ``spf=pass``/``header.d=`` (GHSA-rxqh-5572-8m77).
479	    if (clauses := _ar_clauses(trusted)) is None:
480	        return False, "unbalanced quote or comment in Authentication-Results"
481	    results: Dict[str, List[Tuple[str, List[Tuple[str, str]]]]] = {"dmarc": [], "spf": [], "dkim": []}
482	    for clause in clauses:
483	        if m := _AUTH_METHOD_RE.match(clause):
484	            results[m.group(1).lower()].append((m.group(2).lower(), _auth_props(clause)))
485
486	    def aligned(props: List[Tuple[str, str]], names: Tuple[str, ...], *, required: bool = True) -> bool:
487	        domains = [_domain_of(v) for p, v in props if p in names]
488	        return (bool(domains) or not required) and all(_domains_aligned(d, from_domain) for d in domains)
489
490	    if len(results["dmarc"]) > 1:
491	        return False, "ambiguous dmarc result"
492	    # every header.from in the dmarc clause must be the From domain we parsed (absent header.from: trust the verdict)
493	    if any(r == "pass" and aligned(props, ("header.from",), required=False) for r, props in results["dmarc"]):
494	        return True, "dmarc=pass"
495	    # one SMTP transaction has one MAIL FROM verdict: a second spf clause means the SPF signal is not trusted
496	    if len(results["spf"]) == 1 and (spf := results["spf"][0])[0] == "pass" and aligned(
497	            spf[1], ("smtp.mailfrom", "smtp.from", "envelope-from")):
498	        return True, "spf=pass aligned"
499	    # several dkim clauses are normal (one per signature): any single pass whose own header.d aligns is enough
500	    if any(r == "pass" and aligned(props, ("header.d",) if any(p == "header.d" for p, _ in props) else ("header.from",))
501	           for r, props in results["dkim"]):
502	        return True, "dkim=pass aligned"
503	    return False, f"authentication failed ({trusted[:120]})"

... (gap) ...

529
530	        filename = part.get_filename()
531	        if filename:
532	            filename = _decode_header_value(filename)
533	        else:
534	            ext = part.get_content_subtype() or "bin"
535	            filename = f"attachment.{ext}"
536
537	        payload = part.get_payload(decode=True)
538	        if not payload:
539	            continue
540
541	        ext = Path(filename).suffix.lower()
542	        if ext in _IMAGE_EXTS:
543	            try:
544	                cached_path = cache_image_from_bytes(payload, ext)
545	            except ValueError:
546	                logger.debug("Skipping non-image attachment %s (invalid magic bytes)", filename)
547	                continue
548	            attachments.append({
549	                "path": cached_path,
550	                "filename": filename,
551	                "type": "image",
552	                "media_type": content_type,
553	            })
554	        else:
555	            cached_path = cache_document_from_bytes(payload, filename)
556	            attachments.append({
557	                "path": cached_path,
558	                "filename": filename,
559	                "type": "document",
560	                "media_type": content_type,
561	            })
562
563	    return attachments
564
565
566	class EmailAdapter(BasePlatformAdapter):
567	    """Email gateway adapter using IMAP (receive) and SMTP (send)."""
568
569	    # Per-account snapshot of seen UIDs, surviving adapter recreation.

... (gap) ...

587	        # misleading ``[Errno 8] nodename nor servname`` (an unresolvable name)
588	        # instead of an obvious "host not set" error.
589	        extra = config.extra or {}
590	        self._address = (_get_secret("EMAIL_ADDRESS", "") or extra.get("address", "")).strip()
591	        self._password = _get_secret("EMAIL_PASSWORD", "")
592	        self._imap_host = (_get_secret("EMAIL_IMAP_HOST", "") or extra.get("imap_host", "")).strip()
593	        self._imap_port = _esecret_int("EMAIL_IMAP_PORT", 993)
594	        self._smtp_host = (_get_secret("EMAIL_SMTP_HOST", "") or extra.get("smtp_host", "")).strip()
595	        self._smtp_port = _esecret_int("EMAIL_SMTP_PORT", 587)
596	        self._poll_interval = _esecret_int("EMAIL_POLL_INTERVAL", 15)
597
598	        # Skip attachments — configured via config.yaml:
599	        #   platforms:

... (gap) ...

617	        # gate below is skipped.
618	        if "require_authenticated_sender" in extra:
619	            self._require_authenticated_sender = bool(extra["require_authenticated_sender"])
620	        elif _esecret_bool("EMAIL_TRUST_FROM_HEADER", False):
621	            self._require_authenticated_sender = False
622	        else:
623	            self._require_authenticated_sender = True
624
625	        # Optional authserv-id to pin Authentication-Results to the operator's
626	        # own receiving server (defends against an injected header that sorts
627	        # first). Defaults to the From-domain of the agent's own address.
628	        self._authserv_id = (
629	            extra.get("authserv_id", "") or _get_secret("EMAIL_AUTHSERV_ID", "")
630	        ).strip().lower()
631
632	        # Track message IDs we've already processed to avoid duplicates

... (gap) ...

691	                return smtp_ssl_cls(host, port, timeout=SMTP_CONNECT_TIMEOUT, context=ctx)
692	            smtp = smtp_cls(host, port, timeout=SMTP_CONNECT_TIMEOUT)
693	            try:
694	                smtp.starttls(context=ctx)
695	            except Exception:
696	                smtp.close()
697	                raise
698	            return smtp
699
700	        try:
701	            return _connect()
702	        except (socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
703	            if isinstance(exc, ssl.SSLError):
704	                raise
705	            # Connection-level failure (may be unreachable IPv6).
706	            # Retry with IPv4 only.
707	            return _connect(ipv4_only=True)
708
709	    async def connect(self, *, is_reconnect: bool = False) -> bool:
710	        """Connect to the IMAP server and start polling for new messages."""

... (gap) ...

733	            # an empty host. A blank-but-present env var (e.g. ``EMAIL_IMAP_HOST=``)
734	            # used to slip past the startup gate and drive an indefinite retry
735	            # loop that leaked memory until the host OOM-killed (#40715).
736	            self._set_fatal_error(
737	                "email_missing_configuration", message, retryable=False
738	            )
739	            return False

... (gap) ...

750	            try:
751	                imap = imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=30)
752	                imap.login(self._address, self._password)
753	                _send_imap_id(imap)
754	                imap.select("INBOX")
755	                snapshot = self._seen_uids_snapshot.get(self._address)
756	                if is_reconnect and snapshot is not None:
757	                    # Reconnect within the same process: restore the previous
758	                    # adapter's seen-UID baseline instead of re-marking the whole
759	                    # mailbox. Mail that arrived during the outage stays UNSEEN
760	                    # relative to the baseline and is dispatched by the next poll
761	                    # instead of being silently skipped.
762	                    self._seen_uids = set(snapshot)
763	                    self._trim_seen_uids()
764	                    logger.info(
765	                        "[Email] IMAP reconnect test passed. Restored %d seen UIDs; "
766	                        "messages received during the outage will be processed.",
767	                        len(self._seen_uids),
768	                    )
769	                else:
770	                    # First connect (or no snapshot): mark all existing messages as
771	                    # seen so we only process new ones.
772	                    status, data = imap.uid("search", None, "ALL")
773	                    if status == "OK" and data and data[0]:
774	                        for uid in data[0].split():
775	                            self._seen_uids.add(uid)
776	                    # Keep only the most recent UIDs to prevent unbounded growth
777	                    self._trim_seen_uids()
778	                    logger.info("[Email] IMAP connection test passed. %d existing messages skipped.", len(self._seen_uids))
779	            finally:
780	                if imap is not None:
781	                    _close_imap(imap)
782	            self._seen_uids_snapshot[self._address] = set(self._seen_uids)
783	        except Exception as e:
784	            logger.error("[Email] IMAP connection failed: %s", e)
785	            # Always set an explicit fatal code (OOF-156): returning False
786	            # with no error info made the gateway treat every IMAP failure —
787	            # including permanently bad credentials — as transient, retrying
788	            # forever with zero owner signal ("stuck retrying 22h").
789	            # Kept retryable=True deliberately: imaplib raises the same
790	            # generic IMAP4.error for bad credentials AND transient server
791	            # NOs (e.g. Gmail's "too many simultaneous connections"), so a
792	            # type-based terminal classification isn't safe here. Long-lived
793	            # loops surface via the reconnect watcher's NEEDS_ATTENTION
794	            # escalation instead.
795	            self._set_fatal_error(
796	                "email_imap_connect_error",
797	                f"IMAP connection to {self._imap_host}:{self._imap_port} failed: {e}",
798	                retryable=True,
799	            )
800	            return False
801
802	        try:
803	            # Test SMTP connection
804	            smtp = self._connect_smtp()
805	            try:
806	                smtp.login(self._address, self._password)
807	            finally:
808	                smtp.quit()
809	            logger.info("[Email] SMTP connection test passed.")
810	        except smtplib.SMTPAuthenticationError as e:
811	            logger.error("[Email] SMTP authentication failed: %s", e)
812	            # Typed auth failure (535 & friends): bad or revoked credentials
813	            # can never self-heal, so drop out of the reconnect queue instead
814	            # of retrying a dead password forever (OOF-156). Type-based only —
815	            # SMTPAuthenticationError is unambiguous, unlike IMAP4.error above.
816	            self._set_fatal_error(
817	                "email_auth_error",
818	                f"SMTP authentication failed for {self._address}: {e}. "
819	                "Check EMAIL_PASSWORD (for Gmail/Outlook this must be an "
820	                "app password, not the account password).",
821	                retryable=False,
822	            )
823	            return False
824	        except Exception as e:
825	            logger.error("[Email] SMTP connection failed: %s", e)
826	            self._set_fatal_error(
827	                "email_smtp_connect_error",
828	                f"SMTP connection to {self._smtp_host} failed: {e}",
829	                retryable=True,
830	            )
831	            return False
832
833	        self._running = True
834	        self._poll_task = asyncio.create_task(self._poll_loop())
835	        print(f"[Email] Connected as {self._address}")
836	        # Plugin-registered native handlers (ctx.register_platform_handler).
837	        self._wire_plugin_handlers(None)
838	        return True
839
840	    async def disconnect(self) -> None:
841	        """Stop polling and disconnect."""
842	        self._running = False
843	        if self._poll_task:
844	            self._poll_task.cancel()
845	            try:
846	                await self._poll_task
847	            except asyncio.CancelledError:
848	                pass
849	            self._poll_task = None
850	        logger.info("[Email] Disconnected.")
851
852	    async def _poll_loop(self) -> None:
853	        """Poll IMAP for new messages at regular intervals."""
854	        while self._running:
855	            try:
856	                await self._check_inbox()
857	            except asyncio.CancelledError:
858	                break
859	            except Exception as e:
860	                logger.error("[Email] Poll error: %s", e)
861	            await asyncio.sleep(self._poll_interval)
862
863	    async def _check_inbox(self) -> None:
864	        """Check INBOX for unseen messages and dispatch them."""
865	        # Run IMAP operations in a thread to avoid blocking the event loop
866	        loop = asyncio.get_running_loop()
867	        messages = await loop.run_in_executor(None, self._fetch_new_messages)
868	        # Dispatch whatever the fetch managed to return BEFORE escalating a
869	        # failure: on a mid-batch exception _fetch_new_messages returns the
870	        # partial results, and dropping them here would lose those messages
871	        # (their processing already marked them seen).
872	        for msg_data in messages:
873	            await self._dispatch_message(msg_data)
874	        if self._last_fetch_failed:
875	            # The IMAP check itself failed (connect/login/select/search/fetch),
876	            # not just an empty inbox. Surface it through the fatal-error hook
877	            # so the gateway's existing reconnect/backoff/status machinery
878	            # re-establishes the mailbox instead of silently treating every
879	            # failed check as "nothing new" (#80016). The handler runs in a
880	            # detached task (gateway/run.py), so awaiting it from our own poll
```
