# Cursor implementation handoff — Windows semantic refresh 2026-09-26

Date: 2026-09-29 JST\
Repository: `zapabob/hermes-agent-windows`\
Campaign: `windows-semantic-refresh-20260926`\
Tracking issue: Linear `B0B-7`\
Audience: Cursor / next implementation agent

This document is the continuation plan for the Windows semantic-refresh campaign from the first campaign instruction through the latest observed local and remote state. It is an implementation handoff, not a claim that all upstream behavior is already integrated, that all runtime gates are satisfied, or that Control MCP production writes are authorized.

The handoff deliberately separates three evidence classes:

1. `VERIFIED_CURRENT`: re-measured on 2026-09-29 from the current machine, GitHub, Linear, or the active worktree.
2. `VERIFIED_HISTORICAL`: recorded in committed family cards, implementation logs, the frozen campaign package, or prior source-bound receipts.
3. `REPORTED_HISTORICAL`: user-reported prior work that must not be silently reclassified as current observation.

Do not turn a historical receipt into a current receipt merely because the same test name or family number appears later.

---

## 1. Fixed campaign inputs — never move these silently

The campaign was opened against the following immutable observation points:

| Name | SHA | Meaning |
|---|---|---|
| D0 | `60deb5c75351a19b1a6fa1d778d7d0c2ff627e5b` | frozen downstream baseline |
| B | `b51c055a12220f8c7c18660e8599365012e19532` | historical inventory anchor |
| R0 | `345cd2b057a452236de401d3534b8502a7465e8d` | upstream 0.21.3 release |
| R1 | `d337b736aa1e8ebecfab043842d13e4a2d2f48a3` | upstream 0.21.4 / v2026.9.21 |
| U0 | `b936546561888a54d5bf9cd7eae9629a824eb4f7` | historical old-campaign ceiling |
| R2 | `f97608f178d1ffeca59860195ab7da295f7c8e5f` | upstream 0.21.5 / v2026.9.24 |
| U1 | `678a4762b887f3eabe5cad11254b2ab1ae859485` | frozen ceiling for this campaign |

History windows remain `B→R0→R1→U0→R2→U1`. A newer `upstream/main` or `origin/main` is drift, not a replacement for U1 or D0.

The original package remains at:

`C:\Users\downl\Downloads\hermes-codex-semantic-refresh-20260926.zip`

Its controlling inputs are:

- `CODEX_IMPLEMENTATION_PLAN.md` chapters 0–7.
- `FROZEN_INPUTS.json`.
- `REPORTED_PRIOR_WORK.json`.
- `CODEGRAPH_PROTOCOL.md`.
- `INVENTORY_PROCEDURE.md`.

The package explicitly forbids silently replacing the old U0 campaign, inventing a latest SHA for missing input, bulk upstream merge/rebase/cherry-pick as a semantic shortcut, direct-main push, deployment, or runtime restart.

---

## 2. PC, repository, and workspace rules Cursor must load first

Before any edit, Cursor must read the current PC-wide prompt/SOP and the repository/scoped instructions that govern the exact path it will edit. At minimum:

