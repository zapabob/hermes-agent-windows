# Node dependency audit remediation — 2026-11-02

Owner: Codex. Authorized scope: remove remaining Node audit findings without losing functionality, restore all main CI, commit and push main. Baseline: 31d7333864a0f23a7fd68cec12f9d1bf493a2a30.

## Findings and boundary

Fresh npm audits included development and optional dependencies at severity low. Root had 36 findings (32 moderate, four high); website had 21 (19 moderate, two high). WhatsApp bridge and Photon sidecar had zero. The reported previous count of 34 had changed. These are dependency paths, not 57 independent advisories.

The owning advisories are GHSA-g3hv-75wg-m249 (minimatch), GHSA-3g3m-2fjr-6pw4 (glob), GHSA-mrwp-f3q8-3g9p (follow-redirects), and GHSA-4528-x5fx-h6hg (Joi). Primary sources: https://github.com/advisories/GHSA-g3hv-75wg-m249, https://github.com/advisories/GHSA-3g3m-2fjr-6pw4, https://github.com/advisories/GHSA-mrwp-f3q8-3g9p, https://github.com/advisories/GHSA-4528-x5fx-h6hg.

Preserved boundaries: maintained nonrecursive pattern matching, legacy callable minimatch consumers, glob 7 traversal/ignore/nonull contracts, modern glob traversal/cancellation, Electron ASAR unpack/extract, static website rewrites/headers, Joi validation and redirect credential isolation. No severity threshold, audit target, script approval, or agent tool was removed.

## Changes

Pin minimatch engine 11.0.3, glob >=9 consumers to 14.0.3, follow-redirects 1.16.2, root Joi 18.3.1 and website Joi 17.13.9. Retain safe glob 7 for its callback API. A small reviewed CJS/ESM facade delegates matching to the real maintained engine; it adapts callable exports and glob 7 parser segments without restoring regex matching. Legacy Windows ignore rules and unmatched brace alternatives retain their previous behavior. Modern named ESM exports remain upstream exports.

The facade source lives in website/vendor/minimatch-compat and is packed using npm pack into website/vendor/hermes-agent-minimatch-compat-1.0.0.tgz. Relative tarball dependencies plus the direct dependency override work in root and standalone website installs. npm directory overrides instead produced invalid nested relative links. The committed archive has SHA-256 a1c829bac733a04ecffc08fac07c54460b104f960a6e15c983a38e62a7869eef. A regression test extracts it and compares every packed file to reviewed source. Regenerate the archive after any source change; update both package-manager locks.

Keep existing release quarantine and lifecycle-script controls. Add only package-specific exceptions for reviewed, exactly pinned security fixes and their matcher closure. npm resolutions were rebuilt in a separate directory using the previous lock, invalidating only stale minimatch/link entries before npm regenerated them. pnpm regenerated its own lock; no dependency record was manually fabricated.

Main CI also exposed existing browser-Desktop regressions. Speech uses a route-specific one-use ticket when that capability exists; native fallback behavior remains. Browser plugin sockets use their existing polling fallback instead of putting private session credentials in a URL. Late pop-outs dismiss the notification under its actual ID. Local file previews share the existing drive-letter decoder and reject remote-host file URLs; POSIX double-slash metadata behavior remains. Test expectations retain the established network-share prohibition and source ownership.

Python guard failures came from reviewed existing source drift. Keep all audited and raw-environment checks and refresh only five exact implicit-spawn fingerprints after inspecting the owning source. Document the two source-build lookups against the explicit managed PATH, with a behavioral test proving ambient PATH cannot win. GNU sort's execution probe now forces a real spill with one worker and sufficient input; the production approval detector remains unchanged.

## Verification and evidence

Both root and website clean npm installs completed. The isolated frozen pnpm install completed. All four fresh npm audits report zero at low severity, including development and optional graphs. The initial focused npm/pnpm suites passed 19 tests; an additional archive-source integrity test was then added. Website behavior suite passed 11 tests. Desktop failure-focused suite passed 38 tests; Desktop typecheck and lint passed (existing warnings remain).

Full workspace checks, final Python guards, packaging/build verification and remote CI are recorded by their actual logs and GitHub runs as they complete. Passing focused checks alone is not a claim that all CI is green. Audit evidence and focused logs are retained through Codex Security under artifacts/node-audit-20261102 in the repository's standalone evidence directory.

Independent read-only investigation and one fresh candidate review were performed. Both confirmed review findings (Windows backslash ignore and nonull brace alternatives) were reproduced, fixed at the shared constructor/parser boundary and added to regression coverage.

Self-review-event: qa_defect; response: review-only. Fresh clean installs, actual dependency consumers, both package managers and archive-source identity belong in the acceptance evidence. No governance, skills or automation instructions were rewritten.

Unrelated _p6.py is preserved and excluded from this commit. Running Hermes services were not stopped for dependency installation.

