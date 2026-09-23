# Hermes Control MCP — API-Mapped TDD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or, after the operator selects that method, `superpowers:subagent-driven-development`. Follow the numbered tasks and their RED → GREEN → review gates. This is an implementation plan, not an implementation or test report.

**Goal:** Give ChatGPT web and the Codex desktop app an authenticated, interoperable interface for Hermes state, evidence and C-level development operations, with human approval and parent-owned credentials.

**Architecture:** An opt-in `control_mcp` extension exposes one typed facade inside the existing Hermes host. Streamable HTTP is the required transport for both clients. Existing authorities continue to own configuration, approvals, engineering execution, profiles and Git operations; narrow host extensions supply capabilities that do not yet exist. Optional stdio is a relay, never a second authenticated agent.

**Tech stack:** Existing Python/pytest, FastAPI/Starlette, MCP SDK, SQLite plugin storage, native Windows process tests and Desktop TypeScript tests. Resolve versions from this checkout's `pyproject.toml` and `uv.lock`; do not install arbitrary latest SDK versions.

**Spec:** `docs/superpowers/specs/2026-09-23-hermes-control-mcp-design.md` at `e3616fa8c4288d43e23b69dec0848bd2bf28b160`. The operator approved that design in the conversation. This plan still requires implementation approval.

**Repository:** `zapabob/hermes-agent-windows` only.

**Inspected product base:** `34562508555d84f0740eda7a0af5ec4ff90bbe60`.

**Documentation branch:** `docs/hermes-control-mcp-c-20260923`.

**Date:** 2026-09-23. Source inspection is read-only; no runtime deployment, account connection, product test, PR or merge is claimed.

## Global constraints

- Keep the 0.21.4 adoption worktree, upstream PR #119964, primary checkout, local user changes, running Desktop/Go/llama services and product versions untouched.
- Implement only in a new isolated worktree, after verifying its repository identity, baseline SHA, status and attached branch. A remote documentation branch is not a local worktree.
- C is a supported capability, not blanket authority. Installation and client registration default to read-only. Each write needs scope, resource access, immutable intent, current-state checks and a one-use human decision.
- Do not add a Codex SDK, Codex App Server requirement, LLM-vendor routing rule, new provider credential store, session registry or independent scheduler.
- Do not expose a generic shell, arbitrary RPC proxy, arbitrary path reader, unrestricted configuration writer, secret export, vault reset, scanner disable, approval-policy relaxation, force-push, direct-main push or protection-rule editor.
- Provider, MCP-resource and GitHub credentials are separate domains. None goes to worker agents or child/grandchild command environments, arguments, files or logs. A trusted in-process integration still belongs to the host trust base.
- Reads must not run inference, refresh provider credentials, decrypt the vault, initialise storage, start Docker, pull an image or run a scanner. A timestamped prior health observation is not a new probe.
- Current Engineering Router execution requires its local Linux Docker backend and pinned prepared image. Observation and route configuration do not. Do not add a native-shell fallback here.
- Pause/resume and replay-after-crash are not existing capabilities. Advertise them as unsupported, not as successful no-ops.
- Use current locale registries. The inspected `agent.i18n.SUPPORTED_LANGUAGES` has 17 entries; Desktop has a separate registry. Preserve stable machine codes and translate each surface's user-facing strings, including RTL.
- Product code, deployment, client configuration edits, public endpoint/tunnel setup and merges need their appropriate later approvals. Do not automatically apply `ci-reviewed`.

## Review focus

1. A valid dashboard token is not necessarily an MCP-resource grant; an empty scope list must never become administrator access.
2. A bridge-local `resolved: true` or client confirmation must not approve the operation that requested it.
3. ChatGPT and Codex submitting concurrently must not create two writers; timeout or restart after an external effect must not trigger replay.
4. Existing convenience helpers can create directories, refresh catalogues, mutate config caches or launch authenticated `gh` processes; read-only and parent-only guarantees require traced call paths.
5. Windows paths, reparse points, UNC/ADS names and reused thread identities can cross the intended workspace or cancellation boundary.

## 1. Verified integration map

All repository links below are relative to the inspected product base. NEW names in later sections are proposed interfaces to implement, not claims about current Hermes APIs.