- `C:\Users\downl\AGENTS.md`.
- `C:\Users\downl\_docs\prompts\CLAUDE-FABLE-5.md` as the configured local canonical pre-implementation prompt, subject to higher-priority model/runtime rules.
- relevant files under `C:\Users\downl\_docs\sop\`.
- repository `AGENTS.md`.
- `docs/windows/semantic-refresh-20260926/AGENTS.md`.
- `docs/windows/semantic-refresh-20260926/families/AGENTS.md` when family cards are edited.

The current campaign docs directory already has both `AGENTS.md` and `README.md`; do not create parallel documentation roots merely to reorganize the same evidence.

Every substantive change must leave an implementation log under `_docs`, following the PC-wide filename and evidence policy.

---

## 3. Current machine state — VERIFIED_CURRENT on 2026-09-29

### 3.1 Primary checkout is dirty and must stay untouched

Primary checkout:

`C:\Users\downl\Documents\New project\hermes-agent`

Observed:

- branch: `main`.
- HEAD: `df14ba8c135a905c76010efa4327427ccd7dcebf`.
- compared with the locally configured `origin/main`, Git reports `ahead 131, behind 44`.
- many tracked and untracked WIP paths are present, including Desktop, Control MCP, memory, plugin, lockfile, nested AIRI work, and local scratch.

Do not reset, stash, clean, delete, rename, mass-stage, or use this checkout as a convenient integration target. It is historical/local WIP and is outside the current handoff edit surface.

### 3.2 Historical semantic-refresh worktree is preserved

Worktree:

`C:\Users\downl\.codex\worktrees\semantic-refresh-20260926\hermes-agent`

Observed:

- branch: `codex/semantic-refresh-20260926`.
- HEAD: `a7bdad73b9232aa75715b95b5883f3e30b2888b8`.
- tree: `c9fe11357c124707ec9c55a37b044e14a5f485e4`.
- tracked Desktop N55 files are modified.
- untracked `$tmp`, CodeGraph material, and reviewer evidence are present.

This worktree contains the N02–N54 campaign history and is a source of evidence. Do not stack new product edits on top of its unrelated dirty state.

### 3.3 Active N53 integration worktree

Worktree:

`C:\Users\downl\.codex\worktrees\n55-desktop-integration\hermes-agent`

Observed:

- branch: `codex/n53-relaunch-incarnation-20260928`.
- committed HEAD: `0a20e2a6ab4f10b3c43fdc498ae41b66f8e230e2`.
- committed tree: `87b7005ce564aa347c909d954a798bb8ec48de72`.
- dirty product/evidence candidate:
  - `docs/windows/semantic-refresh-20260926/families/N53.json`
  - `hermes_cli/update_cmd.py`
  - `tests/hermes_cli/test_update_concurrent_quarantine.py`
  - `tests/hermes_cli/test_windows_relaunch_verify_budget.py`
  - untracked `tests/hermes_cli/test_update_pause_recovery.py`

Current SHA-256 values:

| Path | SHA-256 |
|---|---|
| `hermes_cli/update_cmd.py` | `f32ac816f5d6147c2138b75d1050c68f96965e2839560c857937d9bafca0d18f` |
| `tests/hermes_cli/test_update_concurrent_quarantine.py` | `88e2af92c41b828fdc1fd454c5f05de2a7e8e6188ca9a856489ad6f76c6b7f90` |
| `tests/hermes_cli/test_windows_relaunch_verify_budget.py` | `abbf9090b73d70aa64c4bfee9ae379e56821c5fb8665f0edf76e649e73681f29` |
| `tests/hermes_cli/test_update_pause_recovery.py` | `ba22af34ed9bdbef5e1dbe13d58e7caef5db0c298725a0510dc00054a01e1030` |
| `families/N53.json` | `d81f38e3ad540f709c9be78cf4c66b8f5e2bfb7772ba3ef5c0303cc4df0538e4` |

This is the current implementation continuation point.

---

## 4. Current GitHub state — VERIFIED_CURRENT

### 4.1 Remote main

`git ls-remote origin refs/heads/main` returned:

`cc686ab1d31d6ee5ca07243765c5a07e3b9af1af`

This commit is the merge commit for PR #157 and has tree:

`74acf208a4a9b80c300bad418f6da461e421f789`

Parents:

- `eb966ce2cfc1098b46befe9cd8db52be82729f51`
- `e0096d01abc6d5befc2782e940ee29cb253df6c9`

Do not replace D0 with this value.

### 4.2 PR #157 — N55 is merged

PR: `N55: restore remembered Desktop delegate sessions`

- state: closed.
- merged: true.
- merged at: `2026-09-28T20:16:59Z`.
- PR head: `e0096d01abc6d5befc2782e940ee29cb253df6c9`.
- merge commit: `cc686ab1d31d6ee5ca07243765c5a07e3b9af1af`.
- published product commit: `a549832d3de9ace10fa56e12a2187371739d9dc7`.
- locally validated equivalent product: `242a35623ce26d9d013bf1cbcec990cbaa3eddb5`.
- product tree: `4a7c1951b293cbb2c2e62f08ce1b01d2d9bfbc31`.

Historical N55 validation records 79 affected UI tests, Desktop typecheck, Prettier, ESLint with zero warnings, two final-source mutation kills, CodeGraph 1.6.0, and two read-only independent CLEAR reviews. Packaged Electron/live runtime validation remains open.

### 4.3 PR #158 — N52 is now based on main

PR: `fix(windows): distinguish gateway restart watchers from live processes`

- state: open.
- draft: true.
- mergeable: true.
- base: `main`.
- base SHA: `cc686ab1d31d6ee5ca07243765c5a07e3b9af1af`.
- head branch: `codex/n52-gateway-identity-20260928`.
- head SHA: `86d3149599a2be48a1a66903ba7e3e3a12c819ef`.
- current head tree: `93710f7680cfec66999c5227a08c6d22377ad417`.

The PR body still contains historical wording that it is stacked on N55. The actual PR metadata now says base `main`, because N55 was merged. Use actual base/head metadata, not stale prose.

### 4.4 N53 branch is not a descendant of the current PR #158 head

Current ancestry check:

- `cc686ab…` is an ancestor of `86d31495…`.
- `86d31495…` is not an ancestor of N53 committed HEAD `0a20e2a6…`.
- old PR158 head `10bc0ebc…` is also not a Git ancestor of `0a20e2a6…`.
- merge-base between current PR158 head and N53 HEAD is `eb966ce2cfc1098b46befe9cd8db52be82729f51`.

The N53 branch chain contains locally reconstructed N55/N52-equivalent commits rather than the current public commit lineage:

`242a3562 N55 product → N55 docs → baecdd9c N52 product → N52 docs/carry → 7696e599 N53 → b448ffc8 N53 → N53 docs/carry → 0a20e2a6`

Tree comparison between current PR158 head and N53 committed HEAD shows 12 path differences before the current uncommitted pause-recovery changes. Therefore Cursor must not assume that N53 can be declared current merely by attaching the existing branch to PR158. Reconcile source/tree semantics first.

---

## 5. Linear state — VERIFIED_CURRENT read, history retained

Parent tracking issue:

`B0B-7 — Windows semantic refresh — Cursor引継ぎ・main/PR照合と安全な合流計画`

Current Linear fields:

- status: `Todo`.
- priority: `High`.
- URL: `https://linear.app/zapabob/issue/B0B-7/windows-semantic-refresh-cursor引継ぎmainpr照合と安全な合流計画`.

