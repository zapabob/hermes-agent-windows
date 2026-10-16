# Request-scoped prompt progress and compression budgets

Date: 2026-10-16 JST. Parent: `8eea9970e6b211e84d2b50c0aeb2c68678aec28e`.
Frozen upstream reference: `d923a5eb487a17c0a68801bba9ef0f56c81040a8`,
tree `5a064077e8d1de9fc7a4b27efc04f0caa2cb06c0`.
This checkpoint advances V05 A18/A19/A20/A23. It does not close those full
acceptance rows, V05, the original U01-U18 campaign, or the retained gates.
The source-bound evidence is in [the scoped receipt](V05_AUX_PROMPT_PROGRESS.json).
The earlier [receiving-stream checkpoint](V05_PROMPT_PROGRESS.md) remains a
historical description of its parent source; this checkpoint supersedes its
statement that auxiliary requests have no progress support.

## Behavior

Main and auxiliary chat-completions requests now use the actual selected
client base URL and final runtime model to consult the existing per-model
custom-provider capability registry. Only strict boolean `prompt_progress: true`
authorizes automatic `extra_body.return_progress: true`. Locality, family
probes, model-name similarity and an unrelated provider route grant no such
capability. Explicit caller values, including False, take precedence; other
extra_body fields and config objects are preserved. The existing config owner
is reused without new environment variables, probes or lifecycle authority.

The existing main receiving-stream high-water parser is shared with auxiliary
sync/async/forced-stream paths. Only forward, valid integer processed counts
refresh logical idle time; repeated/reverse counts, usage and empty metadata
do not. Real text, reasoning, tool-call and finish events keep their existing
assembly paths. A capable auxiliary route streams even without a display hook.
An unsupported explicitly requested extension is not silently retried through
a non-streaming bypass.

Measured monotone time_ms on a forward count credits at most the observed
interval, bounded by the server's measured reading-time delta. Missing,
non-numeric, boolean, negative and nonfinite durations grant no total-budget
credit. Unmeasured queue/load delay and generation remain charged. Auxiliary
individual ceilings and the original compression fence deadline are enforced
independently. Sync compression hosts and asynchronous gateway hygiene wait on
the same extended deadline. A completed worker's TimeoutError takes the failure
path immediately instead of being polled as a pending stream.

Progress hooks, reading-credit callbacks, deadline getters and latched
cancellation remain bound to the original attempt, including copied provider
thread contexts. Clearing a later host Event cannot revive that attempt.
Cancelled/revoked/expired/committing/closed fences reject late telemetry and
reading credit. A short dedicated progress lock serializes close with admitted
updates. Both callback lock acquisitions are nonblocking; close never waits on
the durable commit lock. A retired heartbeat cannot republish activity, while
a legitimate new compression episode can replace a previous terminal stamp.
No prompt-prefix, toolset, transcript-role or canonical-chat contract changes.

## Verification and evidence boundaries

The accepted composite contains 248 PASS across 14 test files, zero failure,
error or skip. Independent execution repeats 63 new cases: 50 unit/boundary,
11 actual SDK/owned HTTP peer cases and two actual gateway message-handler
cases. Those repeated 63 are not added to the 248 unique accepted tests.
Actual HTTP fixtures exercise main/sync/async requests, capable/unknown/explicit
opt-out wire bodies, and a protected provider daemon plus compression host
that completes past its initial ceiling only when measured reading advances.
A duplicate-count peer still sends real HTTP frames but loses logical idle
and cannot commit its late result. Fixtures use synthetic credentials and
models, isolated HERMES_HOME/temp directories, finite peers and owned teardown.
They do not qualify a real loaded model, real backend abort on every transport,
Desktop operation or live service deployment.

Seventeen disposable in-memory faults are detected by 45 assertion failures,
zero collection/setup errors or skips. Product/runtime files are unchanged by
fault injection. Three independent review findings were reproduced and fixed:
individual ceiling bypass when sharing a deadline, settled-Future polling and
close/update races. The existing callback-exception regression now synchronizes
commit admission and advances a virtual clock, then proves the overrun callback
was reached; cold imports and scheduler timing cannot substitute another path.

Intermediate failures remain unaccepted. The 300-second whole-file timeout
has its partial log and owned-process teardown record. Early mutation-harness
failures are retained. Two background-review regressions initially hit a test
containment refusal for Windows NUL stdout; the replacement guard permits only
the canonical null device and the same two tests pass. The final receipt names
all substitutions rather than declaring every raw run green.

Containment covers Python audit events in each test interpreter, not the OS or
arbitrary children. Accepted raw runs report 220 refused outside-workspace
write attempts and 90 refused OpenRouter DNS attempts, including the earlier
NUL false positives; these are not successful writes, calls or paid inference.
The sanitized child environments contain no provider credentials. No paid API
call is used as evidence. No new dependency installation is performed.
Previously verified locked test overlays are reused; base versions, complete
file sets and bytes for 16 distributions/837 files, 372 named locked payloads,
and 2784 SDK payloads match their prior snapshots. This is not full dependency
closure. Lock and manifest remain unchanged.

Actual CodeGraph 1.6.0 is used before/after the owner changes. Its 1 MiB
extraction ceiling omits the 1,577,221-byte gateway/run.py file. A separate
private real CodeGraph index covers the exact selected method and original
imports at their original line positions, plus four byte-identical agent files.
The receipt binds the full gateway SHA, method SHA, projection SHA and indexed
owner. This supplements the main index; it does not claim gateway-wide graph
coverage. Runtime gateway regression evidence complements static limitations.
A focused lint comparison finds no introduced diagnostic; gateway's 67 existing
selected diagnostics remain unchanged. New source/tests pass selected syntax,
undefined-name and whitespace checks. This is not a whole-repository lint pass.

## Authority, preservation and remaining work

Only explicitly listed source, tests and new documentation enter the local
commit. The protected primary remains at
`53b65c99587f7c1fe437a44c32d1566576376a17`; earlier unrelated WIP/seed receipts
remain byte-identical and unstaged. The prior U02 fix at
`54c6f5680033c3d7ae8364ab3ad3743db5909508` and its cross-process writer/config
A-to-B-to-A evidence remain preserved. They are not recounted as newly run tests.
The stale shared Lefthook launcher is unchanged; LEFTHOOK=0 is scoped only to
the local commit command and no hook pass is claimed. A later rollback uses a
reviewed inverse commit, preserving unrelated work.

Managed-runtime automatic ownership/capability binding remains mandatory OPEN;
config-declared exact-route support cannot stand in for managed process proof.
Awake-clock qualification, status/autoload, memory budgets, real model
completion, remaining original units and retained gates remain open. Eight-hour
soak and three actual sleep/resume cycles are unexecuted: no dedicated Windows
PC/VM is available. User workstation sleep/reboot is not used as a substitute.
No push, PR, main integration, version bump, release, live config/service/model
change or production deployment is performed. No full release readiness or
formal MILSPEC compliance is claimed.
