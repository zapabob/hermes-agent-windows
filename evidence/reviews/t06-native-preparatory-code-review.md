# T06 preparatory AppContainer boundary review

Reviewed commit: `2ca66d9a1b5765f553c1ce75eee45e65e7249b59`  
Review scope: native Windows AppContainer preparation, with focus on the separately gated profile experiment.  
Reviewer mode: read-only; no test or profile gate was executed.

## Skill-perspective check

The `code-review-and-quality` skill was loaded and applied. `remove-ai-slops` and `programming` were explicitly checked at `<local-codex-skills>\remove-ai-slops\SKILL.md` and `<local-codex-skills>\programming\SKILL.md`; neither exists in this environment, so their requested perspectives were applied from the review brief instead. The production and test changes contain no deletion-only or tautological tests, brittle prompt tests, untyped escape hatches, or unnecessary parsing/normalization for this boundary. The substantial implementation size is justified only as preparatory, inactive Windows-boundary work; it must not be represented as production-ready.

## Findings

### CRITICAL

None.

### HIGH

1. **The interrupted-run cleanup gate can delete a same-user profile based on an unauthenticated, user-writable marker.**  `tests/windows/test_delegated_execution_boundary.py:185-215` accepts JSON from the caller-selected marker path, validates only predictable values (fixed name, current user SID, and deterministically derived AppContainer SID), and then calls `DeleteAppContainerProfile` at line 204. Any local writer able to create a marker under the worktree can construct those fields. The gate therefore does not prove that this test invocation created the named profile, despite its help text and assertion. If the fixed profile is independently created by the current user, a forged or stale marker can authorize its deletion. Make recovery cleanup require an independently verifiable ownership record or remove automatic deletion from the recovery path and require a human state inspection before invoking the Windows API.

2. **The ACL-mutating helper resolves `icacls.exe` through mutable process environment state.**  `tests/windows/test_delegated_execution_boundary.py:425-432` constructs the executable path from `os.environ["SystemRoot"]` and executes it before granting permissions. The gate makes ACL changes, so it must not allow an inherited or test-mutated environment variable to select the executable. Resolve the Windows system directory through a Windows API and validate the final `icacls.exe` path, or otherwise use a trusted absolute operating-system path. Until then, the stated ACL confinement cannot be relied upon for an approved real-profile run.

### MEDIUM

1. **ACL rollback is implicit rather than proved.**  The harness grants inheritable ACEs recursively at `tests/windows/test_delegated_execution_boundary.py:419-432`, but it never removes them. Ordinary pytest cleanup may remove the temporary directories, and a successfully deleted profile makes its SID unusable, but failed profile cleanup or retained pytest artifacts leave grants on disk. The targets are correctly confined to the H-drive pytest directory (`:420-424`), so this does not expose credentials or source tools; still, the recovery record should include ACL cleanup outcome or the harness should explicitly remove only the ACEs it added before test cleanup.

### LOW

1. **The positive gate remains evidence pending.**  The useful-process and denial tests are well-scoped behavior tests, but they were intentionally not run. The preparation document correctly records this at `_docs/2026-09-24_t06-native-delegation_codex.md:59-70`. No result from this commit establishes AppContainer usefulness, loopback denial, or cleanup reliability on this machine.

## Scope and side-effect assessment

The normal creation path has strong boundaries: profile creation requires both opt-in switches (`tests/windows/conftest.py:8-22`), refuses a pre-existing marker (`test_delegated_execution_boundary.py:224-227`), uses one fixed profile name (`:28`), and returns early if profile creation fails (`:251-259`). Its native-process child environment is rebuilt rather than inherited (`downstream/platform/windows/delegated_execution.py:575-588`), and the only supplied handles are the standard input/output pipe pair (`:453-460`). ACL target validation requires descendants of pytest's resolved temporary root (`tests/windows/test_delegated_execution_boundary.py:419-424`). The test network probes use only loopback sockets (`:617-675`).

These observations support the intended scope for a future experiment, but the two HIGH findings mean the command currently carries avoidable mutable-host and recovery-deletion risks.

## Verdict

`codeQualityStatus`: **BLOCK**  
`recommendation`: **REQUEST_CHANGES**

Do not ask the human to approve the gated real-profile run until the `icacls.exe` trust boundary is fixed. Do not approve the interrupted-run cleanup gate until its ownership proof is made non-forgeable or it is replaced with an explicit manual-review procedure. After both fixes, the human approval request should name the sole profile, state that it creates current-user AppContainer storage and may leave a recovery marker on H:, and exclude any cleanup command unless separately reviewed.
