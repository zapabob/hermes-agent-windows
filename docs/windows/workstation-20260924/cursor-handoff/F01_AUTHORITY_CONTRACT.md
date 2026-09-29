# F01 approval authority contract (Integrator definition for LM03 / LM04 / LM05)

- defined_local: 2026-09-25 JST
- base: `feat/cursor-workstation-continue-20260925` at `d7fc97317b`
- status: CONTRACT_DEFINED (revision 2, after independent review). No product code
  changes in this unit. LM03 is unblocked for RED tests only; Control MCP write
  remains DISABLED.
- scope: contract only. It does not enable MCP writes or add a new authority module,
  and it does not change `tools/approval.py`, `downstream/control_mcp/*`,
  `plugins/implementation_router/*`, or the Desktop UI.

## 0. Ledger binding (no renumbering)

| Packet | Ledger definition (`LUNA_MAX_EXECUTION_PLAN.md`) | Contract sections |
|---|---|---|
| LM03 / RV04 | principal/client/profile/resource/args/source/policy/epoch/nonce binding; forged approval denied | 1-6, 8 |
| LM04 / RV05 | once-consume under a two-client race | 7 |
| LM05 / RV06 | scratch execute and destination apply need distinct approvals | 7.4, 8 |

LM03 means the F01 approval-binding implementation, so Phase A/B bind to it directly.

## 1. Existing authority (traced, not replaced)

- **Human decision authority:** `tools/approval.py`.
  - Public surface: `ControlApprovalBinding`, `request_control_consent`,
    `resolve_control_consent`, `take_control_decision`, `consume_control_verdict`.
  - Decisions live only in the process-local `_control_decisions`, and copied or
    serialised decisions are never accepted.
- **Durable operation state:** `downstream/control_mcp/journal.py`
  (`HostControlJournal`). State edges:
  - `PENDING_APPROVAL -> APPROVED | DENIED | EXPIRED | BLOCKED | UNKNOWN`. BLOCKED
    comes from `withdraw_unpresented` / `block_unexecuted`; UNKNOWN comes from
    `mark_admission_unknown`.
  - `APPROVED -> RUNNING` (`claim_approved`, and today also `transition`), plus
    `APPROVED -> CONFLICT | BLOCKED`.
  - `RUNNING -> SUCCEEDED | FAILED | BLOCKED | UNKNOWN`.
  - `APPROVED | RUNNING -> UNKNOWN` (`recover_after_restart`).
- **Admission:** `downstream/control_mcp/coordinator.py` (`HostControlCoordinator`).
- **Effect owner:** `plugins/implementation_router/control.py`. It revalidates the
  grant, calls `claim_approved`, submits the work, and records the outcome in
  `finally`.
- **Client grant:** `downstream/control_mcp/auth.py` (`auth.py:136,147`).
  `grant_revision` is the revision of the client's grant (its scopes, profiles and
  workspaces). It is NOT the policy revision.
- **Desktop mirror:** `apps/desktop/src/store/prompts.ts` and
  `apps/desktop/src/components/assistant-ui/tool/approval.tsx`.

All new fields below extend these owners. No parallel authority module is allowed.
Existing denial codes (`approval_required`, `approval_conflict`, `expired_approval`,
`revoked_grant`, `operation_conflict`, `workspace_busy`, `idempotency_conflict`,
`resource_denied`) are unchanged.

## 2. Canonical approval binding

The binding is `ControlApprovalBinding`, extended in place.

