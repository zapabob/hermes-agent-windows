# Owner map — semantic refresh 2026-09-13

Navigation evidence only (CodeGraph 1.6.0). Not execution proof.

## Index coverage

| Tree | Path | Revision | Files | Nodes | Edges | DB |
|---|---|---|---:|---:|---:|---|
| D1 (=D0 at branch create) | `.worktrees/semantic-refresh-d1` → junction `H:\hermes-codegraph\...\d1` | `7c697a8a658d4ceadb80276f37b90cd93d84d6a9` | 8773 | 188304 | 602017 | ~598 MiB |
| U | `.worktrees/semantic-refresh-u` → junction `H:\hermes-codegraph\...\u` | `6dd091a89c33e6e4909a80f78343bb384deb5ca8` | 9637 | 217260 | 674002 | ~660 MiB |

CLI: `.tools/codegraph-cli/.../codegraph.cmd` **1.6.0** (matches approved pin). Commands confirmed: `init/sync/status/query/explore/impact/callers/callees/affected`.

C: disk was ~3 GB free; indexes live on **H:** via directory junctions. First C:-local init failed with `database or disk is full` (recorded, recovered).

## Critical owners (D1 queries)

| Symbol | Kind | Path | Notes |
|---|---|---|---|
| `SessionDB` | class | `hermes_state.py` | state/FTS owner |
| `CredentialPool` | class | `agent/credential_pool.py` | credential lease owner |
| `WinPtyBridge` | class | `hermes_cli/win_pty_bridge.py` | Windows PTY |
| `_get_hermes_config_resolved` | function | `tools/file_tools.py:686` | **memoized on D0** — security gap vs U |
| `get_hermes_home` | function | `hermes_constants.py` | profile-aware home |
| Watchdog structs | Go | `scripts/windows/watchdog-go` | outer restart authority |

### Impact: `_get_hermes_config_resolved` (D1, depth=2)

Callers: `_check_sensitive_path` → `write_file_tool` / `patch_tool`. Tests: `tests/tools/test_file_write_safety.py`, `tests/tools/test_file_tools.py`.

U moves the same symbols into `tools/file_tools_write_guards.py` (module split). Downstream COMPOSE keeps owner in `tools/file_tools.py` for this campaign slice (no second module unless required).

## Dynamic edges (static graph incomplete)

- Plugin `register()` / decorator registration
- Gateway multiplex `HERMES_HOME` ContextVar per turn
- Electron↔Python JSON-RPC
- Go Watchdog process spawn/claim

Unresolved edges must be closed with file read + runtime tests, not CodeGraph alone.
