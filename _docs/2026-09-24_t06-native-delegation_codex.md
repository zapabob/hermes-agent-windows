# T06 native Windows delegated execution preparation

## Status

This is a preparation commit for T06. The native boundary module and its gated Windows test harness are not yet a proven usable boundary: the positive tests require an explicitly approved AppContainer profile experiment. No AppContainer profile was created and no ACL was changed outside pytest-owned temporary directories.

The isolated worktree is `H:\hermes-control-mcp-t06-native-20260924`, branch `codex/t06-native-boundary-h-20260924`, starting at `98e1be6e94bab5cc0d70d4a827f826e3a6a020b2`. Before-edit CodeGraph receipts are `evidence/codegraph/T06-98e1be6-source-map.md` and `evidence/codegraph/T06-98e1be6-before.json`.

## Native observation

With a derived AppContainer SID that had no registered profile, the Windows `CreateProcessW` attempt failed with `WinError 2`. The focused test `test_unregistered_appcontainer_name_fails_closed` passes by asserting this failure. The pytest fixture granted the derived SID access only to directories under pytest's H-drive `tmp_path`; it did not call `CreateAppContainerProfile`. This establishes fail-closed behavior when profile setup is absent. It does not establish that a useful process can run inside an AppContainer or that its filesystem and network denials work.

## Gated profile experiment

The fixed profile name is `HermesDelegated-T06Pytest-20260924`. The harness requires both `--allow-t06-ephemeral-appcontainer-profile` and the exact matching `--t06-confirm-appcontainer-profile` value before it calls the profile API. The test's `--basetemp` must be an absolute path inside this isolated worktree, on the same volume as the checkout. ACL helpers independently assert every grant target remains under pytest's `tmp_path`.

The sequence is:

1. Derive the expected SID using `DeriveAppContainerSidFromAppContainerName` and record a recovery marker beside the unique basetemp. The marker binds the fixed profile name, current Windows user SID, derived AppContainer SID, and lifecycle state.
2. Call `CreateAppContainerProfile` for the current user with no capabilities. The harness refuses an existing profile and never treats an already-existing profile as test-owned.
3. Call `GetAppContainerFolderPath` for the created SID and store the returned local-app-data path in the marker.
4. Run each contained process with no capabilities and with temporary test ACLs limited to pytest-owned H-drive directories. Close process and job handles, then call `DeleteAppContainerProfile`. Retry once after a short delay if the API reports failure; retain a `cleanup-failed` marker if the result remains unsuccessful.
5. If a test run is interrupted after the marker reaches `created`, use the cleanup gate with the exact profile name, the prior marker path, and a fresh `--basetemp`. Cleanup checks the recorded user SID and derives and matches the AppContainer SID before deletion. A `creating` marker is deliberately insufficient for automatic deletion because interruption could have occurred either side of the profile API; that narrow case requires manual state review and a separate explicit decision.

Microsoft documents the profile as current-user and per-app, with per-user folders and registry storage. Its local app-data path is obtained dynamically with `GetAppContainerFolderPath`; the documented shape is `%LOCALAPPDATA%\Packages\<profile-name>\AC`, with AppContainer `TEMP` and `TMP` under that profile's `Temp` directory. The registry storage location is OS-managed and is not inferred as a literal path. The harness records the API result rather than assuming the current machine's resolved path. The deletion API requires profile file handles to be closed first and says a failed deletion can leave state undetermined, which is why the harness retries once and retains its marker on failure.

References: [CreateAppContainerProfile](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile), [Launch an AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer), [GetAppContainerFolderPath](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-getappcontainerfolderpath), and [DeleteAppContainerProfile](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deleteappcontainerprofile).

## Temporary test ACL scope

For each profile-gated test, ACL changes apply only to paths rooted under that test's pytest `tmp_path` in the H-drive worktree. The copied Python runtime gets AppContainer read/execute access; the copied Node.js and Git trees get read/execute access; the synthetic workspace and its private temp directory get modify access. The fixture checks containment before invoking `icacls`. No `icacls` call targets the source installations, user profile, repository outside pytest `tmp_path`, or any other machine path.

## Probe matrix

The harness contains six profile-gated behavior probes plus four safe profile-free test cases:

