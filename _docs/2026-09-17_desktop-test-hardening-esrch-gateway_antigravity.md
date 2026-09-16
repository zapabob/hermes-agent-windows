# MILSPEC Implementation Audit Record: Desktop Test Hardening (ESRCH & Gateway onRequest)

- **Date**: 2026-09-17
- **Feature**: Fix Linux ESRCH processStartMarker handling and guard gateway.onRequest in Desktop
- **Agent**: Antigravity (Gemini 3.8 Flash)
- **Branch / Revision**: `main` (commit `5cb889f0a1`)
- **Status**: Complete / Validated

---

## 1. Background & Root Cause Analysis

Following the merge of PR #127 and PR #128 (`fix/windows-runtime-authority-g1-g2-20260917`), CI checks on Linux runners exhibited two distinct test failures within `apps/desktop`:

1. **Linux `processStartMarker` Dead PID Handling (`apps/desktop/electron/orphan-reap-liveness.test.ts`)**:
   - `processStartMarker(pid, isAlive)` previously branched on `process.platform === 'linux'` and directly called `fs.promises.readFile('/proc/${pid}/stat', 'utf8')`.
   - On Linux, reading `/proc/<deadPid>/stat` fails with `ENOENT`.
   - Test 10 in `orphan-reap-liveness.test.ts` expects an error with `err.code === 'ESRCH'` when encountering a dead process or when the injected `isAlive` predicate returns `false`.
   - On Linux runners, the absence of `isAlive` evaluation before `/proc` inspection and raw `ENOENT` re-throw caused `AssertionError: Must set error.code = ESRCH: 'ENOENT' !== 'ESRCH'`.

2. **Un-guarded `gateway.onRequest` Call in `apps/desktop/src/store/gateway.ts`**:
   - In `createSecondary`, `entry.offRequest = gateway.onRequest(...)` was invoked unconditionally.
   - Vitest unit tests (`gateway-activation-prune-lease.test.ts` and `plugin-socket-scope.test.ts`) mock `HermesGateway` without `onRequest`, leading to `TypeError: gateway.onRequest is not a function`.

---

## 2. Implementation & Repairs

### A. `apps/desktop/electron/backend-claim.ts`
- Added an initial check respecting explicit custom `isAlive` predicates:
  ```ts
  if (isAlive !== isPidAliveWindows && !isAlive(pid)) {
    const error = new Error(`ESRCH: no process found with PID ${pid}`) as NodeJS.ErrnoException
    error.code = 'ESRCH'
    throw error
  }
  ```
- Wrapped `/proc/${pid}/stat` read in a `try...catch` block mapping `ENOENT` to a standardized `ESRCH` error with `error.code = 'ESRCH'`.

### B. `apps/desktop/src/store/gateway.ts`
- Guarded `gateway.onRequest` defensively:
  ```ts
  entry.offRequest =
    typeof gateway.onRequest === 'function'
      ? gateway.onRequest(request => {
          g.config?.onServerRequest?.({ ...request, ...(connectionId ? { connectionId } : {}), profile })
        })
      : () => {}
  ```

### C. Test Suite Mock Hardening
- `apps/desktop/src/store/gateway-activation-prune-lease.test.ts`: Added `onRequest = vi.fn(() => () => {})` to the mocked `HermesGateway`.
- `apps/desktop/src/plugin-socket-scope.test.ts`: Added `onRequest = vi.fn(() => () => {})` to the mocked `HermesGateway`.

---

## 3. Local Verification

Executed native targeted Vitest suite:
```bash
pnpm --dir apps/desktop exec vitest run src/store/gateway-activation-prune-lease.test.ts src/plugin-socket-scope.test.ts electron/orphan-reap-liveness.test.ts
```
**Results**:
- `gateway-activation-prune-lease.test.ts`: 4 passed (100%)
- `plugin-socket-scope.test.ts`: 3 passed (100%)
- `orphan-reap-liveness.test.ts`: 10 passed (100%)
- Total: 17 passed, 0 failed.

---

## 4. Operational Invariants Preserved
- No regression in Windows process handle verification or Session 0 authority contracts.
- Strict backward compatibility for mock and production socket implementations.
- All temporary artifacts isolated to `tmp/probes/` leaving working tree pristine.
