# U02 OAuth save and retirement closure — 2026-10-16

The local save/retirement change passed 558 checks, with 21 explicitly qualified platform/privilege skips and no final failures or errors. The actual SDK loopback E2E passed all 71 native callback, relay and REST cases. This closes this OAuth race slice; it does not certify the entire Windows adoption/release campaign.

## Resulting behavior

Provider leases are captured before an operation's network waits and preserved across SDK generator yields. Retirement, replacement and restore invalidate an old operation. Storage validates the provider, saved-config revision and credential generations before committing, and publishes SDK tokens/expiry under that same synchronous commit boundary. A stale result cannot overwrite a newer writer or recreate removed credentials. A newer provider's cache identity survives old-flow rollback; changed files reload through the existing disk-watch path.

The existing config/storage owners share a bounded native process lock and a persistent counter-only journal per physical Hermes home. Canonical config serializers, the direct plugin config writers and credential import participate. Config A→B→A and same-byte credential writes remain distinguishable. Windows CONFIG.YAML aliases enter the same boundary. The journal and stable lock are excluded from backup/export/import, including older archives. Valid snapshots can repair malformed config. Issuer maintenance advances the owning storage's generations without granting old in-flight operations a new lease.

## Verification

OAuth regression: 271 passed, 1 skipped, fresh Python subprocess per file. Config writers, plugins, backup and doctor: 216 passed, 20 skipped. Actual SDK E2E: 71 passed, zero skipped. Native checks include real Win32 deny-delete handles, two-process writers, actual msvcrt byte-range lock contention followed by CAS recheck, and Windows case aliases. All 10 enforcement-removal mutations were detected through failing assertions; source files were unchanged by those disposable interpreter mutations. Ruff and git diff whitespace checks passed.

CodeGraph 1.6.0 indexed 9188 files, 198677 nodes and 626951 edges, with zero pending changes/references. Independent review identified five concrete issues; each was fixed and independently rechecked. The final source hashes, exact per-file counts, skip reasons, review coverage and artifact digests are in [verification.json](verification.json). Runtime: native Windows Python 3.12.13, MCP 2.0.0.

The symlink test now uses the repository's existing require_symlinks capability marker. The backup clock stub is scoped to its module, and snapshot size is asserted from actual bytes so Windows newline encoding is respected. The E2E stale-response assertion now requires zero setter attempts, while retaining real issuer redemption, settlement and absence-of-token checks. Earlier failed runs remain preserved in private evidence and are not counted as passes.

The shared Git hook is a stale Lefthook launcher with no project configuration or referenced executable. Its fallback can invoke package runners. For this one local commit the launcher is disabled with LEFTHOOK=0; the shared hook is retained unchanged, no dependencies are fetched, and hook execution is not claimed as a passed check. The actual checks above and an explicit staged-file/source audit govern this commit.

## Boundaries and recovery

This is a local commit on codex/v0216-semantic-20261010 based on ec5af6f193ca9ad799d652838802dfe83ea4dc32. The protected primary main checkout, operator configuration and live services were not changed. Existing unrelated WIP and historical BLOCK evidence remain outside this commit. No dependency update, cloud CI, push, PR, main merge, version change, release or deployment is claimed.

The cross-process contract covers writers using the repository transaction. Arbitrary external edits and deliberate journal deletion are outside that protocol. Do not restore or reset the monotonic journal while clients are running. A future authorized code rollback should use a reviewed inverse commit and retain the journal; no rollback was performed here. The whole-campaign eight-hour soak and three physical sleep/resume cycles remain unqualified because no dedicated test PC/VM was available.
