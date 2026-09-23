# Control MCP legacy Router retirement map (T02)

## Scope and source

Repository: zapabob/hermes-agent-windows. This bounded task records what the old Implementation Router and adjacent Control MCP surfaces own, which pieces remain shared, and the gates required before replacement. The isolated task branch is `codex/t02-retirement-20260924`, based on `dbca4d19cf3c91fb39f7e123eb0829e5118ab088` with tree `ba2198bd79dc8640abda5f1ea7553e77dcd0fbea`. The user's original checkout, recovered integration worktree, main, remote refs, and endpoint/client settings were not modified.

The canonical PC prompt, project guidance and applicable Implementation Start, Common, Security, Python, Application Development and LLMOps SOPs were read before edits. The attached workstation plan and its CodeGraph protocol were used. No Router source, workflow, dependency, client grant, or runtime setting was changed.

## Inventory decision

`docs/windows/workstation-20260924/retirement-map.json` records 104 existing file paths: 21 KEEP, 39 REPLACE_AFTER_PARITY, and 44 SHARED_RETAIN. Separately, it marks the new Control MCP operation `hermes_start_engineering_run` as RETIRE_ENTRY: it remains absent, its write capability remains false, and calls are rejected. The legacy plugin `engineering_run` and `/engineer` stay available only as the existing opt-in plugin surface until general Hermes subagent parity and migrated consumers are demonstrated; the map does not authorize their removal now.

The inventory keeps the generic provider/model assignment and auxiliary-client owners, Hermes human approval owner, credential-free environment helpers, Docker execution boundary, ordinary MCP host/auth implementation, and unrelated CI/history. It treats environment filtering as insufficient proof of OS-level worker isolation. Control MCP receipt observation still imports digest/source helpers from the legacy plugin workspace module; those readers and historical receipts must be migrated before that module can retire. Package metadata and `uv.lock` remain shared because they also carry Control MCP/runtime dependencies and pinned dependencies; future cleanup must be narrowly audited after parity.

Parity gates are written in the map. They include native Windows credential/handle/SSH isolation for worker, child and grandchild; Hermes-owned exact-once approval; targeted cancel/recovery; real producer evidence; preservation of the Docker fail-closed boundary; migration of fixed-role UI, locale, docs, package-data, tests, and old-only checks; and required checks at exact integration HEAD. No gate is reported as already proven by this T02 inventory.

## TDD and direct checks

No meaningful new assertion was added because `tests/control_mcp/test_mcp_protocol.py::test_retired_engineering_tool_is_absent_even_with_legacy_coordinator` already provides the exact negative behavioural contract on the task base. On the real MCP SDK client it verifies tool absence despite an inert legacy coordinator, false general/start capability, and rejection when the retired tool is called. It passed on the unmodified source base before the map was edited and was re-run after the inventory work. Thus T02 records an existing GREEN baseline and deliberately claims no new RED/GREEN code implementation cycle; the earlier missing pytest in the base environment was environment setup, not a behavioural RED.

The file inventory was checked for unique paths, existing tracked files, valid disposition/group references and resolvable test paths. The associated existing test is the direct runtime check; CodeGraph's empty symbol lookup alone is not used to claim runtime absence.

## CodeGraph evidence and limits

The approved @colbymchenry/codegraph 1.6.0 CLI was used on the isolated task worktree. The before receipt and query summary are `evidence/codegraph/T02-dbca4d19-before.json` and `evidence/codegraph/T02-dbca4d19-before-summary.md`; the after receipt and summary are `evidence/codegraph/T02-dbca4d19-after.json` and `evidence/codegraph/T02-dbca4d19-after-summary.md`. Receipts use a stable task-worktree identity and contain no account-specific filesystem paths. Static queries and impact paths helped map legacy and shared owners, but cannot establish plugin auto-discovery at runtime, operating-system isolation, or real Codex/ChatGPT client behaviour.

## Residual work

This task does not establish subagent credential isolation, real desktop client authentication/read/write, real approval UI parity, native Docker end-to-end parity, final integrated required checks, security review, PR merge, or post-merge CI. Legacy Router modules remain in place until those replacement gates pass. Reversal is a revert of the inventory/evidence commit; no runtime rollback is necessary because runtime configuration did not change.
