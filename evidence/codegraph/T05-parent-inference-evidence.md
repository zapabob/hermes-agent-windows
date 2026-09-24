# T05 parent-owned inference evidence

## Scope

This slice adds a host-admitted keyless child-construction seam, a child-scoped parent inference port, and dispatch from the normal Hermes conversation loop. The ordinary delegation route keeps its existing credential-inheritance and provider-client behavior when no inference port is admitted. Controlled child and grandchild construction does not store a direct reference to the credential-bearing parent.

## RED and GREEN

The pre-fix behavioral RED was observed in `test_host_admitted_child_constructor_receives_port_without_credentials`: the admitted child constructor received the synthetic parent API key. The original transient pytest output was not retained. The current regression asserts that the key and credential pool are absent, the inference port is present, the child graph has no parent/client/key reference, and the pool resolver is not called.

GREEN in this worktree:

- `\.venv\Scripts\python.exe -m pytest tests/tools/test_parent_owned_delegation.py -q --tb=short` — 9 passed in 13.12s. This covers controlled constructor/init tripwires, child and grandchild graph checks, chat-completions and Anthropic Messages tool-loop round trips, A→B→A and concurrent profile isolation, cancellation/late-response refusal, and auxiliary-inference refusal before secret resolution.
- Earlier compatibility run: `tests/tools/test_delegate.py tests/agent/test_subagent_lifecycle.py -q --tb=short` — 74 passed in 33.05s.
- `git diff --check` — passed.
- Manual static review found parent-key reads and child-pool resolution guarded by `inference_port is None`; controlled construction passes no key, endpoint, or pool; controlled initialization skips provider client/token resolution, pool synchronization, and fallback-chain loading; request proxy blocks credential/client attributes. The child graph regression walks stored attributes only and does not inspect function code.

An ad hoc AST credential-path script stopped at an assertion that did not match the source shape. It made no changes and is not counted as a passing check.

## CodeGraph source evidence

`T05-9b275d-before.json` and `T05-9b275d-source-map.md` record the exact pre-change source snapshot `9b275d0818e21d2c5c4db0ba998f2833a42013ab`, CodeGraph CLI 1.6.0, and a verified-current v25 extraction with 8,903 files, 190,479 nodes, and 609,557 edges. The impact query reported 85 nodes and `NEEDS_DIRECT_CHECKS`.

No post-change CodeGraph index/receipt was generated. A full index pass was deferred under the bounded-disk instruction; the latest confirmed C: free space was approximately 0.75 GiB. The source-map receipt therefore describes the baseline, not the committed tree.

## Remaining verification boundaries

The two normal-loop round trips use synthetic provider responses at `interruptible_api_call`; no live provider request, native SDK client, or credential-refresh flow was exercised. The focused response-family tests cover chat-completions and Anthropic Messages; the Codex Responses wire path remains unverified. `admit_parent_owned_inference()` is exercised as a trusted host boundary in tests, but no production API/lifecycle call site is wired in this slice. This change does not expose MCP write operations and does not provide T06 or OS-level isolation.