| Spec field | Field | Source of truth | Status |
|---|---|---|---|
| principal_id | `subject` | verified token `sub` | exists |
| client_id | `client_registration` | verified token `client_id` | exists |
| profile_id / workspace_id | same names | request, checked against the grant | exists |
| operation | `kind`, inside `intent_digest` | request | exists (implicit) |
| arguments_digest | `intent_digest` = sha256(canonical request) | `journal._validate_request` | exists |
| source_head | `source_sha`, inside `intent_digest` | request | exists (implicit) |
| destination_head | `expected_revision`, inside `intent_digest` | request | exists (implicit) |
| grant revision | `grant_revision` | auth grant | exists |
| policy_revision | `policy_revision` | host (3.1) | NEW |
| tool_revision | `tool_revision` | effect owner (3.2) | NEW |
| route_revision / provider_revision | same names, or `""` | host (3.3) | NEW |
| approval_owner_epoch | `owner_epoch` | journal epoch table (4) | NEW |
| nonce | `operation_id`, plus the decision `request_id` | journal / approval owner | exists |
| expiry | `expires_at` | journal | exists |
| presentation | `presentation_digest` | section 6 | NEW |

Rules:
- **Storage:** every NEW field is a journal column written at `reserve` and copied
  into the binding by `HostControlJournal._binding`. The existing compare in
  `consume_control_verdict` (`decision.binding != binding`) therefore covers these
  fields, with no second comparison path.
- **`intent_digest` is unchanged:** it keeps its current input set. The new
  revisions are separate fields, so a stale revision produces a specific denial code
  instead of a generic mismatch.
- **Retransmission identity is unchanged:** the NEW revision fields are not part of
  it (7.2). They are checked only by the fence (section 8).

## 3. Revision semantics

### 3.1 policy_revision

- **Meaning:** the host policy that decides whether an operation of this kind may be
  admitted and approved.
- **Value:** a per-kind policy slice, `sha256(canonical_json(slice))`. The slice
  holds that kind's scope from `SCOPES`, its request schema version, the allowed
  choices (`once`, `deny`), the timeout bounds, and the values of the
  `config.yaml` keys that the code lists in a per-kind `_POLICY_CONFIG_KEYS`
  constant.
- **Scope of invalidation:** adding or changing another kind does not change this
  kind's slice.
- **When it is checked:** recomputed at every effect-starting fence check (8.1).
- **On change:** approvals issued under the old value get `stale_policy`.
- **Relation to the grant:** it is independent of `grant_revision`. Grant changes
  are caught by the existing grant revalidation, and both checks apply.

### 3.2 tool_revision

- **Meaning:** the effect contract of the owner that performs the operation.
- **Value:** `"<kind>@<contract_version>"`. The effect owner adapter declares it, and
  `contract_version` is bumped by hand only when the request schema or the effect
  semantics change.
- **Not a source hash:** hashing source would churn on unrelated commits.
- **On mismatch:** `stale_tool`.

### 3.3 route_revision / provider_revision

- **Default:** not bound; the value is `""`.
- **route_revision:** a kind binds it only if it declares `route_sensitive = True`,
  meaning its effect class depends on routing (for example read-only analysis vs
  code-producing delegated work).
  - Value: `sha256(canonical_json({"effect_route_class": ...}))`.
  - Model id, catalogue refresh time, price and model-list changes are excluded.
    They never invalidate an approval.
- **provider_revision:** a kind binds it only if it declares
  `provider_sensitive = True`.
  - Value: `"<provider_id>@<adapter_contract_version>"`.
- **Current kinds:** `start_engineering_run` is route-sensitive with class
  `code_producing_delegate`, and not provider-sensitive. Its effect is confined to
  the scratch workspace, and apply is a separate operation (7.4).
- **On mismatch:** `stale_route` / `stale_provider`.

## 4. approval_owner_epoch

- **Meaning:** one live approval-authority generation. That is the process that owns
  `tools/approval._control_decisions` and the journal writer role.
- **Storage:** journal schema v2. `initialise()` must accept `user_version` 2 and
  migrate from 1. The epoch table is:
  `control_owner_epochs(generation INTEGER PRIMARY KEY, epoch_id TEXT UNIQUE NOT NULL,
  opened_at REAL NOT NULL, closed_at REAL NULL, owner_pid INTEGER NOT NULL,
  reason TEXT)`.
  - `epoch_id` is 128 random bits.
  - `generation` increases monotonically.
  - The single open row is enforced by
    `CREATE UNIQUE INDEX one_open_epoch ON control_owner_epochs((1)) WHERE closed_at IS NULL`.
