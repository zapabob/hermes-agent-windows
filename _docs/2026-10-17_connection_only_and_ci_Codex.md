# Preserve outbound messaging while assigning one receiver

The user requires one default owner for shared Telegram/Discord receivers,
preserved work and invocation routes in other profiles, retained unused Buzz
settings/files with its connection disabled, first-attempt CI, main publication
and actual runtime responses. The user also requests removal of this chat's
newly-created worktrees after integration. Protected pre-existing SOURCE WIP
and unrelated worktrees remain outside that cleanup scope.

## Connection versus delivery

The earlier local plan used platform.enabled=false to suppress duplicate
receivers. Tracing the existing send_message and cron dispatch showed that this
also suppresses outbound delivery. That plan is superseded: retain each
platform's original outbound permission, and set the existing platform extra
configuration connection_enabled=false only on non-owner receivers.

PlatformConfig.connection_enabled derives its value through the existing bool
normalizer. Its default is true and extra round-tripping is unchanged. Startup,
primary and secondary reconnect, secondary listener validation, adapter creation,
the receiving open-policy gate and relay idle eligibility respect the new
connection gate. The dashboard's secondary listener guard uses the same rule.
The existing get_connected_platforms capability list, send_message, delivery
router, cron targets, standalone senders and credentials remain unchanged.
No core tool, environment variable, dependency or version change is introduced.

Tests use synthetic profiles and local send boundaries. They prove receiver
construction is skipped; queued primary and secondary retries cannot connect;
Telegram/Discord/LINE standalone send branches remain reachable; enabled=false
still denies sends; cron targets and standalone delivery remain available;
secondary outbound-only LINE remains editable; relay idle eligibility and
open-policy protection remain correct. The initial source fails the receiving
adapter construction test. The final ownership file passes23 tests without
retry. Config62, sender49 and startup9 pass; primary reconnect32, secondary23,
scale watcher24 and dashboard8 also pass. Initial test-authoring failures are
retained in the local evidence, including required fake fixture constructor
arguments and pre-existing Windows read_text calls lacking explicit UTF-8.

## Full-CI races

Initial final-SHA CI1c1dc9c7ba6 passed the Windows Tier-1, distribution, runtime
authority, Docker and Nix workflows. The full Python job found one persistent
Relay cleanup failure and one OAuth startup file that passed only on a retry.
Those results are not called all-green and the unchanged workflow is not rerun.

The Relay test began its0.1-second timeout before its real child turn started,
then could reset shared runtime state while that child was still initializing.
Gate on actual turn entry, retain the timeout, release the actual child in
finally and await its Future before resetting. Use existing psutil PID probes
and reap owned test children on Windows instead of os.kill(pid,0).
The final file16 and related daemon/delegation/lease/Relay files16 pass:32 total.
Production delegation and Relay code are unchanged.

OAuth startup and retention held cleanup only after the entire real MCP probe,
which includes1+2+4 seconds of jittered reconnect backoff. This races their
unchanged8-second observation deadline. Hold the actual callback's expected
failure before retry unwinding, release it explicitly and preserve the real
SDK, REST, native worker, retries, ownership, token and sentinel assertions.
Added retry-hold cases prove observation precedes retry and release resumes it.
Source-bound REDs retain the old barrier. Final first-attempt sequence passes
startup5, retention4 and REST SDK4,13 total, with cleanup and thread exit proof.
Production OAuth/MCP code is unchanged.

The full Python CI runner now explicitly uses --file-retries0. The Windows
isolated lane additionally includes all affected startup, reconnect, profile,
OAuth and Relay files with retries0. A new commit and fresh exact-SHA CI are
required; retrying the failed run is not an acceptance path.

## Local operations and remaining closeout

Initial source1c1dc9 was restarted successfully: all four gateways report that
SHA, all current platform rows have current process ownership, no retrying/fatal
rows remain, Desktop is visible/responsive and owns its actual backend. Eight
HTTP probes pass; two real chats complete within45 seconds; structured tool
output and1024 finite nonzero embedding dimensions pass. One synthetic-home
real Hermes turn returns the expected marker. These are baseline runtime
evidence, not proof of the additional connection-only configuration.

The revised local plan retains parallel voice/display/browser settings detected
by hash guards, restores demonstrated original send permission and applies
eight connection-only flags. Original explicit false permission stays false;
previous credential-enabled absent leaves become explicit true. Buzz remains
explicitly disabled. Private exact backups and original byte copies are outside
Git. Actual Windows ACL, bytes, restore read/journal faults and a separate
process writer are qualified using the existing native lock and OAuth fence.
No external message is sent by the verification harness.

Real CodeGraph source slices are SHA-bound. Oversized gateway and web-server
owners retain full sources plus exact AST span/line/hash maps for indexed
owners. This is scoped navigation and independent review, not a whole-repo audit.

After final source review, explicit-path commits and regenerated carry metrics,
push main, require all required workflows on the same SHA to finish success on
attempt1, apply only the reviewed local flags after drain, and repeat actual
runtime responses. Preserve ignored task logs/builds by same-volume rename,
then use managed worktree archive for this chat's completed integration checkout.
Do not delete or reset the protected pre-existing SOURCE worktree.
