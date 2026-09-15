# Receipt — NC-0213-C dashboard refresh single-flight

| Field | Value |
|---|---|
| Slice | NC-0213-C |
| Campaign | windows-native-carry-v0.21.3 |
| U_NEXT | `345cd2b057a452236de401d3534b8502a7465e8d` |
| U commits | `5dea46d13d`, `f561155a70` |
| Decision | ADOPT |
| Method | PORT/COMPOSE into `hermes_cli/dashboard_auth` |
| Contract | Same RT → one IdP exchange; cookie gate + native route share flight table; refresh off event loop |
| Command | `python -m pytest tests/hermes_cli/test_refresh_singleflight.py -q` |
| Result | **13 passed** |
| LOCAL_DEPLOYED | NOT_RUN |
| soak_24h | NOT_RUN |
| PRIVATE_SECURITY | NOT_RUN |
| main integration | NOT_DONE |

## Files

- `hermes_cli/dashboard_auth/refresh_singleflight.py` (new)
- `hermes_cli/dashboard_auth/request_utils.py` (new; scan helper)
- `hermes_cli/dashboard_auth/middleware.py` — coalesced + threadpool
- `hermes_cli/dashboard_auth/routes.py` — native refresh coalesced + threadpool
- `tests/hermes_cli/test_refresh_singleflight.py` (new)
