# PR #160 review remediation — 2026-09-29

## Scope and delivery state

The local candidate addresses the supplied F1–F4 review of PR #160. It remains uncommitted in the existing `n53-review-fix` worktree. No commit, push, merge, PR comment, or PR state change was performed. Local verification is not a new reviewed Git head or release approval.

The inspected HEAD is `eb4cea919502caf0e1c21d4ab3366b1e1610eeb7`, on `cursor/n53-on-pr158-20260929`. The requested parent/base is `86d3149599a2be48a1a66903ba7e3e3a12c819ef`, on `codex/n52-gateway-identity-20260928`.

Five paths already contained uncommitted F1–F4 candidate repairs at the start: `gateway/status.py`, `hermes_cli/update_cmd.py`, and the concurrent-quarantine, pause-recovery, and relaunch-budget test modules. Those changes were preserved and verified. This session supplemented them with the Windows wedged-stop route correction, persistent manual-stop failure accounting, pointer-sized native-call arguments, partial-rollback accounting, and eight additional regression cases. It did not originate all of the existing candidate changes.

Applied guidance: repository AGENTS.md; the canonical pre-implementation prompt where compatible with stronger instructions; implementation-start, Python, application-development, security, and engineering SOPs; receiving-code-review, systematic-debugging, test-driven-development, requesting-code-review, and verification-before-completion skills. Self-review remained recommendation-only; no governance or memory files were changed.

## F1 — original worker identity owns launcher nomination

`_venv_launcher_ancestor_identities` receives the workers' original creation-time guards. It checks each worker before and after reading the parent relationship and the parent's creation time. A stable parent alone is insufficient. Parent identity is still revalidated at the force-stop boundary. Regression cases cover worker reuse before the parent walk, reuse during the walk, parent reuse, the unchanged-worker positive control, and the actual pause candidate set. SCM descendants remain excluded from ordinary launcher nomination.

## F2 — every late Windows stop retains its original guard

Strict discovery failure leaves unverifiable manual candidates untouched. The late sweep uses captured guards rather than PID-only signals or a freshly adopted replacement identity. A refused guarded stop now remains in the incomplete set instead of disappearing from both result sets.

An additional caller defect survived the incoming repairs: the mapped-gateway wedged-loop branch entered `_escalate_wedged_gateway`, whose initial signal is PID-only. `_stop_manual_gateway_for_update` now sends every Windows candidate through `_stop_windows_manual_gateway` with the discovery-time guard. POSIX drain and wedged-loop behavior remains separately exercised. The survivor sweep also reuses the original guard. Failed stop requests do not enter successful killed/relaunched bookkeeping.

`manual_restart_incomplete` remains set for strict discovery errors, refused mapped stops, unresolved sweep candidates, and refused survivor stops. A successful recovery of another supervised service cannot clear that independent manual failure. Receipt accounting includes the incomplete state.

## F3 — uncertain liveness cannot authorize replacement

When psutil cannot be imported, Windows native liveness keeps access-denied, unknown OpenProcess errors, and WAIT_FAILED pending. Only affirmative exit evidence permits the old incarnation to be considered gone. Handles are closed after waiting.

The incoming native loader omitted argument types. An added test exercised real ctypes conversions through harmless native callbacks and reproduced an OverflowError for a large handle at both WaitForSingleObject and CloseHandle. The loader now declares HANDLE-sized argument and return types, with DWORD/BOOL parameters matching the native interfaces. The test does not operate on a real OS process handle.

Reference contracts consulted: Microsoft OpenProcess and WaitForSingleObject documentation, and the Python 3.11 ctypes function-prototype documentation. Sources: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess ; https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject ; https://docs.python.org/3.11/library/ctypes.html#specifying-the-required-argument-types-function-prototypes .

## F4 — interrupted rollback remains explicitly unverified

A detached watcher being armed is not a completed rollback. On pause failure, unobserved watcher outcomes are reported in the raised error or KeyboardInterrupt note and recorded as a failed `windows_gateway_pause_rollback` receipt step. The token retains `rollback_recovery_pending` and `rollback_recovery_detail`.

