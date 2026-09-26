# Hermes Control MCP — Design for ChatGPT and Codex Desktop

Status: proposed design for operator review; not a deployed or tested MCP service.
Date: 2026-09-23.
Repository: `zapabob/hermes-agent-windows`.
Inspected base: `34562508555d84f0740eda7a0af5ec4ff90bbe60`.
Design branch: `docs/hermes-control-mcp-c-20260923`.

## 1. Approved intent and scope

The operator selected option C: expose Hermes state and evidence, operational controls, configuration changes and development/PR operations to both ChatGPT and the Codex desktop app. Use the existing Hermes harness and its authorities. Do not create an independent agent runtime, approval authority, model catalogue or process supervisor.

The outcome is a shared, authenticated control-and-evidence service. A client can request work; Hermes authorises and executes it; either authorised client can inspect its actual progress and receipts. This is not automatic access to another client's private conversation, nor an API for consuming the ChatGPT Pro subscription from Hermes.

This design is independent of the ongoing 0.21.4 adoption campaign. Do not change its worktree, branches, files, running services or frozen inputs. This document changes no product version. Creating this design branch does not constitute creating a local isolated worktree; implementation must establish and verify its own worktree after design and plan approval.

C describes supported capability, not blanket permission. Installation defaults to read-only. Each write is subject to operator configuration, client scope, authoritative Hermes approval, current state and execution safety checks. Do not publish the service, install a tunnel, change Codex configuration, create PRs or merge code merely because this specification exists.

## 2. Evidence from the inspected repository

- `mcp_serve.py` already exposes a stdio messaging bridge with conversation, event and approval-shaped tools. Reuse appropriate server/schema conventions, not an unreviewed export of all tools.
- `EventBridge.respond_to_approval()` removes a bridge-local pending item, emits an event and returns `resolved: true`; it explicitly operates without gateway IPC. This is NOT sufficient evidence that the authoritative approval was resolved or an action executed.
- `agent/transports/hermes_tools_mcp_server.py` is an existing Codex App Server-oriented tool bridge. The new feature must not require that runtime or a Codex SDK.
- `hermes_cli/web_server.py` is the existing FastAPI host. Its lifecycle and authenticated host interfaces are the integration starting point; do not launch another backend to impersonate the running installation.
- `plugins/implementation_router/entrypoint.py` and `host.py` own the engineering invocation and its journals. Read or extend those owners rather than infer a run from a chat title.
- The engineering README requires an explicitly configured, local Linux Docker execution boundary, a pinned prepared image, bounded source inputs and protected checks. Its bridge-level observation does not require Docker. Starting an engineering run still requires its existing backend and policy.
- The engineering workflow does not promise restart-resume. Do not advertise pause/resume/retry capabilities until their host semantics are implemented and tested.
- `CARRY.yaml` records Electron main as the Desktop/Python backend owner and the Go watchdog as the embedding llama-server supervisor. Do not revive the retired second Desktop/backend owner.

These are inspected starting points, not a certification of every code path. Before implementation, read current repository instructions and trace the live approval, authentication, task, configuration and Git operation owners. Record their actual callable interfaces in the implementation plan; do not invent methods from names in this design.

## 3. Architecture decision

Preferred: an opt-in Hermes-owned extension with one typed service facade, hosted by the existing parent process, and two MCP transport adapters.

```text
ChatGPT web --- authenticated HTTPS / approved private tunnel ---+
                                                               |
Codex desktop --- authenticated loopback Streamable HTTP --------+--> Hermes Control facade
                                                               |       |
Other local MCP clients --- optional thin stdio adapter --------+       +--> existing approvals
                                                                       +--> existing run owner
                                                                       +--> existing config/picker
                                                                       +--> existing Git/PR operations
                                                                       +--> sanitised evidence
```

Both clients see the same identifiers and operation history when authorised for the same profile/workspace. They must not obtain separate execution owners. Simultaneous writes to one workspace are serialised by the existing host owner or rejected as busy.

Alternatives considered: exposing the legacy messaging server directly would not supply trustworthy control acknowledgements or sufficient remote authorisation; a separate orchestrator would duplicate ownership and risk divergence. A thin facade is preferred. A small host-side extension is legitimate where an observable public seam is missing; an independent scheduler is not.

Keep reusable implementation under an appropriate downstream-owned extension and existing plugin discovery seams. Mount Streamable HTTP into the existing host's lifecycle. Any new route, CLI switch or module name remains proposed until the implementation plan maps it to repository conventions.

## 4. Client compatibility

### Codex desktop

Support Streamable HTTP to the local Hermes service, with MCP-specific authentication. Use the desktop MCP settings or the shared Codex `config.toml` configuration. Do not read, copy or request Codex account tokens or `auth.json`.

