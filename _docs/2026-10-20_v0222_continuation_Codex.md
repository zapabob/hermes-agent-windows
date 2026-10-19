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

## T01 baseline public-contract review of the mixed kernel/root commit

Original Teknium commit 4dac5f28af54001b899c9b6fc8ba81cb58da2f0e contains both
the already bounded LSP package-root contract and a separate session-kernel
attached-cell lifecycle fix. Original parent and all four changed paths were
inspected. The commit is an ancestor of both R_AFTER and U_RELEASE, so it predates
the release delta inventory; it must not be counted as a mapped edge in that
22,565-commit/23,218-edge population. This uses the separate baseline public-contract
entry required by the plan. The original inventory and zero-mapping receipt remain
immutable, with full semantic coverage still null.

Current code_kernel.py still treats proc=None as dead during concurrent acquire,
reaps/evicts without attached-cell protection and removes entries by key in old
cell cleanup. Final upstream retains the separate settled/dead and attached-cell
protections. This is a source-confirmed gap, not a reproduced current native
failure. No kernel implementation or upstream restructuring is adopted here.
Later kernel cluster commits remain individually unreviewed. The new baseline
contract receipt separates original attribution, final blobs, actual Windows public
caller, vendor edges, risk, required positive/refusal/recovery tests and acceptance.

Fresh CodeGraph 1.6.0 covers nine complete current owner/test files, 699 nodes and
1,804 edges, with complete state and zero pending changes/references. It identifies
execute_code as the caller of execute_in_session_kernel. The graph is reference
only and establishes neither whole-history nor dynamic runtime completeness.

## T08 stream elapsed clocks and diagnostic timestamp compatibility

Sixteen elapsed-time sites in interruptible_streaming_api_call now use monotonic,
preventing wall-clock corrections from prematurely retiring healthy streams or
postponing real stalls. Progress counts, attempt/writer fences, trial, route
capability, auxiliary/compression and function-external behavior remain unchanged.
Independent review found a P2: watchdog instants also fed wall-clock diagnostic
TTFB. The two diagnostic assignments now retain wall time; real initializer and
logger tests detect all four old mixed-clock normal/partial-failure cases. The
same reviewer closed the P2 with no new concrete finding in this bounded scope.

Final-source verification passes 206 cases: 112 in zero-refusal runs and 94 in
guarded existing regression runs. Parent independently reran the focused 12 and
audited all 16 accepted/RED/fault receipts. Actual OpenAI SDK/Relay finite SSE peers
prove completion/stall/cancel/trial and diagnostic effects. Anthropic diagnostics
use finite events/client fixtures with actual helper/Relay/logger; its SDK is not
installed and remains unqualified. Wall-revert, mixed-receive and mixed-diagnostic
faults fail five, four and four behavioral assertions respectively.

All accepted runs have zero failure/error/skip, timeout, forced recovery and owned
survivors. New focused cases/faults have zero audit refusals; existing guarded runs
retain 36 refused external-DNS and 246 refused unowned-connect events. They do not
establish whole-OS network silence. Actual loaded SDK/dependency paths and 1,392
distinct files were rehashed; the final focused run binds 1,370 files. No install
or environment synchronization occurred.

Fresh CodeGraph 1.6.0 binds 15 complete selected files including stream_diag:
1,695 nodes, 5,237 edges, complete state, zero pending changes/references. Dynamic
dispatch is not completely resolved. Earlier 202-case mixed-diagnostic evidence is
retained and superseded for final qualification. Windows sleep exclusion, managed
ownership/capability, actual local model completion, soak, real Anthropic SDK,
cloud CI and full T08/campaign acceptance remain OPEN.

## T04/T10 actual surface typechecks and bounded workspace-link repair

Actual Desktop renderer, Electron and E2E --noEmit compiler configs pass in three
fresh owned Windows Jobs. Composite buildinfo goes into new owned directories;
no old build evidence is cleaned or overwritten. Sources remain unchanged and
all Jobs have zero timeout, recovery, survivors or guard refusals. Node 24.19.0
and TypeScript 6.0.3 implementation hashes are retained; the entry shim and tracked
compiler inputs were bound before/after, implementation/Node hashes after runs.

