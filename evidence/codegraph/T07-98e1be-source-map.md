# T07 CodeGraph source map (before)

Source: `zapabob/hermes-agent-windows` at `98e1be6e94bab5cc0d70d4a827f826e3a6a020b2`.
Index: CodeGraph 1.6.0 in this isolated worktree at `H:\hermes-control-mcp-t07-semantics-20260924\.codegraph`; status reported complete, 8,906 files, 190,577 nodes, 609,972 edges, zero pending changes, and no worktree mismatch. The index was built with extraction version 25, which matches the current extraction version. A worktree-local `codegraph.json` excludes `output/logs/`, `_docs/`, and `_artifacts/`; CodeGraph file filters reported no indexed files beneath `output/logs/` or `_docs/`.

## Queries and observed results

1. `explore 'ParentInferencePort complete NormalizedTurn caller child request loop' --max-files 12`
   - Located `NormalizedTurn` and the parent inference port, but the static result did not establish the dynamic normal-loop transition or test coverage within three caller hops.
2. `explore 'Codex Responses event stream terminal status commentary output item function call conversation normalizer' --max-files 12`
   - The CLI result exceeded the captured output budget; detailed result evidence is incomplete. Direct source and regression-test inspection is required before relying on this graph result.
3. `impact 'ParentInferencePort.complete' --depth 2`
   - The reported impact centered on the method itself and did not resolve all dynamic calls through the conversation loop.

## Direct source owners identified for follow-up

- `downstream/delegation/inference_port.py`: `NormalizedTurn` and `ParentInferencePort.complete`.
- `agent/conversation_loop.py`: `_perform_api_call`; it dynamically imports the normalized turn type and consumes `inference_port.complete(...).response`.
- `agent/codex_runtime.py`: `_consume_codex_event_stream`.
- `agent/codex_responses_adapter.py`: `_normalize_codex_response`.
- `agent/transports/chat_completions.py`, `agent/transports/codex.py`, and `agent/transports/anthropic.py`: existing provider normalization paths.
- `tests/tools/test_parent_owned_delegation.py` and `tests/agent/test_codex_responses_settle_pending_tool_calls.py`: existing parent-port and Codex incomplete-call coverage.

## Unresolved graph edges and disposition

The static graph does not prove the runtime edge from `_perform_api_call` through the dynamic import to the parent port result. The Codex Responses query was output-truncated, and `impact` under-reported transitive callers. Validate these by direct source inspection and focused tests. No behavior or security conclusion is drawn from CodeGraph alone.

Disposition: `NEEDS_DIRECT_CHECKS`.
