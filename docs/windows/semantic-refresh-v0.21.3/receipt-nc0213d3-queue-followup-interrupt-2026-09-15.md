# Receipt — NC-0213-D3 queue / follow-up / interrupt ordering

| Field | Value |
|---|---|
| Slice | NC-0213-D3 |
| Campaign | windows-native-carry-v0.21.3 |
| U_NEXT | `345cd2b057a452236de401d3534b8502a7465e8d` |
| Decision | ADOPT |
| Method | COMPOSE into existing Windows owners (`gateway/run.py`, `ssh-bootstrap-coordinator.ts`) |
| Contract | Queued follow-up fires `on_processing_start`/`complete` hooks (#72502); `cancelAndWait(scope, afterCancel?)` composes drains so replacement `start()` cannot race teardown |
| Command | `python -m pytest tests/gateway/test_queued_followup_processing_hooks.py -q` |
| Result | **5 passed** |
| Exact tested SHA | _(stamped on commit)_ |
| LOCAL_DEPLOYED | NOT_RUN |
| main integration | NOT_DONE |

## U_NEXT existence check

- `gateway/run_turn_followup_ack.py` present at U_NEXT
- `ssh-bootstrap-coordinator.ts` `cancelAndWait` compose + `afterCancel` present at U_NEXT
- No post-tag-only contract mixed in

## Files

- `gateway/run_turn_followup_ack.py` (new; COMPOSE from U)
- `gateway/run.py` — in-band queued follow-up wraps `_run_agent` with start/complete/cancel hooks; preserves history offset
- `apps/desktop/electron/ssh-bootstrap-coordinator.ts` — composed drain + `afterCancel`
- `apps/desktop/electron/ssh-bootstrap-coordinator.test.ts` (synced cancelAndWait cases from U; vitest deferred if workspace deps missing)
- `tests/gateway/test_queued_followup_processing_hooks.py`

## Invariants held

- Human input / completion / follow-up ordering preserved (hooks mirror idle-session path)
- Stale generation cannot resurrect mid-drain (`cancelAndWait` barrier)
- Active turn double-submit not introduced
- Go Watchdog not a task owner
- Prompt cache: `_refresh_agent_cache_message_count` before recursive `_run_agent`
- Desktop/backend/Gateway lifetime separation unchanged
