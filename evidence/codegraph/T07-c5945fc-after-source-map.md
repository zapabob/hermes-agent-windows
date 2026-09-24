# T07 after-change CodeGraph source map

Source commit: `c5945fc05886f9663d882dd2e3c5f9fb8f02d8a6` on `codex/t07-response-semantics-h-20260924`. The source-tree fingerprint recorded in the after receipt is SHA-256 over the NUL-delimited `git ls-tree -r HEAD` entries. The machine-local CodeGraph index is `H:\hermes-control-mcp-t07-semantics-20260924\.codegraph`; it is not committed.

The first post-edit `codegraph sync --yes` attempt was rejected because CodeGraph 1.6.0 does not accept `--yes`, and the default Node 26.9.0 was refused before indexing. The existing Node 22.23.2 under NVM was invoked directly for the supported `sync` command; no machine or user configuration was changed. The final sync after the last test-only edit reported one changed file and 31 updated nodes. Status then reported a complete index of 8,876 files, 189,361 nodes, 608,647 edges, zero pending changes, and no worktree mismatch.

## Post-edit query

The focused query returned `NormalizedTurn` and `ParentInferencePort` as the leading matches in `downstream/delegation/inference_port.py`. The depth-two impact query for `ParentInferencePort.complete` reported 22 nodes and 21 edges, including the new controlled chat and Responses SSE tests and the existing profile/concurrency/round-trip tests. The static graph still does not resolve the dynamic import/result-consumption edge through `agent.conversation_loop._perform_api_call`; direct source inspection and the passing normal-loop tests cover that edge for the tested paths.

Direct checks exercised recorded synthetic Chat Completions and Codex Responses outcomes through the parent port and `AIAgent.run_conversation`. Both valid tool dispatch and refusal before dispatch were observed. The existing parent-owned delegation regression covers successful Chat Completions and Anthropic Messages tool round trips. These local tests do not establish live provider behavior, native desktop-client authentication, or real Codex-host SSE compatibility; those remain later qualification gates.

Query transcripts were reviewed locally and are not included because the receipt and this sanitized summary carry the relevant graph result without raw output.