The issue body still contains older observations in which PR157 was Draft/Open, PR158 was stacked on PR157, and remote main was `eb966ce2…`. Preserve those as historical observations. Do not rewrite history. Add a new dated observation/comment when implementation state changes materially.

Cursor must use B0B-7 as the parent tracking issue. Do not create a duplicate campaign issue. Family-specific work may reference existing related issues, but family state, source binding, tests, CodeGraph, review, publication, main inclusion, and runtime qualification must remain separate fields or evidence entries.

---

## 6. CodeGraph state and mandatory protocol

CodeGraph is a hard gate for product edits/parity claims in this campaign.

### 6.1 Historical validated receipts

Family cards repeatedly bind evidence to approved CodeGraph `1.6.0`. The current N53 card records a final 1.6.0 integration run with:

- 8,923 files.
- 191,274 nodes.
- 613,121 edges.
- pending added/modified/removed = 0/0/0.
- `worktreeMismatch = null`.
- pending refs = 0.
- `_pause_windows_gateways_for_update` at `hermes_cli/update_cmd.py:6219-6614`.
- `_venv_launcher_ancestor_identities` at `5429-5515`.
- impact depth 4 recorded as 47 nodes / 46 edges in the family receipt.

This is historical source-bound evidence for the recorded candidate. It is not permission to skip a fresh bind after another edit or after moving the candidate onto a different parent tree.

### 6.2 Current CLI recheck found an environment mismatch

Current machine recheck found:

- default `node` on PATH: `v26.9.0`.
- CodeGraph refuses Node 26 as unsupported.
- installed NVM Node: `22.14.0`, `22.16.0`, `22.18.0`, `22.23.2`.
- Codex runtime Node also exists at `v24.19.0`.
- global `codegraph.ps1` currently resolves to CodeGraph `1.5.0`, not 1.6.0.
- the active N53 worktree contains a `.codegraph/codegraph.db` but its `.tools/codegraph-cli` directory no longer contains local `node_modules`.

Using Node 22.23.2, CodeGraph 1.5.0 could read the existing index and reported the same 8,923 files / 191,274 nodes / 613,121 edges with no pending file changes. Its `query` and `impact` worked, but `explore` is not a command in 1.5.0. This recheck must not be promoted to a 1.6.0 final receipt.

### 6.3 Cursor's CodeGraph rule

Before changing N53 product code or declaring parity:

1. Resolve the already approved CodeGraph 1.6.0 executable/package and record its exact source/version/help.
2. Use an existing Node 22 or 24 runtime; do not switch the system installation and do not use the unsafe Node 26 override.
3. Do not run `@latest` installation or download a replacement automatically.
4. If approved 1.6.0 cannot be located, mark `BLOCKED_CODEGRAPH` for product edit/parity and continue only independent read-only investigation/documentation.
5. Bind D0, U1, and actual integration as separate indexes/sources as the protocol requires.
6. Run `status → sync only if needed → status → query → explore → impact → affected`, using actual 1.6.0 help syntax.
7. Record root, HEAD/tree, dirty source/test hashes, index identity, excluded-path digest, query strings, returned symbols/callers, dynamic boundaries, and output receipt hashes.
8. After any edit, repeat the source-bound operations. A clean old index is not a new receipt.

Never replace CodeGraph with grep/ripgrep for a parity claim. Static graph output also does not replace native/runtime testing for subprocess, Windows service, Electron IPC, plugin, or Python↔Go boundaries.

---

## 7. Prior local work that must not be reopened without source change

The initial package records the following as `REPORTED_HISTORICAL`, later corroborated by campaign work where applicable:

| Work | Historical state | Rule for continuation |
|---|---|---|
| LM01 | closed; reported commit `20b3d81465` | freshness/inventory support only; do not reimplement without changed source |
| T16 identity subtask | reported commit `d7fc97317b0e46741ac0e012fa414ce326321dc9` | not equivalent to whole T16 closure |
| F01 contract | reported commit `94e406c8ebde65ba9a00ab150a17faf8567cb6c2` | preserve as prior contract evidence |
| LM03 | `8c796578d2a1d7ea0e9020c38038074521fdf7f2`; 19 mutants on Python 3.11 and 3.12 | do not reopen the old final-19-mutant task |
| LM04 | reported `4bb51cdc1c`; review APPROVE_WITH_NITS | reuse; revalidate only affected changed source |
| LM05 | reported `0f6f98ce47`; 17 mutants, 35 baseline tests, 398 passed / 3 skipped per Python | do not count baseline as mutation; do not mark unfinished again |

