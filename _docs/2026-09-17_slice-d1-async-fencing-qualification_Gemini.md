# Implementation Audit Log: Slice D.1 — Async Model Picker Response Fencing

- **Date**: 2026-09-17
- **Feature**: Slice D.1 — Async Model Picker Response Fencing Qualification
- **Implementer**: Claude (Advanced Agentic Pair Programmer)
- **Baseline**: `d93f7d9b96cec12d2fdfd279abe3745d5d0229fb` (Slice D CLOSED)
- **Freeze**: `ec7d86eb0e` (Slice D.1 TDD GREEN)
- **Status**: QUALIFIED (GREEN) — CLOSED

---

## 1. Mission

Prove whether existing Desktop picker mechanisms already provide equivalent
async response fencing across four RED scenarios. Introduce new generation
state only if a genuine test failure demonstrates a gap.

**Outcome**: All four contracts are **ALREADY_EQUIVALENT**. No new
`requestGeneration` state was introduced.

---

## 2. Mechanisms Under Test

| Mechanism | Location |
|---|---|
| Owner-scoped React Query key | `modelOptionsQueryKey()` in `model-options.ts` |
| `connectionId` cache key | `ownerConnectionId` segment in `modelOptionsQueryKey` |
| `selectionEpochByTargetRef` | `useModelControls` / `selectModel` in `use-model-controls.ts` |
| React component ownership | `enabled: open` guard in `ModelPickerDialog.useQuery` |

---

## 3. RED Scenario Classification

### RED 1 — Focus race with real async responses

**Mechanism**: owner-scoped React Query key

Owner A and Owner B are keyed under distinct cache entries:
```
modelOptionsQueryKey('profile-a', sessionId, 'conn-a')  ≠
modelOptionsQueryKey('profile-b', sessionId, 'conn-b')
```
A's response is stored at A's key. B's `useQuery` reads B's key only.
A arriving late cannot overwrite B's UI state regardless of timing.

**Classification**: `ALREADY_EQUIVALENT`

### RED 2 — Reconnect generation race (B1 → B2)

**Mechanism**: `connectionId` cache key

When B reconnects, `ownerConnectionId` changes from `conn-b1` to `conn-b2`.
The React Query key changes:
```
modelOptionsQueryKey('profile-b', sessionId, 'conn-b1')  ≠
modelOptionsQueryKey('profile-b', sessionId, 'conn-b2')
```
The late B1 response writes to the B1 key. B2's picker reads the B2 key.
No B1 credential or endpoint state is reused under B2.

**Classification**: `ALREADY_EQUIVALENT`

### RED 3 — Delayed switch acknowledgement (B2 → B3)

**Mechanism**: `selectionEpochByTargetRef` in `useModelControls`

`selectModel` increments a per-target epoch on every call:
```typescript
const selectionTarget = `${connectionId}\0${profile}\0${sessionId}`
const selectionEpoch = (epochMap.get(target) ?? 0) + 1
epochMap.set(target, selectionEpoch)
```
`commitAcknowledged` calls `selectionIsCurrent()`:
```typescript
epochMap.get(target) === selectionEpoch
```
The B2 ack arrives after B3 was selected. `epochMap.get(targetB)` now
equals B3's epoch, so B2's `selectionIsCurrent()` returns false — the
stale ack is discarded. Tile A's epoch map entry is independent.

`refreshCurrentModel(force=true)` calls `epochMap.clear()` — old profile's
in-flight acks are fenced on profile swap.

**Classification**: `ALREADY_EQUIVALENT`

### RED 4 — Unmount while pending

**Mechanism**: React component ownership (`enabled: open` guard)

`ModelPickerDialog` uses:
```typescript
useQuery({
  queryKey: modelOptionsQueryKey(profile, sessionId, ownerConnectionId),
  queryFn: () => requestModelOptions({ ... }),
  enabled: open
})
```
When `open=false` (dialog closed or tile unmounted), the query is disabled —
no fetch fires. Even if a prior fetch was in-flight, React Query removes the
observer on unmount and the resolved data is written only to the owner-keyed
cache — never to tile A's separate key or any ambient React state.

**Classification**: `ALREADY_EQUIVALENT`

---

## 4. Implementation Decision

> **No new `requestGeneration` state was introduced.**

The four existing mechanisms together provide generation-equivalent fencing
across all async race scenarios. Adding `requestGeneration` would be
speculative infrastructure (violating AGENTS.md §2 "What We Reject") because
no failing test demonstrated a real gap.

---

## 5. Verification

```text
Test file:
  apps/desktop/src/lib/model-picker-async-fencing.test.ts

Suite summary:
  Tests  15 passed (15)
  Exit   0
```

---

## 6. Qualification Receipt

```text
======================= QUALIFICATION RECEIPT =======================
SLICE D BASELINE:    d93f7d9b96cec12d2fdfd279abe3745d5d0229fb
SLICE D.1 FREEZE:    ec7d86eb0e (main)

ASYNC_FOCUS_RACE_FENCED:          ALREADY_EQUIVALENT (React Query key isolation)
STALE_CONNECTION_RESPONSE_FENCED: ALREADY_EQUIVALENT (connectionId key segment)
STALE_SWITCH_ACK_FENCED:          ALREADY_EQUIVALENT (selectionEpochByTargetRef)
UNMOUNTED_OWNER_RESPONSE_FENCED:  ALREADY_EQUIVALENT (enabled: open guard)

NEW_GENERATION_STATE_INTRODUCED:  NONE

SLICE D.1 STATUS:    CLOSED
NEXT:                Slice E (session/profile persistence semantics)
=====================================================================
```
