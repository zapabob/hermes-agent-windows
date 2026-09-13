# Functional inventory — semantic refresh 2026-09-13

REUSE H..U ledgers + U public surfaces. REIMPLEMENT_NATIVE in schema_notes.

Coverage (separate flags — none imply LOCAL_DEPLOYED/soak):

| Coverage | State |
|---|---|
| inventory | PARTIAL→fuller (families below classified; U full surface census still incomplete) |
| implementation | SR-001..006 + 003b + **007a+007b** done; card chrome SKIP |
| verification | Focused Windows pytest + Desktop vitest on landed slices; LOCAL_DEPLOYED=NOT_RUN; soak=NOT_RUN |

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

## FI-* families (census continue)

| Family | U entrypoints (frozen) | D owner | Decision | Notes |
|---|---|---|---|---|
| FI-CLI | `hermes_cli/main.py`, commands registry | same | KEEP / ALREADY | COMMAND_REGISTRY |
| FI-TUI | `ui-tui` + `tui_gateway` | same | KEEP | JSON-RPC parity |
| FI-DESKTOP-UX | onboarding / Settings providers | `onboarding.ts`, Settings | ADOPT_PARTIAL | cards SKIP; **007a+007b DONE** |
| FI-GATEWAY | `gateway/run.py`, platforms | same | KEEP / prior COMPOSE | multiplex authz |
| FI-MCP | `tools/mcp_tool.py` | monolithic | PORT subset | 006a/006b |
| FI-TOOL-GATE | `tools/managed_tool_gateway.py` | same | REIMPLEMENT_NATIVE | 007a share_auth |
| FI-MEMORY | plugins/memory/* | same | prior COMPOSE | 004b |
| FI-PROVIDER | auth / auxiliary | `hermes_cli/auth.py` | KEEP | SoT for 007a |
| FI-RUNTIME | watchdog / llama / ConPTY | `scripts/windows/*` | KEEP_DOWNSTREAM | no second supervisor |
| FI-CRON | `cron/` | same | KEEP | |
| FI-DELEGATION | `tools/delegate_tool.py` | same | KEEP | |

Evidence rows still thin for FI-CLI/TUI/CRON/DELEGATION (classify-only). Next campaign: deepen those or LOCAL_DEPLOYED when requested.
