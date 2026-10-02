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
