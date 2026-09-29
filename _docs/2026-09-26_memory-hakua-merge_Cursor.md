# 2026-09-26 memory-hakua-merge (Cursor)

## Overview

Port the uncommitted Ebbinghaus / hakua-memory / lm-twitterer memory work from
the operator checkout onto a clean branch cut from `origin/main`
(`3beeca89e8e`), and land it through a pull request.

- Branch: `feat/ebbinghaus-hakua-memory-20260926`
- Worktree: `C:\Users\downl\Documents\New project\hermes-memory-hakua-20260926`
- Source checkout was treated as read-only (no reset/stash/checkout there).

## Background and requirements

1. hakua-memory 0.3.5 as an optional extra (`hakua-memory`) plus the
   `memory.hakua` lazy-install entry; kept out of `[all]`.
2. Ebbinghaus plugin: `store_backend: builtin|hakua` with a schema guard
   (`schema_identity.py`), an opt-in LLM judge (`judge.py`) exposed as
   `hermes ebbinghaus judge|findings` (`cli.py`), and exclusion of cron/flush
   sessions from turn auto-encoding.
3. lm-twitterer: memory write-back of generated posts gated by
   `plugins.entries.lm-twitterer.memory_writeback` (config.yaml, default off).

## Decisions

- `plugins/lm-twitterer` and `plugins/memory/ebbinghaus` are tracked on
  `origin/main`; the backslash-path `??` rows in the source status snapshot were
  duplicates of the tracked `M` rows, not separate files.
- lm-twitterer `core.py` ported version is hash-identical to
  `~/.hermes/plugins/lm-twitterer/core.py`
  (`EC5142E0...FDD3ABE2`).
- Every working-tree hunk in `pyproject.toml`, `tools/lazy_deps.py` and
  `tests/test_project_metadata.py` was hakua-related; none were dropped.
  The source checkout's local `main` diverges from `origin/main` (openai,
  anthropic, google-auth, nemo-relay, firecrawl-anydoc pins), so only the
  working-tree diff against source `HEAD` was applied, never whole files.
- `uv.lock` was regenerated in the worktree, not copied. uv 0.9.28 (CI pin)
  re-resolution rewrote unrelated lines (`exclude-newer` placeholder and numpy /
  vercel markers) because main's lock was written by a newer uv. The lock was
  therefore produced with uv 0.11.29, giving a minimal diff (hakua package,
  extra, requires-dist, provides-extras), and verified with
  `uv 0.9.28 lock --check` (exit 0) so the CI gate agrees.
- Existing `test_dry_run_post_is_written_to_ebbinghaus_memory_db` assumed
  write-back by default; it now opts in explicitly, matching the new contract.
- `__init__.py` was split across three commits (backend, judge config keys,
  cron exclusion); intermediate commits were test-run individually.

## Changed files

- `pyproject.toml`, `tools/lazy_deps.py`, `tests/test_project_metadata.py`, `uv.lock`
- `plugins/memory/ebbinghaus/__init__.py`, `schema_identity.py`, `judge.py`, `cli.py`
- `plugins/lm-twitterer/core.py`
- `tests/plugins/test_ebbinghaus_hakua_backend.py`,
  `test_ebbinghaus_schema_identity.py`, `test_ebbinghaus_judge.py`,
  `test_ebbinghaus_cron_auto_encode.py`, `test_lm_twitterer_memory_writeback.py`,
  `test_lm_twitterer_plugin.py` (opt-in adjustment)

## Commands

```powershell
git fetch origin
git worktree add -b feat/ebbinghaus-hakua-memory-20260926 <worktree> origin/main
git diff --binary --output=<patch> -- <5 modified files>   # in source checkout
git apply --3way <patch>                                   # in worktree
uv lock                                                    # uv 0.11.29
uvx --from uv==0.9.28 uv lock --check
uv sync --frozen --extra dev
uvx ruff@0.16.2 check <changed files>
.venv\Scripts\python.exe -m pytest <tests> -q
```

## Verification

- `ruff check` on all changed Python files: pass. (`ruff format --check` is not
  a CI gate and already differs on untouched main files.)
- No `print(` in changed files; no BOM.
- pytest (ebbinghaus x7, lm-twitterer x2, project metadata, plugin CLI
  registration, ebbinghaus skill, lazy_deps x3, memory_provider tests):
  315 passed, 5 skipped.
- Intermediate commits: backend commit 39 passed / 2 skipped; judge commit
  14 passed / 1 skipped.
- `uv 0.9.28 lock --check`: exit 0.
- CI and merge evidence: recorded on the pull request.

## Residual risk

- The hakua backend test mocks/guards the package; a real hakua-memory schema
  drift in a future release is caught at runtime by the schema guard (falls
  back to builtin), not by CI.
- `hermes ebbinghaus judge --run` sends memory text to the configured model;
  it is gated by `judge_enabled` (default false).

## Next actions

- Enable `store_backend: hakua` on one profile and confirm the log line
  `Ebbinghaus memory store backend: hakua-memory`.
- Run `hermes ebbinghaus judge --estimate` before any `--run`.
