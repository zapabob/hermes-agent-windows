# T07 provider response semantics

## Snapshot and scope

Implemented T07 on isolated worktree `H:\hermes-control-mcp-t07-semantics-20260924`, branch `codex/t07-response-semantics-h-20260924`. Product commit: `c5945fc05886f9663d882dd2e3c5f9fb8f02d8a6` (`fix(providers): preserve completion and tool-call semantics for delegation`). The commit tree fingerprint is `8bcb48ef7006e782ec3eb8dfaee26d79c875f47a4662759cf3a969252e6e8c64`, computed as SHA-256 over NUL-delimited recursive Git tree entries. Before and after CodeGraph records are `evidence/codegraph/T07-98e1be-before.json` and `evidence/codegraph/T07-c5945fc-after.json`.

## Change

`NormalizedTurn` now carries normalized terminal status, final text, commentary count, complete tool-call identities, configured/requested/provider-reported model values, configured/wire/reported effort, and an optional fixed failure code. The underlying provider response remains hidden from repr and is returned to Hermes' established adapter and normal tool loop. Chat Completions, Anthropic Messages, and Codex Responses are checked for terminal validity, tool/status consistency, requested tool identity, duplicate or missing call IDs, complete call arguments, and refusals before any tool dispatcher can run. JSON tool arguments reject duplicate keys and non-finite constants. Error codes and user-safe exception text never include the raw provider response.

The configured model is read from the child agent's requested/configured model selection; requested model is read from the prepared request; reported model is read only from the provider response. Configured effort is read from the child reasoning configuration, wire effort from the prepared request fields, and reported effort only from explicit response fields. Missing provider-reported effort stays unknown.

The three profile/concurrency regression fixtures in `tests/tools/test_parent_owned_delegation.py` were updated to return a completed Chat Completions response. The original locking, profile restoration, and cross-profile isolation assertions remain unchanged; production validation was not relaxed.

## TDD and verification

The new focused test file first produced a meaningful behavior RED: `uv run --frozen --extra dev python -m pytest tests/agent/test_delegation_response_semantics.py -q` reported 9 failures and 3 passes. The missing normalized terminal metadata raised `AttributeError: 'NormalizedTurn' object has no attribute 'terminal_status'`; duplicate and unknown-status Chat calls and incomplete/duplicate/unknown-status recorded Responses SSE reached the mocked tool dispatcher through the actual `AIAgent.run_conversation` tool loop. After implementation, the same focused file passed 12 tests. A separate T05 regression run then exposed three stale dummy-response fixtures (`object()` / empty `choices`); those were replaced by valid completed responses, retaining their target assertions.

Final affected regression command: `uv run --frozen --extra dev python -m pytest tests/tools/test_parent_owned_delegation.py tests/agent/test_delegation_response_semantics.py -q` — 23 passed in 48.67 seconds. Ruff passed for `downstream/delegation/inference_port.py`, the T07 test file, and the parent-owned delegation regression file. `git diff --check` passed. Tests were run against the same tracked source tree committed as `c5945fc05886f9663d882dd2e3c5f9fb8f02d8a6`.

## Self-review and remaining qualification

The normal loop continues to consume the same provider response object and standard Hermes tool schemas; the additional port metadata does not replace ordinary adapter behavior. Invalid calls fail before `handle_function_call`; valid Chat, Anthropic, and recorded Codex Responses tool cycles succeed in the affected tests. Codex tests use synthetic recorded SSE through `_consume_codex_event_stream` and the regular parent port. The CodeGraph query/impact and direct source inspection agree on the tested call path; the dynamic import/result edge is not statically represented.

No real provider request, authenticated Desktop/Codex/ChatGPT client, native hosted Codex SSE stream, or provider-reported effort value was verified here. These remain separate qualification gates. The CodeGraph index and `codegraph.json` are local only and were not committed.

## Independent review correction and integration

An independent read-only review blocked the first T07 commit on three concrete paths: Responses SSE without a terminal event could dispatch tools, the requested model could be mislabeled as provider-reported, and an unknown message phase could enter the ordinary adapter despite being omitted by normalization. The follow-up product commit in the H: worktree is `8d7996d80d3894ef939596a45664438e903f50c0`; the integrator cherry-pick is `91c5ac34d1`. The collector now records terminal observation, confirmed completion, and an independently observed terminal response model. Controlled normalization requires the matching terminal facts before tool dispatch and rejects an unknown phase. A recorded incomplete event with a completed status is rejected as well.

The follow-up RED had three assertion failures before the correction: a fabricated reported model and two unsafe tool-dispatch paths. The corrected T07/T05 focused suite passed 27 tests; the affected existing Codex Responses adapter and run-agent files plus the new incomplete-terminal regression passed 81 tests; the existing pending-tool-call file plus that regression passed 9 tests. Ruff and `git diff --check` passed. The independent reviewer rechecked all three issues and approved integration from static inspection, without rerunning tests. These results use synthetic SSE and do not establish live provider or client behavior.

The first post-correction CodeGraph sync invoked the global 1.5.0 CLI and is not counted as a passed gate. On 2026-09-24, the exact pinned 1.6.0 CLI from the original checkout was verified with `--version` and rerun in the isolated T07 worktree at source HEAD `8d7996d80d3894ef939596a45664438e903f50c0`. `sync` exited 0 (`31 changed files`, `1,267 nodes`); `status --json` reported `version` and `builtWithVersion` 1.6.0, state `complete`, 8,907 files, 190,632 nodes, 610,006 edges, zero pending added/modified/removed files, zero pending refs, `reindexRecommended: false`, and no worktree mismatch. The local `codegraph.json` exclusion of generated output remains untracked. This satisfies the corrected-source after-index gate; it does not verify a live provider or client.
