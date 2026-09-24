# T08 resource-admission code review

**Reviewed commit:** `1e1b9515f6ee8feedf3a6b754cc5cce22110709e`  
**Scope:** `downstream/delegation/resources.py`, `downstream/platform/windows/gpu.py`,
and `tests/downstream/test_resource_admission.py`.  
**Method:** read-only diff and source review. No tests were run by this reviewer.

## Result

- `codeQualityStatus`: **WATCH**
- `recommendation`: **REQUEST_CHANGES**

The admission book is currently unwired: repository search found no production
construction or call of `ResourceSnapshotCollector` or `ResourceReservationBook`.
That keeps the implementation inactive, but means the test suite proves only the
new local model rather than an existing delegation path. Its stated fail-closed
rules for stale/missing snapshot data, unreconciled started reservations, and
unknown GPU residency are generally present and have focused contract tests.

## Findings

### CRITICAL

None.

### HIGH

1. **The claimed output bound is enforced only after the complete child output
   has been buffered.**
   [gpu.py](../../downstream/platform/windows/gpu.py:84)
   invokes `subprocess.run(..., capture_output=True)`, and the 16 KiB check is
   only made at [line 101](../../downstream/platform/windows/gpu.py:101).
   `capture_output=True` accumulates stdout in memory without a size limit, so a
   replaced or malfunctioning `nvidia-smi` can consume arbitrary parent memory
   before it is classified as `gpu_probe_output_invalid`. The two-second timeout
   does not cap data volume. This contradicts the module's bounded passive probe
   contract and can itself induce the workstation pressure the admission layer is
   intended to prevent.

   Required change: use a streaming/limited reader (or a separately enforced
   OS-level output cap) that terminates the probe once the bounded byte count is
   exceeded, while retaining the current sanitized error result. Add a test that
   exercises the cap at the reader/process boundary; returning an already-built
   oversized `CompletedProcess.stdout` is not sufficient.

### MEDIUM

1. **The inactive seam is much broader than its supported integration boundary.**
   [resources.py](../../downstream/delegation/resources.py:1)
   introduces 968 production lines and [test_resource_admission.py](../../tests/downstream/test_resource_admission.py:1)
   introduces 746 more, yet the commit's own CodeGraph evidence records that T08
   is unwired and depends on T06/T10 for composition. The new public API contains
   collection, per-resource reconciliation, pressure state, opaque reservation
   lifecycle, Windows commit inspection, and NVIDIA process residency probing;
   no host lifecycle owner supplies the required per-reservation reflection or
   local-process identity. This is substantial speculative production surface
   before a consumer contract exists. It will be difficult to know which parts
   are required when T10 supplies the real owner, and tests presently certify the
   private accounting design rather than end-to-end behavior.

   Required change: either reduce this commit to the small data/decision boundary
   that T10 will call, or record and implement the concrete owner-facing contract
   in the composition task before treating this API as reusable. Keep it inactive
   until the owner can supply authenticated process identity and measured
   per-reservation usage.

### LOW

1. **The test helper suppresses type checking for the public request contract.**
   [test_resource_admission.py](../../tests/downstream/test_resource_admission.py:73)
   passes a general `str` to the `Workload` field under `# type: ignore[arg-type]`.
   The currently used values are valid, so this does not demonstrate a defect,
   but it removes static protection from the helper that creates most admission
   inputs. Make the helper parameter `Literal["read", "inference", "embedding"]`
   or create deliberately invalid requests directly in the validation tests.

## Test and skill-perspective check

The `remove-ai-slops` and `programming` skill files were sought at their stated
local locations and by filename beneath the available local skill roots; neither
was available in this execution environment. I applied their requested review
criteria directly. The production code has no prompt-output tests, deletion-only
tests, tautological tests, or implementation-constant snapshot checks. The
focused tests cover real admission outcomes and concurrency, but they do not test
the actual output-buffer limit described above and the `type: ignore` escape hatch
at line 73 violates the programming perspective. The broad unused API is also a
remove-ai-slops concern: it parses and normalizes telemetry beyond a current
production boundary.

## Evidence and remaining risk

- `git diff --check` on the reviewed commit was clean.
- The checked-in CodeGraph evidence is a before-change record only; no after-change
  graph receipt is part of this commit.
- No runtime NVIDIA driver, real host-owned PID source, or real delegation
  lifecycle integration was exercised in this review.

## Blockers before approval

1. Enforce the NVIDIA probe's output bound while the child is running and add a
   boundary-level regression test.
2. Resolve the unsupported breadth of the inactive API through either reduction
   or an owner-integrated T10 contract before production use.
