# T09 max-age entitlement freshness correction

## Scope

This correction passes the already bounded `max_age` from `classify_cost` and `build_free_route_snapshot` into both entitlement validators. Snapshot construction rejects invalid negative/non-`timedelta` values, caps accepted values at the existing 12-hour maximum, and uses the same cap for entitlement metadata and cost classification. This prevents stricter caller policy from promoting stale free-quota or subscription evidence.

Pre-correction source SHA: `1d72882bf01ef35fa89a53c32a60861764b039d1`.

## TDD and verification

The behavioral RED was 2 failures and 20 passes in `tests/agent/test_free_route_catalogue.py`: a two-hour-old free-quota entitlement classified as `VERIFIED_FREE_QUOTA` with a one-hour `max_age`, and a similarly old subscription entitlement classified as `SUBSCRIPTION_INCLUDED`; both assertions expected `UNKNOWN`.

After the correction, the affected suite passed: 101 tests across the free-route catalogue, usage-pricing, model-catalogue, and model-catalogue adapter files. Ruff 0.15.10 passed for the changed source and test. ty 0.0.21 passed for the changed source. `git diff --check` passed.

## CodeGraph

Pinned CodeGraph 1.6.0 ran under Node 22.23.2. Before the sync, the 1.6.0 index was complete at the pre-correction source SHA with 8,909 files, 190,729 nodes, and 610,693 edges; two changed files were pending. After sync, the index was complete with 8,909 files, 190,731 nodes, 610,711 edges, zero pending file changes, zero pending references, and no worktree mismatch.

Caller queries confirmed `_matching_free_quota` and `_matching_subscription_entitlement` each have the expected two callers: `classify_cost` and `build_free_route_snapshot`. The `affected` query returned no tests, so the four-file test suite above was selected and run directly.

Raw status and caller results are in `evidence/codegraph/T09-max-age-correction/`.

## Remaining T09 integration gaps

The 12-hour refresh API remains explicit and has no host-owned startup/wake tick wired to it. The catalogue is in-memory; after a cold restart there is no trusted snapshot, so classification remains `UNKNOWN` until an approved refresh completes. This correction does not complete the broader T09 lifecycle or persistent offline-display acceptance.
