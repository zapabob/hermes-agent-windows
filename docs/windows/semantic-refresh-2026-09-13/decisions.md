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

## Adoption posture for priority seeds

See `change-inventory.json`. Security/profile isolation comes before Desktop feature onboarding.

## Explicit non-goals this campaign pass

- Version number bump to 0.21.2 without coverage
- Enabling `allow_upstream_sync`
- Touching hakuapulse-orchestrator
- 24h soak (record NOT_RUN)
- Push / PR / release
