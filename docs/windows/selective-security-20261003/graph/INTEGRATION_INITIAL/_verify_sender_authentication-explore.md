**Exploration: _verify_sender_authentication**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `verify` (scripts/verify_desktop_theme.py:11) — 1 caller in `scripts/verify_desktop_theme.py`; no tests found within 3 caller hops
- `verify` (plugins/shinka-osint/core.py:450) — 3 callers in `plugins/shinka-osint/cli.py`, `plugins/shinka-osint/core.py`; no tests found within 3 caller hops
- `verify` (downstream/implementation_router/kernel.py:147) — 1 caller in `downstream/implementation_router/kernel.py`; tested via callers: `tests/implementation_router/test_kernel.py`
- `verify` (downstream/control_mcp/auth.py:99) — 10 callers in `downstream/control_mcp/http_boundary.py`; tests: `tests/control_mcp/test_auth.py`

**Relationships**

**calls:**
- verify → get
- get → require_access
- get → valid_id
- get → exists
- get → _connection
- get → execute
- get → _public
- main → get
- _named_custom_provider_catalogs → get
- _edit_approval_policy_for_state → get
- _wait_then_refresh → get
- _run_agent → get
- _cmd_tools → get
- set_config_option → get
- get_session → get
- ... and 180 more

**instantiates:**
- verify → CheckReceipt
- run_workflow → NativeEngineeringHost
- test_real_kernel_stops_and_journals_only_safe_failure_metadata → NativeEngineeringHost
- run → _Hold
- run → VerificationRequest
- result → RunResult
- verify → ControlError
- verify → ControlContext
- build_control_mcp_host → ResourceVerifier
- decode_request → ControlError

**references:**
- call_tool → _ISOLATED_TOOLS
- register → shinka_osint_command
- run → _DIGEST
- decode_request → ControlError
- canonical_json → ControlError
- __call__ → ControlError

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`plugins/platforms/email/adapter.py`** — calls(calls), strip(calls), _verify_sender_authentication(function), split(calls)

```python
386	)
387
388
389	def _verify_sender_authentication(
390	    msg: email_lib.message.Message,
391	    from_addr: str,
392	    *,
393	    authserv_id: str = "",
394	) -> Tuple[bool, str]:
395	    """Verify that the message's ``From:`` domain is authenticated.
396
397	    The ``From:`` header is attacker-controlled and is never authenticated by
398	    IMAP delivery, so an allowlist keyed on ``From:`` alone is trivially
399	    spoofable (GHSA-rxqh-5572-8m77). The only trustworthy signal is the
400	    ``Authentication-Results`` header that the *receiving* mail server (the one
401	    we IMAP into) stamps after running SPF/DKIM/DMARC. That header is prepended
402	    by our own server, so the topmost instance is the one we trust; any
403	    ``Authentication-Results`` an attacker injected into the body of their
404	    message sorts below it.
405
406	    Returns ``(authenticated, reason)``. ``authenticated`` is True when:
407	      * a DMARC pass is recorded for the From domain, OR
408	      * an SPF pass aligned with the From domain, OR
409	      * a DKIM pass aligned (``header.d``) with the From domain.
410
411	    When no ``Authentication-Results`` header is present at all, we return
412	    ``(False, "no Authentication-Results header")`` — fail-closed. Operators
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
467
468
469	def _extract_attachments(
```

**Not shown above — explore these names for their source**

- downstream/implementation_router/kernel.py: verify:147, CheckReceipt:79, HostPort:119, run:264, admit:133, lease:143, +18 more
- apps/desktop/scripts/diag-scroll-reset.mjs: send:50, evalP:56, wheelUpSweep:143
- plugins/implementation_router/host.py: verify:250, NativeEngineeringHost:29, cancellation_requested:65, _check_guards:189, _record_check_evidence:173, __init__:30, +10 more
- plugins/shinka-osint/core.py: verify:450, handle_verify:510, handle_slash:528, _scenario_records:175, status:293, analyze:335, +3 more
- apps/desktop/scripts/diag-jump.mjs: send:16, evalP:22, diag-jump.mjs:1
- downstream/control_mcp/auth.py: verify:99, ResourceVerifier:65, _grant:89, __init__:66, revalidate:141
- apps/desktop/scripts/click-session.mjs: send:15, click-session.mjs:1
- scripts/verify_desktop_theme.py: verify:11, verify_desktop_theme.py:1
- downstream/control_mcp/contracts.py: require_access:80, valid_id:26, decode_request:145, ControlError:16, ControlContext:31, canonical_json:129
- plugins/shinka-osint/bridge.py: call_tool:301, _call_tool_isolated:264, _load_mcp_module:182, _ISOLATED_TOOLS:50, save_root:135, save_default_example:153
- ... and 41 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,014 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
