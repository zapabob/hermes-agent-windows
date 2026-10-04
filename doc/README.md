# doc/

Operator scratch, generated data, and run output for this workstation.

**This folder is the documented destination for anything that is not part of
the product surface.** `AGENTS.md` §17 (Root layout policy) is the normative
rule; this README is the map.

## Why `doc/` exists

The repository root is deliberately kept narrow — entry modules, packaging, and
product ledgers only. Everything else has a classified home:

| Folder | Holds | Tracked? |
|--------|-------|----------|
| `doc/scripts/` | Ad-hoc Python / JS / awk operator scripts | README + AGENTS only |
| `doc/scripts/db-inspect/` | Throwaway state-DB inspection helpers | README + AGENTS only |
| `doc/scripts/osint/` | OSINT scraping / parsing scratch | README + AGENTS only |
| `doc/scripts/jma/` | JMA earthquake feed parsing scratch | README + AGENTS only |
| `doc/scripts/sync/` | sync_memory wrappers, dependabot auto-merge | README + AGENTS only |
| `doc/json/` | Bulk JSON / JSONL datasets and result files | README + AGENTS only |
| `doc/logs/` | Captured `*.log` and `*.txt` run output | README + AGENTS only |
| `doc/reports/` | Generated Markdown reports | README + AGENTS only |
| `doc/archive/` | Operator artifacts worth version-controlling | contents tracked |
| `doc/desktop-inbox/` | Files relocated from the Windows Desktop, awaiting review | policy files only |

`README.md` and `AGENTS.md` in each folder are **force-included** in
`.gitignore` (`!` negation), so every folder is self-describing in a fresh clone
while its contents stay out of history.

## Read path

1. `AGENTS.md` §17 — the policy (root layout, what may never move).
2. This file — the map of what lives where.
3. `doc/<class>/AGENTS.md` — the rules for that class, written before anything
   lands there.
4. `doc/desktop-inbox/DIVERGENCE.md` — Desktop files that already have a repo
   counterpart; read before promoting anything.

## Related (do not duplicate into `doc/`)

- `output/` — media, logs, reports (already git-ignored, README/AGENTS tracked).
- `tmp/probes/` — throwaway experiments.
- `_docs/` — dated implementation audit records (MILSPEC requirement).
- `notes/archives/` — tracked operator archives.
- `docs/` — upstream product documentation. **Not** an operator scratch sink.
