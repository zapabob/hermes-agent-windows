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
