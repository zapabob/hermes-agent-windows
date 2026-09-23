# Hermes MCP and legacy engineering router retirement specification

Status: implementation contract, 2026-09-24 JST. Scope: `zapabob/hermes-agent-windows` only.
Base: `origin/main` `e6070028c9d0d75634ad7661c33fa937b682474a` (#143 and #144 merged).
Continuation branch before this specification: `aa145e3ae9d02134741b310f2fdd8aa244c15927`.

## Decision and boundary

Retire the opt-in fixed planner/worker/reviewer actor and its Docker-specific workflow as a product surface. Keep generic Hermes model selection, strict provider routing, profile isolation, approvals, credential-free launch helpers, Docker backend, and MCP authentication. Build a general Hermes MCP resource around the existing Hermes host and its normal session/delegation authorities. Historical router receipts remain read-only and labelled legacy until their last consumer is migrated. There is no new Codex SDK, App Server, provider store, scheduler, or model catalogue.

This changes the earlier Control MCP plan for Tasks 4–8. An operation named `start_engineering_run` must not be presented as the new general Hermes task. Existing `delegate_task` cannot be exposed as the replacement: `tools/delegate_tool.py` currently passes `effective_api_key` and a credential pool to child AIAgents. A new parent-brokered, credential-free subagent mode must first prove that worker, child and grandchild receive no MCP/LLM/Git token, authenticated client, credential file, inherited handle or SSH socket. A clean environment alone is insufficient OS isolation. Until that mode and its real host authority are proved, general task execution over the new MCP resource remains unavailable. Existing Hermes delegation outside this resource is outside this retirement change.

The old `mcp_serve.py` stdio messaging bridge is not the authenticated general-control transport. In particular, its `permissions_respond` records a bridge ACK; it never supplies Hermes human approval. Do not mount or proxy that bridge on the new Streamable HTTP resource. Mutations use a digest-bound Hermes approval in the existing Desktop/TUI queue, one bounded intent per decision. No MCP tool can approve itself.

Codex local reachability and hosted ChatGPT reachability are separate. Do not change account settings, expose an endpoint, create a tunnel, or relabel writes as reads under this specification. Actual ChatGPT client capabilities are measured per client; documentation currently lists custom MCP apps on web and Pro read/fetch limits, so desktop or Pro write is not assumed.

## File disposition for #143/#144 and the continuation

`KEEP` means preserve the generic behaviour and its tests. `MIGRATE` means remove only the old-router dependency after its new owner and tests exist. `RETIRE` means remove the named legacy product file once no runtime import remains. `LEGACY READ` means retain bounded read compatibility for existing receipts, without new writes.

| File or exact group | Disposition | Required action |
| --- | --- | --- |
| `agent/auxiliary_client.py` | KEEP | Retain strict `allow_fallback`, expected-route and effort forwarding; test against generic auxiliary slots. |
| `agent/plugin_llm.py` | KEEP | Retain parent-owned inference and #144 effort forwarding; no new authentication store. |
| `apps/desktop/src/app/settings/model-settings.tsx`, `apps/desktop/src/types/hermes.ts` | KEEP | Retain dynamic plugin auxiliary slots. Remove only retired router-specific labels/fixtures. |
| `apps/desktop/src/app/settings/model-settings.test.tsx` | MIGRATE | Replace engineering-slot fixture with a generic registered plugin slot; retain dynamic-picker regression. |
| `apps/desktop/src/i18n/en.ts`, `ja.ts`, `zh.ts`, `zh-hant.ts`, `ar.ts` | MIGRATE | Remove obsolete fixed-role copy, keep unrelated translations and key parity. |
| `apps/desktop/src/i18n/engineering-routing.test.ts` | RETIRE | Replace with general MCP/subagent copy tests if such UI is added. |
| `hermes_cli/web_server.py` | KEEP | Keep `_auxiliary_picker_slots` and profile-scoped registration. Remove no generic auth/model functionality. |
| `tests/hermes_cli/test_web_auxiliary_plugin_slots.py` | MIGRATE | Use a generic fake plugin registration, retaining profile/secret-redaction assertions. |
| `tests/agent/test_auxiliary_strict_route.py`, `tests/agent/test_plugin_llm_reasoning.py` | KEEP | Keep strict route and request-effort contracts. |
| `tools/environments/credential_free.py`, `tools/environments/docker_isolation.py` | KEEP | Preserve opt-in credential-free primitives; their existence does not prove a subagent boundary. |
| `tools/environments/docker.py`, `tools/terminal_tool.py` | KEEP | Preserve native backend and scoped credential-free binding; no general Docker requirement for MCP reads. |
| `tests/tools/test_bound_credential_free_environment.py`, `tests/tools/test_credential_free_docker.py`, `tests/tools/test_discord_tool.py` | KEEP | Retain generic isolation and compatibility tests. |
| `agent/engineering_diagnostics.py` | RETIRE | Only old actor/host imports use it. A future generic diagnostic needs a separate owner and tests. |
| `downstream/implementation_router/AGENTS.md`, `kernel.py`, `routes.py`, `security.py`, `i18n.py`, `locales.json` | RETIRE | Remove fixed-stage protocol after all imports are cut; preserve history in Git. |
| `plugins/implementation_router/__init__.py`, `plugin.yaml`, `README.md`, `actors.py`, `configuration.py`, `entrypoint.py`, `host.py`, `control.py` | RETIRE | Remove old `/engineer` and `engineering_run` registration and native workflow; do not silently map their arguments to a new task. |
| `plugins/implementation_router/workspace.py` | MIGRATE | Move bounded path/digest and safe export checks needed by legacy receipts or future apply to a neutral owner before deleting this module. |
| `docs/implementation-router/AGENT_PROTOCOL.md`, `STATUS.md`, `i18n/en.md`, `ja.md`, `zh.md`, `zh-hant.md`, `ar.md` | RETIRE | Replace with this retirement record and current general MCP documentation. |
| `.github/workflows/engineering-router.yml`, `.github/workflows/implementation-router-contract.yml` | RETIRE | Remove old-only workflows after a general MCP CI gate covers their security-relevant contracts. |
| `.github/workflows/ci.yaml` | MIGRATE | Remove only old-router job hooks; retain all unrelated required jobs and protection rules. |
| `scripts/ci/implementation_router_sabotage.py`, `isolated_subprocess_env.py`, `qualify_implementation_router.py`, `engineering_repair_mutations.py` | MIGRATE | Retain any reusable isolated-runner helper under a neutral name; retire old-only qualification/mutation programs once new negatives exist. |
| `tests/implementation_router/test_kernel.py`, `test_route_admission.py`, `test_security_contract.py`, `test_i18n_docs.py` | RETIRE | Replace security assertions with general MCP/subagent tests before removal. |
| `tests/plugins/test_engineering_workflow.py`, `test_engineering_reasoning.py`, `test_engineering_diagnostics.py`, `tests/e2e/test_engineering_native_docker.py` | RETIRE | Keep generic inference checks in agent tests; replace live Docker test with a credential-free subagent test before claiming write support. |
| `pyproject.toml`, `uv.lock` | MIGRATE | Remove router-only package data and dependency changes only after lock diff review; keep pinned shared dependencies. |
| `_docs/carry-surface-20260826.json`, `_docs/carry-surface-20260826.md` | REGENERATE | Refresh with the repository-native generator after code changes, without manual metric edits. |
| `downstream/control_mcp/auth.py`, `contracts.py`, `http_boundary.py`, `transport.py`, `host_context.py` | KEEP | Retain resource-only auth, strict protocol, profile-bound context and parent lifespan; rename public instructions for general Hermes. |
| `downstream/control_mcp/journal.py`, `coordinator.py`, `service.py` | MIGRATE | Replace old start kind with bounded general-task intents; preserve idempotency, revocation and Hermes human decision rules. |
| `downstream/control_mcp/observations.py`, `projection.py` | MIGRATE / LEGACY READ | Add real general session/run/status projections. Isolate old engineering receipt reader as read-only legacy data, with no new producer claim. |
| `plugins/implementation_router/control.py` | RETIRE | Its `EngineeringRunOwner` is old workflow authority; do not reuse as a generic task owner. |
| `tests/control_mcp/*` | MIGRATE | Keep auth, protocol, journal and approval negatives; replace old owner/evidence expectations with general host and subagent evidence. |
| `docs/control-mcp/IMPLEMENTATION_LOG.md` | KEEP | Record old and new SHAs, RED/GREEN and changed acceptance criteria without rewriting history. |
| `mcp_serve.py`, `tests/test_mcp_serve.py` | KEEP AS LEGACY | Keep stdio messaging compatibility; do not equate `permissions_respond` ACK with human consent or mount it on HTTP. Its Windows same-tick mtime test currently fails and is a separate quality gate. |

## Ordered implementation and acceptance

1. Freeze this disposition and add a retirement inventory test that fails if a legacy entrypoint is still registered in the new MCP resource. Keep `main` and the original checkout untouched.
2. Build the general read facade from existing Hermes session, route and host producers. Reads must be profile/workspace scoped and must not create DBs, decrypt vaults, refresh OAuth, infer, start Docker or run scanners. Old receipts are visibly `LEGACY`.
3. Implement parent-owned task admission, a tokenless subagent worker and a narrow parent inference broker using existing Hermes model authority. The IPC must be capability-bound to one task and must not hand an authenticated client to the child. Preserve configured/sent/reported effort separately. Prove child/grandchild environment, handles, filesystem and network confinement on Windows and Docker where required.
4. Bind task start, targeted cancel and reverify to the existing strict Hermes approval queue and journal. Do not expose write flags until real host wiring and positive/negative MCP protocol tests pass. Keep Git apply/PR/merge as separately approved operations and authority, with no direct main push.
5. After replacement tests pass, retire each old file above in small commits; keep generic #143/#144 hunks by semantic review. Run full required exact-head checks and independent security review before a normal PR/merge. Post-merge CI and actual clients are separate observations.

Minimum acceptance: two different scoped clients see one host state and operation ID; unauthorized profile/workspace/empty-scope/dashboard token fail; one write waits for a real human `once` decision and cannot self-approve; retries never duplicate effects; worker descendants receive no credentials; source and verification evidence come from actual producers; Windows and Docker negatives pass. Codex Desktop and ChatGPT Web/Desktop authentication, read and approved write are recorded independently. An unavailable client capability remains unavailable, without a read-only disguise.

## Existing gate result at the design change

Commit `aa145e3ae9d02134741b310f2fdd8aa244c15927` added a bound native receipt/result-byte check for the old owner. It remains history, not proof of the new architecture. Focused tests: 37 passed, 1 skipped. The affected file-isolated run on that commit: 25 files, 579 passed, 1 failed, 3 skipped. The failing `tests/test_mcp_serve.py::TestEventBridgePollE2E::test_startup_baseline_suppresses_historical_replay` reproduced alone on Windows: `os.utime(..., None)` left the fixture mtime unchanged on that filesystem tick. A later test-only commit advances fixture mtime explicitly; its focused rerun passed. The earlier affected gate remains a recorded failure until rerun at the later HEAD.
