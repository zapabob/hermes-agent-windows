# N07-A2 partial: failed apply witness must not report success

Repository: `zapabob/hermes-agent-windows`. Product commit `5c2cea7d2dd8a14f440ab687e1880424a2e6a80e`, tree `f88023b448ccf4910cb0beb9647365c354117450`. Frozen downstream D0 is `60deb5c75351a19b1a6fa1d778d7d0c2ff627e5b`, upstream U1 is `678a4762b887f3eabe5cad11254b2ab1ae859485`, and old U0 remains `b936546561888a54d5bf9cd7eae9629a824eb4f7`. This is one narrow Control MCP result correction, not T12 qualification or complete upstream coverage.

## Actual source, RED, and correction

`VerifiedApplyOwner.start_approved` in `plugins/implementation_router/apply.py:46-86` claims an approved operation through the native SQLite journal, checks the expected destination revision, performs destination compare-and-swap, calls `_witness` at lines 88-100, and records a terminal state. Before this correction, `_witness` swallowed `append_effect_evidence` failure and the owner could return `SUCCEEDED` after the destination changed with no append-only witness. `HostControlJournal` owns the outcome and reservation, while `HostControlCoordinator` forwards to this owner. D0 and U1 do not contain these local implementation-router paths; the pre-change blobs were already present on the preserved feature branch.

An actual-owner regression in `tests/control_mcp/test_review_claim_grant_and_witness.py:336-363` first failed RED for both `ControlError` and `sqlite3.OperationalError` raised by the witness append. It uses an inert counted destination with a native SQLite journal. The minimal correction makes `_witness` report append success or failure. A failed append after landed compare-and-swap now records `UNKNOWN`, raises `apply_outcome_unknown`, keeps the reservation, rejects replay, and remains UNKNOWN after journal restart. It does not fabricate the missing append-only evidence.

## Validation and review

At the final product bytes, Windows Python 3.12 passed 167 tests across six affected Control MCP files. Both focused cases passed again after a controlled mutant that forced `_witness` to return success on append failure killed both cases; the source was restored byte-identically before final verification and commit. Python 3.11 was unavailable on this PC in this session; no install was performed. No production destination writer was bound or run.

Approved local CodeGraph 1.6.0 bound D0, U1 and the integration source to separate indexes. The integration index was up to date with 8,950 files, zero pending changes or refs, and actual/committed/indexed SHA-256 equality for the two changed paths. Query, explore and impact were run on the final source. External receipt `H:\hermes-worktrees\semantic-refresh-20260926\source-bindings\receipts\codegraph\N07-A2-witness-20260927\receipt.json` has SHA-256 `8ca7acb1626026a4e24a45dd3cb3f09627d017e07df6c10841e2b70f336042c4`. Static graph reachability is not proof of the injected owner path or destination durability; the actual-owner test provides the former only.

An independent read-only Code Reviewer found no new blocking defect in the two-file correction and traced the UNKNOWN state through coordinator cleanup and retained reservation. The reviewer did not run tests, CodeGraph, or a native writer. Only `plugins/implementation_router/apply.py` and `tests/control_mcp/test_review_claim_grant_and_witness.py` entered the explicit-path product commit.

## Open safety gates

N07-A1 is still P0 open: host `grant_lookup` and revocation can operate in a separate store while the journal claims RUNNING, and no shared linearization with the effect boundary has been proved. The failed witness case has no append-only witness at all; destination outcome durability and a write that lands then raises without acknowledgement remain unproved. The implementation-router kernel may classify an uncertain post-effect exception as BLOCKED and release the reservation. T12 therefore remains blocked, and Control MCP production write stays DISABLED.

The 17,065-commit metadata inventory remains short of full U1 semantic family coverage. The original checkout and preserved feature worktree were not edited, reset, stashed, cleaned, deleted or renamed for this correction. No upstream merge/rebase/cherry-pick, public PR, push or production restart occurred. To reverse only this narrow product correction in the isolated branch, review and revert `5c2cea7d2dd8a14f440ab687e1880424a2e6a80e`, then rerun affected tests and refresh the integration CodeGraph index. No reversal was performed.
