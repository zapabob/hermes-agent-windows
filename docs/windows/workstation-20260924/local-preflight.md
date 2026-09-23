# Workstation 2026-09-24 local preflight and inventory

Captured 2026-09-24T06:22:29.7351889+09:00 (2026-09-23T21:22:29.7351889Z). The committed record redacts the Windows profile name; exact local paths remain in the Codex task context. The canonical downstream repository is `zapabob/hermes-agent-windows`, with frozen remote-main SHA `e6070028c9d0d75634ad7661c33fa937b682474a`.

## Worktree identity and preservation

The integration worktree was observed clean at `dbca4d19cf3c91fb39f7e123eb0829e5118ab088`, branch `feat/hermes-control-mcp-c-20260923-recovered`, with merge-base `e6070028c9d0d75634ad7661c33fa937b682474a`. Before the parent’s T03 commit, the same recovered path was observed at `27685609cd356cf0d786b2eac65207bcf9cd5a98` with six tracked T03 paths modified and two CodeGraph receipts untracked; those paths and receipts were preserved by the integrator and are recorded in `local-preflight.json` without copying any diffs.

T01 inventory ran from an isolated branch `codex/workstation-t01-20260924` at exact source HEAD `ebe05b1a397cf3855b36f84c60841abc9f2d7ce2`, 39 commits ahead of the frozen downstream main and not shallow. This is the chosen inventory source snapshot. The later integration HEAD is recorded separately; it was not silently substituted or merged into the T01 source. No parent source files were edited by this task.

## Instruction and source integrity

The PC and Codex AGENTS files, canonical pre-implementation prompt, applicable MILSPEC/SOP references, repository AGENTS and historical `.codex` policies were read and SHA-256 indexed in `local-preflight.json`. No additional `AGENTS.md` exists in the target `docs`, `docs/windows`, or campaign directory. Original `UPSTREAM_ADOPTION.yaml`, `FEATURES.yaml`, `CARRY.yaml`, `.codex/SOP.md`, `.codex/UPSTREAM_POLICY.md`, and `downstream/distribution.json` remain unchanged; their input hashes are recorded.

The supplied plan ZIP SHA-256 is `7870af3fa739d541c19b0374f4ac6496e0b561ebf85848f21b5be9a0ad95b738`. Its 28 manifest entries all matched. The campaign retains the historical snapshot `b51c055a12220f8c7c18660e8599365012e19532` and keeps `allow_upstream_sync: false`.

## T01 inventory result

All four frozen upstream commit objects are present and verified; the three ancestry edges from historical snapshot to release base to v0.21.4 to ceiling pass. The v2026.9.21 tag object peels to the recorded v0.21.4 release. The repository is not shallow. The inventory covers 2,777 commits from b51 to v0.21.3, 5,173 from v0.21.3 to v0.21.4, and 993 from v0.21.4 to the ceiling, for 8,943 range commits. The historical ledger contributes 5,105 rows, every referenced commit object and parent list is available, and the combined deduplicated universe contains 14,048 commit SHAs.

Every commit remains `UNREVIEWED`. The historical decision labels are carried as prior claims only; no downstream receipt was verified. All historical rows have categories. The unreviewed union of `SECURITY_CRITICAL` and `DATA_INTEGRITY` contains 1,671 unique commits. The separate seed queue contains 34 family seeds, including 16 P0 seeds; all remain unreviewed. No adoption decision, implementation mapping, test receipt, or semantic conclusion was fabricated.

The helper’s 11 synthetic Git tests passed on Windows via the locked project Python (`uv run --frozen --no-sync python -m unittest docs/windows/workstation-20260924/tests/test_inventory_commits.py -v`). The real metadata run exited 0 and emitted the five JSONL files under `inventory/`. The helper is offline and read-only with respect to Git: no fetch, checkout, reset, commit, or push.

## CodeGraph and remaining T00 boundary

The parent integrator reports the approved CodeGraph 1.6.0 CLI and an index current at clean source HEAD `ebe05b1a`; this docs-only inventory did not issue symbol queries or build/sync an index. The 1.5.0 global CLI was not used. Product-change CodeGraph sync and receipts remain parent-owned.

The parent reported 256 passed and 1 skipped for the focused MCP suite at commit `27685609cd`; that result is clearly separate from this branch and this commit. The historical event-mtime regression reproduction against the recovered tree and actual pre-change base was not performed by this bounded T00/T01 task. T00’s worktree identity, scoped change inventory, and instruction provenance are recorded, but that predecessor/base regression gate remains open for the integrator.
