# Windows semantic adoption — 2026-09-17, batch 1

## Scope and immutable inputs

This is a bounded behavioral adoption, **not a whole-upstream parity certification**.
Keep the existing native Windows architecture; do not merge upstream directories or
copy its decomposition merely because file hashes differ.

- Downstream base: `4aba35ed84aa8096c7394f0d26538bcdcdcab769`.
- Upstream reference: `NousResearch/hermes-agent@260da4ef6251b29aa830c8c949dbe7c92d58df5f`.
- Historical `.codex/UPSTREAM_SNAPSHOT.json` and its associated evidence are not changed.
- PR #128 was already merged before this base; its fixes are not reimplemented.

Inspection used pinned Git trees, selected live call paths, AST-level candidate
comparison, and native Windows behavioral tests. Path/hash/AST differences identify
candidates; none of them alone establish a behavioral gap or semantic equivalence.

## Adoption decisions

| Surface | Decision | Evidence and boundary |
| --- | --- | --- |
| Plugin validation security scan | Adopt in existing `hermes_cli/plugin_dev.py` | Reuse `tools.plugin_guard.scan_plugin` before the Doctor enters candidate registration. No duplicate validation/loader stack. |
| Catalog-reviewed automatic admission | Do not adopt | Doctor validation is not installation consent. Existing explicit approval/enablement policy remains authoritative. |
| Plugin loader/dispatcher/state decomposition | Do not follow mechanically | No directory migration or removal of native compatibility aliases is needed for the accepted behavior. This is not a claim that all new upstream plugin APIs are present. |
| Router provider profile isolation | Adopt in existing `plugins/model-providers/router/__init__.py` | Cache values and once-only flags are scoped with the existing Windows-normalized `hermes_home_key()`. Warmers capture ContextVars. Scoped dotenv endpoint selection precedes the process fallback. |
| MCP persistent schema cache | Retain native implementation | Compared `tools/mcp_schema_cache.py` at both pins: TTL, fingerprint, write-through deduplication, and list extraction are already present. Upstream helper extraction/combined conditions do not justify a rewrite. Whole-MCP transport/death-supervisor parity is not certified here. |
| Stable prompt-cache prefix boundary | Retain native implementation | Existing LRU/count/character bounds and proper non-whitespace suffix behavior remain. Existing boundary regression tests run in the native contract gate. |
| Memory provider lifecycle and identity | Preserve; broader adoption remains open | Existing manager prefetch context propagation must not be duplicated or replaced. F010/F160 identity, privacy, checkpoint, enhanced-memory and optional-provider boundaries are not changed. New upstream idle-sleep/wake lifecycle behavior still needs a live-call-path audit. |
| Same-model review cache-parity fork | Candidate, not implemented in this batch | Upstream introduces inherited resolved scopes. A future adoption must wire the trusted fork builder and prove model/provider/identity boundaries; accepting an attribute in a resolver alone is insufficient. |
| General task routing/fallback cooldown | Further audit required | The Router change here is the Ramp Router provider's capability catalog, **not** a claim of complete task-router/fallback parity. |

Upstream references:

