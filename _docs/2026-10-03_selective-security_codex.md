# Windows-native P0/P1 selective security adoption

The directive is the attachment `pasted-text-1.txt` supplied on 2026-10-03 JST.
This is a separate selective-intake campaign. The historical snapshot, N/LM/T
families and U1 records remain authoritative for their original campaigns.
No historical frozen input is redefined here.

## Frozen inputs and observed state

R_BEFORE: `63279301bcbdc185c1b07b98a9312eb0c862f26d`.
R_AFTER: `d3630f853239e8c41ce7201e09fbdf39bcbc5431`.
U_TARGET: `4ed093cb6be8a2fadb39e770898f6989fc67201d`.
D_BASE: `c20e98f1370c588645d796047788e3b6f9cc749d`.
Starting task HEAD: `dcbce54f62b91863d1dd819d919db725cd3853d9`.
Observed origin/main: D_BASE; observed upstream/main:
`5fe12f373ea65c1601db678c7841168d6394382b`.
Only the immutable U_TARGET was fetched; the moving head was observed by
`git ls-remote` and was not substituted.

The primary checkout is dirty. Its tracked changes, deletions, submodule and
untracked operator material were not modified or incorporated. The task's
original detached checkout was clean before this campaign.

The canonical PC prompt `C:/Users/downl/_docs/prompts/CLAUDE-FABLE-5.md` was
read. Its identity, product, API, tooling and environment claims do not replace
the actual system/developer instructions or verified tool capabilities.
The root AGENTS.md, .codex SOP, upstream policy, fork invariants, Windows
platform contract, FEATURES.yaml and CARRY.yaml were consulted. The new
directive authorizes its new frozen input; the older SOP's historical snapshot
remains unchanged. No publication or production lifecycle action is authorized.

## CodeGraph and capacity gate

Installed global CodeGraph 1.5.0 rejects the default Node 26.10.0.
Existing project tool CodeGraph 1.6.0 runs through its installed npm shim and
vendored Windows Node. Its help exposes query, explore, node, callers, callees,
impact and affected. `CODEGRAPH_NO_DOWNLOAD=1` and `DO_NOT_TRACK=1` are passed
per process; no global runtime or telemetry preference was modified.

The initial C-drive index failed with `database or disk is full`; the C drive
reported zero free bytes. Product edits remain forbidden until the required
revision-bound indexes are available. Source checkout and indexing on H are
being attempted. A baseline H worktree checkout failed when its Git index
could not be written on C; an empty CodeGraph index for that path is NOT valid
baseline evidence.

Automatic approval review rejected deletion of the task-generated C-drive
R_AFTER `.codegraph` directory with `blocked by policy`, without a more specific
reason. That deletion did not execute. No deletion workaround was used.
Only this task's C-drive indexing sessions were interrupted with Ctrl-C.

## Inventory and first family

The source-bound candidate manifest is
`docs/windows/selective-security-20261003/intake.json`. There are 11 candidates.
All results initially remain PENDING_CODEGRAPH. Missing upstream objects and
unresolved owner paths are explicit and require resolution, not guessed proof.
GHSA reporter credit remains UNVERIFIED_REPORTER: the supplied advisory URL
returned 404 during retrieval. Commit implementation authors are separate.

S01 owner is `plugins/platforms/email/adapter.py`. At D_BASE,
`_verify_sender_authentication` collects method verdicts and properties from
whole-header regular expressions, with dictionary last-match precedence.
The existing parser feeds sender_authenticated to EmailAdapter dispatch.
The planned RED fixture is a trusted authserv header containing `spf=fail`
and a quoted/comment/subtoken `spf=pass`, plus DKIM cross-clause property
mixing, multiple SPF clauses and malformed comments. Expected: authentication
False and no dispatch for the forged sender; legitimate aligned fixtures
remain authorized. RED has NOT_RUN status until a real test runs against the
fixed baseline. No failure due to missing dependency is counted as RED.

## Completion boundary

The actual integration checkout is `H:/hermes-worktrees/p0-p1-local-20261003`
on `codex/p0-p1-local-20261003`, based exactly on D_BASE. It is an isolated
shared-object clone with its writable Git metadata on H. The earlier H
worktree `p0-p1-selective-20261003` is the D_BASE source/index attempt.
R_AFTER and U_TARGET each have their own source worktree on H. None is used
as an import path. All C-drive and H-drive preliminary checkouts are preserved;
the failed `p0-p1-d-base-20261003` checkout/index is not accepted as evidence.

Both missing S08 source commits were subsequently fetched by exact SHA into
the H-local Git repository. No moving upstream branch was fetched.
The manifest was regenerated to record their source/author information.

