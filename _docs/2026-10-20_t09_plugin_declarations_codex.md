# T09 bounded category-platform secret declaration repair

Status: scoped implementation GREEN / review-ready, NOT COMMITTED. Full T09 and vendor independence remain PARTIAL. The broader native regression attempt below did not qualify.

## Requirement and scope

Human authorization limits product edits to `hermes_cli/config.py:platform_manifest_secret_envs` and declaration/native/category tests as needed. Only config.py and tests/tools/test_child_credential_boundary.py changed. No shared runner/bootstrap, LSP, Gateway, status, MCP, registry, dependency, main checkout, or other worker source was edited. No commit/push/install/production service action was performed.

The attached FULL_IMPLEMENTATION_PLAN (2).md T09 requires useful cold local effects while preserving plugin declaration fail-closed policy and profile isolation. This slice repairs a concrete discovery mismatch: normal user plugin discovery supports a category and plugin segment, while secret declaration discovery previously inspected only immediate children. Metadata-only inspection must not execute plugin code.

PC context/SOP: canonical C:/Users/downl/_docs/prompts/CLAUDE-FABLE-5.md, PC and repository AGENTS, common MILSPECLLMOps, Application, Python, LLMOps, Internet Connectivity SOPs; incremental-implementation/debug-failing-test/code-review-and-quality skills. This is a traceable scoped verification record, not a claim of formal certification.

## Frozen source and runtime

- HEAD throughout recorded runs: 5a4eeca983748de480658e68e6ac63a08d9b2241.
- Root: C:/Users/downl/.codex/worktrees/v0222-selective-20261017/hermes-agent.
- Qualified existing interpreter: C:/Users/downl/.codex/worktrees/v0216-semantic-20261010/hermes-agent/.venv/Scripts/python.exe. It loads current source from the selected root; the reference projection never enters runtime paths.
- Initial config SHA-256: 9a6c3263a379f96c38683f4b30c905fe53b37e4085dfd5b8005c6cb4385681d5.
- Final config SHA-256: 72538d8b28dcf3cd335dedd23262ed8c4be1e18f8f4eb6dbc5830bbdb402bccf.
- Final boundary-test SHA-256: 5adb60da125d174ccd078f940ce1f78326f1bc355ee10de92ac7b56fcab28edf.
- Native test file remains unchanged: d6f08ed8043ef336b3969fc705db20d45a4f457efcd79cdabc951212886f0093.
- Complete source hashes and graph/tool binding: tmp/continuation-20261020/t09-plugin-declarations/final-bindings.json.

The pre-existing current-worktree .venv lacks pytest; the first test-launch attempt did not collect and is not RED. The qualified interpreter was located from the prior audited t05-sharing-closed receipt, rather than installing or changing either runtime.

## Implementation and preserved boundaries

The existing declaration parser/validation remains intact. A function-local manifest iterator adds at most one category step. Native .yaml precedes .yml. A native or portable manifest owns its directory and stops category traversal. The explicit legacy user platforms root already consumes one user category segment, so it does not gain a third segment. Known unreadable/dangling declarations continue to refuse spawning. Provider/core authority, per-profile resolution, existing cache behavior, plugin admission and registration owners are unchanged.

New tests use cold real Windows Python workers in Japanese/space-containing task-owned homes. A synthetic CUSTOM_LOGIN variable has no generic secret-name suffix. The worker first confirms the real PluginManager scanner can discover the category platform, without importing its module; the platform module writes a sentinel if imported, which must remain absent. It then exercises each existing terminal/background/CLI/credential-CLI environment owner and launches a real child. A nonce/ordinary-value file is the positive effect. A malformed manifest must yield a declaration error and no child-effect file. Additional tests cover depth/native/portable stopping and .yaml/.yml precedence.

## Harness and safety

All harness additions are under tmp/continuation-20261020/t09-plugin-declarations. Parent shared run.py/bootstrap.py are unchanged. The task runner reuses the existing fxa01_owned_job.run_owned helper, assigning an unnamed kill-on-close Job before resuming the suspended test process. It records active counts before and after recovery, source hashes before/after, exact argv/cwd, JUnit counts and process-specific audits. Job recovery is never a successful qualification condition.

The runner starts from an OS-environment allowlist; HOME, USERPROFILE, APPDATA/LOCALAPPDATA, HERMES_HOME, TEMP/TMP, watchdog/userData and Git configuration/ceilings are task-owned. External secret loading and launcher repair are suppressed by a task-only import observer. Explicit project.env files remain allowed only beneath the owned root. Network lookup/connect/send and host registry changes are rejected and audited. CPython's synchronous socketpair construction is the only network-audit exemption. The final stdlib observer runs isolated with -I. No actual host secret is used or logged.

