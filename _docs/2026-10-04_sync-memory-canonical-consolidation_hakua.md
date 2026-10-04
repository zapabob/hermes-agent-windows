# 2026-10-04 Canonical consolidation: sync_memory.py

- **Date**: 2026-10-04
- **Agent**: Hakua (Hermes Agent / isaku)
- **Branch**: `main`

## Question

Three divergent `memory_sync.py` copies existed, all flagged as carrying the same
`REPO_ROOT = parents[2]` defect. Decide the canonical one and make the layout secure
and convenient.

## pnpm: no action needed

The two pnpm files that had appeared as unstaged deletions were **restored** before
this task began and the worktree was already clean. Verified in HEAD and on disk, no
staged or unstaged delta. Separately confirmed that `package.json` carries a `pnpm`
overrides block **and** an npm-native `overrides` block containing the same
`tar: 7.5.22` Dependabot pin, so the security override survives regardless of which
package manager is used. Every workflow in `.github/workflows/` uses `npm`, not
`pnpm`. There was therefore nothing to decide and nothing to change.

## Canonical decision

**`scripts/standalone/sync_memory.py` is canonical.** The repo-root `sync_memory.py`
is now a compatibility shim that re-exports it.

### Why

1. **The only real code difference was in the root copy**, and it was the better
   version: it wrapped `main()` in `try/except` and printed
   `{"success": false, "error": ...}` as JSON. The cron wrapper
   `scripts/memory/sync_memory_cron.py` parses stdout with `json.loads`, so a
   traceback would surface as the misleading message `invalid JSON from
   sync_memory.py`. **That change was ported into the canonical copy.**

2. **`parents[2]` is a latent defect, not a live break.** At the repo root it
   resolves to `C:\Users\downl\Documents`. But the package is installed editable
   (`__editable__.hermes_agent-0.21.3.pth`), so the repository is on `sys.path`
   regardless. Verified by execution: both copies run correctly under the project
   venv **and** under system Python 3.12, from the repo root **and** from
   `C:\Windows`. Consolidating on `scripts/standalone/` removes the discrepancy by
   construction rather than by luck.

3. **The inbox copy was a different generation.** No argparse CLI (0
   `add_argument` calls), four hardcoded `C:\Users\downl\...` paths, no import of
   the Hermes modules — it could not pass the wrapper's CLI-surface detection. Its
   `SECRET_MARKERS` list is weaker than the canonical pipeline, which applies
   `redact_sensitive_text()` with three regex families plus a 32-char
   high-entropy pattern. Nothing was lost; it is retained as
   `doc/desktop-inbox/superseded/memory_sync.legacy-generic.py`.

## Two regressions I introduced and fixed

Recording these because both failed loudly and are exactly the traps a shim creates.

1. **`exec(compile(...), {"__name__": "__main__"})` broke importing.** The first
   shim executed the canonical module as `__main__`, so importing `sync_memory` ran
   the argparse CLI and consumed pytest's own argv. The test suite failed with
   `INTERNALERROR ... unrecognized arguments: tests/scripts/test_sync_memory.py`.
   Fixed by loading the canonical module with `importlib.util.module_from_spec` and
   running `main()` only under `if __name__ == "__main__"`.

2. **Re-exporting only the public surface broke monkeypatching.**
   `tests/scripts/test_sync_memory.py` patches `sync_memory._export_obsidian`, a
   private name. A shim that aliases only public names raises
   `AttributeError: 'module' object at sync_memory has no attribute
   '_export_obsidian'`. Fixed by re-exporting **every** module-level name via
   `dir()`, privates included.

Honest note on the second: that patch is currently **vestigial**, because the tests
call `run_sync(..., export_obsidian=False)` and `run_sync` guards the call with
`if export_obsidian:`. So the suite would have passed without it. The `AttributeError`
was nonetheless real and would have surfaced the moment that flag flipped — this is
future-proofing, not a live bug fix.

## Verification

| Check | Result |
|---|---|
| `tests/scripts/test_sync_memory.py` | **4 passed** |
| `tests/scripts/test_social_ebbinghaus_sync.py` | **4 passed** |
| Shim vs canonical, isolated `HERMES_HOME`, `--dry-run` | **byte-identical JSON** |
| Shim import has no side effects | verified |
| CLI `--help` via shim | identical to direct |
| Error path emits JSON, not a traceback | verified |

## Residual risk

- **`scripts/memory/sync_memory_cron.py` in the repo is BEHIND the deployed
  wrapper** at `~/.hermes/scripts/sync_memory_cron.py`. The deployed copy has
  `_resolve_sync_script()` and passes `--max-x-events 0`; the repo copy has neither.
  `--max-x-events 0` was traced and is safe — `_x_candidates()` returns `[]` when
  `max_events <= 0`, so X import is disabled as intended. The deployed copy should
  still be synced back into the repository, per
  `cron-runtime-reliability` -> `references/sync-allowlist-workflow.md`.
- `sync_check.py` remains in the desktop inbox; the repo references the name but has
  no tracked counterpart.
