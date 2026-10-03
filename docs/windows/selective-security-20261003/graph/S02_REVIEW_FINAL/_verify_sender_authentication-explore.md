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

**`plugins/platforms/email/adapter.py`** — calls(calls), _verify_sender_authentication(function), split(calls), strip(calls)

```python
422	                           r'|(?:%s|[^\s"])+' % (_QUOTED, _QUOTED), re.IGNORECASE)
423
424
425	def _verify_sender_authentication(
426	    msg: email_lib.message.Message,
427	    from_addr: str,
428	    *,
429	    authserv_id: str = "",
430	) -> Tuple[bool, str]:
431	    """Verify that the message's ``From:`` domain is authenticated.
432
433	    The ``From:`` header is attacker-controlled and is never authenticated by
434	    IMAP delivery, so an allowlist keyed on ``From:`` alone is trivially
435	    spoofable (GHSA-rxqh-5572-8m77). The only trustworthy signal is the
436	    ``Authentication-Results`` header that the *receiving* mail server (the one
437	    we IMAP into) stamps after running SPF/DKIM/DMARC. That header is prepended
438	    by our own server, so the topmost instance is the one we trust; any
439	    ``Authentication-Results`` an attacker injected into the body of their
440	    message sorts below it.
441
442	    Returns ``(authenticated, reason)``. ``authenticated`` is True when:
443	      * a DMARC pass is recorded for the From domain, OR
444	      * an SPF pass aligned with the From domain, OR
445	      * a DKIM pass aligned (``header.d``) with the From domain.
446
447	    When no ``Authentication-Results`` header is present at all, we return
448	    ``(False, "no Authentication-Results header")`` — fail-closed. Operators
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
504
505
506	def _extract_attachments(
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

> **Explore budget: 3 calls for this project (9,016 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
