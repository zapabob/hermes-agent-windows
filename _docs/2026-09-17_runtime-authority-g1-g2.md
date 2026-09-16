# Windows runtime authority: G1/G2

Audit base: `18850122ed29b41ed24c526c63289cd2c9fc437f`.
Scope is limited to embedding-child environment and operator watchdog process identity. No upstream tree mirroring, Desktop ownership migration, inference-model changes, or deployment restart is included.

## Before / after

| Boundary | Before | After |
| --- | --- | --- |
| Watchdog -> embedding llama-server | Parent environment except incompatible cache type | Child-local credential-name filter; parent is not mutated; OS/GPU/inference settings and this server's own `LLAMA_API_KEY`, API-key file and TLS-key file remain usable |
| Denied identity query | Visible Session 0 PID plus serialized lock path/root could become owned | Query failure remains unverified, preserving the lock; only proved absence/exit is stale |
| Operator Session 0 displacement | Failed handle open could fall back to a numeric-PID stop | Bounded retry using the operator's existing SeDebugPrivilege, restored to its prior state; live creation time/image must still match on the exact termination handle |
| Stop completion | Wait result discarded | Non-signalled/failed wait preserves evidence and reports failure |

Electron remains the default backend owner. The Go Session 0 prohibition on killing interactive Desktop is unchanged. No mutation API is added. G3-G6 are not part of this change.

## Regression-first evidence

G1 test commit: `63b9a14b1b59ae65cad96d135e3574054850a7d2`.
Windows Tier-1 run `35121028627`, job `104878548468`, ran `go test ./...` against the PR merge tree. `TestEmbeddingDoesNotInheritUnrelatedCredentials` failed on 16 synthetic credential names; the local-inference preservation test did not fail. The subsequent G1 production change is `140367cee23a9daaef2e40c671f2dc4b8a02422f`.

G2 regression commit: `5e408e3f69ebe3bf938118570e439c941274a20d`. The tests load production PowerShell AST function definitions, never execute the launcher, and use temporary locks. Denied query, invisible/denied process, denied terminate handle, incarnation change, image change, verified Session 0 owner, and incomplete wait are tested with non-destructive native-call doubles. A separate real-child test validates and terminates only its retained harmless sleeper. Both Windows PowerShell 5.1 and PowerShell 7 are required on Windows.

## Validation commands

```powershell
python -m pytest tests/test_go_watchdog_runtime_authority.py tests/test_go_watchdog_launcher_authority.py tests/test_go_watchdog_architecture_contract.py tests/test_go_watchdog_task_registration.py -q
Push-Location scripts/windows/watchdog-go
try { go test ./...; if ($LASTEXITCODE) { exit $LASTEXITCODE }; go vet ./... } finally { Pop-Location }
```

Passing these focused tests is not a claim that repository-wide CI is green. Baseline JS/Python/Tier-1 failures must be diagnosed separately; no test or gate is disabled by this patch.

## Security limits

Environment-key filtering reduces accidental propagation; it is not an OS sandbox and does not prevent a same-user process reading files. Explicit llama-server inbound authentication is not a provider credential. No secret values are logged by the new tests or policy.

SeDebugPrivilege is not newly granted: Windows can only enable a privilege already present in the operator token. Failure to enable, restore, query, validate, terminate, or wait does not authorize a PID fallback. Operator PowerShell sessions carrying the old in-memory Add-Type definition must be restarted rather than silently using the previous policy.
