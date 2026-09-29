# Stop tracking generated scratch and ignore root dumps

- Date: 2026-09-26 (JST)
- Agent: Cursor
- Branch: `chore/untrack-scratch-20260926` (from `origin/main` @ `ff3109158cc`, after PR #152)

## Overview

Removed two generated scratch files from the index (`git rm --cached`; both
remain on disk) and added `.gitignore` rules so the classified scratch folders
under `output/` and the root-level dumps moved out during the root tidy cannot
be re-added. Git history is unchanged.

## Background and requirements

- `AGENTS.md` §17 and `fork/local-workspace/` define `output/media/`,
  `output/reports/`, `output/logs/`, `tmp/probes/` and `tmp/snapshots/` as
  ignored scratch, with only each folder's `README.md` / `AGENTS.md` tracked.
- Two scratch artefacts were still tracked on `main`.
- The 52 root-level files moved into `output/reports/` and `tmp/probes/` during
  the earlier root tidy (scraped municipal HTML, JSON dumps, probe scripts,
  `nul`, `jsonl`, a duplicated `SOPs/` directory) had no ignore rules at root.

## Candidate review

| Path | Decision | Reason |
|------|----------|--------|
| `output/logs/log.txt` | untrack | Generated log; no code, test, CI or docs reference. |
| `output/media/sqlite_leak_fix.png` | untrack | Generated screenshot; no code, test, CI or docs reference. |
| `output/*/README.md`, `output/*/AGENTS.md` | keep | Folder policy files, tracked by design. |
| `tmp/probes/*`, `tmp/snapshots/*` (README/AGENTS only) | keep | Folder policy files, tracked by design. |
| Root-level tracked files | keep | All are entry modules, packaging, ledgers or dotfile config. |
| `scripts/**/*probe*.py`, `tools/*probe*.py`, `apps/desktop/**/probe*` | keep | Source code, imported or run by tooling. |
| `evals/**/*.jsonl`, `training/dpo_seed.jsonl`, `datagen-config-examples/*.jsonl` | keep | Eval results, seed data and examples, not scratch. |
| `_docs/**`, `notes/archives/**`, `docs/**`, `website/**` | keep | Tracked by policy or published. |

`UPSTREAM_ADOPTION.yaml` (`downstream_delta_paths`) lists both untracked paths,
but that block is a point-in-time snapshot (`captured_at: 2026-09-05`) emitted
by `scripts/upstream/snapshot_sync.py`; nothing validates that the paths still
exist, so the ledger was left untouched.

## Implementation details

- `.gitignore`:
  - `/output/{logs,media,reports}/*` with `!` negations for each folder's
    `README.md` and `AGENTS.md`.
  - `!/output/logs/` before narrowing, because the generic unanchored `logs/`
    rule would otherwise exclude the whole directory and defeat the
    negations. As a side effect, `output/logs/README.md` and `AGENTS.md` are no
    longer ignored-but-tracked.
  - Root-anchored patterns for the moved dumps: `/hachioji*.html`, `/hino*.html`,
    `/h_*.html`, `/a.json`, `/h.json`, `/alerts.json`, `/quake.json`,
    `/tsunami.json`, `/sync_report_*.json`, `/sync_report_*.md`, `/_disc*.py`,
    the named probe scripts, `/jsonl`, `/.c`, `/.hermes_tmp/`, `/.venv312/`,
    `/%SystemDrive%/`, `/SOPs/`, `/sillytavern_py/`. `/nul`, `/output.json`
    and `/prs.json` were already covered.
- No broad `*.json` / `*.html` patterns were added.
- `tmp/` is already ignored by the existing unanchored `tmp/` rule; left as is.

## Commands executed

```powershell
git fetch origin
git worktree add -b chore/untrack-scratch-20260926 <worktree> origin/main
git rm --cached output/logs/log.txt output/media/sqlite_leak_fix.png
git ls-files -ci --exclude-per-directory=.gitignore   # before/after comparison
git check-ignore -v --no-index <probe paths>          # in a throwaway repo with only .gitignore
python -m pytest -q tests/test_project_metadata.py tests/downstream/test_repository_identity.py `
  tests/hermes_cli/test_update_zip_fallback_guards.py tests/cli/test_worktree.py `
  tests/upstream/test_snapshot_sync.py
```

## Tests and verification

- Ignore verification was run in a throwaway repository containing only the new
  `.gitignore`, because the shared `.git/info/exclude` on this workstation
  ignores `output/` locally and would mask the result.
  - Ignored: both untracked files, `output/reports/x.json`, all root dump names.
  - Not ignored: every `output/*/README.md` / `AGENTS.md`, `apps/h.json`,
    `docs/a.json`, `website/h_x.html`, `package.json`, `sync_memory.py`.
- Tracked files ignored by `.gitignore`: 164 before, 161 after; newly ignored
  tracked files: 0.
- Both untracked files confirmed present on disk after the index removal.
- pytest: 102 passed, 1 skipped.

## Residual risk

- `.gitignore` is not honoured retroactively; other clones keep the two files
  until they pull, at which point git deletes them from those working trees
  (they were generated scratch, so no data loss is expected).
- Pre-existing tracked files that `.gitignore` still ignores (e.g. `_docs/*`
  force-adds, `brain/AGENT.md`) are unchanged and out of scope.

## Next recommended actions

- Consider anchoring the generic `tmp/` and `logs/` rules in a separate change
  so folder policy files are not ignored-but-tracked.
