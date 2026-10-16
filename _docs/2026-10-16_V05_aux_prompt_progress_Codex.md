# V05 auxiliary prompt progress implementation record

## Purpose and source

Continue the authorized frozen v0.22.2 semantic adoption from local parent
8eea9970e6b211e84d2b50c0aeb2c68678aec28e. U02 save/retirement, separate-process
writer and configuration ABA changes remain in 54c6f5680033c3d7ae8364ab3ad3743db5909508.
The parent remains the only product writer; one readonly reviewer independently
executes bounded owned verification. Authority ends at an explicit-path local
commit. PRIMARY and production are protected.

The canonical pre-implementation prompt, PC/project AGENTS, Windows platform
contract, Common/Start Gate/Skill Selection/Security/LLMOps/Python SOPs and the
fixed implementation instructions govern this work. Incompatible identity,
product and tool claims in the supplied prompt do not override actual tool or
instruction authority. No formal standards certification is asserted.

## Implementation and decisions

See the detailed scoped behavior, changed owners, limits and residual gates in
[the public checkpoint](../docs/windows/v0222-release-baseline-20261015/V05_AUX_PROMPT_PROGRESS.md)
and [source/evidence receipt](../docs/windows/v0222-release-baseline-20261015/V05_AUX_PROMPT_PROGRESS.json).
Capability remains in the existing route/model registry, progress parsing in
one shared helper, and compression authority in the original commit fence.
Queue and generation are not discounted; only measured forward reading is.
Dedicated progress locking settles close/update races without waiting for an
active commit. No second lifecycle owner or global setting is added.

## RED, GREEN and review

Initial owned regression: 9 failures. Route expansion: 11 failures/12 passes.
Independent review exposed individual/shared ceiling bypass and settled-Future
polling; the 48-case RED had three failures, including 7792 polls in 0.1 seconds.
The close race was independently identified and reproduced for extend and touch
(two RED failures at the assignment seam). Final behavior/boundary unit coverage
is 50 cases. Product changes stay bound to final tests and CodeGraph.

Accepted final composite: 248 PASS, 14 files, no failure/error/skip. Independent
execution: 63 repeated new cases, not an additional unique count. Deliberate
in-memory anti-fixes: 17 detected, 45 assertion failures, no errors/skips.
Historical whole-file timeout, cold-start timing failure, NUL guard refusal
and invalid mutation harness runs are retained with replacement mappings.
Product source, lock and test hashes are checked for every accepted source node.

## Commands and evidence

Native Python: .venv/Scripts/python.exe -u -B; pytest plugin autoload disabled,
asyncio plugin explicit, addopts empty, fresh process per file or bounded test
node, no cacheprovider, isolated HOME/temp and sanitized credentials. The owned
run_owned.py records XML, before/after hashes and Python audit containment.
Accepted groups are final-fast (unit result replaced), final-unit-stable,
final-compression (timeout file replaced), overrun-final2, final-concurrent-0/1/2
(two NUL refusal cases replaced), review-fork-recheck. The independent group is
reviewer-final. Details/hashes live in tmp/probes/v05-aux-progress-20261016 and
are summarized in the public receipt without publishing raw logs or user data.

CodeGraph is invoked through the existing npm-shim with CODEGRAPH_NO_DOWNLOAD=1
and DO_NOT_TRACK=1. Main index sync/query/impact is supplemented by the bound
method projection because its hard 1 MiB parser limit excludes gateway/run.py.
New source/tests have focused Ruff checks; existing modules are compared against
HEAD diagnostics by code/message/source line, with zero introduced diagnostics.
No unrelated lint cleanup is included.

## Preservation and rollback

Previous protected WIP and seed receipts remain byte-identical; primary HEAD,
base dependency bytes/file sets and verified overlays are rechecked. Explicit
staging excludes old WIP, seeds, .env, runtime payloads and probes. Index/commit
blob equality and exact scope are checked, and the shared hook is preserved.
LEFTHOOK=0 affects the commit command only. Rollback is a later reviewed inverse
commit. Push, PR, main merge and live operations are outside this execution.

## Residual work

The original goal stays active. Exact-route declared progress support is scoped
progress, not managed-runtime ownership evidence. Full V05/A18/A23, awake-clock,
status/autoload, memory-budget/model completion, original units, retained gates,
8-hour soak and three real sleep/resume cycles remain mandatory open. No
dedicated Windows trial environment exists; no live workstation power action
is undertaken. Continue with managed-runtime source ownership and the next
unclosed frozen-source contract in the isolated worktree.
