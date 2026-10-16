# Preserve profile defaults when creating Desktop sessions

Frozen upstream main: `63d0b94120027d487c9a5235b9ec64b696af1b26`. Local parent/recovery reference: `6b0880ea048893eae1143ae1e2bca2696ab9c6c8`.

## Behavior adapted

ADAPT the frozen session-create model-source rule at the existing local request owner, without adopting upstream module rearrangements. The request snapshots model source together with model/provider before the asynchronous profile handshake. Only a manual model selection supplies model/provider overrides to `session.create`; default-derived composer values no longer pin a new chat against its profile defaults. Reasoning effort, fast mode, profile and workspace behavior retain their existing contracts.

The public-action regression covers actual `session.create` and first `prompt.submit` arguments, manual selection, omission of default-derived values, first-message retention across warm resume, and transcript reconciliation without duplicate user messages. Existing picker and production async-fencing tests are reused unchanged.

The frozen upstream refusal test expects removal of the optimistic user row. Local submit handling deliberately keeps typed input with a visible assistant error for retry, and excludes failed turns from backend ordinal calculations. Preserve this proven local behavior as ADAPT: the new public rejection case checks false return, retained input, visible error and released busy/awaiting state. No upstream zero-row equivalence or live inference claim is made.

## Verification

RED_R1 failed before collection because an upstream-only test helper was absent; RED_R2 exposed shared test-store state not reset between cases. Neither is product RED. RED_R3 reached the actual request assertion and demonstrated unwanted default model/provider overrides. Its copied upstream refusal assertion also recorded the documented local behavioral difference; the raw log remains intact.

GREEN_R1 passed 36 cases across three files. Following import cleanup and explicit request argument typing, GREEN_R2 passed the final new test's four cases; the 32 unchanged picker/fencing cases are reused. Desktop renderer typecheck (`tsc -p tsconfig.typecheck.json --noEmit`) and ESLint on the two changed files passed. An initial TypeScript launcher-path error occurred before compiler startup and was corrected to the existing root dependency. No dependencies were installed or updated.

The H-drive Node launcher used existing ROOT Vitest, explicit Desktop working directory, an allowlisted environment without provider credentials and isolated HOME/HERMES_HOME/temp. No live providers or production services were used. One final CodeGraph sync indexed two changed files and 78 nodes; status showed 9,179 files, current extraction version 25 and zero pending changes/references. The caller mapping locates `desktopSessionCreateParams` on the actual `useSessionActions` creation path.

Independent Luna MAX review verified both final source/test hashes and returned specification and quality PASS for this unit. Full model-response display, restart and actual packaged UI acceptance remain separate requirements.

## Evidence and recovery

Evidence directory: `H:/Codex-v0216-archive/`. `V0217_DESKTOP_MODEL_SELECTION_CLOSEOUT_20261013.md` (SHA256 `DF76B1D18C9A09DED0BC433C78D31924C42B71415C50DB9A32C71CE9774755A3`) indexes source hashes, runner arguments and RED/GREEN logs. `V0217_DESKTOP_MODEL_SELECTION_INDEPENDENT_REVIEW_20261013.md` has SHA256 `826483683ED7FEDBABB66516E43F87CC52011633B669E4A64AF5EE91F44CE008`. Parent guards and the commit receipt connect protected-state checks to exact staged and committed blobs. Raw logs, dependencies, databases, credentials and unrelated local materials are excluded from this commit.

Recovery is a targeted revert on the isolated branch after checking later dependencies, using the parent above as prior source. Do not reset PRIMARY or discard unrelated work. The broader frozen-delta ledger, local resource/memory and Windows execution contracts, actual isolated package acceptance and version 0.21.7 remain open.