D_BASE initial indexing failed with `database is locked`. A status call after
the failed writer exited reported index state `indexing` and 39,305 pending
references, despite populated nodes/edges. This is NOT a completed graph gate.
A same-index query attempted before indexing finished also failed with a lock;
its result is excluded from ownership evidence. A documented sync retry is
running. U_TARGET and integration indexing sessions were interrupted to limit
competing disk I/O and preserve free H space. R_AFTER indexing continues.
No runtime or production process was stopped.

Implementation, RED/GREEN, regression, mutation, native E2E, fresh graph and
independent review remain NOT_RUN. No family completion, parity or
release-readiness claim is made. A documentation-only intake commit records
this preparation; it is not an implemented-family commit. The goal remains active.

Broad upstream merge was not performed. Main was not modified.
Production Hermes resources were not used.


## S01 implementation evidence (pending final independent review)

All four CodeGraph indexes now reached complete/zero pending refs and have
separate pinned revision/source-hash receipts. Filepath-pinned Email explore
queries recover the actual owner; earlier fuzzy `verify` results and unrelated
builtin-name edges remain recorded as excluded limitations.

The original 42-case RED yielded 26 behavioral failures and 16 passes on the
D_BASE-equivalent owner. The final 56-case fixture includes 28 real native
parse-to-dispatch scenarios (19 hostile, nine legitimate), without IMAP/SMTP
or production state. The canonical Windows regression run passed 148 tests
across seven Email/profile/shared-authz files, with no skip or collection error.

The owner adopts only the frozen upstream authentication clause logic. It
preserves scoped secrets, dispatch policy, settings and existing authserv
selection. A result-token end boundary additionally rejects escaped `pass`
prefixes and `pass1`; the independent source review found this residual gap
in U_TARGET itself. From-address parser replacement is outside this clause
failure class and is not silently imported with the rest of the module.

Mutation evidence uses the existing repository framework's isolated native
environment and test execution functions. A verification-only commit-tree
snapshot, with no integration branch movement, gives the disposable checkout
a clean candidate HEAD. All four required semantic mutants fail behavioral
assertions; each is reverted byte-for-byte with clean tracked diff. Restored
candidate passes all 56 tests. Mutation code stays in ignored scratch.

CodeGraph was freshly synced after both owner/test edits; receipt S01_FINAL
records the indexed owner hash matching the clean verification candidate.
Its revision field identifies the unchanged integration parent, explicitly
distinguished from the indexed candidate source tree. No final family commit
or completion claim is made before independent review.

The stopped, task-generated C-drive partial R_AFTER index was moved, with
contents preserved, into this checkout's ignored tmp archive. The earlier
directory-delete request was rejected by automatic approval review with no
specific policy explanation. No deletion was performed or bypassed. This
preserving move allowed independent review to start; production indexes and
personal files were not touched.

Independent reviewer 01a0fef5-982a-7b82-a926-02264bf34f0e returned final S01 PASS with no actionable finding. Reviewed product/test hashes match the verified candidate; scope exclusion of From parser accepted. S01 is approved for its local family commit. No other family is complete.

CodeGraph markdown receipts normalize trailing whitespace on source-number blank lines for git diff --check. Owner/test bytes and reviewed SHA256 values are unchanged.


## S02 implementation evidence (pending independent final review)

S01 local family commit: 709c7aeedf6c192137d231d719ad8cadf59414f6.
S02's initial fixture had a WhatsAppCloud env-name error; that failure is
excluded, fixed before product edits, and the valid RED rerun yielded nine
real unauthorized-acceptance failures and seven positive passes. The owner
was otherwise D_BASE-equivalent. No import/dependency failure counts as RED.

The authz change removes generic bare-ID splitting and SimpleX's mutable
display-name match, while keeping the existing WhatsApp alias implementation.
The adapter already emitted immutable contactId; only its operator-facing
allowlist guidance changes. The old display-name acceptance test now asserts
denial. Profile-scoped authz, pairing, wildcard and opt-in behavior are retained.

Canonical Windows regression: nine files, 132 passed, zero failed or skipped,
including SimpleX adapter, profile/multiplex, relay/shared authz and S01 Email.
Four semantic mutants are killed, including all three required mutations and
a fail-open nonempty-allowlist mutation. Clean verification-only candidate
checkout restores byte-for-byte and all 16 behavioral tests pass again. Native
adapter event-to-principal cases prove allowed rename and denied collisions,
without WebSocket connections or production resources. Fresh S02_FINAL graph
hashes equal the clean candidate owner hashes. Final review/commit still pending.