## CI archive boundary follow-up

The unconditional profile archive guard initially rejected the public npm source tarball by suffix. Its exception is restricted to the one reviewed repository-relative path, exact 1,942-byte size and SHA-256 above. Symlinks, directories, changed bytes and identical archives at another path remain rejected. Reads are bounded to the expected size plus one byte. Behavioral tests cover these cases and retain the original profile-secret non-disclosure controls. Source changes require archive regeneration, lock updates, source identity verification and a reviewed update of the boundary digest.

Additional security regression coverage exercises preprocessing amplification limits at optimization level two through upstream and compatibility entry points, plus cancellation during actual filesystem reads. The direct advisory boundary is checked in addition to audit metadata.

Local final focused verification passed 22 tests plus tests-js typecheck and lint. The archive boundary suite passed seven tests on Windows; the symlink creation test is Unix-only and remains active in Linux CI. Root path-scurry is explicitly pinned at 3.0.0, matching the reviewed installed graph; unused website glob/path-scurry release-age exceptions were removed.

The initial full local workspace run was not counted as passing: native fixtures encountered runtime selection, nested npm lookup and timeout failures. Repeated long local guard/native runs were stopped rather than used as evidence. Clean GitHub Windows Tier-1 validation on a47aaac645c passed all eight jobs, including native Desktop, Python, Go and all four Node audits. The main JS workflow passed ten of eleven workspace checks; its one failure was the new HTTP cleanup callback type, now corrected and locally typechecked. The remaining profile-artifact CI failure is addressed by the bounded, digest-checked source-archive exception above. The final commit must be checked by remote CI before closeout.

## Nix local-package integration

The Nix check exposed importNpmLock resolving a relative file: tarball as a literal source path containing the scheme. Supply the one reviewed local package through packageSourceOverrides, the upstream-supported interface, so npm receives its real Nix store path while retaining lockfile integrity. Other dependency fetching and source-filter behavior remain unchanged. Owning implementation inspected at NixOS/nixpkgs 0954f7ee2f6bb3dc7d4e3d0d8bcb8fd4bde4cfc5, pkgs/build-support/node/import-npm-lock/default.nix. The required nix flake check provides end-to-end verification on Linux; no local Nix runtime is available on this Windows host.

## Prepared workspace and Docker inputs

The local archive must also exist before dependency installation in filtered build contexts. Docker now copies only the reviewed archive in the dependency-cache layer; its ignore rules retain exclusion of documentation, secrets and every other archive. Validation with Docker's official moby/patternmatcher v0.6.0 passed 13 allow/deny cases. The local Docker daemon is unavailable, so a full local image build was not claimed; the fork's Docker publication job was already gated to upstream only and was not weakened or enabled for publishing.

The existing frontend-common input table now supplies the same local source to product freshness and dependency-install receipts. The private Webapp mirror therefore copies it before npm ci, and archive-byte changes invalidate TUI, dashboard, Desktop and Webapp receipts. A behavioral filesystem test checks mirror identity and all four invalidations. The focused Node suite now has 23 passing tests, with typechecking.

Nix validation passed on 03e19dd2bb4 after the supported packageSourceOverrides fix. A separate clean npm installation reproduced the store-style absolute package reference successfully without a relative archive in the build root. Windows Tier-1 also passed on that commit. Final CI is required again after the prepared-workspace/Docker source-input follow-up.

## Full Python CI follow-up

The complete 69019ad13b3 Python lane ran 3,901 files: 46,501 tests passed, three failed and 737 skipped. Remaining failures were the GNU sort probe and two CLI steering cases. Ubuntu 26.04 supplies a uutils default sort; GNU's leading-dash argument contract is now tested against the installed gnusort (or Homebrew gsort), with stderr retained if the execution marker is absent. The approval detector remains unchanged. Ubuntu's package file list confirms /usr/bin/gnusort: https://packages.ubuntu.com/resolute/amd64/gnu-coreutils/filelist.

The steering peer treated a closed connection from a real 0.5-second progress GET as a model failure and aborted the first scenario. The following cancellation case failed during snapshot bootstrap with exit 130. Record closed GET probes separately while keeping every model POST, tool effect, ordering and SQLite assertion strict. The unchanged five-case file passed in an isolated local Windows process before this fixture correction (75.1 seconds); the corrected file and complete Linux lane must be verified again. No test case or audit threshold is removed.

Final local follow-up: all five corrected steering cases passed (43.4 seconds). The execution-boundary file passed 78 tests with seven unavailable-platform/tool cases skipped (15.5 seconds), including the actual GNU sort marker. Use resolved executable paths to avoid Windows CreateProcess selecting the system sort ahead of PATH. The sort case forces an intermediate compressed file by merging three sorted inputs with batch-size two. Ruff, Windows footgun scan and whitespace checks passed. Full final-SHA Linux CI remains required.
