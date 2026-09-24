# TASK_CHECKPOINT — LM01 source freshness (F00 / RV02 freshness)

- captured_local: 2026-09-25T03:42+09:00
- writer: Cursor (single writer, feature worktree). Shared files: Integrator serialised.
- worktree: `hermes-cursor-workstation-20260925` / branch `feat/cursor-workstation-continue-20260925`
- base: `df14ba8c135a905c76010efa4327427ccd7dcebf` (actual tip; reported `fd1f5339…` is its parent — HEAD_ADVANCED_OR_DIFFERS, legitimate progress, no reset)
- source checkout: untouched. WIP preserved: `M docs/control-mcp/IMPLEMENTATION_LOG.md` (staged), ` M docs/windows/workstation-20260924/LUNA_MAX_EXECUTION_PLAN.md`, plus 20 untracked `SOPs/*.md` (appeared during session, not created by Cursor). See `local-preflight.json`.
- push: none. main: not edited.

## Status

`LM01_FIXED_ON_FEATURE` (not `LM01_VERIFIED_AT=df14ba8c`): the df14ba8c module was RED on a supported interpreter.

| Item | Result |
|---|---|
| module | `docs/windows/workstation-20260924/tools/family_receipts.py` |
| test | `docs/windows/workstation-20260924/tests/test_family_receipts.py` |
| df14ba8c on CPython 3.11.11 (source venv) | 7 passed, 1 skipped |
| df14ba8c on CPython 3.12.10 (supported, `>=3.11,<3.14`) | **4 failed**, 3 passed, 1 skipped — `SOURCE_CHANGED_DURING_CAPTURE` |
| root cause | Windows 3.12: path `lstat().st_ctime_ns` = creation time, `fstat().st_ctime_ns` = metadata change time; identity mismatch after any post-creation write. `st_birthtime_ns` agrees (Python 3.12 docs: `st_ctime` deprecated on Windows, `st_birthtime` added). |
| fix | `_stable_time_ns`: on `nt` use `st_birthtime_ns` when present, else `st_ctime_ns`; POSIX unchanged |
| tests added | same-status worktree movement; same-status index movement; `_stable_time_ns` with platform passed as data |
| after fix 3.11 / 3.12 | 10 passed, 1 skipped / 10 passed, 1 skipped |
| symlink test | SKIPPED — symlink creation not permitted: `BLOCKED_NATIVE_PATH` (junction test passes natively) |

## SPEC_RED vs mutant kill (kept separate)

- SPEC_RED (handoff "expected False, got True"): weakened in-test validator; not a module defect.
- Real-module mutants (isolated copies, verbatim test, no mocks):
  - before test additions (3.11): M06 worktree-bytes-dropped and M07 index-dropped **SURVIVED**; others killed. RV02 required mutant M02 (fingerprint compare removed) KILLED.
  - after (3.12): 13/13 KILLED (M13 = fix reverted to `st_ctime_ns`).
  - after (3.11): 12/13 KILLED; M13 SURVIVED (defect not observable on 3.11 — interpreter-bound). The later pure-function test covers branch removal on any host.

## Gates

- Ruff 0.15.10: pass. `git diff --check`: clean.
- CodeGraph (Node 22.23.2, 1.6.0): before — `validate_family_receipt` impact = itself only (no product caller). After sync — `_stable_time_ns` impact confined to `family_receipts.py`.
- Independent review (separate subagent, read-only): APPROVE_WITH_NITS; no critical/important findings. Nits applied: helper placement, docs-referenced comment, direct pure-function test of the Windows branch (runs on every host).
- Inventory 16 passes remain bound to `cdffa3d7…`; not a final-HEAD gate. 9/24 RV02 (freshness) ≠ 9/25 RV02 (unborn HEAD).

## Findings handed to other owners (not changed here)

- T16 same bug class: `downstream/security/{updates,service,vault,engines,clamav_definitions}.py` compare path-stat `st_ctime_ns` with fstat identity → likely false "changed" on 3.12 Windows. Owner: T16 / Integrator.
- Junction test: `mklink` output decoded as UTF-8 raises a thread warning (cp932). Harness-only.

## Next minimal unit

CH02 ID crosswalk (reuse LM00/LM02; keep both SQLite temps) → F01 approval journal/caller (`tools/approval.py`); LM03 definitions only from the local ledger.
