# U01: bind interactive MCP OAuth to the saved configuration

Date: 2026-10-13. Scope: Windows-native semantic adoption, local commit only.

## Behavior and adoption

ADAPT: bind an interactive OAuth attempt to its canonical Hermes home, logical server name, raw saved entry and effective configuration. Revalidate authority at callback entry, actual token persistence and final provider adoption. A removed, disabled, renamed or replaced configuration must not let an old attempt overwrite current credentials or provider state.

Configuration read-modify-write paths cooperate through the existing reentrant lock. Lock sections exclude network requests, async waits, thread joins and listener shutdown. Raw saved configuration is retained instead of persisting expanded secret values or a stale whole configuration. Rollback is limited to the attempt's owned generation/content/provider object, including protection of a newer writer that saves identical contents.

Public success and callback error behavior is preserved. This establishes guarantees for cooperating writers in one process; arbitrary external file writers and cross-process atomicity are not qualified here.

## Verification

The unchanged 13-file source set retains the independently qualified native corpus: 71 saved-configuration cases, 11 writer cases and 29 repair cases, all passing. Original positive controls reached OAuth grants and protected tool effects; negative cases covered stale configurations, callback state/replay and competing writers.

Focused existing impact regressions ran through the unchanged repository parallel runner on native Windows, one fresh process per file, no file retries, 300-second file timeout, UTF-8/UTC and a credential-free isolated home. The runner duration cache and logs were directed to the evidence drive. The nine-file result was 354 passed, 0 failed and 1 skipped in 55.2 seconds, exit 0.

The sole explicit Windows-conditional skip in the selected test bodies is test_token_file_created_with_0o600, which checks POSIX permission bits. The aggregate skip is consistent with this marker; the quiet runtime log does not name the skipped case. This evidence does not certify NTFS ACL behavior.

Existing CodeGraph owner/caller mappings were current and used to select OAuth storage, issuer, provider-manager and configuration-writer regressions. No redundant reindex was needed. A blanket mutation gate was removed by the user's simplified acceptance policy; a concrete unsupported critical invariant would still require additional evidence.

## Evidence and acceptance boundary

Frozen sources and prior results: U01_R3_FROZEN_HANDOFF_MANIFEST_20261013.json and U01_R3_NATIVE_111_AND_PRESERVATION_20261013.json. Prior source/native reviews are preserved. Current execution record: U01_SIMPLIFIED_CLOSEOUT_20261013.md. Final independent verdict: U01_SIMPLIFIED_FINAL_REVIEW_20261013.md.

This U01 change does not complete U02, certify every OAuth path, update the product version or qualify the complete Windows 0.21.7 package. The broader campaign remains pinned to upstream 63d0b94120027d487c9a5235b9ec64b696af1b26. No upstream refactoring, dependency change, live restart, push or publication is included.

The pre-change local restore reference is 5c859bf3850f5b5abca7f7fc916afe98f4cbb1ec. If rollback is required after this commit, revert this one U01 commit on the isolated branch; do not reset or clean unrelated work.