| Area | Existing interface / location | Reuse decision and required change |
|---|---|---|
| Gateway observations | `gateway.status.read_runtime_status(path=None)`, `runtime_status_is_stale(record, ttl_s=120)`, `runtime_status_pid_is_live(record)` | Read the authorised profile's exact status path; retain stale/unknown distinctions. PID liveness without start-time proof is not an ownership claim. Never call takeover/termination from a read. |
| Configuration reads | `hermes_cli.config.load_config_readonly()` | Returns the shared cached dictionary, NOT an immutable copy. Project fields into fresh objects; never mutate returned nested objects. Trace cold-cache behaviour and add a side-effect-free snapshot accessor if required. |
| Configuration writes | `hermes_cli.config.save_config(config, *, strip_defaults=True, preserve_keys=None, merge_existing=False)` | Existing save owner, `_CONFIG_LOCK`, managed-policy handling and atomic YAML writer remain authoritative. Add compare-and-set within this owner; do not invent an independent YAML writer. |
| Model picker | `hermes_cli.web_server.get_model_options(...)`, `get_auxiliary_models(profile=None)`, `set_model_assignment(body, profile=None)`, `_apply_model_assignment_sync(...)`; `get_plugin_auxiliary_tasks()` | Reuse catalogue/slot validation, but not raw API responses: base URLs and registration defaults are not export-safe. The mutation body supports credentials; the new MCP schema must not. Extract shared validation rather than forge an HTTP request to a handler. |
| Request-scoped authentication | `dashboard_auth.token_auth.register_token_route(path)`, `authenticate_token(request)`, `token_auth_middleware(...)`; `TokenPrincipal(principal, provider, scopes=())` | Exact-path token seam exists. Add a path-specific resource verifier; do not let the generic try-every-provider path accept a dashboard token as a C grant. A new validated control context supplies resource/audience, client and profile/workspace grants. |
| Human approval | `tools.approval.register_gateway_notify(session_key, cb)`, `list_gateway_approvals(session_key)`, `resolve_gateway_approval(..., request_id=...)`; Desktop/TUI `approval.respond` in `tui_gateway/methods_prompt.py` | Actual owner exists. Extend it with a digest-bound, once-only control request and a trusted-human response path. Request-ID matching, not FIFO resolution. |
| Unsuitable approval shortcuts | `mcp_serve.EventBridge.respond_to_approval()`; `request_tool_approval()`; `request_elicitation_consent()` | The first is bridge-local without gateway IPC. The others permit existing policy/session choices, so they are not a ready-made strict C approval. Do not wrap an `accept` string as proof of a one-use human decision. |
| Engineering entry | `plugins.implementation_router.entrypoint.run_workflow(ctx, args)` with exact keys `workspace`, `task` | Real synchronous entrypoint. Use registered plugin context, not a copied/authenticated child agent. Add a public run-owner adapter at this owner for asynchronous admission, observation and targeted cancellation. |
| Engineering evidence | `NativeEngineeringHost.checkpoint`, `stage`, `verify`, `lease`, `close`; `events.jsonl`, `workspace-receipt.json`, `verified-workspace` | Extend the producer to persist typed verification/route observations. Existing event records alone do not establish all exit-code/platform/effort facts required by this MCP. Never infer a live run from a directory or chat title. |
| Cancellation | `tools.interrupt.set_interrupt(active, thread_id=None, *, reason=None)` | Thread-scoped primitive, not a durable run API. A generation-bound run-owner mapping must mediate it and release the mapping atomically when the actual worker ends. |
| Plugin data | `plugins.plugin_storage.plugin_data_dir(name)`, `plugin_db(name, filename='data.db')` | Both create resources. Initialise only at approved plugin startup/writes. Reads use an existing read-only connection or report ABSENT. Extend host control metadata, not `state.db` transcripts. |
| Git/PR | `hermes_cli.web_git.repo_status`, `review_rev_parse`, `review_create_pr(cwd)`, `_gh`, `_review_push`; `web_routers/git.py` | Existing PR creation shells out to `gh` and attempts a push; it does not implement the required merge gate. Do NOT call it from the new credential-free path. Add parent-process GitHub HTTP operations under the existing Git owner. |
| Mount/lifecycle | `hermes_cli.web_server._lifespan`, `_mount_plugin_api_routes`; dashboard plugin `api` → `APIRouter` | Plugin mount is for routers, not proof that an MCP ASGI session manager is started. Add one explicit lifecycle integration after enablement/trust checks, before SPA catch-all. No second backend/supervisor. |
| Existing MCP | `mcp_serve.create_mcp_server`, `run_mcp_server`; `agent/transports/hermes_tools_mcp_server.py` | Preserve existing entrypoints. Reuse schema conventions only; do not expose their entire messaging/approval/tool catalogue through the new service. |

Source references and blob IDs are provided in `API_MAP.json` in the downloadable bundle. Before implementation, re-read any source that differs from these pins.

## 2. Interface contracts for the new facade

### Identity and safe envelopes

NEW `downstream/control_mcp/contracts.py` defines immutable `ControlContext`, typed requests/results and stable `ControlError(code)`.

`ControlContext`: verified subject, client registration, issuer, resource, grant revision, expiry, scopes, allowed profile IDs and allowed workspace IDs. It contains no token string. It is created only by the resource verifier; no tool argument can supply or replace it.

Every result has `schema_version=1`, `observed_at`, `producer_epoch`, `producer_version`, `profile_id`, optional workspace/run/operation IDs, and a stable state/reason. Never `asdict()` a dashboard `Session`: it contains access/refresh tokens.

NEW pure helpers:

