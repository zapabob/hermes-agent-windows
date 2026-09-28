# N53 Phase 2: reconcile onto the PR158 head (Cursor)

Date: 2026-09-29 JST (started 07:06, recorded 08:10 +09:00)
Implementation AI: Cursor agent
Repository: `zapabob/hermes-agent-windows`
Campaign: `windows-semantic-refresh-20260926`; tracking issue Linear `B0B-7`
Worktree: `C:\Users\downl\.codex\worktrees\n53-on-pr158`
Branch: `cursor/n53-on-pr158-20260929`

## Overview

This record covers Phase 2 of `docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md`. N53 was rebuilt on the current public N52 head, PR158 `86d3149599a2be48a1a66903ba7e3e3a12c819ef`, by semantic composition rather than a branch move. The source bytes are identical to the earlier candidate. Tests, mutation checks and CodeGraph 1.6.0 were rerun on the new tree. The branch is published as a Draft PR against the PR158 head branch so that its diff shows only N53. The GPT-6-pro final review stays PENDING; the user runs it.

## Background and requirements

- The user approved Phase 2. The GPT-6-pro final review is run by the user in the ChatGPT web UI, so N53 has to be pushed with a clean worktree. Merging into main is a later, separate PR decision.
- Plan Phase 2: "do not treat a branch move as proof of equivalence", "Reapply/compose only N53's observable contract onto that current parent", and rebind CodeGraph 1.6.0 on the new source.
- Rules applied: `C:\Users\downl\AGENTS.md`, the repo `AGENTS.md`, `docs/windows/semantic-refresh-20260926/AGENTS.md`, `families/AGENTS.md`, and the plan. The primary checkout and the other workers' worktrees (`e2e-158-*`, `desktop-multi-backend`) were not touched. The old `n55-desktop-integration` worktree was only read.

## Measurements before editing

- `origin/main` = `cc686ab1d31d6ee5ca07243765c5a07e3b9af1af` (unchanged).
- PR158: open, draft, base `main` @ `cc686ab1…`, head branch `codex/n52-gateway-identity-20260928` @ `86d3149599a2be48a1a66903ba7e3e3a12c819ef`, tree `93710f7680cfec66999c5227a08c6d22377ad417`.
- Old worktree `n55-desktop-integration`: branch `cursor/n53-pause-recovery-20260929` @ `04fac33fbf713fb152b118d747d4c249e6f53048`. The only untracked path was the plan file.

## Composition

1. The worktree was created with `git worktree add -b cursor/n53-on-pr158-20260929 C:\Users\downl\.codex\worktrees\n53-on-pr158 86d31495…`.
2. A test cherry-pick (`--no-commit`) of `a952e52d` alone did not apply. It conflicted in `update_cmd.py` and `test_update_concurrent_quarantine.py`, and `test_windows_relaunch_verify_budget.py` was a modify/delete conflict. The reason is that the pause-recovery commit is built on the two earlier N53 relaunch commits, which PR158 does not contain. The attempt was abandoned, and the four affected paths in the new worktree were restored to HEAD.
3. Before composing, the N52 product paths were checked: `git diff 86d31495 56f94e9c` (the local N52 integration end that N53 was built on) touches only `families/N52.json` and the two carry metrics files. The N52 source that N53 depends on is therefore byte-identical in PR158.
4. The three N53 product commits were composed in order, and all three applied without conflict:
   - `7696e599` became `544dd1e58bb4b7ae8e64d192ec4e46ec27d59461` (verify gateway relaunch by process incarnation).
   - `b448ffc8` became `be3051a48475ad8ebdf15010ea832b1fe6eb612a` (verify armed mapped watchers when inventory misses them).
   - `a952e52d` became `b5885d4f7734d14fc53a8bf4407eb139a49e8d8c` (recover paused gateways when update pause fails), tree `04600265ce1822db1931211ebb824e64f7e41af7`.
