# T09 model catalogue refresh evidence

## Scope and commits

Repository: `zapabob/hermes-agent-windows`

Frozen predecessor: `ffc8c74612e7ae279d02ec824f8a850686862756`

Initial product commit: `4f0b04c8d0ad54d69b586122340de7f371040d76`

Review correction product commit: `ed5b82e655ef1b9d74ae616fea24d4bf5e47a7a9`

T11 request-budget product SHA present in its separate worktree: `cdfd15080399bce52bb349ac8884aa4c9941ed96`. T11 has not been cherry-picked into this T09 branch; the default lazy import therefore fails closed until integration.

The source fingerprints in the adjacent before/after JSON files are SHA-256 over the raw bytes emitted by `git ls-tree -rz --full-tree <source_sha>`. The CodeGraph before index was built in a detached H drive worktree at the frozen predecessor. The first after index was synchronized after the initial product commit. Following the independent review corrections, the after index was synchronized again at the correction product commit and the adjacent after JSON describes that current source tree.

## Implemented behavior

The existing `FreeRouteCatalogueOwner` remains the authority for validating snapshots, classifying price evidence, deciding eligibility, retaining last-good state, and coalescing refreshes. The implementation adds a fixed-origin unauthenticated OpenRouter models adapter, a profile-scoped persistent cache and cross-process refresh lock, a 12-hour cadence, and the existing Desktop and Gateway host lifecycle triggers.

Interactive snapshot reads remain cache-only. Cold state returns UNKNOWN/no snapshot until the background owner completes a valid fetch. The picker allow-list is read from the active profile's existing model catalogue cache; the refresher does not call the picker manifest's four-hour network fetch path. Provider refresh starts only when both `model_catalog.enabled` is true and `model_catalog.providers.openrouter.free_route_catalogue_enabled` is explicitly true. Missing provider approval is disabled by default. No operational config was changed.

The Desktop FastAPI lifespan acquires/releases a lifecycle lease. `GatewayRunner.start()` and `GatewayRunner.stop()` acquire/release a lease around the running gateway. The leases share one host per profile in a process and reference-count Desktop and Gateway owners, so releasing one owner does not stop the other's worker. The refresh host checks immediately at startup and uses a five-minute due-check tick while running. The tick only checks the persisted 12-hour due time; it is not a second network cadence. Overdue triggers coalesce through the owner and the profile file lock.

The adapter fixes the HTTPS origin and path, sends no Authorization header, rejects redirects by using a direct HTTPS connection, and reserves T11's shared catalogue request budget under the host-owned `public:openrouter:catalogue` scope. The adapter fails closed if the budget module or required lease methods are unavailable. It sends `If-None-Match` when the provider has supplied a valid ETag, parses numeric or HTTP-date `Retry-After`, and records a 429 cooldown with the shared lease. It enforces a 30-second maximum lease, the lease's total and idle bounds at the socket, 64 KiB `read1` body chunks, a 4 MiB response cap, and a 1,000-model parse cap. Invalid, truncated, or oversized responses preserve the previous cache.

Only models already present in Hermes' existing OpenRouter picker list are projected. A model must report text input/output and tool support to become a candidate. All represented price components must be explicit and current to classify a route as verified zero-price; missing cache prices or any incomplete evidence remain UNKNOWN. Subscription inclusion requires separate exact-scope entitlement evidence and is not inferred from public pricing.

The correction adds a single process-wide bounded DNS resolver worker for the fixed OpenRouter host. A blocked OS `getaddrinfo` call cannot be portably cancelled; after its bounded caller wait expires, the refresh returns and releases its profile lock, while the T11 lease remains accounted through `worker_started()` / `worker_finished()`. The occupied resolver rejects later DNS work until the OS call returns, so a permanent resolver stall can leave one daemon resolver and one budget lease occupied, but cannot create one stuck thread per refresh. Existing active host ticks now re-read explicit provider approval immediately before fetching. A 304 refreshes only provider pricing/observation freshness, and only when it matches an ETag that was sent; it does not renew entitlement evidence. An unsolicited 304 cannot extend freshness.

The metadata class describes provider-advertised pricing. It does not establish this user's usage, quota, account entitlement, route availability at request time, or generation success. This slice does not wire `eligible_routes` into a production route-selection caller, add a model endpoint, make a paid probe, create a credential store, or alter a service definition.

## RED/GREEN and local checks