- `require_access(ctx, *, scope, profile_id, workspace_id=None, now)` → None or `ControlError`.
- `canonical_intent_digest(payload)` → SHA-256 of strict canonical JSON, rejecting duplicate keys at ingress, non-finite values, booleans where integers are required, unknown fields and oversized input.
- `project_routes(config)` → fresh list of only registered engineering slot, provider ID, model ID and configured effort. No base URL, header, credential reference, raw defaults or exception text.

Limits: tool request 32 KiB UTF-8; task 16,000 characters; evidence page 64 KiB UTF-8; at most 100 events/page; maximum event wait 20 seconds; explicit retention-gap response. Byte truncation must preserve UTF-8 and expose `truncated=true`.

### Read tools

Required tools: `hermes_get_capabilities`, `hermes_get_runtime_status`, `hermes_get_run`, `hermes_get_routes`, `hermes_get_evidence`, `hermes_get_operation`, `hermes_list_approvals`, `hermes_poll_events`.

Reads return AVAILABLE / ABSENT / STALE / UNKNOWN / UNSUPPORTED rather than manufacturing empty success. Resource IDs are opaque host-issued IDs, not filesystem paths or URLs. Every tool, resource and event cursor repeats the same authorisation check.

### Write tools and scopes

| Tool | Scope | Immutable target |
|---|---|---|
| `hermes_start_engineering_run` | `hermes:run:start` | workspace policy revision, source SHA/digest, route revision and task digest |
| `hermes_cancel_run` | `hermes:run:cancel` | run ID + owner generation; not a bare PID/thread ID |
| `hermes_reverify` | `hermes:run:verify` | immutable candidate and registered check-set digest |
| `hermes_patch_routes` | `hermes:config:routes` | expected config revision and allow-listed slot edits |
| `hermes_apply_verified_result` | `hermes:workspace:apply` | verified evidence ID, target feature worktree and expected base/tree digest |
| `hermes_create_pull_request` | `hermes:repo:pr` | allowed repository, already-published head branch/SHA, base branch, title/body digest |
| `hermes_merge_pull_request` | `hermes:repo:merge` | PR number, expected head/base, policy/check snapshot and merge method |

All writes also require `hermes:read` on their resource, operator-enabled C capability, human consent and safety gates. The initial implementation does not implicitly publish a local branch while creating a PR. Publishing a branch would be a separately approved typed action; pre-existing published heads are sufficient for the C PR-creation contract.

NEW `HostControlService.submit(ctx, request)` returns an `operation_id` and `PENDING_APPROVAL`, never a success claim. Existing host execution runs after the decision. `get_operation()` distinguishes APPROVED, RUNNING, CANCEL_REQUESTED, SUCCEEDED, FAILED, BLOCKED, DENIED, EXPIRED, CONFLICT and UNKNOWN.

### Approval and replay rules

Journal uniqueness is `(subject, client_registration, idempotency_key)`. Reuse with a different digest is CONFLICT. Across clients, a live workspace reservation prevents duplicate admission; an authorised second client may inspect the existing operation but cannot borrow its approval. Repeating an approved operation requires a new intent and a new decision.

Approval binds operation ID, subject/client, profile/workspace, canonical digest, expected revisions, expiry and request ID. Only `once` or `deny` is valid for a strict control entry; session/always/all and smart/Yolo approval never satisfy it. The human decision must originate from a trusted local UI surface, not from a model-callable MCP tool or self-declared `client_name`.

The journal records intent before side effects. On host restart, RUNNING or effect-unknown work becomes UNKNOWN and is reconciled with the destination; it is never automatically replayed. Metadata is not a new autonomous job scheduler.

## 3. File ownership and task order

NEW implementation files are planned, not present yet:

- `downstream/control_mcp/{contracts,projection,service,journal,auth,transport,capabilities}.py`
- `plugins/control_mcp/{__init__,api}.py`, `plugins/control_mcp/plugin.yaml`, `plugins/control_mcp/AGENTS.md`
- `plugins/implementation_router/control.py` for the engineering-owned run adapter.
- `hermes_cli/web_git_control.py` for parent-owned checked Git/PR integration.
- `tests/control_mcp/` for pure/facade/protocol contracts; `tests/e2e/test_control_mcp_host.py` for the live host.
- `docs/control-mcp/{AGENT_PROTOCOL,CLIENT_SETUP,SECURITY,ACCEPTANCE}.md` plus authoritative locale entries.

Existing files modified narrowly: `tools/approval.py`, `hermes_cli/config.py`, `hermes_cli/dashboard_auth/token_auth.py`, `hermes_cli/web_server.py`, engineering producer files, and the appropriate trusted approval UI wiring. Do not reorganise unrelated core files.

Sequence: 0 freeze → 1 read facade → 2 journal/approval → 3 authenticated MCP transport → 4 engineering controls/evidence → 5 route CAS → 6 verified apply → 7 GitHub PR/merge → 8 interop/i18n/security qualification.

Each task has its own review gate. Auth, approval and GitHub publication require a fresh security review before C is advertised. Read support may be qualified earlier without claiming C completion.