## S02 implementation evidence (pending independent final review)

S01 local family commit: 709c7aeedf6c192137d231d719ad8cadf59414f6.
S02's initial fixture had a WhatsAppCloud env-name error; that failure is
excluded, fixed before product edits, and the valid RED rerun yielded nine
real unauthorized-acceptance failures and seven positive passes. The owner
was otherwise D_BASE-equivalent. No import/dependency failure counts as RED.

The authz change removes generic bare-ID splitting and SimpleX's mutable
display-name match, while keeping the existing WhatsApp alias implementation.
The adapter already emitted immutable contactId; only its operator-facing
allowlist guidance changes. The old display-name acceptance test now asserts
denial. Profile-scoped authz, pairing, wildcard and opt-in behavior are retained.

Canonical Windows regression: nine files, 132 passed, zero failed or skipped,
including SimpleX adapter, profile/multiplex, relay/shared authz and S01 Email.
Four semantic mutants are killed, including all three required mutations and
a fail-open nonempty-allowlist mutation. Clean verification-only candidate
checkout restores byte-for-byte and all 16 behavioral tests pass again. Native
adapter event-to-principal cases prove allowed rename and denied collisions,
without WebSocket connections or production resources. Fresh S02_FINAL graph
hashes equal the clean candidate owner hashes. Final review/commit still pending.

S02 independent review requested additional SimpleX-specific profile pairing, scoped-miss, displayName fallback and group-collision evidence. Eight behavioral cases were added without changing product code. Reviewed suite now has 24 candidate tests and 140 total PASS across the same nine files; all four mutations were rerun at a new clean verification candidate and killed, restored 24 PASS. Nine native event-to-principal cases now cover direct/local name, profile.displayName fallback and group/memberProfile collisions. Fresh S02_REVIEW_FINAL includes the test update. First-pass evidence is preserved under S02/first-pass; final gate remains pending.

S02 final independent review PASS: requested additional boundaries verified, product/test hashes equal reviewed candidate 17143117ff9f51a701e2db14ae0ffd50b67691ec. No remaining actionable finding. Formal family commit authorized by original directive. S03 and later remain unimplemented.


## Task-local resource closeout before S03

Clean disposable S01/S02 verification worktrees were removed only after
their exact candidate commits were retained as refs/codex/verification/S01,
S02-first and S02-reviewed. No mutant source was committed. The source-only
R_AFTER checkout was moved without deletion from this chat's C: tmp/sources
directory to H: tmp/archived-source-r-after, and its frozen SHA/clean status
were checked afterwards. C: free space recovered to about 198 MB; H: about
2.268 GB at that observation. These are storage observations, not runtime
health or delivery gates.

The subsequent Git worktree repair emitted the expected relocated R_AFTER
gitdir repair and an unexpected diagnostic: .git file broken at
C:/Users/downl/feat_x-status-jina. That unrelated path was not inspected or
modified by a follow-up command. The repair command's diagnostic prevents
claiming that all unrelated worktree metadata was untouched. Primary main's
HEAD remained dcbce54f62b91863d1dd819d919db725cd3853d9 and its eight tracked
dirty paths remained unchanged in the read-only verification. No primary
product files, production processes or production Hermes state were changed.

S02 formal local family commit is
d0bba5c1d065b7b1d7d1c2d831a12ddc8e9e26f7. S01 and S02 are implemented;
the remaining nine families are not yet complete. S03 now has a valid native
boundary RED (50 failures/12 passes), a core GREEN (62 passes), a separate
profile/manifest RED after that increment (49 failures/58 passes), and a
profile GREEN (107 passes). The initial owner regression set passed 199 tests
with one macOS-only skip; the skip is not native Windows proof. S03 still
requires bridge coverage, full native spawn coverage, mutation, fresh graph,
independent final review and a family commit.


## S03 final candidate and native resource closeout

The authoritative verification candidate is 935586f9b758f6b8dc59200cf746b9de558621fe,
tree 1887bdeb1b57e44405444c220b7e324b0e38129b, parent
d0bba5c1d065b7b1d7d1c2d831a12ddc8e9e26f7. Earlier S03 counts and candidate receipts
are historical increments, not this final gate. Product owners use existing
credential tiers, scoped declarations, child environment factories and local
snapshot behavior. BaseEnvironment and remote backend source are unchanged.
The final owner/test hashes are in S03/mutation.json and intake.json.