- **Opening an epoch:** a single `BEGIN IMMEDIATE` transaction.
  1. Before this transaction, the host acquires a per-journal OS owner mutex and
     holds it until the process exits. Acquiring the mutex is itself the proof that
     any previous owner is dead; `owner_pid` is diagnostic only.
     - If the mutex cannot be acquired, startup refuses with `owner_epoch_busy`.
     - If an open epoch row exists while the mutex is held, that row belongs to a
       dead owner, and the next step closes it.
  2. Handoff between live owners happens only through an explicit host operation.
     It never happens silently.
  3. Close the previous epoch with a reason: `restart`, `handoff` or `recovery`.
  4. Insert the new generation.
  5. Run restart reconciliation (section 5) on the older generations' rows.
- **Admission order:** the host accepts no control request before this transaction
  commits.
- **Row stamps:** rows record `owner_epoch` at reserve. `approve` checks
  `row.owner_epoch == open epoch` and writes `approved_epoch := open epoch` in the
  same transaction. `claim_approved` checks `approved_epoch == open epoch`.
- **On mismatch:** `stale_owner_epoch`, with no effect.
- **Traced gap G1:** no epoch exists today. The process-local decisions die on
  restart, but an `APPROVED` journal row survives it.

## 5. Restart validity and reconcile

This runs inside the epoch-open transaction. It is never triggered by a transport
reconnect.

| Row state from an old epoch | New state | Reservation |
|---|---|---|
| PENDING_APPROVAL | BLOCKED (`stale_owner_epoch`) — NEW behaviour; today this row is left untouched | released (the decision died with its process, so provably no effect) |
| APPROVED | UNKNOWN while the I-CLAIM test is not GREEN on the branch; once it is GREEN, BLOCKED (`stale_owner_epoch`) | held while UNKNOWN; released when BLOCKED |
| RUNNING | UNKNOWN | held |
| UNKNOWN | UNKNOWN | held |
| terminal | unchanged | none |

Invariant I-CLAIM: every `APPROVED -> RUNNING` transition goes through
`claim_approved` in the same epoch, and no effect starts before it.
- **Today:** it holds for the production owner
  (`plugins/implementation_router/control.py:41-47`; effects only happen in
  `_execute`, after the claim).
- **The one bypass:** `transition` also allows `APPROVED -> RUNNING`
  (`journal.py:31`, used by `tests/control_mcp/test_operations.py:160`).
- **Contract:** remove that edge from `_EDGES`, so `claim_approved` is the only
  path, and migrate that test to `claim_approved`.
- **Consistency:** this matches `block_unexecuted` (`journal.py:240`), which already
  treats APPROVED as unexecuted.

Rules:
- UNKNOWN is never replayed automatically. A retransmission returns the existing row
  in state UNKNOWN (7.2).
- UNKNOWN leaves that state only through an owner reconcile that has effect
  evidence:
  - evidence of absence → BLOCKED, and the reservation is released
  - evidence of completion → SUCCEEDED / FAILED
  - no evidence → stays UNKNOWN

  The reconcile producer belongs to T12 and is out of scope here.
- **Traced gap G2:** `recover_after_restart` has no production caller; only
  `tests/control_mcp/test_operations.py:162` calls it. The epoch-open transaction
  becomes its only production caller.

## 6. Human approval UI display contract

- **One source:** a single pure function derives `ApprovalPresentation` from the
  journal row. The same row produces `ControlApprovalBinding`.
- **Transport:** the presentation is sent structured, as
  `_ControlApprovalEntry.data["control"]["presentation"]`.
  - `description` stays a short summary within its existing 6144-character limit
    (`approval.py:3068`). It is not the argument display.
  - `parameters.task` keeps its 16000-character limit and is carried in full inside
    the presentation.
