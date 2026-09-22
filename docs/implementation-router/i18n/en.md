# Stage-based implementation routing

[Agent protocol](../AGENT_PROTOCOL.md) · [Status](../STATUS.md)

<!-- routing-not-moa -->
The parent Hermes harness assigns an operator-approved model to planning,
implementation and replanning in sequence. This is not MoA or provider fallback.
Any host-supported provider/model may be configured; unavailable selections
stop execution rather than silently switching to another model.

<!-- credentials-host-only -->
Authentication stays with the parent harness. Children and grandchildren must
not receive API keys, OAuth tokens, credential-bearing clients, headers or
auth-store paths. The host validates a bound admission before every stage and
verification. A missing or revoked boundary blocks execution.

<!-- not-os-sandbox -->
The environment helper does not inherit the parent's environment and redirects
credential discovery to private empty paths. This is not an OS sandbox:
same-user file access, memory, keychains, network identities and handle
inheritance still require real host containment and native verification.

<!-- native-adapter-unavailable -->
This branch is not yet a live execution feature: the native adapter, entrypoint,
protected verification and full integration acceptance are incomplete. Do not
create a security receipt merely to make execution pass. Configuration alone
does not enable a plugin. Component GREEN is not whole-harness GREEN.

`planner`, `worker`, `reviewer`, `SUCCEEDED`, `BLOCKED` and `CANCELLED` are fixed
protocol identifiers. Presentation supports English, Japanese, Simplified and
Traditional Chinese, and Arabic (RTL); unknown locales use English.
