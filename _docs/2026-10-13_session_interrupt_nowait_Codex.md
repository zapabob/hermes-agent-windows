# Local session Stop without deferred initialization

Frozen upstream main: `63d0b94120027d487c9a5235b9ec64b696af1b26`. Relevant upstream change: `3cda7a922a239bc2823c647ba875c512fe709767`. Local parent and recovery reference: `62fd33c61ec567c143511914d5fbc4471cfc197a`.

## Accepted contract

ADAPT the local-session `session.interrupt` handler to use the session already resolved by `_sess_nowait`. It no longer enters `_sess`, which can start or wait for deferred agent construction. The existing shared interrupt helper retains cancellation, queued-input disposal and generation advancement. Pending and failed initialization can be stopped without waiting. No compute-host, process ownership or shared-helper behavior is changed by this commit.

## Evidence

The public-handler R1 RED reproduced the local deferred-wait failure before the product change. The same run also reproduced a separate dead-host defect; that defect is not fixed or accepted here. Setup failures preceding R1 are not product RED evidence.

Final acceptance is two corrected new cases in R3 plus five unchanged existing Stop cases from R2. All seven selected cases passed. R3 ran in 3.2 seconds; R2's original seven-case run took 11.6 seconds. A stale variable reference inside the test's deliberately blocked wait helper was removed after review; only the changed two cases were rerun. Existing regressions cover queued-input disposal, stopping before agent readiness and explicit-stop protocol compatibility.

Tests used ROOT's native Windows Python and `scripts/run_tests_parallel.py`, fresh process per file, an explicit file/filter selection, `--jobs 1 --file-retries 0 --file-timeout 300 -q`, UTC/UTF-8, isolated HOME/HERMES_HOME and removed provider credentials. Logs and temporary state stayed on H.

CodeGraph mapped the public handler and shared helper. An initial incremental sync covered the source and two new tests; after the test correction one justified incremental sync refreshed that test. Final graph: 9,177 files, complete, no pending changes or references, extraction version 25 current. The separately retained dead-host RED test is indexed but is not accepted or committed.

Separate Luna MAX review returned specification and quality PASS for this bounded local-session contract. The reviewer verified final source/test pins and reused the focused evidence without rerunning tests.

## Local evidence and recovery

Evidence lives under `H:/Codex-v0216-archive/`: `V0217_SESSION_INTERRUPT_NOWAIT_CLOSEOUT_20261013.md`, `V0217_SESSION_INTERRUPT_NOWAIT_INDEPENDENT_REVIEW_20261013.md`, `V0217_SESSION_INTERRUPT_R1_RED_20261013.log`, `V0217_SESSION_INTERRUPT_NOWAIT_R2_GREEN_20261013.log`, `V0217_SESSION_INTERRUPT_NOWAIT_R3_GREEN_20261013.log`, and `V0217_SESSION_INTERRUPT_NOWAIT_R3_CODEGRAPH_20261013.log`. The local commit receipt binds exact files, Git blobs, protected state and hook outcome. No raw logs, database, credentials or unrelated working documents are committed.

Recovery is a targeted revert of this unit on the isolated branch after checking later dependencies; the parent above identifies the prior source. Do not reset PRIMARY or discard unrelated work.

Compute-host stale recovery remains OPEN: completion callbacks and dispatch admission can temporarily be absent from the supervisor pending map. Astra identified both gaps but exhausted its bounded repair allocation before implementation. Its proposed ownership design is unvalidated and retained in `V0217_SESSION_INTERRUPT_ASTRA_REPAIR_20261013.md`. No full cancellation, packaged Desktop or overall 0.21.7 completion is claimed by this unit.
