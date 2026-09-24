# T16 bounded Security Center gate review

- recommendation: APPROVE for a local `main` commit as an explicitly `NATIVE_UNQUALIFIED` implementation; REJECT any release, push, or qualification claim until the live native scanner gate and campaign-wide final-head gates are satisfied.
- reviewed tree: local `main` at `1326ee6dc9c8eb8a9d92be0a1ef0b5704c1a41e4` plus the uncommitted T16 diff listed below.
- ancestry: `b1d48ec202f7e3170ab3f2ff520056443ca65ce7` is an ancestor of the reviewed HEAD.
- blockers for local commit: none.
- blockers for native qualification/release: LM23 has no managed ClamAV definitions on this workstation, so real benign and EICAR outcomes are unverified. Exact final candidate SHA checks, required CI, and campaign security closeout are outside this local-commit gate.

## Original intent

Continue the Windows-native Hermes workstation campaign on `main` while preserving the user tree. T16 must make Security Center observations and scans bounded and fail closed, retain real malicious findings when another engine is degraded, bind results and cache use to the actual scanner/rule revision, reject reparse and source-change races, avoid scanner execution from status reads, and preserve the distinction between implemented code and real native qualification.

## Desired outcome

The T16 source and regression tests may be committed locally to `main` when the code-level LM21, LM22, and LM24 contracts are independently reproducible. LM23 remains `NATIVE_UNQUALIFIED` until a configured managed ClamAV database produces separate benign and EICAR evidence. This approval does not authorize a push, release, runtime configuration change, endpoint exposure, or a claim that the whole campaign is complete.

## User outcome review

The reviewed delta is suitable for a local preservation commit. It does not delete tracked files, `git diff --check` is clean, and the requested ancestor is already in `main`. The product changes close the six earlier P1/P2 review findings: YARA recompiles on rule-revision changes; engine-version failure no longer suppresses independent positives or quarantine; cached results are revalidated against a fresh healthy version; full path components are rechecked at hash and snapshot boundaries; bounded pipe-read errors fail closed; and root-limit watcher events remain suppressed until inventory recovery. The real ClamAV qualification remains visibly skipped and therefore cannot support deployment or release claims.

## Reproduced evidence

- Six related files: `157 passed, 5 skipped in 28.78s` using the repository virtual environment and `-p no:cacheprovider`.
- Skip inventory: one POSIX process-group-only case; one host symlink-creation limitation; two directory-symlink ancestor-swap cases unavailable on this Windows host; one real ClamAV benign/EICAR case because managed definitions are not configured. Synthetic Windows reparse-attribute tests cover both before-hash and before-snapshot boundaries and passed.
- Ruff: `ruff 0.15.10`, all changed production and test files passed.
- Git checks: `git diff --check` passed; `git diff --name-status` contains six modified tracked files and no deletions, plus five untracked additions.

## Direct remove-ai-slops and programming pass

The named skill files were unavailable at the configured locations, so the reviewer criteria supplied in the gate instructions were applied directly. The new tests exercise externally meaningful behaviors and security boundaries rather than requested line deletion, implementation constants, or tautologies. The synthetic reparse test is justified because the host cannot create the required directory symlink and it drives the public fail-closed outcome, cache absence, scanner non-invocation, and quarantine absence. The helpers separate bounded process execution, bounded walking, definition inventory, and process-wide snapshot reservations at coherent reuse and enforcement boundaries. No needless production parsing, assertion weakening, deletion-only test, brittle prompt test, or goal-unrelated abstraction was found.

No current T16 code-review report artifact was found under `.omo/evidence`. That missing report does not block this decision because this independent direct pass inspected the diff and tests and reproduced the stated evidence. The implementation ledger should record the exact committed SHA and this qualification boundary after the local commit.

## Checked artifact paths

- `downstream/security/engines.py`
- `downstream/security/service.py`
- `downstream/security/updates.py`
- `downstream/security/watch_state.py`
- `downstream/security/watcher.py`
- `downstream/security/bounded_process.py`
- `downstream/security/bounded_walk.py`
- `downstream/security/clamav_definitions.py`
- `downstream/security/snapshot_budget.py`
- `tests/security/test_t16_bounded_security.py`
- `tests/security/test_security_center.py`
- `tests/security/test_security_auto_update.py`
- `tests/security/test_watch_state.py`
- `tests/security/test_t15_security_semantics.py`
- `tests/security/test_security_api.py`
- `docs/windows/workstation-20260924/LUNA_MAX_EXECUTION_PLAN.md`
- `docs/control-mcp/IMPLEMENTATION_LOG.md`

## Exact evidence gaps

- LM23: no configured managed ClamAV definition directory; no real benign result and no real EICAR detection result on this reviewed tree.
- The POSIX descendant-quiescence test is correctly platform-skipped on Windows; it is not Windows qualification evidence.
- Real directory symlink/junction swaps could not be created under this host policy. The equivalent Windows reparse-attribute boundary was covered synthetically, but a privileged real junction race remains unexecuted.
- No exact committed T16 SHA exists yet because the reviewed delta is uncommitted. After commit, tests and diff/status checks must be rebound to that exact SHA before any higher gate cites them.
- Campaign-wide exact final-head CI, live client, approval, native runtime, and release gates remain outside this T16 local-commit decision.
