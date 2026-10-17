# Selective implementation checkpoint — 2026-10-17

Status: **PARTIAL campaign; seven scoped implementation candidates verified locally.**
An additional native Electron probe subsequently exposed the watchdog-control
isolation incident below. Production-control recovery is pending the human's
expected prior-state answer; this checkpoint is not an operational closeout.
This checkpoint does not supersede the historical V03/V04/V05 or U01–U18
receipts and does not certify complete v0.22.2 parity, Windows release readiness,
or vendor-runtime independence. The machine-readable companion is
`SELECTIVE_20261017.json` in this directory.

## Authority and frozen inputs

The human request was to implement from the implementation plan and inventory.
The three supplied documents are requirements and evidence inputs, not additional
human authorization for production changes, publishing, or use of a dedicated
machine. Historical executor-unavailable statements were verified against the
current native executor rather than treated as a prohibition or success proof.

| Input | Identity |
| --- | --- |
| Protected downstream D_BASE | `abad98beee2b74a135ce7e0e9310910c756514b4` |
| D_BASE tree | `b8cde7b4a87a4ae8003f08b40680ec27dea0bf77` |
| R_BEFORE | `63279301bcbdc185c1b07b98a9312eb0c862f26d` |
| R_AFTER | `d3630f853239e8c41ce7201e09fbdf39bcbc5431` |
| U_RELEASE | `d923a5eb487a17c0a68801bba9ef0f56c81040a8` |
| U_RELEASE tree | `5a064077e8d1de9fc7a4b27efc04f0caa2cb06c0` |
| Annotated tag object | `7b77e29eedd85a8497ce2821448dac7964dc46f6` |
| ZIP SHA-256 | `021f2c546766be94fc92e8ebca7ac3b642e2ed6d217545e0200bfa03b55117c8` |
| FULL_IMPLEMENTATION_PLAN (1).md SHA-256 | `430de3871be23aead7911c1ef4cefc3cd2bfbb94bcfd823ee3497046e8a81e97` |
| START_PROMPT (1).md SHA-256 | `3fc3e05774e46c5904373f7b88287be0c0dcf57161221085bca07a19fc49a835` |

All nine SHA256SUMS entries in the ZIP matched. Of its 32 source records, 31
provided a blob and matched the pinned Git object. `D_WEB_PTY` provided no blob;
the pinned object was resolved as `4edad161b5b0c7e215c1ecddb025965fdf050fa9`,
without inventing an attachment hash claim.

Work was isolated in branch `codex/v0222-selective-20261017` at
`<managed-worktrees>/v0222-selective-20261017/hermes-agent`.
The primary checkout and the previous campaign's dirty worktree were preserved.
No upstream source checkout was put on runtime import or executable search paths.

## Scoped behavior delivered

| ZIP observation | Result and verification boundary |
| --- | --- |
| F01 — model favorites | Renderer preference persists provider/model identities, lists favorites first, retains unavailable catalog entries, and does not select a model when the star is clicked. Component and fresh-module storage tests passed; physical Electron restart and keyboard journey remain open. |
| F03 — status summary | Default/`--short` reads a bounded local summary. `--full`, legacy `--all`, and `--deep` retain detailed diagnostics. A fresh native Python CLI subprocess rejected all socket connect/DNS attempts through an audit hook; summary made no attempts and did not repair/create cron state. |
| B01 — cron baseline | Unknown/corrupt/unreadable stores are refused both before and after staging. Continuous degraded-lock races are refused after bounded retries. Explicit recovery remains possible, id-keyed repair survives, concurrent additions and intended removals retain their semantics. |
| B02 — existing TTS output | Provider and delivery failures preserve existing audio. Publication reserves recoverable originals for the whole output set and rolls back a partial publish. A native Windows deny-delete handle on the second original restores the first; failed rollback retains the original backup with a recovery path. This is in-process rollback, not crash-atomic multi-file publication. |
| B03 — support redaction | Shared reports, all bundle copies, local ZIP attachments and RPC client text use strict fail-closed scrubbing before truncation. Tests cover raw/encoded URL secrets and userinfo, headers/cookies, quoted/truncated/escaped argv, helper/privacy failure, real ZIP bytes, and actual HTTP bytes sent only to a test-owned loopback sink. Source logs and explicit CLI opt-out behavior remain covered. |
| B04 — PTY liveness | Retained bridge liveness frees a dead child even without drained EOF. Reaping checks object identity and current eligibility after every yielding close, preserving same-key replacements and sessions reattached meanwhile. A native ConPTY child exit exercised registry release. |
| C01 — Security results | Displays file verdict, engine health and execution decision separately; legacy/malformed values remain conservative. String arrays are rejected as enum values. Connection/socket changes clear displayed results even with the same profile name; activation epochs fence stale completions. Full quarantine/restore/watch/update/approval acceptance is not claimed. |

