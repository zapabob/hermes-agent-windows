# Slice C.1.1 Qualification Corrections Audit Record

**Date**: 2026-09-17  
**Author**: Gemini  
**Baseline (pre-C.1.1)**: `191c695ea76fb68fd27f48d66a64e15e26ae70b1`  
**Freeze (C.1.1 qualified)**: `ecce743c762de70bb08c4363db7b64b5bac7c02b`  
**Status**: QUALIFIED (GREEN) — CLOSED

---

## 1. Executive Summary

Slice C.1.1 completes targeted qualification corrections to the live provider and model catalog subsystems, strictly enforcing contracts without refactoring or rewriting Slices A, B, B.1, B.2, C, or C.1.

Three key qualification contracts were hardened and verified:
1. **Real Single-Flight Concurrency (`SINGLE_FLIGHT_CONCURRENCY = PASS`)**:
   - Stale cache refresh condition simulated via disk cache mtime manipulation.
   - N=8 callers dispatched concurrently across threads synchronized by `threading.Barrier(8)`.
   - The first physical fetch is kept in-flight via thread events while the remaining 7 callers enter `get_catalog()`.
   - Asserts `physical_fetch_count == 1` strictly (not `<= 1`).
   - Asserts all 8 callers receive valid, usable catalog data without errors.
   - Verified that `_catalog_swr_inflight` is not pre-set manually.

2. **Real Live Provider Timeout (`LIVE_PROVIDER_TIMEOUT_BOUNDED = PASS`)**:
   - Real local HTTP server (`_DynamicModelsServer`) bound to localhost with a simulated delay of 6.0s (exceeding the 1.5s discovery timeout).
   - Custom provider probing kept explicitly ENABLED (`probe_custom_providers=True`).
   - Real live transport attempted (`server.request_count >= 1`).
   - Discovery elapsed time bounded (`elapsed < 5.0s < 6.0s stall`).
   - Picker gracefully returns pre-configured fallback models (`fallback-configured-model`).
   - Zero UI/hot-path indefinite blocking.

3. **Real Fallback Executor E2E (`EXPLICIT_NOUS_FALLBACK_RUNTIME_E2E = PASS`)**:
   - Production fallback execution owner identified via CodeGraph as `run_agent.py:AIAgent._try_activate_fallback` (and `agent/chat_completion_helpers.py:try_activate_fallback`).
   - Primary provider configured as deterministic failing fake provider with explicit fallback route `provider="nous"`.
   - Before primary failure: interceptor asserts Nous network call count is exactly 0 (`len(intercepted_nous) == 0`).
   - Primary failure simulated (`FailoverReason.server_error`), triggering `_try_activate_fallback`.
   - Fallback executor actively transitions provider to `"nous"` and activates explicit Nous fallback route (`activated is True`, `agent.provider == "nous"`).
   - Only after fallback activation is the Nous discovery / inference boundary reached (`fetch_nous_models`).
   - Asserts Nous network count is positive and bounded (`len(intercepted_nous) > 0`, all targeted to `nousresearch.com`).
   - Control case: Primary provider failure with NO explicit fallback (`fallback_model=None`). Visibly fails (`activated is False`), and Nous network call count remains strictly 0 (`len(intercepted_control) == 0`).

4. **Authority Separation Contract**:
   - **Authority 1 (Live Provider `/v1/models`)**: Authoritative for current availability / live existence (`list[str]` of model IDs).
   - **Authority 2 (models.dev Normalized Catalog)**: Authoritative for neutral, deep capability metadata (`NormalizedModel`: `context`, `tool_call`, `reasoning`, `modalities`, `release_date`).
   - **Authority 3 (Static In-Repo Fallbacks)**: Base offline fallback when un-probed.
   - Availability and capability metadata are intentionally separate APIs. Live availability is not artificially unified or duplicated into models.dev hot-path merge logic.

---

## 2. Platform & Engine Hardening

During testing on Windows x86_64, two runtime footguns were detected and resolved:
1. **Catalog Disk Cache Read-Time Re-serialization**:
   `parse_legacy_hermes_catalog` previously omitted `pval.get("name")` when constructing `NormalizedProvider`, causing provider names to revert to provider IDs upon re-read. This caused `_read_disk_cache` to detect a spurious diff and invoke `_write_disk_cache`, updating the cache mtime and colliding concurrently. Line 277 now evaluates `pname = str(pval.get("name") or meta.get("display_name") or pid)`.
2. **Windows Atomic Write `.tmp` File Contention**:
   `_write_disk_cache` previously used a static `.tmp` filename, causing Windows `PermissionError: [Errno 13]` when concurrent callers attempted to write simultaneously. Updated to process- and thread-unique temp paths `path.with_suffix(f".{os.getpid()}_{threading.get_ident()}.tmp")`.
3. **Explicit UTF-8 File Encoding**:
   `tests/hermes_cli/test_model_switch_custom_providers.py` had two tests calling `Path.read_text()` and `Path.write_text()` without explicit encoding, triggering CP932 multi-byte decode errors on Windows. Fixed with `encoding="utf-8"`.

---

## 3. Qualification Receipt

```text
======================= QUALIFICATION RECEIPT =======================
FINAL AUTHORITY COMMIT:             ecce743c762de70bb08c4363db7b64b5bac7c02b

Slice C  qualification — SUPERSEDED by C.1 / C.1.1 (do not read as final)
Slice C.1 qualification — SUPERSEDED by C.1.1 (do not read as final)
Slice C.1.1 qualification — THIS DOCUMENT (authoritative)

catalog correctness:                PASS
latest-model discovery:             PASS
Nous independence:                  PASS
fallback boundaries:                PASS
Windows concurrency:                PASS

ZERO_AMBIENT_NOUS_RUNTIME:          PASS (ALREADY QUALIFIED)
SOURCE_ADAPTER_NORMALIZED_CATALOG:  PASS (ALREADY QUALIFIED)
THREE_LAYER_AUTHORITY_HIERARCHY:    PASS (ALREADY QUALIFIED)
SINGLE_FLIGHT_CONCURRENCY:          PASS (QUALIFIED C.1.1)
LIVE_PROVIDER_TIMEOUT_BOUNDED:      PASS (QUALIFIED C.1.1)
EXPLICIT_NOUS_FALLBACK_RUNTIME_E2E: PASS (QUALIFIED C.1.1)

CATALOG TRACK STATUS:               CLOSED — do not expand
NEXT:                               Slice D (Desktop Model Picker Ownership)
=====================================================================
```
