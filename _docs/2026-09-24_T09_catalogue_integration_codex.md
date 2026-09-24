# T09 free-route catalogue integration record

The isolated H: worktree implemented and corrected T09 in source commits
`dc9c95e62cd5af0adea7e660776499be9b03addd`,
`1d72882bf01ef35fa89a53c32a60861764b039d1`, and
`541690c6cdd3b945980cbf8261a8e5b1c8bb38a0`. They were cherry-picked
without conflicts onto the recovered integrator as `bfd02c0503`,
`0c8f92770c`, and `c498dde2a1`, respectively. The unrelated untracked
T06 pytest output was preserved.

TDD began with a behavioral assertion failure for the missing classifier;
the first correction reproduced unchanged revisions after price changes and
unproven subscription admission (17 passed, 3 failed). The final correction
reproduced quota and subscription evidence older than a caller's one-hour
limit being classified current (20 passed, 2 failed). The H: affected suite
ended at 101 passed; Ruff 0.15.10, ty 0.0.21, and diff checks passed. A
read-only independent review requested the strict-age correction, and a
different independent reviewer approved the corrected source with no code
findings. The final pinned CodeGraph 1.6.0 status reported 8,909 files,
190,731 nodes, 610,711 edges, no pending files or refs, and no worktree
mismatch. The exact receipts and queries are committed under
`evidence/codegraph/T09-max-age-correction/`.

At integrated source `c498dde2a1`, the four affected files were rerun using
the integrator's locked virtual environment with an H: pytest temporary
directory: 101 passed in 23.16 seconds. The integrator contained only the
preserved untracked T06 pytest output afterward.

This is a partial T09 integration. `FreeRouteCatalogueOwner` has no
production host lifecycle caller, approved provider fetch adapter, persisted
last-good snapshot, or live provider proof. A cold restart remains UNKNOWN
until an approved refresh. The host must wire a bounded fetch and the
twelve-hour startup/wake schedule before T09 can be accepted as operational;
price and entitlement age continue to gate eligibility independently. No
client, endpoint, configuration, paid route, or production credential was
used in this integration.