TUI first reports 111 diagnostics because @hermes/ink is unresolved. The existing
lockfile declares exactly a local workspace link. After checking all physical
parent/target paths and absent destination, only that junction was created inside
the isolated worktree. Lock bytes are unchanged and no package was installed or
downloaded. This leaves 14 diagnostics: missing existing Ink dependencies plus
two strict-type errors in unchanged Ink source. An in-memory CompilerHost overlay
of the fixed D_REVIEW producer yields all 14 exact same diagnostics, so no added
F05 producer diagnostic is observed. TUI typecheck remains NOT_ACCEPTED.

This closes three Desktop compiler gates only. No frontend/native launch, bundle,
addon rebuild, pack, installer, registry write or local-model inference was run.
The old F05 limited receipt remains historical; it is not rewritten as whole-TUI
qualification. The new typecheck receipt records all six runs and the precise
workspace link retained for review; no evidence or target directory was removed.

## T04/T10 existing native staging and unqualified renderer bundle

The actual existing stageNodePtyInto helper completed in a fresh owned Windows
Job with zero guard refusals, timeout, recovery or survivors. It produced 27
node-pty files (2,670,744 bytes); an additional empty run.stdin belongs to the Job
harness. After-run comparison verifies 26 exact installed-source copies and the
remaining unixTerminal.js contains exactly the helper's two existing ASAR path
replacements. Installed dependency source was not bound before this experiment,
so this is limited staging evidence, not native addon ABI/load or ConPTY proof.

The actual Vite renderer build failed during config dependency externalization.
Its Windows net use mapping probe encountered the child-process guard (213
refusals); Rolldown also reported a native Tailwind dependency read as UTF-8. The
secondary error is retained without asserting an independent product defect.
No renderer bundle was produced and the guard was not relaxed. Both Jobs bound
2,361 source/harness files before and after with unchanged bytes and zero owned
survivors. Existing Vite temporary files and earlier build evidence are preserved.

Installed Electron package metadata exists, but its dist directory and path.txt
are absent. No binary was downloaded, installed or launched. Existing Desktop
typecheck passes remain separate from renderer/native/runtime/packaging gates.
CONTINUATION_DESKTOP_BUILD_20261020.json records both outcomes and their exact
hashes. An initial audit incorrectly counted empty run.stdin as an asset and
expected the helper's intentional ASAR rewrite to be a byte-identical copy;
both audit assumptions were corrected before the receipt was published.

## Independently separable LSP URI/document identity slice

Only agent/lsp/client.py and new test_uri_identity.py are selected here. URI
components decode once, UNC authority survives the path round trip, encoded
Windows drive replies resolve correctly, and document stores use platform path
identity while outbound protocol spelling remains unchanged. No trust manager,
server, workspace, config or constructor-adaptation WIP is selected.

Real Git HEAD owner/config/test objects execute through a source-bound in-memory
loader with the candidate client. All original assertions and constructors remain
in force: 48 passes across eight fresh files, zero failures/errors/skips. The
same URI cases with the HEAD client yield eight failures/five passes; eleven
semantic mutants are detected without errors/skips. Parent independently audited
21 source bindings and 20 Jobs, read the immutable 441-node/1,146-edge graph, and
reran the exact 13 URI cases including two real Windows stdio peers. No graph
copy executes and no fake manager supplies compatibility. During audit a receipt
filename assumption was corrected from bootstrap-audit.json to actual audit.json;
no product source or test assertion changed.

The human-delivered final READONLY review supports exactly this two-file split.
The original full T02 remains 167 passes plus one mandatory untrusted-Python
useful-positive OPEN failure. Its test, WIP, native effects, assets and graphs are
preserved. Native UNC shares, native POSIX processes, project-code sandboxing,
full T02/P0, whole-SHA CI and release acceptance are not claimed. See
CONTINUATION_LSP_URI_20261020.json and the retained parent URI audit.

## Shared-input ownership and normalized busy-route scope

The scoped shared-input candidate retains state identity, generation and boundary
epoch through image/model/skill producers, normalization, callbacks, publication
and consumption. The recovered busy path now receives the original captured
owner. It rechecks after compression, steer and voice waits and validates FIFO
head/tail publication and agent mutation under that state's lock. The sole
SessionStateStore atomically publishes each state and its Telegram chat index;
route capture visits only that chat bucket, preserving actual setdefault winners.

