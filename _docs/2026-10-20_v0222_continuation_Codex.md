# v0.22.2 continuation — 2026-10-20

The human requested implementation within 80 percent usage. START_PROMPT (2).md
and FULL_IMPLEMENTATION_PLAN (2).md are requirement inputs, not independent
authorization for publishing, main updates, production restarts or OS changes.
The existing active goal is reused. Account usage observed at start was 7 percent;
the first subsequent observation was 8 percent. No absolute token budget is inferred.

## Baseline, standards and isolation

Protected primary and reused isolated codex/v0222-selective-20261017 both began at
d50995b06d636e6118214b68789f344882773f3a, tree a939bf0fa9c9f4830d7555ffe303c7f5049394c6,
with no tracked/untracked Git WIP. Ignored prior evidence/WIP remains preserved.
The current session turn_context attests gpt-6.1-sol/high. Inputs, execution
identity and frozen source/tree hashes are recorded under tmp/continuation-20261020.

Applied: PC/home and Codex AGENTS, required canonical CLAUDE-FABLE-5.md context
subject to higher-priority identity/tool/environment instructions, repository
AGENTS, common MILSPECLLMOps, implementation-start, skill-selection, application
and Python SOPs. Skills: goal, milspec-codex-standard, hermes-agent,
executing-plans and agent-self-review-evolution (review-only). Exact immutable
v0.22.2 campaign inputs supersede the old September campaign snapshot only for
this continuation; no old frozen record is overwritten. No formal MILSPEC
certification is asserted.

Tests use the existing qualified v0216 .venv dependency runtime through uv
run --no-project --offline --python <absolute-interpreter> python -B. The current
worktree's end-user .venv has no pytest; its failed collection is excluded.
PYTHONPATH and loaded workspace-module assertion bind product imports to the
current worktree. No dependency install, venv synchronization or lock change.

The retained Windows Job owner creates children suspended, assigns each to its
own kill-on-close Job and resumes only afterward. A fresh process runs each file.
HOME/profile/config/credentials/APPDATA/userData/watchdog/temp are task-owned;
secret loading and launcher self-repair are suppressed before product import;
registry writes are denied. Inherited Git routing is removed and a no-parent-repo
probe must fail. The first runner placed temporary fixtures inside the checkout:
LSP's filesystem .git walk ignores Git ceiling, invalidating two no-workspace
fixture assumptions. Subsequent runs use a unique sibling task-owned directory
outside any Git project; the affected suites are rerun unchanged. No fixture
or product assertion is removed. Evidence directories are retained.

## T01 — inventory verification

The existing original parent-diffs.raw, history-index.jsonl and first-parent.txt
match the three recorded byte sizes and SHA-256 hashes. Streaming enumeration
and frozen Git rev-list confirm 22,565 commits / 23,218 parent edges. Selected
LSP/status paths occur on 346 candidate edges; these are path candidates only.
This continuation has not semantically mapped those edges. Mapping remains
0 accepted / 23,218 unknown here; coverage is null. The 27 attachment observations
are not subtracted from commit counts. inventory-verification.json preserves
the exact original paths, hashes and candidate identities.

## T03a — Python package project roots

The behavioral RED was three failures and three passes: package/setup.py was
mistaken for a project marker, and the real manager/client started a second
stdio child for one project. The minimum change adds an optional package skip
to nearest_root and its existing root helper; only the Python resolver enables
it. TypeScript and other language marker semantics remain unchanged. No upstream
factory/module restructuring or PM dependency is introduced.

The new tests cover package root reuse, genuine nested projects, non-Python
markers, exclude precedence, a real marker above the ceiling with an unbounded
contrast, marker-free workspace fallback, and useful diagnostics through a real
stdio child. The external deterministic language engine is a fixture; the
production root resolver, manager, client and framing remain real. Installed
Pyright engine quality and a packaged Desktop journey are not established.

