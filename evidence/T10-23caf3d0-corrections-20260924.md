# T10 Admission Review Corrections

The corrections are in the isolated `codex/t10-admission-20260924` worktree, based on `290e5812c6fa0a28306de6b67ce0d5a629284213`. The product correction commit is `3a78f02e766bb8ab33ccb8eb1e226142b9303678`; the follow-up test commit is `23caf3d0a98d1922b3ee4ef25e537e5561826e1d`.

## Shared host ledger

`DelegationAdmission` instances using the same `ResourceReservationBook` now share a synchronized in-memory ledger. The shared ledger contains active grants, retained request IDs, unknown-writer tree blocks, route rotation/cooldowns, and the bounded waiter count. This keeps the two top-level and one read-only grandchild limits, and unknown-outcome quarantine, consistent across owners created for the same host resource book.

Tests independently cover a third top-level request across owners, an unknown tree observed by one owner and retried through another, and the single-grandchild capacity across owners.

## Reservation rollback

Grant ID and creation-clock generation now occur inside the rollback scope after resource reservation. Any exception during grant construction removes tentative ledger entries and releases the resource-book reservation. A parameterized regression injects failures in both token generation and the post-reservation clock, then verifies no active grant and no RAM/commit claims remain.

## RED and GREEN evidence

Before the source correction, the top-level-cap regression received an `AdmissionGrant` where `top_level_capacity` was expected. The token-generation and post-reservation-clock regressions each raised as injected but left the 1 GiB RAM and 1 GiB commit claims reserved. The isolated unknown-tree and depth-two tests make those cross-owner contracts independently observable in the final suite.

After correction, the affected suites passed with Python 3.12: `tests/delegation/test_nested_budget.py`, `tests/delegation/test_round_robin.py`, `tests/downstream/test_resource_admission.py`, and `tests/agent/test_free_route_catalogue.py` — 63 passed. Ruff 0.11.12 passed for `downstream/delegation/admission.py` and `tests/delegation/test_nested_budget.py`; `git diff --check` passed. `ty` was unavailable in the installed Python 3.12 environment, so no type-check result is claimed. Pytest emitted the existing `pytest-asyncio` default fixture-loop-scope deprecation warning.

## CodeGraph 1.6.0

The final after-index is recorded in `evidence/codegraph/T10-23caf3d0-after.json`; its query result is in `evidence/codegraph/results/T10-23caf3d0-after-results.json`. Pinned CodeGraph 1.6.0 with Node 22.23.2 reports a complete index at `23caf3d0a98d1922b3ee4ef25e537e5561826e1d`: 8,918 files, 191,138 nodes, 612,124 edges, zero pending changes, zero pending references, and no worktree mismatch.

## Integration boundary

T10 remains inactive. These changes do not add a production caller, launcher, scheduler, or lifecycle integration. Real child execution, host lifecycle reconciliation, and enforcement through the actual production boundary remain unverified.