Final qualification is 248 unique passes in 27 fresh Jobs, zero failures/errors/
skips. Twenty semantic fault variants in 21 Jobs produce 76 failure occurrences
over 61 unique cases, all successful in the normal union. Parent rehashed all
1,646 sealed artifacts, checked every normal/fault Job and JUnit, and read the
actual immutable 1,789-node/5,661-edge selected graph. Parent fresh reruns pass
34 busy cases plus 31 normalized cases with zero source drift, timeout, recovery
or owned survivors. Synthetic model/config/transport and process-snapshot leaves
are explicit; these are not native channel/model qualification.

The human-delivered same-cycle independent READONLY review confirms both prior
P2 findings closed and no new concrete P1/P2 in the frozen slice. It independently
verified all seven source/test hashes, 1,646 artifacts, 48 JUnits, 1,292 exact
method spans and preserved T06n evidence. All 507 prior evidence files and old
33/31 test bytes remain unchanged. No review-side tests, imports or edits were
claimed. Whole run.py SDK unresolved references remain 8,144. Approval/clarify,
API process cleanup, native channels, full T06 and whole-SHA CI remain OPEN.
See CONTINUATION_SHARED_INPUT_20261020.json; no unrelated API/registry/kernel or
LSP trust WIP is included in this local commit.

## T07 retained incremental-recognizer gate

CONTINUATION_T07_20261020.json preserves the explicitly required
BLOCKED_LOCAL_RECOGNIZER outcome. The bounded earlier metadata/cache inventory
identified no qualified Windows incremental recognizer with a pinned matching
ASR model and owned PCM fixtures. This publication verifies the three current
transcription source hashes against that inventory; it does not refresh package
or cache observations. Existing completed-file STT remains unchanged. No engine
import, model/recording read, download, capture, recognition or production
inference occurred. No schema/ABC/toggle or fixed-text partial is added as a
substitute for actual audio-derived partial/final results. The asset gate and
all useful-effect/runtime requirements remain unaccepted.

## T04/T10 renderer bundle under explicit probe denial

A separate guard derivative returns asynchronous EPERM for the exact existing
Vite optimizeSafeRealPathSync net use callback. It executes no command and
supplies no external data; the refusal remains recorded. Other child operations
remain rejected. This lets actual Vite config externalization use its existing
error fallback. The intermediate attempt then stopped at the app-local config
scratch mkdir. Both earlier attempts, helpers, receipts and logs remain intact.

After verifying the app-local node_modules path and its ancestors are physical
worktree directories, a new derivative permits only newly named Vite timestamp
configuration files there. Existing files are not overwritten or removed. The
actual production build succeeds in 75 seconds with 349 bundle files totaling
40,736,870 bytes. Parent rehashed all outputs, checked three local HTML module/
stylesheet entries and all 2,370 before/after source/runtime/harness bindings.
The Job has zero timeout, forced recovery and survivors; sources are unchanged.
One optional mapped-drive command remains refused and unexecuted. The generated
26,287-byte config snapshot and complete bundle hash manifest are retained.

CONTINUATION_RENDERER_BUNDLE_20261020.json qualifies this restricted renderer
bundle only. Direct Vite implementation and Node executable are bound, but a
complete transitive/native dependency closure and whole-OS write/network monitor
are not established. Existing config deprecation and plugin-size warnings remain
in the raw log. This does not accept Electron executable/native ABI, ConPTY,
GUI/E2E, packaging, installer, unrestricted host build, full T04/T10 or release.

## T02 public TypeScript qualification and shutdown wording correction

The real public write_file_tool/patch_tool path through LocalEnvironment and
configured LSP owners returns actual TS2322 and then fresh clean diagnostics
with the same client. Empty and invalid relative trust configurations both pass;
document version and push counter advance 1 to 3. Four faults (no LSP, always
clean, stale result, deny all) each produce two assertion failures, errors/skips
zero. The five accepted Jobs have no timeout, source drift, guard violations,
extra recovery or survivors. Eight pinned external engine asset hashes remain
unchanged. No product change is claimed by this test-only qualification.

Independent review identified unsupported natural-exit wording: ordinary
shutdown_service can invoke terminate/kill and those leaf calls were not audited.
The test now describes eventual exit after ordinary shutdown and records
post_shutdown_exit_wait_seconds. Parent AST comparison confirms that the only
executable difference is this metadata field rename; assertions are unchanged.
Old test and all five historical Jobs are preserved, and the normal plus four
fault Jobs were repeated against corrected test
270d083d125c72fe6de530b5f74c83db661203c8950e8fc2cdf2d7e9553dd4e2.
Parent rehashed all 44 current evidence files,
73 historical files, 21 current sources and 21 reference copies, all 10 per-case
receipts, and read the immutable CodeGraph DB: 1,418 nodes and 3,822 edges.

