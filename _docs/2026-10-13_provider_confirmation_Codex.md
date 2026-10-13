# Confirm manual provider defaults before persistence

Frozen upstream main: `63d0b94120027d487c9a5235b9ec64b696af1b26`. Contract commit: `f8b272b90ef2427d037b5232f4ef0102517a1d75`. Local parent and recovery reference: `79e110a40da1a216c7029970135a8ae026af8102`.

## Behavior adapted

ADAPT manual provider onboarding at the existing Desktop store boundary. OAuth and API-key connections validate the newly connected provider and display the confirmation card without changing the global model default. Begin writes the chosen provider/model to the profile captured for that flow. Closing the confirmation card leaves the existing default unchanged. First-run eager assignment is preserved.

An assignment failure produces a visible error notification and retains the frozen upstream best-effort completion behavior. Generation checks suppress stale completion effects. No Desktop component, new environment variable, provider router, or structural upstream refactor is introduced. The upstream-only owner test file is absent locally; the relevant flow is covered in the existing onboarding test file.

## Verification

The pre-change behavioral RED reached the premature `/api/model/set` assertion: one failure, with the other 18 cases intentionally filtered out. The final full onboarding test file passed 21 cases, zero failures and zero skips. It covers manual OAuth/API-key setup, runtime validation of the connected provider, the pinned profile, confirmation persistence, dismissal preserving the prior default, visible save-failure notification and exactly one completion callback, plus existing first-run and lifetime controls.

An intermediate notification-spy failure was test instrumentation, not a product RED. The final test observes the actual notifications store. Targeted ESLint passed. Renderer typecheck passed before the final test-only additions; the unchanged product source retains that evidence. Tests use existing ROOT Vitest with an isolated H-drive HOME and credentials removed; no live or paid provider was invoked.

CodeGraph maps the completion helper to OAuth polling, submitted codes, external sign-in and API-key setup, and maps confirmation to the Desktop overlay. Final incremental indexing includes the added tests: 9,180 files, 198,435 nodes, 626,004 edges, extraction version 25 complete, zero pending changes or references. A second incremental update was needed because acceptance tests were added after the first source freeze; no database was cloned or reindexed in full.

Separate Luna MAX review returned specification and quality PASS for this contract. This is focused store-level proof; actual packaged Desktop operations and the remaining frozen upstream contracts are separate open requirements.

## Evidence and recovery

Evidence directory: `H:/Codex-v0216-archive/`. `V0217_PROVIDER_CONFIRM_CLOSEOUT_20261013.md`, SHA256 `050F687B1BFE2ABE09529E372AAD3F7FA1B962682C829C5E20545AEA7AC0DF23`, records commands, source pins and logs. `V0217_PROVIDER_CONFIRM_INDEPENDENT_REVIEW_20261013.md`, SHA256 `E154750A8DBE02001777C67666AA8E09E4718A12D5492FA44C3722B0C160A522`, records the independent verdict and limits. The final GREEN4 log has SHA256 `60891A04AD75F3C835FDB21B6CC89A569C5FE3BEB3B706C9FE94997DC7009D0A`.

Parent protection guards and the local commit receipt connect this evidence to exact staged and committed blobs. Raw logs, databases, dependencies, credentials and unrelated local documents are excluded. Recovery is a targeted inverse commit on the isolated branch after checking later dependencies, using the parent above as prior source; never reset PRIMARY or discard unrelated work.

The product version remains unchanged. This commit does not claim full 0.21.7 compatibility, actual package acceptance, publication or a live service update.