Accepted per-file results, SHA-256 source bindings and exact commands are in
CONTINUATION_T03A_20261020.json and private result.json/JUnit/logs. Each accepted
run has no failures/skips/errors/timeouts and zero Job descendants before any
recovery. A first diagnostics-field run passed assertions but left three owned
descendants and is excluded; its sibling-temp rerun exits cleanly.

Four source-bound in-memory anti-fixes are detected by behavioral assertions:
package check removed, all projects forced to one root, Python denied entirely,
and ceiling removed. Source bytes remain unchanged. The first three use the
earlier six-case test snapshot; the ceiling control uses the later seven-case
snapshot. They are not reported as one exact-source full campaign mutation run.

Independent review identified one P2 (a vacuous ceiling check). Its contrast
and fallback coverage were added; scoped rereview closed the P2 with no further
actionable findings. Fresh pinned CodeGraph 1.6.0 has separate D/R/U indexes and
an exact 23-file candidate root graph, 548 nodes / 1,470 edges, zero pending.
Callers/impact were inspected. affected returned no tests, so direct owner/caller
tracing defines regression selection. Whole-repository/dynamic-reference coverage
is not claimed. Ruff and git diff --check pass for the changed root slice.

## Self-review and residual scope

Self-review-event: qa_defect. The missing interpreter capability, incomplete
fixture signature, vacuous ceiling assertion and nested-temp assumptions were
recorded and corrected at the narrow test/harness scope. No AGENTS/Skill/SOP or
automation is edited. Failed and excluded evidence remains available. The
prevention checks are actual interpreter import, full constructor signature,
positive/negative marker contrasts and non-repository task TEMP.

T02 trust boundary, T03b provider list, T04 packaged/public journeys, T05
Security/MCP effects, T06 run authority, T07 real incremental local recognizer,
T08 local model/sleep qualification, T09 cold vendor independence and T10 full
campaign acceptance remain separate. Main, production services, dependencies,
version, publishing and physical sleep/reboot are unchanged by this work.
Rollback of the isolated root slice is its explicit commit inverse after preserving
later work; no reset/clean/stash or production rollback is performed.

## Subsequent selected regressions

The T03a product/test/receipt commit is e71ab4272b6, followed by the explicit
implementation-log commit 9aab2ee6848. The hook reports lefthook unavailable;
this is not recorded as a passed Git hook.

T04 current existing-owner regressions pass 57 cases in five fresh Windows Jobs:
cron baseline 9, TTS preservation/rollback 11, support secret boundary 30, PTY
replacement/liveness 6, actual owned ConPTY child effect/release 1. No failures,
errors or skips, no timeout/recovery and zero descendants. The existing feature
owners are not reimplemented. These selected checks do not close fresh packaged
UI, favorites/restart, actual channel/model, or full T04 acceptance.

T00's pure Desktop protocol/app-env/fixture suites pass 23 cases, zero pending.
They verify the actual protocol helper's undefined/empty/0 worker contracts;
main's caller passes process.env.TEST_WORKER_INDEX. Electron is fake in this
unit selection and no native Desktop is launched. No host association is read,
repaired or registered. Exact source/commands are in the separate
CONTINUATION_REGRESSION_20261020.json receipt; no Python/Desktop test totals
are combined as campaign acceptance.

The qualified dependency interpreter is Python 3.12.13 with pytest 9.1.1,
pytest-asyncio 1.3.0, pywin32 311, openai 2.54.0 and Ruff 0.15.10. It is reused
without installing/upgrading dependencies. Module lookup observes faster_whisper
and sounddevice but no sherpa_onnx/vosk. No local incremental recognizer/assets
or actual audio recognition is qualified, so T07 remains NOT_ACCEPTED.

Pinned Git history identifies the Python-package-root contract source as
4dac5f28af54001b899c9b6fc8ba81cb58da2f0e, authored by Teknium. Its title also
mentions execute_code process cleanup, which is not adopted or reviewed by the
T03a slice. The contract is present in the frozen U final source. Downstream
composition and tests are by Codex; this is distinct from upstream authorship.
GHSA reporter/discoverer attribution is not applicable to this root-routing slice
and no unverified security contributor identity is inferred.

