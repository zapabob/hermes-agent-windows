# N06 partial: security observation and corrupt evidence

Repository: `zapabob/hermes-agent-windows`. Product commit `cab98865a777e023a8b6862606796f955c9ae1c8`, tree `46ca81552919dec511eefa62e3ba310eae6234ea`. The campaign ceiling is U1 `678a4762b887f3eabe5cad11254b2ab1ae859485`; U0 is unchanged. This is a partial N06 contract, not full upstream coverage or production security qualification.

## Source and counterexamples

D0 has the downstream security CLI, service, store and Desktop security view. U1 has no corresponding downstream security paths; the fork capability therefore remains local. The integration predecessor retained T15/T16 and N04/N05 fixes. `hermes security status` previously constructed a writable `SecurityService`, called the ordinary config loader, and kicked the daily updater. The loader created `HERMES_HOME` even when status was the first observation. The Desktop then rendered absent or unreadable state as normal zero counts and empty lists. New actual-caller tests first reproduced these failures.

The final routing constructs `SecurityService(read_only=True)` for status, feeds, watch status and quarantine list/inspect. `load_config_observational()` reads effective config without initializing a home; only explicit scan keeps the daily update kick. The service marks missing state UNKNOWN. Corrupt SQLite, invalid findings JSON, SQLite BLOB values in a TEXT column, and unexpected evidence shape receive the generic `security_store_unreadable` classification. The shared decoder is used by aggregate rows and item inspection, so status, list and detail do not disagree on damaged evidence. The Desktop renders UNKNOWN rather than healthy-looking zero or empty-state labels.

RED evidence includes five corrupt-SQLite CLI/API cases, two detail JSON cases, four aggregate status/list cases, twelve BLOB cases and twelve malformed-shape cases, each observed before its correction. A canonical synthetic quarantine row remained readable through status, list and detail after the correction. The test data was inert and isolated under temporary `HERMES_HOME`; no production scanner, updater, quarantine action or destination writer was run.

## Verification and source binding

At the product commit, Windows Python 3.12 passed 58 selected status/observation tests across five affected security files. One strict xfail records SQLite WAL sidecar creation; 179 tests were outside that focused selection. Config tests passed 121 cases, SecurityView UI tests passed five, targeted ESLint passed, and `git diff --check` passed. A broader center/API run before the final decoder had four existing DPAPI `CryptProtectData` access-denied failures; it is not a final green native quarantine claim. Desktop TypeScript typecheck remained non-green with duplicate React types under the reused dependency junctions.

Two reversible mutants were killed: the mutating config loader broke uninitialized-home invariance, and routing every CLI command read-only broke explicit scan. Both were restored before final tests and commit. Independent read-only review found and drove the JSON/BLOB corrections, then found no new blocker in the final diff. The reviewer did not execute tests, CodeGraph or native writers.

Approved local CodeGraph 1.6.0 indexed D0, U1 and integration separately. Integration status was up to date with 8,950 files and zero pending changes or refs before and after the product commit. Query, explore and impact were rerun against the final source. External receipt `N06-20260927/receipt.json` has SHA-256 `cfaf2ccb4342f60e60e96866252fa4de17b92d0cd39665b965b4fe752ff9b59d`; it binds 14 product/test paths to actual, committed and indexed SHA-256 values and the Git blob OIDs.

## Open gates and preservation

N06-A2 remains partial: a read-only SQLite WAL connection may create `-wal` or `-shm` sidecars on this Windows host. The strict xfail keeps that whole-home purity contract visible. `immutable=1` was not substituted for a live DB because change detection and locking would be lost. The host also denies DPAPI protection in native quarantine tests; no OS setup was changed. The 17,065-commit metadata inventory is not a complete semantic ledger, and Control MCP production write remains DISABLED.

The original checkout and preserved feature worktree were not reset, stashed, cleaned or edited for this product change. An earlier read-only reviewer mistakenly wrote one new untracked report in the original checkout; it was moved intact to the external N06 receipt directory, and the original checkout was verified back to its prior state. No public PR, push or production restart was performed. To reverse only N06 in the isolated branch, review and revert product commit `cab98865a777e023a8b6862606796f955c9ae1c8`, then rerun affected tests and refresh the integration index. No reversal was performed.
