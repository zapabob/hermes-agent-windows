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
