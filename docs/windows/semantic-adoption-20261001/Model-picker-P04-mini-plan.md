# P04: executable minimum public-RPC source plan

Status: SOURCE_BOUND_PLAN_ONLY / TERMINAL. No product implementation, P03 review, test execution or product/parity approval.

## Frozen basis and ownership

Declared I P02: e66562b6236b1758a5bf8764a7f184ad5a672137.
D: a553729853b9648bf8ca9e5c3c7e54365d7f5c62.
R: d3630f853239e8c41ce7201e09fbdf39bcbc5431.
U: 1a269fcd3b61971bd05e841f80154279dd0a7e65.

[Detailed source/leaf report](../../../../evidence/Picker-P04-source-plan-001/report.md) and [before/after hashes and real graph receipt](../../../../evidence/Picker-P04-source-plan-001/source-hashes.json) are the evidence. Source semantics use declared blobs/fixed references, not temporary P03 mutations.

P03 terminal hashes reported by user and independently observed at closing: models.py 241f0badf1395e48e4654cb25028b5f88d62594ee0446b0b7b5402e309472747; model_switch.py 1d83a2914aa973bfe8f27912b3f46dc4fc5d21dd9a4a477f0d8d72b85cd53ac7. Both files remain owned by P03/its fresh independent review: BLOCKED_OVERLAPPING_OWNERSHIP for implementation. P04 issues no verdict. Bind their eventual final commit/tree/tests and reuse the final cache classifier/write admission.

Parent continues disjoint F08d proof closeout; user reports F04b commit4dea37991861f6dc16040f6a5f9f015acb4749db. Neither is reviewed here. Requested gpt-6.1-sol/high remains PENDING_UNEXPOSED actual session metadata; no global config edit.

## One executable first test

Add a sibling real-path fixture to existing tests/tui_gateway/test_model_picker_profile_native.py or one adjacent focused test file; retain its present mocked-inventory tests. Borrow its temporary profile/config setup and only the _RecordingTransport shape from tests/tui_gateway/test_protocol.py:1301. Do not borrow that protocol fixture's core-module mocks.

Use the actual installed server registry, server.dispatch, handle_request, _profile_scoped, inventory.build_model_options_payload/build_models_payload, list_authenticated_providers, credential fingerprint, registered ProviderProfile.fetch_models/parser and existing SWR/thread/executor/cache. No inventory/cache/registry/owner/clock double.

Use one existing registered generic provider such as DeepSeek, with a test-owned profile, synthetic key and configured https://p04.invalid/v1 endpoint. Verify that the finalized source still takes that existing generic profile path; do not insert a test-only provider. Its source chain is models.provider_model_ids -> providers.get_provider_profile -> providers/base.py:227–296 fetch_models -> hermes_cli.urllib_security.open_credentialed_url. Substitute only that credentialed URL transport leaf with entered/release Events and an HTTP-shaped JSON response containing a unique live-only model ID. Credential values are synthetic inputs. Deny unexpected DNS/socket/vendor URL transport at the leaf; no HTTP server or external account.

Cold means a fresh isolated interpreter with real production imports and empty test-owned provider/metadata disk state, not fake empty cache dictionaries. Submit actual JSON-RPC method model.options with profile and explicit_only:true to recording transport. Start real time.perf_counter before submission. dispatch returns None upon pool submission; completion is the matching response id written by transport.write.

Require a positive provider/current-model catalogue response within a proposed1.0s workstation bound, while entered and response Events are observed and release remains unset. An empty catalogue or dispatch returning None does not pass. The response may contain existing registry/config/current floor; no provider entitlement is inferred. Release the leaf only after that assertion. Require real parser/SWR cache persistence of the live-only ID, and its appearance in a second actual normal dispatch. Release Events in finally with5s emergency and10s whole-case deadlock guards. Clock and scheduling remain real. These are proposed bounds, not measurements.

Expected RED at P02: actual response waits at a cold provider or earlier metadata leaf. Expected GREEN after the bounded patch: positive response before held transport release plus real cache recovery. The current mocked-inventory fixture cannot establish either result.

## Minimum patch after P03 handoff