CONTINUATION_PUBLIC_TS_20261020.json records the exact limits. This test depends
on task scratch, prior asset receipts, installed absolute paths and uncommitted
T02 trust owners, so it remains qualification WIP rather than portable CI or a
standalone HEAD slice. It is not staged with this record. Historical 167 T02
passes plus the unchanged mandatory Python OPEN failure are preserved. Global
Python startup closure, other engines and whole T02/P0 remain OPEN.

## T06 first approval producer ownership phase

Captured run registrations now qualify queue admission, callback scheduling and
delivery disposition, and finally cleanup. Retired producer contexts never
select the replacement registration. Entry allocation is followed by validation
under owner RLock then approval lock; callback/transport/waits occur outside
these locks. Replacement removes predecessor entries in the same transaction,
then wakes waiters outside locks. The actual no-ID FIFO regression holds A's
send ACK while B becomes visible and completes B before releasing A. Strict
consent admission also retains the inherited producer across entry allocation;
digest, presentation, ticket and once-consumption contracts remain unchanged.

Parent rehashed 2,835 manifest files and reconciled all 72 accepted JUnits/Jobs:
35 normal Jobs/470 unique passes, 36 fault variants/37 Jobs/98 failed occurrences
and 81 unique failed nodes, every failed node GREEN normally. Errors, skips,
guard violations, input drift, recovery and surviving Job members are zero in
accepted evidence. A fresh parent run adds 24 dedicated ownership passes with
the same three source hashes. Independent READONLY final review reports no new
concrete P1/P2 in the declared first-phase scope. Actual immutable CodeGraph
counts are 2,354 nodes/7,038 edges, with the current t06a-owners-p2 binding of
16 files and 1,650 complete matching method spans; full SDK unresolved 8,157.

CONTINUATION_APPROVAL_OWNER_20261020.json records this bounded local integration.
The fixed registry import and empty snapshot/reaper leaves do not qualify native
process cleanup. Initial deadlock/recovered and source-drift attempts remain
excluded; the unchanged Windows symlink-privilege skip remains unqualified.
Clarify, native adapter routing, post-decision persistence/effect boundaries,
complete strict/native lifecycle, kernel/process/API integration and whole-SHA
CI remain OPEN. Other owner WIP is excluded from this commit.

## Bounded session kernel disposal lifecycle

The kernel keeps every owned instance discoverable from selection until actual
disposal is complete and the process is no longer alive. Removing a reuse-map
entry or reaching zero attached callers does not remove disposal ownership.
Owner/all clear therefore finds selected or settled kernels already awaiting
teardown, and a second clear serializes with an in-progress native kill. Pending
selection is distinguished from a dead process; attached cells are excluded
from idle/cap eviction, and old settlement removes only its exact reuse entry.
CellAuthority, context rules and defaults are unchanged.

Final independent READONLY combined review supports only code_kernel.py and the
new attached-cell tests within the known seven lifecycle windows. Parent audit
rehashed all 682 evidence files, 46 current bound inputs and snapshots/runtime
bindings, reconciled all 25 JUnit/Job records and native PID-parent/nonce pairs,
and read the immutable graph: 2,875 nodes/8,350 edges. Independent span review
verified 23 complete files and five projections containing all 636 Gateway
methods. Full original-file SDK unresolved 8,157 remains OPEN.

The refusal-free, skip-free positive subset is 77 passes: native 29, existing
kernel 24 and approval-owner 24. The 56 launcher/interpreter pairs (112 distinct
processes) all exited before harness recovery. Modes 30 passes/9 skips and env
22 passes/1 skip are partial files. The approval cluster's 24 pytest passes have
eight guard refusals and are excluded from refusal-free GREEN. Broad
code_execution remains 1 failure/27 passes/16 skips plus five passing subtests,
from an unchanged AF_UNIX Windows test. These outcomes are not combined into a
fully qualified total. Eighteen fault Jobs/17 variants produce 68 failures over
25 unique nodes that all pass in native29; eight fault Jobs also retain ver
probe refusals and are classified separately from refusal-free success.

