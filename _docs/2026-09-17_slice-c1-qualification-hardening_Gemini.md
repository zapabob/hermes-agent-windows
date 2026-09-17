# Implementation Audit Log: Slice C.1 (Qualification Hardening & Three-Layer Authority)

> [!WARNING]
> **SUPERSEDED — do not read as final authority.**
> Slice C.1 qualification was superseded by **Slice C.1.1**.
> The authoritative receipt and final freeze commit are in
> [`2026-09-17_slice-c11-qualification-corrections_Gemini.md`](./_docs/2026-09-17_slice-c11-qualification-corrections_Gemini.md).
> **Final authority commit: `ecce743c762de70bb08c4363db7b64b5bac7c02b`**

- **Date**: 2026-09-17
- **Feature**: Slice C.1 Live Provider Catalog Qualification Hardening
- **Implementer**: Gemini (Advanced Agentic Pair Programmer)
- **Baseline Freeze**: `83c3c40652f85ce93ed383b1df824805c7a393fe`
- **Status**: SUPERSEDED by C.1.1

---

## 1. Objectives & Classifications Completed

All qualification invariants defined for Slice C.1 are fulfilled and verified:

```text
LIVE_PROVIDER_DISCOVERY = ALREADY_EQUIVALENT
LATEST_MODEL_ACCEPTANCE = PASS
THREE_LAYER_AUTHORITY = PASS
EXPLICIT_NOUS_DISCOVERY = PASS
EXPLICIT_NOUS_FALLBACK_BOUNDARY = PASS
SINGLE_FLIGHT_CONCURRENCY = PASS
CANONICAL_CACHE_ONLY = PASS
```

---

## 2. Hardening Details

1. **`_write_disk_cache` Fails Closed**:
   - `NormalizedCatalog` $\to$ persisted in canonical shape.
   - parseable `dict` $\to$ normalized $\to$ persisted in canonical shape.
   - unparseable `dict` or invalid payload $\to$ refused with logger warning; never persists non-canonical payloads to disk.
2. **Real Nous Routing Boundaries**:
   - `provider != nous` $\to$ zero Nous network/discovery calls.
   - `provider == nous` $\to$ invokes actual Nous live discovery boundary (`fetch_nous_models`) and hits transport under explicit permission.
   - Explicit Nous fallback configured but primary succeeds $\to$ zero Nous network/discovery.
   - Primary fails and explicit Nous fallback is entered $\to$ Nous discovery called strictly at that moment.
3. **True Three-Layer Authority**:
   - Live provider availability: `[model-A]`
   - models.dev metadata: `model-A` and `model-B`
   - Static fallback: `model-C`
   - Contract verified:
     - Available models presented in picker = `[model-A]` only.
     - `model-A` metadata enriched with models.dev context length and tool-calling capabilities.
     - `model-B` is not advertised as available when live provider does not offer it.
     - Static `model-C` used only when live endpoint is unavailable/offline.
4. **Actual Transport Acceptance**:
   - No mocking of `_fetch_picker_live_models`.
   - Uses real local HTTP `/v1/models` server on ephemeral port.
   - Verified dynamic appearance of newly released model (`["old-model"]` $\to$ `["old-model", "new-model"]`) and selection via `switch_model`.
5. **Real Concurrency & Single-Flight Dedup**:
   - Tested with $N=8$ simultaneous threads synchronized by `threading.Barrier`.
   - Verified physical fetch count = 1.
   - All callers receive valid catalog dictionary without exceptions.
6. **Bounded Timeout & Stale Cache Immediate Return**:
   - Live server stalling (5.0s delay) does not freeze the picker; picker returns boundedly in $< 3.0$s.
   - Stale cache returns immediately ($< 0.5$s) before background revalidation network completes.

---

## 3. Verification

All 61 tests across model catalog, adapter, live provider, routing, and fallback chains pass:
```powershell
uv run --no-sync pytest tests/hermes_cli/test_live_provider_catalog.py tests/hermes_cli/test_model_catalog_adapter.py tests/hermes_cli/test_zero_ambient_nous.py tests/hermes_cli/test_explicit_routing.py tests/hermes_cli/test_model_catalog.py tests/hermes_cli/test_fallback_chain.py
```
Output: `61 passed in 34.24s`.
Carry surface check: `Carry metrics are current.`