The reported old local feature branch later resolved on this machine to `feat/cursor-workstation-continue-20260925` with observed HEAD `2622ea42ce3ad044bac4c4e8b9812ba21f7ae65a`. That is historical/local evidence, not the current active integration head.

---

## 8. Family implementation history from the original campaign to latest

Status words below are intentionally preserved from the family cards. `MAPPED` or `GREEN` is bounded evidence, not whole-U1 parity.

### 8.1 N02–N07: retirement, security, authority

| Family | Observable contract and history | Product evidence | Remaining work |
|---|---|---|---|
| N02 | Retire public fixed planner/worker/reviewer model+effort workflow while preserving normal picker, effort, delegation, MoA, approval/Git owners. | product `b56b5adda21cf5d03f3d69ceb720234c3a685ecc`; CodeGraph 1.6.0; public registration retirement tested. | `PARTIAL_PUBLIC_RETIREMENT`; public STOP/live legacy-operation reconciliation and final publication gates open. |
| N03 | Malicious finding plus engine error must not fall through to execution. D0 RED was reproduced; existing T15/T16 local fix reused. | no new N03 product commit; feature `2622ea42…` affected T15 tests 27 passed; controlled mutants killed. | full U1 security mapping, native positive/negative scanner coverage, parser/allowlist scope remain open. |
| N04 | Exact scanned bytes/file identity and Windows quarantine race/ADS handling. | product sequence `836cb99237f2cf22b83c2434740194dbe85eccdf`, `7dcbfded769a3686008f1d39cb1afb0531434329`, `c68fb7f617ecd4fd7d726a03cc316e39a7f8ad15`. | native/durability and campaign mapping remain partial; DPAPI/native limits kept explicit. |
| N05 | Scanner generation/cache and bounded security state. | product `77331f05da1d9ca9c088ae2fd5864a75f651eb01`. | remaining native/durability/ledger qualifications stay separate. |
| N06 | Read-only/fail-closed security observation; missing/corrupt state must not appear healthy. | product `cab98865a777e023a8b6862606796f955c9ae1c8`; CodeGraph 1.6.0. | SQLite WAL sidecar purity, DPAPI-native qualification, full ledger mapping open. |
| N07 | Authority/destination uncertainty. A2 false-success and witness failure fixed; A3 uncertain native reservation fixed. | `01c28864f87582ab81fa3c6bd9fca7495a8c03ca`, `5c2cea7d2dd8a14f440ab687e1880424a2e6a80e`, `0578b52f789cefa568b416e52b30f7ab7a3ce045`. | **P0 N07-A1 open**: host grant-revocation writer does not exist; grant/claim/effect linearization and durable destination evidence remain open. |

### 8.2 N26–N39: bounded Windows semantics and byte/path integrity

| Family | Product commit | Bounded contract | Card state / remaining boundary |
|---|---|---|---|
| N26 | `69caad2f1958e5e51a1fa1513d47a3916e8e0bdb` | uncertain quarantine disposition fails closed | durability/reconciliation/DPAPI open |
| N27 | `7ce34b908a4dd67dc5cbf9f7b558a408002583b3` | NTFS ADS restore semantics | durability/reconciliation/DPAPI open |
| N28 | `4acaca7703491d9aecc88823bddab1b2092a511f` | local background `persist_on_release` | CLI E2E/non-local coverage open |
| N29 | `107ffaf8a423184f9ee782b6f72555f6d896998f` | Windows GUI PATH bare `uv`/`uvx` | real MCP launch/other OS open |
| N30 | `590e9efe325479e9ad65369fe4f7c72fde789275` | child PATH isolation | real SDK/POSIX/PATHEXT concurrency open |
| N31 | `6c83b01c3af96b571caa0767380b93be7974fc30` | Windows PATHEXT isolation | real SDK/first-hit precedence open |
| N32 | `1ab492f98a2370fce914445f91f18e01c3be2645` | explicit child PATHEXT precedence | real SDK open |
| N33 | `e8f89b0fdeff9757fb4c052f1e4d266ae22eef37` | occupied/dangling destination | OS symlink/atomic race open |
| N34 | `f33ef0e9e2b16bde111c260857226bce8b7033f8` | disabled toolset client surface | composite/runtime open |
| N35 | `724e974fc088e4bf270ce57f5f3e5ccd27856d7d` | composite disabled-toolset propagation | local green/runtime open |
| N36 | `a689ed4a18619ee8e5aa9365f4da1afbd55e4fbd` | V4A exact source-byte fence | other patch paths open |
| N37 | `54c5973ec2bfdb782fbd4c67206f1c08e925ba28` | replace-mode exact reads | other file paths open |
| N38 | `2a15742ec5427e77e25b7d33c6c370c0dfa54e8a` | binary sample integrity | other paths open |
| N39 | `f089620091121e450111e232c40b894874f98472` | document byte-read integrity | upstream mapping open |

### 8.3 N40–N51: transport, runtime, Desktop, profile and update semantics

