**Exploration: plugins/platforms/email/adapter.py**

Found 81 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/email/adapter.py`** — calls(calls), instantiates(instantiates), _esecret_int(calls), _tls_context(calls), _fail(calls), _safe_decode(calls), aligned(calls), _decode_header_value(calls), _esecret_bool(calls), _normalize_security(calls), _open_smtp(calls), _get_socket(method), _create_ipv4_connection(calls), _first_body_part(calls), _strip_html(calls), +120 more

```python
32	from utils import is_truthy_value
33	from gateway.platforms._shared import get_scoped_secret as _get_secret, coerce_port, decode_json_list_literal, send_error
34
35	logger = logging.getLogger(__name__)
36
37	_SECURITY_ALIASES = {"tls": "tls", "ssl": "tls", "implicit": "tls", "starttls": "starttls", "plain": "plain", "none": "plain"}
38	# Automated senders (address substrings / bulk-mail headers) are silently ignored.
39	_NOREPLY_PATTERNS = ("noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster",
40	                     "bounce", "notifications@", "automated@", "auto-confirm", "auto-reply", "automailer")
41	_AUTOMATED_HEADERS = {"Auto-Submitted": lambda v: v.lower() != "no",
42	                      "Precedence": lambda v: v.lower() in {"bulk", "list", "junk"},
43	                      "X-Auto-Response-Suppress": lambda v: bool(v), "List-Unsubscribe": lambda v: bool(v)}
44	MAX_MESSAGE_LENGTH = 50_000  # Gmail-safe max length per email body
45	SMTP_CONNECT_TIMEOUT = 30
46	_TRUTHY = {"true", "1", "yes"}
47	_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
48	# Charset labels seen in the wild that Python's codec registry doesn't know: "unknown-8bit"/"x-unknown" are
49	# RFC 1428 placeholders (QQ Mail emits them); gb2312/gbk map to the gb18030 superset so GBK extensions decode.
50	_CHARSET_ALIASES = {"unknown-8bit": "utf-8", "unknown": "utf-8", "x-unknown": "utf-8", "default": "utf-8",
51	                    "ansi_x3.110-1983": "latin-1", "cp-850": "cp850",
52	                    "gb2312": "gb18030", "gbk": "gb18030", "ks_c_5601-1987": "cp949"}
53	# Ordered (pattern, replacement) substitutions for _strip_html.
54	_HTML_SUBS = ((re.compile(r"<br\s*/?>", re.IGNORECASE), "\n"), (re.compile(r"<p[^>]*>", re.IGNORECASE), "\n"),
55	              (re.compile(r"</p>", re.IGNORECASE), "\n"), (re.compile(r"<[^>]+>"), ""), (re.compile(r"&nbsp;"), " "),
56	              (re.compile(r"&amp;"), "&"), (re.compile(r"&lt;"), "<"), (re.compile(r"&gt;"), ">"), (re.compile(r"\n{3,}"), "\n\n"))
57	# ``display <bracketed>`` split for the _extract_email_address fallback (linear: neither part can match the other's delimiters).
58	_SINGLE_BRACKET_FROM_RE = re.compile(r'([^"<>]*)<([^<>\s]+)>\s*')
59	_COMMENT_RE = re.compile(r"\([^()]*\)")
60	# Longest From: value we parse. parseaddr is pure Python and superlinear on hostile input (~1s at 100KB, GIL held);
61	# a real mailbox plus display name stays far below this (RFC 5322 caps a line at 998 chars).
62	_MAX_FROM_LEN = 2048
63	# Authentication-Results clause head (``dmarc=pass``), matched only at the start of a clause.
64	_AUTH_METHOD_RE = re.compile(r"\s*(dmarc|dkim|spf)\s*=\s*([a-z]+)", re.IGNORECASE)
65	# One token of a clause: a property we read (``header.from=x``; the value may be or contain a quoted-string), or
66	# any other whitespace-delimited token consumed whole, so text inside quotes or other values is never read as a prop.
67	_QUOTED = r'"(?:[^"\\]|\\.)*"'
68	_AUTH_PROP_RE = re.compile(r'(header\.from|header\.d|smtp\.mailfrom|smtp\.from|envelope-from)\s*=\s*((?:%s|[^\s";])+)'
69	                           r'|(?:%s|[^\s"])+' % (_QUOTED, _QUOTED), re.IGNORECASE)
70
71
72	def _esecret_int(name: str, default: int) -> int:
73	    """Scope-aware integer read."""
74	    return coerce_port(str(_get_secret(name, "")).strip() or default, default)
75
76
77	def _esecret_bool(name: str, default: bool = False) -> bool:
78	    """Scope-aware boolean read."""
79	    return is_truthy_value(raw, default=default) if (raw := str(_get_secret(name, "")).strip()) else default
80
81
82	def _normalize_security(value: Any, default: str = "tls") -> str:
83	    """Map to ``tls`` | ``starttls`` | ``plain``; unknown values warn and fall back to *default* (a typo never downgrades to plaintext)."""
84	    raw = str(value or "").strip().lower().replace("-", "").replace("_", "")
85	    if raw and raw not in _SECURITY_ALIASES:
86	        logger.warning("Unknown email security mode %r; using %r", value, default)
87	    return _SECURITY_ALIASES.get(raw, default)
88
89
90	def _tls_context(verify: bool, host: str) -> ssl.SSLContext:
91	    """Verified context by default; unverified only when explicitly opted out."""
92	    if verify:
93	        return ssl.create_default_context()
94	    if host not in ("127.0.0.1", "::1", "localhost"):
95	        logger.warning("TLS verification disabled for non-loopback host %s", host)
96	    return ssl._create_unverified_context()
97
98

