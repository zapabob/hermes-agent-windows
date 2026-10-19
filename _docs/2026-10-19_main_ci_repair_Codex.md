# main CI repair — 2026-10-19

Human request: resume carry metrics and Desktop unit-test dist repairs, commit
and push main, and verify all required main push checks on one final SHA.
Retained WIP, previous evidence, packages and runtime are not cleanup targets.
Starting main/origin SHA: a1b9263fa9544273ce4acbe74be1c212d6aafd9a.

## Changes and acceptance boundaries

Desktop fixture unit tests previously stopped at the real build-presence guard
before reaching synthetic Electron. With dist preserved elsewhere (not deleted),
the existing suite reproduced seven assertion failures. The test now substitutes
only existsSync for the exact two build artifacts and delegates all sandbox
filesystem checks to the real implementation. Two negative controls verify each
missing artifact rejects before Electron launch. The cleanup-failure control
requires the intended launch failure and one launch attempt. Ten cases pass
without dist. No production build guard, native launch or cleanup guard was
weakened. An attempted spy on a native ESM namespace failed during fixture setup;
that attempt is excluded and preserved. The accepted mock uses importOriginal.

Generic CI also failed on missing busy-policy translations and stale fixture
contracts. Fifteen locale files now contain the seven existing English-schema
keys with matching placeholders. Goal resume's session-store fake implements
metadata defaults. Retired-run progress tests require cancelled/interrupted
results and suppression of stale final responses. Stop/cache eviction uses the
real generation invalidation rather than a fake returning None.

Slack had 51 canonical native candidates at the existing 50-entry cap after
adding busy, silently dropping insights. Busy now uses the established
/hermes-only routing set, preserving native insights. Manifest cap/parity and
subcommand mapping are checked, and four actual handler tests verify
/hermes busy queue|steer|interrupt|status reaches the Gateway with identity
metadata intact. Existing parity assertions and the cap remain unchanged.

The fresh profile-route worker passed three local Windows real HTTP/SDK/SQLite
journeys. Its prior Linux CI failure lacked worker diagnostics; the assertion
now includes a bounded UTF-8 log tail with the generated owned token redacted.
This is a diagnostic change, not proof the Linux cause has been repaired.
Actual pushed-SHA results must decide whether more changes are needed.

Carry metrics intentionally measure committed HEAD against the frozen upstream,
excluding all _docs paths. Commit the code first, regenerate using the existing
scripts/downstream/carry_metrics.py, then commit both tracked reports. Do not
alter metric definitions or exclusions just to make --check pass.

## Local verification and safety

Selected Python runs passed 123 cases: goal resume 4, cancellation progress 2,
stop/cache 7, i18n 36, commands 57, Slack handler 14, profile HTTP worker 3.
Each file ran in a fresh owned Windows Job with owned homes before imports;
all selected Jobs ended with zero members and no observed audit violations.
The stop/cache bootstrap retains the actual reaper and denies unsubstituted
registry kills. An older no-op bootstrap caused an event failure and is excluded.
Renderer/e2e TypeScript checking, changed-file ESLint, Ruff and diff checks pass.

An initial full Electron-unit run put temporary Git repositories inside the
checkout without a Git ceiling. A test discovered the parent repository and
switched this worktree to a new rawr branch at the same HEAD. The run was stopped;
main was unchanged, working changes were preserved, and the original branch was
restored. Reflog/status/patch evidence is retained; the incidental ref was not
deleted. Subsequent runs scrub inherited Git routing, set a ceiling and verify
that a fresh test directory cannot discover the parent repository before launch.
The next full run passed 2,153 cases and failed one SSH socket-length control
because this task's deeply nested TEMP exceeded the contract's 104-byte limit.
It is not accepted as all-green. A fresh short, owned TEMP run is pending.

The short owned TEMP run completed: 2,154 cases passed, zero assertion
failures, nine pending cases. Two suites failed collection because the local
ignore-scripts dependency installation has no Electron binary. Therefore this
local full run is not GREEN. No dependency or evidence deletion was used to
remove that limitation. The candidate 7b800be41bb064484ce7678b2565d1af96f31c77
passed every Windows Tier-1 job, including native Desktop and carry policy;
Docker, Nix and the generic JS/TS job also passed. Other push jobs were still
running when this follow-up was recorded.

