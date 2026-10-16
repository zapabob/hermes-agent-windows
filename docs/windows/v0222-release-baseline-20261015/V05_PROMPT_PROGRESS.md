# Local stream prompt progress — 2026-10-16

This checkpoint fixes receiving-stream liveness for the A18/A19 prompt
progress contract and verifies existing explicit request compatibility under
A23. Starting local commit: af2b8279f643c267bf25b852093ed2a340187bef.
Frozen upstream comparison: d923a5eb487a17c0a68801bba9ef0f56c81040a8,
tree5a064077e8d1de9fc7a4b27efc04f0caa2cb06c0. Full V05 and the original
adoption campaign remain open. The exact source and evidence bindings belong
to [the scoped receipt](V05_PROMPT_PROGRESS.json).

Previously both the receive callback and assembly loop refreshed the stale
timer for every SDK frame. A local server could send the same progress value,
reverse its counter or send only empty assistant metadata and postpone the
watchdog indefinitely. The initial actual-SDK owned-peer RED reproduces four
assertion failures with one passing advancing-progress control.

The existing chat-completions owner now keeps a high-water mark per attempt.
Only a strictly increasing positive integer processed-token count can extend
the idle wait. Booleans, fractional/string/negative/zero values and invalid
optional totals do not advance it. A lower sample does not lower the mark,
so subsequent values below the prior maximum cannot masquerade as progress.
Increasing wall time, changing totals and repeated heartbeat metadata alone
grant no extension. A new attempt has its own counter.

Liveness is published in the receive callback before Relay processing, after
rechecking the attempt fence under its existing lock. The assembly loop does
not count that same frame again. Local progress-only and empty metadata
frames do not fabricate text, first-token callbacks or first-output diagnostic
counts. Usage/model identity is retained without granting idle time.
Real content, tool calls, reasoning, refusal, provider errors
and finish reasons preserve their existing assembly paths, including frames
which also contain progress metadata. Remote frame accounting is unchanged.

The test suite includes thirteen actual-SDK/Relay requests to finite owned
loopback SSE peers. Advancing prefill completes successfully after exceeding
the configured idle window; duplicate/backward/zero/malformed/heartbeat
sequences trip the stale boundary, increment its breaker and do not deliver
the peer's late content, including when constant usage is attached. Mixed
output and actual response usage are preserved. Twenty-four additional
boundary cases cover integer validation, high-water behavior and preservation
of ordinary output/error handling. Synthetic credentials/model names and
isolated home/temp directories are used; no live model or service is involved.
The existing abort implementation can report no TCP sockets found. These
finite-peer checks do not qualify immediate backend cancellation or a blocked
native read's release on every transport.

No return_progress field is added automatically. Existing explicit extra_body
True, explicit False and unrelated caller fields survive on the actual wire;
an unknown custom endpoint without that setting receives no new extension.
The existing provider/request-overrides owners remain authoritative. ROOT
does not contain the frozen release's managed-runtime capability/ownership
contract. Locality and a llama.cpp family probe alone do not establish
return_progress support. Managed automatic requesting, auxiliary requests and
end-to-end surface dispatch remain mandatory unclosed work. This receiving
slice must not be used to mark all of A18/A23 or V05 complete.

The final scoped receipt records the fresh native Windows subprocess results,
existing partial/continuation, retry, request-client reuse, stale recovery and
Relay regressions, deliberate in-memory anti-fixes, actual CodeGraph and an
independent source-bound review. Qualification uses Python-process containment
for external DNS/connects and writes outside the workspace. Blocked attempts
are reported explicitly; this is not a whole-OS observer.
Earlier failed/intermediate runs remain
private and unaccepted. The existing Python3.12.13 environment is retained.
Ordinary suites use the previously verified test overlay. The additional
Anthropic SDK/Relay regression uses a separate test-only target containing
the exact locked anthropic0.125.0 and docstring-parser0.18.0 wheels, since
the optional SDK is absent from the base environment. Its original skip is
retained and replaced in accepted results only by an actual zero-skip SDK
run on the same source. This existing SDK regression uses MockTransport;
it is distinct from the thirteen actual loopback HTTP cases above.
Verified wheel/runtime payloads cover openai2.54.0 (1503 files),
anthropic0.125.0 (1271) and docstring-parser0.18.0 (10). Artifact hashes,
sizes and direct installed requirement compatibility are checked before
SDK execution. The base environment and product lock are unchanged.
There is no full
project dependency-closure or formal MILSPEC-compliance claim.

The protected primary, existing unrelated WIP, base packages, operator
configuration, models and services are retained. Only this stream owner, its
new regression file and two new public checkpoint files may be committed.
The unchanged stale shared Lefthook launcher is disabled only for the local
commit command with LEFTHOOK=0 and is not counted as a passed hook. No push,
PR, main integration, version bump, release or deployment occurs. A later
authorized rollback uses a reviewed inverse commit.

Remaining gates include managed automatic capability binding, auxiliary and
closed-compression fences, awake-clock qualification, status/autoload,
memory budgets, real model completion and the remaining original units.
Eight-hour soak and three actual sleep/resume cycles remain unexecuted;
no dedicated Windows PC/VM is available. User workstation sleep/reboot is
not used to substitute for that missing environment.