| Family | Product commit | Bounded contract | State |
|---|---|---|---|
| N40 | `1efe1bfe1abc5c5f0bfc7b8f949f1cc77523ff65` | shell argument transport mapped from upstream `948c9dbf…` | local contract green; campaign open |
| N41 | `12d272b80fe5cb0ec70cf97e918676dcbddc318c` | Windows local Python snippets | native green; broader upstream mapping open |
| N42 | none | approval-word semantics already equivalent to final U1 | no product edit; still part of ledger mapping |
| N43 | `12d7dee651ebff5059ab8a9ea272c12fcc6d03d2` | Windows UGit Git discovery | mapped/native green |
| N44 | `9513530e481ad173da8345919580ef2dd5e0479d` | artifact file reveal | mapped/native green |
| N45 | `6dc16d1b269f708e2a6f96b397290ac9cb295557` | corrupted/damaged archive preflight | mapped/native green |
| N46 | `4633a060896cdda2d37a7ae817d3596f6ef4d720` | external/local memory-provider path | mapped/native green |
| N47 | `a9407b2759729dfb1476c33daab8b19f0b6f722e` | Windows startup prompt visibility | mapped/native green |
| N48 | `8e481720fe4b0ba51c662fcf78bba0988dd21a41` | Desktop effort badge separate from model name | mapped/native green; normal picker/effort ownership preserved |
| N49 | `2851da04cb2a690eeb5836e682fb084d6f248697` | Desktop source Python runtime binding | unit green; broader runtime boundary remains partial |
| N50 | `9d0916ed01580c5132b06175c4e91179032095fd` | cross-profile cron dedupe | mapped/native green |
| N51 | `798a3c9762cba79157e4e109ca261ce47f2a2640` | active runtime deletion protection | mapped/native green |

### 8.4 N52–N55: current public/integration edge

#### N52 — process identity

Upstream source family seed: `fae9e5677a3ef339ec582e967ee19cac13bf68af`.

Historical semantic product: `ad6fb9c1f9185027ff3ec66f8feba5bb18135585`.

Later local integration product: `baecdd9ce966a4dc3d5ac404a671251d5576c87b`.

Current public PR #158 head: `86d3149599a2be48a1a66903ba7e3e3a12c819ef` on current `main`.

Contract: Python `-c` restart watchers containing future Gateway/serve argv are not current live Gateway/Desktop processes. Real Gateway and real serve/dashboard processes retain identity. Later review also corrected updater reapers that used substring matching.

Historical validation includes 32/32 focused reaper/Desktop, 197/197 selected Windows/caller, CodeGraph, and independent read-only CLEAR on the integration correction. Old mutation receipts bound to earlier product bytes remain historical rather than automatically rebased to the latest PR head.

#### N53 — relaunch incarnation + pause recovery

Same upstream seed `fae9e567…`, deliberately split from N52/N54 because it is a different observable contract.

Historical semantic branch:

- product `724beb34742f71b5327b61f63b3874f1591a235b`.
- docs `158d83d6cec6219bb5bbac2b4200daf142381991`.

Current local integration sequence:

- `7696e5996c7e003783da575736300234d81274a1` — verify Gateway relaunch by process incarnation.
- `b448ffc85cc366137e95b7e09af3a1652b922016` — verify armed mapped watchers when inventory misses them.
- `d441746f8a347f39e82355895df81c924ff35413` — N53 docs.
- `0a20e2a6ab4f10b3c43fdc498ae41b66f8e230e2` — carry metrics, current committed HEAD.
- current uncommitted pause-recovery corrections listed in section 3.3.

Current contract extends the original `(pid, create_time)` relaunch wait with rollback semantics:

- do not report replacement success while the old incarnation remains live.
- allow the detached 120-second watcher deadline plus a 30-second bound while the old incarnation is pending.
- PID reuse, unreadable identity, stale snapshot, and strict discovery failure must fail closed.
- after pausing an ordinary Gateway, any later drain/force-stop/SCM-stop failure must roll back what this operation actually paused.
- do not replay untouched unmapped siblings.
- keep SCM-owned descendants outside ordinary Gateway stop ownership.
- revalidate launcher incarnation to prevent PID reuse.
- roll back for `BaseException` paths such as `KeyboardInterrupt`, not only ordinary `Exception`.
- preserve rollback failure visibility.

Current family card records:

- initial GPT-6-pro review: REQUEST CHANGES, two P1 + one P2.
- all three findings reproduced RED and corrected.
- pause-recovery tests: 7/7.
- concurrent quarantine tests: 38/38.
- bounded eight-module set: 125/125.
- CodeGraph-affected recovery set: 64/64.
- Ruff 0.15.10 passed.
- `git diff --check` passed.
- six fresh controlled mutants killed on the final recorded source hash.
- second independent GPT-6-pro review bound to the final four Python SHA-256 values is still recorded as pending.

N53 is not complete until that final review result is recovered and any finding is resolved against exactly the candidate being committed.

#### N54 — test-only spawn guard

Historical semantic branch:

- product `cd206ace032747a6ef507947434dd46b68842d04`.
- docs `a7bdad73b9232aa75715b95b5883f3e30b2888b8`.

