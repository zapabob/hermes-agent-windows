# T06 pre-change CodeGraph source map

Repository: `zapabob/hermes-agent-windows` in the isolated H: worktree on
`codex/t06-native-boundary-h-20260924`. Source HEAD is
`98e1be6e94bab5cc0d70d4a827f826e3a6a020b2`; `git status --porcelain` was
empty. The source fingerprint in the paired receipt is SHA-256 of UTF-8
`git ls-files -s` output joined with LF and terminated by LF (12,348 index
entries). No raw query transcript is committed.

CodeGraph `@colbymchenry/codegraph` 1.6.0 was invoked from the approved
existing Windows CLI at `C:\Users\downl\Documents\New project\hermes-agent\.tools\codegraph-cli\node_modules\.bin\codegraph.cmd`.
The index identity is this worktree's ignored `.codegraph` directory. Initial
indexing completed with 8,905 files, 190,577 nodes, and 609,972 edges; a
subsequent `status .` reported 8,906 files and `Index is up to date`. The
initialization process and its Node workers exited before this receipt was
written. The index is local-only and excluded from Git.

## Local execution owner and impact

`explore LocalEnvironment ProcessRegistry owned Windows process creation cleanup`
located `tools/environments/local.py` and returned the concrete
`LocalEnvironment.cleanup` implementation at line 2233. The broad phrase also
matched unrelated watchdog-go process symbols; those are not treated as the
delegated execution owner. `impact LocalEnvironment` returned 133 affected
symbols and named regression areas including `tests/tools/test_windows_native_support.py`,
`tests/tools/test_local_env_windows_msys.py`, `tests/tools/test_local_interrupt_cleanup.py`,
`tests/tools/test_env_passthrough.py`, `tests/tools/test_local_env_blocklist.py`,
and `tests/tools/test_local_background_child_hang.py`.

`query ProcessRegistry` located the independent background-process owner at
`tools/process_registry.py:445`, including its `get`, `poll`, and
`has_any_active` methods. It must be directly checked to determine whether its
launch, completion, cancellation, and cleanup paths can share the same native
adapter as foreground `LocalEnvironment` execution.

## Direct checks required before implementation

- Trace terminal dispatch into foreground and background execution and check
  whether both can require the same trusted, non-model-supplied execution
  context.
- Preserve ordinary LocalEnvironment behavior, including Windows Git Bash/MSYS
  cwd handling, environment filtering, timeout, interruption, and cleanup.
- Prove the selected Windows token and ACL boundary using useful Python, Node,
  and read-only Git commands, plus synthetic secret, outside-workspace,
  parent-process, and loopback network denial tests.
- Check handle inheritance, descendants, Job Object assignment/limits,
  symlinks/reparse paths, ADS, and breakaway. CodeGraph does not prove any of
  these OS behaviors.
- Keep Docker's existing engineering isolation/fail-closed path unchanged.

Coverage disposition is `NEEDS_DIRECT_CHECKS`; CodeGraph navigation is not
native execution or security evidence.