The first internal Git-ceiling preflight failed before a test Job started; corrected to the owned directory ceiling. A subsequent non-qualified pytest startup failure is retained as red-cold-category-02. An initial full owner attempt exposed a harness mistake: explicit task-owned project.env had been suppressed. Only the task bootstrap was corrected; no existing assertion or product behavior was relaxed. These initial attempts are not successful qualification evidence.

## Commands

Every final run uses the following actual command prefix, with the label/node/fault arguments recorded fully in its result.json:

    C:/Users/downl/.codex/worktrees/v0216-semantic-20261010/hermes-agent/.venv/Scripts/python.exe -I -B tmp/continuation-20261020/t09-plugin-declarations/run.py LABEL NODE [--fault=VARIANT]

The runner launches a fresh qualified Python process for one source test file, with explicit pytest_asyncio, disabled plugin autoload/cacheprovider, owned basetemp and JUnit output. Each result contains immutable before/after bindings, including the actual task harness and existing Job helper.

## Results

Evidence root: tmp/continuation-20261020/t09-plugin-declarations/.

| Run | Result | Meaning |
|---|---|---|
| red-cold-category-03 | 8 behavioral failures, 0 errors/skips | Four actual-child secret leaks and four malformed declarations admitting a spawn on the unchanged product owner. Positive ordinary/nonce effects were observed. |
| green-owner-final | 227 passed | Entire boundary owner file, including eight cold native and four bounded-discovery tests. |
| regression-env-final | 21 passed | Existing common subprocess environment owner regression. |
| regression-scanner-final | 12 passed | Existing plugin category/scanner/load gates. |
| native-cli-final | 1 passed | Existing native served-profile CLI child effect. |
| native-terminal-final | 1 passed | Existing native served-profile terminal child effect. |
| fault-final-missing-discovery | 8 behavioral failures | In-memory replacement with the frozen original owner restores the actual defect. |
| fault-final-allow-all | 8 behavioral failures | Empty declaration set leaks the synthetic value and admits malformed input. |
| fault-final-deny-all | 4 behavioral failures, 4 passed | Positive child effects reject universal denial; malformed cases remain rejected. |
| regression-native-final | TIMEOUT / NOT QUALIFIED | Whole existing native file emitted two progress dots before its 180-second Job deadline. No final JUnit was produced. Four active Job processes were recovered; active-after-recovery=0. Cause is not established, and this is not labeled pre-existing or passed. |

Final successful scoped runs total 262 passed, 0 failed/errors/skips, no network/registry violation, no timeout/recovery and no active descendants. Every RED/fault run above also exits without timeout/recovery/descendants, and all source hashes remain stable. Faults are in-memory only, with owner/replacement hashes in each process audit; product bytes were never overwritten by a mutant.

## Fresh CodeGraph and review package

Pinned real CodeGraph 1.6.0 was invoked through the existing npm-shim.js and bundled Node. The isolated reference-only graph-final contains 16 exact source files, 1,159 nodes and 3,010 edges, reports up to date, and excludes all other repository files/dynamic edges. The shared whole-repository index was not changed. final-bindings.json binds all projected bytes, the CLI hash, root and HEAD. Callers/impact/category caller/affected logs are adjacent. review.patch freezes the two-file diff.

Verified source path: hermes_subprocess_env / _sanitize_subprocess_env / _make_run_env -> _plugin_terminal_env_strip_keys -> platform_manifest_secret_envs. The cold source path also resolves provider declarations via provider_profile_secret_envs -> list_providers; module registration imports remain CODE_LIBRARY evidence, not an assertion that vendor HTTP/OAuth ran. No vendor-independence total is inferred from this slice.

## Remaining limits and rollback

The bounded repair is review-ready; no independent final review is represented as completed. Full T09, full native file acceptance, local model inference, all plugin child/profile paths, package tamper/source-pin validation, vendor independence and hosted CI remain PARTIAL/NOT_RUN. The broad native timeout remains visible and is not hidden by successful selected nodes.

Rollback is a review of the explicit two-file patch against its frozen starting bytes. No reset/clean/stash or automated rollback was performed. Existing initial-attempt evidence and all task-owned directories were retained. There are no outstanding test Jobs from this task; the timed-out Job was fully reaped by its retained authority.
