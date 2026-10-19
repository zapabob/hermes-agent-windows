# T06g process-local permanent-save serialization

Isolated CI worktree, base 47d0473adb2842b4fc9bbce5cbdbfefec77cb716. No commit/push/runtime or dependency action.
Only tools/approval.py and hermes_cli/approvals_suggest.py product changes.
Exact independently source-reviewed v2 bytes: approval 24aeca0e3de89143bf7a08b4488c2165437568813ea223d0e0cc03ddba6f44b5;
CLI d96c39e051c44a9bb63a3f08a1cf2cea54722dac3072733d2b74449fb13aba66.

Dedicated process-local RLock protects payload creation/load/save. Approval lock
is held only for snapshot or memory update, never disk I/O. CLI passes selected
additions to an explicit atomic read/merge/save/memory-sync operation. Replacement
including empty remains exact; valid ALWAYS is not revoked after owner retirement.

Same-worktree baseline: three behavioral lost-update REDs, seven positives,
zero errors/skips/refusals/recovery. Final: 11 qualified normal Jobs,
244 unique PASS; ten semantic fault variants, 13
failed occurrences, 11 unique failed nodes all normal GREEN. Two native/
platform-specific deselections are excluded, not counted as PASS. All guards stay.

Sealed oracle copied by original hash; only imports plus sandbox fixture wiring
ported. All original function/class/assertion bodies and four helper bodies match
sealed bytes. Ordinary pytest missing-STEER scope was exercised under the same
outer Job/file guard. No old fixture/test/assertion or old evidence changed.

Final graph: 16 selected files,
823 matching spans, actual immutable DB
1380 nodes/3746 edges, integrity OK.
Full run.py SDK unresolved references and module-alias query limitations remain;
this is not a root/full SDK/whole-SHA proof. Old 89-file manifest verified unchanged;
v0222 approval retains 43872. Historical generations are preserved separately.

Evidence: tmp/probes/t06g-ci-20261020/evidence/receipt.json and evidence_hashes.json.
Product source is on stable HOLD for independent runtime/evidence review. No further
product edits or source-dependent Jobs planned absent a concrete review finding.
Parent owns composition/integration. Cross-process/direct config/revocation/I/O
failure policy/native/R6/whole-SHA acceptance remains outside this change.
