# T02 CodeGraph before-change summary

Snapshot: branch codex/t02-retirement-20260924, HEAD dbca4d19cf3c91fb39f7e123eb0829e5118ab088, tree ba2198bd79dc8640abda5f1ea7553e77dcd0fbea. The tracked working tree was clean. Source fingerprint is SHA-256 of the UTF-8 string git-tree-sha256-input:v1:<tree SHA>, yielding bf079bb3269d5d594824fb768982a4b17b4677601bda69cd29d65835bcf29711. Ignored task-local .codegraph and .venv are outside the Git tree.

Tool: approved bundled @colbymchenry/codegraph 1.6.0 executable, CLI. Initialised the isolated task-worktree index; status reported 8,900 files, 190,393 nodes, 609,292 edges and Index is up to date.

## Executed queries

## Q1

query -p <task-worktree> -l 60 --json implementation_router: found legacy plugin and downstream files, imports between plugin entrypoint/host and downstream kernel/routes/security/i18n, plus legacy tests.
## Q2

query -p <task-worktree> -l 30 --json hermes_start_engineering_run: returned an empty symbol result. This is only a static index result; it is not used as proof of runtime absence.
## Q3

impact -p <task-worktree> -d 4 --json ImplementationRouter: 51 nodes / 51 edges. The path includes downstream/implementation_router/kernel.py, plugins/implementation_router/entrypoint.py, plugin registration/control, tests/implementation_router/*, tests/plugins/test_engineering_diagnostics.py, tests/e2e/test_engineering_native_docker.py, and tests/control_mcp/test_evidence_provenance.py.
## Q4

impact -p <task-worktree> -d 4 --json NativeEngineeringHost: 32 nodes / 47 edges. The path includes host stage/verify/lease/receipt, entrypoint and plugin control, plus diagnostics/reasoning/E2E/evidence tests.
## Q5

query -p <task-worktree> -l 25 --json plugin_llm: found agent/plugin_llm.py and general agent tests including tests/agent/test_plugin_llm.py, test_plugin_llm_reasoning.py, test_plugin_llm_task_routing.py, and test_auxiliary_strict_route.py.
## Q6

query -p <task-worktree> -l 25 --json auxiliary_client: found the shared agent/auxiliary_client.py, its broad agent test owner, and non-router consumers such as conversation compression and vision.
## Q7

query -p <task-worktree> -l 25 --json credential_free: found tools/environments/credential_free.py, its use by docker_isolation.py and the legacy Router security module, and the bound-environment / Docker tests.

The initial three-query navigation was extended to separate old MCP-name lookup, kernel/host impact, and shared helper consumers because T02 explicitly requires each owner and its remaining consumer/test path. Results were reduced to paths/counts above; no source excerpts or raw query dump are published.

## Direct checks and unresolved scope

The existing real MCP SDK regression tests/control_mcp/test_mcp_protocol.py::test_retired_engineering_tool_is_absent_even_with_legacy_coordinator passed on this exact base. It confirms the retired name is absent from the registered tool list, general and start_engineering_run write capabilities are false despite an injected inert legacy coordinator, and calling the retired name is an MCP error. Direct source references also show the old plugin still has its separate Hermes plugin registration and old actor workflow. That legacy surface and its tests remain until replacement parity; this task does not claim they are removed.

Static CodeGraph does not prove plugin auto-discovery or live Codex/ChatGPT client behaviour. The real MCP SDK fixture is the direct no-resurrection check for this bounded task; the existing plugin remains outside the new MCP registration boundary.