## Task 0 — Freeze, inspect and establish a clean baseline

**Files:** approved spec, `AGENTS.md`, `.codex/{SOP,UPSTREAM_POLICY,FORK_INVARIANTS,WINDOWS_PLATFORM_CONTRACT}.md`, `FEATURES.yaml`, `CARRY.yaml`, `pyproject.toml`, `uv.lock`.

- [ ] Read all instructions and preserve the historical upstream freeze. This task does not require fetching upstream/main.
- [ ] Verify origin slug; locate the user's active checkout without touching it; inspect `git worktree list --porcelain`.
- [ ] Fetch the documentation branch explicitly. Resolve its exact commit once; verify the approved spec is an ancestor/content match. Record the current product main separately, without moving the frozen implementation base silently.
- [ ] Create `feat/hermes-control-mcp-c-20260923` in an operator-selected new sibling directory with `git worktree add -b`. Verify `git rev-parse --show-toplevel`, `HEAD` and clean status inside that directory. Never reset, stash, clean or remove another worktree.
- [ ] Resolve dependencies using `uv.lock` in that worktree. Record the actual MCP package version and public server/client/ASGI signatures. The checkout imports `mcp.server.MCPServer`; do not paste an old `FastMCP` example or assume a v1 lifecycle method exists.
- [ ] Run baseline `tests/test_mcp_serve.py`, `tests/tools/test_mcp_elicitation.py`, relevant dashboard auth tests and existing engineering contract tests. Write exact commands, SHAs, platform and results to the evidence log. A collection error is not behavioural RED.

**Commit:** documentation of baseline only, without secrets or generated dependency trees. If an existing defect blocks the slice, reproduce it at the frozen product base and record it separately.

## Task 1 — Side-effect-free status, routes and evidence facade

**Create:** `contracts.py`, `projection.py`, read portion of `service.py`; `tests/control_mcp/test_reads.py`, `test_projection.py`.

**Consumes:** existing runtime-status reader, read-only config snapshot, engineering journal metadata.
**Produces:** the eight read-tool result contracts and a capability map with unsupported write entries.

- [ ] RED: add tests proving the returned dictionary is independent from config cache and excludes secrets, endpoint URLs and provider registration defaults.

```python
from copy import deepcopy
from downstream.control_mcp.projection import project_routes


def test_projection_neither_leaks_nor_mutates_config():
    config = {'auxiliary': {'engineering_worker': {
        'provider': 'fixture', 'model': 'worker', 'reasoning_effort': 'medium',
        'api_key': 'synthetic-provider-secret',
        'base_url': 'https://private.invalid/token-in-path',
    }}}
    original = deepcopy(config)
    routes = project_routes(config)
    assert routes == [{'slot': 'engineering_worker', 'provider': 'fixture',
                       'model': 'worker', 'configured_effort': 'medium'}]
    routes[0]['model'] = 'changed-in-response'
    assert config == original
```

- [ ] RED: absent/partial journals, stale status, wrong profile, foreign evidence IDs, retained lease after crash, invalid UTF-8 and oversize records. Patch inference, credential decrypt/refresh, `plugin_db`, Docker start/pull and subprocess entrypoints to raise if a read unexpectedly calls them.
- [ ] Implement fresh allow-listed projections. Use `read_runtime_status(path=authorised_status_path)`, freshness and liveness helpers only. Read existing plugin data without calling its creating helpers. If cold config load has side effects, add a read-only snapshot function in the existing config owner and route both consumers to it.
- [ ] RED: a directory and `stage_start` without an active owner cannot produce RUNNING; configured High without a recorded request cannot produce request-sent High. Missing receipt details return UNKNOWN, not a fabricated test pass.
- [ ] GREEN: `python -m pytest tests/control_mcp/test_reads.py tests/control_mcp/test_projection.py -q`; then existing MCP/status/config tests. Commit `feat(control-mcp): add scoped read-only evidence projections`.

## Task 2 — Durable intent, once-only authoritative approval and concurrency

**Create:** `journal.py`, mutation admission in `service.py`; `tests/control_mcp/test_operations.py`, `test_control_approval.py`.
**Modify:** `tools/approval.py` and the trusted Desktop/TUI approval presentation/response path, preserving legacy callers.

**NEW interfaces:** `HostControlJournal.reserve(ctx, request)`, `get(ctx, operation_id)`, `transition(operation_id, expected_state, new_state, evidence_id=None)`; `request_control_consent(intent, *, session_key, timeout_seconds)` in the existing approval module. The latter returns a typed owner decision, not a model string.

