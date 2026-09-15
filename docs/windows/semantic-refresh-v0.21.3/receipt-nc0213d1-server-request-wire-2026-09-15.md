# Receipt — NC-0213-D1 Desktop/Gateway server→client wire

| Field | Value |
|---|---|
| Slice | NC-0213-D1 |
| Campaign | windows-native-carry-v0.21.3 |
| U_NEXT | `345cd2b057a452236de401d3534b8502a7465e8d` |
| U commits | `ebe8cda8ea`, `9f7f2f28c0`, `d4840f9236` / contracts fan-out |
| Decision | ADOPT |
| Method | REIMPLEMENT_NATIVE / COMPOSE into existing Windows owners (no Pydantic `tui_gateway/contracts` copy) |
| Contract | `srq-*` server→client JSON-RPC requests; same-socket respond; stale id drop; session-scoped cancel + `request.cancel`; `open_requests` on resume / events.since |
| Command | `python -m pytest tests/tui_gateway/test_server_requests_wire.py -q` |
| Result | **5 passed** |
| Exact tested SHA | `c272a2a3e9f89d3eacc89db4ace5d9492d8df20c` |
| LOCAL_DEPLOYED | NOT_RUN |
| main integration | NOT_DONE |

## Files

- `tui_gateway/server_requests.py` (new; allowlist instead of contracts registry)
- `tui_gateway/server.py` — bind_sinks, dispatch response frames, `_clear_pending` cancel, `_open_requests` on live resume payload
- `tui_gateway/methods_session.py` — `session.events.since` includes `open_requests`
- `apps/shared/src/json-rpc-gateway.ts` — `onRequest` / `deliverRequest` / open_requests replay
- `apps/desktop/src/store/server-requests.ts` (new)
- `apps/desktop/src/store/gateway.ts` — secondary `onRequest` → `onServerRequest`
- `tests/tui_gateway/test_server_requests_wire.py`
- `apps/shared/src/json-rpc-gateway-server-request.test.ts` (needs workspace vitest install to run)

## DEFER (same campaign, not post-tag)

- Full `_block` cutover from `*.request` events to `server_requests.send` (legacy path still owns clarify/sudo/secret until desktop `handleServerRequest` ports all methods)
- Full U desktop `gateway-event/server-requests.ts` handler matrix (tour/preview/vault/…)
- Generated OpenRPC / Pydantic contracts package

## Invariants held

- Stale/late response frames dropped
- Interrupt cancels only the target session's open requests
- Answers use the same transport (JSON-RPC response id)
- Go Watchdog not involved; prompt cache untouched
- Desktop/backend/Gateway lifetime separation unchanged
