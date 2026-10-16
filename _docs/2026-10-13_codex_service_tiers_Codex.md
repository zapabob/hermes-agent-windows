# Respect selected-account Codex service tiers

Frozen official main: `63d0b94120027d487c9a5235b9ec64b696af1b26`. Adopted contract: `c09527ad4f5bc2d710fec50198afae881b75bfed`. Local parent/recovery reference: `e431a97c726470f406b754ee92110394baa43d08`.

## Behavior adapted

ADAPT request-time service-tier negotiation at the existing request builder. Only official Codex OAuth requests consult the selected token fingerprint and model's advertised tiers. Known unsupported tiers are omitted. Unknown or unavailable information preserves the explicit preference. An unsupported `ultrafast` request may fall back to advertised `priority`; a `priority` preference is never upgraded. Request overrides are copied, and API-key, proxy and non-Codex behavior remains unchanged.

The existing authenticated model-catalog probe supplies normalized tier identifiers to a bounded account cache. The separate context-window cache retains its normal behavior. Independent review identified a split-cache defect: tier eviction could encounter a fresh context entry and skip the necessary catalog request. The repair adds an opt-in catalog refresh that bypasses that early return without rewriting an already-fresh context entry. Both successful refresh and failed refresh have direct request-builder regressions.

The user-facing `ultra` alias and `/fast` preference interface remain open. This commit does not claim full service-tier or frozen-upstream parity, change the product version, or rebuild Desktop.

## Verification and correction of test setup

The initial request-builder RED demonstrated `priority` being emitted for a model whose catalog advertised no tiers. The review repair added two behavioral REDs for the fresh-context/missing-tier state. Original runs inherited the host environment; they provide behavioral evidence but do not qualify as the required isolated acceptance. That limitation was disclosed and retained in additive records, not hidden by replacing logs.

Final acceptance used an explicitly allowlisted native Windows environment, separate H-drive homes and temporary directories, UTC/UTF-8, no credential-like environment keys, fixed ROOT venv Python and asserted ROOT module origins. Batch A passed 165 cases: new tier tests 10, existing provider parity 54, existing Codex transport 101. Batch B passed two selected existing model-metadata catalog/fallback cases. Total: 167 passed, zero failures; the entire metadata file was not run. Ruff and diff-check passed for the unchanged final sources.

Independent Luna source review verified the final four source/test hashes and closed the cache-split finding. Separate final acceptance review read the sanitized launcher and accepted the qualified evidence. Parent closeout also checked raw A/B provenance and terminal summaries, exact log hashes, and the standard runner's `sys.executable`, copied sanitized environment, repository-root derivation and child working directory. No live provider or paid API was used.

Final CodeGraph after the R2 source freeze: 9,182 files, 198,471 nodes, 626,106 edges, extraction version 25 complete, zero pending changes/references. The later environment-only rerun did not change indexed sources or require another sync.

## Evidence and recovery

All evidence is under `H:/Codex-v0216-archive/`. Final source evidence: `V0217_CODEX_TIERS_R2_CLOSEOUT_20261013.md`, SHA256 `6677E95A93DB4ACF15961089707B995E6DC2C8C4CBAA0DB3210F7B32274365A3`. Source review: `V0217_CODEX_TIERS_INDEPENDENT_REVIEW_R2_20261013.md`, SHA256 `3C2E87E6919F35B51FF93A12F1A7744B7472DAE973CDE0B219DCCAA936A0F282`.

Qualified acceptance: `V0217_CODEX_TIERS_R4_SANITIZED_FINAL_CLOSEOUT_20261013.md`, SHA256 `C3E410A1C8EF1D6BAE4178D88D2A63DD538F17B63232440DB3253DD541FC10EC`. Final independent acceptance: `V0217_CODEX_TIERS_FINAL_ACCEPTANCE_REVIEW_20261013.md`, SHA256 `51BA1E27326C259852163187C7CCF59620A87C3B215091F31E7B7B79CBC9C2BA`. Sanitized launcher SHA256 `309B5521E8F781E8045A2E3CFBD120740CFE91F2A40578089232E3ECB5E994AB`; A log `84DD96D0D2D0EB9F923CFE9922BB209F62DA37020DF99DDEEE99F572B04507E8`; B log `2C73D6C7FA02012B96AA8444B312AA6FBBEC435D9E67FD7871EC02D7AD3712CB`.

The local commit receipt ties exact paths/blobs and protected-state checks to these records. Raw logs, environments, databases, secrets and unrelated dirty documents are excluded. Recovery is a targeted inverse commit on the isolated branch after checking later dependencies; use the parent above as prior source, never reset PRIMARY or discard unrelated work. Actual isolated package acceptance and the complete Windows 0.21.7 goal remain open.
