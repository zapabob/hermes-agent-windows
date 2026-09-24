# T06 native AppContainer correction review

Reviewed diff: working tree relative to preparatory commit `2ca66d9a1b5765f553c1ce75eee45e65e7249b59`.  
Scope: read-only review of the correction for profile recovery, trusted ACL utility resolution, ACL teardown, fixture lifecycle, and the proposed one-time gated experiment.  
No test, CodeGraph command, AppContainer profile API, or ACL operation was run by this reviewer.

## Skill-perspective check

The available `code-review-and-quality` skill was applied. `remove-ai-slops` and `programming` were checked at their expected local locations and were unavailable. Their requested review criteria were applied directly: the regression tests target a real unsafe recovery interface and the executable-resolution boundary; they are not deletion-only, tautological, prompt-fragile, or implementation-constant tests. The correction introduces no unnecessary production parsing or abstraction.

## Re-review of prior HIGH findings

### Forged cleanup-marker deletion — resolved

The cleanup options have been removed from `tests/windows/conftest.py`. The old marker-controlled deletion branch is removed from `tests/windows/test_delegated_execution_boundary.py`; the only `DeleteAppContainerProfile` call is the session fixture's in-process finalizer at lines 322-344, after its own successful `CreateAppContainerProfile` call at lines 297-305. The marker path is now deterministic and diagnostic only at lines 347-375. `test_removed_profile_cleanup_switch_is_rejected_during_collection` at lines 61-90 verifies that both removed options fail before collection. An interrupted run can leave a marker and profile, but there is no test command that converts either into deletion authority.

### Mutable `SystemRoot` for `icacls.exe` — resolved

ACL helpers at lines 469-498 now call `_trusted_icacls_executable`. Lines 501-531 obtain the system directory through `GetSystemDirectoryW`, reject remote/non-local results, resolve `icacls.exe` strictly, and validate it is the expected regular file directly inside that directory. `test_acl_helper_ignores_mutable_systemroot` at lines 93-143 sets a synthetic `SystemRoot` and verifies both the grant and revoke utilities still select the Win32-derived executable. This removes the prior ambient-environment executable-selection risk.

## ACL and fixture lifecycle

`native_python_profile` registers revocation before the first grant at line 242, so a partial grant failure still schedules cleanup. Its finalizer calls `_revoke_test_access` only against the current pytest temporary root. Both grant and revoke independently resolve the target and require it to be within that root (`:469-498`). The passed `icacls` invocation removes only grant ACEs for the AppContainer SID and remains recursive only within the H-drive test root.

For profile-gated tests, function-scoped `native_python_profile` teardown occurs before the session-scoped AppContainer fixture teardown, so ACL revocation and owned-process closure precede the one automatic profile deletion attempt. The process wrapper also kills the job and closes its handles on context exit. An abrupt process termination can still leave an ACE inside the named H-drive pytest directory or leave the named profile plus a diagnostic marker; this is correctly recorded as an operational recovery condition rather than silently remediated by a later test command.

## Remaining findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

None.

### LOW

1. The corrected tests and CodeGraph after-index are execution evidence that must be supplied by the executor; this review did not run them. The positive AppContainer probes, including actual profile deletion behavior, remain unverified until the approved trial completes.

2. `downstream/platform/windows/delegated_execution.py:575-588` still derives the child `SYSTEMROOT`/`WINDIR` values from the parent environment. That is outside the ACL-mutator fix and can cause the child to fail under a malformed parent environment; it does not select the ACL tool or grant a child additional authority. Treat it as future production-boundary hardening, not a block on the isolated trial.

## Approval and integration recommendation

`codeQualityStatus`: **CLEAR** for the reviewed correction, conditional on the executor's reported focused tests and CodeGraph after-index succeeding at the exact corrected commit.  
`recommendation`: **APPROVE** the correction for integration and, after those evidence gates, **APPROVE ASKING THE USER** for one narrowly described real-profile trial.

The approval request must state the fixed profile name `HermesDelegated-T06Pytest-20260924`; that the test creates and normally deletes current-user AppContainer storage outside H:; that its ACL changes and any residual ACEs are confined to the supplied H-drive pytest directory; that it starts only local loopback test servers; and that an interrupted/failed deletion leaves a diagnostic marker and requires a new explicit decision after manual inspection. It must not present a recovery-deletion command or claim the native boundary is proven before the trial's full positive and negative results are recorded.
