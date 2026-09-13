# Receipt — FI-SKILL / PLUGIN / BROWSER census — 2026-09-13

| Field | Value |
|---|---|
| base_sha | `501d4e5eacb63875d34c793276d5f50cd651c791` |
| U_frozen | `6dd091a89c33e6e4909a80f78343bb384deb5ca8` |
| decision | KEEP / KEEP_DOWNSTREAM (census only) |
| runtime_delta | **none** |
| CodeGraph | root index ABSENT; `.tools/codegraph-cli` present — evidence is source/registry probes, not CodeGraph |
| LOCAL_DEPLOYED | NOT_RUN |
| soak | NOT_RUN |

## Census highlights

| Family | Decision | Key evidence |
|---|---|---|
| FI-SKILL | KEEP | skills_hub + skill_manager + skill_commands; D 87 bundled / 120 optional SKILL.md vs U 58 / 143 |
| FI-PLUGIN | KEEP + KEEP_DOWNSTREAM | U 18 tops ⊆ D 67; hermes_cli.plugins discovery |
| FI-BROWSER | KEEP | shared browserbase/browser_use/firecrawl; deeplink vitest 10p; camofox suites present |

## Verification

- pytest FI-SPB stable: **89 passed, 3 skipped** (symlink + hook-timeout deselected)
- vitest browser-deeplink + deeplink-routes: **10 passed**
- LOCAL_DEPLOYED / soak: NOT_RUN

## Why no code slice

Inventory rows are already KEEP / prior COMPOSE (004e camofox memo, browser handoff CARRY). No clear ready PORT/COMPOSE/REIMPLEMENT_NATIVE acceptance gap without inventing work (bot_profile explicitly out).

## Ops note

A concurrent checkout briefly detached HEAD to `84e4b6399a` during metrics regen; restored to `main` @ `501d4e5eac` before this commit.

## Intentionally untouched WIP

`Start-HermesGoWatchdog.ps1`, `test_readme_contract.py`, handoff report dirty trees left alone.