CONTINUATION_KERNEL_LIFECYCLE_20261020.json retains all limits. The fixed registry
import and empty Gateway reaper leaves do not accept live API/process r3. Old
evidence, original baseline-contract attribution and 22,565 commits/23,218 edges
with zero fully mapped edges remain unchanged. Arbitrary trees, kill-failure
guarantees, POSIX, managed ownership/model effects and whole-SHA CI remain OPEN.

## Historical native credential proof after exact-listener qualification

The unchanged native credential file passed 28 unique cases on historical r3
registry 5d2d05b8; the separate actual PTY target pass overlaps that file. Both
owned Jobs had zero failures/errors/skips, guard refusals, outer qualification
timeouts, recovery and survivors. Exact-listener permissions are tied to the
same listening socket object/token/descriptor/address/PID and pinned pywinpty
reader/client, not arbitrary loopback. Parent and independent read-only audits
reconciled results, artifacts and 2/15 published Python identity records; native
and -I children remain Job-owned rather than Python-audited. Existing served
profile and benign values stay useful while synthetic launch secrets are
removed. The original 1,054 evidence files and excluded 180-second timeout remain
unchanged.

Codex Security managed storage retains 44 exact-byte artifacts plus a hash index
and qualification note. The versioned canonical bookkeeping pointer is
docs/windows/v0222-release-baseline-20261015/CONTINUATION_NATIVE_CREDENTIAL_HISTORY_20261020.json.
The r3 integration revocation takes precedence over original accepted/local
fields: retained PTY natural-completion monitoring is a later OPEN condition
under R4 repair. These historical credential results do not accept R4, broad
PTY/process lifecycle, complete product-entry E2E, vendor independence or T09.

## R4 actual seal readback and retained integration hold

Parent finally read both actual R4 files at 2026-10-19T21:17:15.1168861Z:
handoff.json is 133,136 bytes with SHA256 247c26c891a4d5d727b6de73c90b2011458b0f8970b64cd064fe99568dfcc91a;
delta-from-r3.patch is 13,467 bytes with SHA256 61c17a30c8850560a88f2928d25f64d9c4148a53eeec0229f86b00693ab9426f.
JSON parsing and text readback succeeded. Complete absolute paths, literal
hashes and actual filesystem readback were forwarded in the reviewer message
body. Earlier absent-file notices were not treated as a freeze.

The parent and independent READONLY reviewer reconciled all 14 candidate
source/test files, 15 saved graph files/projection, 140 named evidence hashes,
28 JUnits/Jobs and old r3 1,441/r2 5,969 preserved files. Normal unique passes
are 223, consisting of 120 required-scope nodes plus 103 extra API nodes from
an accidentally omitted -k filter. The original receipts retain that deviation.
Eighteen fault variants produce 58 failed occurrences over 54 unique nodes,
all GREEN normally; errors/skips/refusals/recovery/survivors are zero in the
qualified rows. Immutable graph integrity is normal with 935 nodes/2,726 edges.
Historical per-run cross-input bindings do not prove a current whole SHA.

Independent source review supports the failed-monitoring natural completion
correction but finds another P2 in the healthy-reader-reopened path. A normal
PTY reader can end while an owned descendant remains; the registry correctly
reopens the session, but after that descendant naturally exits it skips the
public completion reconciliation because monitoring_failed is false. This is
a source condition, not a reviewer native reproduction claim. R4 stays PARTIAL,
P2 OPEN and integration HOLD; native PYWINPTY remains unqualified. R5 is
authorized to obtain the actual owned healthy-reader RED and minimally fix it,
while preserving this seal and all earlier evidence unchanged.

CONTINUATION_PROCESS_R4_REVIEW_20261020.json records the complete readback and
qualification boundaries. No R4 product files are committed by this checkpoint.

## Approval persistence RED and next clarify generation

Parent independently rehashed all 77 T06d RED evidence files, checked the eight
graph files/321 complete spans against their frozen baseline, and read the
immutable 618-node/1,795-edge database. Sixteen saved cases contain 11 legitimate
scope/FIFO/once positives and five behavioral REDs: three retired caller session
grants and two replacement denial tallies cleared by old callers. Independent
review confirms the real wait/caller/boundary/persistence route. The same
boundary retires registration and increments epoch, so these do not isolate
the necessity of epoch alone. The denial values are actual _record_denial
updates, not three real human denial interactions. Product approval remains
unchanged pending the next stable Gateway generation.

