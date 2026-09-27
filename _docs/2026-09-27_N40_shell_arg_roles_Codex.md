# N40 partial: preserve non-path shell argument bytes

Repository: `zapabob/hermes-agent-windows`. Product commit `1efe1bfe1abc5c5f0bfc7b8f949f1cc77523ff65`, tree `675b2f2428f9540386c4db80eef77a36f34f0192`. Frozen D0 `60deb5c75351a19b1a6fa1d778d7d0c2ff627e5b`, R2 `f97608f178d1ffeca59860195ab7da295f7c8e5f` and U1 `678a4762b887f3eabe5cad11254b2ab1ae859485` were not advanced; old U0 `b936546561888a54d5bf9cd7eae9629a824eb4f7` remains separate. Upstream `948c9dbfc0b0e87b1ef4b2b0396750372f75afe6` is ledger row 1355 of `v0215_to_u1.jsonl`; N40 maps only its shell-argument role contract.

## Source, caller and RED

D0 and the observed local feature share `tools/file_operations.py` blob `a23e9afa056f3c09e8775b673ba3142428a0ec11`, where `_escape_shell_arg` begins at line 1234 and has no non-path role. U1 blob `56437d62dcbeff17cdfa7ff41cc099a65de4cd43` begins that method at line 490 and restricts non-path backslash compensation to local Windows. The fork's path translation must remain for actual path arguments, while regular expressions, globs and embedded Python programs must retain their literal backslashes. Public grep search and UTF-16 rescue are actual callers.

At parent `a2e4b963e6644034bd00f57a5cdd8837a965ee38`, four native local/serialized tests failed: the role keyword was absent and the public `alpha\.beta` search returned zero matches instead of the one literal-dot line. After the initial helper change, two additional UTF-16 rescue cases exposed still-translated Python-program escapes, which prevented expected BOM and newline handling. The final `tools/file_operations.py:1303-1321` distinguishes paths from non-path values, updates the search and program callers, and preserves existing single-quote escaping.

## Validation and source binding

At exact product HEAD, all six new cases passed using a real Git Bash child with both local argv and serialized-script transports. The UTF-16 test substitutes `sys.executable` at the test command boundary because this PC's `python3` and `python` resolve to inert WindowsApps aliases; the generated production program is still exercised. The filtered affected Windows selection passed 110, skipped 12 POSIX-only cases and deselected 19 Windows-incompatible cases. An unfiltered affected run passed 113, skipped 12 and failed six existing `TestUtf16Read` cases from the alias issue; ten were deselected, including two previously observed Windows multiline failures. These runs are not full-suite success.

Three controlled mutations failed their relevant tests: path translation of non-path text, path translation of the public search regex, and path translation of the UTF-16 Python program. The source was restored with SHA-256 `9c0501e02c8876ee20d3cd9ccac2f9c2946e4a890a3be96d11be1027e27f1b57`. Independent read-only Code Reviewer initially BLOCKED two omitted Python-program callers. After both and the native regression were fixed, the reviewer re-read the actual diff and returned CLEAR. It did not run tests, CodeGraph, mutations or commit.

Approved CodeGraph 1.6.0 bound separate D0, U1 and post-change integration indexes of 8,881, 12,468 and 8,963 files. All reported zero pending changes and refs. Status, sync, query, explore, valid symbol-name impact, owner/caller results, and actual/Git/index hashes are retained in private `N40-20260927/receipt.json`, SHA-256 `75766d3177f078f3f6b5ef3fa95b46caee9e61598f4c46f070335b47000ec5c3`. The committed family card does not contain the private machine root or graph dump.

## Remaining gates and reversal

N40 is PARTIAL: the rest of upstream `948c9dbf` and the R2-to-U1 ledger remain to be mapped; real Docker/SSH backends and native POSIX hosts were not exercised. The existing UTF-16 cases still fail on this PC's inert WindowsApps Python aliases. No OS setup or additional installation was performed. The user confirmed N07-A1's grant-revocation host writer is not implemented; destination durability and T06/T12 remain P0 open, and Control MCP production write stays DISABLED.

Original main and local-feature WIP were untouched. A test-created zero-byte untracked `$tmp` remains in the isolated worktree because automatic approval review rejected its removal with `blocked by policy` and no detailed reason. No reset, stash, clean, upstream merge/rebase/cherry-pick, PR, push, production restart or Control MCP production write occurred. Reversal would review and revert only the isolated product commit, rerun affected tests and refresh the integration CodeGraph index; no reversal was performed.