- [ ] RED: a valid request reserves one immutable intent but executes nothing; repeated identical request returns the same operation; changed payload on the same key conflicts.
- [ ] RED: a model tool supplying `approved`, `choice`, `session_key`, auth fields or unknown properties fails schema validation before admission.
- [ ] RED: bridge-local `resolved: true`, smart approval, session/always/all choices, missing notify callback, stale request ID and expired intent cannot execute. For the new strict entry class, the existing queue owner must validate the decision before removing it or setting its event.
- [ ] Implement transactional unique intent storage through the existing profile-scoped plugin storage convention, initialised at opt-in startup. Add bound control entries to the existing approval authority. Preserve `resolve_gateway_approval()` behaviour for old entries; dispatch strict entries through the new typed validation.
- [ ] Bind the local human surface to the exact intent digest, request ID and client/resource identity. Reject token-only/MCP-origin requests at the human-decision endpoint. Do not expose approval-allow as an MCP tool.
- [ ] RED/GREEN: concurrent clients race on one workspace; exactly one gets admission and the other gets the visible operation/conflict. Thread-pool work is scheduled only by the existing host after approval; DB transaction locks are not held while awaiting a human.
- [ ] Inject crash immediately before and after a mock external effect. On recovery the host reconciles UNKNOWN; no retry executes merely because the old connection disappeared.
- [ ] Run focused tests plus existing approval, timeout and reconnect tests. Commit `feat(approval): bind control intents to single-use human decisions`.

A read of journal metadata must not create the journal. A post-effect journal-write failure is UNKNOWN, not success and not automatic retry.

## Task 3 — Resource-scoped MCP authentication and real protocol lifecycle

**Create:** `auth.py`, `transport.py`, plugin files, `test_auth.py`, `test_mcp_protocol.py`, `test_host_mount.py`.
**Modify:** exact-route token seam and existing web-server lifecycle only.

**NEW interfaces:** `verify_control_request(request) -> ControlContext`; `create_control_mcp(service)`; `mount_control_mcp(application, service)` and its explicit startup/shutdown context.

- [ ] RED: anonymous, dashboard-only, empty-scope, wrong issuer/audience, expired, revoked and wrong-client tokens cannot reach tools. Test every MCP HTTP method, trailing-slash form, sessions and resource reads.
- [ ] Reuse the existing token route mechanism with a resource-specific verifier for the new MCP endpoint. Pin approved issuer/JWKS metadata and algorithms; never accept token-provided `jku`/arbitrary discovery URLs. No general dashboard bearer token may be upgraded to a C grant.
- [ ] Implement standards-compliant protected-resource metadata and 401 challenges for the chosen public endpoint. Use an operator-approved existing OAuth issuer with PKCE/client registration as needed; the MCP resource validates access tokens but is not a new provider credential store. If no suitable issuer is configured, remote authentication is NOT_CONFIGURED, not unauthenticated public access.
- [ ] Use the locked MCP SDK's real Streamable HTTP server transport. Start its session-manager/lifespan once from the existing parent host. The current plugin `APIRouter` loader is not assumed to run an ASGI subapp lifespan. Add and test that explicit seam; do not start another Uvicorn backend.
- [ ] Authenticate each request and bind MCP session state to the validated principal/resource. Use Host/Origin checks, approved public URLs, TLS for remote exposure and no redirects carrying tokens. Missing Origin from a native client is not automatically rejected, but invalid browser Origin is.
- [ ] RED/GREEN with a real SDK client: initialise, tool list, calls, errors, structured result, DELETE/disconnect, version negotiation and server shutdown. An unsupported protocol version returns a protocol error; SDK version is not a protocol-version string.
- [ ] Read tools carry truthful read-only annotations; write tools never do. No blanket exposure of `mcp_serve` tools or arbitrary HTTP proxy. MCP notifications/resources enforce the same grants as tools.
- [ ] Codex setup is a reviewed snippet for an actual endpoint, not an overwrite of `~/.codex/config.toml`. No auth.json access. Optional stdio must forward to the same host with dedicated pairing credentials, not inherit provider/Git tokens; omit it from advertised capabilities until independently tested.
- [ ] Run protocol/auth and existing dashboard middleware regression tests. Commit `feat(control-mcp): mount authenticated streamable HTTP on the host`.

No tunnel installation, firewall change, live client registration or public exposure belongs to this coding task without operator approval.

## Task 4 — Engineering run owner, typed receipts and targeted cancellation

**Create:** `plugins/implementation_router/control.py`; `test_engineering_adapter.py`, `test_evidence_provenance.py`.
**Modify:** existing engineering `entrypoint.py`, `host.py` and actor request-observation path.

**NEW owner interfaces:** `start_approved(intent, ctx) -> RunHandle`, `get_run(run_id)`, `cancel(run_id, owner_generation)`, `reverify_approved(intent)`. A RunHandle has a host epoch/generation, not an externally writable PID.

