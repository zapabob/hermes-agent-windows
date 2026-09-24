# T08 resource-admission re-review

**Reviewed fix commit:** `3dfa896847760763cfa79af04f360f433c2a2198`  
**Prior reviewed base:** `1e1b9515f6ee8feedf3a6b754cc5cce22110709e`  
**Method:** read-only source/diff review; no tests, CodeGraph operations, or edits
outside this review artifact were performed.

## Result

- `codeQualityStatus`: **WATCH**
- `recommendation`: **APPROVE for integration as an inactive WIP seam only**
- `reportPath`: `.omo/evidence/T08-code-review-rereview.md`

The former HIGH finding is resolved. The probe now streams stdout in bounded
chunks, reads no more than 16 KiB plus one overflow byte, terminates and reaps
the child on overflow or timeout, discards stderr, and returns only a fixed
error code. The new regression suite includes a real endlessly-writing Python
child and checks that it has exited before the test returns.

## Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

1. **The resource-admission API remains inactive and lacks its host lifecycle
   integration contract.**
   [resources.py](../../downstream/delegation/resources.py:544)
   defines the reservation/reconciliation lifecycle, but repository search still
   finds no production construction or call of `ResourceReservationBook` or
   `ResourceSnapshotCollector`. A real owner has not yet supplied the trusted
   local PID source or the fresh per-reservation measurements required by
   [ResourceReflection](../../downstream/delegation/resources.py:297).
   This is not a reason to reject the current intentionally inactive WIP, but it
   is a hard gate on activating admission: T10 must bind reserve, start,
   reconcile, release, cancellation, and crash recovery to one host lifecycle
   owner. It must not infer child residency from model labels or process names.

### LOW

None.

## Former HIGH: output handling verification

The previous `capture_output=True` buffer-before-check pattern is gone. The
new implementation at [gpu.py](../../downstream/platform/windows/gpu.py:121)
uses `Popen` with stdout only and stderr directed to `DEVNULL`. Its bounded
reader at [lines 152-162](../../downstream/platform/windows/gpu.py:152)
requests no more than the remaining capacity plus one byte. The polling loop
observes overflow and timeout, calls the terminate/kill-and-wait helper, and
returns sanitized errors at [lines 177-213](../../downstream/platform/windows/gpu.py:177).

The test at [test_resource_admission.py](../../tests/downstream/test_resource_admission.py:829)
starts an actual continuously flooding Python process through the same
`process_factory` boundary. It asserts `gpu_probe_output_invalid`, completed
child termination, and absence of the synthetic private payload from the
result. The timeout case at [line 858](../../tests/downstream/test_resource_admission.py:858)
checks termination plus the sanitized timeout result. The existing ordinary
probe test continues to assert a minimal child environment containing only
`PATH`, `SystemRoot`, and `WINDIR` at [lines 778-785](../../tests/downstream/test_resource_admission.py:778).

## Scope and skill-perspective check

`remove-ai-slops` and `programming` were unavailable at their stated local
paths and absent from the available local skill roots, so their review criteria
were applied directly. This fix is narrowly connected to the former bounded
output defect: the small process protocol, reader, stop helper, and real-flood
test are necessary to establish a streaming cap. It does not introduce prompt
tests, deletion-only tests, tautological tests, test-only production parsing,
or an untyped escape hatch. The broader inactive resource API remains the
MEDIUM lifecycle/scope risk recorded above.

## Evidence and limitation

`git diff --check` for the reviewed fix was clean. This reviewer did not run
tests. The real-flood regression is platform-neutral subprocess evidence, not a
Windows NVIDIA-driver execution; its assertion proves the pipe cap and child
reap behavior without requiring a real GPU. No real host PID source, resource
reflection producer, or delegation lifecycle has been validated.
