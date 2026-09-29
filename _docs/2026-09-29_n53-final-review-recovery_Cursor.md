# N53 final review recovery — Cursor

Date: 2026-09-29 JST (recorded 07:00 +09:00)
Implementation AI: Cursor agent (Claude)
Repository: `zapabob/hermes-agent-windows`
Campaign: `windows-semantic-refresh-20260926`; tracking issue Linear `B0B-7`
Worktree: `C:\Users\downl\.codex\worktrees\n55-desktop-integration\hermes-agent`

## Overview

This record covers Phase 0 and Phase 1 of `docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md`. The work bound the approved CodeGraph 1.6.0 to the N53 candidate. It then searched for the pending second GPT-6-pro review and did not find one. A separate Cursor/Claude independent review, tests and mutation checks were run, the result was added to the N53 card as dated additive evidence, and the unchanged candidate was committed on a new local branch. Nothing was pushed, no PR was opened, and PR158 reconciliation and N54 composition were not started.

## Background and requirements

The plan says (section 8.4 and Phase 1): "Recover the second independent GPT-6-pro review result that is bound to the four final Python SHA-256 values" and "N53 is not complete until that final review result is recovered and any finding is resolved against exactly the candidate being committed." The plan grants no substitute reviewer. GPT-6-pro is not available in this environment, so the GPT-6-pro slot stays `PENDING_UNAVAILABLE_MODEL`, and the Cursor review is labelled as a separate review.

Applied rules: `C:\Users\downl\AGENTS.md`; `C:\Users\downl\_docs\prompts\CLAUDE-FABLE-5.md` (read; it is a consumer chat system prompt and adds no engineering constraint beyond the SOPs); SOP Common, Implementation Start Gate, Python and Security; the repo `AGENTS.md`; the campaign `AGENTS.md`; `families/AGENTS.md`. The frozen package ZIP was not extracted into the repository. Its controlling constraints are restated in plan section 1, which was followed.

## Measurements

The worktree was on branch `codex/n53-relaunch-incarnation-20260928` at HEAD `0a20e2a6ab4f10b3c43fdc498ae41b66f8e230e2`, tree `87b7005ce564aa347c909d954a798bb8ec48de72`, with the dirty candidate described in plan section 3.3.

| Path | Card SHA-256 | Current SHA-256 |
|---|---|---|
| `hermes_cli/update_cmd.py` | `f32ac816f5d6147c2138b75d1050c68f96965e2839560c857937d9bafca0d18f` | identical |
| `tests/hermes_cli/test_update_concurrent_quarantine.py` | `88e2af92c41b828fdc1fd454c5f05de2a7e8e6188ca9a856489ad6f76c6b7f90` | identical |
| `tests/hermes_cli/test_windows_relaunch_verify_budget.py` | `abbf9090b73d70aa64c4bfee9ae379e56821c5fb8665f0edf76e649e73681f29` | identical |
| `tests/hermes_cli/test_update_pause_recovery.py` | `ba22af34ed9bdbef5e1dbe13d58e7caef5db0c298725a0510dc00054a01e1030` | identical |

Before this task edited it, `families/N53.json` also matched the plan: `d81f38e3ad540f709c9be78cf4c66b8f5e2bfb7772ba3ef5c0303cc4df0538e4`.

## CodeGraph 1.6.0 gate — bound

The approved implementation is the one cited by the T06 receipt: `C:\Users\downl\Documents\New project\hermes-agent\.tools\codegraph-cli`. It was used read-only. `@colbymchenry/codegraph` 1.6.0 has lock integrity `sha512-nCN40MqmYxF7gH1QTKqlxJ1d2mzwhw3fzSdGV2wjnQKsymjM3JZnH/5rpGqhBkcUEom0qWq0WjDRvOZh2t8mFA==`, and the platform package `codegraph-win32-x64` is also 1.6.0. `npm-shim.js` has SHA-256 `80419260f06862d7a422d13ef69e3b24c7a21dbef4309bce41db02ad642b1877`, and `package-lock.json` has SHA-256 `02e3c5a703572396079e0d92b0f46a231d351a9b28089bf34a95e9276de19aa4`. The shim was launched with the existing NVM Node `v22.23.2` and `CODEGRAPH_NO_DOWNLOAD=1`. The actual indexing ran on the package's bundled Node 24 runtime. No package was installed, `@latest` was not used, and the Node 26 override was not used.

The `status . --json` output was 1.6.0 with 8,923 files, 191,274 nodes and 613,121 edges. Pending changes were 0/0/0, `worktreeMismatch` was null, the state was complete, `pendingRefs` was 0, and the index was built with extraction version 25. A sync was not needed. After the product commit, the status was identical.

The queries returned these results. `_pause_windows_gateways_for_update` is at `update_cmd.py:6219`, and `_venv_launcher_ancestor_identities` is at `update_cmd.py:5429`. The callers are `_cmd_update_impl` plus three Windows lifecycle tests. `impact --depth 4` reported 47 affected symbols. `explore` and `affected` both ran; `affected` listed 867 files and is not counted as executed coverage. The receipts are in `tmp/probes/n53-cursor/`, which is gitignored:

| Receipt | SHA-256 |
|---|---|
| `cg-query-pause.txt` | `22a8299f…` |
| `cg-callers-pause.txt` | `8cecaa15…` |
| `cg-impact-pause.txt` | `8119a085…` |
| `cg-affected.txt` | `848ffca6…` |