| Probe | Expected evidence | Run state |
| --- | --- | --- |
| Useful Python `-S` task in workspace | AppContainer token; correct cwd; parent synthetic environment secret absent | Not run; profile gate closed |
| Node.js `-e` task | Node writes a synthetic JSON result only in workspace | Not run; profile gate closed |
| Local Git init | Git initializes a new synthetic repository only in workspace | Not run; profile gate closed |
| Outside-workspace synthetic secret | Child cannot read a sibling file or return its sentinel | Not run; profile gate closed |
| Parent process file handle | Child cannot duplicate a parent-owned synthetic file handle | Not run; profile gate closed |
| Loopback TCP, HTTP, and UDP | Child is denied; local synthetic sinks receive no traffic | Not run; profile gate closed |
| Unregistered AppContainer | Missing profile launch fails closed with `WinError 2` | Passed |
| Unbound host profile | Launch is denied before OS process creation | Passed |
| ADS and UNC paths | Host policy refuses alternate data stream and remote/device paths before open | Passed |

The network test uses only `127.0.0.1`, a temporary HTTP sink, and a synthetic UDP DNS-shaped payload. It does not contact an external resolver or network endpoint.

## Verification receipts and limits

- `uv run --offline python -m py_compile` succeeded for the boundary module and Windows test files.
- Four profile-free focused cases passed with an H-drive `--basetemp`.
- The positive Python test was run with the default gate and skipped before profile creation.
- `pytest --collect-only` listed nine cases without executing profile-gated probes.
- Ruff is not installed in the locked environment; its attempted invocation exited before analyzing files.
- The Node, Git, outside-secret, parent-handle, and loopback assertions remain unverified until the separately approved profile experiment.
- Foreground `LocalEnvironment` and background `ProcessRegistry` are not yet wired to this adapter. Same-user fallback is intentionally absent. Existing Docker isolation was not changed.
- No ChatGPT/Codex client, MCP protocol, real host approval, Docker, or broader integration test was run by this T06 preparation.

## Commands reserved for a separately approved experiment

Create, exercise, and normally delete the one fixed profile in a new H-drive pytest target:

```powershell
$env:UV_CACHE_DIR = 'H:\hermes-control-mcp-t06-native-20260924\.uv-cache'
uv run --offline pytest tests/windows/test_delegated_execution_boundary.py -q `
  --basetemp 'H:\hermes-control-mcp-t06-native-20260924\.t06-profile-run-20260924-01' `
  --allow-t06-ephemeral-appcontainer-profile `
  --t06-confirm-appcontainer-profile 'HermesDelegated-T06Pytest-20260924'
```

The command above was not run. If a run is interrupted after the recovery marker reaches `created`, first use a separate fresh temp target; replace the marker argument with the exact sidecar emitted by the creation command:

```powershell
$env:UV_CACHE_DIR = 'H:\hermes-control-mcp-t06-native-20260924\.uv-cache'
uv run --offline pytest 'tests/windows/test_delegated_execution_boundary.py::test_delegated_python_runs_inside_the_native_boundary[HermesDelegated-T06Pytest-20260924]' -q `
  --basetemp 'H:\hermes-control-mcp-t06-native-20260924\.t06-cleanup-only-20260924-01' `
  --cleanup-t06-ephemeral-appcontainer-profile `
  --t06-confirm-appcontainer-profile 'HermesDelegated-T06Pytest-20260924' `
  --t06-appcontainer-recovery-marker 'H:\hermes-control-mcp-t06-native-20260924\.t06-profile-run-20260924-01.t06-appcontainer-recovery.json'
```

The cleanup command was not run. It is only safe when the marker reports `created` or `cleanup-failed` and its user and AppContainer SIDs match the current user and fixed name. Neither command changes endpoint configuration, network firewall rules, user accounts, source-tool ACLs, or persistent ACLs.

## Remaining T06 work

This preparation does not complete T06. After the separate approval and successful native probes, implement lifecycle ownership and integrate the same fail-closed adapter into foreground `LocalEnvironment` and background `ProcessRegistry`, then verify useful operations and every denial against the real Windows boundary. If the AppContainer APIs or current Windows policy cannot produce both useful operations and the required denials without persistent changes, stop and report the concrete blocker.