The initial adapter regression `test_openrouter_adapter_uses_catalogue_budget_and_bounded_conditional_fetch` failed RED on the exact frozen predecessor because `OpenRouterFreeRouteAdapter` was absent. After the first implementation, three review-specific RED cases were run at predecessor `4f0b04c8`: ETag 304 freshness did not update, `FreeRouteCatalogueOwner` lacked the dynamic `fetch_enabled` callback, and `_BoundedDNSResolver` did not exist. All three failed for those intended reasons. After correction, `tests/agent/test_free_route_catalogue.py` passes with 44 tests. The suite includes cache-only cold reads, no-config/no-network startup, profile A→B→A isolation, same-process Desktop/Gateway sharing and reference release, GatewayRunner start/stop, Desktop lifespan, separate-process profile locking, restart during a bounded fetch, 429 handling, ETag handling, response caps, slow body/header deadlines, blocked-DNS single-worker behavior and lease accounting, dynamic opt-in rechecks, and valid/unsolicited 304 freshness.

The review-specific RED command was `python -m pytest tests/agent/test_free_route_catalogue.py -q -k "etag_not_modified or rechecks_provider_opt_in or dns_stall_has_one_bounded_resolver"`. The corresponding regressions are `test_etag_not_modified_retains_last_good_snapshot_and_429_honors_retry_after`, `test_refresh_host_rechecks_provider_opt_in_before_each_due_fetch`, and `test_dns_stall_has_one_bounded_resolver_and_releases_profile_file_lock`.

Commands and results:

- `C:\Users\downl\Documents\New project\hermes-agent\.venv\Scripts\python.exe -m pytest tests/agent/test_free_route_catalogue.py -q` — 44 passed; one upstream `audioop` deprecation warning during the Gateway import.
- `uvx --from ruff==0.15.10 ruff check downstream/delegation/free_routes.py hermes_cli/model_catalog.py hermes_cli/web_server.py gateway/run.py tests/agent/test_free_route_catalogue.py` — all checks passed.
- `uvx --from ty==0.0.21 ty check --project H:\hermes-worktrees\t09-catalogue-refresh-20260924 --python C:\Users\downl\Documents\New project\hermes-agent\.venv\Scripts\python.exe hermes_cli/model_catalog.py` — passed.
- The same scoped `ty` check for `tests/agent/test_free_route_catalogue.py` — passed.
- The scoped `ty` check for `downstream/delegation/free_routes.py` has one unresolved import, `downstream.delegation.network_budget`, because T11 is still a separate worktree. The module is a required lazy dependency; there is no fallback that bypasses its budget.
- `ty` on `hermes_cli/web_server.py` and `gateway/run.py` reports the same 23 and 112 pre-existing diagnostics as the frozen predecessor, with no diagnostic on the added T09 lines.
- `py_compile` for all five changed files and `git diff --check` passed.

The repository parity runner was also attempted through the Windows WSL `bash.exe` launcher, but that shell could not resolve the Windows virtual-environment path. The focused pytest command was run directly with the project venv Python listed above.

## Controlled OpenRouter public GET

Two controlled HTTPS GETs were made without an Authorization header, credentials, or alternate endpoint:

| Request | Status | Bytes | Rows / total_count | SHA-256 | ETag | Elapsed |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| `/api/v1/models?limit=1000&offset=0` | 200 | 751,207 | 458 / 458 | `9c7f7bc28f3e9dc1d6ddd8eb3a4c7352f3b4f0b4989e0d5ac233931051235129` | absent | 0.937 s |
| `/api/v1/models` | 200 | 751,207 | 458 / 458 | `9c7f7bc28f3e9dc1d6ddd8eb3a4c7352f3b4f0b4989e0d5ac233931051235129` | absent | 0.656 s |

The adapter uses the simpler no-query request. The current [OpenRouter model-list documentation](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties) documents Bearer authorization and the optional `limit`/`offset` controls; omitting both returns the full list. The observed unauthenticated 200 is recorded as a live observation, not as a guarantee that authorization will never be required. If a future request returns 401 or another non-200, the fetch fails closed and last-good state remains. No account credential is reused.

The live response was below both implementation bounds and contained 458 rows, with no ETag. Thus the no-query response was complete for this probe; future responses above 4 MiB or 1,000 models fail closed and can leave cached prices stale until a supported response fits the bounds. Conditional ETag and 304 behavior is covered by deterministic tests, not by this live response.

## CodeGraph before/after

Pinned runtime: Node `v22.23.2` at `C:\Users\downl\AppData\Local\nvm\v22.23.2\node.exe`.

Pinned CLI command: `C:\Users\downl\AppData\Roaming\npm\npx.cmd --yes @colbymchenry/codegraph@1.6.0`.

