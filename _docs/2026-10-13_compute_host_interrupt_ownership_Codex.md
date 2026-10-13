# Preserve compute-host turn ownership through Stop and completion

Frozen upstream main: `63d0b94120027d487c9a5235b9ec64b696af1b26`. Related behavior changes: `3cda7a922a239bc2823c647ba875c512fe709767` (Stop during construction) and `53bc70c5ee8544040cd9f0708d25c0f55276a44b` (dead compute host). Local parent/recovery reference: `7e67be3e0dc28e22114315b3afb55bb3580170cc`.

## Behavior adapted

ADAPT stale-host Stop recovery into the existing Windows session implementation. Public Stop may clear an orphaned busy state and permit a fresh prompt only after checking registered turns, callbacks already taken for completion, and prompt admission ownership. A unique session owner prevents an old completion from clearing a successor. Admission cancellation is consumed before submission or after registration as appropriate; send failure retains cancellable local fallback.

Stop retains ownership until pending-card cleanup and approval denial finish. Completion is buffered while dispatch or Stop owns settlement; cleanup failures retain busy state and can be retried. Supervisor callbacks, transport calls, approval cleanup and queued dispatch execute outside the short state locks. Shared helper/WS orphan-reaper defaults and exception behavior remain unchanged. Probe and callback uncertainty fail closed; automatic recovery from a completion callback that raises is not claimed.

## Acceptance and review

The prior dead-host behavioral RED was retained. Six deterministic cleanup-boundary failures preceded the cleanup repair. Final acceptance comprises 29 fresh passing cases (21 ownership/public-handler controls, 2 no-wait, 4 compute-host and 2 WebSocket timeout) plus one unchanged dead-host pass reused from the 19-case R3B run. Public controls cover stale Stop followed by fresh prompt submission, completion during dispatch/Stop cleanup, and cancellation after host-send failure with inline fallback.

The initial acceptance run recorded 28 passed and one failure: the existing compute-host test equated a Windows Python launcher PID with its child's PID. A sanitized probe confirmed the launcher behavior. The corrected test verifies the exact live child relationship, retains real seed/turn/delta/shutdown assertions, and restricts cleanup to the recorded owned child identity and launcher. Only that four-case file was rerun; it passed 4/4. The original failure log is preserved.

Tests used ROOT's native Windows Python and the existing process-per-file runner with `--jobs 1 --file-retries 0 --file-timeout 300 -q`, isolated fresh H-drive HOME/HERMES_HOME/temp/basetemp, UTC/UTF-8 and an environment allowlist without provider credentials. No live provider or full Desktop package acceptance is claimed.

One final CodeGraph sync indexed seven changed files; extraction version 25 was current with zero pending changes/references. Targeted mappings connect the public handler and orphan reaper to the shared helper and affected ownership/dead-host/no-wait tests. Separate Luna MAX review verified all seven final source/test hashes and returned specification and quality PASS for this bounded contract.

## Evidence and recovery

Evidence directory: `H:/Codex-v0216-archive/`. Exact source pins, commands and log hashes are in `V0217_SESSION_INTERRUPT_OWNERSHIP_FINAL_CLOSEOUT_20261013.md` (SHA256 `B63B9465E7255F7CBCCED315D7A7EF07882B2416F659301A0D670950C09E35EE`). Independent review: `V0217_SESSION_INTERRUPT_OWNERSHIP_INDEPENDENT_REVIEW_20261013.md` (SHA256 `F354E5182A3738E399A95DD3D4D16D1E1EE08C8AEFCCB25CD6BE3E9E2ADB3E8B`).

Raw evidence includes `V0217_SESSION_INTERRUPT_CLEANUP_R3_RED_20261013.log`, `V0217_SESSION_INTERRUPT_CLEANUP_R3B_GREEN_20261013.log`, `V0217_SESSION_INTERRUPT_OWNERSHIP_ACCEPTANCE_LUNA_GREEN_20261013.log` (the superseded 28/1 result despite its filename), and `V0217_SESSION_INTERRUPT_COMPUTE_HOST_PID_R1_GREEN_20261013.log`. Graph evidence is in `V0217_SESSION_INTERRUPT_OWNERSHIP_FINAL_CODEGRAPH_20261013.log` and `V0217_SESSION_INTERRUPT_OWNERSHIP_CODEGRAPH_MAP_20261013.log`. Parent guards and the local commit receipt preserve protected-state and exact staged/committed blob checks. Raw logs, databases, credentials and unrelated materials are excluded from the commit.

Recovery is a targeted revert on the isolated branch after checking later dependencies, using the parent above as the prior source. Do not reset PRIMARY or discard unrelated work. Complete frozen-delta adoption, model-selection UI semantics, local resource/memory and Windows execution contracts, actual isolated package acceptance and version 0.21.7 remain separate open requirements.