A stdio adapter may relay to the same service for compatible local clients. It must not construct authenticated inference agents, read Hermes provider stores or execute a replacement harness. Prefer an approved OS-scoped IPC/pairing mechanism. Any short-lived bridge credential is for the MCP resource only, not a provider credential; never expose it in prompts, tool arguments or logs.

Setup produces a reviewed configuration snippet only after an endpoint exists. Never overwrite the user's entire `config.toml`. Back up, parse, make a targeted change and write atomically only after permission. No auto-trust or global approval-policy changes.

### ChatGPT web

Support authenticated remote Streamable HTTP. A local loopback URL is not directly reachable from hosted ChatGPT; use an operator-approved HTTPS deployment or supported private tunnel. Installing the bridge is not equivalent to connecting it to this conversation.

Official documentation currently disagrees on personal-plan write availability: the developer guide lists Pro/Plus with read/write developer mode, while the Help Centre describes Pro read/fetch-only and broader write support for organisational plans. Test the actual account and client. Record read and write compatibility separately. Never disguise a mutation as a read-only tool to bypass a product restriction.

The MCP server is vendor-neutral. It must not depend on one model name, reasoning preset, OpenAI API key or Codex SDK. A separately selected tunnel may impose its own infrastructure requirements, which require explicit operator approval.

## 5. Read surface and evidence model

Proposed tools, not existing commands:

| Tool | Purpose |
| --- | --- |
| `hermes_get_capabilities` | Authenticated scope, supported operations, transport and host versions; no secret values. |
| `hermes_get_runtime_status` | Actual backend, security, Docker and provider-readiness observations, with timestamps. |
| `hermes_get_run` | Run/workspace/attempt identities, current stage, terminal state and stop reason. |
| `hermes_get_routes` | Existing picker selections and available route observations. |
| `hermes_get_evidence` | Bounded, sanitised test/CI/verification records by opaque evidence ID. |
| `hermes_get_operation` | Authoritative approval and execution progress for a requested operation. |
| `hermes_list_approvals` | Requests visible to this principal; metadata does not confer decision authority. |
| `hermes_poll_events` | Bounded, profile-scoped event delivery with cursor and producer epoch. |

Use the same typed response schema for equivalent tools and MCP resources. Prefer tools for required workflows so client resource support is not a hidden dependency.

Responses include schema version, observation time, producer identity/version, profile/workspace identifiers, relevant SHA and a stable state/reason code. Unknown, unsupported, absent and stale are distinct from false, empty and successful.

Never infer `RUNNING` from an existing directory or `SUCCEEDED` from model text. Do not infer that a selected route was executed. Route evidence separates configured, request-sent and provider-reported model/effort. Unavailable observations remain null/unknown. Actual internal reasoning work is not observable merely from a Medium/High parameter.

Verification evidence records exact source SHA/digest, check IDs, completion, exit codes, timeouts, platform, skipped cases and retries. Separate local tests, mocks, real processes, containers, hosted CI and post-merge validation. A hash identifies content; it is not by itself authenticated provenance. Preserve the existing host receipt trust boundary.

Do not expose arbitrary filesystem reads or raw logs. Use registered evidence IDs, bounded output and explicit field projection. Treat task text, logs, PR comments and source files as untrusted data. Redaction is defence in depth, not permission to export every field.

## 6. C-level operations

Provide explicit, typed tools; no general shell executor, arbitrary RPC proxy or unrestricted configuration writer.

| Proposed operation | Required behaviour |
| --- | --- |
| `hermes_start_engineering_run` | Use an operator-registered workspace/check policy and existing picker routes; require host admission and approval. |
| `hermes_cancel_run` | Request cancellation from the actual run owner; report requested separately from confirmed quiescence. |
| `hermes_reverify` | Execute an approved check set against an identified immutable candidate; never treat it as a read. |
| `hermes_patch_routes` | Propose an allow-listed non-secret change using existing picker/catalogue semantics; require a configuration revision match. |
| `hermes_apply_verified_result` | Apply only a previously verified result to an approved destination with matching base SHA/digest, clean ownership and rollback evidence. |
| `hermes_create_pull_request` | Use an allowed repository and exact source branch/SHA through the trusted host Git/PR path. |
| `hermes_merge_pull_request` | Require separate approval, current head/base, required checks and reviews, host authority and repository permission. |

Drafting, editing or publishing a PR description is also a write. Remote-provider URLs or auth endpoints are not accepted through route changes; those need separate local setup approval. Secret configuration, scanner disabling, vault reset, approval-policy relaxation, raw `taskkill`, force-push and branch-protection changes are not exposed through C.

Capabilities are advertised honestly. Resume, pause and retry remain unsupported unless a real public host path can prove their semantics. In particular, retry must not replay an operation whose remote effect is unknown, and resume must not silently create a new writer. Adding a menu item is not implementation evidence.