| Existing owner | Exact additive change |
| --- | --- |
| inventory.build_model_options_payload, D inventory.py:290–320 | Derive non_blocking_catalogs=not refresh and pricing_cache_only=not refresh. No wire flag/frontend change. |
| inventory.build_models_payload:120–287 | Add both keyword flags default False, forward to actual listing/enrichment. Existing CLI/ACP/MoA/other callers retain default behavior. |
| model_switch.list_authenticated_providers:2644 | Add non_blocking_catalogs=False; explicit refresh forces False. Pass non_blocking to six cached_provider_model_ids sites at D2971/3126/3131/3189/3283/3289. Bypass waiting parallel-prefetch collection/executor in this mode. |
| models.cached_provider_model_ids | Add non_blocking=False; force_refresh dominates. After finalized P03 fingerprint/tier admission, a cold/invalid/expired row enqueues existing _spawn_swr_refresh and immediately returns empty discovery; caller supplies existing configured/registry/current floor. |
| models._spawn_swr_refresh, P02:4638–4702 | Reuse copied ContextVar context, profile/key inflight lock/set, real thread, final P03 admission and merged write owner. No second scheduler/cache writer/inflight map/timer. |
| Normal listing metadata | Existing fetch_models_dev/get_provider_info/list_agentic_models(...,allow_network=False); additive allow_network on existing _merge_with_models_dev. Preserve registry/config/current fallback when models.dev is empty. |
| Existing custom/native helpers | non_blocking is separate from pure cache_only. Gate saved/grouped/bare-current live branches. Discovery-permitted current endpoints use existing SWR; saved discovery-disabled endpoints remain pure cache-only. Existing native probe gets cache-only branch, fresh empty remains authoritative, recognition helper cannot probe synchronously. No normal discovered_models config save. |
| models pricing/capability helpers and model_catalog.py | Add/cache-only gate existing owners, including provider manifest overrides; retain correct memory/disk/static metadata or omit unknown optional enrichment. Do not resolve live credentials to find a Nous metadata URL or copy U's pricing thread subsystem. |

The first narrow patch can omit cold optional metadata until explicit refresh; automatic metadata prewarming is not required. Any retained warming reuses the existing SWR callback and existing cache, with copied profile context and policy-permitted opaque key. No new router/auth-policy cache, dependency/config, agent.models_dev rewrite, frontend/RPC registry edit, PM/steward/vendor bootstrap or remote artifact service.

## Identified leaves and terminal classification

| Leaf or proof | State and disposition |
| --- | --- |
| models.dev cold fetch in D list:2811 and U list:1228; merge/provider-info readers | IDENTIFIED / PENDING_PATCH_AND_TEST. Pass existing allow_network=False; U's flag alone still blocks. |
| Nous curated manifest/master/provider override; LM Studio1.5s; Ollama cloud/native recognition0.5s/current custom | IDENTIFIED / PENDING_PATCH_AND_TEST. Existing cached/config/static floors and nonblocking owner; do not assume URLs are loopback. |
| Provider HTTP/SDK discovery and Codex/Nous/Copilot token resolution | IDENTIFIED / PENDING_RUNTIME. Keep behind real provider SWR on normal miss. |
| Pricing/tier/account/recommendations/org policy | PENDING_SCOPED_METADATA_CONTRACT. Global URL-only pricing is not account-policy evidence; no foreground resolver; unknown remains pending and known deny survives. |
| Nous cache-only capability read -> _nous_caps_cached -> nous_catalog_url -> _resolve_nous_pricing_credentials | IDENTIFIED foreground cold-auth wait despite cache-only comment. Bypass/omit unknown enrichment in normal request. |
| Current AWS botocore/IMDS/SSO probe | IDENTIFIED / PENDING_GATING_TEST. Existing local signal/current unverified skeleton; no interactive SDK credential-chain probe. |
| Credential pool load/seed/persist/auth-file/pool locks and arbitrary filesystem/CPU/pool waits | PENDING_BOUNDARY. has_available uses refresh=False; do not invent an OAuth refresh there. A1 does not prove universally nonblocking local auth/IO. |
| P03 fallback/classifier/write admission | BLOCKED_OVERLAPPING_OWNERSHIP. Await final reviewed source handoff, no P04 mutation/review. |
| Post-request profile, two owners same-profile dedupe, all metadata-stall cases | PENDING_RUNTIME. Required next acceptance cases; A1 alone cannot imply them. |
| Native HTTP fixture | BLOCKED_PREVIOUS_HTTP_ACTION. Automatic approval review rejected prior server-fixture action as blocked by policy before execution. No retry/new server/workaround. |
| Full provider validation/late ACK/Electron E2E | PENDING_SEPARATE_SCOPE; catalogue contract is insufficient. |

