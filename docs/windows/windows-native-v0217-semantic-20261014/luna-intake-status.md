# Windows-native v0.21.7 intake status

Date: 2026-10-14
Status: investigation evidence only; no product change is approved by this record.

## Scope

This note records the B001 free-intake candidate review against the reviewed local source snapshot `ec5af6f193ca9ad799d652838802dfe83ea4dc32` and frozen upstream snapshot `63d0b94120027d487c9a5235b9ec64b696af1b26` (baseline `71d34bad1045610252eda02ee79549436896e784`). It does not claim that the candidate is merged, that v0.21.7 is complete, or that a release is ready.

## Candidate evidence

The review packet is identified by SHA-256 `9447B13262CAC0BE62A1E4DC81D85014A7A8FB601B36F070375BAC867B3C2723`; its readable companion is `27A18539EAC15B3B8223F8023171895E997B8F1CC87B2807C38612FE58F0A044`.

The packet contains three candidate records, but only two model outputs include all three records; the third includes one. The requested maximum-reasoning variants were not applied: the wrapper passed the variant argument after invocation, and the packet records `effectiveVariant` as null. This is not a complete three-output quorum, and the candidate dispositions remain provisional.

## Dispositions

- `tui_gateway/session_workdir.py`: **BLOCKED**. The path is absent from the reviewed local snapshot. No equivalent implementation has been established, so no code change is proposed for this candidate.
- Desktop session workdir hook and its coupled test: **provisional ADAPT**. The local hook callback accepts runtime information without a target session ID. The `wiring.tsx` caller resolves the active session internally, so the candidate's target-session behavior is not wired through the current call path. The test disposition depends on an approved hook-and-caller design.
- The remaining packet proposals are **not approved for adoption** by this intake. Candidate text or model consensus alone is not publication evidence.

## Completion boundary

This branch changes documentation only. No product test, full-suite, CI, package, runtime, or release result is claimed. Hermes remains short of the v0.21.7 completion claim.

Before any product adoption, rerun the missing requested variants through a corrected invocation and preserve the effective-variant metadata; review the target-session behavior across the hook, caller, and test; resolve the absent-path candidate against an identified source contract; and obtain an independent review of the resulting code and focused tests. Until then, retain these dispositions as BLOCKED or provisional ADAPT.
