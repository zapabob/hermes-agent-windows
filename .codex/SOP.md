# Downstream integration SOP

## Scope

This SOP governs Hermes Agent Windows Workstation Edition. Work occurs in an
isolated integration worktree. User changes in the primary checkout are never
reset, cleaned, stashed, or incorporated implicitly.

## Frozen input

The original campaign retains upstream input
`b51c055a12220f8c7c18660e8599365012e19532` and previous frozen BASE
`5a8e8a6b87487c0e0785cd9eb561cc6a96c64f5e`. Its input is unchanged.
Run `scripts/upstream/snapshot_sync.py --upstream-sha <sha>
--downstream-ref <ref> --base-sha <previous-upstream-sha> --report-only` when
that campaign's semantic three-way review calls for it. The helper must not
resolve a moving branch.

Select later campaigns by an explicit campaign ID and its own frozen record:
`windows-workstation-20260924` uses
`docs/windows/workstation-20260924/freeze.json`; the user-authorized
`windows-semantic-refresh-20260926` uses
`docs/windows/semantic-refresh-20260926/freeze.json`. The latter records D0,
the historical B/R0/R1/U0 inputs, and the new R2/U1 window. It does not amend
the earlier ceiling or authorize an upstream merge. Without an explicit
campaign ID, do not substitute any later upstream commit for the original
input. Every integration receipt must name the selected campaign and exact
commit IDs before semantic work begins.

## Integration procedure

Read `.codex/UPSTREAM_POLICY.md`, `.codex/FORK_INVARIANTS.md`,
`.codex/WINDOWS_PLATFORM_CONTRACT.md`, `FEATURES.yaml`, and `CARRY.yaml`.
Classify each upstream commit in `UPSTREAM_ADOPTION.yaml`. Prefer official
public contracts, compose proven downstream properties through
`downstream/compat/hermes`, and stop when a feature or security invariant
cannot be determined.

Keep fork-owned behavior under `downstream/`, existing plugin entrypoints, or
`scripts/windows/`. Do not create another session, approval, profile, gateway,
model-catalogue, or tool-registry authority.

## Verification

Run gates in the directive order: syntax/import sanity; policy validation;
upstream API contracts; downstream feature contracts; Windows runtime tests;
Python lint; TypeScript typecheck/lint; Desktop tests; native Go watchdog tests;
Linux regressions; security and lockfile checks; native Windows CI; full
required GitHub CI. Record exact SHAs and distinguish local, CI, runtime, and
scheduled-task evidence.

## Publication

Commit logical units and push the integration branch. Integrate into `main`
only after required exact-head checks pass. Rename the GitHub repository only
after final `main` is healthy, then update `origin` and rerun required CI under
the new repository identity.
