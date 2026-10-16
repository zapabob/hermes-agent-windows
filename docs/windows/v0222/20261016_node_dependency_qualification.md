# Node dependency security qualification — 2026-10-16

The workspace updates concurrently to 10.0.6 and pins global-agent's roarr
dependency to 6.0.0. The WhatsApp bridge pins sharp 0.35.5 and music-metadata
11.16.0. The website updates its affected selector-parser dependency and
uses an explicitly maintained local braces implementation. Both npm and
pnpm workspace locks reflect the workspace dependency changes. Product
versions are unchanged.

## Maintained braces source

GHSA-vfj7-8cjw-p6xm / CVE-2026-93687 identifies stack exhaustion in braces
through 3.0.3. On the qualification date, the upstream advisory lists no
patched release. The website therefore carries a private source fork,
`@hermes-agent/braces-iterative@3.0.3-hermes.1`, based on upstream commit
`74b2db2938fad48a2ea54a9c8bf27a37a62c350d`. It is not an upstream release
and is not published to npm. Original MIT licensing and contributor credit
are retained. The adjacent vendor PROVENANCE.json records the verified npm
tarball integrity and original source hashes.

The change replaces depth-dependent recursive traversal in compile,
stringify, expand, append and flatten with explicit frames. Parser grammar,
public entry points, expansion ordering, AST mutations, escaping, range
limits and existing options remain intact. The parser, constants and public
entry module match upstream byte for byte. No reduced depth limit, disabled
watching, removed glob support or scanner exclusion is used.

Chokidar 3.6.0 and Micromatch 4.0.8 have scoped local-file overrides. A direct
website dependency provides the shared source location. The committed test
checks every lockfile consumer's actual require resolution and real path,
including link-target metadata. This is necessary: an initial broad file
override produced broken nested links while npm audit still reported zero.
That candidate was rejected. The final fresh installation resolves all
consumers to the maintained source and exercises their actual behavior.

## Local Windows evidence

The frozen upstream test suite passed all 764 tests against both upstream
and the modified implementation. An additional deterministic comparison of
27,000 ordinary input/API/option combinations matched upstream. The
committed regression suite passed all eight tests after a fresh isolated
`npm ci`: consumer resolution, glob enumeration, Micromatch expansion,
Chokidar detection of a new nested MDX file after readiness, normal API
semantics and four deep-input traversal cases.

The deep-input cases run separate Windows Node 24.19 processes with a
256 KB stack and 192 MB heap. Upstream parse, compile, expand and stringify
fail with stack exhaustion; the maintained implementation succeeds for
all four. The fixture stays below the existing input-length limit. This
controlled stack regression does not establish exploitability with the
default Windows Node stack, and does not claim arbitrary CPU or output-size
bounds beyond the original expansion contract.

An independent read-only review found no P1/P2 issue in the source change,
resolver wiring, committed regression or CI propagation. Its separate
probes reported 21,000 string comparisons, 35,000 reused-AST comparisons,
35,000 AST-state comparisons, 128 append comparisons, deep array traversal
and the four native cases on Node 26.10. These additional counts are reviewer
evidence; the parent's separate upstream and differential results are above.
No PR was read or contacted for this review.

Website type checking and production builds for English and the complete
English/zh-Hans locale set succeeded in a private copy. Skill pages,
automation metadata and llms.txt generation also succeeded. Existing broken
documentation-link warnings remain warnings under the unchanged website
configuration; these are not vulnerability findings. The committed Docs
Site Checks workflow runs the regression suite after dependency installation.
The complete build generated 436 HTML pages per locale. A local static
server and real headless Chromium loaded both quickstart pages, checked
document language and visible headings, followed sidebar links and reported
no page JavaScript errors. The browser blocked external requests; public
search/network integrations were not part of that smoke test.

The other dependency probes exercised actual concurrently child processes
and Japanese output, global-agent HTTP proxy/no-proxy/auth/logging with
roarr 6, checksummed local Electron-mirror download plus cache reuse, sharp
SVG resizing/JPEG encoding and invalid-image recovery, three WAV metadata
APIs, and selector-parser AST round trips. HTTP CONNECT and a public Electron
download were not claimed by those local mirror/proxy probes.

A fresh isolated workspace `npm ci --ignore-scripts` installed the updated
lock. All three Desktop TypeScript projects then passed. The first private
copy lacked the existing session-resume JSON fixture; copying that unchanged
tracked fixture resolved the input error without modifying product code or
tests. Renderer production build, Electron main/preload bundling and the
distribution contract check passed against the fresh dependencies. Previously
qualified unchanged node-pty/get-windows payloads were copied without cleanup
hooks; this does not claim a new native-module compilation or a newly
packaged live Desktop.

The updated pnpm lock passed an isolated manifest-only resolution and an
offline frozen-lock check for all eight workspace projects. A source-bound
CodeGraph 1.6 index of seven complete maintained JavaScript files contained
23 nodes and 26 edges. Impact traversal resolved compile and expand through
the public entry module, and append through expand. The graph used an exact
hash-bound copy outside the normally excluded vendor directory; it was not
a whole-repository dependency graph.

## Advisory result and operational boundary

Fresh npm lockfile audits reported zero findings at every severity for all
five tracked npm lockfiles: workspace root, website, WhatsApp bridge,
Photon sidecar and the local CodeGraph CLI. The pnpm audit also reported
zero at every severity. The maintained source fork has no upstream registry
advisory identity; zero audit output alone is not evidence that its code is
fixed. Source inspection, native regression, compatibility comparisons and
actual consumer resolution provide that evidence independently. No severity
threshold or advisory ignore was added.

The preceding MCP 2.2 Python lock audit reported zero findings separately.
Live installations, Go binaries, the pushed commit's complete CI status,
packaged Desktop and unattended restart durability remain separate gates.
This record does not assert an eight-hour soak, three real sleep/resume
cycles or complete U01–U18 qualification.

Qualification data remains in ignored private probe folders. Existing live
dependencies, output directories, user files and unrelated WIP were retained.
The shared Git hook has a pre-existing path/configuration failure; explicit
checks precede a process-scoped Lefthook bypass, not a claim that the hook
passed. To roll back dependency selection, restore the preceding committed
manifests and locks into a separate checkout and install into a fresh
directory, retaining this checkout and its artifacts for recovery.

Advisory: <https://github.com/advisories/GHSA-vfj7-8cjw-p6xm>.