- [ ] RED: prove one call reaches the actual `run_workflow(ctx, {'workspace': ..., 'task': ...})` after human approval, in the authorised profile context. No second AIAgent or new scheduler is constructed.
- [ ] Extend this owner to mint the run ID before start and to publish it with operation ID, source/policy/route revisions and lifecycle checkpoints. Capture ContextVars explicitly across the existing host executor; never carry secrets in a handoff DTO.
- [ ] Add append-only, sanitised verification evidence at `NativeEngineeringHost.verify()` and terminal cleanup. Persist check ID, integer exit code, timeout/completion, source digest, platform and evidence type. Existing JSONL event kind alone is insufficient.
- [ ] Record configured route, host request fields actually sent and provider-reported identity separately. Request effort UNKNOWN remains null when not recorded; do not guess from the composer or response prose. Keep provider-native effort validation and `allow_fallback=False`.
- [ ] RED: cancelling run A cannot interrupt run B after executor thread reuse. Resolve `set_interrupt` through a locked `(run_id, owner_generation, thread_id)` mapping; unregister it atomically when execution exits. CANCEL_REQUESTED is distinct from CANCELLED and from confirmed quiescence.
- [ ] Reverification uses the registered immutable candidate and host-owned protected check set. It cannot reuse a successful receipt from a different source or run. A missing safe host path returns UNSUPPORTED until this owner implements it.
- [ ] Real tiny Docker acceptance runs planner/worker/verifier with a deterministic local test provider and offline prepared image. This proves container integration, not paid-account entitlement. Run separate Windows child/grandchild and interrupted-worker tests.
- [ ] Commit `feat(engineering): expose owner-bound control and verification evidence`. Do not advertise pause/resume/retry-after-crash.

## Task 5 — Existing-picker route changes with configuration compare-and-set

**Modify:** `hermes_cli/config.py`, shared model-assignment validation seam, control mutation adapter; `test_route_cas.py`.

**NEW owner interface:** `apply_engineering_routes_if_revision(*, profile_id, expected_revision, slot_changes, approval_binding) -> ConfigRevision` inside the existing configuration owner. Allowed keys per slot are provider ID, model ID and a provider-supported effort setting; no endpoint/auth keys.

- [ ] RED: two requests at revision R cannot both save; the second conflicts. A stale browser/Codex snapshot cannot overwrite unrelated configuration.
- [ ] RED: mutating a read-only config reference is forbidden; managed settings, missing catalogue entry, unsupported effort, removed plugin slot and selection changes after approval fail before save.
- [ ] Extract/share picker assignment validation from the existing path rather than call a credential-accepting HTTP handler. Resolve configured endpoint IDs through existing configuration; never accept a new URL/header/API key over MCP.
- [ ] Add revision comparison and atomic save under the existing config authority. Extend shared writer coordination, including Windows cross-process file-lock discipline where applicable. All participating save paths must obey it; document that an arbitrary external file editor is not magically transactional.
- [ ] Build changes from `load_config()`/defensive copy, not by modifying `load_config_readonly()`. Preserve managed policy, comments/reference normalisation and unrelated fields in `save_config`. Never hold `_profile_scope` across an await.
- [ ] If the public picker does not yet expose an effort field at this base, add it through its shared schema/config path and tests, not a separate MCP-only route catalogue. Freeze the effective route revision for a running engineering operation; changed policy blocks it rather than silently retargeting.
- [ ] Run route/config/profile tests and `tests/agent/test_auxiliary_strict_route.py`. Commit `feat(config): add approved compare-and-set engineering route updates`.

## Task 6 — Apply a verified result without overwriting active user work

**Create:** application adapter in `hermes_cli/web_git_control.py`, `test_verified_apply.py`.
**Consumes:** actual engineering `verified-workspace` plus host-authenticated evidence and an operator-registered destination.
**Produces:** changed feature-worktree digest, rollback receipt and operation result; not a main merge.

- [ ] RED: foreign evidence, mismatched source SHA/digest, dirty destination, current main target, unknown owner or changed protected probes cause no write.
- [ ] RED: Windows junction/reparse/symlink, hardlink, traversal, UNC, drive-relative path, alternate data stream, case-collision and reserved device names cannot escape the registered source/destination. Use real Windows filesystem tests where supported; report privilege-dependent skips.
- [ ] Compute a bounded diff only from admitted source files and verify evidence provenance with the actual producer. A SHA-256 hash alone is not an authorisation or signature.
- [ ] Reserve the target through its host workspace owner; stage changes in an isolated sibling; back up exactly affected files; record before/after digests. Apply only after final revalidation. Do not claim filesystem-wide atomicity: interrupted multi-file promotion becomes RECOVERY_REQUIRED and blocks further writers until reconciled.
- [ ] Run local read-only Git probes with explicit credential-free environment, disabled hooks/config side effects and no credential helper/SSH agent. Keep the shared Git authority; do not call arbitrary `git` arguments from tool input.
- [ ] Test interruption midway, rollback conflict and concurrent user edits. Never rollback by erasing a new user edit.
- [ ] Run focused apply tests, workspace contracts and Windows tests. Commit `feat(git): apply verified engineering results with guarded rollback`.

## Task 7 — Parent-only GitHub PR creation and checked merge

**Modify:** `hermes_cli/web_git_control.py`; tests `test_pr_create.py`, `test_pr_merge.py`, `test_parent_credentials.py`.

