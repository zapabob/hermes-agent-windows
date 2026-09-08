# Local change disposition — 2026-09-08

This ledger covers 88 local working-tree entries, not the full upstream-history campaign. The fixed comparison remains fork `20c7dd9d87fc6d0dc6b5cb2ed675e139b788be34` and upstream `6e2b8e070d28b1a3381a3fb290b6b8d6cce13cef`.

The 82 source/test entries were composed with the previously published Windows fixes in an isolated worktree. Byte-identical upstream files were not treated as proof of behavioural equivalence. Original working and staged states are retained locally before deployment.

| Path | Initial classification | Disposition |
| --- | --- | --- |
| `agent/agent_init.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `agent/context_compressor.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/api/client.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/api/mcp.ts` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/app/command-palette/index.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/app/contrib/wiring.tsx` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/app/routes.ts` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/app/session-import/api.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/app/session-import/index.test.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/app/session-import/index.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/app/skills/mcp-tab.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/app/types.ts` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/components/assistant-ui/markdown-text.media-md.test.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/components/assistant-ui/markdown-text.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/components/assistant-ui/mcp-setup-tool.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/components/assistant-ui/thread/message-parts.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/components/assistant-ui/tool/fallback-model/index.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/components/chat/preview-attachment.tsx` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/hermes-capability-scope.test.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/i18n/en.ts` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/i18n/ja.ts` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/i18n/types.ts` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/i18n/zh.ts` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `apps/desktop/src/lib/chat-messages/tool-parts.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/lib/mcp-dashboard-oauth.test.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/lib/mcp-dashboard-oauth.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/lib/todos.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/lib/tool-render-class.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/store/suggestion-providers/mcp.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `apps/desktop/src/store/suggestion-providers/repair.ts` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `cli.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `cron/jobs.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `cron/scheduler.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `gateway/authz_mixin.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `gateway/platforms/api_server.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `gateway/platforms/base.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `gateway/run.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `gateway/wake.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `hermes_cli/_subprocess_compat.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `hermes_cli/banner.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `hermes_cli/cli_process_notifications.py` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `hermes_cli/cron.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `hermes_cli/foreign_sessions_browser.py` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `hermes_cli/mcp_config.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `hermes_cli/subcommands/cron.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `hermes_cli/subcommands/mcp.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `hermes_cli/web_models.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `hermes_cli/web_server.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tests/agent/test_command_token_source.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/hermes_cli/test_banner_git_state.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/tools/test_approval_deny_rules.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/tools/test_mcp_oauth.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/tools/test_oneshot_completion_linger.py` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `tests/tui_gateway/test_subagent_child_mirror.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tools/approval.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/async_delegation.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/cronjob_tools.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/delegate_tool.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/environments/local.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/mcp_oauth.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/mcp_oauth_manager.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/process_registry.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/process_registry_notifications.py` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `tools/terminal_tool.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tui_gateway/method_ctx.py` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `tui_gateway/methods_session_foreign.py` | EXACT_FROZEN_UPSTREAM_CONTENT | Commit reviewed composition with focused validation |
| `tui_gateway/server.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `vendor/airi` | SUBMODULE_REVISION_REVIEW | Do not publish changed gitlink; preserve local pr-2477 branch and untracked index backup |
| `.codex/campaigns/semantic-vnext-20260908/ADOPTION_DELTA.yaml` | LOCAL_OPERATOR_RECORD | Keep local; ignore; no publication |
| `.codex/campaigns/semantic-vnext-20260908/INPUTS.json` | LOCAL_OPERATOR_RECORD | Keep local; ignore; no publication |
| `.codex/campaigns/semantic-vnext-20260908/VERIFICATION.md` | LOCAL_OPERATOR_RECORD | Keep local; ignore; no publication |
| `ANTIGRAVITY_IMPLEMENTATION_SPEC_JA.md` | LOCAL_OPERATOR_RECORD | Keep local; ignore; no publication |
| `airi-pr2477/` | SEPARATE_REPOSITORY | Keep independent repository and its index; ignore in Hermes |
| `evals/completion_backlog_probe.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `evals/mcp_device_flow.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/agent/test_context_compressor_custom_providers.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/cli/test_completion_backlog.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/cron/test_atomic_paused_creation.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/gateway/test_completion_admission.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/tools/test_completed_process_results.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/tools/test_delegate_fallback_matrix.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/tools/test_gitbash_probe_stdin.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/tools/test_mcp_device_flow.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tests/tools/test_subagent_process_handoff.py` | TEST_OR_REPRODUCTION_SOURCE | Commit reviewed composition with focused validation |
| `tools/delegate_tool_config.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/mcp_oauth_device.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/mcp_oauth_provider.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |
| `tools/process_registry_results.py` | LOCAL_IMPLEMENTATION_DELTA | Commit reviewed composition with focused validation |

