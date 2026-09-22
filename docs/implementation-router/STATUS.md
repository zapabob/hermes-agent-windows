# Implementation Router — work in progress

**Not a released live-model router; not ready to merge.**
The branch now contains operator-owned, model-neutral stage routes, mandatory
credential-free host admission, zero-ambient-inheritance environment helpers,
localised results and agent/integrator documentation. It does not register or
enable a plugin, launch a native child agent, or add an authentication store.

Start with [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md). Localised guides:
[English](i18n/en.md), [日本語](i18n/ja.md), [简体中文](i18n/zh.md),
[繁體中文](i18n/zh-hant.md), [العربية](i18n/ar.md).

## Source and verification provenance

- Downstream main base: `15f60413bd5d5394aeb8e374c52c1010b8052224`.
- This extension begins at `9ce101210fccdda0b90111c3aae7b98589708626`.
- Historical upstream comparison: `71a2fe399bbd7a219c71f9d9fca2b313b01f2057`;
  this is not a claim to have rebased or ported onto a later upstream main.
- Previous 29-test/10-mutation native component qualification:
  https://github.com/zapabob/hermes-agent-windows/actions/runs/35776467212
  That run does not cover this extension.

Local extension qualification, Python 3.13.5 in an isolated **component fixture
worktree**, not a full fetched repository: 58 tests collected, 57 passed and
1 skipped (desktop locale-source parity needs the full checkout). Sixteen
selected behavioural mutations were detected. The first combined mutation
invocation exceeded its execution limit and is not success evidence; the
completed run uses each mutation's relevant test suite after a full green
component baseline. No raw environment output from inheritance mutants is
printed. Review added three failing cases for stale credential directories,
PATH-separator ambiguity and credential fields in disabled configuration;
all three now pass.

The host qualification workflow creates real linked worktrees from the frozen
main and exact candidate, then runs base RED, candidate GREEN and the mutation
suite. Read the actual workflow outcome at the candidate SHA before claiming
native success. Full repository CI, installer coverage, live OAuth, actual
provider/effort/fallback provenance and end-to-end execution remain separate.

```sh
python -m unittest discover -s tests/implementation_router -v
python scripts/ci/implementation_router_sabotage.py
python scripts/ci/qualify_implementation_router.py --base-sha 15f60413bd5d5394aeb8e374c52c1010b8052224
```

## Enforced component behaviour

Routing defaults to disabled. Enabled routes contain exactly planner, worker
and reviewer selections; credentials, auth endpoints, clients and fallback
fields are rejected, including in disabled prepared configuration. No model
brand is special-cased. Missing/unsupported routes must fail before inference.
The kernel requires a trusted native host's run/workspace/route-bound admission
before work, every stage and verification; absent or revoked admission stops
execution. Existing HostPort implementations do not gain permission by default.

The process environment helper constructs a new mapping and uses an empty
private runtime root, rather than filtering a copy of the parent environment.
Real child/grandchild tests use synthetic secrets only. The POSIX descriptor
probe is skipped on Windows: it is not evidence about native Windows handles.
Environment construction is NOT filesystem, memory, network or keychain
isolation, and the helper is not installed across existing terminal paths.

## Remaining merge holds

A real Hermes native adapter must still provide credential-brokered inference,
authorised tool/workspace execution, protected deterministic checks, descendant
containment, durable state, cancellation and effective-route observations.
Its admission receipt must follow actual preflight, not a setting or a fabricated
model response. Current native subagent construction must not be used to pass
credential-bearing AIAgent objects to descendants. The adapter and public
entrypoint are still absent; this branch therefore cannot perform the requested
one-prompt implementation workflow yet. Desktop UI and packaged-resource
installation are also not accepted on the strength of the i18n unit tests.

Upstream #103346 and #87179 overlap in profile routing. Neither is treated as
accepted or superseded. No code has been transplanted; no co-authorship is
claimed. Preserve actual source credit if a later salvage incorporates code.
No competing upstream resolver PR or main merge is authorised by component
GREEN alone. Existing Switchyard, MoA, provider and approval code is unchanged.
