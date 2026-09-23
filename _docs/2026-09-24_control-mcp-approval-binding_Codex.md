Focused T04 implementation checks (source 4577dc92b0dfd4b754c5d0e9ca14b05159d9a960 plus selected-file fingerprint in after receipt)
RED: uv run --frozen --extra dev python -m pytest tests/control_mcp/test_operations.py::test_human_approval_ticket_binds_and_discloses_resource_and_grant_revision -q
Expected result: 1 failed at assertion because the current HostControlJournal binding omitted resource. This is a human-visible consent/binding completeness gap. It is not an authorization bypass: HostControlJournal._owned already checks resource/client/grant revision on every operation approval.
GREEN: uv run --frozen --extra dev python -m pytest tests/control_mcp -q
Result: 189 passed, 1 skipped.
GREEN: uv run --frozen --extra dev python -m pytest tests/tui_gateway/test_protocol.py::test_control_approval_payload_has_only_once_and_deny tests/tui_gateway/test_protocol.py::test_control_approval_rpc_uses_strict_owner -q
Result: 2 passed.
GREEN: uv run --frozen --extra dev ruff check tools/approval.py downstream/control_mcp/journal.py tests/control_mcp/test_control_approval.py tests/control_mcp/test_operations.py
Result: All checks passed.
Legacy bridge characterization: ack_gateway_approval returns delivery acknowledgement while take_control_decision remains None and the strict entry remains pending. Existing resolve_gateway_approval tests still prove FIFO, resolve-all, and matching request ID do not decide strict consent.
Changes: add exact resource and grant_revision to the immutable ControlApprovalBinding (dataclass equality remains the consume binding), carry them from the journal row, expose them in the structured approval control payload, and render them in description because Desktop normalizes control metadata to operation ID and intent digest. expected_revision and source SHA remain in the human description and canonical intent digest.
Unchanged: strict local host control_approval.respond RPC, current journal _owned auth checks, no MCP self-approval endpoint, no new auth or provider storage, no dependencies/config, no real client auth, no live writes.
CodeGraph 1.6.0: exact root-local index synced 4 changed source/test files; post-sync status current. Receipts are JSON-Schema validated against the attached campaign schema. Index DB remains local/untracked.
Residual checks: actual Desktop/TUI rendered approval UI and real Windows host approval were not launched; live Codex/ChatGPT credentials and remote approval/write were not configured or tested.
