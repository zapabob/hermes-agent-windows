# Selective implementation checkpoint — 2026-10-17

Status: **PARTIAL campaign; initial seven candidates plus supplemental F02/F04 scoped proof below.**
**Native testing is HELD:** a subsequent probe changed the host `hermes://`
registry command. Its current key is backed up; a separate explicit human
restore-target question remains pending. F01 native acceptance is NOT_ACCEPTED.
A native Electron probe exposed the watchdog-control isolation incident below.
The human-authorized removal of its exact test-origin stop marker is complete;
watchdog subsequently reports NORMAL but backend down and embedding disabled.
This checkpoint is not an operational closeout. The eight-hour real-model soak
and three physical sleep/resume cycles are NOT_RUN by the user's direction.
The latest whole-project CodeGraph refresh is incomplete after database locking;
the current protocol prevention proof uses a complete selected-owner graph.
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
| F04 — Gateway busy policy | Per-conversation `/busy` persists queue/steer/interrupt through existing owners; accepted input keeps its order across text and queue commands during save, and stop cannot revive stopped backlog or remove a replacement run. Supplemental 218 Python cases and seven fault detections below; actual-channel/model acceptance remains open. |
| B01 — cron baseline | Unknown/corrupt/unreadable stores are refused both before and after staging. Continuous degraded-lock races are refused after bounded retries. Explicit recovery remains possible, id-keyed repair survives, concurrent additions and intended removals retain their semantics. |
| B02 — existing TTS output | Provider and delivery failures preserve existing audio. Publication reserves recoverable originals for the whole output set and rolls back a partial publish. A native Windows deny-delete handle on the second original restores the first; failed rollback retains the original backup with a recovery path. This is in-process rollback, not crash-atomic multi-file publication. |
| B03 — support redaction | Shared reports, all bundle copies, local ZIP attachments and RPC client text use strict fail-closed scrubbing before truncation. Tests cover raw/encoded URL secrets and userinfo, headers/cookies, quoted/truncated/escaped argv, helper/privacy failure, real ZIP bytes, and actual HTTP bytes sent only to a test-owned loopback sink. Source logs and explicit CLI opt-out behavior remain covered. |
| B04 — PTY liveness | Retained bridge liveness frees a dead child even without drained EOF. Reaping checks object identity and current eligibility after every yielding close, preserving same-key replacements and sessions reattached meanwhile. A native ConPTY child exit exercised registry release. |
| C01 — Security results | Displays file verdict, engine health and execution decision separately; legacy/malformed values remain conservative. String arrays are rejected as enum values. Connection/socket changes clear displayed results even with the same profile name; activation epochs fence stale completions. Full quarantine/restore/watch/update/approval acceptance is not claimed. |

The nine preserve decisions remain preserved source observations, not whole-family
acceptance. F02 retains its existing custom-endpoint owner with the supplemental
contract proof below; native acceptance remains open. F04 `/busy` now has scoped
owner/behavior proof below, while its actual-channel/model acceptance remains
open. F09 still requires an actual local incremental recognizer and assets.
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

F02 verification commit `27a361d2d39feea36382d03f9b142b3ab42e3eea` adds tests
without product changes. One UI test enters a model absent from discovery,
preserves it through validation/save and reloads the saved provider identity.
Two Python cases save through the real profile-scoped REST owner, then use a
fresh native Python process to read the shared picker inventory and runtime
credentials. The SDK sends the saved model to an owned HTTP protocol fixture;
both no-key and dedicated-profile-key cases pass. Default config bytes stay
unchanged and the dedicated synthetic key is stored in the selected profile's
`.env`, outside config YAML. A real `/v1/models` response deliberately omits
the selected model; it remains in the saved picker row and chat request.

These **2 Python / 1 UI** cases are supplemental, excluded from the historical
655/15 totals. Two faults replacing the manually entered model with a discovered
model were killed by assertions with no collection errors. Raw product hashes
are distinguished from the Vite transform-input hash in the mutation record.
Configured Ruff, zero-warning changed-file ESLint, renderer typechecking via
`tsconfig.typecheck.json` and diff hygiene pass. CodeGraph 1.6.0 was synchronized
with zero pending changes; this does not remove the existing large-file coverage
limitation for `gateway/run.py`.