... (gap) ...

121	        sock.settimeout(timeout)
122	        try:
123	            if source_address:
124	                sock.bind(source_address)
125	            sock.connect(sockaddr)
126	            return sock
127	        except OSError as exc:
128	            last_error = exc
129	            sock.close()
130	    raise last_error if last_error is not None else OSError(f"No IPv4 address found for {host}:{port}")
131
132
133	class _IPv4SMTP(smtplib.SMTP):
134	    def _get_socket(self, host, port, timeout):  # type: ignore[override]
135	        return _create_ipv4_connection(host, port, timeout, source_address=self.source_address)
136
137
138	class _IPv4SMTP_SSL(smtplib.SMTP_SSL):
139	    def _get_socket(self, host, port, timeout):  # type: ignore[override]
140	        return self.context.wrap_socket(_create_ipv4_connection(host, port, timeout, source_address=self.source_address), server_hostname=getattr(self, "_host", host))
141
142
143	def _open_smtp(host: str, port: int, security: str, ctx: ssl.SSLContext, smtp_cls: type, smtp_ssl_cls: type, **kwargs: Any) -> smtplib.SMTP:
144	    """Open one SMTP connection with TLS established per *security*; *kwargs* go to the constructor."""
145	    if security == "tls":
146	        return smtp_ssl_cls(host, port, context=ctx, **kwargs)
147	    smtp = smtp_cls(host, port, **kwargs)
148	    if security == "starttls":
149	        try:
150	            smtp.starttls(context=ctx)
151	        except Exception:
152	            smtp.close()
153	            raise

... (gap) ...

171	    try:
172	        try:
173	            from hermes_cli.version_info import get_version_info
174	            version = get_version_info().base_version
175	        except Exception:  # noqa: BLE001 — keep ID best-effort if import fails
176	            version = "0"
177	        imap.xatom("ID", f'("name" "hermes-agent" "version" "{version}" '
178	                         '"vendor" "NousResearch" "support-email" "noreply@nousresearch.com")')
179	    except Exception as e:  # noqa: BLE001 — best-effort, never fatal
180	        logger.debug("[Email] IMAP ID command not accepted: %s", e)
181
182
183	def _is_automated_sender(address: str, headers: dict) -> bool:
184	    """True if this email is from an automated/noreply source."""
185	    addr = address.lower()
186	    return any(pattern in addr for pattern in _NOREPLY_PATTERNS) or any(
187	        (value := headers.get(header, "")) and check(value) for header, check in _AUTOMATED_HEADERS.items())
188
189
190	def check_email_requirements() -> bool:

