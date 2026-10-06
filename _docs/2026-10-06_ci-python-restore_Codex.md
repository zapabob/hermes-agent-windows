# Python CI contract restoration

## Request and fixed reference

Continue the authorized main publication and Windows runtime delivery while preserving existing functionality, UI behavior, conversation history, and profile credentials. The starting main is `3b233408bbdf65a1252a22667eb99b53a462f993`. Its GitHub CI run `37454580377`, Python job `112240796830`, failed with 132 test failures and nine files that could not collect tests. Five other required workflows succeeded on that commit; this does not qualify the delivery as all green.

## Restored behavior

Restore the existing multi-key atomic YAML writer, profile-scoped auxiliary URLs and Nous authentication-file lookup, provider retry notices, parent-owned inference dispatch, and completed model-route observations. Restore the auxiliary-call refusal before route or credential resolution when a parent-owned inference port is active. Reconnect native dashboard refresh to the existing refresh-token singleflight owner; its synchronous refresh executes in the Starlette thread pool and retains the established outage and rejected-token responses.

The conversation cache and tool catalog are not rebuilt. Electron remains the lifecycle owner of Desktop and its backend; Go continues to observe their health.

## Source preservation and collection fixes

Publish the existing stateless Hermes GPT OAuth/authentication source modules required by tests. These are source code, not live authentication stores. Publish the existing PQ2 codec, lattice, Hadamard, GGUF, and ablation utilities under `scripts/model_quantization/pq2`; update test imports accordingly. Original local source files remain preserved. Model weights and runtime quantization settings are not changed.

The Nimble performance benchmark remains explicitly opt-in through its existing `NIMBLE_BENCH=1` contract; optional accelerator imports now occur only for an enabled benchmark. Native refine evidence and thread-whitelist tests use owned temporary directories instead of a machine-specific artifact directory or fixed drive letter.

## Test transport and platform contracts

Updater scenario tests already script `subprocess.run`. A shared fixture connects that scripted transport to the bounded Git owner, including its recovery path. Dedicated Git policy, process lifetime, branch preservation, and runtime restart tests continue to use their existing real owners. Scenario fixtures supply actual SHA-shaped rollback anchors and branch identities. Native updater unit scenarios do not discover or restart host gateways.

Worktree tests replace hosted PR probes at the existing internal GH boundary. Git repository operations remain real and isolated. Ref deletion races retain their exact expected-OID assertions. Messaging Tier-1 secrets remain stripped even when passed with the internal force prefix.

POSIX cleanup can pass a directory file descriptor to `os.scandir`; ClamAV fault injectors now accept that descriptor and still inject faults only into the selected synthetic definition database. Pipe-read fault injection targets owned output-reader threads, preserving POSIX process-launch communication. The Windows debug-event adapter uses explicit LLP64 widths even on mocked POSIX hosts; its 176-byte ABI, assignment-before-resume, observation rights, and independent cleanup refusals remain enforced. The native fixture entry point remains Windows-only.

## Evidence and remaining gates

The Windows runtime additionally exposed different `st_ctime_ns` meanings between path stat and open-handle fstat. Use the explicit `st_birthtime_ns` creation-time field on supported Windows interpreters, with the previous ctime fallback for older interpreters; POSIX keeps ctime. Share the comparable five-field generation identity across target snapshots, ClamAV definitions, YARA inventory, and rule updates. Device, file ID, size, modification time, content digest, reparse refusal, protected snapshot ACLs, and write-denying retained handles remain checked. See the [Python stat documentation](https://docs.python.org/3.12/library/os.html#os.stat_result.st_birthtime_ns).

Local native results: 84 security/file-generation tests passed with four expected skips; 47 updater scenario tests and two HEAD-movement tests passed; 108 Windows debug fixture contracts, 13 refresh singleflight contracts, 22 thread-whitelist contracts, 11 parent-owned delegation contracts, and 58 process registry contracts passed. Earlier transport and parity checks remain recorded separately. Full worktree tests exceeded the native local 300-second budget; focused race/PR checks and the full cloud run remain the acceptance gates.

Spawn fingerprints were compared with source archive `265cb44c84e`, which reproduces the previous approved digests. Former CLI/Git/ClamAV raw launches now use the existing bounded owners. The changed existing memory cron arguments, public curl utility, bounded Desktop policy discovery, and isolated interpreter test probe were reviewed explicitly. OpenViking no longer copies a raw parent environment. Baseline scope removal and digest updates follow this source comparison; the scan itself remains intact.

Local test output, stopped test-process identities, pre-edit snapshots, and spawn-boundary source comparisons are retained in task-local artifacts. During diagnosis, an updater recovery path acted on the isolated checkout; the resulting stash was retained and applied to recover all changes, then that transport boundary was repaired. The canonical live main was not modified by the isolated tests.

Publish only reviewed source changes and this record. Keep runtime databases, authentication data, model weights, logs, generated releases, and task-local investigation artifacts outside Git. After publication, fast-forward canonical main, rebuild/restart the authorized runtime stack, and verify all required workflows reach terminal success on the same pushed commit. Pending runs, earlier successful commits, process existence, and conditional E2E skips are not completion evidence.

## Native CI follow-up

Run `37464368563` on `19d64281f5c796a283362784a5dc40ad9f468137` exposed a race in the browser warmup spawn test: its process-wide Popen replacement also captured an import-time Git prefetch. Replace only the browser module's subprocess and executable-discovery references, retaining all original helper constants and the exact npx executable and hidden-window assertions. Assert that the shared Popen reference is unchanged. All ten native hidden-window tests pass with this isolation. No production browser behavior changes.
