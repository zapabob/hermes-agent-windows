# Slice D.1.1: Production-Path Model Picker Async Fencing Qualification

**Date:** 2026-09-17  
**Implementer:** Gemini 3.8 Flash (Advanced Agentic Pair Programmer)  
**Workspace:** `c:\Users\downl\Documents\New project\hermes-agent` (`zapabob/hermes-agent-windows`)  
**Baseline Freeze:** `ec7d86eb0e7f3625de2380e7f099b0a0ea878467` / `ac621c1831`  

---

## 1. Objective & Mandate

Qualify the model picker response fencing against the **real production code paths**, verifying whether existing mechanisms (`selectionEpochByTargetRef`, `refreshCurrentModel(force=true)`, `useQuery` observer gating in `ModelPickerDialog`, and owner resolution in `ModelPickerOverlay`) are ALREADY_EQUIVALENT without introducing speculative `requestGeneration` state:

1. **STALE SWITCH ACK:** Real `useModelControls.selectModel` hook with deferred `requestGateway` promises.
2. **PROFILE SWAP WITH PENDING ACK:** Real `useModelControls` with in-flight switch under Profile A, profile swapped via production `refreshCurrentModel(force=true)`, ensuring stale A acknowledgement cannot mutate B state.
3. **ACTUAL REACT QUERY UNMOUNT:** Real `ModelPickerDialog` inside `QueryClientProvider`, unmounted/switched while query is pending, late response resolved.
4. **ACTUAL FOCUS OWNER SWITCH:** Integration-level test around `ModelPickerOverlay` and `QueryClient`.

---

## 2. Production Mechanisms Qualified

### 2.1 Stale Switch Acknowledgement (`useModelControls.selectModel`)
- **Call chain under test:** `useModelControls.selectModel` $\to$ `requestGateway('config.set', ...)` $\to$ `commitAcknowledged` $\to$ `commitSelection` $\to$ `selectionIsCurrent()`.
- **Mechanism:** `selectionEpochByTargetRef.current.get(selectionTarget) === selectionEpoch`.
- **Target key:** `${cacheOwnerConnectionId ?? '<ambient>'}\0${liveGatewayProfile}\0${liveSessionId ?? '<new-session>'}`.
- **Result:**
  - Tile B starts switch B2 (epoch 1, held pending).
  - Tile B starts switch B3 (epoch 2, held pending).
  - B3 acknowledges first $\to$ Tile B updates to B3 (`resB3 === true`).
  - Stale B2 acknowledges later $\to$ `selectionEpochByTargetRef` check evaluates `1 === 2` (`false`), bailing out cleanly (`resB2 === false`).
  - Tile B remains on B3, query cache remains B3, primary tile A is completely untouched.
- **Classification:** `STALE_SWITCH_ACK_FENCED = ALREADY_EQUIVALENT`

### 2.2 Profile Swap Lifecycle Invalidation (`useModelControls.refreshCurrentModel`)
- **Call chain under test:** Switch starts under Profile A. During transit, active profile switches to Profile B and calls the production lifecycle callback `refreshCurrentModel(force=true)`.
- **Mechanism:**
  ```typescript
  if (force) {
    profileRefreshEpochRef.current += 1
    selectionEpochByTargetRef.current.clear()
  }
  ```
- **Result:**
  - `refreshCurrentModel(true)` executes the production epoch wipe on `selectionEpochByTargetRef`.
  - When deferred A acknowledgement arrives, `selectionIsCurrent()` finds `get(selectionTarget)` is `undefined !== selectionEpoch`, and `$activeGatewayProfile.get() !== liveGatewayProfile`.
  - Late A acknowledgement is cleanly discarded (`resA === false`). Profile B state remains intact.
- **Classification:** `PROFILE_SWAP_ACK_FENCED = ALREADY_EQUIVALENT`

### 2.3 React Query Component Unmount (`ModelPickerDialog`)
- **Call chain under test:** `ModelPickerDialog` mounted with `open=true` for Owner B with deferred `model.options` query. Host re-renders unmounting/closing B and mounting Owner A. Late B request settles.
- **Mechanism:** `enabled: open` in `ModelPickerDialog`, plus distinct TanStack React Query keys:
  `['model-options', 'profile-a', 'session-a', 'owner', 'conn-a']` vs
  `['model-options', 'profile-b', 'session-b', 'owner', 'conn-b']`.
- **Result:**
  - Owner A renders and displays only Owner A catalog (`OpenAI`).
  - Late B resolution does not mutate Owner A DOM or Owner A cache.
  - If cached, B result exists only under B owner key; zero ambient/global cache keys created or mutated.
- **Classification:** `UNMOUNTED_OWNER_RESPONSE_FENCED = ALREADY_EQUIVALENT`

### 2.4 Focus Owner Switch (`ModelPickerOverlay` Integration)
- **Call chain under test:** `ModelPickerOverlay` mounted with focus on Tile A (`$focusedStoredSessionId = 'stored-a'`). A request begins and is held pending. Focus switches to Tile B (`$focusedStoredSessionId = 'stored-b'`). B request begins and resolves first. Late A resolves second.
- **Mechanism:** `resolveModelPickerOwner` resolves the focused tile route, dynamically binding `requestPickerGateway` to Tile B's connection and profile.
- **Result:**
  - Visible `ModelPickerDialog` DOM displays Tile B state (`Anthropic`).
  - Late A resolution does not overwrite Tile B DOM (`Anthropic` remains, `OpenAI` is absent).
  - QueryClient holds both results in their exact respective owner keys without cross-contamination.
- **Classification:** `ASYNC_FOCUS_UI_FENCED = ALREADY_EQUIVALENT`

---

## 3. Test Evidence

Test file: `apps/desktop/src/lib/model-picker-async-fencing-production.test.tsx`  
Runner: Vitest v4.1.11

```
 RUN  v4.1.11 C:/Users/downl/Documents/New project/hermes-agent/apps/desktop

 ✓  ui  src/lib/model-picker-async-fencing-production.test.tsx (4 tests) 529ms
       ✓ fences stale switch acknowledgement when B3 resolves before B2: B3 wins, tile A unchanged (35ms)
       ✓ fences pending switch acknowledgement when profile is swapped via refreshCurrentModel(force=true) (12ms)
       ✓ unmounting or closing Owner B while query is pending does not corrupt Owner A UI or cache (411ms)
       ✓ switches focus from A to B while A is pending: B displays B state, late A does not overwrite B (147ms)

 Test Files  1 passed (1)
      Tests  4 passed (4)
```

Combined Slice D + D.1 + D.1.1 test results:
```
 ✓  ui  src/lib/model-picker-ownership-isolation.test.ts (15 tests)
 ✓  ui  src/lib/model-picker-async-fencing.test.ts (15 tests)
 ✓  ui  src/lib/model-picker-async-fencing-production.test.tsx (4 tests)

 Test Files  3 passed (3)
      Tests  34 passed (34)
```

---

## 4. Final Classification & Acceptance

```
STALE_SWITCH_ACK_FENCED          = ALREADY_EQUIVALENT
PROFILE_SWAP_ACK_FENCED          = ALREADY_EQUIVALENT
UNMOUNTED_OWNER_RESPONSE_FENCED  = ALREADY_EQUIVALENT
ASYNC_FOCUS_UI_FENCED            = ALREADY_EQUIVALENT
REQUEST_GENERATION_REQUIRED      = NO
```

**Slice D.1.1 is CLOSED.**  
Next milestone: **Slice E — session/profile persistence semantics**.