5. The equivalence check `git diff --name-status 04fac33f b5885d4f` listed only documentation and carry paths. Every product and test path is identical to the reviewed candidate.
6. The N53 documentation commits were composed after that: `d441746f` became `8a56934a`, and `04fac33f` became `0752426d`. The old carry-metrics commit `0a20e2a6` was not carried; the metrics were regenerated on the new tree instead.

These are downstream family commits, not upstream commits. No upstream merge, rebase or cherry-pick was performed.

## The 12 differing paths (PR158 head `86d31495` against old N53 HEAD `0a20e2a6`)

| # | Path | Origin of the difference | Decision |
|---|---|---|---|
| 1 | `_docs/2026-09-28_N53_gateway_relaunch_incarnation_Codex.md` | N53 docs (`d441746f`) | Carried as `8a56934a`; historical, bound to its own parent. |
| 2 | `_docs/carry-surface-20260826.json` | Generated metrics; each side generated on its own tree | Not carried. Regenerated on the new tree and committed; `--check` exits 0. |
| 3 | `_docs/carry-surface-20260826.md` | Same as 2 | Same as 2. |
| 4 | `docs/windows/semantic-refresh-20260926/families/N52.json` | PR158 is newer: it binds N52 to public commit `fb71fa0` and records publication in #158. The local copy predates that. | PR158 version kept. Taking the local copy would lose the publication binding. |
| 5 | `docs/windows/semantic-refresh-20260926/families/N53.json` | N53 card, absent from PR158 | Carried, plus the new dated entry `additive_2026-09-29_phase2_pr158`. Earlier entries are unchanged. |
| 6 | `gateway/status.py` | N53 `7696e599`: `_pid_identity_is_live` (PID-reuse-aware incarnation check) | Composed; SHA-256 `fa382acc…`. Mutant P5 is killed. |
| 7 | `hermes_cli/gateway.py` | N53 `7696e599`: the restart watcher waits for the old incarnation and declines a second launch | Composed; SHA-256 `c6b2eca3…`. |
| 8 | `hermes_cli/update_cmd.py` | N53 `7696e599` + `b448ffc8` (and `a952e52d` on top) | Composed; SHA-256 `f32ac816…`, equal to the reviewed candidate. |
| 9 | `tests/hermes_cli/test_update_concurrent_quarantine.py` | N53 `7696e599` (and `a952e52d`) | Composed; SHA-256 `88e2af92…`. |
| 10 | `tests/hermes_cli/test_update_fleet_check_fail_closed.py` | N53 `b448ffc8` | Composed; SHA-256 `2d744843…`. |
| 11 | `tests/hermes_cli/test_update_fleet_probe_resume_token.py` | N53 `b448ffc8` | Composed; SHA-256 `73c7c882…`. |
| 12 | `tests/hermes_cli/test_windows_relaunch_verify_budget.py` | N53 `7696e599` (and `a952e52d`) | Composed; SHA-256 `abbf9090…`. |

`tests/hermes_cli/test_update_pause_recovery.py` (SHA-256 `ba22af34…`) is new in `a952e52d`, so it is not among the 12. No difference comes from N52 source, and none needed a hand edit.

## Final hashes (SHA-256)

| Path | SHA-256 |
|---|---|
| `hermes_cli/update_cmd.py` | `f32ac816f5d6147c2138b75d1050c68f96965e2839560c857937d9bafca0d18f` |
| `tests/hermes_cli/test_update_concurrent_quarantine.py` | `88e2af92c41b828fdc1fd454c5f05de2a7e8e6188ca9a856489ad6f76c6b7f90` |
| `tests/hermes_cli/test_windows_relaunch_verify_budget.py` | `abbf9090b73d70aa64c4bfee9ae379e56821c5fb8665f0edf76e649e73681f29` |
| `tests/hermes_cli/test_update_pause_recovery.py` | `ba22af34ed9bdbef5e1dbe13d58e7caef5db0c298725a0510dc00054a01e1030` |
| `gateway/status.py` | `fa382acc38b82fb3f04d5ea916442830a084d37ec70f718832c23bff98c91cda` |
| `hermes_cli/gateway.py` | `c6b2eca3c00a2159d2c11d9a80628fe5246ecbcc88603d220b804aa84393a11b` |
| `tests/hermes_cli/test_update_fleet_check_fail_closed.py` | `2d74484319c92be890349937c769456b653feed28b2deb40451047538dd64299` |
| `tests/hermes_cli/test_update_fleet_probe_resume_token.py` | `73c7c8826f1e63a84efdadf08436775cbc25ef78920550d848a543393d83d7d0` |