Clarify's older coercion retirement and already-registered global interrupt
gaps have bounded corrections, while a new RED-only generation reproduces
post-release prose entering a replacement queue, old reply typing resumption,
and callback registration after global hard interrupt. The first attempted
global case had a fixture setup defect and is excluded; the corrected run has
three behavioral REDs and three current positives, zero errors/skips and
unchanged source. R4 reviewer snapshot readback released Nash's separate product
hold for these minimal owner/generation repairs. Earlier 190 positive cases
and legacy four failing teardown expectations are preserved separately from
their ID-specific test migration. Whole T02/T06 acceptance remains OPEN.

## Bounded clarify lifecycle and shared-pause integration

The final clarify slice retains exact request identity across send ACK, wait,
transcription and cleanup. Rejected prose is revalidated after coercion and
requires successful exact resolution before ordinary routing; its original
input owner is retained across compression, steering, queues and admission.
Global interruption invalidates the captured still-current generation and
clears its questions under the same existing session lock as registration,
while signaling outside that lock. Retired callbacks cannot register again.

Run-current checks alone did not protect the same run's next question. The
final helper checks existing pending clarify and blocking approval state while
the caller holds its existing owner lock. Both registry locks are acquired
sequentially, not simultaneously or across transport waits. It protects inbound
typing resume and the actual callback's typing and stream-reopen sites. Real
same-owner sequential/parallel questions and a following approval keep their
actual paused state and useful answers. A single answered question still
reopens streaming and resumes typing immediately before body cleanup.

Parent independently rehashed all 350 sealed files, 33 saved source/graph files
and 30 exact complete projected methods, read immutable CodeGraph integrity
and actual counts 3,052 nodes/8,985 edges, and reconciled all 36 JUnit/Job rows.
Fourteen normal Jobs contain 267 unique passes with no failures/errors/skips.
Twenty-two fault Jobs have 21 behavioral assertion kills, 29 failed occurrences
over 25 unique nodes all normal GREEN, and one explicitly disclosed redundant
generation-only removal survivor. It is not reported as 22 killed mutants.
Guard refusals, recovery and owned survivors are zero in the qualified rows.

The six planned source/test overlay files exactly match the sealed bytes, and
all other 27 selected dependencies exactly match committed HEAD blobs. No LSP,
registry, API, kernel or new approval WIP is included in this integration.
Frozen approval ca3 and declared process import 5d2, empty process/reaper leaves
and offline/model/transport stubs remain explicit qualification limits. The
separately authorized approval working-tree change does not alter this saved
proof or become a dependency of the commit. Four legacy session-clear assertions
were minimally migrated to request-specific cancellation; original failing
receipts, timeout/sent/log/no-wait behavior and real no-ID positives remain.

Independent bounded final review finds no remaining P1/P2 in C1-C5 and the
declared prose/global/same-run pause extensions. The canonical
CONTINUATION_CLARIFY_OWNER_20261020.json records exact hashes and exclusions.
Native channel transport, queued finalize, post-decision approval persistence,
permanent save concurrency, live API/process/R6, whole T02/Python/P0, portable
CI, complete SDK and whole-SHA acceptance remain OPEN. No production action or
publication is performed.

## Frozen R5 review and R6 publication repair boundary

Frozen R5 remains PARTIAL with integration held. Parent and independent review
reconciled 16 owned source/test hashes, 17 graph copies, 155 named evidence
hashes and 31 JUnit/Job rows: 124 unique normal passes, 20 fault variants with
66 failed occurrences over 58 unique nodes, all normal GREEN, plus four R4
baseline failures. Errors/skips and qualified Job/audit/recovery issues are
zero. Immutable graph integrity is ok with 964 nodes and 2,781 edges. The
handoff and delta retain their original 87ffa1f3 and e0fe1f9f hashes on parent
readback. Earlier generations and source copies remain unchanged.

R5 closes the healthy-reader-ended stuck-running condition structurally, but
its reader sets exited and exit_code before entering the scope-aware finish
helper. A public observer at that interval can report or consume completion
while the actual retained Job still contains a live descendant. This is a
source finding from independent review, not native execution by the reviewer.
The four healthy cases query after joining the reader and miss that interval.
The canonical CONTINUATION_PROCESS_R5_REVIEW_20261020.json preserves both the
supported slice and this unresolved P2 without accepting R5 product changes.