The exact-base before worktree initialized 8,915 files; its status inventory reported 8,916 file nodes, 191,121 nodes, and 611,924 edges. Status was complete, pending changes 0, unresolved references 0, and `worktreeMismatch=null`.

After the initial product commit, CodeGraph synced 5 changed files (1,332 nodes). After the correction product commit, it synced 2 changed files (305 nodes). The current product index reports 8,916 files, 191,330 nodes, and 612,521 edges, with pending changes 0, unresolved references 0, complete state, and `worktreeMismatch=null`. The pinned extraction version is current at 25, with no full reindex recommended.

### Before query receipts

<a id="before-q1"></a>

**Q1 — `node --file downstream/delegation/free_routes.py --symbols-only`.** 41 symbols; the file was used only by `tests/agent/test_free_route_catalogue.py`. No production caller was indexed.

<a id="before-q2"></a>

**Q2 — `impact FreeRouteCatalogueOwner --depth 2 --json`.** 13 nodes and 16 edges: the owner, its refresh/read methods, and focused tests.

<a id="before-q3"></a>

**Q3 — `impact FreeRouteCatalogueOwner.refresh_if_due --depth 2 --json`.** 6 nodes and 5 edges: the refresh method and tests only.

<a id="before-q4"></a>

**Q4 — `impact eligible_routes --depth 2 --json`.** 5 nodes and 4 edges: the pure eligibility function and its focused tests.

### After query receipts

<a id="after-q1"></a>

**Q1 — `node --file downstream/delegation/free_routes.py --symbols-only`.** 98 symbols; indexed use is the focused test file and Desktop `hermes_cli/web_server.py`.

<a id="after-q2"></a>

**Q2 — `impact _BoundedDNSResolver --depth 2 --json`.** 10 nodes and 9 edges: the single resolver worker, adapter connection path, host factory/lifespan, and the blocked-DNS regression.

<a id="after-q3"></a>

**Q3 — `impact FreeRouteCatalogueOwner._refresh --depth 2 --json`.** 15 nodes and 27 edges: owner refresh, host loop, fetch-enabled check, 304 handling, and the focused refresh tests.

<a id="after-q4"></a>

**Q4 — `impact eligible_routes --depth 2 --json`.** 5 nodes and 4 edges: the eligibility evaluator and tests only. No production route-selection caller is present in this slice.

<a id="after-q5"></a>

**Q5 — `impact start_free_route_catalogue_refresh_host --depth 2 --json`.** 11 nodes and 10 edges: the host factory, Desktop lifespan, the direct lifespan regression, plus unrelated Control MCP lifespan tests matched by the symbol-level query.

<a id="after-q6"></a>

**Q6 — `impact OpenRouterFreeRouteAdapter --depth 2 --json`.** 11 nodes and 11 edges: the adapter, resolved HTTPS connection, bounded DNS resolver, adapter tests, and host factory / Desktop lifespan path.

<a id="after-q7"></a>

**Q7 — `node --file gateway/run.py --offset 12860 --limit 45`.** The indexed gateway file reports 32,560 lines and 0 symbols, so CodeGraph cannot show the GatewayRunner call path. Direct source at the selected range shows the idempotent Gateway lifecycle helpers and their lazy host start/stop calls; `test_gateway_runner_lifecycle_acquires_and_releases_host_lease` covers helper ownership and `test_gateway_runner_start_and_stop_call_catalogue_host_lifecycle` exercises the actual runner. This is a graph coverage gap, not a claim that Gateway startup is absent.

## Limits and follow-up boundary

The T11 `RequestBudget` is shared within one process. T09's OS file lock and persisted state coalesce the same profile cache across processes, but a public request budget across distinct Desktop/Gateway processes or different profiles is not established by these changes.

The adapter registers its abort callback before DNS/connect/header/body work. Once the HTTPS socket exists, the lease can close it, and socket timeouts are clamped to the remaining total deadline. DNS is isolated behind one process-wide resolver worker and the caller has a bounded wait, but the OS `getaddrinfo` call itself remains uncancellable; a permanent stall can occupy that one worker and its request lease until the OS call returns. Later resolution attempts fail closed while it is occupied. The regression verifies timeout return, profile-lock release, fixed worker count, and lease accounting through resolver completion; it does not prove the operating system will eventually return from DNS.

No Windows power notification registration is added. The host checks at startup, accepts a wake notification through the owner seam, and checks the persisted deadline on a five-minute tick after its thread resumes. A native OS wake callback remains unwired.

The CodeGraph file summary currently misses `gateway/run.py` symbols, so Gateway lifecycle impact is supported by direct source and tests. Pricing labels remain metadata only; `eligible_routes` has no production routing consumer in this slice.