Contract: tests/conftest admission guard rejects restart-watcher future Gateway spawns before process creation while preserving direct display/container/read-only status paths and closing shell/executable-override bypasses.

Historical evidence:

- selected Windows modules 107 passed.
- six controlled mutants killed.
- CodeGraph 1.6.0.
- independent review CLEAR.

Do not attach these 107 results to a new N53/current-PR158 parent. N54 must be re-composed onto the final N53/current integration source, then affected tests and CodeGraph must be refreshed for that exact tree.

#### N55 — Desktop delegate-session restore

N55 is the only one of N52–N55 already merged into current main.

Contract: a remembered delegate child restores through the user-facing parent; normal `/branch`, profile/connection ownership, stale async responses, and transient lookup failures retain correct behavior.

Merged through PR #157 as described in section 4.2. Packaged Electron/live runtime remains a separate qualification.

---

## 9. Inventory completeness and semantic coverage

The campaign inventory procedure identified:

- 5 fixed history windows totaling 11,960 rows.
- historical ledger rows: 5,105.
- distinct commit metadata records: **17,065**.
- a prior full object walk recorded **417,159** objects with missing 0.

These numbers prove enumeration properties only for the recorded inputs/walk. They do not prove that every commit or object has been semantically mapped, that every observable upstream behavior is adopted, or that each family is release-qualified.

`semantic_review_complete` remains false until every in-scope metadata row has a justified mapping/disposition and every required P0 contract is evidenced.

For each commit/ledger row, the final mapping must land in one or more family records with a disposition such as:

- `ADOPT`.
- `COMPOSE`.
- `ALREADY_EQUIVALENT`.
- `KEEP_DOWNSTREAM_STRONGER`.
- `NOT_APPLICABLE`.
- `DEFER`.
- `SUPERSEDED_OR_REVERTED`.

`DEFER` may not erase a required P0.

---

## 10. Invariants that must not regress

Do not reintroduce any of the following merely because similar upstream code exists:

- fixed planner/worker/reviewer engineering-stage model routing.
- stage-specific forced model/effort ownership.
- strict actor JSON as the ordinary user contract.
- Docker as a mandatory normal execution dependency.

Preserve:

- ordinary model picker.
- provider-supported reasoning/effort.
- normal delegation.
- MoA/fallback.
- existing approval owner and Git owner.
- internal/shared authority unless a concrete ownership conflict is proven.

For lifecycle ownership:

- Electron is the destructive lifecycle owner for the Desktop backend.
- Go may own only the embedding llama that it explicitly launched/owns.
- do not import Linux supervision or a new PM owner as a second owner for the same Windows runtime role.

For security and Control MCP:

- observation/freshness metadata is not write authority.
- graph freshness is not native success.
- test success is not human approval.
- `OWNERSHIP_PROPOSAL.json` is not a lease.
- shared authority/config/registry/conftest/lock paths must not have parallel writers across worktrees.

---

## 11. P0 gates that remain open

### 11.1 N07-A1 — grant revocation host writer

The user explicitly clarified that the host implementation that writes grant revocations has not been implemented.

Therefore:

- injected `grant_lookup` behavior is not a real host revocation writer.
- claim-time grant revalidation is not equivalent to an implemented revocation writer.
- grant revoke/claim/effect must have one linearization contract before T12.

### 11.2 T06

Before write enablement, complete useful native positive and negative evidence, trusted producer binding, separate apply approval, and actual writer fence as defined by the campaign's T06/T12 acceptance materials.

### 11.3 T12

Before T12 completion:

- destination outcome must have durable, identity-bound evidence.
- a write that lands but whose journal/witness acknowledgement fails must reconcile without false success or duplicate effect.
- trusted producer and actual writer ownership must be shown in the same source-bound candidate.

Until these gates are closed:

**Control MCP production write remains DISABLED.**

Do not enable it as a prerequisite for investigating or merging otherwise independent families.

---

## 12. Cursor execution order

### Phase 0 — read-only preflight

Before any edit:

1. Re-read PC/repo/scoped AGENTS and SOPs.
2. Record current date/time and exact repo root.
3. Record every worktree, branch, full HEAD, tree OID, staged/unstaged/untracked/ignored state.
4. Record owner/lease files relevant to the chosen family.
5. Re-read current GitHub PR157/158 metadata and `origin/main` SHA.
6. Re-read Linear B0B-7; append a new dated measurement rather than overwriting history.
7. Resolve approved CodeGraph 1.6.0 and bind the actual candidate. If unavailable, stop product edits with `BLOCKED_CODEGRAPH`.
8. Fingerprint all family source/test/config files before changing them.

No `reset`, `stash`, `clean`, delete, rename, bulk move, or primary-checkout repair is part of this phase.

### Phase 1 — close N53 on its current source candidate

1. Recover the second independent GPT-6-pro review result that is bound to the four final Python SHA-256 values.
2. Verify the review actually inspected those bytes, including:
   - SCM descendant ownership separation.
   - launcher PID reuse/revalidation.
   - `BaseException` rollback.
   - ordinary rollback of already-paused Gateways.
   - untouched unmapped sibling non-replay.
   - rollback-failure visibility.