... (gap) ...

224	        parts = decode_header(raw)
225	    except Exception:  # malformed RFC 2047 structure
226	        return raw
227	    return " ".join(_safe_decode(part, charset) if isinstance(part, bytes) else part for part, charset in parts)
228
229
230	def _first_body_part(msg: email_lib.message.Message, content_type: str) -> str:
231	    """Decoded text of the first non-attachment part of *content_type*, or ''."""
232	    for part in msg.walk():
233	        if "attachment" in str(part.get("Content-Disposition", "")) or part.get_content_type() != content_type:
234	            continue
235	        if payload := part.get_payload(decode=True):
236	            return _safe_decode(payload, part.get_content_charset())
237	    return ""
238
239
240	def _extract_text_body(msg: email_lib.message.Message) -> str:
241	    """Extract the plain-text body from a potentially multipart email."""
242	    if msg.is_multipart():
243	        html = _first_body_part(msg, "text/html")
244	        return _first_body_part(msg, "text/plain") or (_strip_html(html) if html else "")
245	    text = _safe_decode(payload, msg.get_content_charset()) if (payload := msg.get_payload(decode=True)) else ""
246	    return _strip_html(text) if msg.get_content_type() == "text/html" else text
247
248
249	def _strip_html(html: str) -> str:

... (gap) ...

265	        return ""  # hostile size/nesting: take the empty-sender drop (parseaddr recurses per nested comment)
266	    _, addr = parseaddr(value)
267	    if not addr and (m := _SINGLE_BRACKET_FROM_RE.fullmatch(value)):
268	        display, bracketed = _strip_comments(m.group(1)).strip(), m.group(2)
269	        if ("@" in bracketed[1:-1] and not any(c in display for c in ";:()")
270	                and ("@" not in display or display.lower() == bracketed.lower())):
271	            addr = bracketed

... (gap) ...