The same reporting now runs after a partial restart failure, so an error restarting one sibling does not hide a watcher already armed for another. Failed unmapped entries are not described as successfully handed off. The watcher still refuses duplicate launch when its 120-second deadline expires while the original incarnation drains for 180 seconds. The tests advance a virtual clock; they do not wait three real minutes or start a production gateway. This is explicit incomplete-recovery reporting, not a claim that availability was automatically restored.

## Verification on the final working files

Final scoped run: **20 files, 246 tests passed, zero failures, exit 0**, 77.1 seconds, two workers, no file retries. The repository's per-file runner created a fresh pytest interpreter for each module. TEMP/TMP and duration outputs were directed into this worktree. Provider/test isolation remained governed by the repository fixtures. The suite includes real Windows test-owned sleeper processes; it does not prove a production SCM stop/restart or packaged Desktop launch.

| Test module under tests/hermes_cli | Passed |
| --- | ---: |
| test_update_pause_recovery.py | 12 |
| test_update_concurrent_quarantine.py | 41 |
| test_windows_relaunch_verify_budget.py | 34 |
| test_update_review_boundary_regressions.py | 6 |
| test_update_fleet_check_fail_closed.py | 12 |
| test_update_fleet_probe_resume_token.py | 8 |
| test_windows_gateway_cold_start_desktop_lifecycle.py | 7 |
| test_gateway_restart_watcher_identity_windows.py | 16 |
| test_update_orphan_backend_reap.py | 17 |
| test_update_interrupted_recovery.py | 2 |
| test_update_restart_recovery.py | 17 |
| test_update_wedged_gateway.py | 17 |
| test_windows_update_restart_reconciliation.py | 4 |
| test_update_gateway_launcher_refresh.py | 2 |
| test_update_fleet_restart_pending.py | 13 |
| test_update_fleet_restart_timeout.py | 9 |
| test_update_handoff_backend_reap.py | 8 |
| test_venv_holder_windows_live.py | 11 |
| test_stderr_timestamp.py | 8 |
| test_desktop_lifecycle_windows_live.py | 2 |

Ruff 0.15.10 check passed on the six changed/new Python paths. Formatting checks passed on the new boundary test module and the edited pause-recovery test module. `git diff --check` passed. The eight additional tests were first observed failing: four missing routing-helper cases, the dropped stop-failure case, the ctypes handle case, and two rollback-state cases. Their subsequent green results are retained separately.

Fresh in-memory mutation checks on the final source killed **5/5** mutants: removed worker revalidation, restored PID-only sweep, restored the Windows wedged bypass, native liveness failing open, and omitted rollback-handoff reporting. Each mutant ran in a separate disposable interpreter and failed its intended behavioral regression. Working source files were never replaced for these checks; SHA-256 before and after matched. The final JSON contains each child's actual pytest exit code of 1. A native output-polling error prevented reading the outer process's final exit directly; persisted per-mutant results and final source hashes were read independently.

Evidence directory: `tmp/pr160-verification-20260929T023303/`. Primary records are `final-suite.log`, `final-suite.exit`, `additional-red.log`, `f2-green.log`, `f3-green.log`, `f4-green.log`, and `mutation-final/mutation-results.json`. The mutation driver is `verify_review_mutants.py`; the final run sets `PR160_MUTATION_EVIDENCE_ROOT` to the `mutation-final` subdirectory. Earlier results were retained.

## Wider command-test limitation

The initial 21-file run also included `test_cmd_update.py`. That file exceeded its 180-second cap and the runner exited 1. Its progress must not be represented as a passing full-command suite. A narrowed run of `TestCmdUpdateBranchFallback::test_update_on_fork_checks_upstream_when_origin_up_to_date` also exceeded a 60-second diagnostic cap. Faulthandler located the wait in `hermes_cli.main._run_npm_watching_for_engine_failure`, through `_update_node_dependencies` and `_repair_node_deps_on_current_checkout`, before the late restart phase.