**NEW owner interfaces:** `create_pr_checked(intent, credential_handle)`, `merge_pr_checked(intent, credential_handle)`, `reconcile_pr_effect(operation_id)`; the credential handle never appears on the MCP wire or reaches subprocesses.

- [ ] RED: patch `web_git._gh`, `review_create_pr`, `review_push`, subprocess execution and credential-helper launch to raise. The new remote PR path must still work against a controlled in-process HTTP transport.
- [ ] Use existing profile-scoped secret resolution for an explicitly configured GitHub credential source and an in-parent HTTPS client. Do not obtain it by invoking `gh auth token`; do not create a new token file/store. An unavailable parent-only grant blocks the capability.
- [ ] PR creation accepts an allow-listed repository and an already-published branch. Verify actual remote head SHA, base branch and approved title/body before POST; no implicit push, branch creation, reviewers, labels or protection changes.
- [ ] If POST returns ambiguously, look up the remote PR by repository/head/base and the host operation identity before considering a retry. Never claim exactly-once delivery across network failure.
- [ ] Merge is a separate intent and human approval. Re-fetch current PR head/base, required checks, review state, draft/mergeability and applicable repository rules. `action_required`, pending, unknown, failing or inaccessible policy information never passes.
- [ ] Submit GitHub's expected head SHA when merging. Base-SHA preflight alone is not atomic: require repository-enforced up-to-date checks/merge-queue guarantees appropriate to the approved target, and fail closed when that guarantee cannot be established. Do not bypass branch rules or use an admin override.
- [ ] After remote success, fetch the actual merged PR and merge commit. Record post-merge CI separately; successful merge does not imply green post-merge tests.
- [ ] Tests inject a head change, base change, missing check pages, untrusted check producer, stale reviews, invalid token scope, rate limits and response loss after actual remote acceptance. Paginate checks/rules/reviews where required; zero results is not success.
- [ ] Run controlled HTTP and credential-containment tests. A later live write test requires an operator-approved disposable repository/PR. Commit `feat(github): add parent-owned checked control operations`.

## Task 8 — Client interoperability, i18n, sabotage and release qualification

**Create:** `docs/control-mcp/*`, `tests/e2e/test_control_mcp_host.py`, `tests/control_mcp/test_i18n.py`, a focused mutation runner and a normal read-only CI workflow.

- [ ] Write server instructions whose opening states: inspect capabilities/state; writes request human approval; never infer execution or ask for secrets. Expose supported capabilities based on wired/tested host paths, not static marketing claims.
- [ ] Populate `control_mcp.*` keys through current language registries, using the existing `agent.i18n.t`. Add translated approval summaries/errors/client help and Desktop keys only where UI changes require them. Key parity alone is not translation review; mark unreviewed translations honestly.
- [ ] Start an actual Hermes test host and two real MCP clients, not facade mocks. Test simultaneous observations and conflicting writes. Both clients must see the same host operation ID/result when authorised, with different scoped client identities.
- [ ] Codex Desktop acceptance: import a targeted reviewed endpoint snippet, authenticate, read capabilities/status/evidence, request one bounded write, approve in Hermes, inspect actual result. No whole-file config overwrite, automatic trust or auth.json read.
- [ ] ChatGPT web acceptance: use an explicitly approved TLS endpoint/tunnel; test read and write availability independently for the real account. Product restrictions must not be bypassed by mislabelling a mutation as read-only. Server C capability can be implemented while a client remains READ_ONLY/BLOCKED.
- [ ] Execute the negative/mutation matrix below. Each mutation must be killed by an assertion about behaviour, not syntax/import failure.
- [ ] Run affected tests, ordinary Python suite, Ruff, Windows footgun checks, Desktop JS/TS/lint/i18n, engineering Windows/Ubuntu contracts, real Docker acceptance and native Windows process tests. Record skips and retries separately. Do not skip security tests just because they are inconvenient on the implementation host.
- [ ] Review exact final diff for auth files, real tokens, test archives, source caches, temporary workflows and unrelated adoption changes. Submit a focused downstream PR only after implementation authorisation and local gates. Await required exact-head CI and security review; merge/post-merge/deployment require the relevant permission.

**Commit:** `test(control-mcp): qualify clients, translations and failure boundaries`.

## 4. Acceptance and sabotage matrix

