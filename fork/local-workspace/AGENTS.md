# Local Workspace — Agent Instructions

This is the **AI workstation harness** companion for root hygiene on
`zapabob/hermes-agent-windows`. The root [`AGENTS.md`](../../AGENTS.md) remains
the required entrypoint. This file only covers scratch classification and
CodeGraph-aware cleanup.

## CodeGraph before classifying owners

When a root file looks related to a real subsystem, do **not** invent a home by
filename alone. Confirm ownership with CodeGraph first:

```powershell
npx --yes @colbymchenry/codegraph query <symbol-or-filename-stem>
npx --yes @colbymchenry/codegraph impact <symbol>
```

If CodeGraph shows a packaging / entry / ledger owner, **leave it at root**.
If it is operator scratch with no callers, move it per the table below.

## If you see clutter at repo root

1. Check `.gitignore` / `.git/info/exclude` — the file is probably intentional local scratch.
2. Read [`README.md`](README.md) category table before moving.
3. **Never delete** operator scratch unless the operator explicitly asks.
4. **Never** `git add` logs, media, secrets, or `_docs/` unless the operator explicitly requests it.
5. Do **not** relocate official root entry modules (`run_agent.py`, `cli.py`,
   `model_tools.py`, `hermes_*.py`, `toolsets.py`, `FEATURES.yaml`, `CARRY.yaml`,
   `UPSTREAM_ADOPTION.yaml`, …) — they match packaging and product ledgers.

## Moving files (store, do not delete)

Prefer moving scratch into these dirs:

| Type | Destination |
|------|-------------|
| Generated media | `output/media/` |
| Reports / JSON snapshots | `output/reports/` |
| Generated logs | `output/logs/` |
| One-off probes / `_tmp_*` | `tmp/probes/` |
| Config / path dumps / nested local projects | `tmp/snapshots/` (incl. `windows-caches/`, `broken-paths/`, `nested-projects/`) |
| Tracked operator archives that must stay in git | `notes/archives/` |
| Tracked navigation maps | `docs/maps/` |
| Windows handoff / carry SOPs | `docs/windows/` |

Create the destination before moving. Verify source and destination stay inside
this repository. Preserve symlinks as symlinks. Never move a link target outside
the repository.

## Probes and tests

- Do not leave `test_*.py` at repo root — use `tests/` with `scripts/run_tests.sh`,
  or park throwaways under `tmp/probes/`.
- Do not execute an untrusted generated script merely because it is in-tree.

## Harness safety

Root-level scratch must **not** be referenced from `scripts/merge_tools/` policy
or overlay paths. Overlays target stable paths under `plugins/`, `tools/`,
`scripts/`.

## Identity files

`SOUL.md`, `brain/*`, and sovereign identity files may exist locally; `brain/*`
is `preserve_custom` in merge policy. Do not publish private identity content
upstream.

## Related

- Root layout: [`../../AGENTS.md`](../../AGENTS.md) §§16–17
- Fork decision tree: [`../AGENTS.md`](../AGENTS.md)
- Category examples: [`README.md`](README.md)
