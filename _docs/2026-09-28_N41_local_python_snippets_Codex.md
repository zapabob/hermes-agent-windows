# N41 partial: local Python snippets use the host interpreter

Repository: `zapabob/hermes-agent-windows`. Product commit `12d272b80fe5cb0ec70cf97e918676dcbddc318c`, tree `fad0829cd41f0861523efd4df17b4ed48355324f`. Frozen D0 `60deb5c75351a19b1a6fa1d778d7d0c2ff627e5b`, R2 `f97608f178d1ffeca59860195ab7da295f7c8e5f`, U1 `678a4762b887f3eabe5cad11254b2ab1ae859485`; old U0 `b936546561888a54d5bf9cd7eae9629a824eb4f7` remains separate. N41 maps only the Python-snippet subset of upstream `bd258480d3cf6a63a12650661f00d4f355568394` at `v0215_to_u1.jsonl:1697`; that commit touches 222 files.

## Source, caller and RED

D0 and the observed local feature have `tools/file_operations.py` blob `a23e9afa056f3c09e8775b673ba3142428a0ec11`; U1 uses `56437d62dcbeff17cdfa7ff41cc099a65de4cd43`. D0 `_try_read_utf16` begins at line 1469, U1 at 690 and integration at 1556. Public `read_file` invokes it for possible UTF-16 content. `delete_file` and `delete_path` invoke `_python_delete` at integration line 2060. The existing `_lsp_local_only` at line 2769 identifies `LocalEnvironment` by actual type.

At parent `e5820950cccb529d8047a1d46ce91e380fe7beac`, the nine-case real LocalEnvironment UTF-16 suite failed six and passed three on this PC. A new local deletion test also failed when the WindowsApps `python3`/`python` aliases returned `Python` instead of executing the program. The test path contained a space, Unicode and an apostrophe, and it checked that nonrecursive file deletion leaves a directory intact. Integration `tools/file_operations.py:1542-1554` now selects `sys.executable` for a real local backend and sends generated Python source as ASCII base64. Remote backends still use their own `python3` and fallback `python`; the existing delete deny-list and directory refusal remain.

## Validation and source binding

At exact product HEAD, 16 focused native cases passed across UTF-16 rescue, the new local delete contract and the prior N40 transport tests. Seven affected files passed 109 with 13 POSIX-only skips and 22 Windows-incompatible deselections. The unfiltered run produced 113 passes, 14 failures and 17 skips. Those 14 cases cover hidden-path fallback, atomic-write permissions, symlink privilege and `/dev` or `/proc` expectations on Windows; the same upstream commit adds Linux-only or symlink-required gates to those tests. Neither run is a full-suite pass.

Changing local interpreter selection back to `python3` killed the UTF-16 BOM case. A separate raw-source transport mutation survived the representative UTF-16 CRLF and Unicode/apostrophe deletion cases; their passing results therefore do not prove that base64 is indispensable on this host. The final source was restored to SHA-256 `39ea6250228e32175dc327bde44427920f4eb51d153c8600a6df0b773412e34b`. Independent read-only Code Reviewer returned CLEAR on the current diff and the upstream file-operations subset, while explicitly retaining the mutation limit. The reviewer did not run tests, CodeGraph, mutations or commit.

Approved CodeGraph 1.6.0 bound separate D0, U1 and post-change integration indexes of 8,881, 12,468 and 8,964 files. All reported zero pending changes and refs. Status, sync, query, explore, valid symbol-name impact, owner/caller map and actual/Git/index hashes are in private `N41-20260927/receipt.json`, SHA-256 `ba2e1d6ac0c1d2078fa0500d1e9cc4d4ad145a0d70dc0c49505a1575b376a1fe`. No private machine root or graph dump is committed.

## Remaining gates and reversal

N41 is PARTIAL. The other product and test changes in the 222-file upstream commit, other U1 ledger rows and the 17,065-row metadata universe remain unmapped. Real Docker/SSH and native POSIX host execution were not verified. The user confirmed the N07-A1 host grant-revocation writer is not implemented; destination outcome durability and T06/T12 remain P0 open, and Control MCP production write stays DISABLED.

Original main and local-feature WIP were untouched. A zero-byte untracked `$tmp` remains in the isolated worktree because automatic approval review rejected its removal with `blocked by policy` and gave no detailed reason. No reset, stash, clean, upstream merge/rebase/cherry-pick, PR, push, production restart or Control MCP production write occurred. Reversal would review and revert only the isolated N41 product commit, rerun affected tests and refresh the integration CodeGraph index; no reversal was performed.
