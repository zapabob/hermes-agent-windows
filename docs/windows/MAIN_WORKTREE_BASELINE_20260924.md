# Hermes Windows workstation main baseline

Captured 2026-09-24 (Asia/Tokyo) before continuing the frozen-upstream v0.21.4 semantic adoption and Hermes Control MCP implementation.

## Git state

- Repository: `zapabob/hermes-agent-windows`
- Branch: `main`
- Local `HEAD` and freshly fetched `origin/main`: `e6070028c9d0d75634ad7661c33fa937b682474a`
- `git rev-list --left-right --count origin/main...HEAD`: `0 0`
- `git status --porcelain=v2 --branch`: `main` tracks `origin/main`; no staged, modified, or untracked files.

The main checkout was already clean and equal to the fetched remote. The inspection did not delete, move, stash, clean, or prune repository files or linked worktrees. Existing work in other worktrees remains preserved.

## CodeGraph state

Pinned `@colbymchenry/codegraph@1.6.0 status` reported 9,520 files, 204,198 nodes, 654,306 edges, and an up-to-date index.

## Scope of this record

This is a starting-state receipt only. It does not claim product implementation, test, security review, real-client, runtime, or release-gate completion.

## Locked dependency and focused baseline checks

At source HEAD `8660c9343fc7e8c157720b379080ebde2fb0bc3a`, `uv lock --check` completed successfully with 256 locked packages resolved. The configured Windows virtual environment reported Python 3.11.11.

Command:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider -rs tests/downstream/test_upstream_windows_semantic_contracts.py tests/agent/transports/test_hermes_tools_mcp_server.py tests/downstream/test_windows_contracts.py
```

Result: 51 passed, 1 skipped in 5.05 seconds. The skip is `tests/downstream/test_upstream_windows_semantic_contracts.py:103`, whose POSIX PTY import requires `fcntl`; Windows uses `WinPtyBridge`. This is a focused existing-contract baseline, not a complete repository or Control MCP acceptance run.
