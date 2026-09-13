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

## SR-20260913-003 (2026-09-13)

**Decision: SKIP_WITH_REASON** (was pending COMPOSE).

U seeds `876e444e` / `6806a380` assume `hermes_state_registry.acquire()` already owns the process-wide writer boundary. D1 has `hermes_state_common.py` and `SessionDB` but **no** `hermes_state_registry.py`; `git merge-base --is-ancestor db339f0051 HEAD` is false. Gateway sharing is a runner-local `RecoverableHandleCache`, not the U registry. CLI + Goals still mint bare `SessionDB()`.

Composing only the seed call-site diffs would require inventing a parallel owner (forbidden) or bulk-porting `#90837` / `db339f0051` outside seed scope (forbidden). Re-open when the registry owner lands.

## Explicit non-goals this campaign pass

- Version number bump to 0.21.2 without coverage
- Enabling `allow_upstream_sync`
- Touching hakuapulse-orchestrator
- 24h soak (record NOT_RUN)
- Push / PR / release
