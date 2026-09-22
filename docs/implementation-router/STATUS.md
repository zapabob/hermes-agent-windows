# Implementation Router — work in progress

This branch is **not a working live-model router and is not ready to merge**.
It contains a tested, provider-neutral workflow controller and its failure-injection tests. No plugin is registered or enabled, and no model call, credential access, terminal execution or existing Switchyard/MoA configuration is introduced by importing it.

## Frozen revisions and related work

Downstream base: `15f60413bd5d5394aeb8e374c52c1010b8052224`.
Upstream comparison base: `71a2fe399bbd7a219c71f9d9fca2b313b01f2057`.

Upstream #103346 (`victor-kyriazakos`, head `d1f0ce43acd81211c7fbd6c4876d53308c5ce93e`) overlaps with the operator-owned provider/model/reasoning profile requirement. #87179 (`agafox`, head `f1908fd4656f0260b218f189ae59b3d6bba2368d`) is another open design. Neither is treated here as an accepted upstream interface or as superseded. No source from either proposal has been copied, and no co-authorship is claimed. Any later salvage must preserve the actual source authors and distinguish retained work from subsequent changes.

The separate contribution here is sequential plan/worker/verification/replan control, not another profile resolver or a replacement for NVIDIA Switchyard, MoA, provider fallback, or the native subagent scheduler.

## Component evidence

Local Python 3.13.5: initial 26-test RED, then GREEN. Review added three cases; two exposed premature success/cancellation handling and were corrected. Final local component suite: **29 passed**. Ten selected source mutations are all detected by behavioural failures. The duplicate-key mutation initially survived; an otherwise-valid duplicate-key case closes that test gap.

```sh
python -m unittest discover -s tests/implementation_router -v
python scripts/ci/implementation_router_sabotage.py
python scripts/ci/qualify_implementation_router.py --base-sha 15f60413bd5d5394aeb8e374c52c1010b8052224
```

The qualification command requires both commits to exist locally and creates disposable linked worktrees. Its success is component evidence only. Hosted CI results must be read at the exact candidate SHA; merely adding the workflow is not a passing result.

The initial local tests used newly authored component files because this execution container could not resolve github.com to fetch a complete checkout. The authenticated GitHub branch does start from the real frozen downstream commit. Synthetic local fixture, hosted native tests, full repository CI and live runtime evidence are distinct.

## Not yet implemented or verified

- A real Hermes `HostPort` adapter and gated plugin/CLI entrypoint.
- Stage-specific approved provider/model/reasoning selection and effective fallback provenance.
- Authorised shared-worktree binding across planner, worker and verifier.
- Actual host-owned terminal/check receipts and authoritative protected acceptance probes.
- Host-backed durable workflow state, workspace leases and unknown-admission recovery.
- Full repository, native Windows integration, live OAuth and existing-plugin coexistence acceptance.

At the inspected main revisions, the public subagent launch request supports `model` but not `provider`, `reasoning_effort` or `model_profile`; downstream explicitly rejects per-launch working-directory and timeout overrides. The implementation must not invent these arguments or modify private child objects to appear complete. The live adapter must use a reviewed host interface and preserve existing approval and process ownership.

`HostPort` is a trusted boundary. Python dataclasses are not a cryptographic defence against a malicious adapter or a same-user process that can rewrite the verifier. Production verification requires the host to isolate and protect its acceptance probes. Passing component tests does not establish that isolation.

## Merge and upstream publication gate

Do not create a ready-for-merge claim, merge this branch, or submit a competing upstream resolver on the strength of these tests. Complete live wiring and run all required checks at the final SHA first. The user's main branch and all existing routing integrations remain unchanged by this branch.
