# Receipt — NC-0213-D4 Desktop recovery / readiness UX

| Field | Value |
|---|---|
| Slice | NC-0213-D4 |
| Campaign | windows-native-carry-v0.21.3 |
| U_NEXT | `345cd2b057a452236de401d3534b8502a7465e8d` |
| Decision | ADOPT |
| Method | COMPOSE / REIMPLEMENT_NATIVE into Windows owners (`backend-claim.ts`, `main.ts`, overlay) |
| Contract | Live-child probe failure → `degrade` + `pid-only:` marker (never kill healthy backend); overlay exit on `gatewayState === 'open'` only (not bootDone); Windows dwell cap kept with explicit non-readiness comment |
| Command | `esbuild backend-claim.ts` + `node --test` claim-policy (3 passed); vitest full suite deferred to promotion gate (workspace `@rolldown/plugin-babel`) |
| Result | **3 passed** (claimDecision degrade/fail/claim) |
| Exact tested SHA | _(stamped on commit)_ |
| LOCAL_DEPLOYED | NOT_RUN |
| main integration | NOT_DONE |

## U_NEXT existence check

- `claimDecision` degrade arm + `pidOnlyStartMarker` at U_NEXT `backend-claim.ts`
- Overlay readiness = `gatewayState === 'open'` at U_NEXT (no bootDone-without-open dismiss)
- Windows `CONNECTING_MAX_DWELL_MS` retained as local COMPOSE (dismiss ≠ ready)

## Files

- `apps/desktop/electron/backend-claim.ts` — restore degrade + `pidOnlyStartMarker` / `isPidOnlyStartMarker`
- `apps/desktop/electron/backend-claim.test.ts` — live-fail → degrade assertion
- `apps/desktop/electron/main.ts` — degrade path claims with PID-only marker + warning log
- `apps/desktop/src/components/gateway-connecting-overlay.tsx` — remove bootDone-without-open exit; keep dwell cap with non-readiness invariant comment

## Invariants held

- Process exit ≠ task success ≠ side-effect confirmation (claim degrade separates probe flakiness from child death)
- Ambiguous probe outcome does not auto-respawn (no kill on live child)
- CONNECTING overlay disappearance alone is not readiness (`gatewayState === 'open'` required)
- Desktop/backend/Gateway lifetime separation unchanged; Go Watchdog not a task owner
- Prompt cache untouched
