# Main integration candidate, 2026-10-16

## Authorization and scope

The user proposed committing/pushing and merging main without a semantic-version
increase. The user also asked whether PR review responses were being performed
without permission. No PR was fetched, created, commented on or responded to by
this work. Internal independent review is restricted to the authorized local
implementation and merge resolution. Existing GitHub js-autofix.yml, triggered
by main TS/JS pushes, independently contains an automatic repair-PR path; it is
not the agent reading/responding to a PR.

Protected PRIMARY: C:/Users/downl/Documents/New project/hermes-agent at
53b65c99587f7c1fe437a44c32d1566576376a17. Qualified source ROOT remains at
bb4d2c0c8d8b91ebb3a08546ef365ecc00b83fc7 with its existing unrelated dirty WIP.
Candidate branch: codex/v0222-main-integration-20261016. Main is first parent,
qualified local feature history is second parent. This merges previously
implemented local work; it is not a blind merge of the frozen upstream release.
The source instruction campaign remains active and incomplete.

## Reproduction and selective resolution

Main's tools/mcp_tool.py fails compile with IndentationError at line3672.
The automatic merge retains that broken code. Its main-only hunks are inside
MCPServerTask._run_http and run: duplicate/missing indentation, deleted timeout/
TLS initialization, unconditional OAuth and a malformed preflight block.
After CodeGraph owner/caller inspection, those two affected method ranges were
restored to the previously qualified local implementation. The resulting MCP
raw blob is 4ebace2875d4b1f5de47dbd6913e632e65c67cd8 and SHA-256 is
6deb4568cb0a487e923d67d482f9b559d190d47c83d09b5e58519b0f3ab9495f.
At that initial resolution, all nine other main-only blob/gitlink paths were preserved, including Familiar,
Yuanbao, lm-twitterer and .gitmodules. Gitlink equality is not runtime proof.

Four new regressions prove actual entry into the mocked HTTP/SSE sessions,
initialize/ready state, conditional OAuth provider acquisition, TLS/client-cert,
connect/read timeouts and caller protocol-header preservation. Early-return
without transport entry cannot pass. Three in-memory anti-fixes are detected
by ten test failures, zero errors/skips. Not all ten failures are assertion
failures: undefined-variable faults are represented as ordinary test failures.
The four mock cases do not prove real TLS handshakes or nonempty SSE factory
argument forwarding; existing regression/source inspection and actual owned
SDK redirect cases provide complementary, separately scoped evidence.

Desktop E2E typechecking exposed TS6307: an existing mcp-oauth.spec.ts import of
apps/shared/src/json-rpc-gateway.ts was not listed in the composite project.
Only that shared file is added explicitly to tsconfig.e2e.json includes. Strict,
composite, inherited options and excludes remain unchanged. Renderer/Electron
checks exit0; E2E changes from exit2 to exit0 using the actual compiler.

## Native/local qualification

Accepted local regression composite: 538 PASS, 26 test files, zero failure,
error or skip. Internal independent re-execution: four new mocked transport
cases plus six actual SDK/owned HTTP redirect cases, ten repeated PASS, not an
additional unique count. Separate source review approves the explicit TS
include. The 71 config-binding tests run in four disjoint bounded filters:
native21, relay21, rest26, remaining3. Their JUnit case identities are disjoint.
An earlier 300-second whole-file run is retained and unaccepted; its owned
process tree was terminated by the harness. No external process was targeted.

Python changed-file compile:171 source/test files valid before adding the new
regression (that additional test is collected/executed). Ruff with the project
configuration exits0 with zero diagnostics. A malformed historical noqa warning
is retained in stderr and is not a clean-stderr claim. Windows footgun scan:
1527 files, no findings. Desktop ESLint exits0, zero errors and164 warnings;
this is not a zero-warning or zero-auto-fix-diff claim. No JS autofixes were
applied. Downstream policy validation passes. Carry metrics are stale before
the merge commit and must be regenerated from committed HEAD by the existing
generator, with no policy weakening, then checked in a subsequent docs-only
commit before CI/main promotion.