- **Required presentation fields:** values are shown verbatim; only labels are
  localised.
  - `kind` and the static per-kind effect summary
  - `workspace_id` and `profile_id`
  - `resource` (destination) and `expected_revision` (destination revision)
  - `source_sha`
  - the complete `parameters.task`
  - `client_registration` and `subject`
  - `grant_revision`
  - the route effect class, when bound
  - `expires_at`
- **Parity check:**
  - The journal stores `presentation_digest = sha256(canonical_json(presentation))`
    in the binding.
  - The Desktop recomputes sha256 over the canonical JSON of the fields it actually
    rendered, using byte-identical rules to Python `canonical_json` (sorted keys,
    `(",", ":")` separators, UTF-8, integer-only numbers).
  - It sends that value together with `intent_digest` to `resolve_control_consent`,
    and a mismatch on either rejects the decision.
  - Echoing the server's digest back is not acceptable.
  - A Python/JS byte-parity fixture is part of B8.
- **Incomplete or non-rendered fields:** they disable both the approve button and
  the Ctrl/⌘+Enter approve shortcut (`approval.tsx:197-200`). Long text is shown in
  full in a scrollable region and is never truncated to a single line.
- **Traced gap G3:** `_binding` truncates the task to 2500 characters
  (`journal.py:199`), while `intent_digest` binds up to 16000 characters
  (`journal.py:51`).
- **Traced gap G5:** the Desktop control block renders only `grantRevision` and
  `resource` (`approval.tsx:218-233`), and `description` is rendered as a one-line
  `truncate` (`approval.tsx:97-98`).

## 7. Journal consume and replay semantics

### 7.1 Once-consume
- A decision object is consumed exactly once. This is the existing
  `_control_decisions.pop` in `consume_control_verdict`, which runs under the module
  lock inside the `BEGIN IMMEDIATE` transaction of `approve`.
- `claim_approved` is the only `APPROVED -> RUNNING` path (section 5) and succeeds
  at most once. A second claim gets `operation_conflict`.

### 7.2 Retransmission
- A request with the same `subject`, `client_registration`, `idempotency_key`,
  `intent_digest`, `resource` and `grant_revision` returns the existing row in its
  current state, including UNKNOWN.
- It never creates a new effect or a new approval request.
- The NEW revision fields are not part of this identity.
- A retransmission after a grant revision bump yields `idempotency_conflict`
  (existing behaviour, `journal.py:133-135`).

### 7.3 Replay by another principal or client
- Another client's operation → `resource_denied` (DENY_CLIENT_MISMATCH).
- The same idempotency key with different arguments → `idempotency_conflict`
  (DENY_ARGUMENT_MISMATCH).

### 7.4 Execute approval is not apply approval
- `kind` is inside `intent_digest`, and every kind has its own scope in `SCOPES`.
  An approval for `start_engineering_run` can therefore never authorise
  `apply_verified_result`, `create_pull_request`, `merge_pull_request` or a
  deployment.
- Each of those needs its own row and its own decision.
- Apply additionally requires a T12 trusted receipt bound by `operation_id`.

### 7.5 New denial codes
All match the `ControlError` regex `[a-z][a-z0-9_]{0,79}` (`contracts.py:13`).

| Spec label | Code |
|---|---|
| DENY_STALE_POLICY | `stale_policy` |
| (tool / route / provider) | `stale_tool`, `stale_route`, `stale_provider` |
| DENY_STALE_OWNER_EPOCH | `stale_owner_epoch` |
| (epoch opening) | `owner_epoch_busy` |
| DESTINATION_CHANGED | `destination_changed` |
| ALREADY_APPLIED | `already_applied` |
| DENY_ARGUMENT_MISMATCH / DENY_CLIENT_MISMATCH | existing `idempotency_conflict` / `resource_denied` |

## 8. Final writer fence

