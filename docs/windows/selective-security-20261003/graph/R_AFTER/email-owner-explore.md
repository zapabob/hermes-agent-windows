**Exploration: plugins/platforms/email/adapter.py**

Found 73 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/email/adapter.py`** — calls(calls), _domain_of(calls), _esecret_int(calls), _tls_context(calls), _fail(calls), _safe_decode(calls), _domains_aligned(calls), _decode_header_value(calls), _esecret_bool(calls), _normalize_security(calls), _open_smtp(calls), instantiates(instantiates), _get_socket(method), _create_ipv4_connection(calls), _first_body_part(calls), +108 more

```python
27	from utils import is_truthy_value
28	from gateway.platforms._shared import get_scoped_secret as _get_secret, coerce_port
29
30	logger = logging.getLogger(__name__)
31
32	_SECURITY_ALIASES = {"tls": "tls", "ssl": "tls", "implicit": "tls", "starttls": "starttls", "plain": "plain", "none": "plain"}
33	# Automated senders (address substrings / bulk-mail headers) are silently ignored.
34	_NOREPLY_PATTERNS = ("noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster",
35	                     "bounce", "notifications@", "automated@", "auto-confirm", "auto-reply", "automailer")
36	_AUTOMATED_HEADERS = {"Auto-Submitted": lambda v: v.lower() != "no",
37	                      "Precedence": lambda v: v.lower() in {"bulk", "list", "junk"},
38	                      "X-Auto-Response-Suppress": lambda v: bool(v), "List-Unsubscribe": lambda v: bool(v)}
39	MAX_MESSAGE_LENGTH = 50_000  # Gmail-safe max length per email body
40	SMTP_CONNECT_TIMEOUT = 30
41	_TRUTHY = {"true", "1", "yes"}
42	_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
43	# Charset labels seen in the wild that Python's codec registry doesn't know: "unknown-8bit"/"x-unknown" are
44	# RFC 1428 placeholders (QQ Mail emits them); gb2312/gbk map to the gb18030 superset so GBK extensions decode.
45	_CHARSET_ALIASES = {"unknown-8bit": "utf-8", "unknown": "utf-8", "x-unknown": "utf-8", "default": "utf-8",

... (gap) ...

56
57	def _esecret_int(name: str, default: int) -> int:
58	    """Scope-aware integer read."""
59	    return coerce_port(str(_get_secret(name, "")).strip() or default, default)
60
61
62	def _esecret_bool(name: str, default: bool = False) -> bool:
63	    """Scope-aware boolean read."""
64	    return is_truthy_value(raw, default=default) if (raw := str(_get_secret(name, "")).strip()) else default
65
66
67	def _normalize_security(value: Any, default: str = "tls") -> str:
68	    """Map to ``tls`` | ``starttls`` | ``plain``; unknown values warn and fall back to *default* (a typo never downgrades to plaintext)."""
69	    raw = str(value or "").strip().lower().replace("-", "").replace("_", "")
70	    if raw and raw not in _SECURITY_ALIASES:
71	        logger.warning("Unknown email security mode %r; using %r", value, default)
72	    return _SECURITY_ALIASES.get(raw, default)
73
74
75	def _tls_context(verify: bool, host: str) -> ssl.SSLContext:
76	    """Verified context by default; unverified only when explicitly opted out."""
77	    if verify:
78	        return ssl.create_default_context()
79	    if host not in ("127.0.0.1", "::1", "localhost"):
80	        logger.warning("TLS verification disabled for non-loopback host %s", host)
81	    return ssl._create_unverified_context()
82
83

... (gap) ...

106	        sock.settimeout(timeout)
107	        try:
108	            if source_address:
109	                sock.bind(source_address)
110	            sock.connect(sockaddr)
111	            return sock
112	        except OSError as exc:
113	            last_error = exc
114	            sock.close()
115	    raise last_error if last_error is not None else OSError(f"No IPv4 address found for {host}:{port}")
116
117
118	class _IPv4SMTP(smtplib.SMTP):
119	    def _get_socket(self, host, port, timeout):  # type: ignore[override]
120	        return _create_ipv4_connection(host, port, timeout, source_address=self.source_address)
121
122
123	class _IPv4SMTP_SSL(smtplib.SMTP_SSL):
124	    def _get_socket(self, host, port, timeout):  # type: ignore[override]
125	        return self.context.wrap_socket(_create_ipv4_connection(host, port, timeout, source_address=self.source_address), server_hostname=getattr(self, "_host", host))
126
127
128	def _open_smtp(host: str, port: int, security: str, ctx: ssl.SSLContext, smtp_cls: type, smtp_ssl_cls: type, **kwargs: Any) -> smtplib.SMTP:
129	    """Open one SMTP connection with TLS established per *security*; *kwargs* go to the constructor."""
130	    if security == "tls":
131	        return smtp_ssl_cls(host, port, context=ctx, **kwargs)
132	    smtp = smtp_cls(host, port, **kwargs)
133	    if security == "starttls":
134	        try:
135	            smtp.starttls(context=ctx)
136	        except Exception:
137	            smtp.close()
138	            raise

... (gap) ...

157	    """True if this email is from an automated/noreply source."""
158	    addr = address.lower()
159	    return any(pattern in addr for pattern in _NOREPLY_PATTERNS) or any(
160	        (value := headers.get(header, "")) and check(value) for header, check in _AUTOMATED_HEADERS.items())
161
162
163	def check_email_requirements() -> bool:
164	    """True when all email settings are present and non-blank (blank keys left by an abandoned setup must not enable the platform).
165
166	    Treats blank/whitespace-only values as missing so an abandoned setup that left empty ``EMAIL_*`` keys in
167	    ``.env`` does not enable the platform (#40715).
168	    """
169	    return all(_get_secret(name, "").strip() for name in ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_IMAP_HOST", "EMAIL_SMTP_HOST"))
170
171
172	def _safe_decode(payload: bytes, charset: "Optional[str]") -> str:
173	    """Decode without ever raising: ``errors="replace"`` does not guard a missing codec (``LookupError``), so fall back alias → UTF-8 → latin-1.
174
175	    Unknown or malformed charset labels (``unknown-8bit``, misspelled names, attacker-controlled garbage)
176	    previously raised ``LookupError`` from ``bytes.decode`` — ``errors="replace"`` only guards decode
177	    errors, not a missing codec — which aborted the whole IMAP fetch and dropped every message in the batch
178	    (#35901, #55381, #55383). Fall back through a small alias table, then UTF-8, then latin-1 (which never
179	    fails).
180	    """
181	    label = (charset or "utf-8").strip().strip("\"'").lower() or "utf-8"
182	    for candidate in (_CHARSET_ALIASES.get(label, label), "utf-8"):
183	        try:
184	            return payload.decode(candidate, errors="replace")

... (gap) ...

197	        parts = decode_header(raw)
198	    except Exception:  # malformed RFC 2047 structure
199	        return raw
200	    return " ".join(_safe_decode(part, charset) if isinstance(part, bytes) else part for part, charset in parts)
201
202
203	def _first_body_part(msg: email_lib.message.Message, content_type: str) -> str:
204	    """Decoded text of the first non-attachment part of *content_type*, or ''."""
205	    for part in msg.walk():
206	        if "attachment" in str(part.get("Content-Disposition", "")) or part.get_content_type() != content_type:
207	            continue
208	        if payload := part.get_payload(decode=True):
209	            return _safe_decode(payload, part.get_content_charset())
210	    return ""
211
212
213	def _extract_text_body(msg: email_lib.message.Message) -> str:
214	    """Extract the plain-text body from a potentially multipart email."""
215	    if msg.is_multipart():
216	        html = _first_body_part(msg, "text/html")
217	        return _first_body_part(msg, "text/plain") or (_strip_html(html) if html else "")
218	    text = _safe_decode(payload, msg.get_content_charset()) if (payload := msg.get_payload(decode=True)) else ""
219	    return _strip_html(text) if msg.get_content_type() == "text/html" else text
220
221
222	def _strip_html(html: str) -> str:
223	    """Naive HTML tag stripper for fallback text extraction."""
224	    for pattern, repl in _HTML_SUBS:
225	        html = pattern.sub(repl, html)
226	    return html.strip()
227
228
229	def _extract_email_address(raw: str) -> str:
230	    """Extract bare email address from 'Name <addr>' format."""
231	    match = re.search(r"<([^>]+)>", raw)
232	    return (match.group(1) if match else raw).strip().lower()
233
234
235	def _domain_of(address: str) -> str:
236	    """Lowercased domain part of an email address, or ''."""
237	    return address.rpartition("@")[2].strip().lower()
238
239
240	def _domains_aligned(a: str, b: str) -> bool:
241	    """Relaxed DMARC alignment: equal, or one is a dot-suffix of the other."""
242	    a = (a or "").strip().lower().rstrip(".")
243	    b = (b or "").strip().lower().rstrip(".")
244	    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))
245
246
247	def _verify_sender_authentication(msg: email_lib.message.Message, from_addr: str, *, authserv_id: str = "") -> Tuple[bool, str]:
248	    """Verify the ``From:`` domain is authenticated; returns ``(authenticated, reason)``.
249	    ``From:`` is attacker-controlled (GHSA-rxqh-5572-8m77); the only trustworthy signal is the
250	    ``Authentication-Results`` header stamped by the *receiving* server. It prepends, so the FIRST
251	    instance is trusted and an injected copy sorts below it; pinned to *authserv_id* when given.
252	    True on DMARC pass, aligned SPF pass, or aligned DKIM (``header.d``) pass. No header → fail-closed
253	    (opt out via ``EmailAdapter._require_authenticated_sender``)."""
254	    from_domain = _domain_of(from_addr)
255	    if not from_domain:
256	        return False, "missing From domain"
257	    if not (headers := msg.get_all("Authentication-Results")):
258	        return False, "no Authentication-Results header"
259	    values = (" ".join(str(raw).split()) for raw in headers)  # authserv-id precedes the first ';'
260	    trusted = next((v for v in values if not authserv_id or (serv := v.split(";", 1)[0].strip().lower()) == authserv_id.lower()
261	                    or _domains_aligned(serv, authserv_id)), None)
262	    if trusted is None:
263	        return False, "no Authentication-Results from trusted authserv-id"
264	    methods = {m.lower(): r.lower() for m, r in _AUTH_METHOD_RE.findall(trusted)}
265	    props = {p.lower(): v.strip().strip('"') for p, v in _AUTH_PROP_RE.findall(trusted)}
266	    if methods.get("dmarc") == "pass":  # DMARC already enforces From alignment
267	        return True, "dmarc=pass"
268	    if methods.get("spf") == "pass":  # envelope/MAIL FROM domain must align with From
269	        spf_domain = _domain_of(props.get("smtp.mailfrom", "")) or props.get("smtp.from", "") or props.get("envelope-from", "")
270	        if _domains_aligned(_domain_of(spf_domain) if "@" in spf_domain else spf_domain, from_domain):
271	            return True, "spf=pass aligned"
272	    if methods.get("dkim") == "pass":  # signing domain header.d must align with From
273	        dkim_domain = props.get("header.d", "") or _domain_of(props.get("header.from", ""))
274	        if _domains_aligned(dkim_domain, from_domain):
275	            return True, "dkim=pass aligned"
276	    return False, f"authentication failed ({trusted[:120]})"
277
278
279	def _extract_attachments(msg: email_lib.message.Message, skip_attachments: bool = False) -> List[Dict[str, Any]]:
280	    """Extract attachment metadata and cache files locally (nothing when *skip_attachments*)."""
281	    attachments = []
282	    if not msg.is_multipart():
283	        return attachments
284	    for part in msg.walk():
285	        disposition, content_type = str(part.get("Content-Disposition", "")), part.get_content_type()
286	        if skip_attachments or ("attachment" not in disposition and (
287	                "inline" not in disposition or content_type in {"text/plain", "text/html"})):
288	            continue  # not an attachment, or an inline text/html body part
289	        filename = _decode_header_value(fn) if (fn := part.get_filename()) else f"attachment.{part.get_content_subtype() or 'bin'}"
290	        if not (payload := part.get_payload(decode=True)):
291	            continue
292	        if (ext := Path(filename).suffix.lower()) in _IMAGE_EXTS:
293	            try:
294	                cached_path, kind = cache_image_from_bytes(payload, ext), "image"
295	            except ValueError:
296	                logger.debug("Skipping non-image attachment %s (invalid magic bytes)", filename)
297	                continue
298	        else:
299	            cached_path, kind = cache_document_from_bytes(payload, filename), "document"
300	        attachments.append({"path": cached_path, "filename": filename, "type": kind, "media_type": content_type})
301	    return attachments
302
303
304	def _attach_file(msg: MIMEMultipart, path: Path, filename: str) -> None:
305	    """Attach *path* to *msg* as base64 application/octet-stream."""
306	    with open(path, "rb") as f:
307	        part = MIMEBase("application", "octet-stream")
308	        part.set_payload(f.read())
309	        encoders.encode_base64(part)
310	        part.add_header("Content-Disposition", f"attachment; filename={filename}")
311	        msg.attach(part)
312
313
314	class EmailAdapter(BasePlatformAdapter):
315	    """Email gateway adapter using IMAP (receive) and SMTP (send)."""
316
317	    # Per-account seen-UID snapshot surviving adapter recreation: the reconnect watcher builds a FRESH
318	    # adapter per retry; without this connect(is_reconnect=True) would re-mark the mailbox seen and skip
319	    # mail that arrived during the outage. Keyed by address (multiplex runs several accounts); same-process only.
320	    _seen_uids_snapshot: Dict[str, set] = {}
321
322	    def __init__(self, config: PlatformConfig):
323	        super().__init__(config, Platform.EMAIL)
324	        # Env first, then PlatformConfig.extra (config.yaml-only setups). Host/address are stripped: a stray
325	        # newline made IMAP4_SSL raise ``[Errno 8] nodename nor servname`` instead of "host not set".
326	        extra = config.extra or {}
327	        setting = lambda env, key: _get_secret(env, "") or extra.get(key, "")  # noqa: E731
328	        tls_verify = lambda env, key: _esecret_bool(env, is_truthy_value(extra.get(key), default=True))  # noqa: E731
329	        self._address = setting("EMAIL_ADDRESS", "address").strip()
330	        self._password = _get_secret("EMAIL_PASSWORD", "")
331	        self._imap_host = setting("EMAIL_IMAP_HOST", "imap_host").strip()
332	        self._imap_port = _esecret_int("EMAIL_IMAP_PORT", 993)
333	        self._imap_security = _normalize_security(setting("EMAIL_IMAP_SECURITY", "imap_security"))
334	        self._imap_tls_verify = tls_verify("EMAIL_IMAP_TLS_VERIFY", "imap_tls_verify")
335	        self._smtp_host = setting("EMAIL_SMTP_HOST", "smtp_host").strip()
336	        self._smtp_port = _esecret_int("EMAIL_SMTP_PORT", 587)
337	        self._smtp_security = _normalize_security(setting("EMAIL_SMTP_SECURITY", "smtp_security"), default="tls" if self._smtp_port == 465 else "starttls")
338	        self._smtp_tls_verify = tls_verify("EMAIL_SMTP_TLS_VERIFY", "smtp_tls_verify")
339	        self._poll_interval = _esecret_int("EMAIL_POLL_INTERVAL", 15)
340	        self._skip_attachments = extra.get("skip_attachments", False)  # platforms.email.skip_attachments
341	        # Require an authenticated From: domain (SPF/DKIM/DMARC) before trusting it for authorization
342	        # (GHSA-rxqh-5572-8m77). Default ON; opt out via require_authenticated_sender: false / EMAIL_TRUST_FROM_HEADER=true.
343	        if "require_authenticated_sender" in extra:
344	            self._require_authenticated_sender = bool(extra["require_authenticated_sender"])
345	        else:
346	            self._require_authenticated_sender = not _esecret_bool("EMAIL_TRUST_FROM_HEADER", False)
347	        # Optional authserv-id pinning Authentication-Results to the operator's own server (defeats an injected header sorting first).
348	        self._authserv_id = (extra.get("authserv_id", "") or _get_secret("EMAIL_AUTHSERV_ID", "")).strip().lower()
349	        self._seen_uids: set = set()
350	        self._seen_uids_max: int = 2000   # cap to prevent unbounded memory growth
351	        self._poll_task: Optional[asyncio.Task] = None

