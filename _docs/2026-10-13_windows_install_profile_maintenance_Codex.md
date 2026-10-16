# Windows long paths and profile wrapper maintenance

Frozen upstream main: `63d0b94120027d487c9a5235b9ec64b696af1b26`. ADAPT contracts from `3b63f7b0a4c7beb9eadbce2f15b9da75d01f5065` (installer long paths), `6fa79e9b968ecedc90a59d0a764a335d49634d42` (orphan alias removal), and `6090407840a4931d93cd700c467d92946214e604` (Windows profile wrapper cleanup). Local parent/recovery reference: `3940f727a842fa0f144308f7c41e8aaad1473419`.

## Behavior adapted

The existing PowerShell installer persists repository-local `core.longpaths=true` before updating a checkout, supplies it to both fresh-clone paths, and sets it when initializing the ZIP fallback repository. The existing CLI implementation now permits removal of a validated alias whose profile is already absent; alias creation still requires the profile. Profile deletion locates the Windows `.bat` wrapper for its confirmation summary and subsequent guarded removal. Alias validation, deletion confirmation and the existing wrapper-content ownership check remain in place. No upstream module rearrangement or new dependency is introduced.

## Evidence

Real Windows Git operations against a temporary local origin reproduced fresh-clone and existing-update failures involving a deeply nested file. The initial existing-checkout fixture incorrectly entered the clone branch and was excluded; a corrected fixture reached fetch followed by a failing checkout before the product change. Profile regressions reproduced the missing `.bat` cleanup and orphan-alias behavior before the fix.

Final acceptance is 66 passed, zero failed and three skipped: three unchanged long-path cases from the first GREEN plus 63 passes from the two-file recheck. Two test-only issues in the first GREEN were corrected: the existing clone-argv regex was updated for the required option while retaining relaxed-ErrorAction checks, and foreign-wrapper preservation was checked as exact bytes rather than normalized text. Product code did not change after the accepted long-path run.

The harness extracts the unmodified installer function, redirects its SSH/HTTPS clone URLs to a test-owned local bare repository, and makes downloads fail closed. The actual installer, live profiles, global/system Git settings and registry were not changed. ZIP fallback is covered by source/order assertions, not executed end to end. The three skips are a POSIX-only shell wrapper test and two symlink-capability-gated export/metadata tests, separate from the changed alias/delete branches. The exact Windows symlink-probe exception was not captured; symlinked-wrapper acceptance is not claimed.

Tests used ROOT's native Windows Python and the existing process-per-file runner with `--jobs 1 --file-retries 0 --file-timeout 300 -q`, fresh H-drive HOME/HERMES_HOME/temp/basetemp, UTC/UTF-8 and an allowlisted environment without provider credentials. One final CodeGraph sync recorded 9,180 files, 198,435 nodes and 625,963 edges, extraction version 25 current with zero pending changes/references. Python owners and tests are indexed; PowerShell is unsupported by the index, so its responsibility mapping is explicitly supported by source and the indexed tests.

Independent Luna MAX review verified all six frozen source/test hashes and returned specification and quality PASS for these three contracts, with the limits above. The full frozen-tree ledger remains only partially adjudicated; these results do not establish whole-file or whole-release parity.

## Records and recovery

Evidence directory: `H:/Codex-v0216-archive/`. Exact commands, source pins and RED/GREEN log hashes are indexed in `V0217_WINDOWS_MAINT_CLOSEOUT_20261013.md` (SHA256 `58DE99EE68C51DBE0C3EE9C581000781CB370098563119B9DC9CFEAED6DA9226`). Independent review is `V0217_WINDOWS_MAINT_INDEPENDENT_REVIEW_20261013.md` (SHA256 `4F6D8E97ABB4545F4211569084FC10CD73DB1A8550197D6A379BBA4188C73156`). The disposition ledger links these focused contracts to frozen blobs and earlier local commits. Parent guards and the local commit receipt verify protected-state equality and exact staged/committed blobs. Raw logs, databases, credentials and unrelated materials are excluded from this commit.

Recover through a targeted revert on the isolated branch after checking later dependencies, using the parent above as prior source. Do not reset PRIMARY or discard unrelated work. Manual provider confirmation, remaining frozen-delta adoption, local resource/memory and Windows execution acceptance, actual packaged UI testing and consistent version 0.21.7 remain separate open requirements.
