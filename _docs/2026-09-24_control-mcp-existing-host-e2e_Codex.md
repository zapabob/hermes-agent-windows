# Hermes Control MCP T03: existing-host integration

Date: 2026-09-24 JST
Repository: `zapabob/hermes-agent-windows`
Task branch: `codex/control-mcp-t03-host-20260924`
Task worktree: `task-worktree/codex-control-mcp-t03-host-20260924`
Exact starting HEAD: `dbca4d19cf3c91fb39f7e123eb0829e5118ab088`

## Scope and decision

This task qualified the existing Hermes FastAPI parent host with the locked MCP SDK. `transport.mount_control_mcp(web_server.app, host)` already supplies the needed opt-in installation path, and `web_server._lifespan` enters the mounted SDK session manager. The actual parent middleware correctly marks only the exact MCP resource routes for the dedicated resource verifier. The real-host test passed without a `web_server.py` change, so no redundant product wrapper or startup configuration was added.

The test mounts only an in-process, ephemeral test host. It does not set a production endpoint, issuer, registration grant, account setting, public bind, or tunnel. Actual Codex Desktop/ChatGPT Desktop/Web auth and client acceptance remain unverified pending separately approved resource configuration and real clients.

## Behaviour evidence

`tests/e2e/test_control_mcp_host.py::test_real_hermes_parent_serves_two_scoped_clients_without_read_side_effects` uses `web_server.app`, its actual middleware stack and lifespan, `HermesObservations`, `HostControlService`, `AuthenticatedControlASGI`, the locked `mcp==2.0.0` client, and `httpx2==2.12.0` ASGI transport. Two independent RS256 test identities receive separate profile grants and read different configured route-effort snapshots. A cross-profile read is denied. Configured effort is reported as configuration only; sent/provider-reported routes remain unknown. The runtime producer reports `ABSENT` for a missing status file rather than opening or creating state.

The same test confirms write capability is false and no engineering-start tool is registered. A dashboard session-token-only request receives resource-auth `401 invalid_token`. Invalid Origin is rejected with 403; the MCP host allowlist returns 421; and the real parent Host policy rejects a different bound hostname with 400. OAuth protected-resource metadata is served through the parent route without a dashboard cookie. SDK client contexts close cleanly; the stateless manager retains no server instances and the parent lifespan leaves the SDK task group stopped. Test homes contain only the pre-existing `config.yaml` files after reads.

To make unexpected work fail during the read sequence, the test blocks config hydration/secret expansion, socket connections, and process creation. That covers the tested boundary for DB/vault/config hydration, OAuth/provider network activity, inference endpoints, and Docker/scanner subprocesses. The real Hermes profile database or vault is never opened. Unrelated normal Hermes startup DB reconciliation, security-watch resume, security-definition update and gateway import are mocked so this is a focused existing-host test rather than an ordinary operator startup.

This is host/protocol proof with synthetic in-memory issuer keys and grants. It is not live-client authentication, production endpoint qualification, operator approval UI qualification, or an approved write. No production config or live credential was used.

## RED/GREEN and test setup record

The new test was added before any product changes. Its first invocation exposed test-environment setup problems only: the E2E conftest requires the locked `all` extra (`aiohttp`), and `control_module` is local to the `tests/control_mcp` tree rather than visible under `tests/e2e`. Both were corrected using frozen extras and direct module imports. A later teardown error exposed that the test had restored `web_server.app.state` before `monkeypatch` cleanup; state restoration was changed to a complete pre-test snapshot and the error disappeared.

There was no behavioural RED: the recovered source already contained a safe mount and parent-lifespan seam. The first complete assertion run passed on unchanged product code. This task therefore adds characterization and runtime evidence for an existing integration instead of asserting an unnecessary host-factory change. The initial setup/teardown errors are not recorded as security or behavior test failures.

## Verification

Frozen test environment: `uv run --frozen --extra all --extra dev`. No dependency or lockfile was changed.

`uv run --frozen --extra all --extra dev ruff check tests/control_mcp/test_host_mount.py tests/e2e/test_control_mcp_host.py`: passed.

`uv run --frozen --extra all --extra dev python scripts/run_tests_parallel.py -j 2 tests/control_mcp tests/e2e/test_control_mcp_host.py -q`: 13 files, 182 passed, 0 failed, 1 skipped. The skip belongs to the existing Control MCP suite; it is not counted as a successful check.

## CodeGraph

Approved `@colbymchenry/codegraph` CLI 1.6.0 was initialized once in this task worktree at the exact starting HEAD. No full reindex was performed. Before edits it was current at 8,899 files, 190,393 nodes and 609,292 edges. After the two test-file edits, `sync .` processed one added and one modified file; final status is current at 8,901 files, 190,415 nodes and 609,338 edges.

The final `query mount_control_mcp` points to `downstream/control_mcp/transport.py:109`. Its static impact still reports only the existing protocol tests because it does not resolve the E2E test's `importlib` imports. `_lifespan` impact shows 53 nodes / 52 edges and includes the strengthened real-parent lifespan test. `_token_auth_seam` resolves to `hermes_cli/web_server.py:1092`. These are navigation receipts; the E2E supplies the direct ASGI and SDK evidence for dynamic dispatch.

Machine-readable receipts: `evidence/codegraph/T03-dbca4d19-before.json` and `evidence/codegraph/T03-dbca4d19-after.json`.

## Commit/review boundaries

Only the two host integration tests, this task log and its CodeGraph receipts are in scope. `hermes_cli/web_server.py` remains unchanged because the existing route mount and lifecycle were proven sufficient. No actual Desktop or hosted ChatGPT client auth/read/write was attempted; no production grants or endpoints were created. T03 real-client auth, approved-write qualification, exact final-head CI and independent security review remain release blockers outside this bounded host-test task.
