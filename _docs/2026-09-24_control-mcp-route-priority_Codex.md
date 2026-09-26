# Control MCP route priority on the recovered host

## Scope and requirements

Repository: zapabob/hermes-agent-windows. Recovered integration branch at predecessor ebe05b1a397cf3855b36f84c60841abc9f2d7ce2. This is a bounded T03 change: registering the authenticated SDK resource after an existing SPA catch-all must still route exact MCP paths to the MCP boundary. Other application paths must keep their existing handler. It does not activate a production endpoint or grant a client.

PC baseline, canonical pre-implementation prompt, Implementation Start Gate, Security, Application Development, LLMOps and Python SOPs were read. The hermes-agent and executing-plans skills were applied. CodeGraph protocol from the 2026-09-24 plan was used; the approved 1.6.0 CLI is in the main checkout's .tools directory. The PATH global 1.5.0 CLI refused Node 26 and was not used for evidence.

## Decision and change

CodeGraph at the recovered predecessor reported 8,900 files and an up-to-date index. Query/node/impact of mount_control_mcp found downstream/control_mcp/transport.py as owner and tests/control_mcp/test_mcp_protocol.py as a caller. Static impact did not model the FastAPI catch-all's dynamic route precedence; the SDK test supplies that direct evidence.

The resource mount now moves only its three newly added exact routes to the front of the parent's route list. Existing route conflict checks remain. This permits an already-registered SPA fallback while leaving unrelated paths on their original handler. Files changed: downstream/control_mcp/transport.py and tests/control_mcp/test_mcp_protocol.py. Sanitised before/after graph receipts are evidence/codegraph/T03-ebe05b1-before.json and T03-ebe05b1-after.json. After sync, CodeGraph reported 2 changed files and up-to-date status; impact included the new test and the older parent middleware test.

## RED and GREEN

RED: uv run --frozen python -m pytest tests/control_mcp/test_mcp_protocol.py::test_late_parent_mount_precedes_existing_spa_catch_all -q returned 1 failed. The actual MCP SDK client received the SPA JSON for /api/control/mcp, so JSON-RPC initialization failed. This was a behavioural assertion, not an import error.

GREEN: the same SDK test and the existing parent mount test returned 2 passed in 3.60s. The affected suite command uv run --frozen python -m pytest tests/control_mcp tests/test_mcp_serve.py -q returned 256 passed, 1 skipped in 25.24s. uv run --frozen ruff check downstream/control_mcp/transport.py tests/control_mcp/test_mcp_protocol.py passed.

## Trust boundary and residual risk

The route remains behind the dedicated resource verifier. No dashboard session token, legacy ACK or model call is added. The normal serve process still lacks operator-approved issuer/client grants and startup construction, so actual Codex Desktop and ChatGPT Desktop authentication/read remains unverified. The wider T03 side-effect-free read proof, T04 write authority, native worker boundary, exact final-head CI, independent review and deployment remain open. The change is reversible by reverting this logical commit; no production configuration was changed.