## Review corrections

The banner composition initially supplied creationflags twice and passed a second git token to its shared wrapper. Both were corrected. Cron uses its existing cronjob registration; an unsupported alias and unused catch-all arguments were removed. Native handoff verification waits for completion publication after OS exit and still requires exactly one parent-owned result.

Completion admission now requires an explicit receipt. The canonical FIFO sets it only after storing an event; rejected and full queues do not acknowledge it. Older success fixtures were updated to model actual admission. Missing-adapter expectations now require retained payloads rather than permanent disposal, supported separately by real SQLite and Windows process-restart tests for zero-attempt preservation.

README was rewritten for downstream 0.21.1. The previous integration inventory is retained separately; release policy now distinguishes downstream versions from upstream provenance.

## Evidence and remaining gates

### CI follow-up: case-sensitive hosts and canonical tool routing

The hosted Python run exposed lower/mixed-case credential names surviving the
child-environment scrub on Linux. Both existing environment owners now compare
credential names case-insensitively, preserving the explicit provider-inheritance
tier and leaving the parent mapping unchanged. Factory mapping tests pass on
Windows independently of the operating system's environment-key normalization.

The refactored CLI input loop had lost interrupt recovery and skipped post-turn
bookkeeping after exceptions. The loop now finalizes each submitted turn in a
finally block and invokes recovery only after an interrupted turn. Tests execute
the actual nested input-loop function with normal, failed and interrupted turns.

The duplicate process_manage schema registration was removed. Handoff, durable
completion and receipt retrieval remain on the existing process tool; native
Windows receipt recovery (2 tests) and child handoff (3 tests) pass through that
canonical registration. Blank-slate setup asserts the effective catalog before
Tool Search wraps deferred tools, without changing its expected tool list.

Successful notification fixtures now return admission receipts after accepting an
event; rejecting fixtures still do not acknowledge. Version checks compare the
actual downstream metadata instead of a stale 0.21.0 literal. README navigation,
installation links, historical inventory and attribution are retained.

The subprocess audit delta was reviewed: the banner's same Git spawn moved from
_git_stdout to _git_run, with network calls retaining credential-isolated options.
The reviewed fingerprint records that rename; no runtime spawn was added.
Two .node-test.mjs child-process fixtures are now recognized as test files, like
.test and .spec files. Dependency directories are pruned before audit traversal;
the production source scopes and mandatory sanitized-boundary assertions remain.
The audit passes all five checks. CodeGraph 1.6.0 re-extraction covers the token
source, both environment owners, CLI input loop and process registry, but retains
unresolved references and is not a complete graph qualification.

Desktop type checking and 28 focused UI tests passed. Windows process tests cover native spawn/output/exit/kill, and handoff covers a live child surviving sibling cleanup. Git helper tests check hidden native children. Approval regression: 180 passed, one symlink-availability skip. OAuth loopback: 57 passed, one POSIX permission skip. Token-source tests: 34 passed in the installed dependency runtime, with isolated profile state. Completion backlog: two tests passed using an owned loopback HTTP fixture.

The first combined Python run recorded 205 passes, six failures and three skips. It is retained as a failed run. Subsequent isolated runs diagnosed dependencies, fixture networking/synchronisation and composition defects. A hung pre-admission-fixture run was interrupted and is not a pass.

CodeGraph 1.6.0 extraction was rerun for the existing credential/consent/Desktop-owner supplement. It is source extraction, not a complete resolved graph of this change set. Full history classification, remaining P0/private contracts, clean-machine installer/upgrade qualification, exact-head CI and the isolated first-run onboarding issue remain unresolved. Native tests do not by themselves qualify the complete application.