339	    instance is trusted and an injected copy sorts below it; pinned to *authserv_id* when given.
340	    True on DMARC pass, aligned SPF pass, or aligned DKIM (``header.d``) pass. No header → fail-closed
341	    (opt out via ``EmailAdapter._require_authenticated_sender``)."""
342	    from_domain = _domain_of(from_addr)
343	    if not from_domain:
344	        return False, "missing From domain"
345	    if not (headers := msg.get_all("Authentication-Results")):
346	        return False, "no Authentication-Results header"
347	    values = (" ".join(str(raw).split()) for raw in headers)  # authserv-id precedes the first ';'
348	    trusted = next((v for v in values if not authserv_id or (serv := v.split(";", 1)[0].strip().lower()) == authserv_id.lower()
349	                    or _domains_aligned(serv, authserv_id)), None)
350	    if trusted is None:
351	        return False, "no Authentication-Results from trusted authserv-id"
352	    # Each verdict comes from the head of its own clause (split outside quotes/comments) and its domains only from that
353	    # clause: a quoted local part or comment can otherwise smuggle ``spf=pass``/``header.d=`` (GHSA-rxqh-5572-8m77).
354	    if (clauses := _ar_clauses(trusted)) is None:
355	        return False, "unbalanced quote or comment in Authentication-Results"
356	    results: Dict[str, List[Tuple[str, List[Tuple[str, str]]]]] = {"dmarc": [], "spf": [], "dkim": []}
357	    for clause in clauses:
358	        if m := _AUTH_METHOD_RE.match(clause):
359	            results[m.group(1).lower()].append((m.group(2).lower(), _auth_props(clause)))
360
361	    def aligned(props: List[Tuple[str, str]], names: Tuple[str, ...], *, required: bool = True) -> bool:
362	        domains = [_domain_of(v) for p, v in props if p in names]
363	        return (bool(domains) or not required) and all(_domains_aligned(d, from_domain) for d in domains)
364
365	    if len(results["dmarc"]) > 1:
366	        return False, "ambiguous dmarc result"
367	    # every header.from in the dmarc clause must be the From domain we parsed (absent header.from: trust the verdict)
368	    if any(r == "pass" and aligned(props, ("header.from",), required=False) for r, props in results["dmarc"]):
369	        return True, "dmarc=pass"
370	    # one SMTP transaction has one MAIL FROM verdict: a second spf clause means the SPF signal is not trusted
371	    if len(results["spf"]) == 1 and (spf := results["spf"][0])[0] == "pass" and aligned(
372	            spf[1], ("smtp.mailfrom", "smtp.from", "envelope-from")):
373	        return True, "spf=pass aligned"
374	    # several dkim clauses are normal (one per signature): any single pass whose own header.d aligns is enough
375	    if any(r == "pass" and aligned(props, ("header.d",) if any(p == "header.d" for p, _ in props) else ("header.from",))
376	           for r, props in results["dkim"]):
377	        return True, "dkim=pass aligned"
378	    return False, f"authentication failed ({trusted[:120]})"

... (gap) ...

388	        if skip_attachments or ("attachment" not in disposition and (
389	                "inline" not in disposition or content_type in {"text/plain", "text/html"})):
390	            continue  # not an attachment, or an inline text/html body part
391	        filename = _decode_header_value(fn) if (fn := part.get_filename()) else f"attachment.{part.get_content_subtype() or 'bin'}"
392	        if not (payload := part.get_payload(decode=True)):
393	            continue
394	        if (ext := Path(filename).suffix.lower()) in _IMAGE_EXTS:
395	            try:
396	                cached_path, kind = cache_image_from_bytes(payload, ext), "image"
397	            except ValueError:
398	                logger.debug("Skipping non-image attachment %s (invalid magic bytes)", filename)
399	                continue
400	        else:
401	            cached_path, kind = cache_document_from_bytes(payload, filename), "document"
402	        attachments.append({"path": cached_path, "filename": filename, "type": kind, "media_type": content_type})
403	    return attachments
404
405
406	def _attach_file(msg: MIMEMultipart, path: Path, filename: str) -> None:
407	    """Attach *path* to *msg* as base64 application/octet-stream."""
408	    with open(path, "rb") as f:
409	        part = MIMEBase("application", "octet-stream")
410	        part.set_payload(f.read())
411	        encoders.encode_base64(part)
412	        part.add_header("Content-Disposition", f"attachment; filename={filename}")
413	        msg.attach(part)
414
415
416	class EmailAdapter(BasePlatformAdapter):
417	    """Email gateway adapter using IMAP (receive) and SMTP (send)."""
418	    # One email carries the whole body, so cron delivery hands over the full payload untruncated.
419	    splits_long_messages = True

... (gap) ...

429	        # newline made IMAP4_SSL raise ``[Errno 8] nodename nor servname`` instead of "host not set".
430	        extra = config.extra or {}
431	        setting = lambda env, key: _get_secret(env, "") or extra.get(key, "")  # noqa: E731
432	        tls_verify = lambda env, key: _esecret_bool(env, is_truthy_value(extra.get(key), default=True))  # noqa: E731
433	        self._address = setting("EMAIL_ADDRESS", "address").strip()
434	        self._password = _get_secret("EMAIL_PASSWORD", "")
435	        self._imap_host = setting("EMAIL_IMAP_HOST", "imap_host").strip()
436	        self._imap_port = _esecret_int("EMAIL_IMAP_PORT", 993)
437	        self._imap_security = _normalize_security(setting("EMAIL_IMAP_SECURITY", "imap_security"))
438	        self._imap_tls_verify = tls_verify("EMAIL_IMAP_TLS_VERIFY", "imap_tls_verify")
439	        self._smtp_host = setting("EMAIL_SMTP_HOST", "smtp_host").strip()
440	        self._smtp_port = _esecret_int("EMAIL_SMTP_PORT", 587)
441	        self._smtp_security = _normalize_security(setting("EMAIL_SMTP_SECURITY", "smtp_security"), default="tls" if self._smtp_port == 465 else "starttls")
442	        self._smtp_tls_verify = tls_verify("EMAIL_SMTP_TLS_VERIFY", "smtp_tls_verify")
443	        self._poll_interval = _esecret_int("EMAIL_POLL_INTERVAL", 15)
444	        self._skip_attachments = extra.get("skip_attachments", False)  # platforms.email.skip_attachments
445	        # Require an authenticated From: domain (SPF/DKIM/DMARC) before trusting it for authorization
446	        # (GHSA-rxqh-5572-8m77). Default ON; opt out via require_authenticated_sender: false / EMAIL_TRUST_FROM_HEADER=true.
447	        if "require_authenticated_sender" in extra:
448	            self._require_authenticated_sender = bool(extra["require_authenticated_sender"])
449	        else:
450	            self._require_authenticated_sender = not _esecret_bool("EMAIL_TRUST_FROM_HEADER", False)
451	        # Optional authserv-id pinning Authentication-Results to the operator's own server (defeats an injected header sorting first).
452	        self._authserv_id = (extra.get("authserv_id", "") or _get_secret("EMAIL_AUTHSERV_ID", "")).strip().lower()
453	        self._seen_uids: set = set()

... (gap) ...

474	    def _connect_imap(self) -> imaplib.IMAP4:
475	        """Create an IMAP connection using implicit TLS, STARTTLS, or plaintext."""
476	        if self._imap_security == "tls":
477	            return imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=30, ssl_context=_tls_context(self._imap_tls_verify, self._imap_host))
478	        imap = imaplib.IMAP4(self._imap_host, self._imap_port, timeout=30)
479	        if self._imap_security == "starttls":
480	            try:
481	                imap.starttls(ssl_context=_tls_context(self._imap_tls_verify, self._imap_host))
482	            except Exception:
483	                _close_imap(imap)
484	                raise
485	        return imap
486
487	    @contextmanager
488	    def _inbox(self):
489	        """Logged-in IMAP handle on INBOX; always ``_close_imap``-ed on exit (a login/select failure used to leak one fd per reconnect)."""
490	        # Test IMAP connection. The handle is closed in ``finally`` — before this, a failure in
491	        # login/select/search left the TCP socket open with no owner, leaking one fd per connect attempt.
492	        # Under the gateway's reconnect watcher (fresh adapter instance per retry) against an
493	        # unreachable/proxied host this grew monotonically until fd exhaustion on macOS's 256 soft limit
494	        # (#79889).
495	        imap = self._connect_imap()
496	        try:
497	            imap.login(self._address, self._password)
498	            _send_imap_id(imap)
499	            imap.select("INBOX")
500	            yield imap
501	        finally:
502	            _close_imap(imap)
503
504	    def _connect_smtp(self) -> smtplib.SMTP:
505	        """SMTP connection with TLS established (callers go straight to ``login()``). An unreachable IPv6 address can
506	        hang until the socket timeout, so connection-level failures retry through an IPv4-only socket path (no global
507	        resolver mutation); TLS verification errors are not retried."""
508	        host, port, security, ctx = self._smtp_host, self._smtp_port, self._smtp_security, _tls_context(self._smtp_tls_verify, self._smtp_host)
509	        try:
510	            return _open_smtp(host, port, security, ctx, smtplib.SMTP, smtplib.SMTP_SSL, timeout=SMTP_CONNECT_TIMEOUT)
511	        except (socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
512	            if isinstance(exc, ssl.SSLError):
513	                raise
514	            return _open_smtp(host, port, security, ctx, _IPv4SMTP, _IPv4SMTP_SSL, timeout=SMTP_CONNECT_TIMEOUT)
515
516	    def _fail(self, log_fmt: str, err: object, code: str, detail: str, *, retryable: bool) -> bool:
517	        """Log *err*, record a fatal error for the gateway's reconnect machinery, return False."""
518	        logger.error(log_fmt, err)
519	        self._set_fatal_error(code, detail, retryable=retryable)
520	        return False
521
522	    def _probe_imap(self, is_reconnect: bool) -> bool:
523	        """Connection test + seen-UID baseline. Sets a fatal error and returns False on failure."""
524	        try:
525	            with self._inbox() as imap:
526	                snapshot = self._seen_uids_snapshot.get(self._address)
527	                if is_reconnect and snapshot is not None:
528	                    # Same-process reconnect: restore the previous adapter's baseline so mail that
529	                    # arrived during the outage stays eligible for the next poll.
530	                    self._seen_uids = set(snapshot)
531	                    passed = "[Email] IMAP reconnect test passed. Restored %d seen UIDs; messages received during the outage will be processed."
532	                else:  # first connect (or no snapshot): mark all existing messages seen
533	                    status, data = imap.uid("search", None, "ALL")
534	                    self._seen_uids.update(data[0].split() if status == "OK" and data and data[0] else ())
535	                    passed = "[Email] IMAP connection test passed. %d existing messages skipped."
536	                self._trim_seen_uids()
537	                logger.info(passed, len(self._seen_uids))
538	            self._seen_uids_snapshot[self._address] = set(self._seen_uids)
539	            return True
540	        except Exception as e:
541	            # Always set an explicit fatal code, else the gateway treats every failure as transient with zero
542	            # owner signal. retryable=True because imaplib raises the same generic IMAP4.error for bad credentials
543	            # AND transient NOs (Gmail "too many simultaneous connections"); loops surface via NEEDS_ATTENTION.
544	            return self._fail("[Email] IMAP connection failed: %s", e, "email_imap_connect_error",
545	                              f"IMAP connection to {self._imap_host}:{self._imap_port} failed: {e}", retryable=True)
546
547	    def _probe_smtp(self) -> bool:
548	        """SMTP connect + login test. Sets a fatal error and returns False on failure."""
549	        try:
550	            smtp = self._connect_smtp()
551	            try:
552	                smtp.login(self._address, self._password)
553	            finally:
554	                smtp.quit()
555	            logger.info("[Email] SMTP connection test passed.")
556	            return True
557	        except smtplib.SMTPAuthenticationError as e:
558	            # Typed auth failure (535 & friends) can never self-heal, so drop out of the reconnect queue — unambiguous, unlike IMAP4.error.
559	            return self._fail("[Email] SMTP authentication failed: %s", e, "email_auth_error",
560	                              f"SMTP authentication failed for {self._address}: {e}. Check EMAIL_PASSWORD (for Gmail/Outlook "
561	                              "this must be an app password, not the account password).", retryable=False)
562	        except Exception as e:
563	            return self._fail("[Email] SMTP connection failed: %s", e, "email_smtp_connect_error",
564	                              f"SMTP connection to {self._smtp_host} failed: {e}", retryable=True)
565
566	    async def connect(self, *, is_reconnect: bool = False) -> bool:
567	        """Connect to the IMAP server and start polling for new messages."""
568	        # Validate up front so a missing host is an actionable config error, not IMAP4_SSL("") raising ``[Errno 8]``.
569	        required = (("EMAIL_ADDRESS", self._address), ("EMAIL_PASSWORD", self._password), ("EMAIL_IMAP_HOST", self._imap_host), ("EMAIL_SMTP_HOST", self._smtp_host))
570	        if missing := [name for name, value in required if not value]:
571	            message = f"Not configured — missing {', '.join(missing)}. Set it via `hermes gateway setup` (env) or platforms.email in config.yaml."
572	            # Non-retryable: a blank-but-present env var used to drive an indefinite retry loop that leaked until OOM.
573	            return self._fail("[Email] %s", message, "email_missing_configuration", message, retryable=False)
574	        if not self._probe_imap(is_reconnect) or not self._probe_smtp():
575	            return False
576	        self._running = True
577	        self._poll_task = asyncio.create_task(self._poll_loop())
578	        print(f"[Email] Connected as {self._address}")
579	        self._wire_plugin_handlers(None)  # plugin-registered native handlers
580	        return True
581
582	    async def disconnect(self) -> None:
583	        """Stop polling and disconnect."""
584	        self._running = False
585	        await cancel_task(self._poll_task)
586	        self._poll_task = None
587	        logger.info("[Email] Disconnected.")
588
589	    async def _poll_loop(self) -> None:
590	        """Poll IMAP for new messages at regular intervals."""
591	        while self._running:
592	            try:
593	                await self._check_inbox()
594	            except asyncio.CancelledError:
595	                break
```
