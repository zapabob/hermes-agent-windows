# OAuth startup oracle and cryptography metadata alignment

## Requirements and scope

Repair the remaining OAuth startup flake and cryptography dependency-check
inconsistency while retaining features, protected files and unrelated WIP.
Publish the reviewed change to main, verify applicable CI on the final SHA,
then restart the canonical Hermes fleet and prove actual responses.
The product version remains 0.21.5. No PR handling or automation is involved.

Baseline: 9287227f9dc95be525ff5ffc864f1b1a7c7988bd. Work was isolated in
the existing v0222-main-integration-20261016 checkout. Primary operator files
and the nine protected SOURCE WIP paths were hashed before implementation.
No reset, clean, stash, file deletion, or shared-venv sync is authorized.

## Cause and implementation

The after_sdk_start ownership test waits eight seconds for the real SDK probe
to finish retrying. Production retry delays are 1, 2 and 4 seconds with +/-20%
jitter: the maximum is 8.4 seconds before network/scheduling overhead. Fixing
jitter at its upper boundary reproduces the original failure. The test now
patches only tools.mcp_tool._jittered inside that failure experiment to return
zero and records all three requested delays. Actual SDK, transports, retry
loop, asyncio.sleep, public RPC, ownership, cleanup and legitimate recovery
remain exercised. The scoped patch is removed before legitimate recovery.
Production OAuth/retry code is unchanged; no waiting bound was increased.

The declared dependency and checked-in lock were cryptography 50.0.0 while
the canonical runtime already contained 50.0.2. The uv override was a range,
which replaces even the project's exact requirement during resolution.
Pin both the direct requirement and required Alibaba compatibility override
to 50.0.2 and regenerate uv.lock. Only cryptography distributions and Hermes
requirement/override metadata change. Keep the patched floor and existing
WeCom/Weixin cryptographic APIs. A regression checks declared exact pin,
override and resolved version together without hardcoding a release number.

Windows Tier-1 now runs both affected regression files in its existing native
Python contract step. The YAML remains one folded command; existing tests
and other gates are retained.

## Verification evidence

Evidence directory: H:/HermesQualification-oauth-deps-20261017.

* oauth-red.log: original real-SDK test fails at cleanup_entered.wait(8) with
  maximum production jitter (one failure, 17.81 seconds).
* oauth-green.log: identical boundary harness passes (12.84 seconds).
* dep-red.log: the regression rejects the former range override.
* native-regression.log: canonical per-file subprocess runner, eleven files,
  172 passed, zero failed, three platform skips, retries disabled, 87.2 seconds.
  Includes real SDK startup/listener/admission, manager/retirement, process
  writer locking, production reconnect controls and WeCom/Weixin adapters.
* focused.log: 109 passed, three skipped in the initial combined smoke run.
* metadata-build.log: setuptools 83.0.0 builds editable Requires-Dist as
  cryptography==50.0.2 without installing into the shared test environment.
* uv lock --check --offline and targeted Ruff checks pass.
* Parsed lock comparison limits package changes to cryptography and the
  project's own metadata; parsed Windows YAML is a single command.
* Real CodeGraph indexed the hash-bound owner slice before/after changes;
  nine Python files, initial 829 nodes/2167 edges, no pending changes.
* Independent read-only reviewer 01a14631-85b9-7233-a4d3-ec7dd5f1269d approves
  the OAuth/dependency change with no required findings. CI path addition
  receives a separate supplemental review.

Fresh-process repeated boundary runs, installed-runtime dependency check,
exact final-SHA cloud CI and final runtime receipts are collected separately
in that evidence directory during publication/deployment. These are separate
gates; this source log does not claim their success before they execute.

## Operational safety and rollback

The candidate .venv is a junction to the protected SOURCE runtime. Do not run
uv sync or editable installation there. Invoke the existing interpreter with
bytecode disabled for verification; this is the documented Windows shared
environment exception to the UV-first SOP. uv lock does not sync an environment.
Refresh only the canonical editable installation metadata, with a prior backup
and --no-deps, after main publication. Retain installed cryptography 50.0.2
and verify all other installed distributions are unchanged. Snapshot all
overwritten packaging metadata before changing it.

All Git mutations use process-local LEFTHOOK=0 because the existing hook's
fallback uv run previously replaced the shared environment. Manual checks
are still required. No hook configuration is changed. C: is almost full;
additional test/cache/evidence writes go to H:, without deleting operator data.

Reuse the existing packaged Desktop because frontend sources are unchanged.
Restart exact canonical Desktop/backend, Go watchdog and four gateway owners
with graceful draining and preserved in-memory environments. Reuse the
already verified generation/embedding model configuration and probe actual
responses; do not unnecessarily cold-load large models. External messaging
channel availability, reboot durability and long soak testing are separate
claims and are not implied by process health.

Rollback is a normal follow-up revert plus the retained editable metadata
backup; never downgrade cryptography merely to satisfy stale metadata.

## Standards and sources

Applied PC-wide common engineering, implementation start, skill selection,
security, deep research, application development and Python SOPs; skills
milspec-codex-standard, gh-fix-ci, debug-failing-test, deepresearch-defense-standard
and code-review-and-quality. Formal MILSPEC certification is not claimed.
The active user request authorizes fixing, main publication and restart.

Verified official sources on 2026-10-17:
https://pypi.org/pypi/cryptography/50.0.2/json
https://cryptography.io/en/latest/changelog/ (50.0.2 wheel/OpenSSL update)
https://docs.astral.sh/uv/concepts/resolution/#dependency-overrides
The runtime's already-installed patch is retained; no newer major is adopted.
