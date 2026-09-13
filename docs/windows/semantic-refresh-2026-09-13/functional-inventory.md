# Functional inventory — semantic refresh 2026-09-13

REUSE H..U ledgers + U public surfaces. REIMPLEMENT_NATIVE in schema_notes.

Navigation note: root `.codegraph/` **ABSENT** this phase; evidence from source/registry probes + focused tests (not claimed as CodeGraph).

Coverage (separate flags — none imply LOCAL_DEPLOYED/soak):

| Coverage | State |
|---|---|
| inventory | PARTIAL→fuller (FI-CLI…DELEGATION + **FI-SKILL/PLUGIN/BROWSER** evidence) |
| implementation | SR-001..007 + CARRY-RECHECK done; **no new runtime slice this phase** (no ready gap) |
| verification | Focused pytest/vitest on FI-SPB + prior CARRY; LOCAL_DEPLOYED=NOT_RUN; soak=NOT_RUN |

| ID | Decision | Method | Status |
|---|---|---|---|
| SR-001 | COMPOSE | REUSE_AND_EXTEND | PASS |
| SR-002 | SKIP | NONE | POSIX-only |
| SR-003 | ADOPT | REIMPLEMENT_NATIVE | 003a+003b PASS_FOCUSED |
| SR-004f | ALREADY_EQUIVALENT | KEEP | on main |
| SR-005 | COMPOSE | REUSE_AND_EXTEND | PASS |
| SR-006 | PORT | NATIVE_PORT | 006a PASS; 006b ALREADY |
| SR-007 | ADOPT_PARTIAL | REIMPLEMENT_NATIVE/SKIP cards | **007a+007b PASS** |
| SR-008 | SKIP | NONE | Linux-only |
| SR-CARRY-RECHECK | ALREADY_EQUIVALENT_OR_KEEP | KEEP | **PASS_FOCUSED** @ `c11161a68f` |
| FI-SKILL / PLUGIN / BROWSER | KEEP / KEEP_DOWNSTREAM | KEEP | **census PASS** @ `501d4e5eac`+ |

## FI-* families (census + evidence)

| Family | U entrypoints (frozen `6dd091a89c`) | D owner | Decision | Evidence |
|---|---|---|---|---|
| FI-CLI | `hermes_cli/main.py`, `COMMAND_REGISTRY` | same | KEEP / ALREADY | U+D both **102** `CommandDef(` |
| FI-TUI | `ui-tui` + `tui_gateway` JSON-RPC | same | KEEP | **92** `tests/tui_gateway/*.py`; WS deadline CARRY green |
| FI-DESKTOP-UX | onboarding / Settings | `onboarding.ts` | ADOPT_PARTIAL | **007a+007b DONE**; cards SKIP |
| FI-GATEWAY | `gateway/run.py`, platforms | same | KEEP / prior COMPOSE | multiplex + relay F-004 |
| FI-MCP | `tools/mcp_tool.py` | monolithic | PORT subset | 006a/006b |
| FI-TOOL-GATE | `tools/managed_tool_gateway.py` | same | REIMPLEMENT_NATIVE | 007a share_auth |
| FI-MEMORY | plugins/memory/* | same | prior COMPOSE | 004b |
| FI-PROVIDER | auth / auxiliary | `hermes_cli/auth.py` | KEEP | aux origin CARRY green |
| FI-RUNTIME | watchdog / llama / ConPTY | `scripts/windows/*` | KEEP_DOWNSTREAM | ConPTY CARRY green |
| FI-CRON | `cron/` | same | KEEP | **81** cron tests; dead-owner reap green |
| FI-DELEGATION | `tools/delegate_tool.py` | same | KEEP | leaf/orchestrator + depth; **25** delegate tests |
| **FI-SKILL** | `skills/`, `optional-skills/`, `tools/skills_hub.py`, `tools/skill_manager_tool.py`, `agent/skill_commands.py` | same | **KEEP** | D: **19** cats / **87** `SKILL.md`, optional **21**/`120`; U: **58** / **143** optional. Hub has `OptionalSkillSource` + `SkillSource` ABC. Slash skills inject as user messages (cache-safe). Tests: **44** under `tests/skills/` + `test_skill_manager_tool` (symlink-dir refuse needs Windows SeCreateSymbolicLink — env-limited, not a missing contract). No Windows-ready gap → no invent. |
| **FI-PLUGIN** | `plugins/`, `hermes_cli/plugins.py`, `plugin_storage.py` | same + **D-only tops** | **KEEP / KEEP_DOWNSTREAM** | U tops **18** (browser, memory, platforms, …). D tops **67** (U set ⊆ D; extras: hermes-bot-mode, world-intel-osint, …). Discovery via `discover_entrypoint_manifests` / `get_bundled_plugins_dir`. Tests: **190** under `tests/plugins/` + `tests/hermes_cli/test_plugins*.py`. Do **not** PORT U layout by deleting D-only plugins. |
| **FI-BROWSER** | `tools/browser_tool.py`, `browser_camofox.py`, `browser_use_cli.py`, `plugins/browser/{browserbase,browser_use,firecrawl}` | same | **KEEP** (+ CARRY COMPOSE handoff) | U+D same provider tops. Core tools register `browser_navigate/snapshot/click/…`. Camofox + provider plugin suites present. Desktop `hermes://open/browser` CARRY KEEP (vitest deeplink **10 passed** this phase). Prior 004e camofox/tirith profile memo already on main. |

### Thin → fuller notes

- FI-SKILL / PLUGIN / BROWSER: evidence rows filled. **No executable slice** — contracts already KEEP / prior COMPOSE; inventing `bot_profile` / second plugin supervisor forbidden.
- Next inventory deepening (docs-unless-ready): FI-UPDATE packaging, FI-VOICE/TTS (D-heavy), mechanical H..U backlog `UNRES-FULL-H-U-CLASSIFICATION`.
- CodeGraph: pin CLI exists under `.tools/codegraph-cli`; root index absent — do not claim graph navigation for this phase.

## FI-SPB focused verification (this phase)

| Suite | Result | Notes |
|---|---|---|
| memory multiplex + browser providers + camofox + skill_manager (−symlink/−timeout) | **89 passed, 3 skipped** | `tmp/probes/fi-spb-stable-2026-09-13.txt` |
| `test_skill_manager_tool::test_symlinked_skill_dir_refused` | FAIL env (deselected) | WinError 1314 privilege — not a missing contract |
| `test_plugins::test_pre_tool_call_timeout_fail_closed` | intermittent (deselected) | timing flake ~1.31s vs 1.0s bound |
| vitest browser-deeplink + deeplink-routes | **10 passed** | CARRY desktop-browser-chrome-edge-handoff |

`LOCAL_DEPLOYED` / soak: **NOT_RUN**.

## CARRY-RECHECK (prior evening — still valid)

See `receipt-carry-recheck-2026-09-13.md`. Prior PORT items KEEP @ `c11161a68f` (pytest 96p/1s; vitest 80p).