## T03b — observational provider summary

The default/short summary adds one unique Providers display-name list, preserving
the selected Provider and Model. Empty configuration renders none connected;
corrupt/unreadable snapshots render unknown. Existing full/all/deep dispatch is
preserved. Inventory reuses canonical provider identities/labels, custom config
compatibility and the established current/global auth paths. It does not refresh
catalogs, migrate/seed credential pools, start authentication or probe endpoints.
These are configured credential signals, not live endpoint/token health.

Real subprocess tests exposed an import-time side effect: models._xai_curated_models
called the repairing cache loader and moved corrupt catalog files before status
ran. The existing cache owner now has an explicit read_only path; its default
quarantine/repair behavior remains covered. Source review also closed two P2s:
explicit scoped Bedrock signals and per-provider global-pool fallback. The fast
AWS signal helper is shared in the existing model-switch owner rather than
duplicating SDK/admission logic. No SDK credential chain is added.

The final collection is 44 nodes: 28 non-matrix cases plus 16 exact real CLI
default/short cases. Parent verification independently compares JUnit node names
to the collected union: 44/44, no repeats/omissions/failures/skips. Batch
deselections are explicit and not counted as passes. A 180-second file-level
timeout is excluded and preserved; bounded exact-node batches cover the complete
same-source set. Additional models.dev 68 and xAI catalog 5 regressions pass.

Five source-bound in-memory real-CLI anti-fixes fail behavioral assertions:
empty list, read error presented healthy, added DNS probe, omitted AWS signal,
and omitted global-pool fallback. Each mutant affects an actual fresh CLI worker,
has zero collection errors/timeouts/recovery and leaves source unchanged. The
last two use exact final positive-test bytes, resolving the evidence limitation
that the original focused P2 RED/GREEN test-file hashes differed.

Independent frozen six-file rereview closes both P2s and reports no further
actionable findings. Parent pinned CodeGraph 1.6.0 indexes ten exact selected
status/config/auth/catalog owners/tests, 1,311 nodes / 3,946 edges, zero pending;
caller/impact identify the actual summary and direct test consumers. This remains
selected-source evidence, not whole-repository or whole-campaign acceptance.
CONTINUATION_T03B_20261020.json binds the final source, commands and results;
expanded private argv/resources stay under tmp, while canonical commands use
workspace/runtime placeholders. The LSP trust WIP is not part of this slice.

## T05 scoped MCP protocol qualification and Windows fixture repair

The fresh-process qualification exposed a fixture sharing race: Windows could
publish a marker path before its contents were readable. The helper now retries
only missing-file and permission failures under the original eight-second
monotonic deadline, and still rejects any marker other than exact observed bytes.
No production MCP owner was modified and no assertion was removed.

A real deny-read Windows handle supplies the deterministic RED control. The
historical RED fails the expected behavioral wait assertion, without collection
errors or forced cleanup. Later test scaffolding changes improve cleanup, so the
record does not claim identical final test bytes across that historical RED.
The final reviewed process suite passes five cases: real fresh-process saved
disable/reenable, lock/unlock, abort while locked, invalid bytes, bounded missing
marker. The actual stdio/loopback HTTP suite passes four more cases with nonce
file effects. All accepted runs have zero failures, skips, timeout, forced Job
recovery and surviving owned descendants, with unchanged bound source bytes.

Independent review closed two P2 findings: cleanup must verify and terminate the
actual worker separately from its venv launcher, and WriteFile must be inside
the protected try with an independent finally for the Windows handle. Final
source review has no remaining P1/P2 in this two-file scope. Parent independently
audited the final JUnit and source hashes. Pinned CodeGraph 1.6.0 covers ten exact
selected owner/test files, 1,555 nodes / 4,372 edges, zero pending changes; helper
caller/impact outputs are retained. This is selected protocol qualification,
not full Desktop/OAuth/profile acceptance or complete dynamic call coverage.

