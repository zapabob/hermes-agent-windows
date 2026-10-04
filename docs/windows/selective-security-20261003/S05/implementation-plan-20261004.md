# S05 implementation plan — 2026-10-04

Status: **HOLD / NOT IMPLEMENTED / NOT ACCEPTED**. This is a durable record
of completed read-only source review and a proposed implementation. No S05
product/test edits, RED/GREEN tests, native sentinel runs, mutants, installs,
network requests or production launches have been performed by this reviewer.
The user has authorized the complete selective intake implementation.
S05 implementation follows S06 acceptance under the specified family order;
the reviewer assigned to this investigation performed read-only work.
If S06 finishes late, publishing this plan alone does not accept S05.

## Frozen inputs and provenance

These four pins match the original attachment and `intake.json.pinned`.
Remote drift does not replace them.

| Pin | Commit | Meaning |
| --- | --- | --- |
| R_BEFORE | `63279301bcbdc185c1b07b98a9312eb0c862f26d` | Historical refactor semantics anchor |
| R_AFTER | `d3630f853239e8c41ce7201e09fbdf39bcbc5431` | Historical PR #102117 integration anchor; not latest main |
| U_TARGET | `4ed093cb6be8a2fadb39e770898f6989fc67201d` | Frozen upstream final contracts |
| D_BASE | `c20e98f1370c588645d796047788e3b6f9cc749d` | Frozen downstream owner baseline |

U_TARGET source root: `H:\hermes-worktrees\p0-p1-u-target-20261003`.
D_BASE source root: `H:\hermes-worktrees\p0-p1-selective-20261003`.
Current integration: `H:\hermes-worktrees\p0-p1-local-20261003`.
The review began against integration HEAD
`989b0709c3f0ae6ff4493ebd24e4fa82bbbdb9ac`; this document does not claim it
is the subsequently published head. U_TARGET's detached HEAD and D_BASE's
symbolic HEAD/branch ref were read directly from existing Git admin files;
no Git command or ref mutation was used. Historical pins are recorded from
the authoritative attachment/ledger, not claimed as newly executed tests.

Original specification:
`C:\Users\downl\.codex\attachments\b82fd564-4213-4aff-a9cb-f8625fab802b\pasted-text-1.txt`,
S05 lines 642–720. Family severity P0, action COMPOSE, upstream implementation
provenance `f5c754d4365e17ff7c6e7c1c51808ec36f4d7cc9`. Discovery/reporting
credit remains UNVERIFIED in intake; reading source does not resolve it.

## Actual frozen U_TARGET contracts

The final source, rather than only the original introducing commit, was read.

| U_TARGET file/line | Observed contract |
| --- | --- |
| `agent/lsp/workspace.py:157` | Launch and surface-selected cwd supply operator roots. Kanban has no automatic anchor; cron's job cwd is excluded. A Git root at/above HOME is excluded. This function imports `tools.terminal_scope`, which will not be ported. |
| `agent/lsp/workspace.py:186` | Explicit trusted directories allow descendants; otherwise the nearest Git root must equal an operator root. A nested clone's own `.git` does not inherit launch-root trust. |
| `agent/lsp/manager.py:65`, `:229`, `:553` | Parse trusted-workspace configuration and gate unsafe servers before live client/future reuse or spawn. Its accumulating operator roots and trust-only-growth assumption require composition for downstream session isolation/revocation. |
| `agent/lsp/servers.py:183` | Project `.venv`/`venv` is considered only for trusted roots. Operator VIRTUAL_ENV remains usable, including `Scripts/python.exe`. Installed Python fallback uses upstream PM; the PM subsystem will not be imported into D. |
| `agent/lsp/servers.py:238`, `:300` | Untrusted TS uses an SDK beside installed server/Hermes staging, with no project node_modules fallback. Missing safe SDK skips the server. |
| `agent/lsp/servers.py:380` | Deny by default except audited safe IDs: pyright, typescript, svelte-language-server, bash-language-server, yaml-language-server, dockerfile-ls, intelephense, clangd. Svelte also requires `isTrusted=False`. Rust, Vue/compiler plugins and build-evaluating servers are denied while untrusted. |
| `tools/file_operations_lint.py:171`, `:254` | Local `.ts`/`.rs` shell lint checks the actual linter execution cwd, not just the edited file. Untrusted `npx tsc`/rustup-rustfmt paths are skipped. |
| `hermes_cli/config_defaults.py:2411`; `cli-config.yaml.example:592` | `lsp.trusted_workspaces` defaults to an empty list and documents explicit operator selection. |
| `tests/agent/lsp/test_workspace_trust.py:99`, `:125` | Recording-only spawn/config tests cover launch/nested/explicit/cron/kanban/HOME and lint contracts. They are useful source contracts, not executed native marker proof. |

