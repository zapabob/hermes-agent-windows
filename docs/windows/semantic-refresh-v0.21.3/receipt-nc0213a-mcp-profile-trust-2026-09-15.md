# Receipt  ENC-0213-A MCP/profile trust

| Field | Value |
|---|---|
| Slice | NC-0213-A |
| Campaign | windows-native-carry-v0.21.3 |
| Mode | selective_semantic + composed_windows_hardening |
| U_NEXT | `345cd2b057a452236de401d3534b8502a7465e8d` |
| D0_NEXT | `af685eba691784c703a5a19c3b2ffa0d741a6c39` |
| Decision | ADOPT (partial; same-name keys ALREADY_EQUIVALENT) |
| Method | COMPOSE / REIMPLEMENT_NATIVE into monolithic owners |
| OS | Windows 11 |
| Runtime | `.venv` Python 3.11; synthetic `HERMES_HOME` under `tmp/v0213-isolation/runtime/pytest-home` |
| Command | `python -m pytest tests/tools/test_mcp_multiplex_connection_keys.py tests/tools/test_mcp_oauth_issuer_binding.py tests/tools/test_mcp_trust_gating.py tests/tools/test_mcp_circuit_breaker.py -q` |
| Result | **31 passed** |
| Tested SHA | 71919dd15290f3b6f72f4a0a7fd8e5698ddb20f8 |
| LOCAL_DEPLOYED | NOT_RUN |
| soak_24h | NOT_RUN |
| PRIVATE_SECURITY | NOT_RUN |
| main integration | NOT_DONE (isolation phase only) |

## Files touched

- `tools/mcp_tool.py`  EmTLS/OAuth identity, per-profile trust + parallel, adopter trust
- `tools/mcp_oauth.py`  E`hermes_issuer` storage helpers
- `tools/mcp_oauth_provider.py`  Eenforce/bind issuer + refresh carry
- `tools/mcp_oauth_manager.py`  Eenforce after metadata prefetch
- `tests/tools/test_mcp_multiplex_connection_keys.py`  Eexpanded contracts
- `tests/tools/test_mcp_oauth_issuer_binding.py`  Enew

## Isolation limits

Worktree + env + synthetic HOME only. Not an OS security sandbox. Production stack untouched.