## 7. Approval and operation lifecycle

C mutations follow:

```text
client request
  -> authenticate and authorise scope/profile/workspace
  -> validate schema and expected state
  -> store immutable operation intent in host-owned journal
  -> request authoritative Hermes approval
  -> trusted human decision bound to the exact intent
  -> recheck revision, SHA, policy and safety prerequisites
  -> host-owned execution
  -> authoritative result and evidence
```

A proposed operation record binds principal, client registration, profile, workspace, operation type, canonical argument digest, expected revision/SHA, expiry and idempotency key. Approval is single-use and cannot be transferred to another operation or client. A changed target or payload requires new approval.

Ordinary model-callable MCP tools must not grant their own approvals. Client confirmation UX is not automatically a cryptographic proof of a human decision. Default approval occurs in Hermes's existing trusted UI. A future remote human approval UI must authenticate the human separately and deliver a digest-bound decision to the same host authority. Do not export `allow-always` as a shortcut.

The existing bridge-local `permissions_respond` acknowledgement is not reusable as a successful authoritative decision. Only report approved/executed after the actual owner acknowledges it. A logged event or HTTP 200 is not sufficient.

Accepted writes return an operation ID promptly; clients poll the shared record. A transport disconnect does not mean the operation failed, nor authorise another execution. Duplicate requests are deduplicated by the host across clients, including concurrent requests and restarts. Use transactional uniqueness and argument-digest comparison. If the host crashes around an external side effect, report unknown and reconcile from the real destination before any retry. Do not claim universal exactly-once execution across external services.

The operation journal extends host control metadata; it is not a second queue that independently launches agents. Where the existing host lacks a safe capability, reject that action until its owner is extended and tested.

## 8. Credentials, authentication and containment

Three credential domains must remain separate:

1. The client authenticates to the MCP resource with a dedicated, scoped grant.
2. The parent Hermes inference broker retains provider API keys and OAuth sessions.
3. Trusted host integration paths retain the separate credentials needed for GitHub or other authorised external actions.

Worker agents and their descendant processes receive none of these credentials. Do not forward client access tokens to provider APIs or workers. MCP tokens must be issued for and validated by the intended resource, with issuer/audience/expiry/scope checks. A generic gateway token must not automatically become a C-level authorisation.

Reuse existing secure storage and established authorisation components. Do not implement an ad hoc token store or assume an existing gateway login already implements MCP OAuth discovery. Trace its suitability first; if an additional standards-compliant resource adapter is needed, keep it inside the host authority with narrowly scoped storage.

Remote access requires TLS and proper OAuth metadata/PKCE support appropriate to the supported clients. Validate origins/hosts and approved public metadata URLs; prevent DNS rebinding, token passthrough and SSRF. Loopback is not an authentication substitute. Identity, profile and workspace permissions come from validated host grants, never a client-provided `user`, `approved` or `client_name` string.

The bridge's read paths must not decrypt provider vault contents, install Docker, pull images, initialise a new vault or refresh model credentials just to display status. Report DPAPI or scanner faults as infrastructure state. Never disable protections to make a write succeed.

Docker is not necessary to observe state or select a reasoning setting. The current engineering run still requires its configured Docker execution boundary; this MCP feature neither removes that requirement nor adds an implicit Windows shell fallback.

GitHub operations belong to the trusted parent integration path. Do not give a general worker process a PAT, OAuth token, SSH agent socket, credential helper or authenticated SDK object to publish its own changes.

## 9. Concurrency, privacy and model-facing contract

ChatGPT and Codex may read the same run concurrently. Writes use revision checks and an authoritative workspace lease. Stale configuration, a changed branch head or an expired approval returns a conflict requiring refreshed intent, not last-writer-wins.

Events include producer epoch and bounded cursors. A restart or retention gap returns an explicit gap requiring a fresh snapshot. The bridge does not invent success by replaying cached events. Profile authorisation applies equally to tools, resources, event streams and error details.

Do not mutate earlier model messages or prompt-cache prefixes to inject progress. Keep stage history append-only and send only approved, bounded task/evidence data across clients. Connecting ChatGPT is an explicit data-sharing action; show which profile, repositories and evidence categories will be exposed.

Model-facing server instructions begin with the essential rule: inspect capabilities/current state before writes; request only the named operation; never infer approval or successful execution; never ask for secrets. Tool descriptions explain when to use them and the precise constraints. Write tools have truthful non-read-only annotations. Server-side policy remains authoritative regardless of annotations.

Reuse the authoritative locale registry at implementation time. Translate user-facing statuses, help, approval summaries and error explanations for every supported locale; preserve stable machine IDs and support RTL presentation. Do not assume the historical five-language or upstream seventeen-language inventory applies unchanged.