Qualified fresh-process probes use owned user/config homes and PATH, deny helper
subprocesses, deny foreign socket connections, and reject foreign DNS before
resolution. Public catalogue and synthetic-key provider discovery still attempt
DNS; the receipt records those blocked attempts rather than claiming discovery
is offline. Earlier harness errors (an unsupported resolver-model assumption,
unisolated gh discovery, and overstrict zero-DNS expectations) are excluded from
product RED evidence. The final proof joins inventory and runtime credentials
at the SDK boundary, not inside an AIAgent conversation. Separate UI stubs and
backend probes do not certify a native Electron journey or loaded-model
inference. The watchdog incident and expected-prior-state question remain open.
An independent read-only review found no actionable P1/P2 within the two new
tests' isolation/false-acceptance scope. It started against the pre-commit
working files; final diagnostic refinements proceeded in parallel, so it is
not an exact-final-commit review or independent runtime attestation.

F04 intake identified a prerequisite defect in the existing session-metadata
setter: serialization or persistence failure left the requested value active
in memory, allowing an unrelated later save to revive it. Commit
`56f9d1fba272f556fff77cf8551e0fdf0ac7b1d1` persists a separate candidate before
publishing it. It retains the existing whole-index write, primary DB/legacy
mirror fallback, shared generation ordering and unchanged activity timestamp.
Four confirmed behavioral RED failures and one positive primary-commit control
became **5 passed**; the existing session test file separately passed **65**.
These counts are supplemental, not added to the historical 655/15 totals.
Two source-and-test-bound faults (mutate before save; skip durable save) were
killed with four/five assertion failures and no collection errors. Ruff and diff
hygiene pass. An independent read-only reviewer found no P1/P2 within the
setter/recovery/persistence/generation scope; its start/end source hashes match
the committed files. It did not independently execute the tests.

This fixes the metadata prerequisite, not the Gateway `/busy` feature. The
registry remains CLI-only. The inventory explicitly forbids another profile or
chat receiving the mode and forbids stopped messages reviving; the upstream
profile-wide config mutation cannot be copied without resolving that contract.
A four-file source-only projection was prepared, but its first index invocation
resolved the parent campaign index instead. It is not a qualified F04 graph,
and its pre-fix session snapshot must be regenerated before use. The campaign's
actual CodeGraph 1.6.0 index was refreshed for the metadata change with zero
pending changes; whole `gateway/run.py` coverage is still not claimed.

The dated `_docs/2026-10-17_v0222_selective_implementation_Codex.md` log remains
local under its existing ignore rule; it was not force-added. This tracked
checkpoint and JSON receipt provide the durable repository record.


Human-authorized recovery supplement (2026-10-17): the user confirmed the
workstation was previously in normal operation and authorized removing the
test-origin stop designation. The recovery opened the exact production marker
with write/delete sharing denied, verified SHA-256
`440370e8e1ff9aedaa0f62574a337520c8b30b0fd9984ba324a1449c513be702`
and the recorded test lifecycle HOME/nonce/owner, durably backed up the bytes,
then set deletion disposition on that same file handle. The path was absent
after close. Evidence is retained under
`tmp/selective-20261017/watchdog-isolation-incident/authorized-recovery-20261017T061146Z-ac176a1e/`.
No forced restart was issued. This resolves the pending human-answer/removal
gate, not runtime health or complete native acceptance; pre-test bytes were
never captured, so byte-exact restoration is not claimed. Earlier open-incident
statements above describe the historical checkpoints.

The user also confirmed no dedicated Windows test environment is available and
directed recording the real-model eight-hour soak and three physical
sleep/resume cycles as **NOT_RUN**. The user workstation will not substitute
for those tests. Their absence is a qualification limitation, not a passing
result or an outstanding request for an environment from the user.