Native Python3.12.13 and previously verified locked SDK/test overlays are reused.
Candidate .venv, root node_modules and Desktop node_modules are junctions to the
existing isolated source worktree dependencies, not new installations. Python
audit containment denies writes outside the candidate, including borrowed SDK
paths; tests use isolated HOME/temp and no provider credentials. TypeScript
build-info paths are explicitly inside the owned candidate probe directory.
ESLint uses no cache and no fix. This is not a fresh locked npm installation
or whole dependency-closure proof. Initial redirect failures caused by the
missing candidate-local .venv reference are retained and replaced only by the
same six actual SDK cases on the bound reused runtime.

Actual CodeGraph1.6.0 identifies the original MCP and shared TypeScript owners.
The final private index has11 parsed files,938 nodes,2784 edges,pending0. Twelve
input hashes bind exact candidate copies; the JSON configuration itself is
reviewed directly and verified by tsc, not counted as a parsed source file.
This is a partial owner graph, not full-repository caller closure.

Private raw artifacts, intermediate failures, exact source pins and review
receipts live under tmp/probes/main-integration-20261016. No private raw log,
operator config, environment secret, runtime payload or old unrelated WIP is
staged. Independent approvals are limited to the selected MCP restoration,
new transport test and explicit E2E include; they are not full-main stability
approval. Final source/version/commit audits and CI remain separate gates.

## Remaining publication and stability gates

No version owner is changed. Before main promotion require source-bound merge
commit inspection, fresh carry reports, exact-SHA native/full-main CI and Git
remote equality. GitHub CLI authentication currently fails both with inherited
environment and stored CLI credentials. This is not proof that Git transport
credentials also fail; no credential values are printed or manually extracted.
No main merge/push, release/tag or live-service operation has been performed at
this checkpoint. A later inverse commit is the rollback path; do not reset or
clean protected worktrees. The shared stale Lefthook launcher is preserved and
LEFTHOOK=0 may be scoped to the local commit command, without claiming hook pass.

Managed-runtime automatic capability/ownership, full frozen-plan requirements,
real-model completion, eight-hour soak and three actual sleep/resume cycles
remain mandatory OPEN. No dedicated Windows test PC/VM is available. Local
checks and a version string do not establish stable release readiness.

## Follow-up main Settings regression

Additional validation of the preserved main LM-twitterer source reproduced five
existing failures. Its explicit keyword constructor silently ignored media_dir,
memory_bridge_enabled, memory_db, memory_recall_limit and memory_writeback_enabled.
Five explicit per-instance assignments restore the supplied settings while
retaining main's keyword constructor and all other defaults. No external post,
live configuration or real memory database is touched.

Three new consumer tests fail before the fix and pass after it: disabled recall
must not open an existing scoped database (bridge False / limit zero), and the
configured limit must bound results from an actual isolated SQLite database.
The existing20 plugin and3 writeback cases also pass. Main Yuanbao SSRF2 and
pipeline70 cases pass on its preserved source. The initial claim of nine exact
main paths is historical: LM-twitterer now has this minimal semantic repair;
the other eight blob/gitlink paths remain identical to main. Independent
Settings approval and fault-injection results are attached separately rather
than rewriting the prior MCP approval. The updated local accepted composite is
538 unique PASS across26 files, zero failure/error/skip. Whole-main CI remains
an independent gate.

Settings follow-up qualification:26 local PASS and26 independent repeated PASS.
Five constructor faults are detected by seven ordinary test failures, zero
errors/skips. Together with the transport faults this is8 detected faults and
17 test failures; undefined-variable/TypeError failures are not mislabeled as
assertion failures. Eight other main-only paths remain unchanged. The final
source graph binds12 exact inputs and parses11 files (938 nodes,2784 edges,
pending0). Independent approvals remain scoped; they do not certify the whole
campaign or main's long-duration stability.
