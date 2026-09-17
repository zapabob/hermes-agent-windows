# Implementation Audit Log: Slice D — Desktop Model Picker Ownership Isolation

- **Date**: 2026-09-17
- **Feature**: Slice D — Desktop Model Picker Ownership Isolation
- **Implementer**: Gemini / Claude (Advanced Agentic Pair Programmer)
- **Baseline**: `ecce743c762de70bb08c4363db7b64b5bac7c02b` (Slice C.1.1 CLOSED)
- **Freeze**: `d93f7d9b96` (Slice D TDD GREEN)
- **Status**: QUALIFIED (GREEN) — CLOSED

---

## 1. Mission

The Desktop model picker must always operate on the focused Desktop owner's
`(profileId, connectionId, sessionId)` and must never read or mutate an
ambient/global gateway connection.

Ownership dimensions formalized:

| Dimension | Owner key |
|---|---|
| Catalog cache | `(profileId, connectionId, provider)` |
| Selection | `(profileId, sessionId)` |
| Request | `(profileId, connectionId, requestGeneration)` |

---

## 2. Invariants Proved

Six scenarios verified by TDD (pure-function + async unit tests):

### PROFILE_ISOLATION

Tile-B focused → owner resolved as B (`connectionId`, `profile`) — A catalog,
A provider, A connection never read or written.

Tile-A focused → owner resolved from ambient (A) — B route never loaded.

Cross-read: B tile owner carries zero reference to A's route object.

### REFRESH_ISOLATION

Manual Refresh Models from tile-B dispatches only through the B-scoped
`request` dispatcher. A's dispatcher is never called.

Owner-routed refresh with empty response (re-auth needed): does NOT fall back
to ambient REST with A's profile name. Returns B's (empty) catalog; exactly 1
dispatch call.

### SWITCH_ISOLATION

Model switch on tile-B produces owner with `connectionId = conn-b` only.

Model switch on primary tile (focused == selected): uses ambient owner — no
tile route injected.

### RECONNECT_ISOLATION

Reconnect event on connection-B: tile-A owner resolves from ambient (`conn-a`)
unchanged. No bleed from `conn-b-reconnected`.

Post-reconnect: tile-B focused resolves to new `conn-b-reconnected` route
correctly.

### FOCUS_RACE

Rapid focus A → B → C: final resolution is C owner (`conn-c`, `backend-c`).

Rapid focus A → B → A: final resolution is ambient (focused == selected → no
route).

Unknown (unmounted ghost) tile `stored-ghost` not in `sessionTiles` → falls
back to ambient; no stale route surfaced.

### CREDENTIAL_CROSS_PROFILE_LEAK = ABSENT

Owner-routed `request` with selectable models:
- Dispatch called exactly once with `{ profile: 'profile-b', session_id: 'session-b' }`.
- No ambient REST fallback.

Owner-routed `request` with empty response:
- Dispatch called exactly once.
- REST fallback NOT attempted (would leak profile-a credential scope — #93892).

Owner-routed `request` throws:
- Error propagates to caller.
- No silent REST retry under foreign credential scope.
- Dispatch count = 1.

---

## 3. Implementation Architecture

### `resolveModelPickerOwner` (`apps/desktop/src/lib/model-picker-owner.ts`)

Pure synchronous function. Takes an explicit snapshot of the focused tile state
and ambient defaults. Returns one coherent `ModelPickerOwner`.

**Tile-wins rule**: A tile route wins only when `focusedStoredSessionId` differs
from `selectedStoredSessionId` AND the focused tile exists in `sessionTiles`.

Unknown/unmounted tile IDs produce no route → ambient fallback (no stale state).

### `requestModelOptions` (`apps/desktop/src/lib/model-options.ts`)

Owner-routed guard (line 187):
```typescript
if (!request) {
  // Only ambient gateway requests attempt REST recovery
  try { const restOptions = await restModelOptions(...) }
}
```
When `request` is set (owner-routed), the REST recovery block is skipped
entirely — foreign profile names never touch the ambient REST endpoint.

### `ModelPickerOverlay` (`apps/desktop/src/app/model-picker-overlay.tsx`)

Computes `pickerOwner` on every render from `$focusedStoredSessionId` and
`$sessionTiles`. All picker operations (`selectFocusedModel`, `requestPickerGateway`)
are bound to `pickerOwner.{connectionId, profile, route}` — never to ambient store state.

---

## 4. Verification

```text
Test file:
  apps/desktop/src/lib/model-picker-ownership-isolation.test.ts

Suite summary:
  Tests  15 passed (15)
  Exit   0
```

Full desktop Vitest suite:
```text
Test Files  805 passed | 1 skipped (806)
      Tests  8481 passed | 9 skipped (8490)
   Duration  758.29s
   Exit      0
```

---

## 5. Qualification Receipt

```text
======================= QUALIFICATION RECEIPT =======================
CATALOG TRACK BASELINE:             ecce743c762de70bb08c4363db7b64b5bac7c02b
SLICE D FREEZE:                     d93f7d9b96 (main)

catalog correctness:                PASS (ecce743c — CLOSED, not re-opened)
latest-model discovery:             PASS (ecce743c — CLOSED)
Nous independence:                  PASS (ecce743c — CLOSED)
fallback boundaries:                PASS (ecce743c — CLOSED)
Windows concurrency:                PASS (ecce743c — CLOSED)

                         ↓

PROFILE_ISOLATION:                  PASS
REFRESH_ISOLATION:                  PASS
SWITCH_ISOLATION:                   PASS
RECONNECT_ISOLATION:                PASS
FOCUS_RACE:                         PASS
CREDENTIAL_CROSS_PROFILE_LEAK:      ABSENT (PASS)

SLICE D STATUS:                     CLOSED
NEXT:                               Slice E (session/profile persistence semantics)
=====================================================================
```
