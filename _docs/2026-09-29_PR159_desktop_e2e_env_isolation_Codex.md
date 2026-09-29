# PR159 Desktop E2E environment isolation — Codex

Date: 2026-09-29
Repository: `zapabob/hermes-agent-windows`
Pull request: `#159`
Branch: `fix/desktop-multi-backend`

## Purpose

The Desktop Playwright harness previously inherited arbitrary `HERMES_DESKTOP_*`
variables from the developer or CI runner. In particular,
`HERMES_DESKTOP_CWD` can outrank the fixture's normal workspace fallback and
make a sandboxed E2E session operate on a real checkout. PR #159 isolates the
application environment before Electron is launched.

This is a test-harness change. It does not alter the Desktop application runtime
under `apps/desktop/electron/` or `apps/desktop/src/`.

## Implementation

- Added `apps/desktop/e2e/app-env.ts` as the Playwright-independent owner of
  `buildAppEnv()` and credential stripping.
- `buildAppEnv()` removes inherited `HERMES_DESKTOP_*` names case-insensitively
  before applying fixture-owned sandbox values.
- Case variants of explicitly owned fixture keys, including `HERMES_HOME`, are
  removed so Windows environment-name semantics cannot preserve a hostile
  duplicate.
- Explicit test overrides remain supported after inherited values are removed.
- `apps/desktop/e2e/fixtures.ts` re-exports `buildAppEnv()` so existing E2E specs
  keep the same import surface.
- Added `apps/desktop/e2e/app-env.unit.test.ts` with a hostile inherited
  environment, mixed-case variants, a foreign checkout path, a dev-server
  override, and a credential.

## Stack reconciliation

The original PR #159 head was `d88b2586572333a88056f25d388eb46d7b124ccd`.
N52 and N53 subsequently landed on `main`, so PR #159 was refreshed by merging
the then-current downstream `main` into the PR branch instead of replaying or
duplicating those families.

The stack-refresh merge commits are:

- `fc819eefd9891b58743983ed50e638baeafa3f69`
- `e7cabb157854c23c01df87aee9883d13020c3d26`

At the second refresh, downstream `main` was
`8d2c914b39923f54112adb0c394f8e03db49e754`. The only merge conflicts were the
generated carry-surface reports. They were regenerated from the combined tree
with `scripts/downstream/carry_metrics.py`; product and E2E source files had no
merge conflict.

## Verification before this record

On the combined N53 + PR #159 tree at `e7cabb157854c23c01df87aee9883d13020c3d26`:

- `npm --prefix apps/desktop exec -- vitest run e2e/app-env.unit.test.ts`:
  1 file passed, 5 tests passed.
- `npm --prefix apps/desktop run typecheck`: passed.
- `uv run --no-sync python scripts/downstream/carry_metrics.py --check`:
  `Carry metrics are current.`
- `git diff --check`: passed.
- GitHub exact-head CI had no recorded failures when this document was written.
  The full Python test job was still running, so this record does not claim the
  complete CI gate was closed at that observation point.

Earlier Desktop E2E results produced with inherited `HERMES_DESKTOP_*` leakage
remain unsuitable as evidence for workspace isolation. Fresh E2E evidence must
use the corrected harness.

## Scope and remaining gates

PR #159 only closes the Desktop E2E inherited-environment isolation defect. It
does not certify Control MCP production writes, runtime restart, release, or the
remaining N07-A1/T06/T12 evidence. Those gates remain independent.

No primary-checkout reset, stash, clean, deletion, force push, production
restart, or frozen-upstream rewrite is part of this change.