## CodeGraph 1.6.0

- Package: the primary checkout's `.tools\codegraph-cli` (`@colbymchenry/codegraph` 1.6.0), used read-only. Launched with `C:\Users\downl\AppData\Local\nvm\v22.23.2\node.exe` and `CODEGRAPH_NO_DOWNLOAD=1`. No install, no `@latest`, no Node 26.
- Drive C had only about 0.5 GB free, so the 621 MB index could not be copied into the worktree. The index was copied from the N53 integration worktree to `H:\hermes-worktrees\codegraph-index-n53-on-pr158`, and `.codegraph` in the new worktree is a junction to it. `.codegraph` is excluded by `.git/info/exclude`.
- `sync`: already up to date. `status --json`: 1.6.0, 8,923 files, 191,274 nodes, 613,121 edges, pending 0/0/0, `worktreeMismatch` null, state complete, pendingRefs 0, extraction version 25.
- `query`: `_pause_windows_gateways_for_update` is at `update_cmd.py:6219`, and `_venv_launcher_ancestor_identities` is at `update_cmd.py:5429`.
- `impact` (depth 2): 7 affected symbols each, including `_cmd_update_impl`, `cmd_update`, and the Windows lifecycle tests. At depth 4 (`--json`), `_pause_windows_gateways_for_update` reaches 47 nodes and 46 edges, the same as the historical receipt.
- `explore "gateway update pause rollback"` ran (580 lines). `affected` for the three product sources listed 1,020 paths; this is not counted as executed coverage.
- The receipts are in the gitignored `tmp/probes/n53p2/`. Their SHA-256 prefixes: status `87e5c05e…`, impact-d4 `7728e9e8…`, query-pause `07921837…`, query-launcher `3a393af5…`, affected `1aaad381…`, explore `477e54ff…`.

## Tests, lint and mutation

The virtual environment was created on drive H because C was nearly full: `UV_PROJECT_ENVIRONMENT=H:\hermes-worktrees\venv-n53-on-pr158`, `uv sync --frozen --extra dev`, with `TEMP` and `TMP` also on H. The interpreter was CPython 3.11.11, and uv was 0.11.29.

- N53 eight-module set: 125/125 passed in 18.95s. The modules were pause recovery, concurrent quarantine, relaunch budget, fleet check fail-closed, fleet probe resume token, cold-start Desktop lifecycle, restart-watcher identity, and orphan backend reap. The earlier log did not name its eight modules. This set was reconstructed from per-module collection counts, and it is the only set of eight candidate modules whose counts add up to 125.
- N52 set: 62/62 passed in 45.66s. The modules were restart-watcher identity, handoff backend reap, orphan backend reap, venv holder live, stderr timestamp, and Desktop lifecycle live.
- Ruff 0.15.10 (`uvx --offline`) check passed on all eight changed Python paths. The format check on `test_update_pause_recovery.py` passed.
- `git diff --check 86d31495 HEAD` passed with exit 0.
- Mutation: probe `tmp/probes/n53p2/mutate_p2.py` (SHA-256 `4343b56e…`), results in `mutation-results-p2.json` (SHA-256 `2cad326a…`). Five of five mutants were killed. Each ran against the eight-module set and was restored with a hash check:
  - P1 skip the SCM service rollback: killed by `test_pause_windows_gateway_service_failure_restores_every_attempted_service`.
  - P2 omit the ordinary gateway rollback: killed by `test_partial_pause_recovers_before_returning_failure[drain|force_stop]`.
  - P3 replay untouched unmapped siblings: killed by `test_partial_pause_recovers_before_returning_failure`.
  - P4 drop rollback failures from the raised detail: killed by `test_partial_pause_reports_recovery_failure`.
  - P5 ignore PID reuse in `_pid_identity_is_live`: killed by `test_live_pid_requires_the_original_start_time`.
  - After the restores, the eight-module set passed 125/125 again.

