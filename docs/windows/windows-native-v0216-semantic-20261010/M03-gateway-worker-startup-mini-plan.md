# M03 Gateway OAuth worker startup and Desktop cleanup

This bounded slice follows c69d65f234b00eca1894aa3613a6347ea5fde490 on codex/v0216-semantic-20261010. Frozen campaign identities remain D_BASE 606f7e557c13a0789a2420f7adf6181becf60d75, R_BEFORE 63279301bcbdc185c1b07b98a9312eb0c862f26d, R_AFTER d3630f853239e8c41ce7201e09fbdf39bcbc5431 and U_RELEASE 818c13be1dc4fd28987e1e881a9408224afd4535. The authorized endpoint is a reviewed isolated local commit. Publication, release, dependency changes and production restart are outside this slice.

## Behavior

A Windows OAuth worker can acquire a native thread before Thread.start returns or assigns ident. The previous Gateway startup error path could interpret ident absence as completion and omit the already-reserved session identity from its public failure response. The Desktop controller consequently could not cancel that owner on the original captured connection/profile.

The owner now settles locally only if no worker object was returned. An acquired object stays reserved until its actual finally proves completion. McpOAuthStartupError carries the reserved session ID and server name and preserves the original cause. The existing registered RPC returns error5024 and typed metadata for that failure; pre-reservation errors retain their prior behavior without fabricated identity. Metadata adds no credential or HOME field.

The shared Desktop controller accepts only the actual JsonRpcGatewayError with code5024, the expected kind/server and a nonempty safe session ID. It captures that ID and rethrows the same error. Existing finally cleanup cancels the native listener and backend owner through the original RPC scope. Failed start never opens a browser, awaits a callback or reports approval. Malformed/wrong-server/legacy errors retain their prior behavior.

## Qualification

The candidate's twelve canonical Python startup cases and nineteen Desktop unit cases pass, with eight preserved admission cases separately qualified. Their case counts overlap the affected regression denominator and must not be added to it as new unique coverage. Original behavioral RED is preserved separately from collection, observation and UI fixture failures.

Six Python mutations produce five intended AssertionErrors and one explicitly private-reservation KeyError; the latter is not public-poll coverage. Six Desktop mutations produce forty-five intended AssertionErrors, with 228 passing before/restored control case executions. Desktop unit coverage uses doubles and the real shared error class; snapshots are not import traces.

Two source-tree development Electron scenarios qualify constructor failure/recovery and an actual native worker held before ident, including public identity, original-scope cancellation, direct native joins, one actual token redemption, nonce effects and fresh cold-process allowed/foreign-denied checks. They use owned synthetic issuer/MCP peers, scripted model output and browser-open observation. Constructor evidence binds its exact historical spec; the later held-only navigation changes do not constitute a fresh constructor run. Packaged Desktop, external browser/provider/model and production health are unqualified.

The affected denominator is thirteen unchanged files and sixty-four fixed node IDs. Eighteen qualified executions are inherited through exact retained source/runtime/artifact equality; forty-six are freshly collected and canonically executed with zero file retries. All 192 setup/call/teardown reports pass and 55 required cleanup property instances are present. The old profile eight raw passes remain excluded; the fresh eight have actual proof of two exact synthetic credential producers. The old eighteen keep their original four-suffix classifier limitation. No single successful sixty-four-case run, collection test credit or production credential isolation is claimed.

Real CodeGraph navigation and bounded source/node records support call-chain review. They do not substitute for tests. Independent qualification binds 51 source inputs and two installed runtime source files. A finite 4,477-entry archive preserves raw original, candidate, mutation, restored, native and excluded evidence; every member independently matches its fixed path/SHA/size. It contains 93,953,185 uncompressed bytes and 32,797,748 compressed bytes. Task HOME/temp, whole databases, installed executables and package trees remain excluded; sixteen exact retained runner source snippets are explicitly pinned exceptions.

## Local delivery and remaining work

The code/test scope is ten files: Gateway owner and registered RPC, Desktop shared controller and unit tests, Gateway fake and admission tests, worker startup tests, native OAuth spec, and owned cold-process/bootstrap helpers. Only these and this plan/receipt belong to the product commit. Probe helpers, archives, runtime HOME and investigation outputs stay outside Git. Exact staged patch review, fresh primary audits and subsequent parent/tree/patch/twelve-blob verification remain required.

Protected primary HEAD and the original twenty-three status/file hashes are unchanged. Two opaque HTML files appeared as additional untracked work; their hashes are recorded in an additive baseline without changing or restoring them. Audits must preserve both the original twenty-three and the current additional two, and must not claim the primary status had no additions.

The separate Gateway callback listener's native acquisition and HTTPServer.shutdown-before-serve_forever behavior remains unchanged and requires its own reproduction and repair. In-place remint/revival, revoked-token/config replacement, plugin OAuth/module split, other M03 obligations and the full frozen campaign inventory remain open. Full M03 and campaign completion are false. The receipt is a reviewed precommit evidence snapshot; a later local identity record must supply the observed commit and postcommit audits. Recovery of this isolated change is a targeted Git revert after review, with the original working files and raw evidence retained. No reset, clean or primary-tree restoration is authorized.
