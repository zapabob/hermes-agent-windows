# Workstation freeze and inventory evidence

**Campaign:** `windows-workstation-20260924`
**Record date:** 2026-09-24 JST
**Owned scope:** T00/T01 freeze and metadata-only adoption inventory
**Task branch:** `codex/workstation-t01-20260924`
**Frozen source HEAD:** `ebe05b1a397cf3855b36f84c60841abc9f2d7ce2`

## Freeze

The frozen downstream source is the exact task-worktree HEAD above. The historical upstream snapshot remains `b51c055a12220f8c7c18660e8599365012e19532`; the campaign ceiling remains `b936546561888a54d5bf9cd7eae9629a824eb4f7`. The `v2026.9.21` tag object `dd2c35f4f6d14c518a46d8ceb5311f57851a1ee2` peels to release commit `d337b736aa1e8ebecfab043842d13e4a2d2f48a3`. All required objects and the three ancestry edges were verified locally in a non-shallow repository. `allow_upstream_sync` and whole-upstream merge are false; the historical snapshot is not rewritten.

The separate recovered integration checkout was observed at `dbca4d19cf3c91fb39f7e123eb0829e5118ab088` on `feat/hermes-control-mcp-c-20260923-recovered`. That later integration HEAD is provenance only and is not the source of this inventory. The local preflight record keeps the frozen source and integration observation distinct. Machine paths redact the Windows account component.

## Inventory

The stdlib-only helper `docs/windows/workstation-20260924/tools/inventory_commits.py` enumerated the three frozen ranges and re-audited the historical ledger. The outputs contain 2,777 commits from historical snapshot to v0.21.3, 5,173 from v0.21.3 to v0.21.4, and 993 from v0.21.4 to the campaign ceiling: 8,943 unique commits total. The legacy ledger has 5,105 rows: 1,536 ADOPT, 3,568 COMPOSE, and 1 DEFER_PLATFORM. Its categories are fully accounted for; the SECURITY_CRITICAL and DATA_INTEGRITY categories contain 1,671 unique SHAs.

The metadata-universe JSONL contains one row for each of 14,048 unique commits, with SHA, direct parent SHAs, frozen source-window membership, prior decision/category labels, critical-category and review/adoption status markers, and empty implementation, test, and CodeGraph evidence fields. It does not include author or committer metadata, commit subjects, or changed paths. All 14,048 remain `UNREVIEWED`. The 34 adoption seeds, including 16 P0 seeds, are also explicitly unreviewed; they contain no fabricated implementation or test receipts. The 1,671 commits in the two critical legacy categories remain an open semantic-review queue, not verified findings or adoption decisions.

## Verification and boundaries

The bounded Windows synthetic Git suite passed: `uv run --frozen --no-sync python -m unittest docs/windows/workstation-20260924/tests/test_inventory_commits.py -v` — 11 tests passed. The real frozen inventory helper exited 0 against task-worktree HEAD `ebe05b1a397cf3855b36f84c60841abc9f2d7ce2`. Archive integrity verification found 28 manifest entries and zero mismatches; ZIP SHA-256 is `7870af3fa739d541c19b0374f4ac6496e0b561ebf85848f21b5be9a0ad95b738`, and the manifest SHA-256 is `efb6ff38d0ecdc1dc0ca107c574644af5194ca1936bbe27e737d1a8de98f29ca`.

The parent-reported MCP product suite (`256 passed, 1 skipped`, commit `27685609cd356cf0d786b2eac65207bcf9cd5a98`) is recorded separately in `local-preflight.json`; it was not run on this task branch and is not claimed as T01 evidence. The approved CodeGraph 1.6.0 executable/status was reported by the integrator for clean frozen HEAD; this task did not query or build an index. The historical event-timestamp regression reproduction and predecessor/base comparison were not run by this bounded inventory task and remain open for integrator closeout. No semantic adoption review is claimed.