Frozen D_BASE owners with these tests produce 205 behavioral failures and
40 passes. The clean candidate baseline and restored suite each pass 245.
All 24 semantic mutants are killed; syntax, import, collection and timeout
errors are not accepted as kills. Canonical regression on this immutable
candidate completes 27 files with 707 passed, zero failed and 13 skipped.
S03/regression-candidate.json records the exact argv, candidate and 17 source
hashes; S03-regression-final-source.log retains the runner output. Its explicit
OpenViking byte-writer/POSIX-only exclusions are reproduced or identified in
the manifest, and are not counted as passes.

Native Windows coverage passes 28 cases without skips. The source-bound
ledger observes 322 test process identities; before/after task footprints,
remaining observed identities and owned listeners are all zero. A separate
post-regression audit also reports zero processes/listeners and sends no
signals. A mixed-case snapshot probe runs against the same candidate and
retains served benign values and ordinary exports while removing the foreign
value and owned temporary files. Actual winpty is exercised without fallback.

The initial timeout fixture cleanup exposed an existing BaseEnvironment
Windows limitation: direct shim termination can leave MSYS descendants. This
family does not claim to fix that product timeout owner. Its test probe owns
its PID/birth identity explicitly, records the wrapper before initialization
wait, records descendants during polling, and cleans only matching owned
identities. Failed earlier resource receipts are preserved under the historical
S03 directories. Normal native and final resource gates now pass. Polling at
100ms can miss short-lived children; the final footprint audit is complementary,
not a claim of complete historical process enumeration. Windows file symlink
creation privilege error 1314 is not RED/PASS; unit lstat and native broken
junction tests provide their separately described coverage.

Fresh S03_FINAL_ACCEPTANCE graph is complete with pendingRefs zero and binds
the exact owner/test hashes and verification candidate. Source/path-pinned
review excludes false name-based edges. Independent reviewer
01a0fef5-982a-7b82-a926-02264bf34f0e approved source, all semantic mutants and
native resources; final canonical receipt has been submitted for family
approval. Backend model/effort are unavailable and are not inferred.

No broad upstream merge, main modification, production Hermes state or
production process restart is part of this family. Later-family preflight
documents and the S06 draft regression file remain separate uncommitted work.

S03 final independent review PASS: current candidate canonical 707 PASS/0 FAIL/13 SKIP and all source, mutation, native and resource receipts accepted. No actionable findings remain. Approval covers exact source/test bytes and audit helpers in the local family commit; its formal SHA is mapped after commit.

S03 evidence text views trim trailing console whitespace and blank EOF lines for diff-check compliance. S03/raw_logs.zip and raw_logs_index.json preserve and hash every original log byte; product/test source and test outcomes are unchanged.


## Authorized delivery closeout, 2026-10-03 JST

Later user instructions authorized main publication, canonical Desktop pack/restart and Go restart by 24:00 JST, with no llama operations and an implementation handoff for incomplete work. Accepted S01-S03 and selected-conversation Desktop Git fix were published at 6decaba; the handoff, runtime ledger and regenerated carry metrics were then published at 5ec659260b1313b56ca1c5a7d09f4455cee417ee. Product sources are unchanged between these heads. Existing primary tracked WIP hashes and 105 untracked file metadata remain unchanged.

S06 plugin/update subwork source-bound results, incomplete gates, immutable local WIP snapshot hashes and runtime/CI limits are recorded in docs/windows/selective-security-20261003/HANDOFF_20261003.md, delivery-ledger.json and s06-interrupted-work.json. S06 and seven other families remain incomplete; no full campaign acceptance is claimed.

Final S06 real CodeGraph 1.6 sync and capture both exit 0. The complete graph has 194800 nodes and 612485 edges; 55 receipts include query, explore, callers, callees, impact, affected and binding, at local S03 base 989b0709 with current WIP source hashes. All bound owner hashes still match. Graph receipts remain in the isolated S06 worktree. This is current graph evidence, not family acceptance. Nine fixture self checks passed; full native reacceptance and independent family review remain pending. The source-bound final audit is selective-security-delivery-closeout-20261003.json.


23:57 JST final runtime observation: Desktop PID11024 has a responding visible Hermes window. After a renderer-triggered connection reset at14:56:48Z, the new owned backend announced port59770 and ready at14:56:59Z; /api/status returns HTTP200. Current Go PID4364 /health also returns HTTP200 and status=ok. Previous status timeout and 90s announcement failure are retained as incidents, not erased. Continuous runtime stability is not proven. No llama operation was issued by this task. Main and origin/main matched c788077dfe32ed5e2219e0218e2f68c74dd15611 before this runtime receipt; final-head CI is pending/in progress, not all green. Full eleven-family campaign remains incomplete, with S06 and seven other families handed off in docs/windows/selective-security-20261003/HANDOFF_20261003.md.
