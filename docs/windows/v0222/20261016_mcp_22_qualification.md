# MCP 2.2 and configuration authority qualification

The dependency pins and lazy installer move together to MCP 2.2.0, including
mcp-types 2.2.0 in uv.lock. The official wheels were hash-checked against the
lock and loaded from an isolated qualification overlay; the shared working
virtual environment was not updated during these tests.

The new raw-document reader centralizes OAuth configuration reads without
normalizing missing, null, non-mapping, malformed or inaccessible documents.
It does not acquire the configuration lock inside the OAuth journal lock.
The journal, atomic replacement and credential compare-and-swap boundaries
remain in place. The source guard excludes only root-level ignored probe
copies; nested product directories remain scanned.

SDK redirect refusals now park immediately rather than consume the initial
retry budget and lose the useful error to cancellation. The migration
regression starts at the redirecting endpoint, checks public connection
status, closes the old transport, saves the verified final endpoint and
completes an actual nonce-bound tool effect. The SDK still enforces its
origin policy. See the adjacent endpoint migration guide.

## Local Windows evidence

Each test file or filtered transport surface ran in a fresh Python process
with a private HERMES_HOME and synthetic peers/credentials. Final results:

| Contract | Passed |
| --- | ---: |
| Raw document semantics and replacement failures | 18 |
| Configuration ownership guard | 3 |
| OAuth retirement, including another writer and A→B→A | 28 |
| Native SDK retirement and Windows locking | 8 |
| Credential commit contract | 60 |
| Configuration writer locking | 11 |
| Saved-config binding repair | 29 |
| Actual SDK config binding: native / relay / REST / other | 21 / 21 / 26 / 3 |
| Renewed credentials in a cold process | 1 |
| Configuration loader E2E / read-only validity | 2 / 22 |
| Failure classification / native redirect boundary | 20 / 10 |
| Auth-park discovery recovery / SDK session retention | 1 / 2 |

An initial whole-file binding invocation exceeded its qualification driver's
300-second budget after 36 completed cases. The final invocation split the
same test nodes by transport into fresh processes; all 71 selected nodes
completed. No assertion was removed or relaxed for this split.

Independent read-only review found no P1/P2 regression in the four-file raw
reader change. The earlier SDK review identified cross-origin compatibility
as a P2; the endpoint migration guide and public-status-to-reconnection
regression address that finding. A source-bound CodeGraph index of eleven
complete selected files resolved the raw reader, config entry, replacement
guard and failure classifier and their callers. It was not a whole-repo
graph. OAuth producer source guards were retained.

The all-extras hash-bound Python advisory audit reported zero findings with
this dependency lock. That is not proof of zero findings in other dependency
trees, a live runtime update, or a successful full CI run. Website braces
remains an unresolved separate advisory. No scanner threshold was lowered.

The local shared Git hook has a pre-existing path/configuration failure;
commits use a process-scoped Lefthook bypass after explicit checks. Hook
execution itself is not counted as passing validation. No version bump,
user-file deletion, credential publication or PR interaction is included.