## Review status

No new independent review was run on this composition. The source bytes are identical to those the Cursor/Claude CLEAR_WITH_NOTES review covered, but that review was not bound to this parent. The GPT-6-pro final review is `PENDING_UNAVAILABLE_MODEL`, to be run by the user. The PR must not be merged before that review is complete.

## Changed files and commits

The commits are listed from the PR158 parent upwards:

- `544dd1e5`, `be3051a4`, `b5885d4f`: N53 product, composed.
- `8a56934a`, `0752426d`: N53 docs, composed.
- `d1ea8d7b`: `families/N53.json` additive Phase 2 entry, plus `CURSOR_IMPLEMENTATION_PLAN_20260929.md` (byte-identical to the untracked copy in the old worktree, SHA-256 `4c740724…`).
- A final commit contains the regenerated `_docs/carry-surface-20260826.json` and `.md`, plus this log (force-added).

Commands used: `git worktree add`, `git cherry-pick` (N53 family commits only), `git restore`/`git rm` on the four conflicted paths in the new worktree only, `git cherry-pick --quit`, `git add <explicit paths>`, `git add -f` for the log, `git commit`, `git push -u origin` (no force), `gh pr create --draft`, `gh run list/watch`, `uv sync/run`, `uvx --offline ruff@0.15.10`, the CodeGraph shim, and `Get-FileHash`. No `git add .`, clean, stash, reset --hard, force push, main push, or merge was performed. Frozen SHAs were not moved. Control MCP production write stays DISABLED. The model picker, provider and OAuth settings, and Defender were not changed.

## Old worktree `n55-desktop-integration`

Nothing was deleted, reset, cleaned or stashed there. Its only untracked path is `docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md`, and it is now committed byte-identically on this branch, so the user could remove that copy. Its branch `cursor/n53-pause-recovery-20260929` (`04fac33f`) and the original `codex/n53-relaunch-incarnation-20260928` (`0a20e2a6`) were left untouched. Two logs there are ignored through `.git/info/exclude` (`_docs/`), so plain `git status` does not show them: `_docs/2026-09-29_windows-semantic-refresh-cursor-handoff_GPT-5.6-Sol.md` and `_docs/2026-09-29_N53_gateway_pause_recovery_Codex.md`. They are not committed on this branch and are not safe to remove. Ignored `__pycache__`, `web_dist`, `.venv`, `tmp` and `.codegraph` content is local scratch.

## Linear B0B-7 comment (not posted; drafted)

> 2026-09-29 08:10 JST Cursor: N53 Phase 2 done. The three N53 product commits were composed onto PR158 head 86d31495 (branch cursor/n53-on-pr158-20260929). The source bytes equal the reviewed candidate (update_cmd f32ac816…, quarantine 88e2af92…, relaunch budget abbf9090…, pause recovery ba22af34…). CodeGraph 1.6.0: 8,923 files / 191,274 nodes / 613,121 edges, pending 0, mismatch null, impact d4 47/46. Tests: N53 125/125, N52 62/62. Ruff and diff --check are clean. 5/5 fresh mutants killed. A Draft PR targets the PR158 head branch. The GPT-6-pro final review is pending with the user, and the PR must not merge before it.

## Residual risks and next actions

1. The GPT-6-pro final review is pending. Any finding needs RED → fix → rerun → CodeGraph → re-review on this branch.
2. Drive C is almost full (about 0.1–0.5 GB free). The venv, index and temp files were placed on H. The user should free space on C before further local builds.
3. CI on the Draft PR is recorded in the PR and in the final report. Windows-lane coverage and skipped jobs must be read separately.
4. Phase 3 (N54 recomposition onto this parent), the aggregate candidate, N07-A1, T06 and T12 remain open.
