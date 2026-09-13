# Functional inventory — semantic refresh 2026-09-13

REUSE H..U ledgers + U public surfaces. REIMPLEMENT_NATIVE in schema_notes.

Coverage (separate flags — none imply LOCAL_DEPLOYED/soak):

| Coverage | State |
|---|---|
| inventory | PARTIAL→fuller (FI-* evidence rows below; U full surface census still incomplete) |
| implementation | SR-001..006 + 003b + **007a+007b** done; card chrome SKIP; **CARRY-RECHECK PASS_FOCUSED (no new code)** |
| verification | Focused Windows pytest + Desktop vitest on landed slices + CARRY PORT suite @ `c11161a68f`; LOCAL_DEPLOYED=NOT_RUN; soak=NOT_RUN |

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

## FI-* families (census + evidence)

| Family | U entrypoints (frozen `6dd091a89c`) | D owner | Decision | Evidence @ `c11161a68f` |
|---|---|---|---|---|
| FI-CLI | `hermes_cli/main.py`, `COMMAND_REGISTRY` | same | KEEP / ALREADY | U+D both **102** `CommandDef(`; sample cmds `start/new/topic/clear/…`; no Windows-only gap invent |
| FI-TUI | `ui-tui` + `tui_gateway` JSON-RPC | same | KEEP | packages present; **92** `tests/tui_gateway/*.py`; WS send-deadline CARRY green (`test_ws_send_timeout.py`) |
| FI-DESKTOP-UX | onboarding / Settings providers | `onboarding.ts`, Settings | ADOPT_PARTIAL | cards SKIP; **007a+007b DONE**; OAuth Sign-in-again CARRY vitest green |
| FI-GATEWAY | `gateway/run.py`, platforms | same | KEEP / prior COMPOSE | multiplex authz prior; relay F-004 CARRY green |
| FI-MCP | `tools/mcp_tool.py` | monolithic | PORT subset | 006a/006b |
| FI-TOOL-GATE | `tools/managed_tool_gateway.py` | same | REIMPLEMENT_NATIVE | 007a share_auth |
| FI-MEMORY | plugins/memory/* | same | prior COMPOSE | 004b |
| FI-PROVIDER | auth / auxiliary | `hermes_cli/auth.py` | KEEP | SoT for 007a; aux origin/progress CARRY green |
| FI-RUNTIME | watchdog / llama / ConPTY | `scripts/windows/*`, `win_pty_bridge.py` | KEEP_DOWNSTREAM | no second supervisor; ConPTY CARRY `test_win_pty_bridge.py` **15 passed, 1 skipped** |
| FI-CRON | `cron/jobs.py`, `cron/scheduler.py` | same | KEEP | U+D files present; **81** `tests/cron/test_*.py`; dead-owner reap CARRY green |
| FI-DELEGATION | `tools/delegate_tool.py` | same | KEEP | `_normalize_role`→leaf/orchestrator; `MAX_DEPTH=1` + `max_spawn_depth`; background child contract; **25** `*delegat*` tests on D — no missing Windows slice invented |

### Thin → fuller notes

- FI-CLI / TUI / CRON / DELEGATION: classify-only → **evidence rows** (counts, owners, CARRY cross-links). Still not a full U public-surface census of every opt-in plugin.
- Next inventory deepening (docs-only unless a contract gap appears): FI-SKILL / FI-PLUGIN / FI-BROWSER / FI-UPDATE packaging; mechanical H..U backlog remains `UNRES-FULL-H-U-CLASSIFICATION`.
- Executable code slice: **none invented this phase** — highest-value ready work was CARRY-RECHECK verification.

## CARRY-RECHECK (2026-09-13 evening)

Do not double-implement. Existing CARRY PORT items re-verified on HEAD `c11161a68f` vs frozen U symbol presence:

| CARRY id | Result | Tests |
|---|---|---|
| tui-gateway-ws-send-deadline | KEEP / ALREADY | pytest batch A (incl. `tests/tui_gateway/test_ws_send_timeout.py`) |
| cron-fire-claim-dead-owner-reap | KEEP / ALREADY | `test_claim_job_for_fire.py`, `test_dead_owner_claim_reclaim.py` |
| relay-provision-secret-issued-f004 | KEEP / ALREADY | `tests/gateway/relay/test_provision_secret_optional.py` |
| dashboard-auth-native-provider-chooser | KEEP / ALREADY | `tests/hermes_cli/test_dashboard_auth_native_flow.py` |
| desktop-oauth-sign-in-again | KEEP / ALREADY | py error-surface + vitest `error-surface` + `assistant-message` **5 passed** |
| auxiliary-origin-async-progress | KEEP / ALREADY | `test_aux_relay_progress_seam.py`, `test_aux_session_endpoint_affinity.py` |
| windows-conpty-pty-ownership | KEEP / ALREADY | `tests/hermes_cli/test_win_pty_bridge.py` 15p/1s |
| windows-system-ca-expiry-dedup | KEEP / ALREADY | vitest `windows-system-ca.test.ts` |
| desktop-queue-discovery-gate | KEEP / ALREADY | vitest composer-queue + background-queue-drain |
| desktop-clarify-submit-shortcut | KEEP / ALREADY | vitest `clarify-tool.test.tsx` |

Totals this phase: pytest **96 passed, 1 skipped** (A 35 + B 46 + win_pty 15/1s); vitest **75 passed** (5 files) + assistant-message **5 passed**. Probe: `tmp/probes/carry-recheck-2026-09-13.md` (gitignored).

`LOCAL_DEPLOYED` / soak: **NOT_RUN**.