CONTINUATION_MCP_20261020.json records the scoped result and exclusions. Failed
and intermediate runs remain private under the task scratch directory. No
production restart, dependency change, release or push was performed.

## T05 explicit restoration policy and Windows private staging

Current restore code rescan results requiring review did not prevent ordinary
restoration. Independent investigation correctly identified an undocumented
restoration-policy decision rather than treating execution policy as automatic
restoration authority. The human explicitly chose refusal until scanner recovery,
including force. The shared vault owner now rejects typed REVIEW before publishing
plaintext, while keeping healthy CLEAN/WARN, explicitly forced malicious restores,
and the existing force requirement for allowlisted malicious verdicts.

Fresh independent review found a pre-existing creation-time Windows ACL exposure
in the same staging path. Parent confirmed inherited reader access before the
first actual plaintext write. Windows staging now supplies a protected owner and
LocalSystem DACL to CREATE_NEW, keeps the exclusive HANDLE through full write and
flush, and removes owned staging on failed/partial writes. POSIX retains the
private mkstemp FD through writing. Same-cycle source review closes the confirmed
P1 with no remaining concrete finding in this patch scope.

Final frozen sources pass restoration policy 23, native Windows ACL/write-lifetime
3, existing API 12 and existing three-dimension security 27. Each accepted run has
zero failures/errors/skips, timeout, forced Job recovery, surviving owned children
or outgoing network attempts. Real inert-file hash detection, AES-GCM vault,
Windows DPAPI/ACL, metadata and CLI/API effects are used; external detector verdict
fixtures do not establish real scanner accuracy. Final source-bound faults fail
for removed review gate 16, force bypass 8, deny all 6, success-only 23 and unsafe
inherited staging 3. Original policy RED shares final policy test bytes; historical
ACL RED predates observer strengthening, with exact-final-test unsafe-staging
counterfactual retained separately. No existing assertion was removed.

Pinned CodeGraph 1.6.0 final selected graph covers 29 source/test files, 2,013 nodes,
5,234 edges, zero pending changes. Private raw execution evidence and the scoped
report are retained through Codex Security managed storage; the new continuation
receipt records collection identity and digests without personal runtime paths.
Earlier EICAR-dependent failures remain unaccepted: inputs were absent on later
inspection, cause unestablished. Initial asyncio audit and snapshot-observer
mistakes are preserved and excluded. Full scanner assets, Desktop journeys,
POSIX native execution, CI and whole T05/campaign acceptance remain open. Host
security settings, dependencies, production processes and main were not changed.

## T05 actual native YARA Unicode paths and CI selection

Real installed yara-python 4.5.4 failed Windows Unicode filepath inputs, including
a clean file. Windows scanning now opens through Python and supplies a read-only
mapping to YARA, preserving the timeout and typed-error handling without a second
full-payload copy. Empty files still execute rules. POSIX keeps the filepath API.

Nine final native cases use inert owned bytes and actual YARA rules, Windows vault
encryption/DPAPI, rescan failure and recovery, force/refusal, destination preservation
and authenticated tamper rejection. Unicode/long/ASCII paths, empty-file matching
and handle release pass. The native ACL suite gains only the windows_only marker;
its assertions are unchanged. Both native files are discovered by the OS enumerator
and pass the actual CI marker expression (nine plus three). The fork native list
also includes these files and the restoration policy suite. No dependency changed.

Existing bounded-security owners pass 79, with four excluded skips for a POSIX-only
process-group case and unavailable Windows symlink privilege. Every accepted run
has zero errors, timeout, forced recovery, surviving owned children or outgoing
network attempts. Exact final test bytes fail for old filepath behavior five,
empty-always-clean one, eager payload copying five, success-only seven and deny-all
nine. Historical pre-expansion RED remains separate. Independent source review
found no product issue and closed its native CI-selection P2 after the marker and
workflow changes. Parent independently audited execution and unchanged source hashes.

