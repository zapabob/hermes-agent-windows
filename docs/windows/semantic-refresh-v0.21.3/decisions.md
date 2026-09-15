# Decisions — windows-native-carry-v0.21.3

## Freeze

| Role | Exact SHA |
|---|---|
| D0_NEXT | `af685eba691784c703a5a19c3b2ffa0d741a6c39` |
| U_NEXT (peeled) | `345cd2b057a452236de401d3534b8502a7465e8d` (`v2026.9.14` / 0.21.3) |
| Tag object | `7a963716b81be13ba513d4f127633b7da493aff2` |
| U_PREV (prior campaign) | `6dd091a89c33e6e4909a80f78343bb384deb5ca8` (not overwritten) |
| H snapshot | `b51c055a12220f8c7c18660e8599365012e19532` (unchanged) |

`allow_upstream_sync: false` retained. Product SemVer synced to 0.21.3 with U_NEXT 0.21.3 (operator-approved sync during main deployment).

## Slice NC-0213-A — MCP / profile trust

| Contract | U carrier | D owner | Decision | Method |
|---|---|---|---|---|
| Same-name connection keys | ceaf622 / mcp_tool_scope | already on D0_NEXT | ALREADY_EQUIVALENT | KEEP |
| Adopter keeps own trust | e609efb | `tools/mcp_tool.py` | ADOPT | COMPOSE / REIMPLEMENT_NATIVE |
| Parallel opt-in per profile | 9d39267 | `tools/mcp_tool.py` | ADOPT | COMPOSE |
| mTLS in connection identity | bbe4089 | `tools/mcp_tool.py` | ADOPT | COMPOSE |
| OAuth never shared cross-profile | 399238f | `tools/mcp_tool.py` | ADOPT | COMPOSE |
| Refresh token issuer binding | d9e88e1 | `mcp_oauth*.py` | ADOPT | COMPOSE |
| U module split (`mcp_tool_*.py`) | U layout | monolith | KEEP_DOWNSTREAM | NONE |

**Must not:** second MCP supervisor, second credential SoT, force U module layout.

## Inherited residuals (prior campaign — do not overwrite)

See `docs/windows/semantic-refresh-2026-09-13/`. Residual IDs referenced, not closed by assumption.

## Explicit non-goals this phase

- main merge / push / Release / tag
- Desktop/Go rebuild / llama restart
- 24h soak, private security live, packaging
- post-tag upstream/main (`DEFER_POST_TAG`)
- MoA / model swap / HOLD unlock
