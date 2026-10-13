# Desktop interim mock routing

Date: 2026-10-14. Scope: prevent the E2E mock's interim-response script from being consumed by the non-streaming session-title request. The mock now advances that script only for a matching trigger with a non-empty tools array. The public Desktop request sequence is preserved: title generation receives the ordinary mock reply, then tool-bearing chat requests receive the scripted interim messages.

The focused Vitest regression at `apps/desktop/e2e/mock-server.unit.test.ts` passed 1/1 (709 ms) with the isolated runner recorded at `H:/Codex-v0216-archive/V0217_DESKTOP_INTERIM_R3_20261014/GREEN-mock-server-R2/`. It interleaves a title request and two chat requests and checks that both scripted chat responses remain in order. The single flag-ON Playwright case `all interim texts survive alongside the final response` passed 1/1 (47.0 s; assertion completed in 29.7 s) using the already-built Desktop output. It exercised the public interim-message flow after the mock fix.

The flag-OFF stale-interim failure remains open. This mock change does not alter renderer or backend behavior, and it does not establish that flag-OFF preserves or clears text correctly. No renderer rebuild was performed. Earlier exploratory edits to `apps/desktop/src/app/session/hooks/use-message-stream/interim-sealing.test.tsx` were reverted after its saved copy and patch were verified; the file is now clean against HEAD. No product fix is claimed for the unresolved OFF path.

Final owned file SHA-256 values: `apps/desktop/e2e/mock-server.ts` = `8286567481B9BAD7B6E96D84E30DDC6879684E3E0CED86EFF74162C59AC2E310`; `apps/desktop/e2e/mock-server.unit.test.ts` = `D9E70AF045CFC2E772FC93611E74BC4A595629F6EB8600628F8019CCD732AC09`. Restored interim test SHA-256 is `966E3D6D5CCEC60DA92C70C48977E3F76AB2BF48EC2FADB8B68D5BE867691BC3`.

The single incremental CodeGraph sync reported two changed files (one added, one modified; 62 nodes). Final status: 9,183 files, 198,489 nodes, 626,210 edges, complete extraction format 25, zero pending changes/references, no reindex recommended. The focused `startMockServer` caller mapping includes the E2E fixture setup and the new mock unit test. This graph result covers the two mock files only.

Detailed launch provenance, raw logs, exit code, and CodeGraph commands are recorded in `H:/Codex-v0216-archive/V0217_DESKTOP_INTERIM_MOCK_CLOSEOUT_20261014.md`.


The follow-up direct ESLint check included both E2E files and exited 1: one named-import ordering error in the new unit test and 52 blank-line warnings (50 in the pre-existing mock server, two in the new test). The package lint script omits e2e, but the direct config check did include it. No source edits followed the lint result; details and raw log pins are in the H closeout.


The final direct ESLint rerun included both E2E files and exited 0. The new unit test has no remaining lint findings; `mock-server.ts` retains 50 existing blank-line warnings. The earlier failing ESLint receipts remain preserved separately. The mock unit test changed only in import ordering and two blank-line placements after the prior source review; its earlier reviewed pin was `55BAA819368B5607B45142CB1CD25DDEBB15280C04DACF1E9A702C679C8B604E`, and the final pin is `D9E70AF045CFC2E772FC93611E74BC4A595629F6EB8600628F8019CCD732AC09`. Per the formatting-only repair instruction, Vitest and Electron were not rerun.