The upstream file-operation mixin split, PM integration, multi-root client
sharing and terminal-scope subsystem are not necessary downstream owners.
Compose the behavior into D's existing functions without copying that graph.

## Downstream boundaries and minimal owner plan

The actual cwd owner is
[agent/runtime_cwd.py](H:/hermes-worktrees/p0-p1-local-20261003/agent/runtime_cwd.py:60).
`tools/runtime_cwd.py` is absent in the inspected trees. Existing
[session_context.py](H:/hermes-worktrees/p0-p1-local-20261003/gateway/session_context.py:292)
pins session cwd; cron's existing scoped flag is set in
[scheduler.py](H:/hermes-worktrees/p0-p1-local-20261003/cron/scheduler.py:5938).
Kanban's model-selected task cwd must not be promoted into operator trust.
These carriers are reused; no new trust environment variable or subsystem.

| Proposed owner | Minimal responsibility |
| --- | --- |
| [workspace.py](H:/hermes-worktrees/p0-p1-local-20261003/agent/lsp/workspace.py:173) | Add shared trust helpers. Keep launch/operator provenance separate from terminal `cd`, cron workdir and kanban task workspace. Capture launch anchor only in an operator context; a worker's process cwd cannot create it. Reject HOME ancestors and nested Git roots. Normalize Windows drive/case and resolve trust containment through real filesystem paths, without changing LSP's lexical workspace identity globally. Trust must not reuse stale Git-marker cache results after a nested repository appears. |
| [manager.py](H:/hermes-worktrees/p0-p1-local-20261003/agent/lsp/manager.py:264) | Parse explicit trust; snapshot caller/session authority before background scheduling. Gate enabled_for, diagnostics, cache hit, future join and spawn. Introduce only local policy generation/metadata needed to invalidate clients and futures; no process-wide union of operator roots from other sessions. |
| [servers.py](H:/hermes-worktrees/p0-p1-local-20261003/agent/lsp/servers.py:232) | Carry trusted state into existing ServerContext. Exclude project interpreters when untrusted; retain operator VIRTUAL_ENV/Windows Scripts and an explicit installed-runtime fallback. Pin TS to verified installed SDK outside the untrusted checkout, or skip. Deny unsafe server IDs before builder/install/start. Safe Svelte initialization must prevent config execution. |
| [file_operations.py](H:/hermes-worktrees/p0-p1-local-20261003/tools/file_operations.py:2545) | Gate existing local TS/Rust fallback using `self.env.cwd`/actual execution cwd. Maintain in-process Python/JSON/YAML/TOML syntax checks, write/patch behavior and explicit skipped reason. LSP refusal must not cause execution through the fallback. |
| [LSP singleton](H:/hermes-worktrees/p0-p1-local-20261003/agent/lsp/__init__.py:45) | Existing singleton currently returns the first service without trust reload. Detect profile/trust-policy changes, invalidate affected clients and prevent old in-flight spawn results being published after revocation. Recheck policy before consuming a completed future. |
| [config.py](H:/hermes-worktrees/p0-p1-local-20261003/hermes_cli/config.py:2098) | Recognize the existing LSP configuration namespace and add/document the empty trusted_workspaces default. Validate list/path types; malformed entries grant nothing. Preserve existing downstream config changes and server override shape. |

`agent/lsp/install.py` already installs the TS SDK as an extra package beside
typescript-language-server. Preserve this positive instead of rewriting the
installer. Preserve installed Windows Scripts launcher resolution and
existing PowerShell server functionality. Explicit server initialization
options must not silently undo safety fields on an untrusted root. Operator
workspace trust is the gate for project runtime execution.

Revocation must invalidate both cached unsafe configuration (including a
pyright client previously pointed at project Python) and pending spawns.
Stop/discard affected owned LSP clients with existing lifecycle ownership.
A policy denial is not a permanent broken-server failure: later explicit
trust may retry. No automatic trust for nested repositories, no expansion
from another session, and no cache/future bypass after policy change.

## Five proposed RED cases — all NOT RUN