3. If review is CLEAR and no source changed, do not rerun unrelated historical suites merely for volume.
4. If a finding changes source, create a real RED/equivalence proof first, make the smallest implementation change, rerun focused/affected/native checks, refresh mutations if the mutated contract changed, refresh CodeGraph 1.6.0 after the edit, then re-review.
5. Recompute final file hashes.
6. Update N53 card to the actual review result and exact final source binding.
7. Run `git diff --check`.
8. Commit only explicit N53 paths when all evidence is bound to the exact commit candidate.

Do not include this Cursor handoff document or unrelated dirty files in the N53 product commit unless the repository's documented commit split intentionally includes docs in a separate explicit-path docs commit.

### Phase 2 — reconcile N53 against current PR158/main lineage

Because current public PR158 (`86d31495…`) is not an ancestor of the current N53 branch, do not treat a branch move as proof of equivalence.

1. Compare current PR158 tree/source with the N52-equivalent bytes embedded in the N53 worktree.
2. Identify the exact N52 public corrections present in PR158 but absent/different in the N53 branch.
3. Build a clean integration candidate from current main/PR158 state using repository-approved local composition, preserving family authorship/evidence. Do not import the historical branch wholesale.
4. Reapply/compose only N53's observable contract onto that current parent.
5. Re-run N52/N53 interaction tests required by the changed parent.
6. Rebind CodeGraph 1.6.0 to the new integration source and repeat query/explore/impact/affected.
7. Independently review the composed diff.

Do not call this a rebase of upstream. The critical requirement is source/tree semantic composition, not preservation of a particular local branch topology.

### Phase 3 — compose N54 onto the final N53 parent

1. Use historical N54 product `cd206ace…` as evidence/reference, not as an instruction to move the entire old semantic-refresh tree.
2. Inspect the final N53 spawn/resume paths and ensure the test admission guard still covers all future Gateway spawn forms.
3. Reproduce any new RED introduced by the changed parent.
4. Apply the smallest N54 guard/test composition.
5. Run N54-focused and affected Windows tests on this exact parent.
6. Run fresh mutation cases for any altered guard branch.
7. Rebind CodeGraph 1.6.0 after the final edit.
8. Independent review.
9. Commit explicit N54 paths only; docs separately if that remains the established family pattern.

### Phase 4 — publication/stack review

The target public structure after N53/N54 is validated should be reviewable as small family layers while allowing a single main-facing aggregate decision.

Current published state starts with:

`main(cc686) → PR158/N52(86d314…)`

N53 and N54 should be layered from the actually validated current parent. Do not resurrect the old `main → PR157 → PR158` state; PR157 is already merged.

Before opening/updating a PR:

- verify exact base/head/tree.
- verify the PR diff is only the intended family layer plus required evidence/metrics.
- verify CI on the exact current head.
- distinguish skipped jobs from successful executed jobs.
- inspect Windows-specific workflow coverage.
- keep packaged Electron qualification separate from N55's source/UI validation.
- do not claim OSV neutral/warnings as either a proven vulnerability or a complete clean scan without the configured coverage.

No direct-main push or force push. Normal PR publication/merge remains a separate explicit operation from this handoff plan.

### Phase 5 — aggregate candidate

After N52/N53/N54 layers are source-bound and reviewed:

1. Form one aggregate candidate against the then-current observed `main` without moving D0/R2/U1/U0.
2. Compare merge-base, two-dot final tree diff, and three-dot PR diff separately.
3. Verify no primary-checkout WIP, `$tmp`, CodeGraph cache, local receipts, secrets, personal state, nested repo, or unrelated formatter branch is present.
4. Run the cross-family affected suite for N52/N53/N54 and N55-adjacent Desktop/update call paths.
5. Run relevant Windows CI on the exact aggregate head.
6. Run CodeGraph 1.6.0 against the exact aggregate source.
7. Run independent review of the aggregate diff in addition to family reviews.

Family test counts must not be added together and presented as one aggregate test count unless the aggregate head actually executed that combined suite.

### Phase 6 — campaign-wide semantic ledger completion

Continue from the existing `metadata_universe.jsonl`, `family-map.jsonl`, and adoption decision evidence.

For every in-scope row:

1. map upstream commit/merge parents and fixup/revert lineage.
2. identify final U1 observable behavior.
3. identify actual downstream owner/caller on the current candidate.
4. connect prior local implementation if one exists.
5. assign a disposition with reasoning.
6. attach source-bound tests/mutation/native/CodeGraph/review evidence as applicable.
7. create additional families when existing seed families do not capture an observable contract.

Do not stop because 25 seed families or 50 acceptance specs were exhausted. The completion unit is the in-scope ledger plus discovered observable contracts.

### Phase 7 — P0 authority and writer gates

Only after the relevant source is stable:

1. implement the real N07-A1 host grant-revocation writer under the correct owner.
2. prove grant/claim/effect linearization.
3. close durable destination outcome evidence.
4. close T06 useful native positive/negative cases.
5. close trusted producer, separate apply approval, and actual writer fence.
6. independently review and source-bind the final authority/writer paths.

