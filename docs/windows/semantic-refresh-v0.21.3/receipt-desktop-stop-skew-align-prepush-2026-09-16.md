# Receipt — DESKTOP_STOP + skew-align pre-push gate (Cursor)

| Field | Value |
|---|---|
| Candidate HEAD | `000726248346831375de88ab4236257324f008dc` |
| Parent (origin/main before push) | `951dad8f8f2ef51a031c7327b7f377b1b5ce434f` |
| Product SemVer | **0.21.3** |
| `allow_upstream_sync` | **false** |
| Ran at | `2026-09-16T01:12:53+09:00` |

## Results

| Lane | Result |
|---|---|
| DESKTOP_STOP vitest (`desktop-restart-lifecycle` + `watchdog-stop-fence`) | **11 passed** |
| NC-0213 A/B/C/D focused pytest | **64 passed, 1 skipped** |
| Windows-native affected pytest | **321 passed** |
| Go `watchdog-go` `go test ./...` | **ok** (43.1s) |
| Electron `tsc -p tsconfig.electron.json --noEmit` | **exit 0** |
| Policy/carry | **POLICY_CARRY_OK** (24 entries, version 0.21.3, allow_upstream_sync false) |

## Production vs DIAG

- **Included:** DESKTOP_STOP lifecycle identity commit only (already on local main).
- **Excluded:** diag worktree DIAG_RPC / BE_ADOPT / instance-id (not merged).

## Verdict

**PRE_PUSH_GATE_PASS** → normal `git push origin main` (no force).