| ID | Concrete reproduction and required positive |
| --- | --- |
| R01 authority | Launch/operator-selected A; sibling clone B; nested A/vendor/B with its own `.git`; plain selected directory; HOME-ancestor repo; cron workdir B and kanban workspace B. Only the authorized root/explicit listed directory permits project code. A model's `cd` into B cannot grant trust. Explicit trusted B is positive; malformed config grants nothing. Include Windows junction escape and adding `.git` after workspace cache warming. |
| R02 Python | Put runnable marker sentinels in B/.venv/Scripts/python.exe and B/venv/Scripts/python.exe. Public read/write/patch must not invoke either or create a marker. Trusted B and operator VIRTUAL_ENV/Scripts/python.exe remain positive. With VIRTUAL_ENV absent, choose an explicit safe installed runtime rather than cwd-local Python discovery. |
| R03 TS | Put a repo node_modules/typescript sentinel and node_modules/.bin/tsc sentinel in untrusted B. LSP must load only the installed server SDK, or skip if none exists. Disable/unavailable LSP and omit ancestor tsconfig to exercise the real shell fallback: repo tsc still must not run. Installed server SDK/trusted project TS are positive. |
| R04 Rust/default deny | B has Cargo.toml, build.rs, proc-macro marker and rust-toolchain.toml. No untrusted rust-analyzer start or rustfmt fallback; marker absent. Unsafe Vue/build server overrides also cannot bypass root trust. Trusted Rust remains positive. Allowlisted Svelte must carry isTrusted=False, or remain denied until that contract exists. |
| R05 warm/in-flight policy | Start a trusted project client, revoke trusted_workspaces or switch caller/session to an untrusted worker, then request diagnostics/write. The old client cannot be returned or used. Hold a spawn future across revocation; its completion cannot reinsert or return the old client. Restore explicit trust and prove retry works; policy denial must not poison the broken set. |

Proposed test inventory: new focused `tests/agent/lsp/test_workspace_trust.py`
and native trust fixture coverage; extend existing test_workspace,
test_service, test_lifecycle and test_shell_linter_lsp_skip; use the real
public file_tools/file_operations chain in integration tests. These are
proposals only, not test files created by this review.

Existing positive regression inventory includes
`tests/agent/test_runtime_cwd.py`, the LSP backend/broken/stale diagnostics
tests, `test_install_and_lint_fixes.py` (Windows Scripts and installed TS
recipe), `test_powershell_server.py`, `test_client_e2e.py`, and
`tests/tools/test_file_operations_windows_paths.py`. Keep local versus
remote backend semantics explicit; host LSP must not run for remote files.

## Native and mutation gates — all NOT RUN

After S06 acceptance and implementation authorization, use a unique owned
temporary root with spaces/Windows drive paths, isolated HERMES_HOME and
already installed dependencies. Do not install or fetch test dependencies.
Prove sentinel executability in a trusted positive before treating its
absence in an untrusted case as evidence. Use actual native interpreter,
Node/installed language-server dispatch and Rust/build invocation markers;
record both process invocation and marker outcomes, not just SpawnSpec AST.
Exercise public read/write/patch and LSP-disabled fallback. Bound each child
and operation, retain process/Job ownership and demonstrate cleanup. A
missing native dependency or inert sentinel is HOLD/UNKNOWN, not PASS.

| Mutant | Required killed behavior |
| --- | --- |
| M01 | Treat every Git root as trusted; R01 must fail. |
| M02 | Always choose root/.venv or root/venv; R02 native marker must fail. |
| M03 | Permit project TypeScript SDK/fallback; R03 native marker must fail. |
| M04 | Permit untrusted Rust buildScripts/procMacro/server execution; R04 must fail. |
| M05 | Return warm cached client before checking current trust; R05 must fail. |
| M06 | Publish/join an old spawn future after revocation; R05 must fail. |

Isolate mutants; restore exact source bytes and bind each receipt to them.
Do not aggregate repeated partitions into extra PASS counts. Native gates,
focused canonical regressions, mutants and independent review are separate.

## Source hashes captured by this read-only review

SHA256 below uses raw file bytes. The first six current files and
gateway/session_context also match the inspected D_BASE byte hashes. Config
and scheduler differ from D_BASE because of existing integration work; they
must not be reset or replaced. Hashes are this review's snapshot, not a
claim that a later shared-workspace edit is automatically reviewed.

