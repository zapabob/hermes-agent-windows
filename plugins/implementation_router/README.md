# Native sequential engineering: agent and operator contract

The native adapter and opt-in entrypoint are implemented on this branch. Check
`STATUS.md` and the exact PR-head checks for qualification; code presence does
not constitute a release, a live-account test, or a successful deployment.

## Purpose

The workflow is **planner → worker → deterministic verification → reviewer →
worker**. It is neither parallel MoA aggregation nor transport fallback. It
adds no Codex SDK, Codex App Server, login flow, credential store, session
registry or replacement scheduler. It uses the existing Hermes auxiliary
picker, host inference facade, native tools and Docker environment.

Enable `implementation_router` through the existing plugin manager. The
existing **Models → Auxiliary models** picker (and `hermes model`) then offers
`engineering_planner`, `engineering_worker` and `engineering_reviewer`. Select
any supported concrete model/provider there, including named custom endpoints.
There is no new model catalogue or brand allowlist. Explicit selection is
required; `auto` is not an authorisation to try other providers. An unavailable
model stops the run. Catalogue membership does not prove account entitlement.
The picker owns configuration. Do not send provider/model/auth overrides in a
workflow task. Native provider-specific request shaping remains authoritative;
no universal reasoning-effort mapping is invented by this plugin.

## One-prompt entrypoint

The registered tool is `engineering_run(workspace, task)`. In a session:

```text
/engineer {"workspace":"sample","task":"Implement the specified behaviour using TDD."}
```

The operator must first enable the feature and configure the workspace policy:

```yaml
plugins:
  enabled: [implementation_router]
  entries:
    implementation_router:
      settings:
        enabled: true
        workspaces:
          sample:
            path: C:/Projects/sample
            image: sha256:REPLACE_WITH_A_LOCALLY_PREPARED_IMAGE_ID
            source_paths: [src, tests, pyproject.toml]
            protected_paths: [tests/acceptance]
            checks:
              - id: acceptance
                argv: [/usr/local/bin/python, -m, unittest, discover, -s, tests/acceptance]
```

The image is prepared explicitly by the operator. It must contain `/bin/bash`,
`/bin/sleep`, `/usr/bin/env`, `/usr/local/bin/python`, and all offline build/test
dependencies the task requires. The execution mode never pulls an image, starts
a login, installs host software, or inherits Docker proxy/auth configuration.
It requires a local Linux Docker engine; Windows hosts can use Docker Desktop's
Linux engine. Absence of that boundary is an error, not permission to use an
ordinary same-user Windows or POSIX shell. Other Hermes modes are unchanged.

Source paths are explicit, bounded, non-secret inputs. Known credential files,
symlinks, hardlinks, special files and traversal paths are not admitted. Review
the selected source content: no generic scanner can prove that arbitrary source
text contains no secrets. Do not select private credentials disguised as source.
Limits are 2,048 files, 512 KiB/file and 16 MiB total. Work on a bounded source
subset and prepare dependencies in the pinned image; runtime network access is
disabled. Every protected acceptance path must be included in source inputs.

## Host-only authentication and containment

Contract: `host-brokered-credential-free-v1`.

Only the parent Hermes process resolves provider credentials, refreshes OAuth
and holds authenticated SDK clients. Stage actors are data-only conversations,
not credential-bearing AIAgent children. The existing `ctx.llm.complete` runs
with `allow_fallback=False` and an expected native-picker route. A changed
selection is rejected before client construction. No auth object, token,
auth-store path or provider exception body is included in a stage handoff.

Each run creates a fresh native Docker environment with no host bind mounts,
credential/skill/cache mounts, forwarded environment, network, privileged mode,
Docker socket or shared host process namespace. Its root filesystem is read-only,
capabilities are dropped and no-new-privileges is set. Execution is non-root;
root is used only by host-owned file import/protection operations in tmpfs.
Descendant environment maps are constructed, never copied from the parent.
Native launchers use `close_fds=True`. The parent's sudo password is not supplied
on stdin. Cloud configuration, Git configuration and home paths point at empty
in-container locations. Child/grandchild inheritance is separately tested.

An empty environment or Git worktree is **not an OS sandbox**. The actual Docker
configuration and running process tree are inspected before admission, stages
and verification. If the measured boundary is unavailable,
`credential_boundary_unavailable` stops the run. A dataclass admission receipt
is not a cryptographic proof. The trusted host, local Docker daemon, pinned image
and installed in-process plugins are the trust base; a malicious administrator,
daemon, image or already-authorised host plugin is not contained by this feature.
No claim is made that Windows handle isolation is proved by a POSIX-only test.

NVIDIA NeMo Switchyard and MoA are not modified or replaced. Fixed-stage routing
must not be silently rewritten by an external routing policy. Provider-returned
identities and request-selected identities are different observations; do not
infer an actual provider/effort from a model's prose. A routing middleware that
cannot respect fixed selections must not be used for these slots.

## Actor and evidence protocol

Actors return one JSON envelope. `action: tool` names only the stage's available
native tools and permitted arguments; `action: finish` contains the structured
plan or worker result. Planner/reviewer have read access only. Workers can use
native read/write/patch/foreground-terminal operations. They cannot choose host
paths, credentials, sibling task IDs, force approvals, background sessions or
new agents. Tool/source content is data, never an authority to change policy.

Plans contain objective, constraints, steps and acceptance criteria. Workers
return `READY` or `BLOCKED`, summary and decision_required. READY is a request
for verification, not a successful test verdict. Protected acceptance probes
remain root-owned and read-only. The host executes operator-defined argv from
the immutable image without the worker's mutable shell snapshot or PYTHONPATH.
Required check IDs, real exit codes, run/workspace/attempt/revision and before/
after source digests must match. Missing evidence is never a pass.

A conclusive failed check permits the configured finite worker retry/replanning
budgets. `UNKNOWN` completion, timeout, cancellation, lost environment or
transport ambiguity cannot launch another writer. No abandoned subprocess may
survive verification. Native environment recreation and transport-level command
replay are disabled while this binding is active. Stage histories are append-
only and bounded; only structured handoffs cross stage boundaries.

The original checkout is never changed by this tool. After host verification,
the result contains a `verified_workspace` path in profile-owned plugin data,
plus a digest receipt and an fsynced event journal. Applying that copy or opening
and merging a PR is a separate host action under normal approvals. A surviving
`.lease` means a run did not conclusively finish cleanup: inspect its journal
and Docker state before an operator removes the lease. Do not auto-expire or
replay it. The workflow does not claim restart-resume support.

## Tests, portability and authorship

Use isolated worktrees and exact SHAs. Read actual native Docker E2E, Windows
contracts, full repository CI and deliberate mutation outcomes. A mocked provider
response does not establish paid-account/OAuth entitlement; an environment
inspection mock does not establish OS containment. Protected tests can detect
known sabotages, not prove that every possible implementation is correct.

Upstream #103346 and #87179 concern operator-owned delegation profiles/personas.
This workflow consumes the existing auxiliary picker and does not copy or replace
those resolvers. No code from either PR has been transplanted. Preserve source
revision and actual authorship if a later salvage incorporates code;
`Co-authored-by` is for genuine incorporated work, not implied endorsement.

## Localisation

`en`, `ja`, `zh`, `zh-hant` and `ar` use the native language inventory. Model-picker
labels/hints, result messages and concise guides are translated. Arabic uses
RTL presentation. Protocol names, state and reason codes never change with
locale. Unknown host text is not echoed as a translated error. English is the
fallback for an unsupported locale; configuration identifiers are not translated.
