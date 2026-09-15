# Receipt — NC-0213-D promotion gate (A/B/C/D)

| Field | Value |
|---|---|
| Gate | NC-0213-D-PROMOTION |
| Campaign | windows-native-carry-v0.21.3 |
| Candidate tip SHA | `7b5592ef32372690a604e9d0a464ec760c9aeea7` |
| U_NEXT | `345cd2b057a452236de401d3534b8502a7465e8d` |
| Ran at | `2026-09-15T21:08:06+09:00` |
| main integration | **NOT_DONE** (gate only; no merge / prod restart) |
| LOCAL_DEPLOYED | NOT_RUN |

## Results

| Lane | Command | Result |
|---|---|---|
| A/B/C/D focused pytest | MCP×4 + foreign-holder×2 + refresh_singleflight + server_requests_wire + queued_followup_hooks | **64 passed, 1 skipped** |
| Windows-native affected pytest | watchdog_maintenance + watchdog_lifecycle + terminal_env_registry + hardline_blocklist | **321 passed** |
| Go affected | `go test ./...` in `scripts/windows/watchdog-go` | **ok** (41.2s) |
| Desktop electron typecheck | `tsc -p tsconfig.electron.json --noEmit` | **exit 0** |
| Targeted Electron claim policy | esbuild `backend-claim.ts` + node:test | **3 passed** |
| D2 tool-result summary | esbuild `tool-result-summary.ts` + node:test (failureDeclared / envelope) | **3 passed** |
| Downstream policy / carry | `CARRY.yaml` parse; `allow_upstream_sync: false` in baseline; `DOWNSTREAM_POLICY.md` Tier-1 Windows clause | **POLICY_CARRY_OK** (24 carry entries) |

## Residuals (non-blocking for this gate; not main)

| Item | Status |
|---|---|
| Full desktop `vitest run` / renderer `tsc -p tsconfig.json` | Blocked by worktree/root npm gap (`blobatar` missing from `node_modules`; pre-existing vs D diffs). Electron path + targeted node:test cover D1–D4 owners. |
| Full SSH vitest `ssh-bootstrap-coordinator.test.ts` | Same vitest/workspace gap; compose verified by source sync from U_NEXT + CodeGraph owner. |
| D1 shared vitest `json-rpc-gateway-server-request.test.ts` | Same; pytest wire suite green. |

## Slice SHA map (exact tested)

| Slice | Impl SHA |
|---|---|
| D1 | `c272a2a3e9f89d3eacc89db4ace5d9492d8df20c` |
| D2 | `409181b96936c482cf604ea8b80c0a5521953824` |
| D3 | `16d4bb398f2f0c60f97052d0ee1533047023a593` |
| D4 | `56898b81261f39451c23b9bc9393e3438c527fc9` |
| Gate tip | `7b5592ef32372690a604e9d0a464ec760c9aeea7` |

## Verdict

**PROMOTION_GATE_PASS** on candidate tip `7b5592ef32372690a604e9d0a464ec760c9aeea7`.

Do **not** merge to main or restart production until an operator explicitly requests that next step.
