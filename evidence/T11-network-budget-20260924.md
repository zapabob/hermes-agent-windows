# T11 delegated network request budget

## Scope and commits

The product implementation is committed at `cdfd15080399bce52bb349ac8884aa4c9941ed96` on `codex/t11-network-budget-20260924`, based on integrator `9b6bdfe6b94093e5c72466522bce14faa1037a41`. Independent review correction `97cbe8f00416c9cc2e0abeb31148e403b51515a1` makes the first cancellation reason win, increments the cancellation generation once, and invokes the registered abort callback at most once for repeated cancel notifications. It also preserves the first reason when an external abort is recorded before the budget is notified. Existing unbudgeted callers remain compatible.

The budget is process-local. No production host currently passes a budget and account scope to `ParentInferencePort.for_parent`; the feature remains inactive until host admission wiring is added. Separate OS processes do not share global capacity, account concurrency, or cooldown state.

## RED and GREEN evidence

The unknown-worker regression first showed a timed-out request still running while a same-account retry was admitted. The assertion expected `request_outcome_unknown`; the pre-fix path admitted it. The fix retains that account's capacity and refuses another request until the tracked worker exits.

Global reservation tests first failed for inference, catalogue, and embedding at saturation because no `capacity_reserved` refusal occurred. The corrected policy keeps one global network slot for control operations and one non-control slot for inference when catalogue or embedding maintenance is admitted. Status and cancellation are local in-memory operations; a loopback slow-provider test exercises status and cancel while network capacity is saturated and confirms both remain responsive.

Another loopback HTTP test sends a response as a slow trickle. The scoped delegated inline request is aborted within its absolute lease deadline while the read-idle deadline remains separate. No live provider, credentials, malware sample, or public network was used.

The independent review's cancellation RED tests reproduced `['user_cancel', 'deadline']` callback delivery on repeated notifications and showed a recorded `interrupt` being replaced by `deadline`. After the fix, both tests pass: repeated `RequestBudget.cancel` calls preserve `user_cancel` and notify the transport once, while a prior `note_cancelled('interrupt')` remains authoritative and prevents a later budget cancellation from re-notifying an already aborted transport.

## Verification

- `tests/delegation/test_network_budget.py tests/delegation/test_request_cleanup.py`: 20 passed after the review correction (18 passed before it).
- Affected suites: cascading interrupt 2 passed; Codex TTFB watchdog 8 passed; parent-owned delegation 11 passed; delegation response semantics 17 passed; OpenAI client lifecycle 5 passed (43 total).
- Ruff 0.15.10 passed on all seven changed Python files.
- `ty` 0.0.21 passed on the budget, inference port, and two new test modules. The whole-file check of `agent/chat_completion_helpers.py` and `run_agent.py` still reports 350 diagnostics; a diff-hunk audit found zero diagnostics on edited lines, so this is not a whole-file cleanliness claim.
- Targeted `compileall` and `git diff --check` passed.

## CodeGraph

Pinned CodeGraph 1.6.0 ran under Node 22.23.2. The product commit was synced as seven changed files (three added, four modified; 749 nodes). Its after-index receipt is `evidence/codegraph/T11-cdfd1508-after.json`, with sanitized results in `evidence/codegraph/results/T11-cdfd1508-after-results.json`. The independent cancellation correction was then synced as two modified files (92 nodes); its receipt and results are `evidence/codegraph/T11-97cbe8f0-after.json` and `evidence/codegraph/results/T11-97cbe8f0-after-results.json`. Correction status was complete with 8,922 files, 191,367 nodes, 612,964 edges, zero pending changes, zero pending references, and no worktree mismatch. The before receipt and queries are `evidence/codegraph/T11-9b6bdfe6-before.json` and `evidence/codegraph/results/T11-9b6bdfe6-before-results.json`.

The after impact query for `ParentInferencePort.complete` returned 16 nodes and 15 edges, including the `conversation_loop` API-call path. CodeGraph does not prove process lifecycle or transport behavior, so these were checked directly and with local HTTP tests.

## Remaining qualification

Cross-process/global host limits are not implemented. No runtime host injects the explicit trusted account scope yet. Real provider SDK cancellation, TLS and redirect handling, DNS behavior, external Retry-After responses, and gateway lifecycle under real providers remain unqualified. A provider worker that does not exit after its transport is aborted remains counted, and same-account admission stays blocked until the worker exits; T11 does not claim to close the userspace check-to-network race for every provider implementation.
