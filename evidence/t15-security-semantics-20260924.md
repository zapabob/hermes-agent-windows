# T15 Security Center semantics evidence

## Source and scope

Repository: `zapabob/hermes-agent-windows`.

Worktree: `H:\hermes-worktrees\t15-security-semantics`.

Branch: `codex/t15-security-semantics`.

Base: `05889e42e0f773e2d54c64a8fd9d056e0d170df4`.

Implementation commit: `9869602a084301021bd884c40d0643d6cf22aade`.

The implementation is limited to typed security projections, deterministic scan policy, lazy vault initialization, execution-gate enforcement, the terminal refusal message, and focused tests. The source commit preserves the legacy `verdict`, `action`, and `cached` fields. It contains no Desktop, Go, llama, or operational configuration changes.

## TDD evidence

The first actual terminal-boundary RED assertion expected the mocked `_create_environment` executor not to run. It failed because the terminal path called it once after a YARA score of 80 and a ClamAV error had been projected as `SCAN_ERROR` / `blocked_pending_review`. The expanded RED run had seven failing assertions covering execution reaching the executor, malicious detection loss, absent typed fields, quarantine failure losing detection, stale cache allowlist action, absent API fields, and status-created vault state.

The tests use only synthetic findings and inert files. The terminal test calls `terminal_tool` with `_create_environment` mocked and proves it is not called for a malicious result with an engine error or when no authoritative scanner is available. Separate assertions prove that only the explicit `allowlisted` action allows malicious content, current allowlist state is reevaluated on cache hits, and quarantine failure leaves the result malicious and blocked.

## Verification

Focused command:

```text
uv run --frozen --extra dev python -m pytest tests/security/test_t15_security_semantics.py tests/security/test_security_center.py tests/security/test_security_api.py -q -k 'not high_confidence_detection_is_encrypted_before_source_removal and not restore_rescans_and_never_overwrites and not quarantine_tamper_is_rejected_and_metadata_is_complete and not real_clamav_detects_eicar_when_required and not bundled_yara_core_detects_eicar'
```

Result: `52 passed, 5 deselected`. The two live-engine EICAR tests were deselected. No live malware was downloaded or created, and no real scanner run is claimed. Three existing vault/restore cases were also excluded by the recorded command.

Ruff 0.15.10 passed on the changed security modules, terminal tool, and focused API/tests. Ty 0.0.21 passed on the changed security modules and focused tests. A separate broad Ty run including the legacy `tools/terminal_tool.py` module reported pre-existing diagnostics elsewhere in that module; no diagnostic was on the changed terminal lines. `git diff --check` passed. The source worktree was clean at the implementation SHA.

## CodeGraph after-index

Pinned CodeGraph 1.6.0 was invoked with the explicit Node 22.23.2 runtime and shim. The sync exited successfully and reported one changed file (17 modified nodes). The exact post-sync `status --json` snapshot is in `evidence/codegraph/T15-9869602a-after.json`.

Status: 8,914 files, 190,966 nodes, 611,338 edges, zero pending added/modified/removed files, zero pending references, complete state, no worktree mismatch, and no reindex recommendation. H had 21,409,181,696 bytes free at final verification, above the 8 GiB floor. The serialized CodeGraph writer was released to T09 after this status check.

## Remaining runtime and integration gates

This is local implementation and test evidence only. Real ClamAV and YARA runtime behavior was not exercised. `SecurityService.status()` no longer initializes the quarantine vault, but its current `versions()` path can still spawn `clamdscan` or `clamscan --version`; T16 owns that remaining read-path process behavior, so status is not claimed to be fully side-effect-free.

The Desktop TypeScript `SecurityScanResult` projection still lacks `file_verdict`, `engine_health`, and `execution_decision`; this UI projection gap is recorded for T19 and was not changed here. Independent review of implementation commit `9869602a084301021bd884c40d0643d6cf22aade` is pending.
