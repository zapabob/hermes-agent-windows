# CH02 ID crosswalk and F01 entry receipt (read-only)

- captured_local: 2026-09-25T03:50+09:00
- tree: feature worktree on `df14ba8c` + LM01 fix (uncommitted at capture time)
- mode: read-only trace. No product change for F01 in this unit.

## CH02 — F00 crosswalk (definitions from local ledger only)

| Packet | Family / RV | Evidence (ledger) | State |
|---|---|---|---|
| LM00 | F00 / RV01 | test commit `b07bef422ef96919cd7d5814171c3455040a8197`; node `test_successful_legacy_walk_missing_sha_refuses_output` | reuse |
| LM01 | F00 / RV02 (9/24 freshness) | `family_receipts.py`; see `TASK_CHECKPOINT_LM01.md` | fixed on feature branch |
| LM02 | F00 / RV03 | test commit `17e684bb281bc5c9e38d136209ee3f41ec3a2ed4`; nodes `test_generate_closes_sqlite_and_removes_temp_dirs_on_{success,exception}` | reuse |

- 9/25 RV02 (unborn repository HEAD, `INTEGRATION_HEAD_MISMATCH` vs `INTEGRATION_HEAD_UNKNOWN`) is a different check from 9/24 RV02 (source freshness). Not counted as the same PASS.
- Preserved, untouched: `%LOCALAPPDATA%\Temp\workstation-inventory-db-fzws1t5e`, `...-gmoefmwv`.
- Inventory 16 passes stay bound to `cdffa3d7…`.

## F01 — approval journal / caller boundary (CodeGraph 1.6.0, Node 22.23.2)

Authority: `tools/approval.py` (`retirement-map.json`: remains the Hermes human decision authority).

Callers:
- `downstream/control_mcp/coordinator.py` — `request_control_consent`, `cancel_control_consent`; `_await_decision` → `consume_control_verdict`.
- `downstream/control_mcp/journal.py` — `HostControlJournal._binding` / `approval_binding` / `approve` → `ControlApprovalBinding`, `consume_control_verdict` (function-local imports).
- Desktop mirror: `apps/desktop/src/store/prompts.ts` (`ControlApprovalBinding`, `hasValidControlApprovalBinding`), `components/assistant-ui/tool/approval.tsx`.
- Existing tests: `tests/control_mcp/test_control_approval.py` (forged dataclass copy, invalid resource/grant revision, legacy FIFO cannot approve strict entry, missing notify does not auto-approve, deadline).

RV04 proposed node `tests/control_mcp/test_review_approval_binding.py::test_denies_forged_consent_and_foreign_resource`: `PROPOSED_NOT_COLLECTED` (file absent).

### RV04 binding map vs `ControlApprovalBinding`

| RV04 term | Existing field | Gap |
|---|---|---|
| principal | `subject` | — |
| client | `client_registration` | — |
| profile | `profile_id` | — |
| resource | `resource` | — |
| args / source | `intent_digest` | derivation of digest inputs not asserted by a test |
| policy | `grant_revision` | policy revision vs grant revision equivalence undefined |
| epoch | none | **owner epoch absent** |
| nonce | `operation_id` / `request_id` | once-consume under race is LM04 / RV05 |

## Gate

`LM03_BLOCKED_ON_INTEGRATOR_DEFINITION`: per ledger, the Integrator must define route/provider revision, owner epoch, and restart/replay semantics before the LM03 RED test is written. AUTH scope; Cursor does not invent these.
