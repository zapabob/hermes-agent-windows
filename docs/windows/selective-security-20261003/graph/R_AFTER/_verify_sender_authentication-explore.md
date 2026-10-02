**Exploration: _verify_sender_authentication**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `send` (tools/send_message_senders.py:171) — 1 caller in `tools/send_message_senders.py`; tested via callers: `tests/tools/test_send_message_telegram_proxy.py`, `tests/tools/test_send_message_tool.py` +2
- `verify` (hermes_cli/secrets_cli.py:295) — 1 caller in `hermes_cli/secrets_cli.py`; no tests found within 3 caller hops
- `send` (apps/desktop/scripts/click-session.mjs:15) — 3 callers in `apps/desktop/scripts/click-session.mjs`, `apps/desktop/scripts/live-drive.mjs`; no tests found within 3 caller hops
- `send` (apps/desktop/scripts/diag-jump.mjs:16) — 2 callers in `apps/desktop/scripts/diag-jump.mjs`; no tests found within 3 caller hops

**Relationships**

**calls:**
- send → _send_telegram_message_with_retry
- _telegram_send_text_chunk → send
- _telegram_send_text_chunk → _is_telegram_thread_not_found
- _telegram_send_text_chunk → warning
- _telegram_send_text_chunk → _sanitize_error_text
- _telegram_send_text_chunk → _strip_mdv2_safe
- _send_telegram → _telegram_send_text_chunk
- _send_telegram_message_with_retry → send_message
- _send_telegram_message_with_retry → _telegram_retry_delay
- _send_telegram_message_with_retry → warning
- _send_telegram_message_with_retry → _sanitize_error_text
- _send_telegram → _send_telegram_message_with_retry
- _telegram_send_one_media → _is_telegram_thread_not_found
- warning → append
- _cmd_reset → warning
- ... and 89 more

**references:**
- verify → _DOCS_URL
- cmd_token → _DOCS_URL
- cmd_token → _DEFAULT_TOKEN_ENV
- cmd_token → save_env_value
- verify → _NOT_BSM_TOKEN_WARNING
- cmd_token → verify
- cmd_token → _NOT_BSM_TOKEN_WARNING
- cmd_token → _DEFAULT_TOKEN_ENV
- cmd_token → save_env_value

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/email/adapter.py`** — calls(calls), _verify_sender_authentication(function), split(calls)

```python
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
```

**Not shown above — explore these names for their source**

- tools/send_message_senders.py: send:171, _telegram_send_text_chunk:167, _send_telegram_message_with_retry:84, _is_telegram_thread_not_found:98, _sanitize_error_text:46, _strip_mdv2_safe:137, +3 more
- apps/desktop/scripts/diag-scroll-reset.mjs: send:50, evalP:56, wheelUpSweep:143
- hermes_cli/secrets_cli.py: verify:295, cmd_token:285, _list_projects:446, _NOT_BSM_TOKEN_WARNING:39, _load_bw:49, _bw_cfg:236, +1 more
- hermes_cli/onepassword_secrets_cli.py: verify:257, cmd_token:248, _op_whoami:377, _DOCS_URL:38, _op_cfg:44, _DEFAULT_TOKEN_ENV:37
- apps/desktop/scripts/diag-jump.mjs: send:16, evalP:22, diag-jump.mjs:1
- apps/desktop/scripts/click-session.mjs: send:15, click-session.mjs:1
- apps/desktop/scripts/eval.mjs: send:37, eval.mjs:1
- apps/desktop/scripts/probe-renderer.mjs: send:17, probe-renderer.mjs:1
- apps/desktop/scripts/perf/lib/cdp.mjs: send:112, CDP:57, eval:130, typeIntoComposer:158, withCpuProfile:184
- acp_adapter/server.py: _register_session_mcp_servers:405, _session_response_fields:546, load_session:588, resume_session:598, set_session_model:929, set_session_mode:941
- ... and 29 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
