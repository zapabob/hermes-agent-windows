# T00 Windows EventBridge mtime reproduction

Date: 2026-09-24 (Asia/Tokyo)

## Scope and source identity

This record closes the narrow T00 check for the Windows EventBridge database-mtime fixture. It changes no product code and makes no claim about the broader MCP implementation or aggregate suite.

| Role | Commit | `tests/test_mcp_serve.py` blob | `uv.lock` blob |
|---|---|---|---|
| Report branch base / recovered integration HEAD | `9b275d0818e21d2c5c4db0ba998f2833a42013ab` | `c4567e4da0413a4c1e4981af5a4913ff64df92b9` | `4542bbc44a9e82eb2b5d2fed187891e63278e376` |
| Historical predecessor under test | `aa145e3ae9d02134741b310f2fdd8aa244c15927` | `e31838111f62fb321a770cb1cb9e6154f4e8fb86` | `4542bbc44a9e82eb2b5d2fed187891e63278e376` |
| First fixture correction | `76a194dbe6420863b7b72c14d173645b7464b083` | `45d2792b967414d8c0b9696fd8a670611fe2abe0` | `4542bbc44a9e82eb2b5d2fed187891e63278e376` |
| Later correction included in current HEAD | `dbca4d19cf3c91fb39f7e123eb0829e5118ab088` | current test blob above | unchanged |

All tests ran in separate Windows worktrees checked out at those exact commits. The interpreter was the already-available recovered `.venv` (`Python 3.11.11`, `pytest 9.1.1`, `mcp 2.0.0`). `uv 0.11.29` ran with `--frozen --no-sync`; the lockfile blob was identical at each source. No dependency install or lock edit was performed.

The two focused cases were:

- `tests/test_mcp_serve.py::TestEventBridgePollE2E::test_startup_baseline_suppresses_historical_replay`
- `tests/test_mcp_serve.py::TestEventBridgePollE2E::test_new_conversation_after_baseline_is_delivered`

## Command shape and results

Run from each selected worktree root in PowerShell with `UV_PROJECT_ENVIRONMENT` set to the already-existing recovered `.venv`. The actual absolute environment path is retained only in task context and is omitted here. In the command shapes below, `<recovered-worktree>\.venv` is a redacted placeholder; substitute the appropriate absolute path before running.

```powershell
$env:UV_PROJECT_ENVIRONMENT = '<recovered-worktree>\.venv' # redacted placeholder
uv run --frozen --no-sync python -m pytest tests/test_mcp_serve.py::TestEventBridgePollE2E::test_startup_baseline_suppresses_historical_replay tests/test_mcp_serve.py::TestEventBridgePollE2E::test_new_conversation_after_baseline_is_delivered -q
```

| Source | Result |
|---|---|
| `aa145e3ae9d02134741b310f2fdd8aa244c15927` | `1 failed, 1 passed in 4.28s`; the new-conversation case failed because `len(events)` was `0`, expected `1`. |
| `76a194dbe6420863b7b72c14d173645b7464b083` | `2 passed in 2.57s` in this one run. This is not proof that the remaining `os.utime(path, None)` fixture was deterministic. |
| `9b275d0818e21d2c5c4db0ba998f2833a42013ab` | `2 passed in 2.31s`. |

The predecessor failure was then isolated with this command shape:

```powershell
$env:UV_PROJECT_ENVIRONMENT = '<recovered-worktree>\.venv' # redacted placeholder
uv run --frozen --no-sync python -m pytest tests/test_mcp_serve.py::TestEventBridgePollE2E::test_new_conversation_after_baseline_is_delivered -q
```

At `aa145e3ae9d02134741b310f2fdd8aa244c15927`, it failed again: `1 failed in 2.95s`, with the same `len(events) == 0` assertion at `tests/test_mcp_serve.py:1419`. These are two observed uninstrumented predecessor failures (one in the two-test run and one isolated); the startup-baseline test passed in the combined predecessor run.

