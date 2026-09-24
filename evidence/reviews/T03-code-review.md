# T03 Code Review

Reviewed commit `cfde4e5e6b3aea88c22a3887e8b5169722a93fbf` against parent
`7299159af3bb65224e047a7bab386befa6ed5b33` in the T03 worktree.

## Result

- `codeQualityStatus`: `CLEAR`
- `recommendation`: `APPROVE`
- `blockers`: none

## Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

None.

### LOW

None.

## Review evidence

The new typed config in `downstream/control_mcp/startup.py` validates the
trusted in-memory boundary, snapshots the key map, then delegates issuer,
resource, key material, and lifetime checks to `ResourceVerifier` before
routes are mounted. `hermes_cli/web_server.py` creates and mounts the host
only when an explicit config is present; invalid config fails before
`mount_control_mcp`, and an independently pre-supplied host/config pair
raises `route_conflict`. A same-object config reuses its already-mounted host
on a later lifespan. The existing parent token middleware explicitly defers
the three registered MCP paths to the resource-specific ASGI verifier, which
continues to check the bearer token and live grant on every request.

The targeted diff adds no production public key, grant lookup, provider
credential loader, default enablement, listener, or configuration source.
Repository-wide references show the bootstrap state field is only read by
the new lifecycle code and populated by test code, so production stays
unmounted until a trusted same-server owner supplies the configuration.

The added protocol test uses two concurrent locked-SDK client sessions with
separate client registrations and non-overlapping profile grants. It also
checks no-config disablement, untyped configuration rejection, invalid-key
configuration failure before mounting, route ordering before the SPA route,
and host/config conflict preservation. These are behavior tests rather than
prompt, literal, or implementation-mirroring tests.

Independent verification passed:

```text
uv run --frozen --extra dev --extra slack python -m pytest \
  tests/control_mcp tests/e2e/test_control_mcp_host.py -q \
  --basetemp=<isolated-review-basetemp>
196 passed, 1 skipped
```

`git diff --check` passed for the reviewed range.

## Skill-perspective check

The required `remove-ai-slops` and `programming` skill files were not
available in the configured skills directory or skills catalog. I applied
their requested review criteria directly: no deletion-only, tautological,
constant-mirroring, or brittle prompt tests were added; no untyped escape
hatch, needless abstraction, or unnecessary production parsing or
normalization was introduced. No violation found.

## Remaining validation limits

This commit intentionally provides no real operator-owned key/grant source.
The passing tests prove the local in-process lifecycle and two scoped SDK
clients, but cannot prove a future production bootstrap, external client
admission, TLS/listener deployment, or real grant-store availability.
