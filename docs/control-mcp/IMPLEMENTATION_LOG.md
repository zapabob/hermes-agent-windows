# Hermes Control MCP implementation ledger

Updated: 2026-09-24 JST. Repository: `zapabob/hermes-agent-windows` only. This ledger records observed results; an unchecked item is not a completed capability.

## Provenance and isolation

- Verified baseline `origin/main`: `34562508555d84f0740eda7a0af5ec4ff90bbe60`. Approved document source: `73e6c5f01b961c25ca422db2a9e923fe56d504c2`.
- Advanced handoff archive had six original commits ending `b87ac9483fd5b18f7d2ad2e7d6be1dce836078ba`; it was replayed into the isolated Windows worktree `hermes-control-mcp-recovered-20260923`, branch `feat/hermes-control-mcp-c-20260923-recovered`. New replay SHAs: `9cd69f18f6ee0c61e0c18f38484844b6e4c66a45`, `bfbc2e124c91c155cae89fcb2f25a127c3d68cda`, `bf544a5e497a3224d050d76957531a1457ee8ed3`, `76e0f45276952afee26c028b968568c5bad4107a`, `117250d0230a7d8adf613afdd909149613059f0f`, `af38acb37e343f1192bfe7190b37fd433fd54044`.
- Approved design and plan commits: `2581f41ed18ba15331ab53c402ca1cb1cb827382`, `deb80b356485d23dd3850253eb3a0547d8b4052c`. The user explicitly authorized implementation, TDD, isolation and conditional merge in the task request; older plan text requesting implementation approval does not override that instruction.
- The original feature worktree and the 0.21.4/upstream worktrees were preserved. The primary checkout and running Desktop/Go/llama processes were not changed.

## Task results

| Task | State | RED and GREEN evidence | Code SHA | Remaining gate |
| --- | --- | --- | --- | --- |
| 0 freeze/baseline | Partial | Source/branch/worktree inventory and locked `uv sync --locked --python 3.11 --extra all --extra dev` completed. Initial sync failed for low C: space, then succeeded after space recovered. | n/a | Full ordinary baseline and CI pending. |
| 1 read facade | Partial | Handoff recorded import-only RED separately from meaningful assertions. On this Windows PC, component suite initially: 130 passed, 1 skipped; no live client read. | `9cd69f18`, `bfbc2e12`, `af38acb3` | Run/evidence producer mapping and real host enablement pending. Reads still report unsupported where producer is unwired. |
| 2 journal/approval | Partial | Handoff journal/decision tests are behavioural. New TUI tests first failed on missing strict RPC and permissive choices, then passed. Desktop tests first failed on normal RPC, missing digest and reconnect mapping, then passed. File-isolated Python run: 217 passed, 1 skipped across five files. Desktop focused tests: 63 passed. TUI focused tests: 120 passed. | `bf544a5e`, `a33bc9d23b8860b274545e65ba5e60a8e92bc676` | MCP admission is not wired to a real human session or host executor. Real human approval and actual write not proven. |
| 3 MCP auth/protocol | Partial | SDK import RED, then HTTP 404 behaviour RED before transport wiring. Real locked SDK client, two scoped identities, revocation, parent mount/dashboard bypass: GREEN. | `76e0f452`, `117250d0`, `b355c937c4f384154730fc883a239c32067c0f44`, `1d4919cac1438c2b62a3eabf45e27606ecfa8c3a` | No approved issuer/client registration, startup config, operational endpoint or live client auth. No write tools are advertised. |
| 4 engineering owner/evidence | Partial | Native host writes fsynced manifest, terminal result and typed check receipts. Meaningful RED on missing receipt/unsupported reader, then GREEN. File-isolated component run: 216 passed, 3 skipped across 15 files; Ruff passed. Negative cases cover failed exit, timeout, wrong attempt, missing check, source/route mismatch and cross-workspace denial. | `5e985dbb8e8eeda541851699643e7c0e5a47e1a8` | Actual start/cancel/reverify controls, Docker acceptance and live producer session remain pending. |
| 5 route CAS | Not started | n/a | n/a | Native picker validation and atomic config authority. |
| 6 verified apply | Not started | n/a | n/a | Provenance and guarded destination promotion. |
| 7 PR/merge controls | Not started | n/a | n/a | Parent-only Git authority, separate approval and remote protection checks. |
| 8 qualification | Not started | n/a | n/a | i18n, 24 negatives, real Windows/Docker, two clients, exact-head CI/security review. |

## Test boundaries and defects

- Direct multi-file pytest in one interpreter reported 5 existing approval failures (unattended/timeout). Those two representative cases passed alone; the repository-prescribed file-isolated runner passed all five files with 217 tests, 1 skip, no retries. The direct run is retained as a test-isolation finding, not concealed.
- Desktop renderer typecheck in the recovered worktree uses junctions to the untouched primary checkout's `node_modules`. It exits 2 with approximately 1,387 duplicate React type errors from the shared dependency path; filtered errors in changed files were 0 after fixing event and resume typings. This does not qualify as a full typecheck pass. TUI typecheck passed. ESLint on changed Desktop/TUI files had no errors; pre-existing padding warnings in the TUI event handler remain.
- The one skipped Python test in the earlier approval run depends on platform privilege; it is not a successful Windows negative scenario. The later engineering component run had 3 skips, reported separately from passes.
- No remote endpoint, tunnel, client account, provider credential, Docker service, PR or main merge was activated by these tests. No production write is enabled.

## Current release gates

Do not advertise C or merge while Tasks 4–8, real client authentication/read/approved-write, full exact-head checks and security review remain open. Live endpoint and client settings require a separate concrete operator approval; Pro feature limitations must be reported as client limitations rather than masked as read results.