Pinned CodeGraph 1.6.0 has 31 exact binding entries, 30 indexed files, 1,939 nodes,
4,966 edges, complete state and zero pending changes/references. The selected graph
excludes unrelated changing config.py and does not establish repository-wide
dynamic completeness. Thirty-five managed persistent artifacts retain raw logs,
JUnit, Job receipts, helper hashes and caller/impact evidence. The new YARA receipt
records the scope; the earlier restore receipt remains historical. Cloud CI,
ClamAV/feed accuracy, native Desktop and full campaign acceptance are still open.

## T09 category plugin secret declaration discovery

Actual PluginManager discovery reaches plugins/category/name, while secret-name
discovery previously missed that category level. The existing declaration owner
now descends one category only, preserving native/portable directory ownership,
yaml precedence, malformed-declaration refusal and profile/core/provider precedence.
No plugin is executed merely to inspect its declarations, and no shared cache or
central approval/catalog policy is introduced.

The owner suite passes 227, existing subprocess environments 21, category scanner
12 and selected existing native CLI/terminal one each. Parent independently reran
the eight cold native-child cases: synthetic CUSTOM_LOGIN is absent, ordinary
values and exact nonce survive; malformed declarations prevent child effects.
These are real environment-owner effects, not complete product-entry E2E. The
missing-discovery and allow-all faults fail eight each; deny-all fails four valid
positive cases. Historical RED predates the final whole-file test expansion;
the final missing-discovery fault supplies the exact-final-test counterfactual.

Independent source review reports no concrete finding in this two-file slice.
Parent independently checked JUnit, source hashes, artifact hashes, containment
and all 16 graph copies. CodeGraph 1.6.0 has 1,159 nodes and 3,010 edges in the
selected graph; dynamic and repository-wide completeness are not established.
Accepted runs have zero failure/error/skip, audit violation, timeout, forced
recovery or surviving owned descendants.

The separate full native file timed out after 180 seconds, without final JUnit;
four owned processes were recovered and zero remained. Cause is unknown. Its
progress dots supply no accepted passes and this record does not call it a known
baseline issue. Full native qualification, vendor independence and full T09 remain
PARTIAL. The continuation receipt records that limit and managed persistent audit
identity; raw task-owned evidence remains retained. Dependencies, primary main,
production processes and host security settings were not changed.

## F05 typed TUI branch syntax and shared help

Shared branch help now advertises the already existing --here flag. Source review
found typed TUI input previously became a literal --here-prefixed title. The typed
producer now supplies an explicit parse_slash_args boolean, and the existing RPC
owner uses the shared leading-flag parser only for that typed input. Structured RPC
names beginning with --here remain literal. Aliases, mixed case, Unicode, default
names and non-leading flag text retain their intended behavior.

Parent independently reviewed all seven changed files and reran the final bytes:
145 Python owner/regression cases and 85 actual producer unit cases pass. A
source-extracted callback bridge feeds the real RPC/SQLite owner and proves child
prompt/history/linkage, unchanged parent bytes and reopened persistence. It is not
an interactive frontend journey. Exact-final-source faults fail three cases when
typed parsing is removed, three when structured names are globally parsed, five
when the producer marker is removed and one when the help hint is removed.

All eleven parent Jobs have zero timeout, forced recovery or surviving descendants;
all accepted cases have zero failure/error/skip. The new CodeGraph 1.6.0 selected
index has 18 files, 1,369 nodes and 4,462 edges, complete state and zero pending
changes/references. Changing unrelated Gateway routing code is excluded from this
graph; its separate regression receipt binds the bytes actually exercised. Old
worker runs remain historical rather than substituting for the parent final-source
runs. Full TUI build/typecheck, interactive TUI/Desktop and cloud CI remain open.
No dependency installation, production restart or primary main edit was performed.