A further diagnostic loaded the original HEAD's two affected product modules in memory and compared the candidate. In both cases the selected test reached the same npm execution boundary. That diagnostic deliberately raised a sentinel before npm execution; both pytest invocations therefore exited 1 by design, and neither is counted as a pass. It establishes that the boundary is also reached on the original head, not that the full original suite was completed. No tests were skipped or rewritten to conceal this timeout. Records: `bounded-suite.log`, `cmd-update-diagnostic.log`, `npm-boundary-comparison.json`, and the corresponding original/candidate logs. Driver: `diagnose_cmd_update_baseline.py`.

## Independent source binding

The following SHA-256 values were calculated from raw `git cat-file blob` bytes at HEAD, independently of the PR text. All four matched the supplied review values.

| Original-head path | SHA-256 |
| --- | --- |
| hermes_cli/update_cmd.py | f32ac816f5d6147c2138b75d1050c68f96965e2839560c857937d9bafca0d18f |
| tests/hermes_cli/test_update_concurrent_quarantine.py | 88e2af92c41b828fdc1fd454c5f05de2a7e8e6188ca9a856489ad6f76c6b7f90 |
| tests/hermes_cli/test_windows_relaunch_verify_budget.py | abbf9090b73d70aa64c4bfee9ae379e56821c5fb8665f0edf76e649e73681f29 |
| tests/hermes_cli/test_update_pause_recovery.py | ba22af34ed9bdbef5e1dbe13d58e7caef5db0c298725a0510dc00054a01e1030 |

The following values bind the **raw final working-file bytes**, including their line endings. They are not hashes of a new commit; no new commit exists.

| Working-file path | SHA-256 |
| --- | --- |
| gateway/status.py | 4d1cd34cfe78c0321cca340d58484aa6d43b6e22b9ef74738d3fae2c2fa9887b |
| hermes_cli/update_cmd.py | 889d7ce9db5402522e33ec05ef28c638abc12e993bdb8beaf2f1211095c545b6 |
| tests/hermes_cli/test_update_concurrent_quarantine.py | 159a27f2646ec0d7bf67c1a7a1a0f76edade0e0bea7feb9b896e0feb1da26183 |
| tests/hermes_cli/test_update_pause_recovery.py | 8a5473a8d952ccd9764bdd73d17a29923d5270928d939d5a1120ffc8b43902b7 |
| tests/hermes_cli/test_windows_relaunch_verify_budget.py | 36462c442f2ee2ce8e071941ce8442797d08a29644f9a9d21022912657267847 |
| tests/hermes_cli/test_update_review_boundary_regressions.py | aeefc0239a19e99dffdce953943f5112d4b63a618330bf059964cf78f52b4460 |

## Open gates and operational limits

CodeGraph execution was attempted and rejected with: `This tool call was blocked by OpenAI because we couldn't determine the safety status of the request.` No current graph result is claimed, and the blocked action was not retried through an alternate tool. Two process-output polls encountered the same error; saved test/mutation records were subsequently read where available.

The requested independent read-only reviewer ended with: `stream disconnected before completion: ChatGPT did not confirm that the prompt was sent. Check the ChatGPT tab before continuing.` No independent review verdict was received. The old review's approval state must not be upgraded on this basis.

No new-head cloud CI, main integration, production fleet health, live SCM recovery, release readiness, or whole-U1 parity is claimed. The original main checkout and its unrelated changes were preserved. The new test file is untracked; this log and temporary evidence may be ignored by existing repository exclusions, so a plain tracked-file diff is not the entire deliverable.

For rollback, preserve the incoming five-file dirty state. Do not restore these paths wholesale to HEAD: doing so would also remove repairs that predated this session. Reverse only the supplemental hunks after reviewing their ownership. No rollback, cleanup, broad drive scan, or production restart was performed.

Self-review-event: qa_defect. Helper-level passes alone had missed a Windows caller entering a PID-only wedged-stop path, and a wider test run exposed an npm execution-boundary gap. Future review should inspect every destructive caller and keep full-command test outcomes distinct from scoped safety-contract tests. Governance changes were not applied.