- [Shared admission scanner](https://github.com/NousResearch/hermes-agent/blob/260da4ef6251b29aa830c8c949dbe7c92d58df5f/hermes_cli/plugin_validate.py)
- [Router profile-scoped caches and warmer context](https://github.com/NousResearch/hermes-agent/blob/260da4ef6251b29aa830c8c949dbe7c92d58df5f/plugins/model-providers/router/__init__.py)
- [MCP schema cache](https://github.com/NousResearch/hermes-agent/blob/260da4ef6251b29aa830c8c949dbe7c92d58df5f/tools/mcp_schema_cache.py)
- [Stable prompt-cache boundary](https://github.com/NousResearch/hermes-agent/blob/260da4ef6251b29aa830c8c949dbe7c92d58df5f/agent/prompt_cache_boundary.py)
- [Review-fork inherited cache scopes](https://github.com/NousResearch/hermes-agent/blob/260da4ef6251b29aa830c8c949dbe7c92d58df5f/agent/prompt_cache_scope.py)

## Behavioral contracts

### Plugin Doctor

The live `doctor_plugin()` entry point scans a resolved candidate before
`_doctor_runtime()` can import/register it. `dangerous`, unknown verdicts, and scanner
failure block that path. `caution` remains a diagnostic warning; it never authorizes
installation. Scanner failures expose the exception class, not arbitrary exception
text. High-severity diagnostics include rule identifiers and file/line locations,
not raw source snippets.

This static scan is **not a sandbox** and is not a TOCTOU guarantee against concurrent
candidate-directory replacement. Existing real-registration/network-blocking and
registry/module cleanup behavior is retained and tested.

### Router

The existing provider and wire API remain in place. A per-home state holder prevents
profile B from changing profile A's reasoning vocabulary or suppressing its disk
lookup/background warm-up. Legacy unscoped module cache slots remain supported.
The background thread captures the scheduling context before `Thread.start()`, so
fetch and disk mirroring retain that profile after the caller exits its scope.

This does not claim cache invalidation across API-key rotation inside the same home,
nor replace the existing provider's authentication or HTTP security implementation.

## TDD chronology and evidence

All recorded behavioral runs used native Windows Server 2025 / Python 3.11.9 and a
real detached Git worktree at `D:\a\_temp\native worktree 日本語`.
Tests were committed and their failures observed before the corresponding production
changes were materialized in that worktree. No user's local worktree or running
Desktop/backend installation was touched.

| Stage | Immutable input / output | Observed result |
| --- | --- | --- |
| Doctor RED | `dbb5c0feb5c3dabae5806aaa31dd75c4bdde523d` | 7 cases: 6 behavioral failures, 1 pass, 0 collection errors, 0 skips. [Run](https://github.com/zapabob/hermes-agent-windows/actions/runs/35161420744) |
| Doctor GREEN | Input `e03960901acc8bbb911481722ae905a2892df269`; tested source published as `eebaa25f7d90b7254849a769d2601214d7b51a7a` | 33 passes including existing Doctor and prompt-boundary tests; 0 errors/skips. [Run](https://github.com/zapabob/hermes-agent-windows/actions/runs/35161618305) |
| Router RED | `743719d193a7560abc1423fdcc29f7d1e0b0e17f` | 38 cases: 4 new behavioral failures, 34 passes, 0 collection errors, 0 skips. [Run](https://github.com/zapabob/hermes-agent-windows/actions/runs/35161863000) |
| Router GREEN | Input `25cd92db761ef1fd9e17219707c3db913a99a3bf`; tested source published as `cb74b514a3343f7aaedac36ea9bbdfd8d07d4df2` | 38 passes, 0 failures/errors/skips. [Run](https://github.com/zapabob/hermes-agent-windows/actions/runs/35161989892) |

The earlier Windows stdout-encoding failure occurred before tests; it is **not** RED
evidence. UTF-8 was set in the harness and the behavioral RED run was rerun.
The 33/38 figures overlap; they are not additive coverage counts.

One-shot source materializers were removed. Their temporary publication workflow
was replaced with a read-only exact-head native contract gate for Python 3.11 and
3.13. Tests receive no publication credentials. The permanent gate fails on missing
JUnit evidence, collection errors, skips, failures, or unexpectedly missing cases.

Reproduce the focused suite from the repository root:

```text
python -m pytest --noconftest -o addopts= tests/test_plugin_doctor_security_adoption.py tests/test_router_profile_scope_adoption.py tests/hermes_cli/test_plugin_dev.py tests/agent/test_prompt_cache_boundary.py -q
```

The minimal-dependency `--noconftest` gate deliberately exercises this bounded suite;
it does **not** replace the repository's ordinary CI, full-suite, integration, or
Desktop runtime-authority gates. Final PR checks must be evaluated on the latest PR
head, not on historical RED failures or an older GREEN commit.

## Merge and rollout boundaries

No data/schema migration, process-owner change, credential propagation change,
watchdog replacement, upstream structural merge, or Desktop UX change is included.
No bypass of protected-branch checks is permitted. Revert this bounded PR to roll
back the two behavior changes. Repository merge is not a claim that an already
running Desktop/backend binary has been rebuilt or restarted.

The broader plugin/MCP/memory/task-router/cache-parity audit remains incomplete.
The explicit candidates above must not be silently relabeled as implemented or
certified merely because this batch's focused tests pass.
