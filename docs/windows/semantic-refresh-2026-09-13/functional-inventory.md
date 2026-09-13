# Functional inventory — semantic refresh 2026-09-13

REUSE H..U ledgers + U public surfaces. REIMPLEMENT_NATIVE in schema_notes.

Coverage (separate flags — none imply LOCAL_DEPLOYED/soak):

| Coverage | State |
|---|---|
| inventory | PARTIAL (SR seeds + selected FI families; U full public-surface census incomplete) |
| implementation | SR-001..005 + 003b + 006a done/classified; 007 useful subset pending |
| verification | Focused Windows pytest on landed slices; LOCAL_DEPLOYED=NOT_RUN; soak=NOT_RUN |

| ID | Decision | Method | Status |
|---|---|---|---|
| SR-001 | COMPOSE | REUSE_AND_EXTEND | PASS |
| SR-002 | SKIP | NONE | POSIX-only |
| SR-003 | ADOPT | REIMPLEMENT_NATIVE | 003a+003b PASS_FOCUSED |
| SR-004f | ALREADY_EQUIVALENT | KEEP | on main |
| SR-005 | COMPOSE | REUSE_AND_EXTEND | PASS |
| SR-006 | PORT | NATIVE_PORT | 006a PASS; 006b ALREADY |
| SR-007 | ADOPT_PARTIAL | REIMPLEMENT_NATIVE/SKIP cards | CLASSIFIED → next 007a |
| SR-008 | SKIP | NONE | Linux-only |
| FI-CLI | inventory | — | PARTIAL |
| FI-TOOL | inventory | — | PARTIAL (MCP breaker family updated) |
| FI-MCP | inventory | — | PARTIAL |
| FI-DESKTOP-UX | inventory | — | PARTIAL (007 split recorded) |
| FI-RUNTIME | inventory | — | PARTIAL |

Next: SR-007a share_auth / auth-recovery probe → useful REIMPLEMENT only; continue FI-* census; no LOCAL_DEPLOYED claim without rebuild.