### 8.1 Effect-starting transitions
Applies to `approve`, `claim_approved` and the future apply. Each runs in one
`BEGIN IMMEDIATE` transaction and checks:
1. The caller's `epoch_id` is the open epoch.
2. Epoch stamp:
   - `approve`: `row.owner_epoch` is the open epoch.
   - `claim_approved` and apply: `row.approved_epoch` is the open epoch.
3. The row's `policy_revision`, `tool_revision`, `route_revision` and
   `provider_revision` equal the current host values.
4. The grant revalidates. The journal calls an injected grant-revalidation function
   (the same `auth` revalidation that the owner and coordinator call today) inside
   the same transaction. Today the journal only runs `require_access` and compares
   `grant_revision`.

Any failure changes nothing and returns the specific code.

### 8.2 Outcome-recording transitions
Applies to `RUNNING -> SUCCEEDED | FAILED | BLOCKED | UNKNOWN` (the effect owner's
`finally`, `control.py:131`).
- These check item 1 only.
- A revision change or grant revocation must never prevent a row from leaving
  RUNNING.
- If item 1 fails (the host lost its epoch), the state is left unchanged. The
  outcome evidence goes to an append-only per-run file under the profile's
  `get_hermes_home()`, and the row is picked up as RUNNING → UNKNOWN.
  - That file is only input for the T12 reconcile. It has no state authority.
- On a displaced host, background workers log the outcome and exit without
  mutating the journal. This includes the coordinator's `block_unexecuted` after a
  `stale_owner_epoch` failure, which must not raise out of the worker.

### 8.3 Other journal mutations
`reserve`, `expire_pending`, `block_unexecuted`, `withdraw_unpresented` and
`mark_admission_unknown` check at least item 1, so a displaced host can neither
reserve nor release.

### 8.4 Destination
- Apply is a compare-and-swap at the destination (for example
  `git update-ref <ref> <new> <expected_revision>`).
- A failed CAS returns `destination_changed` and has no effect.
- Reading the destination head inside the SQLite transaction is not a fence.

### 8.5 Limits
- In-process fence re-checks only narrow the race window. They do not fence
  external effects.
- Safety rests on RUNNING → UNKNOWN plus held reservations.
- Mid-run re-checks inside `run_workflow` wait for the T06 boundary.
- LM01 freshness receipts are never fence tokens or approval tokens.

## 9. Test plan binding (Phase B)

All tests target the existing owners, through
`tests/control_mcp/test_review_approval_binding.py` (the RV04–RV06 proposed nodes)
plus Desktop vitest for UI parity.

| Test | Contract | Packet | Expected |
|---|---|---|---|
| B1 stale policy | 3.1, 8.1 | LM03 | `stale_policy`, effect 0 |
| B2 stale owner epoch | 4, 8.1 | LM03 | `stale_owner_epoch` |
| B2b concurrent epoch open | 4 | LM03 | second host gets `owner_epoch_busy` |
| B3 destination changed | 8.4 | LM05 / Phase F | `destination_changed`, no effect |
| B4 argument replay | 7.3 | LM03 | `idempotency_conflict` |
| B5 retransmission | 7.2 | LM04 | existing row / UNKNOWN, no new effect |
| B6 second client | 7.3 | LM03 | `resource_denied` |
| B7 restart UNKNOWN | 5 | LM03 | no automatic replay |
| B8 UI/journal parity | 6 | LM03 | one-sided mutation of destination / operation / arguments detected; Python/JS canonical byte parity |
| I-CLAIM | 5 | LM03 | `transition` cannot move APPROVED → RUNNING; no effect before claim |
| G3 truncation | 6 | LM03 | a task beyond the rendered length cannot be approved |
| 8.2 outcome | 8.2 | LM03 | a revision change during RUNNING still allows the terminal/UNKNOWN record |

## 10. Still out of scope / blocked

- Control MCP write stays DISABLED until every Phase N gate passes.
- Out of scope here: the T12 reconcile/receipt producer, the T06 native boundary and
  the T11 cross-process budget.
- U=`b936546561888a54d5bf9cd7eae9629a824eb4f7` is not changed, and there is no
  upstream sync.
