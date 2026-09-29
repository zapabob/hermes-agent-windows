# PR #145 MCP-only port (Cursor)

Date: 2026-09-26 09:35 +09:00
Branch: `feat/control-mcp-port-20260926` (base `origin/main` 60deb5c753)
Source: #145 head `b9f651d3f2` (merge-base `a62a3d1ae6`; branch deleted, fetched via `refs/pull/145/head`)

## Overview

Carries only the MCP-related work from #145 (Hermes Workstation Campaign
2026-09-25) onto main as a clean PR. The Control MCP host remains opt-in and
read-only: it mounts only when a trusted bootstrap sets
`app.state.control_mcp_startup_config`; there is no `config.yaml` key, and
`hermes_get_capabilities` reports `write: false` with every write operation
false.

## Background / requirements

- Port only MCP changes; never include b1d48ec / 122e4ac3 or revert to
  4e4cfe24 / e6070028; do not reopen LM01, T16, LM03, LM04.
- No model picker, provider or OAuth change. Control MCP write stays disabled.
- Deps / relay 0.8 / credential masking / Windows test portability / memory
  (#147-#154) already on main: not re-applied. T06, T16, non-MCP carries and
  bare-skipif changes excluded.

## Classification

| Group | Decision | Content |
|---|---|---|
| Control MCP server | Ported | `downstream/control_mcp/*`, `tests/control_mcp/*` (except catalogue lifespan test), `tests/e2e/test_control_mcp_host.py` |
| Authority integration | Ported | `tools/approval.py` control bindings, `tui_gateway/methods_prompt.py` `control_approval.respond`, `tui_gateway/server.py` control choices, `hermes_cli/config.py` `peek_effective_config`, dashboard auth bypass for the control resource, `web_server.py` host prepare / lifespan / token seam, `plugins/implementation_router/*` control entry |
| S06 MCP enabled parser (MCP hunks of 9f3aad3e94) | Ported | `tools/mcp_tool.py`, `agent/coding_context.py`, `hermes_cli/mcp_*`, `oneshot.py`, `tools_config.py`, `tui_gateway/mcp_*`, `web_server.py` MCP summary / OAuth scope hunks, Desktop MCP tab + shared cases |
| Control approval UI | Ported | Desktop and ui-tui strict control approval presentation (a33bc9d23b, d40e052476, 9ef2897370, 8c796578d2) |
| mcp_serve test | Ported | deterministic mtime fixture (76a194dbe6) |
| Docs | Ported | design / plan / retirement spec / F01 contract / control-mcp records; ledger trimmed to Control MCP entries |
| Everything else | Excluded | T05-T16 free routes (incl. catalogue lifespan hooks in `web_server.py` and `gateway/run.py`), F00/LM inventory, Luna Max / freeze material, `evidence/`, deps / relay / lock changes, S05 state, S12 plugin trust, S13 network, profile runtime scope, model picker, codegraph pane |

Dependency check: none of the ported hunks depend on b1d48ec / 122e4ac3; the
free-route catalogue start/stop block that shared `_lifespan` with the control
host was removed by hand, leaving only `async with control_host.lifespan()`.

## Commits

1. `feat(control-mcp)`: host and approval authority (42 files)
2. `fix(mcp)`: one parser for `mcp_servers.<name>.enabled` (18 files)
3. `feat(approval)`: strict control approvals in Desktop and TUI (29 files)
4. `test(mcp)`: deterministic event-bridge mtime fixture
5. `docs(control-mcp)`: design, plan, contract and records (12 files)
6. `chore(downstream)`: regenerated carry surface + this log

## Commands

- `git diff a62a3d1ae6 origin/pr145 -- <paths> --output=...; git apply -3` (path-scoped), hunk-split staging for mixed files
- `pytest` per file with the workspace venv, `uvx ruff@0.15.10 check`
- `vitest` (apps/desktop, ui-tui), `tsc --noEmit` (ui-tui)
- `scripts/downstream/carry_metrics.py` then `--check`; `scripts/downstream/validate_policy.py`; `tests/downstream/test_ci_contracts.py`

## Verification

- Control MCP + e2e + mcp_serve + enabled reader + schema sanitizer + tui protocol + project metadata: 573 passed, 1 skipped (runtime symlink privilege skip).
- Ruff on changed Python: pass.
- Desktop vitest 104 passed (6 files); ui-tui vitest 130 passed (2 files); ui-tui tsc pass.
- Write disabled by default: `test_existing_host_startup_is_disabled_without_explicit_config` passes; capability tests assert `write: false`; no control_mcp config default.
- No bare `skipif` in carried tests.
- Wider regression (approval / mcp / web_server / dashboard auth / implementation_router, per file): every failure reproduces identically on an `origin/main` baseline worktree (dashboard auth gate port 9119 held by a live backend, approval timeout overflow, profile-scoped web server writes, mcp catalog bearer headers, oauth write perms).
- `carry_metrics.py --check`: "Carry metrics are current." `validate_policy.py`: passed. `test_ci_contracts.py`: 12 passed.

## Residual risk

- Desktop `tsc` not clean locally because `node_modules` is a junction to another checkout (duplicate `@types/react`); CI is the authority there.
- Control MCP remains read-only; any future write surface needs the contained subagent mode and host approval noted in the ledger.

## Next actions

- Merge, confirm main `Downstream policy` green, comment on #145 with what was ported and what remains there.
