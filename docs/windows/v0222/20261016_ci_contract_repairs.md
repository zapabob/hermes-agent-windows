# CI contract repair qualification, 2026-10-16

The overall CI run 38854337830 for `c0afdacde56cb22e4c32be3f42ed28eb43c3ebfe`
failed its Python job 116822375530: 45,406 passed, 48 failed, 667 skipped,
and one test file exceeded the unchanged 300-second subprocess limit.
Windows Tier 1, downstream Windows release checks, Nix and Docker succeeded
for that SHA. Those successes did not constitute an all-green overall CI.
This document records the local repairs; a new pushed SHA still needs its
own completed workflow results.

## Runtime correction

The subprocess guard exposed a real new implicit environment inheritance
in `plugins/familiar/core.py`, rather than an acceptable baseline change.
Both `familiar status` and the injected `Popen` launch now use the existing
`hermes_subprocess_env()` owner. They do not request provider credential
inheritance. Familiar's own non-Hermes settings and executable search path
remain available. The existing exact trusted Desktop-user launch gate,
command line, vendor working directory and idempotent launch lock remain.
The status probe also uses the existing Windows `CREATE_NO_WINDOW` flag;
the launch already used it. Familiar/VRChat was not actually launched.
The pinned existing vendor `246831133ef6d9738085f370c45dc2805f8741ed`
config/CLI source confirms that config path, port and body-control token are
Familiar-owned settings, and that `run` starts the body separately from `mind`.
Their synthetic values are retained in both boundary regressions.

Two synthetic-secret boundary regressions failed before this correction.
All 20 Familiar plugin tests pass afterward. They check removal of model,
messaging, GitHub and auxiliary credentials, retention of Familiar settings,
profile home and PATH, unchanged process argv, launch gate and window flags.
The repository subprocess guard now passes all five tests without approving
the new unsafe Familiar fingerprint. Its separate obsolete cron raw-env
exception was removed: the actual cron owner already uses the central
sanitizer within the target profile scope. Nineteen neighboring Bot Chat
delivery/profile tests passed in the worker's isolated runs.

## Test contract corrections

The auxiliary Anthropic fake now accepts and asserts the actual required
keyword-only `provider` using autospec. Credential refresh asserts the
provider alongside the existing new token, URL and old-client close checks.
Local/Docker environment doubles initialize the real shared state; the
Docker execute-only double retains a valid snapshot. On Windows its real
shell assertion selects Git Bash explicitly instead of the WSL launcher.
The four targeted file/method runs pass 11 tests, with no skips. These are
test fixture repairs, not production changes to credential ownership.
The parent additionally ran both complete Docker-environment and run-agent
test files together using actual MCP 2.2.0: 340 passed, zero failures,
errors or skips in 330.94 seconds. That broader run exposed one unhandled
thread warning: the persistence-race fake DB lacked the existing async
token-accounting `flush_token_counts` method (introduced in `174ad459393`).
Treating thread warnings as errors reproduced a failure in that exact test.
The fake now records the token flush and asserts exactly one flush, while
retaining the shared-marker/locking assertions. The test permanently treats
unhandled thread warnings as errors. The repaired race test plus all three
credential-refresh tests pass, four total, without warnings.
The combined run's containment also blocked external model-metadata DNS
lookups. It is not real container/provider execution or per-file canonical
CI isolation; its original warning-bearing receipt is retained.

Queue/steer tests now inject generation changes and public Stop immediately
after the real claim lock is released. The previous injection hook had moved
before claim, where adopting the current generation or observing an already
cleared queue is correct. Restoration, FIFO, no dispatch and no replay
assertions remain. Both local and compute-host paths and pre-claim controls
are covered. The two files plus neighboring ownership tests pass 98 tests.
Four in-memory source mutations are rejected by the intended assertions;
the product source is unchanged by both the repair and mutation probes.

OAuth dashboard/callback fixtures persist their intended configuration in
their private profile before starting authorization. Cleanup tests recognize
the actual owned Event.wait/Thread.join stack frame by object identity,
instead of depending on two hard-coded SDK worker line numbers. Anonymous
rejection still asserts failure and no stored tokens; its message comparison
is case insensitive. The four complete files pass 28 tests with real MCP
2.2.0, zero skips. The adapter fault-injection double supplies WinError and
get_last_error on a per-instance ctypes facade for cross-platform CI; all
seven targeted adapter tests pass. This does not claim execution of native
Windows debugging APIs against a real process.

Fifteen translation catalogs gain the seven existing `gateway.branch` keys,
using matching placeholders. English and Japanese are unchanged. The i18n
file passes 36 tests; additional catalog formatting and unchanged-content
checks pass 138 assertions. Native-speaker review was not performed.

## Preserve the complete configuration-binding suite within the CI limit

`tests/tools/test_mcp_oauth_config_binding.py` formerly collected 71 cases
in one subprocess. Its function bodies and fixtures now live in the shared
`tests/fakes/mcp_oauth_config_binding_contract.py`. Three explicit collection
wrappers partition native, relay and REST surfaces without dropping cases,
adding skips or changing the generic CI timeout/retry policy.

| Surface | Cases | Local elapsed | Result |
| --- | ---: | ---: | --- |
| Native, RPC mutation and writer controls | 24 | 200.27 s | PASS |
| Relay | 21 | 131.44 s | PASS |
| REST and REST mutation controls | 26 | 175.54 s | PASS |

All 21 shared top-level function bodies were compared by AST with the
pre-split committed source. Every body is structurally identical; only the
surface parametrization moved into the collection wrappers. Each wrapper
ran in a fresh Python process with actual MCP 2.2.0, private HERMES_HOME,
private temporary files and synthetic loopback protocol peers. The private
driver's outer watchdog was 900 seconds for qualification; every actual
test file completed below the unchanged 300-second CI limit. This is a
local measurement, not a prediction of hosted-runner timings.

## Evidence and limits

Retained local evidence is under `tmp/probes/main-integration-20261016/`:
`ci-repair-20261016/` holds parent-run JUnit, output and containment receipts;
`binding-split-source-proof.json` binds the original/shared sources and case
counts; `i18n-branch-qualification-20261016.json` records catalog checks.
Worker records are under `tmp/probes/bounded-compat-6b1ec4d0/` and
`tmp/probes/queue-steer-20261016/`. These private execution logs are not
included in Git. No production configuration, session history, credential
file, original WIP or existing build output was removed.

Actual CodeGraph indexed 11 complete hash-bound maintained files in
`tmp/probes/ci-repair-graph-final-20261016/`, producing 651 nodes and 1,520 edges.
The environment-owner impact resolves both Familiar process boundaries.
The queue worker separately indexed four complete hash-bound files with
893 nodes and 2,177 edges. An empty dynamic-test affected list was not used
as evidence that no tests were affected. Neither scope is a full-repo graph.

Repository Ruff, scoped diff whitespace checks and offline `uv lock --check`
pass. Independent review found no actionable P1/P2 issue across the 33 code,
catalog and test files. It independently executed AST/case-set/YAML checks
and inspected parent JUnit artifacts; it did not rerun pytest or cloud CI.
`tmp/probes/ci-repair-independent-20261016/final-scope.json` binds those
reviewed files by SHA256. Hosted CI remains a separate gate. The prior Python
run's two tests that passed only on automatic retry remain identified as
flaky observations; this patch does not conceal them with new skips or
longer timeouts. Eight-hour soak, real sleep/resume and complete Windows
distribution qualification remain outstanding acceptance requirements.
