# Native implementation routing: agent and integrator contract

**Status: component and security contracts, not a released live execution feature.**
Read `STATUS.md` before making a completion claim. This document is normative
for this branch; it does not declare an accepted upstream API.

## Purpose and scope

A host-owned sequence of **planner → worker → deterministic verification →
reviewer → worker**. This is neither MoA (parallel proposals and aggregation)
nor provider fallback (transport recovery). The planner, worker and reviewer
may use any provider/model that the active Hermes installation supports and
the operator has explicitly authorised. There is no product-name allowlist,
no Codex SDK, no Codex App Server and no additional authentication store.

The operator owns the immutable `RoutingTable`. A model cannot edit its route,
request a provider credential, introduce a fallback, or increase its budget.
`reasoning_effort` is provider-specific: the actual provider must validate it
before admission. Do not translate unsupported values into a supposedly
similar setting. An unknown or unavailable route stops execution; a catalogued
model is not proof that the account is entitled to use it.

## Host/descendant security boundary

Contract identifier: `host-brokered-credential-free-v1`.

The trusted **parent harness** owns provider resolution, OAuth refresh, SDK
clients, authorization headers, credentials and fallback policy. The route
record contains only `provider`, `model` and optional `reasoning_effort`.
Never pass an AIAgent with an API key, credential pool, authenticated client,
auth-store path, or provider headers to a stage actor or any descendant.
Do not serialize full config, `.env`, auth.json, cookies, bearer capabilities,
SDK responses or provider exception bodies into handoffs, results or logs.

Descendants receive bounded task data and tool permissions, not login material.
If they require inference, the existing host performs the authenticated call.
The host must observe the actual provider/model/effort and enforce the
operator's no-silent-fallback policy; do not infer an effective route merely
from the requested name or from a completion facade that does not report it.
No new provider resolver, approval authority, tool registry, scheduler or
restart loop may be introduced by the adapter.

`HostPort.admit(binding, routes)` MUST preflight the real native boundary and
return a run/workspace/route-fingerprint-bound `CredentialFreeAdmission`.
Its type is a trusted-host receipt, **not a cryptographic sandbox proof**.
Never manufacture it from model JSON, a plugin setting, or a configuration
boolean. The kernel checks it at run admission, immediately before each
model stage, and before verification. Missing, stale, revoked, cross-workspace
or malformed receipts produce `credential_boundary_unavailable` and no further
stage or verifier call. Existing hosts without this method remain blocked.

## Processes and containment

`security.child_environment()` constructs a new environment from explicitly
approved runtime directories and an empty private runtime root. It never
copies `os.environ`. HOME, HERMES_HOME, CODEX_HOME and common cloud/Git config
paths point into that root. No env overlay or credential-passthrough setting
is supported. The canonical host launcher must use `close_fds=True`, no
`pass_fds` or inheritable Windows handle list, and credential-free argv/stdin.
Run Python probes with `-I`. Never work around a denied launch using shell,
MCP, an alternate runner, or a child that logs in independently.

**An empty environment or a Git worktree is not an OS sandbox.** A same-user
process may still read the host's files, inspect accessible process memory,
load a keychain or use cloud metadata/network credentials. The native adapter
must isolate those resources (including credential-agent sockets and broker
connections), close descendant lifetimes on cancellation, and protect its
acceptance probes. In-process Python objects and ContextVars are not a
malicious-child isolation boundary. Do not issue admission merely because
the environment-helper tests pass. No such native adapter is supplied yet.

## Stage and evidence protocol

1. The host supplies a unique run/workspace binding, explicit routes and
   non-empty operator-owned required check IDs. Routing defaults to disabled.
2. The planner returns only objective, constraints, steps and acceptance criteria.
3. The worker returns `READY` or `BLOCKED`, a summary and a required design
   decision when blocked. It does not return an authoritative test verdict.
4. Verification belongs to the host, not the model. Every required check has
   a conclusive exit code and a matching run, workspace, attempt, revision and
   before/after snapshot. Protect tests against removal or weakened assertions.
5. A proven nonzero test exit permits only the configured finite retry budget.
   A design blocker may use the bounded reviewer budget. Timeouts, `UNKNOWN`
   admission/completion, missing receipts and transport exceptions never
   authorise another potentially concurrent writer.
6. Stop/cancellation and durable-checkpoint failures take precedence over
   success. A locale changes presentation, never state, role or policy.

The host adapter must retain native approvals, restricted tools, prompt-cache
prefixes and session/profile isolation. Do not mutate parent or sibling config.
No optional plugin, including NVIDIA NeMo Switchyard, may silently override a
stage's operator-approved route. Composition must be observable and fail closed
when its actual routing cannot be established.

## Configuration contract (not an installed CLI option)

```yaml
implementation_router:
  enabled: false
  roles:
    planner:
      provider: provider-one
      model: your-planning-model
    worker:
      provider: provider-two
      model: your-implementation-model
    reviewer:
      provider: provider-one
      model: your-review-model
```

Replace the illustrative IDs with host-supported selections. This mapping is
parsed by `RoutingTable.from_config(...)`; adding it to config.yaml alone does
**not** activate a plugin. No live plugin/CLI entrypoint exists on this branch.

## TDD, sabotage tests and publication

Use an isolated worktree and frozen SHAs. Run RED before changing behaviour,
then GREEN, then adversarial mutations. Test at least: credential-bearing route
fields, unknown credentials under arbitrary env names, child/grandchild env
inheritance, denied/stale admission, wrong workspace, cancellation, malformed
outputs, false-green claims, unbounded re-entry, and translated-result stability.
Run the native Windows and Linux lanes plus required full repository gates at
exact HEAD. A test-double admission is component evidence only; it is not
live OAuth, native terminal, effective-route or whole-harness certification.

Upstream #103346 and #87179 overlap in profile selection. Do not submit a third
resolver or present either proposal as accepted. Keep this workflow controller
separate from that maintainer decision. No code from those PRs has been copied.
If actual source is salvaged later, preserve its author and source revision;
add `Co-authored-by` only for genuine incorporated contributions, never for
merely citing an idea. Explain retained, altered and omitted portions precisely.

## Localisation

Native locale inventory: `en`, `ja`, `zh`, `zh-hant`, `ar` (Arabic is RTL).
`RunResult.to_dict(locale=...)` returns stable state/reason codes and a localised
message. Unknown locales fall back to English; unknown host text is not echoed.
Guides under `i18n/` carry the same safety and incomplete-status requirements.
This does not add a desktop control or claim that the UI is already wired.
