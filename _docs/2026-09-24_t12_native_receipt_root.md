# T12 host native receipt consistency slice — 2026-09-24

This is a bounded T12 component, not the completed T12 gate. It introduces a
host-only receipt evaluator for an eventual qualified Windows native producer.
No MCP tool, child, UI, journal writer, or apply operation calls this code yet.

## Source and graph

- Repository: `zapabob/hermes-agent-windows`; isolated branch
  `codex/t12-evidence-20260924`; predecessor
  `9b6bdfe6b94093e5c72466522bce14faa1037a41`.
- Before-tree Git object: `6f0c2d7d9cd0999d3693b079e4b213fb399c44a9`.
  The before fingerprint in the JSON receipt is SHA-256 of the ASCII tree
  object ID. The after fingerprint is SHA-256 of the UTF-8 concatenation of
  that base tree ID, a newline, and the two staged product-file `git ls-files
  -s` rows joined by newlines. The receipt and this log are excluded from that
  product fingerprint to avoid a self-reference.
- Pinned `@colbymchenry/codegraph@1.6.0` under Node 22.23.2, local index
  `H:\hermes-worktrees\t12-evidence-20260924\.codegraph`. Before index at
  2026-09-24T09:31:29.210Z: 8,919 files, 191,245 nodes, 612,432 edges;
  no pending changes before edits. Exact predecessor queries and unresolved
  dynamic edges are in `evidence/codegraph/T12-9b6bdfe6-before.json`.
- Before graph located legacy `verify_native_result` at
  `downstream/control_mcp/observations.py:196`. The impact query found that
  method and its provenance test. `HermesObservations.evidence` additionally
  reached the read and provenance tests. Legacy evidence remains read-only.

## TDD and checks

- Added an importable typed API and behavioural assertions first. The focused
  RED command was `python -m pytest tests/delegation/test_native_receipts.py
  -q -p no:cacheprovider` through the locked integrator venv with
  `PYTHONDONTWRITEBYTECODE=1`: **21 assertion failures, 1 pass**. Failures
  showed `unimplemented` where a current receipt or an exact refusal reason
  was expected; this was not an import or setup failure.
- The minimum evaluator binds owner epoch, operation/run/profile/workspace,
  source/result digests, protected check-set revision, platform, exact check
  inventory and individual process/check exit, completion, timeout, cleanup
  and before/after digest facts. Empty or malformed host expectations fail
  closed. The evaluator accepts only a receipt supplied by a trusted native
  producer; its dataclass shape alone is not authority.
- GREEN: 24 focused tests; 39 tests when combined with
  `tests/control_mcp/test_evidence_provenance.py`. With the graph-impacted
  `tests/control_mcp/test_reads.py` included: 62 passed, 1 skipped (symlink
  privilege unavailable on this host). Ruff on
  both changed Python files, `ty check` on both, and staged
  `git diff --check` passed. Both CodeGraph receipts validated against the
  supplied `CODEGRAPH_RECEIPT.schema.json` with the locked venv's `jsonschema`.

## Unverified dependencies and next boundary

- T06 still needs the user-approved real Windows AppContainer profile test;
  the earlier safe suite had 6 passed and 5 skipped. There is no claim of
  native isolation or useful positive execution from this component.
- The current producer does not mint these receipts. T12 still needs a real
  registered check runner, durable journal intent/outcome and owner fencing at
  the writer, uncertain-outcome recovery, source/reparse race checks, and a
  separate human-approved verified apply. No receipt may be minted from child
  text, legacy bridge ACK, or merely a READY state.
- T12 full gate and T20 generic write capabilities remain false until those
  direct checks and a positive native task pass. No endpoint or operational
  configuration was changed for this slice.