The nine preserve decisions remain preserved source observations, not whole-family
acceptance. F02 custom-model UI, F04 `/busy`, and F09 local streaming STT remain
conditional until their actual owner and acceptance requirements are resolved.
An absent upstream filename or registry entry was not treated as a missing feature.

## Validation

The final selected Python evidence is **655 passed, 5 skipped, 0 failed, 0
collection errors**, across 30 independent test-file subprocesses. UI evidence
is **15 passed, 0 skipped, 0 failed**. Reruns, RED results, old campaign receipts
and fault-injection failures are excluded from these pass totals.

The skips are one non-Windows-only test, one POSIX process-group test, and three
symlink/reparse tests unavailable under the current Windows privilege. They are
not counted as native acceptance. No privilege elevation was attempted.

Tests used the prior campaign's qualified native Python 3.12 interpreter as the
documented custom-interpreter SOP exception. Candidate cwd/PYTHONPATH and owned
HERMES_HOME/TEMP/TMP were set explicitly; PYTHONUTF8=1 and
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 were used. Each file ran with:

```text
python -B -m pytest -p pytest_asyncio.plugin -o addopts= TESTFILE
  --basetemp OWNED_UNIQUE --junitxml=OWNED_RECEIPT -q
```

Renderer TypeScript checking, changed-file ESLint, repo-configured Ruff, and
`git diff --check` passed. Locked `npm ci --workspace apps/desktop
--include-workspace-root --ignore-scripts --no-audit --no-fund` installed the
candidate build dependencies without changing manifests or locks.
`npm run build --workspace apps/desktop` and its `assert-dist-built` postbuild
passed after the final renderer edits. Windows node-pty/get-windows addons were
staged by the existing build; the first build fetched the pinned get-windows
9.3.0 binding through its existing node-pre-gyp path. No installer or production
Desktop was launched. The receipt hashes renderer bundles and native addons.
The local Git hook reported that lefthook was not available in PATH; hook
success is not claimed. The checks above were invoked explicitly. Source
bindings distinguish tested Windows worktree bytes from committed Git blob
identities, and the tracked JSON uses LF as required by `.gitattributes`.

Nine named in-memory source-bound faults were killed with assertion failures
and no collection errors: treating unknown cron baseline as empty, all-deny
cron, missing PTY liveness, bypassed PTY object guard, direct TTS overwrite,
missing strict support redaction, missing summary, favorite no-op, and discarded
Security results. This is targeted fault-injection evidence, not exhaustive
mutation coverage.

## Review and graph limits

A fresh read-only investigator examined the security boundary. A separate fresh
read-only reviewer found seven concrete defects in the initial candidate:
space-bearing argv values, later cookie values, cron post-stage read failure,
same-key PTY replacement, partial multi-output TTS publish, same-profile
connection switching, and array-shaped Security enums. Each finding was
confirmed by behavioral RED and corrected; additional escaped-value and PTY
reattachment probes also progressed from RED to GREEN. There was one independent
review cycle. The corrected patches were verified by the implementer; no second
independent clean review is claimed.

Real CodeGraph 1.6.0 used the project-pinned shim and bundled supported Node with
downloads and telemetry disabled. D_BASE was indexed before editing; the
candidate was refreshed after code changes. R_AFTER used a source-bound
15-present-file projection with its own Git root/index; absent paths were
recorded, not fabricated. U_RELEASE used the existing fixed-source graph plus
selected blob binding. `gateway/run.py` exceeds the extractor's 1 MiB cap and
was unchanged; its whole-file graph coverage is not claimed. Graph status is
navigation evidence, not execution or semantic acceptance.

## Population, credit and open gates

The reused V03 raw inventory hashes matched its recorded population of 22,565
commits and 23,218 parent edges. No full-history commit is newly accepted by this
checkpoint. The ZIP's 19 observations, the plan's 20 review rows, 33 prior leads,
and 66 acceptance cases are distinct from that population. Nineteen observations
cannot be subtracted from the commit count. Unmapped final public-surface
contracts remain unenumerated; their count is unknown.

Reporter/discoverer credit remains unestablished where the supplied evidence
does not identify it. Upstream implementer/salvage/co-author credit is separate
from reporter credit. Support parsing was adapted from the fixed upstream helper,
whose path-source commit is `48975fcaa2c81102ee2021d81e9cdac700b056e8`
(kshitijk4poor). Downstream implementation commits are listed separately in the
JSON receipt. Other preserved source credits are carried from the ZIP without
inventing authorship from a last-touch commit.