Control MCP production write remains disabled throughout this phase until all required gates are satisfied.

---

## 13. Per-family implementation template

Every family continuation uses this sequence:

`actual source/caller → RED or existing-equivalence proof → smallest implementation → GREEN → affected/native → mutation → fresh CodeGraph 1.6.0 after → independent review → explicit-path commit → docs receipt`

Required evidence record:

| Axis | Required content |
|---|---|
| Source | repo, worktree, branch, HEAD/tree, dirty fingerprints, source/test SHA-256 |
| Upstream | exact commit/ledger row, final U1 behavior, fixup/revert lineage |
| Ownership | actual public entrypoint, registry/construction, owner, authorization, effect/output, recovery |
| RED/equivalence | failure before fix or actual-call-path equivalence proof |
| GREEN | exact commands, test counts, skips/xfails, environment |
| Native | real Windows/runtime boundary when needed; absence explicitly recorded |
| Mutation | changed contract branch killed by regression test and restored |
| CodeGraph | version/source/index/status/query/explore/impact/affected and dynamic-boundary limits |
| Review | independent reviewer, exact source hashes, actionable findings, result |
| Integration | local product commit/tree, public PR base/head, main inclusion status |
| Runtime | packaged/live qualification separate from source tests |
| Gaps | remaining contract, severity, dependency, revisit trigger |

---

## 14. Prohibited shortcuts

Do not perform any of the following as part of the semantic refresh merely to make the numbers or history look complete:

- replace U0 with U1.
- move U1 to a newer upstream SHA without a new explicit campaign record.
- bulk merge/rebase/cherry-pick upstream as a substitute for family review.
- direct-main or force push.
- tunnel changes.
- Defender disable/exclusion changes.
- production Gateway/Desktop restart.
- production Control MCP write enablement.
- automatic CodeGraph `@latest` install.
- unsafe Node 26 CodeGraph override.
- treat grep as CodeGraph.
- treat CodeGraph `complete` as semantic or runtime qualification.
- treat a merged PR as live runtime qualification.
- treat a test count from one parent/source as evidence for a different tree.
- treat `missing 0` or 17,065 metadata rows as semantic parity percentage.
- reopen LM03 final-19-mutant or LM05 final-17-mutant work without changed source.
- delete or reorganize unrelated WIP to make a worktree look clean.
- move nested repositories such as AIRI into Hermes publication scope.

---

## 15. Completion criteria for this campaign

The campaign may be described as complete only when all of the following are true for the fixed D0/R2/U1/U0 scope:

1. every in-scope metadata/ledger row has an evidence-backed family/disposition mapping.
2. additional families discovered beyond the original seeds are included.
3. no required P0 remains unreviewed or unproved.
4. every implemented family has source-bound RED/equivalence, GREEN, affected/native evidence as applicable, mutation where required, fresh approved CodeGraph, independent review, and explicit commit/tree binding.
5. aggregate integration is tested/reviewed on one exact candidate rather than inferred from sums of historical receipts.
6. current main inclusion is separately recorded from local implementation and PR publication.
7. packaged/live runtime qualifications are separately recorded where required.
8. Control MCP write gates are closed before production write is enabled.
9. publication/deployment/restart is performed only under its separate authorization and exact-head gates.

Until then, the correct campaign state is a set of bounded verified contracts plus explicit open gaps, not a parity percentage.

---

## 16. Immediate next-action checklist for Cursor

Cursor should begin with this exact order:

- [ ] Read PC/repo/scoped AGENTS and SOPs.
- [ ] Re-measure all worktrees and preserve primary/semantic WIP.
- [ ] Re-read GitHub PR158 and current `origin/main`; do not rely on stale PR body/Linear prose.
- [ ] Re-read Linear B0B-7 and append the new observation timestamp.
- [ ] Locate approved CodeGraph 1.6.0; use existing Node 22/24; no install/unsafe Node 26.
- [ ] Recover N53 second GPT-6-pro review bound to the four final Python SHA-256 values.
- [ ] Resolve findings, if any, with RED → minimal fix → focused/affected/native → mutation → fresh CodeGraph → re-review.
- [ ] Commit N53 only after source/test/card/review all bind to the same candidate.
- [ ] Compare/re-compose N53 against current PR158 head `86d3149599a2be48a1a66903ba7e3e3a12c819ef` because the current N53 history is not its descendant.
- [ ] Compose N54 onto that final N53 parent and revalidate its guard on the new source.
- [ ] Build/review the aggregate candidate against current main while keeping PR157 historical state out of the active stack.
- [ ] Continue ledger semantic mapping and new-family discovery.
- [ ] Close N07-A1/T06/T12 authority/writer gates before any production write enablement.

The first product edit after this handoff should therefore be driven by the recovered N53 final review or by a proven source/tree reconciliation gap against the current PR158 parent. Do not start a new unrelated family while N53's current dirty candidate and parent-lineage mismatch remain unresolved.
