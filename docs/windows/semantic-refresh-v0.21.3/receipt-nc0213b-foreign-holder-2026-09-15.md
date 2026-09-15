# Receipt — NC-0213-B state.db foreign-holder repair preflight

| Field | Value |
|---|---|
| Slice | NC-0213-B |
| Campaign | windows-native-carry-v0.21.3 |
| U_NEXT | `345cd2b057a452236de401d3534b8502a7465e8d` |
| Decision | ADOPT (partial) |
| Method | COMPOSE / REIMPLEMENT_NATIVE into `hermes_state.py` (no `hermes_state_holders.py` port) |
| Contracts | ANY foreign holder blocks repair preflight; holder paths use `realpath`; Windows scan remains `[]` |
| ALREADY_EQUIVALENT | shared acquire/generation (`test_shared_session_db_native` 7p) |
| SKIP | virtiofs/9p WAL refuse (Linux `/proc/mountinfo`; U skips non-Linux) |
| Command | `python -m pytest tests/hermes_state/test_foreign_holder_repair_preflight_native.py tests/hermes_state/test_shared_session_db_native.py -q` |
| Result | **10 passed, 1 skipped** |
| LOCAL_DEPLOYED | NOT_RUN |
| soak_24h | NOT_RUN |
| PRIVATE_SECURITY | NOT_RUN |
| main integration | NOT_DONE |

## Files

- `hermes_state.py` — `foreign_state_db_holders`, realpath canonicalization, `_live_writer_holds_db` fail-closed on holders
- `tests/hermes_state/test_foreign_holder_repair_preflight_native.py` — new