Mandatory open work includes full-history semantic classification, remaining
public surfaces and conditional/legacy contracts, complete Security and outbound
versus Control MCP effects/lifecycle, a fresh packaged Windows journey and real
model inference, an eight-hour dedicated Windows soak with three physical
sleep/resume cycles, and cold local model/MCP/user-plugin operation without
vendor authorization/catalog/network. The parent runtime did not expose an
accepted model/effort attestation; it was not fabricated or silently substituted.

Only test-owned children, sockets, handles and temporary state were closed.
Machine-local graphs, dependencies and receipts remain in this candidate.
No existing evidence was moved/deleted to recover capacity. No push, merge,
version bump, production restart, sleep, or reboot was performed. Cloud CI was
not run and is not reported green.

## Subsequent native-probe isolation incident — OPEN

After the seven product commits, a new native favorites/restart test reused the
existing Electron fixture. HERMES_HOME and Electron userData were isolated,
but Windows watchdog control was not: `watchdogMaintenancePath` defaults to
`LOCALAPPDATA/HermesWatchdog/maintenance.json` unless HERMES_WATCHDOG_DATA is set.
The test Desktop's quit wrote its own DESKTOP_STOP fence at that workstation
control path. The record's lifecycle HOME is the owned E2E sandbox, not the
production HOME. Its prior contents were not captured, so an exact restoration
cannot be asserted or invented.

Native Electron probes are stopped. The observed record was copied unchanged
to ignored task-owned incident evidence; SHA-256 is
`440370e8e1ff9aedaa0f62574a337520c8b30b0fd9984ba324a1449c513be702`.
No stop-fence clearing, production restart or restoration was performed.
No watchdog lock/state file was found in that default control directory at the
inspection time; whether an active watchdog consumed the fence is unverified.
The known Electron PIDs observed in these test attempts were absent when checked;
complete descendant teardown was not independently captured in advance.

The human was asked whether the prior intended state was normal operation or
intentional stop. Clearing could resume watchdog activity and will not proceed
on silence. Full native restart/model-route acceptance remains NOT ACCEPTED.

The cause was reproduced in two focused environment-builder tests. The fixture
now forces HERMES_WATCHDOG_DATA beneath the sandbox HOME and rejects inherited
or explicit case variants that point elsewhere. Fifteen helper tests across
environment, setup cleanup, binary lookup and listener ownership pass. A fresh
independent read-only review found no P1/P2 escape in the watchdog-path repair,
and one P2 in the new restart probe's teardown. That probe now tracks the current
application handle and preserves sandbox state if closure or launch ownership
is uncertain; the change is typechecked, not yet verified by a native rerun.
No further Electron run has been used to claim safety or acceptance.

The next goal continuation verified the same failure class in the shared fixture
cleanup. Four behavioral RED cases (with four positive controls passing) exposed
deletion after unconfirmed mock exit, silently accepted no-provider/dead-backend
exits, and deletion after a failed first-window startup whose process could not
be stopped. A common close-and-cleanup owner now preserves the sandbox until
the captured process has a terminal exit state; a typed shutdown error preserves
failed-start evidence too. All four fixture kinds, including packaged, use that
owner. The packaged binary itself was not launched.

Supplemental helper results are 22 passed, no failures/errors/skips. They use
in-memory Electron handles, a real owned loopback listener and actual temporary
files; they are not native Electron acceptance. Changed-file ESLint and the E2E
TypeScript project passed. Three source-bound faults (delete a live sandbox,
retain every sandbox, delete failed-start evidence) were killed with assertion
failures and no collection errors. The repair is local commit
`5ed8a8d079489b97447851dc25f1bdfe09579974`; the earlier reviewer identified
the unsafe cleanup owner, and no post-fix independent clean review is claimed.
The earlier 655 Python/15 UI and 15-helper receipts remain separate historical
counts, not added to this 22-case rerun.

No production control file was changed during this continuation. Its observed
hash still matches the retained incident snapshot. The expected prior-state
answer remains pending; automatic goal continuation supplies no clearing
authority. The original objective remains active and unachieved.

The preceding native attempts are distinct: the first could not resolve the
binary after ignore-scripts installation; an exact-version existing Electron
41.10.7 binary was then reused read-only through the test process PATH. The next
attempt hit the intentional parked-pointer guard (explicit real mouse movement
fixed the harness). The later attempt successfully starred and reordered the
model without changing config or inference, but failed at native quit/restart
with the control-path escape above. These are not counted as a complete GREEN.

Conditional F02 source tracing found the existing Custom Endpoints UI's
free-form model field and profile-scoped save/activation owner. Twelve selected
custom-endpoint tests passed (174 deselected, excluded from pass totals). This
is additional existing-contract evidence, not full unlisted-model inference
acceptance. No duplicate custom-model owner or streaming STT stub was added.

The dated `_docs/2026-10-17_v0222_selective_implementation_Codex.md` log remains
local under its existing ignore rule; it was not force-added. This tracked
checkpoint and JSON receipt provide the durable repository record.
