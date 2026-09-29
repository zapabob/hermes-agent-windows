# 2026-09-29 main CI repair — GPT-5.6 Sol

## Scope

Repair the failing GitHub Actions checks on `main` after the 0.21.5 README
alignment, without touching the dirty canonical checkout.

Observed failing exact head before this repair:
`425e3762ffb05b0f7189ae1f83b92031f410711f`.

## Failures observed

`Windows Workstation Tier-1 CI` failed in two places:

1. `Downstream policy / Validate carry-surface metrics` reported that the
   generated carry metrics were stale.
2. `Windows native Python / Cross-platform and native Windows contracts` failed
   because `tests/tools/test_windows_native_support.py` still required an older
   README sentence about the Windows installer. The rewritten README preserves
   the same contract with updated wording.

The same Tier-1 run showed the other Windows jobs green, including Desktop,
watchdog Go, regression, security/lockfiles, and upstream API compatibility.

## Repair

- Updated the Windows README contract test to assert the current stable contract:
  the downstream release pipeline can produce an NSIS installer and portable ZIP,
  and the official upstream installer targets the upstream distribution.
- Regenerated `_docs/carry-surface-20260826.json` and `.md` from the current tree.
- Preserved the existing frozen upstream snapshot and policy boundaries.

## Local validation before publication

- `scripts/downstream/validate_policy.py`: passed.
- `scripts/downstream/carry_metrics.py --check`: current.
- CI/carry/README focused tests: 16 passed.
- Tier-1-equivalent Windows contract suite: 261 passed and 9 skipped; one local
  real-ClamAV test failed on this workstation. The corresponding GitHub runner
  test had already passed on the failing exact head, so no security test or
  production behavior was weakened to accommodate the local ClamAV state.
- `git diff --check`: passed.

## Qualification boundary

This record describes the repair candidate before the replacement `main` SHA is
published and its GitHub Actions workflows reach terminal state. Exact-SHA cloud
CI must be checked again after push before calling `main` all-green.