Follow-up recovery observation at 2026-10-17T06:17:13Z: watchdog state reports NORMAL, and its reported PID exists with process name hermes-watchdog. The same state reports desktop=up, backend=down, embedding=disabled; these are watchdog reports, not independent backend/model probes. The test stop marker remained absent. No forced restart was issued; complete running-model health is not claimed.


F04 scoped implementation supplement: commit
`ea150c8c08c0bea351b1ff2ad92edc142ae39a0d` adds Gateway `/busy
queue|steer|interrupt|status` through the existing command, SessionStore,
adapter and FIFO owners. The setting persists per conversation and overrides
the routed profile default without modifying that default. Idle and active
commands share the existing authorization gate. Save failure retains the prior
mode; an existing conversation does not enter the expiration/reset path.
Already accepted debounce input precedes both ordinary input and `/queue`/`/q`
arriving while a worker's save is published but its reply is pending. `/stop`
discards all stopped backlog before yielding, then guards cleanup against a
replacement generation. No system prompt or toolset reload was introduced.

Final native Python validation is **218 passed, zero failures/errors/skips**
across 19 fresh test-file processes, including 31 feature cases. Seven final
source/test-bound behavioral faults were killed with assertion failures and
zero collection errors. These supplemental counts are separate from historical
655 Python/15 UI results. The final alias-race RED was two failures/29 positive
controls. An earlier expiry test failed its setup because reset defaults to
none; that failure and the intermediate mutations containing it are excluded.
Final expiry cases explicitly use idle/daily/both, and restoring the resetting
creation call fails all three. Independent final source review found no P1/P2;
all eight start/end source hashes match the tested committed source. Ruff and
diff hygiene pass; the absent Lefthook executable is not reported as a pass.

Real CodeGraph 1.6.0 was refreshed. The explicitly initialized final selected
owner projection contains 11 files, 1,234 nodes and 3,224 edges, with no pending
changes. `gateway/run.py` still exceeds the extraction cap, so full-file graph
coverage is not claimed. The projection binds exact source ranges and is never
executed as runtime code. The actual full source is used by the Python tests.
F04 whole-family/live-channel/actual-model acceptance remains open: the active
leaf agent is mocked, and no new native Electron or actual model run occurred.

F09 read-only inventory confirmed that current local owners transcribe completed
files, frozen upstream streaming excludes local/local_command, and the existing
sherpa owner is a keyword spotter. An actual incremental ASR provider, matching
local model and task-owned audio fixture remain to be established; no ABC-only,
toggle-only or mocked-recognizer completion is claimed.


Host protocol incident supplement: subsequent native probes exposed another
escaped OS write. Startup unconditionally registered the real per-user
`HKCU\Software\Classes\hermes\shell\open\command` default value, pointing
it to the qualified test Electron with a candidate `--inspect=0` entry path.
HOME/userData/watchdog confinement does not isolate this registry API. The
current exact key snapshot (SHA-256 `33693e7fd5f627dfae4cf39e9e87f2fc646caeba4dd29667b8c99b6ab4cecad1`) and a
reviewable canonical packaged-Hermes restore proposal are retained under
`tmp/selective-20261017/protocol-association-incident/`. No pre-test registry
baseline exists. A separate explicit human restore-target question is pending;
the earlier watchdog-stop permission does not authorize this change. No registry
restoration, production application restart or forced descendant stop was performed.

Native runs are HELD. V1 and V2 reported one Playwright pass each, but neither
is accepted: V1 had a reduced-PATH process-identity fallback and weak request
correlation; V2 lacked the final request-lifetime check. Both also registered
the host scheme. V3 failed with a typed observer ETIMEDOUT in finally; its
controller captured 210 identities and initially observed two remaining
Electron identities. Both were ALREADY_EXITED at the later identity-specific
check, without force. Its HOME/evidence remains retained. The watchdog marker
was absent before/after all three runs. These observations do not make F01 a
native acceptance success and do not weaken the completed F04 scoped proof.