Before claiming the complete slice, extend this same real fixture to successful stale immediate response, worker profile after request reset, two transport owners/same-profile inflight dedupe, each stalled metadata/auth/custom leaf, explicit forced refresh waiting until release, cache-tier/native boundaries and failures. Pair with existing real ModelMenuPanel/QueryClient selection tests in apps/desktop/src/app/shell/model-picker-refresh-native.test.tsx; their RPC is synthetic and is separate renderer evidence. Preserve model/provider/effort/fast and newer choice, and known denial/no vendor prerequisites.

## Lifetimes and evidence limits

Keep models.dev4h/14400s, provider1h/3600s, successful stale7d/604800s, native Ollama300s and finalized P03 placeholder60s. U's optional Nous remote artifact20min/1200s is a separate purpose and is not adopted as provider TTL or required runtime. No4/12-hour or other periodic timer. Manual refresh remains explicit force under existing policy.

Real CodeGraph1.6.0 fixed D/R/U read-only SDK queries executed with unique P04 prefixes; eighteen target symbol-file hash bindings matched. No I graph query/sync while P03 mutated. Graph is partial/noisy static navigation; no runtime/whole-source coverage approval. Before/after blob and pending hashes are separate in source-hashes.json. No tests, HTTP/server/runtime actions, product changes, Git mutations, dependency/config/graph updates or other-worker review were performed.

Terminal result: JUSTIFIED_SOURCE_PLAN for the one public-RPC cold-response test and the additive existing-owner patch. Other leaves/proofs remain precisely PENDING/BLOCKED above. Parent can schedule this bounded slice after P03 ownership handoff without broad infrastructure work.

## P04 implementation pre-edit mini-contract (2026-10-01)

Parent explicitly released the four-product lease after Newton APPROVE_BOUNDED_SLICE and P03 commit 998ace4af0bbfe47cb85bec43da594bf3980007e, tree 5392bf67b4bbc855f38c3e77464f9d8eb4576957. The postcommit receipt is evidence/Picker-P03-postcommit-001.json. Final P03 models raw SHA-256 is 241f0badf1395e48e4654cb25028b5f88d62594ee0446b0b7b5402e309472747; switch raw SHA-256 is 1d83a2914aa973bfe8f27912b3f46dc4fc5d21dd9a4a477f0d8d72b85cd53ac7. Final classifier _disk_serve_tier and latest-disk writer _store_provider_models_entry have been read. This append semantically replaces the P02 implementation basis; their fingerprint admission, fallback provenance, success retention, writer lock and per-task/per-worker copied Context remain the governing owners.

Before the first product edit require an actual behavioral RED through installed server.dispatch/handle_request/profile wrapper to inventory and the registered DeepSeek ProviderProfile parser, plus a matching transport.write ID. New test is tests/tui_gateway/test_model_picker_cold_native.py; no existing test is rewritten. Credential resolution and URL opening alone are doubled. Clock, disk, registry, parsing, RPC registration, dispatch pool, SWR, classifier and writer stay real. First timed cold case runs in a fresh clean owned Windows process; production imports/registry initialization precede its perf_counter. Event-held provider/auth leaves and refused optional vendor transports cannot reach DNS/socket. No HTTP server fixture or workaround.

Implement normal non_blocking_catalogs and metadata cache-only propagation with defaults preserving other consumers; refresh forces existing live policy. Cold provider or discovery-permitted current endpoint schedules the existing profile-keyed SWR and returns the current/config/curated floor. Pure cache_only performs neither fetch nor SWR. Known native empty stays authoritative. Normal listing cannot save discovered_models to config. Cache-only metadata uses existing allow_network=False readers; cold optional manifest metadata can be omitted without auth resolution. Account-policy/Nous entitlement is not inferred from shared metadata; if required policy owner cannot be source-bound, record the remaining narrower boundary blocked rather than claiming full parity.

