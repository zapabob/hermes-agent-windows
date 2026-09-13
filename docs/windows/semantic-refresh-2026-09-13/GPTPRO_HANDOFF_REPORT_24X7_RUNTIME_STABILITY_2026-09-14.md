# GPT-Pro Handoff: Hermes Windows 24/7 Runtime Stability (2026-09-14)

## Verdict

Go-first backend health state machine is **implemented and unit/native-tested**.  
**Soak: NOT_RUN. Do not claim 24/7 verified.**

## Root cause chain

1. HTTP probe timeout treated as process death → premature `stopLocked`
2. Desktop `Watchdog.failCount` coupled to backend soft failures → Desktop restart on stall
3. Token remint on soft restart → sessions 401 drift

## Files changed

| Path | Role |
|------|------|
| `probe.go` / `probe_windows_test.go` | ProbeKind / ProbeResult (timeout ≠ unauthorized ≠ dead) |
| `health.go` / `health_windows_test.go` | HEALTHY/DEGRADED/UNRESPONSIVE/DEAD + replace policy |
| `native_health_windows_test.go` | Live listener stall + grace restart |
| `backend.go` | EnsureHealthy wired to probes/health; keep on soft fail |
| `config.go` / `main.go` | soft-fail / grace / timeout / auth-confirm flags |
| `watchdog.go` | DEGRADED must not increment Desktop failCount |
| `process_windows.go` | probe helpers relocated (no second authority) |
| `README.md` | state machine + CLI docs |
| `tests/test_go_watchdog_architecture_contract.py` | reads `probe.go` + `health.go` |

**Not touched:** `apps/desktop/**`, Electron heartbeat, taskkill, second watchdog, plan file.

## State machine

```
alive + probes OK          → HEALTHY
alive + soft fail          → DEGRADED      (keep process, publish manifest)
DEGRADED ∧ N≥threshold ∧ t≥grace → UNRESPONSIVE → stopLocked → respawn (token keep)
owned PID dead             → DEAD          → stopLocked immediate
2× unauthorized            → controlled replace + token clear
```

## When `stopLocked` is allowed

- `DEAD`
- `UNRESPONSIVE` (threshold ∧ grace)
- confirmed unauthorized
- existing spawn/clear paths for zombies / foreign occupants (not single soft timeout)

## Token proof

- Stall/timeout: token unchanged, rotation not armed
- Hang restart after grace: token unchanged
- Confirmed unauthorized: token cleared for remint path

## Test evidence

| Check | Result |
|-------|--------|
| `go test ./... -count=1` (no `-short`) | PASS (~45s) |
| Native stall | PASS — no kill, DEGRADED→HEALTHY |
| Native hang+grace | PASS (~40s port-clear cost) |
| Full 120s grace in CI | SKIP (budget; shortened grace used) |
| `go test -race` | SKIP — requires CGO on Windows |
| pytest contracts + downstream windows | 40 passed |
| Operator soak | **NOT_RUN** |

Logs under `tmp/probes/*-20260914.log`.

## Absolute contracts preserved

- Go watchdog sole outer recovery
- Owned `os.Process` handle only
- Port 9119 managed backend
- Token reuse on soft restart
- `Watchdog.failCount` is Desktop-layer only
- DEGRADED ≠ nil backend

## Known gaps

1. Soak NOT_RUN
2. Race detector SKIP (no CGO)
3. Native hang test wall time ~40s
4. No claim of continuous 24/7 production proof

## Git

- Base HEAD before commits: `b8c3a13727350cd32e50b18cb7ff1246dc132801`
- Branch: `main`
- **Push: no**
- Impl log: `_docs/2026-09-14_24x7-runtime-stability_Cursor.md`

## Operator next step

Run overnight soak with existing boot/logon scheduled tasks; compare `hermes-go-watchdog.log` for degraded→recover without Desktop thrash.
