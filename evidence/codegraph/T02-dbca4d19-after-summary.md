# T02 CodeGraph after-change summary

## Snapshot

The retirement map and implementation record are committed on `codex/t02-retirement-20260924` at source SHA `9add308fbba43c7b99c798c6b07d4b0e595dbc60`, tree `9b50de2fc287a8f12a7acc2dcc5cf5e5832a739a`. The tracked worktree was clean when checked. Source fingerprint is SHA-256 of the UTF-8 string `git-tree-sha256-input:v1:<tree SHA>`, yielding `2d8183b71acb923ca434bbd73f76dc6ca358143b862a15d5d454b8b23ccae88f`.

Tool: approved bundled @colbymchenry/codegraph 1.6.0 executable, CLI. A post-commit sync reported `Already up to date`; status reported 8,900 files, 190,393 nodes, 609,292 edges, and index current. Query/impact commands below ran against this source SHA. The query paths omit the local worktree location.

## Executed queries

## Q1

`query -l 60 --json implementation_router`: 34 matches. Results include legacy Router files, imports connecting the plugin entrypoint/host to downstream kernel/routes/security/i18n, and legacy tests.

## Q2

`query -l 30 --json hermes_start_engineering_run`: zero static symbol matches. Static absence is not runtime evidence; the SDK test below is the direct negative check.

## Q3

`impact -d 4 --json ImplementationRouter`: 51 nodes / 51 edges, including plugin registration/control, kernel/host workflow, legacy tests and evidence consumers.

## Q4

`impact -d 4 --json NativeEngineeringHost`: 32 nodes / 47 edges, including host stage/verify/receipt paths and diagnostics, reasoning, E2E and MCP evidence tests.

## Q5

`query -l 25 --json plugin_llm`: 9 matches including the shared `agent/plugin_llm.py`, generic task-routing/reasoning tests, and strict auxiliary route tests.

## Q6

`query -l 25 --json auxiliary_client`: 25 matches including the shared `agent/auxiliary_client.py`, broad provider tests, and non-Router consumers such as compression and vision.

## Q7

`query -l 25 --json credential_free`: 18 matches including `tools/environments/credential_free.py`, its Docker boundary use, Router admission use, and shared credential-free/Docker tests.

## Direct behavioural check and scope

After the inventory commit, `uv run --frozen --extra dev python -m pytest tests/control_mcp/test_mcp_protocol.py::test_retired_engineering_tool_is_absent_even_with_legacy_coordinator -q` passed: 1 passed in 12.97s. This is the existing real MCP SDK no-resurrection gate; no duplicate test or implementation assertion was added by T02.

The inventory contains 104 tracked unique paths, and disposition/group/test references resolve. The CodeGraph query for the retired MCP name is only a static lookup. Dynamic plugin auto-discovery, worker process credential/handle isolation, actual desktop-client auth/read/write, live Docker execution, and full integration CI remain outside T02 and are not claimed as passed.
