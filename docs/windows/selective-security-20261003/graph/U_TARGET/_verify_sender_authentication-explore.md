**Exploration: _verify_sender_authentication**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `send` (tools/send_message_senders.py:172) — 1 caller in `tools/send_message_senders.py`; tested via callers: `tests/tools/test_send_message_telegram_proxy.py`, `tests/tools/test_send_message_tool.py` +1
- `verify` (scripts/releases/stable.py:621) — 2 callers in `scripts/releases/darwin.py`, `scripts/releases/stable.py`; tested via callers: `tests/scripts/test_stable_release.py`
- `verify` (hermes_cli/secrets_cli.py:288) — 1 caller in `hermes_cli/secrets_cli.py`; no tests found within 3 caller hops
- `verify` (pm/package.py:144) — 12 callers in `hermes_cli/_secrets_common.py`, `hermes_cli/local_runtime/binaries.py`, `pm/cli.py`, `pm/install.py` +2 more; tests: `tests/pm/test_dmgbuild_package.py`, `tests/pm/test_stage_only.py`, `tests/pm/test_startup_recovery.py`

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
- ... and 150 more

**references:**
- main → verify
- main → admit
- main → transitions
- main → candidate_manifest
- main → complete
- verify → _DOCS_URL
- cmd_token → _DOCS_URL
- cmd_token → _DEFAULT_TOKEN_ENV
- cmd_token → save_env_value
- verify → _NOT_BSM_TOKEN_WARNING
- cmd_token → verify
- cmd_token → _NOT_BSM_TOKEN_WARNING
- cmd_token → _DEFAULT_TOKEN_ENV
- cmd_token → save_env_value
- cmd_setup → _DEFAULT_TOKEN_ENV
- ... and 1 more

**instantiates:**
- cmd_token → Console
- cmd_token → Console
- test_deb_rejects_traversal_before_touching_outside → DebPackage
- unpack → InstallError
- _untar_payload → InstallError

**extends:**
- DebPackage → Package
- Uv → DebPackage
- Python → DebPackage
- Nodejs → DebPackage
- Ffmpeg → DebPackage
- _LibDeb → DebPackage
- _P → DebPackage
- BinaryPackage → Package
- Dmgbuild → BinaryPackage
- Uv → BinaryPackage
- Python → BinaryPackage
- Nodejs → BinaryPackage
- Npm → BinaryPackage
- Git → BinaryPackage
- Gh → BinaryPackage
- ... and 13 more

**decorates:**
- Dmgbuild → register
- Uv → register
- Python → register
- Venv → register
- Nodejs → register
- TermuxDocker → register
- Npm → register
- Git → register
- Gh → register
- Ffmpeg → register
- Ripgrep → register
- CuaDriver → register
- AgentBrowser → register
- Chromium → register

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/email/adapter.py`** — calls(calls), split(calls), _verify_sender_authentication(function), append(calls)

```python
332	    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))
333
334
335	def _verify_sender_authentication(msg: email_lib.message.Message, from_addr: str, *, authserv_id: str = "") -> Tuple[bool, str]:
336	    """Verify the ``From:`` domain is authenticated; returns ``(authenticated, reason)``.
337	    ``From:`` is attacker-controlled (GHSA-rxqh-5572-8m77); the only trustworthy signal is the
338	    ``Authentication-Results`` header stamped by the *receiving* server. It prepends, so the FIRST
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
379
380
381	def _extract_attachments(msg: email_lib.message.Message, skip_attachments: bool = False) -> List[Dict[str, Any]]:
```

**Not shown above — explore these names for their source**

- pm/package.py: verify:144, verify:262, Package:47, binary:141, _binary_reason:153, missing_reason:88, +16 more
- pm/packages.py: verify:90, verify:152, verify:828, verify:180, Uv:190, Python:221, +22 more
- tools/send_message_senders.py: send:172, _telegram_send_text_chunk:168, _send_telegram_message_with_retry:85, _is_telegram_thread_not_found:99, _sanitize_error_text:47, _strip_mdv2_safe:138, +3 more
- scripts/releases/stable.py: verify:621, stable_context:496, emit:563, main:898, check_claim:453, stage_receipt:334, +7 more
- hermes_cli/onepassword_secrets_cli.py: verify:257, cmd_token:248, _op_whoami:377, _DOCS_URL:38, _op_cfg:44, _DEFAULT_TOKEN_ENV:37, +1 more
- hermes_cli/secrets_cli.py: verify:288, cmd_token:278, _list_projects:439, _NOT_BSM_TOKEN_WARNING:32, _load_bw:42, _bw_cfg:229, +1 more
- pm/install.py: _entry_verified:253, _publish_entry:292, _entry_current:323, _install:358
- hermes_cli/_secrets_common.py: cfg_str:33, rotate_token:119, require_enabled:58, print_status_panel:67, print_table:77, prompt_index:156
- acp_adapter/server.py: _register_session_mcp_servers:427, _session_response_fields:579, load_session:623, resume_session:633, set_session_model:1022, set_session_mode:1060
- scripts/releases/darwin.py: publish_mac_feed:132, parse_mac_feed:27, finalize:172
- ... and 36 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
