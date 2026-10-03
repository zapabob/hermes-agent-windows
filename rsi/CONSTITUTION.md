# RSI Constitution — Level 1 (bounded, human-gated)

**Status:** normative. These six clauses are not design suggestions; they are the
invariants that make a self-improvement loop auditable rather than self-reinforcing.
They are checked mechanically by `rsi/constitution.py` (see Verification).

**Scope:** Level 1 trains exactly one adapter (`hakua-epistemic`). Generation
N -> N+1 is an *auditable self-improvement pipeline*. The word **recursive** is
withheld until N+1 -> N+2 completes through the same mechanism with real data.

---

## Clause 1 — Candidate may not modify the Evaluator

The candidate (proposer / trainer side) has no write path to the evaluation
harness, its criteria, or its thresholds. Changing how you are measured is not
an improvement; it is a different, unmeasured system.

Enforcement: the evaluator's files are hashed at evaluation time and recorded in
`lineage.json`. A generation whose eval harness hash differs from its parent's
is rejected regardless of score.

## Clause 2 — Candidate may not modify the acceptance criteria

Acceptance thresholds are fixed outside the candidate's reach, for the same
reason, and additionally because a self-set threshold is trivially satisfiable.

Enforcement: thresholds live in `rsi/acceptance.yaml`, hashed into lineage, and
compared across generations.

## Clause 3 — Evaluation holdout never flows into training

The holdout set is write-protected from the dataset compiler. Selection
pressure toward the holdout is the standard way a self-improving loop reports
gains it has not earned.

Enforcement: every training example carries a provenance chain back to a
memory id. Any example whose chain reaches a holdout item is rejected at
compile time, not filtered afterwards.

## Clause 4 — Every training example is traceable to its origin memory

```
experience_id -> memory_id / revision_id -> consolidation_candidate_id
              -> training_example_id -> dataset_hash -> adapter_sha
              -> evaluation_run_id -> acceptance_decision -> generation_id
```

An example that cannot be traced to a specific memory revision is not trained
on. This is what makes "why does generation 7 behave this way" answerable.

Enforcement: `provenance` is a required field, not optional metadata.

## Clause 5 — No automatic adoption on regression in any dimension

Acceptance is a **vector**, never a single mean score. A child that improves
epistemic consistency while regressing coding ability is rejected, because the
regression is invisible to an average.

| dimension | direction |
|---|---|
| epistemic consistency | higher is better |
| revision correctness | higher is better |
| provenance preservation | higher is better |
| permission-boundary adherence | higher is better |
| unsupported-assertion rate | lower is better |
| coding regression | lower is better |
| tool-use regression | lower is better |
| latency / token cost | lower is better |

Enforcement: any dimension outside its tolerance blocks adoption regardless of
the others.

## Clause 6 — Rollback per adapter; no immediate merge into base weights

An adapter is activated as a layer and can be removed in one step. Merging into
the base weights is irreversible and destroys the comparison surface, so it is
forbidden while generations are still moving.

Enforcement: base model weights are read-only to the RSI pipeline.

---

## What Level 1 does not claim

- It does not claim the loop is recursive. Recursion requires N+1 -> N+2 to
  complete through this same mechanism with real data.
- It does not claim `corroborated` provenance is proof. Accepted run-membership
  evidence is a **threat-model threshold**, not a proof level; writer identity
  is not established.
- It does not claim the agent "got smarter". It claims: a specific set of
  memorized correction trajectories, passed an evaluation fixed in advance,
  improved specific measured behaviours without regressing others.

## Relationship to the environment-epoch work

```
memory continuity:      state      -> revision            -> provenance
environment continuity: process    -> artifact progression -> epoch boundary
RSI continuity:         generation -> dataset -> adapter   -> eval -> activation
```

None claims continuity from a snapshot resembling a previous snapshot. All
claim it from a **traceable transition history**.

## Verification

`python rsi/constitution.py --check` verifies each clause is representable, by
inspecting the pipeline's own write permissions rather than trusting prose.