R6 is a separate unsealed author generation. Twelve corrected actual owned
pipe/PTY publication and unstarted-reader cases fail behaviorally against R5;
the initial four pipe CRLF setup mismatches remain preserved and excluded.
An earlier R6 candidate passed those twelve, while subsequent compatibility
and missing-scope guards require fresh final-source runs and a new seal.
Native provider test preparation has separate timing and early cleanup
findings: barrier expiry must remain a setup/precondition result, and all
reader/launcher barriers must release and join before closing the provider.
No native R6 execution or native completion acceptance has been authorized at
this preparation checkpoint. The R5 credential target is historical and does
not establish publication correctness. Cross-sensitive R6 jobs must bind the
final approval checkpoint; old ca3 proof cannot qualify moving approval WIP.

## Approval decision memory commit integration

The reviewed approval43872 candidate closes the original five post-wait state
regressions without changing their assertions. Each of the three callers uses
the same pre-wait producer in a new bounded owner-guard then approval-lock
transaction. Current identity and grant/denial memory changes now commit in
the same critical section as retirement. Current once/session/always consent,
parallel FIFO, Smart-DENY one-operation overrides and Tirith session limits
remain useful. Combined permanent saves occur zero or one times outside both
locks; transport, waits, hooks and disk I/O stay outside the transaction.

Parent independently rehashed all 932 sealed files and retained 2835/77/7/116
history files, reconciled 80 raw Jobs/JUnits and 3091 before/after binding pairs,
and verified all 58 current/copied graph files and 1294 complete method spans.
Actual immutable read-only DB integrity is ok at 2218 nodes/5657 edges/58 files.
Normal49 Jobs contain 631 unique passes with no errors/skips/refusals/recovery;
fault31 Jobs contain 29 variants, 61 failed occurrences over 39 unique nodes,
all normal GREEN. Five older test/bootstrap/mutator input versions are saved
by hash. Historical lock faults are distinct from final test7804 repeats.

Independent read-only final review supports only this source/runtime slice,
with no new concrete P1/P2. It did not execute tests or query the DB anew.
Eight exploratory rows, including an admission-deny prompt TimeoutError and
guard-refused cluster attempts, are excluded from qualified GREEN/kills.
Three unchanged platform/native-effect cases are deselected explicitly; final
pure cluster23 and selected CLI10 qualify their narrower state behavior.

Only approval.py, original unchanged-assertion decision ownership testc173 and
new commit/save-count test7804 are integrated as product/test changes. The
canonical CONTINUATION_APPROVAL_COMMIT_20261020.json records exact seal hashes.
Declared fixed5d2/empty-process/offline leaves remain limits. Permanent disk
snapshot concurrency is separate OPEN evidence on both ca3 and 43872, not a
durability fix. R6 explicit-kill output-drain proof, native adapter request IDs,
effect leases, full strict/native lifecycle and whole-SHA CI remain open.

## Main CI advisory repair

Published main 2a04dd5041ff32392766e57e6c75e52b5df63562 triggered the full
workflow set. Windows Tier-1 run 39335745576 Security and lockfiles failed
its unchanged pip-audit gate on aiohttp 3.14.3: CVE-2026-111063,
CVE-2026-111064 and GHSA-2g87-pp6c-29x5. All six extras now pin 3.14.4.
The generated uv.lock changes only aiohttp 3.14.3 to 3.14.4 and its required
yarl 1.24.5 to 1.25.1; all other package versions remain unchanged.
The official PyPI metadata requires yarl>=1.25.1,<2.0 for this release.

Fresh hash-required pip-audit 2.10.1 of the frozen all-extras export checked
251 applicable dependencies and found no known vulnerabilities. uv lock
--check, downstream policy validation, carry metrics --check and git diff
--check pass. No advisory exclusion, workflow condition, test assertion or
runtime configuration is changed by this patch. Cloud all-green remains
pending the next pushed SHA and all its applicable terminal workflow results.

## Branch RPC formatting gate

Applied the formatter's whitespace-only wrapping to the accepted session.branch
RPC chain in ui-tui. Non-whitespace source equality is verified against HEAD;
the branch response guard and session identity behavior are unchanged. Carry
metrics are regenerated for the same formatting delta. No lint suppression or
test expectation is changed. Exact-SHA cloud checks remain required.
