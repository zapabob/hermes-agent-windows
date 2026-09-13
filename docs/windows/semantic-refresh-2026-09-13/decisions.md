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
| Inode-replacement generation retire/drain | registry generations | Deferred 003b (Windows value; not POSIX-only) | DEFER_WITH_BLOCKER → next slice |
| POSIX fd-close drops advisory lock fault injection | U tests | **SKIP per-mechanism** (Windows locks differ) | SKIP_WITH_REASON |

**Must not:** invent a second DB lifecycle authority beside SessionDB; wholesale skip DB safety because registry filename is absent.

## SR-20260913-004f

**ALREADY_EQUIVALENT** on main (`7f8a608445`, `tools/mcp_tool_scope.py`). Do not re-implement.

## SR-20260913-007 (reopened)

**Prior:** DEFER_WITH_BLOCKER (onboarding cards).  
**Revised split:**

- Upstream “card look” / promotional onboarding chrome → SKIP_WITH_REASON (keep Windows UX).
- Useful setup / provider select / auth recovery / reach-conversation after update → evaluate **REIMPLEMENT_NATIVE** into existing Desktop Settings / gateway boot overlays (not a second onboarding framework). Slice plan after 003a.

## Explicit non-goals this campaign pass

- Enabling `allow_upstream_sync`
- Touching hakuapulse-orchestrator / MoA / HOLD / model swap
- 24h soak (record NOT_RUN until real time elapsed)
- Force push / protection bypass / UAC weaken
- Bulk port of U `hermes_state_*.py` module decomposition