Prevention commit `ae9aed87962bafe2b03d3b2078b7ebdb9adcb20e` extracts the actual registration owner, wired
from the existing startup wrapper. Direct-import fake-API tests replace the
discarded source-reading/AST/VM draft. A pre-guard boundary counterfactual had
three assertion failures and three positive controls; final direct-owner and
existing fixture/fence suites pass 28 cases. Three actual helper faults are
killed (two/one/one assertion failures, no collection errors). ESLint has zero
warnings; Electron typecheck and diff hygiene pass. Independent final review
found no P1/P2, with matching start/end hashes of all three committed files.
No native run of the fixed source or new packaged build has occurred.

The real CodeGraph 1.6.0 final selected-owner graph is complete: seven exact
files, 861 nodes, 2,954 edges, zero pending changes. The two whole-project
refreshes failed during WAL/checkpoint activity with database locking; their
retained index is incomplete. No index deletion, unlock or tool upgrade was
used. Whole-project graph freshness and full release acceptance remain open.

Later watchdog follow-up (2026-10-17 16:14 JST): its state reports NORMAL, desktop up, backend up/healthy and embedding disabled. The production stop marker is absent. This is a watchdog status report, not independent model inference or embedding-service proof. No production restart command was issued. The separate protocol association restoration remains pending.

F06 / FX-A01 scoped CLI supplement: the existing queue implementation is
retained. A new behavioral integration test drives the real prompt_toolkit
Application through pipe keyboard input and the actual busy inline queue/q
commands. After add/list/edit/move/rm/clear, the actual process loop calls
HermesCLI.chat and AIAgent through the real OpenAI SDK to an owned HTTP/SSE
model peer. The real file-tool dispatcher and ShellFileOperations write C.json
then B2.json, once each, with the expected bytes. Removed/cleared inputs create
no files. The test checks actual SQLite user/assistant transcript order,
unchanged history during management, and the first system message across all
five requests. Synthetic credentials/model responses, pipe I/O, offline catalog
inventory and nonselected-tool availability are explicit fixture leaves.

The final native-Windows proof is 69 passes in four fresh per-file processes
(CLI runtime 1, existing CLI contracts 51, Gateway queue dispatch 12, Gateway
consumption 5), with zero failures/errors/skips. The ten additional Gateway
cases preserve queue/q literal payloads such as list, edit, move, rm and add;
they do not add CLI management verbs to Gateway. Gateway uses the existing
synthetic runner/adapter fixture. These counts are selected final runs and
must not be added to historical or repeated-run totals.

Two source-bound in-memory faults are killed by behavioral assertions: move
becomes a no-op, and the actual input consumer omits chat after the first turn.
Each binds once, loads the mutated owner, fails one test without collection
errors, and leaves source/test bytes unchanged. Final runtime test SHA-256 is
31f8725bd428c804151ce1a3b20c04227350427204a0050346b892e32ef60616.

The local Windows runner assigns the suspended child to a dedicated
KILL_ON_JOB_CLOSE Job before resume. All descendants inherit that ownership.
Normal runs and both killed faults finish with zero active Job processes and
no forced recovery. A separate qualification checks a normal exit and a
three-second timeout: child and grandchild report Job membership, six active
processes are observed before timeout recovery, and zero remain afterward.
The runner rejects timeout or residual-recovery runs even if pytest exits 0.
Independent review closed the timeout-descendant recovery P2; final test,
scope and runner reviews found no remaining P1/P2. Ruff and diff hygiene pass.
All proof, harness hashes and retained failed fixture attempts are referenced
by the JSON receipt's fxa01_cli_runtime_acceptance field.

Real CodeGraph 1.6.0 completed a new exact selected-owner graph: twelve files,
1,739 nodes, 5,096 edges, zero pending changes. It covers the selected CLI,
agent and file-tool owners/tests only. It is not runtime code or a fresh
whole-repository/Gateway graph. Same-CLI new/resume/profile transitions, actual
messaging channels and model quality remain unaccepted. The campaign remains
partial; Electron launches remain held for the separate protocol association
restore question, and actual-model eight-hour/physical sleep acceptance stays
NOT_RUN under the human instruction.