## Review receipt search

The four hashes were searched for in `~/.codex/sessions`, in `_docs` in the N53, semantic-refresh and primary checkouts, in the worktree `tmp`, and in the Cursor agent transcripts. Four Codex session files and the Codex N53 log matched. The two review sub-sessions ended with errors and `last_agent_message: null`:

- `rollout-2026-09-29T03-51-36-01a0e95b…` failed with "ChatGPT composer did not preserve the complete prompt".
- `rollout-2026-09-29T03-56-04-01a0e95f…` failed with "ChatGPT stopped responding".

No second GPT-6-pro result exists. Linear B0B-7 could not be read: the connected Linear MCP authenticates to workspace `mame44242`, where `B0B-7` does not exist.

## Independent review (Cursor/Claude, not GPT-6-pro)

The review read the full `update_cmd.py` diff against HEAD, the resume path (`_resume_windows_gateways_after_update_impl`), and `gateway.status.terminate_pid` / `get_process_start_time`. It covered the six plan-listed contracts, the unit consistency of the centisecond guards, and the missing-watched-profile gate.

The result is `CLEAR_WITH_NOTES`: there is no P0, P1 or P2 finding, and no source edit was made. There are three P3 notes:

1. When argv or a start time cannot be re-read, or a launcher exits between discovery and revalidation, the update now aborts. This fail-closed behaviour is intentional, but it can refuse an update spuriously.
2. The "Restart manually after update" branch is unreachable now that every unmapped entry needs verified argv.
3. An SCM descendant spawned between service discovery and the gateway scan would be classified as an unmapped ordinary gateway. This is a narrow TOCTOU window and was not addressed.

## Tests and mutation

All Python ran through `uv run --frozen --extra dev` on CPython 3.11.11 (uv 0.11.29 created the ignored `.venv`).

- The eight-module bounded N53 set passed 125/125 in 143.79s.
- Ruff 0.15.10 (`uvx --offline`) passed on all four paths.
- `git diff --check` passed.

The mutation probe is `tmp/probes/n53-cursor/mutate.py` (SHA-256 `2a59cc12…`); its results are in `mutation-results.json` (SHA-256 `b2f4bed5…`). Each mutant was applied in place, the three N53 modules were run, and the file was restored with a hash check. Five of five mutants were killed:

- M1 dropped the missing-watched-profile gate.
- M2 swallowed a force-stop failure of a still-live incarnation.
- M3 skipped the launcher discovery incarnation check.
- M4 skipped the unmapped attempt journal.
- M5 narrowed the `BaseException` rollback to `Exception`.

After every restore the hash was `f32ac816…`.

## Changed files and commits

The work is on the new local branch `cursor/n53-pause-recovery-20260929`. The old branch `codex/n53-relaunch-incarnation-20260928` stays at `0a20e2a6`.

- Product commit `a952e52dfbb50959e465639b3d9d99a264b483eb` (tree `672468d1f2b84edf1f9e0127c8ce08484bff7233`) contains the four Python paths, added with explicit `git add`. The blob SHA-256 values match the table above exactly.
- The docs commit contains `docs/windows/semantic-refresh-20260926/families/N53.json` (additive keys `gpt6pro_second_review_status: PENDING_UNAVAILABLE_MODEL` and `additive_2026-09-29_cursor`; the status stays `…REVIEW_PENDING`) and this log (force-added).
- The Cursor plan and the GPT-5.6 Sol handoff log stay untracked.

Commands used: read-only `git -C` commands, `git switch -c`, `git add <explicit paths>`, `git commit`, `Get-FileHash`, the CodeGraph shim commands above, `uv run`, and `uvx --offline ruff@0.15.10`. No reset, stash, clean, push, merge, rebase, deploy or restart was performed.

## Linear B0B-7 comment (not posted — drafted for the user)

> 2026-09-29 07:00 JST Cursor: N53 hashes re-measured and equal to the card (update_cmd f32ac816…, quarantine 88e2af92…, relaunch budget abbf9090…, pause recovery ba22af34…). Approved CodeGraph 1.6.0 (primary checkout `.tools/codegraph-cli`, integrity sha512-nCN40Mqm…) was bound with Node 22.23.2: 8,923 files, 191,274 nodes, 613,121 edges, pending 0, mismatch null. No second GPT-6-pro result exists; both Codex launches disconnected. The slot is PENDING_UNAVAILABLE_MODEL. A separate Cursor/Claude review returned CLEAR_WITH_NOTES (3× P3, no edit). The bounded tests passed 125/125, Ruff passed, and 5 of 5 mutants were killed. Local commit a952e52d is on branch `cursor/n53-pause-recovery-20260929`; not pushed. PR158 reconciliation and N54 are not started.

## Residual risks and remaining gates

1. The second GPT-6-pro review, or an explicit user decision to accept a substitute, is required before N53 can be called finally reviewed.
2. Linear access to the `zapabob` workspace is needed so the drafted comment can be posted.
3. Phase 2: the PR158 (`86d3149599a2be48a1a66903ba7e3e3a12c819ef`) tree/source reconciliation. N53 is not a descendant, the merge-base is `eb966ce2…`, and there are 12 path differences. It needs a fresh CodeGraph bind and review on the composed parent.
4. Phase 3: the N54 recomposition onto the final N53 parent.
5. N07-A1, T06 and T12 remain open. Control MCP production write remains DISABLED.
