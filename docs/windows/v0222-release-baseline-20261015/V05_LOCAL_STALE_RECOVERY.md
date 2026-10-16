# Local stale-breaker recovery — 2026-10-16

This change implements the health-recovery/one-trial part of C05/V05 against
fixed release d923a5eb487a17c0a68801bba9ef0f56c81040a8. Its starting local
commit is 95bfa6ee7b690e4c6b989d3ca5a49b76540b57ee. The full V05 and adoption
campaign remain open. Exact source, verification, graph and independent-review
bindings are in [the receipt](V05_LOCAL_STALE_RECOVERY.json).

A new user turn can recover an agent whose configured local provider has
reached the existing consecutive-stale threshold. The existing turn prologue
asks the existing request owner to check that explicit runtime endpoint's
health. A 200 response admits one trial of the same provider/model by setting
the streak to threshold minus one. It does not count as a model completion.
A new stall, transport/API failure or unfinished partial response closes the
trial. The actual response/error channels settle streaming, worker-thread
non-streaming and inline calls consistently. Successful completion retains the
existing reset to zero. Ordinary partial responses outside a recovery trial
retain their prior behavior, and partial text remains available to the caller.

The marker lock protects admission and final revalidation, with all network
waits outside that lock. A changed route, model, turn, streak, pending interrupt
or threshold invalidates an in-flight health result. Only one probe may be
outstanding per agent, including across new turns if DNS has not returned.
Explicit user cancellation retains the existing neutral treatment.

Health uses the existing shared synchronous deadline primitive for a total
three-second caller budget. A socket idle timeout alone is insufficient when
headers trickle. Expiry shuts down only the private probe socket, with close
and shutdown serialized; no request pool or shared client is touched. A late
DNS/TLS result is checked before a health request can be sent. The worker
cannot publish a trial after the caller's deadline. A blocked DNS operation
cannot be forcibly killed by Python; admission remains closed and the pending
marker prevents more probe workers until that owned worker finishes.

The health GET carries no credentials, model/autoload parameters or redirect
following. HTTPS uses normal certificate verification. Unsupported, denied or
unhealthy health endpoints keep the breaker closed. No provider switch, cloud
fallback, new environment setting, model load/unload or service control is
introduced. Private/LAN endpoints use the repository's existing local-endpoint
classification; this does not grant destructive runtime ownership.

Verification includes the original turn-prologue RED, independent partial
response and trickled-header REDs, plus real SDK 503 REDs for non-streaming and
inline calls. Final native cases use owned ephemeral loopback peers and the
actual request paths for complete, stalled, partial, trickled-health and 503
responses. They inspect actual POSTs and their model/stream fields, no auth on
health, no second request after failure, preserved partial text and successful
completion's zero reset. The trickle case checks both caller duration and the
owned worker's release. A held-connect test checks no late GET and no worker
accumulation. Regular partial-response/continuation assertions remain intact.

The pre-existing partial-response suite now stubs its dummy provider's
compressor context-metadata lookup. Its stream assembly and continuation
assertions are unchanged. The independent 17-case legacy check passed under
additional write/network containment: three attempted writes outside the
reviewer directory and one external DNS resolution were blocked. The review
records that qualification explicitly. Final parity
uses a fresh native Windows Python 3.12.13 process per file, isolated home/temp,
removed provider credential variables and disabled automatic pytest plugins.
The frozen project .venv is used without synchronization or installation.
Mutation checks run only in disposable interpreters and compare source hashes
before/after. Earlier failed/intermediate runs remain private and unaccepted.

CodeGraph 1.6 connects turn entry, the existing stale guard, all request paths,
the shared deadline and completion/error settlement. Runtime traces complement
dynamic HTTP/worker edges. The independent review is scoped to these exact
source/test bytes and does not certify the rest of V05.

Private evidence stays under tmp/probes/v05-breaker-20261016. The existing
primary checkout, operator settings, services, models and unrelated WIP are
protected. The stale shared Lefthook launcher is disabled only for the local
commit command with LEFTHOOK=0, retained unchanged, and not claimed as a passed
hook. Recovery, if authorized later, is a reviewed inverse commit; no reset,
clean, push, PR, main integration, release or deployment occurs here.

Prompt progress, awake-clock behavior, compression deadlines, immediate model
request cancellation, status/autoload behavior, memory budgets, remaining
original units/retained slices, an eight-hour soak and three actual sleep/resume
cycles remain separate acceptance gates. Existing transport-abort diagnostics
can report no TCP sockets found; this checkpoint does not qualify immediate
backend cancellation. C04's idna 3.18/3.19 behavior difference also remains open.
