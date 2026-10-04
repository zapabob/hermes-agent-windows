# Hakua-RSI Independent Artifact Audit

## Verdict

**Independent artifact audit: NEEDS_REVISION**

The reported Level 1 is **not yet independently audited**. Human approval remains pending, and no promotion to `hakua-epistemic-v0` or Level 2 is authorized.

## Six-axis audit

| Axis | Verdict | Summary |
|---|---|---|
| causal_validity | NEEDS_REVISION | The correction directions are plausible and consistent with the supplied conversation, but the bundle does not contain primary/raw evidence for all four trajectories. |
| claim_strength | NEEDS_REVISION | ASR censoring and PID hedging are good; the fence row is too categorical for `asserted_with_caveat`, and one authority classification is unsupported. |
| generalizability | NEEDS_REVISION | General lessons exist, but transient facts remain in rows and there is no Stage-2 formatter contract yet. |
| instruction_boundary | PASS | All shipped rows enforce `content_role=quoted_data` and `action_permission=none`; compiler logic rejects violations of these two fields. |
| provenance_integrity | NEEDS_REVISION | Row→snapshot provenance is exact, but snapshot→actual memory/revision/raw evidence is not independently resolvable from the bundle. |
| artifact_integrity | **FAIL** | Core hashes/determinism pass, but the verifier reports checks as PASS/false that the compiler does not actually execute. |

## Independently reproduced strengths

- ZIP SHA-256 matches: `5ab281294b79a33565e6f1b0705995a542cb0972b9847aa42278692c3af368aa`
- Every hash listed in `LINEAGE.json` matches its shipped file.
- Canonical source snapshot SHA matches the dataset manifest.
- Compiler SHA matches the manifest.
- `train.jsonl` SHA matches the manifest.
- `manifest_body_sha256` recomputes correctly.
- Exhaustive **24/24** input permutations produce one dataset SHA and one output ordering.
- All four shipped rows pass the supplied JSON Schema when independently validated.
- All four `train.jsonl` rows exactly match their corresponding `source_snapshot.json` candidates.

## Blocking findings

1. `compiler.py` does **not** load or apply `candidate.schema.json`; `schema_result="PASS"` is hard-coded.
2. A candidate missing a schema-required field can be accepted while the generated verification report still says schema PASS.
3. `REJECT_HOLDOUT_ORIGIN` is declared but there is no holdout-origin check.
4. `REJECT_CONTRADICTORY_UNRESOLVED` is declared but there is no unresolved-contradiction check.
5. `holdout_contamination=false` and `duplicate_conflict_check="PASS"` are literal outputs, not derived verifier results.
6. Fixture source/test code is not shipped, so `verifier_evidence.json` cannot itself be independently rerun.
7. The shipped compiler's default source path does not exist in the ZIP, so `python compiler.py` fails standalone.
8. Provenance reaches the shipped snapshot, but not the underlying hakua-memory records/raw evidence.

## Required before re-audit

- Integrate real JSON Schema validation into the compiler/verifier.
- Implement + exercise all declared reject rules, especially holdout and unresolved contradiction.
- Derive verification fields from executed checks; no hard-coded PASS/false.
- Ship the fixture/test definitions.
- Make the bundle compiler directly reproducible with its shipped snapshot.
- Add resolvable underlying memory/revision evidence.
- Correct the unsupported `external_verified` authority label.
- Soften the fence candidate wording to match its caveated claim strength.
- Define the Stage-2 formatter contract before training.

## State after this audit

```text
Reported Level 1            = YES
Independent artifact audit  = NEEDS_REVISION
Human approval              = PENDING
Level 1 independently audited = NO
Level 2                     = NOT REACHED
weight_modified             = false
self_improvement_observed   = false
recursive_improvement       = false
```

**Next allowed transition:** revise the artifact and resubmit it for independent artifact audit.