## 10. Acceptance and adversarial tests

Use TDD with observed behavioural RED, minimal GREEN and affected regression suites. Record exact SHAs. The design adds no claim that any of the following tests have run.

Required negative/contract cases:

- An invalid, expired, wrong-audience or wrong-scope grant cannot read protected evidence or mutate state.
- A caller cannot select another user's profile/workspace through arguments, resources or event cursors.
- Read-only tools do not start agents, decrypt stores, refresh auth, change config or run tests.
- A forged `approved=true`, fake model receipt or legacy bridge-local approval event cannot execute a write.
- Expired/replayed approval, changed arguments, changed config revision, and changed PR SHA all refuse execution.
- Duplicate and concurrent submissions produce one host admission; restart after an uncertain side effect does not replay it.
- Failure to deliver a decision to the live approval owner never returns approved/executed.
- Cancel acknowledgement is distinct from confirmed termination; no new writer starts while completion is uncertain.
- DPAPI failure, scanner error and missing Docker remain distinguishable and never weaken policy.
- Synthetic provider/Git/MCP secrets are absent from child/grandchild environment, arguments, files, handles and bridge responses to the extent the platform tests can establish.
- No arbitrary paths, traversal, symlink/junction escapes, oversized evidence, unsafe redirects or untrusted command fields are accepted.
- Model removal, unsupported effort and policy changes after admission are rejected; configured/requested/provider-reported effort are not conflated.
- PR creation and merging use trusted host credentials; no direct main push or automatic `ci-reviewed` label is permitted.
- Main merge checks are re-evaluated against the current exact head/base and required branch rules, without a bypass.
- Locale parity and machine-code stability hold across every enabled transport.

Deliberate mutations must test gate removal, approval replay, scope confusion, stale-SHA acceptance, false success, ambient credential inheritance and client-confirmation-as-host-approval. Syntax/import errors do not count as behavioural mutation detection.

Integration acceptance requires actual MCP initialise/list/call tests, live host approval and result acknowledgement, Windows native process tests, and two concurrent clients. Record Codex desktop and ChatGPT web read/write connections separately. A test client, mock OAuth server or stdio-only success does not prove that this Pro account can use remote writes. Real Docker acceptance remains a separate engineering-backend test.

## 11. Delivery and review gates

Implement in independently testable slices after review: host read/evidence facade; authenticated MCP transport and client setup; approval-bound operational controls; configuration and verified-result application; trusted Git/PR actions; end-to-end interoperability and localisation. The subsequent implementation plan must name actual host interfaces and tests for each slice.

Keep feature code out of main until required exact-head CI and security review pass. Then use the normal downstream PR/merge policy and verify post-merge CI. Do not touch upstream PR #119964 or the 0.21.4 worktree as a side effect. Explicit operator approval is still required to enable C on the running installation or expose it remotely.

Completion evidence must distinguish: design, implementation, local tests, adversarial tests, CI, deployed endpoint, client authentication, read calls, approved write calls and actual external results. Report pending, skipped and blocked stages as such.

## 12. Sources checked for this design

Repository sources are pinned to the inspected base:

- https://github.com/zapabob/hermes-agent-windows/blob/34562508555d84f0740eda7a0af5ec4ff90bbe60/AGENTS.md
- https://github.com/zapabob/hermes-agent-windows/blob/34562508555d84f0740eda7a0af5ec4ff90bbe60/mcp_serve.py
- https://github.com/zapabob/hermes-agent-windows/blob/34562508555d84f0740eda7a0af5ec4ff90bbe60/hermes_cli/web_server.py
- https://github.com/zapabob/hermes-agent-windows/blob/34562508555d84f0740eda7a0af5ec4ff90bbe60/CARRY.yaml
- https://github.com/zapabob/hermes-agent-windows/blob/34562508555d84f0740eda7a0af5ec4ff90bbe60/plugins/implementation_router/README.md
- https://github.com/zapabob/hermes-agent-windows/blob/34562508555d84f0740eda7a0af5ec4ff90bbe60/plugins/implementation_router/entrypoint.py
- https://github.com/zapabob/hermes-agent-windows/blob/34562508555d84f0740eda7a0af5ec4ff90bbe60/plugins/implementation_router/host.py

Official client/protocol documentation checked on 2026-09-23; recheck before implementation/deployment:

- https://developers.openai.com/codex/mcp/ (redirects to current shared MCP documentation)
- https://developers.openai.com/api/docs/guides/developer-mode
- https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt
- https://developers.openai.com/plugins/build/mcp-server
- https://developers.openai.com/plugins/build/auth
- https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices

This document approves no runtime action and asserts no completed product test. The next gate is operator review of this design, followed by a concrete implementation plan and its execution approval.