Acceptance: positive actual normal write under 1.0s while leaf held; after release actual parser/writer admission and a second actual RPC sees live ID; stale immediate; same-profile two-owner dedupe and different-profile isolation after request scope reset; force waits; failed refresh preserves successful bytes; saved custom pure-cache-only/discovery gates; native fresh empty; unchanged model/provider and config effort/fast. Retain TTLs metadata 14400, provider 3600, success stale 604800, native 300, failure 30, fallback 60. No timer, scheduler, pricing thread subsystem, vendor requirement, routing/import restructuring or additional owner. U optional Nous artifact 1200s remains a distinct unadopted source purpose.

Validation uses fresh owned processes, focused existing regression, targeted mutations with exact-byte restoration, four-root fresh CLI status/query/explore/impact/affected and public SDK source binding. Requested model/effort gpt-6.1-sol/high; actual metadata null. No commit, config/dependency edit, UI/security/schema owner edit, primary write or other-worker edit. Old 319-pass/143-source integration proof is historical, not P04 head GREEN. New receipts label log_sha256_raw and log_sha256_utf8_lf explicitly. Independent review remains PENDING.

Parent negative-metadata correction pre-edit contract: Nous authoritative policy/reasoning readers stay on their existing path and are excluded from the cold latency claim because account credential resolution may block. Same-profile/same-account real JWT and parsed warm transport must retain policy narrowing, reasoning=False and paid-model unavailability for known free tier. Unknown account must omit free_tier/unavailable_models rather than invent a paid entitlement; unknown Nous reasoning must omit its positive flag. The actual existing get_nous_portal_account_info owner is read-only SDK source-bound by Picker-P04-nous-account-SDK-001.json. Picker-P04-nous-unknown-RED-001 records actual public RPC unknown entitlement RED before this correction. No URL-global account cache is added; wider Nous cross-account cache correctness and bounded cold enrichment remain BLOCKED_SCOPED_METADATA, with existing runtime safety owners unchanged.

Custom stale callback refinement pre-edit: Picker-P04-custom-stale-RED-001 proves both success/failure public cases never reached the transport because the nested cached wrapper consumed stale data while the outer SWR already owned its key. In the existing _fetch_picker_live_models owner only, the SWR callback must use actual native/generic leaf parsing without recursively serving stale cache or stamping stale data fresh. Defaults retain the existing cached wrapper for blocking callers; the outer P03 writer remains the sole callback admission and failure leaves exact successful bytes intact. This changes no TTL, fingerprint or writer owner.

Saved-native pure-cache refinement pre-edit: Picker-P04-saved-native-RED-001 shows a fresh authoritative empty native row lost its marker in the existing saved section-3 read. Route this existing cache-only branch through the same native-aware helper, with cache_only=True and no probe/SWR. A row aged 301 seconds must cease to be authoritative under the existing 300-second TTL and fall back to saved config, still with zero native fetch/SWR. No new native detection or cache owner is permitted on this path.

Picker-P04-saved-native-RED-002 independently reproduces the same marker loss through saved custom_providers (section 4), while section 3 now passes. Apply the same cache_only helper to section 4 and the bare cache-only reader; retain all discovery, explicit-model, TTL and network gates. No additional owner or new test file.

Fresh metadata pre-edit correction: Picker-P04-cold-metadata-trace-001 preserves a real foreground stack list_authenticated_providers -> get_label -> get_provider -> get_provider_info -> requests.get, unlike the earlier same-file suite where retry backoff hid this path. hermes_cli/providers.py is read-only source-bound by Picker-P04-label-owner-SDK-001.json. Its existing get_provider(allow_network=False), normalized reseller exclusion and overlay identities may be consumed from the owned listing/inventory callsites; never edit providers.py. Normal labels and routing classification must use that existing cache-only provider owner, while blocking callers retain get_label/is_routing_aggregator. This is not a new provider/entitlement allowlist. Fresh process RED precedes the correction and 1-second acceptance is unchanged.


## P04 bounded implementation terminal

Implemented and verified the bounded public cold-response slice. Final canonical-003 passes 24 cases with --file-retries=0/file-timeout180; final-denied-regression-002 passes 191 cases in 13 existing files; mutants-final-002 kills 8/8 and restores four products exactly. Four-root final CLI and public SDK source bindings completed. Source-equivalent purpose matrix and exact final raw hashes are in evidence/Picker-P04-handoff-002/report.md and receipt.json. Independent review PENDING. Nous per-credential 300-second catalog freshness remains BLOCKED_SCOPED_METADATA; normal metadata after-4h SWR lifecycle is PENDING. No P05 patch, consolidated timer, upstream runtime import or commit.