## Fixture history and mtime observations

At the predecessor, the new-conversation fixture called `os.utime(db_path, None)`. `_poll_once` returns early when the database `st_mtime` equals its saved baseline, so this fixture can fail to create a detectable transition when the filesystem timestamp does not advance. The first correction at `76a194dbe6420863b7b72c14d173645b7464b083` made the startup-baseline fixture advance `st_mtime_ns` by exactly `1_000_000_000`; that commit did not yet correct the new-conversation fixture. Commit `dbca4d19cf3c91fb39f7e123eb0829e5118ab088` later changed that fixture too, and current HEAD contains explicit one-second `st_mtime_ns` advances in both focused cases.

An auxiliary `os.utime` observer was run through an inline Python wrapper. The wrapper called `stat` before and after the original call, so it perturbed timing; its values are diagnostic observations, not a faithful capture of the uninstrumented failing instant:

| Source / fixture | `st_mtime_ns` before | `st_mtime_ns` after | Delta |
|---|---:|---:|---:|
| predecessor / startup baseline | `1790201462507906000` | `1790201462508904700` | `998700 ns` |
| predecessor / new conversation | `1790201462638873000` | `1790201462640866900` | `1993900 ns` |
| `76a194d` / startup baseline (explicit fixture) | not retained by the wrapper output | not retained by the wrapper output | `1000000000 ns` |
| `76a194d` / new conversation (`os.utime(..., None)`) | not retained | not retained | `1336400 ns` |
| current HEAD / both cases (explicit fixtures) | not retained by the wrapper output | not retained by the wrapper output | `1000000000 ns` each |

The 76a/current observer test run passed both cases (`2 passed in 10.74s` and `2 passed in 5.81s`, respectively). The predecessor observer run also passed both (`2 passed in 6.97s`), consistent with observer overhead masking a timing-sensitive fixture. The incomplete exact endpoints in the two explicit-fixture rows were not printed by the retained run summary; they are deliberately not reconstructed here. In an additional after-only observer run, the new-conversation update was distinguishable from the bridge baseline (`after_ns=1790201869069678200`, `bridge_baseline_s=1790201869.0686917`), but that observer also perturbs timing.

The failing uninstrumented run did not capture `st_mtime_ns` immediately before and after the fixture mutation. Therefore, the evidence establishes a repeated predecessor event-loss failure and the implicated equality-gated mtime path, but does not establish that exact timestamp equality was observed in either failing process. The safe fixture now enforces an explicit nanosecond target one second later.

## Relationship to the older 579/1/3 report

The repository contains a summary of a broader run (`579 passed, 1 failed, 3 skipped`), but no raw pytest log or machine-readable result for it was found in the searched repository/docs/temp/attachment locations. `docs/control-mcp/RETIREMENT_SPEC.md:67` identifies `test_startup_baseline_suppresses_historical_replay`; `docs/control-mcp/IMPLEMENTATION_LOG.md:68` describes only an EventBridge baseline test. Those notes do not identify the original full-suite failure consistently enough to map it to this reproduced `test_new_conversation_after_baseline_is_delivered` failure. The original failing test identity and whether this mtime race accounts for the aggregate's single failure remain unverified. This report does not claim to rerun the old 25-file aggregate.

## Outcome and remaining boundary

The focused predecessor/base reproduction is established for the new-conversation case: it failed twice without instrumentation on `aa145e3`, while the corrected fixture is present and both focused cases pass on current HEAD. The intermediate `76a194d` focused pass is a single sample while its new-conversation fixture still uses current-time `os.utime`; only the later `dbca4d19` correction removes that remaining nondeterminism.

This is local focused Windows evidence only. It is not a full-suite, hosted-CI, mutation, client-compatibility, or security-review result. Temporary historical worktrees were retained intact. No historical checkout, recovered integration checkout, main branch, or T04 worktree was modified.
