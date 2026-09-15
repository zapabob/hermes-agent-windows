# Receipt — NC-0213-A MCP/profile trust

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
| Tested SHA | *(fill after local commit)* |
| LOCAL_DEPLOYED | NOT_RUN |
| soak_24h | NOT_RUN |
| PRIVATE_SECURITY | NOT_RUN |
| main integration | NOT_DONE (isolation phase only) |

## Files touched

- `tools/mcp_tool.py` — mTLS/OAuth identity, per-profile trust + parallel, adopter trust
- `tools/mcp_oauth.py` — `hermes_issuer` storage helpers
- `tools/mcp_oauth_provider.py` — enforce/bind issuer + refresh carry
- `tools/mcp_oauth_manager.py` — enforce after metadata prefetch
- `tests/tools/test_mcp_multiplex_connection_keys.py` — expanded contracts
- `tests/tools/test_mcp_oauth_issuer_binding.py` — new

## Isolation limits

Worktree + env + synthetic HOME only. Not an OS security sandbox. Production stack untouched.