... (gap) ...

370	    def _connect_imap(self) -> imaplib.IMAP4:
371	        """Create an IMAP connection using implicit TLS, STARTTLS, or plaintext."""
372	        if self._imap_security == "tls":
373	            return imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=30, ssl_context=_tls_context(self._imap_tls_verify, self._imap_host))
374	        imap = imaplib.IMAP4(self._imap_host, self._imap_port, timeout=30)
375	        if self._imap_security == "starttls":
376	            try:
377	                imap.starttls(ssl_context=_tls_context(self._imap_tls_verify, self._imap_host))
378	            except Exception:
379	                _close_imap(imap)
380	                raise
381	        return imap
382
383	    @contextmanager
384	    def _inbox(self):
385	        """Logged-in IMAP handle on INBOX; always ``_close_imap``-ed on exit (a login/select failure used to leak one fd per reconnect)."""
386	        # Test IMAP connection. The handle is closed in ``finally`` — before this, a failure in
387	        # login/select/search left the TCP socket open with no owner, leaking one fd per connect attempt.
388	        # Under the gateway's reconnect watcher (fresh adapter instance per retry) against an
389	        # unreachable/proxied host this grew monotonically until fd exhaustion on macOS's 256 soft limit
390	        # (#79889).
391	        imap = self._connect_imap()
392	        try:
393	            imap.login(self._address, self._password)
394	            _send_imap_id(imap)
395	            imap.select("INBOX")
396	            yield imap
397	        finally:
398	            _close_imap(imap)
399
400	    def _connect_smtp(self) -> smtplib.SMTP:
401	        """SMTP connection with TLS established (callers go straight to ``login()``). An unreachable IPv6 address can
402	        hang until the socket timeout, so connection-level failures retry through an IPv4-only socket path (no global
403	        resolver mutation); TLS verification errors are not retried."""
404	        host, port, security, ctx = self._smtp_host, self._smtp_port, self._smtp_security, _tls_context(self._smtp_tls_verify, self._smtp_host)
405	        try:
406	            return _open_smtp(host, port, security, ctx, smtplib.SMTP, smtplib.SMTP_SSL, timeout=SMTP_CONNECT_TIMEOUT)
407	        except (socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
408	            if isinstance(exc, ssl.SSLError):
409	                raise
410	            return _open_smtp(host, port, security, ctx, _IPv4SMTP, _IPv4SMTP_SSL, timeout=SMTP_CONNECT_TIMEOUT)
411
412	    def _fail(self, log_fmt: str, err: object, code: str, detail: str, *, retryable: bool) -> bool:
413	        """Log *err*, record a fatal error for the gateway's reconnect machinery, return False."""
414	        logger.error(log_fmt, err)
415	        self._set_fatal_error(code, detail, retryable=retryable)
416	        return False
417
418	    def _probe_imap(self, is_reconnect: bool) -> bool:
419	        """Connection test + seen-UID baseline. Sets a fatal error and returns False on failure."""
420	        try:
421	            with self._inbox() as imap:
422	                snapshot = self._seen_uids_snapshot.get(self._address)
423	                if is_reconnect and snapshot is not None:
424	                    # Same-process reconnect: restore the previous adapter's baseline so mail that
425	                    # arrived during the outage stays eligible for the next poll.
426	                    self._seen_uids = set(snapshot)
427	                    passed = "[Email] IMAP reconnect test passed. Restored %d seen UIDs; messages received during the outage will be processed."
428	                else:  # first connect (or no snapshot): mark all existing messages seen
429	                    status, data = imap.uid("search", None, "ALL")
430	                    self._seen_uids.update(data[0].split() if status == "OK" and data and data[0] else ())
431	                    passed = "[Email] IMAP connection test passed. %d existing messages skipped."
432	                self._trim_seen_uids()
433	                logger.info(passed, len(self._seen_uids))
434	            self._seen_uids_snapshot[self._address] = set(self._seen_uids)
435	            return True
436	        except Exception as e:
437	            # Always set an explicit fatal code, else the gateway treats every failure as transient with zero
438	            # owner signal. retryable=True because imaplib raises the same generic IMAP4.error for bad credentials
439	            # AND transient NOs (Gmail "too many simultaneous connections"); loops surface via NEEDS_ATTENTION.
440	            return self._fail("[Email] IMAP connection failed: %s", e, "email_imap_connect_error",
441	                              f"IMAP connection to {self._imap_host}:{self._imap_port} failed: {e}", retryable=True)
442
443	    def _probe_smtp(self) -> bool:
444	        """SMTP connect + login test. Sets a fatal error and returns False on failure."""
445	        try:
446	            smtp = self._connect_smtp()
447	            try:
448	                smtp.login(self._address, self._password)
449	            finally:
450	                smtp.quit()
451	            logger.info("[Email] SMTP connection test passed.")
452	            return True
453	        except smtplib.SMTPAuthenticationError as e:
454	            # Typed auth failure (535 & friends) can never self-heal, so drop out of the reconnect queue — unambiguous, unlike IMAP4.error.
455	            return self._fail("[Email] SMTP authentication failed: %s", e, "email_auth_error",
456	                              f"SMTP authentication failed for {self._address}: {e}. Check EMAIL_PASSWORD (for Gmail/Outlook "
457	                              "this must be an app password, not the account password).", retryable=False)
458	        except Exception as e:
459	            return self._fail("[Email] SMTP connection failed: %s", e, "email_smtp_connect_error",
460	                              f"SMTP connection to {self._smtp_host} failed: {e}", retryable=True)
461
462	    async def connect(self, *, is_reconnect: bool = False) -> bool:
463	        """Connect to the IMAP server and start polling for new messages."""
464	        # Validate up front so a missing host is an actionable config error, not IMAP4_SSL("") raising ``[Errno 8]``.
465	        required = (("EMAIL_ADDRESS", self._address), ("EMAIL_PASSWORD", self._password), ("EMAIL_IMAP_HOST", self._imap_host), ("EMAIL_SMTP_HOST", self._smtp_host))
466	        if missing := [name for name, value in required if not value]:
467	            message = f"Not configured — missing {', '.join(missing)}. Set it via `hermes gateway setup` (env) or platforms.email in config.yaml."
468	            # Non-retryable: a blank-but-present env var used to drive an indefinite retry loop that leaked until OOM.
469	            return self._fail("[Email] %s", message, "email_missing_configuration", message, retryable=False)
470	        if not self._probe_imap(is_reconnect) or not self._probe_smtp():
471	            return False
472	        self._running = True
473	        self._poll_task = asyncio.create_task(self._poll_loop())
474	        print(f"[Email] Connected as {self._address}")
475	        self._wire_plugin_handlers(None)  # plugin-registered native handlers
476	        return True
477
478	    async def disconnect(self) -> None:
479	        """Stop polling and disconnect."""
480	        self._running = False
481	        if self._poll_task:
482	            self._poll_task.cancel()
483	            with suppress(asyncio.CancelledError):
484	                await self._poll_task
485	            self._poll_task = None
486	        logger.info("[Email] Disconnected.")
487
488	    async def _poll_loop(self) -> None:
489	        """Poll IMAP for new messages at regular intervals."""
490	        while self._running:
491	            try:
492	                await self._check_inbox()
493	            except asyncio.CancelledError:
494	                break
495	            except Exception as e:
```