| ID | Deliberate fault / scenario | Required assertion |
|---|---|---|
| A01 | Accept a generic dashboard token or empty scopes | Protected control call denied; no projection or write |
| A02 | Skip resource audience/issuer/expiry check | Wrong-resource token rejected by real transport |
| A03 | Trust tool `profile_id` without grant check | No cross-profile tools/resources/events/error leakage |
| A04 | Replace human consent with model/client `approved=true` | No owner execution; schema/authority denial |
| A05 | Accept legacy bridge-local approval event | No transition to APPROVED/RUNNING |
| A06 | Reuse once-only decision; accept session/always/all | Second write denied; new approval required |
| A07 | Change args, config revision, policy or SHA after consent | Conflict before execution |
| A08 | Remove transactional uniqueness/workspace exclusion | Two-client test detects duplicate admission |
| A09 | Replay after timeout/crash around external effect | UNKNOWN is reconciled, not executed again |
| A10 | Treat cancel-request acknowledgement as quiescence | Workspace remains reserved until actual owner stops |
| A11 | Reuse old thread ID for cancellation | New run/other session is not interrupted |
| A12 | Read creates DB, decrypts vault, refreshes auth or starts Docker | Side-effect tripwire fails test |
| A13 | Export raw Session/config/defaults/logs | Synthetic secret/endpoint marker never reaches client |
| A14 | Permit evidence traversal/Windows reparse escape | Rejected before content is read or changed |
| A15 | Infer success from folder/hash/model prose | UNKNOWN/ABSENT; no fabricated receipts |
| A16 | Accept stale/foreign/incomplete/timeout verifier record | No verified-result apply or success |
| A17 | Copy parent environment to child/grandchild | Synthetic provider/Git/MCP markers detected by test |
| A18 | Pass GitHub credential to `gh`/git helper | Child launch forbidden; parent HTTP remains functional |
| A19 | Missing Docker triggers native fallback | Run BLOCKED, observation still works |
| A20 | Wrong Origin/Host or token redirect | No data disclosure or forwarded credentials |
| A21 | Missing retained event window after restart | Explicit epoch/gap; no cursor pretending continuity |
| A22 | Override removed/unsupported picker route/effort | Rejected; configured/sent/reported remain distinct |
| A23 | Merge against stale head/checks or inaccessible rules | Merge not submitted |
| A24 | Leave supported locale keys incomplete | Parity test fails; machine IDs unchanged |

Coverage must also include useful success paths. A service that blocks everything is not a passing C implementation.

## 5. Concrete pure-test and integration-test conventions

Use `ControlError.code` for stable assertions, never translated strings. Create test-only context factories in `tests/control_mcp/conftest.py`, defaulting to zero write scopes. Fake contexts are allowed only for unit tests; HTTP tests authenticate through a controlled signing issuer and real verifier.

```python
import pytest
from downstream.control_mcp.contracts import ControlError, require_access


def test_read_scope_never_implies_merge(control_context):
    ctx = control_context(scopes=('hermes:read',), profiles=('p1',),
                          workspaces=('w1',), expires_at=200)
    with pytest.raises(ControlError) as caught:
        require_access(ctx, scope='hermes:repo:merge', profile_id='p1',
                       workspace_id='w1', now=100)
    assert caught.value.code == 'insufficient_scope'
```

The NEW `control_context` fixture is a callable that constructs the immutable ControlContext defined in Task 1 using explicit test issuer, resource, subject and client defaults; it never reads an OS credential store.

For a worker operation, assert both positive and negative effects: before trusted approval the host execution counter is zero; after the bound decision it is one; after reconnect/repeated submission it remains one. Test the actual owner callback and result, not only a mocked `approved` value.

For each task, record a failing test on the pre-implementation source, then the minimal change, a successful focused run, the affected regression suite and a logical commit. Never retroactively call tests written after production changes “strict TDD”.

## 6. Evidence and completion contract

A final report must include: frozen base, feature HEAD, PR/check SHAs, changed files, capability matrix, producer route observations, exact test commands and results, native Windows evidence, real container evidence, mutations killed/survived/invalid, languages covered, two-client protocol evidence, live Codex/ChatGPT read/write evidence and remaining risks.

Distinguish these stages:

`DESIGN_APPROVED → PLAN_APPROVED → IMPLEMENTED → LOCAL_TESTED → CI_VERIFIED → DEPLOYED → CLIENT_AUTHENTICATED → READ_VERIFIED → APPROVED_WRITE_VERIFIED`.

The present deliverable is the plan. None of the product-test/deployment stages is asserted by this document. A lack of a Docker daemon, suitable OAuth issuer or available ChatGPT write entitlement is a named acceptance blocker, not permission to weaken security or declare success.

## 7. External specifications and client checks

Consult the current official pages at implementation time; API/product availability can change:

- Codex/shared MCP: https://developers.openai.com/codex/mcp/ (redirects to the shared MCP guide).
- ChatGPT developer mode: https://developers.openai.com/api/docs/guides/developer-mode
- ChatGPT availability: https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt
- MCP transports: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- MCP authorisation: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- GitHub pull requests and expected-SHA merge: https://docs.github.com/en/rest/pulls/pulls

The repository's SDK pin and negotiated client protocol are authoritative for actual SDK calls; the linked protocol snapshot is not an instruction to downgrade them. The two OpenAI pages currently differ on Pro write availability, so record the installed client/account outcome instead of promising compatibility from documentation alone.

## Plan review gate

Review Tasks 1–3 first: the read facade, actual approval owner and resource authentication establish the boundary for all later C operations. After plan approval, implement in order in an isolated worktree. Do not attempt a single large unreviewed patch or route development through the currently unconfigured production Engineering Router.