| Current integration file | SHA256 |
| --- | --- |
| agent/runtime_cwd.py | `c9a79cd5086e0afce63285de30c719257f0b2e84a7b8fa8fe5309aa13bd1bb75` |
| agent/lsp/workspace.py | `3cf2155fd06655ab57bdf7b768274f2d64207924283e87909dbfd5241cd609e9` |
| agent/lsp/manager.py | `0ea7126ba7499f15ac90b5871fa6f40dffedaca7f1da5ee14d48661d20beff8f` |
| agent/lsp/servers.py | `f71211a96e1b5198b9e354d8a0fca3ca8de830fb347da3cb4ff734e95c35987e` |
| agent/lsp/__init__.py | `5fce00264dd2e4d02750fd092063fb54de3308993003e234ee228f4b7f02981f` |
| tools/file_operations.py | `f137f0604838b804212173963b1162869fc502c3166999701077cffd15d67c0e` |
| hermes_cli/config.py | `6b7c07a57a477c6cb747381f91d4cc818f8bb4ba5818851cbf9771079973de8c` |
| gateway/session_context.py | `b68908ffec7891b12080933a4d50a63d449479a596335c2579776c6e545c4500` |
| cron/scheduler.py | `e5caf50bebcf6e682607f7c292944087df2964e00190dde680b1114ac9c84b56` |

D_BASE config SHA256:
`d679ca0b84f2e184b84f8557bf92bbeea55a021f7fc2e18f269264e1310c30b5`.
D_BASE scheduler SHA256:
`a7537a3822a05289a20262f133ab665e38cfeaaccb07a8e19ef0d82d60569783`.

| Frozen U_TARGET file | SHA256 |
| --- | --- |
| agent/lsp/workspace.py | `80646f6bd624e16afc4deeba57135e9cf34fe4022cd2123636e7337d0cfa3e28` |
| agent/lsp/manager.py | `bd1871ab26d9067fadb98b40e76f92c24454a091100498eabcbbfc4af4e319f8` |
| agent/lsp/servers.py | `5a863ee4153b88ff807a2037c74d24443b8c1c699f5ecc3e8b697ef9011033c3` |
| tools/file_operations_lint.py | `c0130fca628e6081fe8ce105059f1ab2beb0d5b4fa55dd5179685976342c2a1c` |
| tests/agent/lsp/test_workspace_trust.py | `a21b102e5b18cbbbdf5db3d88d0464c9f195df1c10fbd834dcec3d73fd8b2da4` |
| hermes_cli/config_defaults.py | `e85fdba7368a414817e611b9a6400a203d377ca552b85f4ea8ba5ee97e1ddb39` |
| cli-config.yaml.example | `369d74441ebff7ac323ae2d03f9814db70aafb4efa93c07721b90f233cfcb5d1` |

The U_TARGET three LSP hashes and config/example hashes match S05's existing
intake ledger. The downstream three LSP hashes also match its owner entries.
The additional shell-lint path is a required final-source contract, not an
assumed new subsystem.

## CodeGraph and acceptance gate

Real installed CodeGraph 1.6.0 was used, not simulated output: status,
runtime_cwd/get_service queries, workspace/manager/servers/runtime/file
operations exploration and get_service callers. Actual callers identified
include CLI status, `_lsp_will_handle`, `_snapshot_lsp_baseline` and
`_maybe_lsp_diagnostics`. Concrete current files were read afterward.

Current Graph: complete, pendingRefs 0, worktreeMismatch null; indexed
`2026-10-04T10:08:29.948Z`, 9,041 files. At the review status snapshot it had
1 added/7 modified pending files. Frozen U_TARGET: complete, pendingRefs 0,
worktreeMismatch null and no pending changes, 13,144 files; older extraction
metadata recommends reindex. No sync/reindex was executed. These navigation
results are not final acceptance bindings or execution evidence. Before
implementation, parent must confirm relevant owner bindings; after the
final implementation epoch, parent owns fresh source/caller Graph capture.

Acceptance requires explicit parent S06 acceptance first, authorized S05
implementation, observed source-bound RED, exact-byte GREEN, native marker
and positive proofs, at least M01–M04 killed, cache/future mutant coverage,
focused per-file canonical regression, final source/caller binding and an
independent reviewer with no unresolved P1/P2. No all-Python, release or
runtime-health claim follows from this plan.

Estimated authorized work: **90–150 minutes**, assuming usable existing
native dependencies/fixtures: approximately 25–40 minutes RED/minimal owner
composition, 40–70 minutes native/cache/lint cases, and 25–40 minutes focused
regression/mutants/review preparation (some work overlaps). This is not a
22:30 completion guarantee. If S06 is late or a native fixture is unavailable,
retain this plan and keep S05 HOLD instead of weakening a gate.

Metadata follow-ups remain separate and OPEN: S06-META-HONCHO external
workspace probe; S06-META-AKARI installation-tree scope decision;
S06-META-NEURO vendor metadata scope decision. This plan neither closes those
rows nor claims all internal Python Git callers are covered.
