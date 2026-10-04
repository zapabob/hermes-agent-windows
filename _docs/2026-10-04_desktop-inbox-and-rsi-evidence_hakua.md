# 2026-10-04 Desktop inbox, RSI evidence commit, and weight-blob guard

- **Date**: 2026-10-04
- **Agent**: Hakua (Hermes Agent / isaku)
- **Branch**: `main`
- **Scope**: root surface (continued), Desktop-to-repo sync, RSI evidence

## Problem

Three separate drifts had accumulated since the first tidy commit:

1. The root surface had re-accumulated scratch (3 JSON files).
2. `rsi/` had grown to 174 untracked files, including a **988 MB**
   `model.safetensors` and four 4.3 MB adapters that **no gitignore rule
   covered** — a single `git add` would have written ~1 GB into history, and a
   blob, once written, is permanent.
3. The Windows Desktop held 25 loose Hermes-related scripts and data files. Three
   divergent `memory_sync.py` copies existed as a direct result of that drift.

## Decisions taken (operator-confirmed)

- **rsi/**: commit evidence, datasets, protocols and review documents. Weight
  blobs stay ignored; the artifacts remain on disk either way.
- **Desktop**: move the loose files into the repo (not copy), leaving the
  Desktop clear of them.

## What was done

### 1. Weight-blob guard added to `.gitignore`

```text
/rsi/experiments/**/base_checkpoint/
/rsi/experiments/**/runs/**/adapter/
/rsi/experiments/**/runs/**/adapter_initial/
/rsi/experiments/**/adapter/
**/*.safetensors
**/*.gguf
**/*.bin
```

Evidence, manifests and receipts under `rsi/` remain tracked; only weights are
excluded. Untracked files over 1 MB went from **8 (1,010 MB)** to **0**.

### 2. `doc/desktop-inbox/` created

25 files moved from `C:\Users\downl\Desktop` — 21 scripts and 4 data files.
Before moving, each was checked against `~/.hermes/cron/jobs.json`, the Windows
scheduled-task list, and `git grep`. **No live references were found**, so moving
was safe. The inbox carries `README.md`, `AGENTS.md` and `DIVERGENCE.md`.

`DIVERGENCE.md` records the three files that already have repo counterparts,
with sha256 prefixes for both sides:

| Inbox | Repo counterpart | Finding |
|---|---|---|
| `memory_sync.py` (sha 27516810310d) | `sync_memory.py` root (sha 9826d31ca171) | Diverge; a third copy exists under `scripts/standalone/` |
| `social_sync_cron.py` (sha bfc6f5cb78f2) | `scripts/memory/sync_memory_cron.py` (sha 6b7e927c0f9f) | Large divergence, 15,947 vs 2,564 bytes; inbox copy is the older implementation |
| `sync_check.py` (sha 82ac3f65cef8) | none tracked | Referenced by name in the repo but absent — investigate before deleting |

### 3. `.gitignore` ordering bug found and fixed

The first `doc/desktop-inbox/` block was inserted at line 290, *before* the
generic `/doc/*/*` rule at line 349. Because **git applies the last matching
pattern**, the generic rule won and swallowed even the policy `.md` files. The
block was moved after the generic rules. This is the same last-match-wins trap
that `output/logs/` already needs a re-include for, and it is now documented as
such in the SOP.

### 4. AGENTS.md sections 17.7 and 17.8 added

- **17.7 Desktop-to-repository sync SOP** — five steps: survey for live
  references (cron jobs, scheduled tasks, `git grep`), move never copy, record
  divergence never merge blind, promote deliberately, keep `.gitignore` ordering
  correct.
- **17.8 Periodic sync** — when to run the survey, including "before any
  `git add -A`", and the 2026-10-02 `sync_memory_cron.py` incident where a wrapper
  resolved a stale debug stub at the repo root instead of the real CLI under
  `scripts/standalone/`. Points at
  `cron-runtime-reliability` -> `references/sync-allowlist-workflow.md` for the
  repo-authoritative deployment pattern.

`doc/README.md` was updated with the `desktop-inbox` class and the divergence
read-path step.

### 5. Root scratch moved

`contradiction_result_20261004T180637Z.json`, `pr_meta.json` and
`unresolved_threads.json` moved into ignored `doc/json/` — they correctly stayed
unstaged.

## Verification

| Suite | Result |
|---|---|
| `tests/plugins/test_irodori_tts_plugin.py` | **48 passed, 45 subtests passed** |
| `tests/scripts/test_irodori_startup_windows_live.py` | included above |
| `rsi/revisions/.../test_compiler.py` | included above |

Commit safety checks: 167 files staged, **0** weight blobs, **0** files over
2 MB, `rsi/` staged total 1.83 MB, **0** pnpm entries, Desktop loose script/data
files 25 -> 0.

## Residual risk

- **The three divergent `memory_sync.py` copies are still unmerged.** The inbox
  copy is a root-level script and therefore carries the same
  `REPO_ROOT = parents[2]` defect that resolves to `C:\Users\downl\Documents`.
  Fixing it requires deciding which copy is canonical; that decision is not made
  here.
- **`social_sync_cron.py` in the inbox is a 15,947-byte implementation against a
  2,564-byte repo counterpart.** The size gap suggests the repo copy was reduced
  at some point. Review before treating either as authoritative.
- **The pnpm deletions remain unstaged**, as before.