The JS autofix workflow proposed PR #167 with 20 TypeScript/TSX formatting
changes. Its complete patch is preserved locally and was independently
reviewed: no assertions, guards, dependencies, or translated string values
were removed or relaxed. A separate read-only check found identical syntax
trees after excluding redundant parentheses and JSX indentation, and identical
emitted JavaScript syntax. Prettier check passed; changed-file ESLint reported
zero errors and four existing pipeline-order whitespace warnings. The reviewed
patch is incorporated directly into the authorized main repair, followed by a
fresh carry report. No change to workflow gates or metric definitions is made.

The existing autofix automation then updated and merged PR #167 as c77d0b8b14c:
four blank lines in two test files, corresponding to the four remaining ESLint
warnings. The complete diff was reviewed and both worktrees fast-forwarded;
the additional committed lines require one more carry regeneration. This bot
advance is part of the final source binding, not an accepted stale report.
Superseded 7b800 main-push CI and artifact runs were cancelled to release their
concurrency slots; run metadata and available logs are preserved locally. Only
the final main SHA's terminal required checks can satisfy this request.

The full progress file has two separate pre-existing Windows file-URI failures;
the repaired generation cases pass without changing those assertions. The
scheduled full Windows qualification at the old SHA has 424 failures in 159
files. Neither is converted into full Windows/parity acceptance by repairing
the required main push CI lanes. They remain in the broader campaign inventory.

Evidence: tmp/ci-repair-20261019/ plus fresh fxa02-ci-* / fxa04-ci-wire-v1
directories under tmp/selective-20261017/. Prior evidence files are untouched.
Final commit binding and remote CI receipts will be saved locally after all
applicable required main-push workflows reach terminal success. No all-green
claim is made by this initial implementation record.

## Linux profile-route follow-up

Final-candidate 494bdf60cb98c2adf22f9993d92397dad1eed2ba passed Tier-1,
Windows artifact qualification, Docker, Nix and the explicit autofix dispatch.
Its first generic Python job lost hosted-runner communication; GitHub left the
test step in_progress and published no job log. Official job details and the
communication-loss annotations are retained. Failed jobs were retried at the
same SHA without changing test conditions. No source cause is inferred from
that infrastructure annotation.

A separate diagnostic branch, codex/ci-profile-probe-20261019, retained the same
product tree and locked Linux setup but limited execution to the profile file.
Run 39187659640 reproduced all three failures after successful real model
answers: shell._session_db was None. Diagnostic RED run 39188016795 also failed.
Source inspection and CodeGraph locate the cause: the fixture set HOME to its
temporary directory and HERMES_HOME to HOME/.hermes, placing the child profile
DB exactly under the POSIX default root protected by the live-DB test guard.
CLI catches that refusal and continues without indexing; the worker then fails
when reading history. Windows resolves a different default root, which explains
why the prior owned Windows runs did not expose the collision.

The fixture now uses the explicit profile-route-owned directory outside the
platform-default root. Production guard code, bypass variables, DB access,
credentials, HTTP transport and history assertions are unchanged. The worker
asserts a usable DB before inference and reports the owned path and existing
initialization diagnostics. It does not substitute a DB or skip persistence.
Independent review found no guard bypass or weakened assertion.

Diagnostic GREEN run 39188126106, commit 0f17d1779a45dc05ded3be0b7ff7058b8937d4ec,
passed all three profile journeys and all twelve existing live-DB guard tests
(15 total, zero failures, zero file retries). The source hashes match the local
fix. The fresh owned Windows run fxa04-ci-w2 passed all three journeys in 104s,
with unchanged source bindings, no timeout and zero Job members before/after
recovery. Ruff and diff checks pass. The diagnostic branch and evidence remain
preserved; its reduced workflow is not merged to main or counted as full CI.

Only the two test files and this record are integrated into the main repair.
Carry reports must be refreshed from that committed code, followed by all
required final-main workflows at the new exact SHA. The previous full CI's
attempt 2 is superseded by this verified fixture fix; its metadata is retained.
