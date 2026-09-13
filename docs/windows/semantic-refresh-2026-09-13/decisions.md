# Decisions — windows-semantic-refresh-2026-09-13

## Freeze

| Role | Exact SHA |
|---|---|
| D0 | `7c697a8a658d4ceadb80276f37b90cd93d84d6a9` |
| U | `6dd091a89c33e6e4909a80f78343bb384deb5ca8` |
| R peeled | `939e45c91d751fadd94dcd1b873ac3cb44846213` (`v2026.9.11`) |
| H snapshot | `b51c055a12220f8c7c18660e8599365012e19532` |

Plan draft U (`205645ee…`) was **26 commits behind** live upstream at start; frozen once to live U.

## Implementation rules chosen

1. No merge/rebase/bulk cherry-pick of `upstream/main`.
2. First implementable security slice: **SR-20260913-001** COMPOSE into `tools/file_tools.py` (D0 owner), do not force U's `file_tools_write_guards.py` module split unless a later slice requires it.
3. Dirty main working tree (watchdog-go WIP) left untouched; all work in `.worktrees/semantic-refresh-d1`.
4. CodeGraph indexes on H: junctions after C: disk-full failure.
5. **SR-20260913-004b/c/d** COMPOSE into existing owners (`plugins/memory/*`, `agent/auxiliary_client.py`, `gateway/run.py` + `session.py::_profile_home_for_key`). Do not invent `gateway/run_agent_cache.py` or `tools/mcp_tool_scope.py` solely to match U layout.
6. Resume checkpoint was `a537893…`; continued from legitimate later HEAD `f5b3fcc…` (GPT Pro report) without reset.

## Adoption posture for priority seeds

See `change-inventory.json`. Security/profile isolation comes before Desktop feature onboarding.

## Implementation methods (addendum 2026-09-13)

Adoption decision and implementation method are **separate** fields.

| Method | Meaning |
|---|---|
| `KEEP` | No runtime change; equivalence verified |
| `REUSE_UPSTREAM` / `NATIVE_PORT` | Small reuse or OS-adapted port |
| `REUSE_AND_EXTEND` | Compose onto existing Windows owner |
| **`REIMPLEMENT_NATIVE`** | Extract observable contract from U; realize on existing Windows owner with **different** internal structure. Not a full rewrite. Prefer when PORT of U layout would invent a second supervisor/DB/credential owner or force unused module splits |
| `NONE` | SKIP / DEFER — no implementation |

**Allowed under REIMPLEMENT_NATIVE:** helpers under the existing owner, typed boundaries, OS adapters, local extractions modules with clear responsibility.  
**Forbidden:** second supervisor, second credential SoT, competing DB lifecycle authority, speculative event buses / frameworks / future hooks “because U has them”.

Missing a same-named U registry/module is **not** alone grounds for SKIP.

## SR-20260913-003 (reopened 2026-09-13 — Feature Inventory addendum)

**Prior decision:** SKIP_WITH_REASON (registry-name absence).  
**Revised:** **ADOPT** via **`REIMPLEMENT_NATIVE`** on SessionDB / Goals / gateway opener — **not** a port of `hermes_state_registry.py`.

### Contract decomposition (mechanism ≠ family)

| Contract | U carrier | Downstream owner | Method |
|---|---|---|---|
| One writable handle per resolved `state.db` path per process (refcount) | `hermes_state_registry.acquire/release` | New helper `hermes_state_shared` under SessionDB family + Goals/gateway call sites | REIMPLEMENT_NATIVE (slice 003a) |
| `close()` on shared handle = release, not teardown | SessionDB `_shared_registry_owned` | SessionDB `_shared_owned` + shared helper | REIMPLEMENT_NATIVE (003a) |
| Profile A/B independent DBs | path key = resolved home/`state.db` | same | ALREADY via path key; tests required |
| Closed-handle reuse raises typed/clear error | SessionDB | Existing `RuntimeError("SessionDB connection is closed")` | ALREADY_EQUIVALENT |
| Backup / FTS repair / WAL PASSIVE close | SessionDB | Existing `hermes_state.py` | ALREADY_EQUIVALENT (keep) |
| Gateway open heal / backoff | RecoverableHandleCache | Keep as caller-side recovery **on top of** shared acquire | COMPOSE (opener uses shared acquire) |
| Inode-replacement generation retire/drain | registry generations | `hermes_state_shared` identity + `_retired` | REIMPLEMENT_NATIVE (003b DONE) |
| POSIX fd-close drops advisory lock fault injection | U tests | **SKIP per-mechanism** (Windows locks differ) | SKIP_WITH_REASON |

**Must not:** invent a second DB lifecycle authority beside SessionDB; wholesale skip DB safety because registry filename is absent.

### SR-003b receipt (2026-09-13)

- Contract: known `(st_dev, st_ino)` change retires live generation; holders keep connection; unknown/`st_ino=0` never false-retires.
- Tests: `py -3 -m pytest tests/hermes_state/test_shared_session_db_native.py -q` → **7 passed**
- Method remains REIMPLEMENT_NATIVE (not a port of U registry tables).

## SR-20260913-004f

**ALREADY_EQUIVALENT** on main (`7f8a608445`, `tools/mcp_tool_scope.py`). Do not re-implement.

## SR-20260913-006 (2026-09-13)

**006a PORT (NATIVE_PORT)** into monolithic `tools/mcp_tool.py`: `_server_errors_all_application` + open-breaker rejected wording; JSON/`isError` tool-error path bumps with `application=True`.  
**006b ALREADY_EQUIVALENT**: SSE `_ever_connected` fallback guards already on D — do not re-port `a565e2`.

Focused: `test_breaker_opened_by_tool_errors_says_rejected_not_unreachable` + full `test_mcp_circuit_breaker.py` → **8 passed**.

## SR-20260913-007 (reopened → 007a DONE 2026-09-13)

**Prior:** DEFER_WITH_BLOCKER (onboarding cards).  
**Revised split:**

- Upstream “card look” / promotional onboarding chrome / guided film → SKIP_WITH_REASON (keep Windows UX).
- **007a DONE (REIMPLEMENT_NATIVE / NATIVE_PORT):**
  - `tools/managed_tool_gateway._read_nous_provider_state` → `get_provider_auth_state("nous")` so share_auth profiles see root identity (no second auth SoT).
  - `agent/conversation_loop.emit_provider_retry_wait_notice` names provider backoff on the live status line (U `turn_recovery` contract; D has no `turn_recovery.py`).
- **007b DEFER:** credential-miss → existing Settings/onboarding without card chrome.

Tests: managed_tool_gateway suite **32 passed** + `test_provider_retry_wait_notice`.  
`LOCAL_DEPLOYED` / soak: **NOT_RUN**.

## Explicit non-goals this campaign pass

- Enabling `allow_upstream_sync`
- Touching hakuapulse-orchestrator / MoA / HOLD / model swap
- 24h soak (record NOT_RUN until real time elapsed)
- Force push / protection bypass / UAC weaken
- Bulk port of U `hermes_state_*.py` module decomposition
