# Slice F — Effective Model Enforcement Implementation Record

## Date & Author
- **Date:** 2026-09-18
- **Author/Agent:** Gemini
- **Slice:** Slice F & F.1 — Effective Model Enforcement and Production Qualification Closure

---

## 1. Executive Summary

Slice F guarantees that a model selected by the user actually executes on the wire, subject only to documented provider canonicalization, explicitly configured fallback, or explicit provider rejection. It eliminates silent model substitution across all supported provider adapters and enforces full observability over the request/response lifecycle.

### Core Semantic Definitions
- `requested_provider` / `requested_model`: User/session routing intent after alias resolution.
- `wire_provider` / `wire_model`: Provider/model identifier sent across the network/transport.
- `effective_provider` / `effective_model`: Route/model actually used for the completed request.
- Normally: `requested == wire == effective`, except for:
  1. Provider canonicalization (e.g. stripping `anthropic/` or `google/` prefixes, mapping to endpoint URLs).
  2. Explicitly configured fallback (where `fallback=True`, `reason` is recorded, and original `requested_model` remains intact).
  3. Authoritative server response reporting (e.g. server downgrades or Copilot ACP server defaults).

---

## 2. Implemented Architecture & Production Changes

### 2.1 Model Route Observation (`agent/model_route_observation.py`)
- Created `ModelRouteObservation` dataclass:
  - Fields: `requested_provider`, `requested_model`, `wire_provider`, `wire_model`, `effective_provider`, `effective_model`, `fallback` (bool), `reason` (str | None), `effective_model_source` ("request" | "response" | "server").
  - Methods: `to_dict()`, with strict zero-secret exposure.
  - CamelCase properties (`requestedProvider`, `requestedModel`, `wireProvider`, `wireModel`, `effectiveProvider`, `effectiveModel`, `effectiveModelSource`) for seamless desktop/TUI UI bindings.
  - Factory function `build_route_observation(...)` supporting both agent/runtime introspection and explicit argument overrides.

### 2.2 Copilot ACP Protocol Lifecycle (`agent/copilot_acp_client.py`)
- Standardized ACP session model application in `_apply_session_model`:
  - **Case A (Supported model):** Dispatches `session/set_model {"sessionId": session_id, "modelId": target_id}` in strict protocol order: `initialize` → `session/new` → `session/set_model` → `session/prompt`. Reports `effective_model = target_id`, `source = "server"`.
  - **Case B (Unsupported model):** Suppresses `session/set_model`, logs clear degradation warning, avoids falsely claiming model was active, reports `effective_model = server_default`.
  - **Case C (Virtual slug):** Internal slugs (`"copilot-acp"`, `"default"`) are never forwarded to the ACP wire; resolves to advertised server default.
  - **Case D (Server without model switching capability):** When the ACP server advertises no `availableModels` and no `setModel` capability, preserves server default explicitly without false claims, suppressing `session/set_model`.

### 2.3 Gemini Native Adapter & Provenance (`agent/gemini_native_adapter.py`)
- Retains wire formatting to `/models/{model}:generateContent` using `bare_gemini_model_id`.
- Sets `effective_model_source = "request"`, ensuring requests are not falsely marked as authoritative response confirmations when Google's REST response omits an explicit echo.

### 2.4 Agent Lifecycle & Fallback Provenance (`run_agent.py`, `agent/agent_init.py`, `agent/agent_runtime_helpers.py`, `agent/chat_completion_helpers.py`)
- Added `requested_model` to `AIAgent`, preserving original routing intent during model initialization and in `_primary_runtime`.
- In `try_activate_fallback`: removed destructive overwrite of `agent.requested_provider`. Preserved `requested_provider` and `requested_model` while marking `fallback=True` and recording `_fallback_reason`.
- Restored `requested_model` and `requested_provider` faithfully in `restore_primary_runtime`.
- In `turn_finalizer.py` and `conversation_loop.py`: automatically captured `agent.last_route_observation` and included `route_observation` in the turn result dictionary.

---

## 3. Qualification Suite (`tests/agent/test_effective_model_enforcement.py`)

All tests execute against actual production request-building boundaries, real agents, and genuine transports:
1. `test_requested_model_switch_and_fallback_lifecycle`: Verifies `switch_model` establishes new requested routing intent, fallback preserves it, and primary restore returns to it.
2. `test_openai_compatible_transports_effective_model`: Parameterized across OpenAI, OpenRouter, NVIDIA, Nous, Custom, and Ollama, verifying wire payload `model` matches sentinel IDs and custom endpoints match configured `base_url`.
3. `test_anthropic_production_transport`: Verifies Anthropic SDK call receives exact normalized model ID without prefix.
4. `test_gemini_production_transport_and_provenance`: Verifies URL contains `/models/{model}:generateContent` and provenance source is `"request"`.
5. `test_copilot_acp_production_path_qualification`: Full subprocess JSON-RPC server test verifying call ordering (`initialize` → `session/new` → `session/set_model` → `session/prompt`), degradation handling for unsupported models, virtual slug filtering, and Case D (server without model switching capability preserving default).
6. `test_session_effective_model_isolation`: Concurrent threads driving Session A and Session B with zero cross-contamination.
7. `test_resume_effective_model_real_restore`: Validates that startup session resume restores persisted session model before the first inference call without transient default leakage.
8. `test_explicit_fallback_observable`: Validates `fallback=True`, `reason != None`, and provenance retention.
9. `test_no_silent_model_substitution`: Validates unexpected model drift in responses is flagged and observable.
10. `test_requested_vs_effective_observable`: Validates zero-secret dictionary serialization and camelCase schema.
11. `test_acceptance_receipt_matrix`: Programmatic verification of all 14 criteria.

---

## 4. Acceptance Receipt

```
OPENAI_EFFECTIVE_MODEL = PASS
ANTHROPIC_EFFECTIVE_MODEL = PASS
GEMINI_EFFECTIVE_MODEL = PASS
OPENROUTER_EFFECTIVE_MODEL = PASS
NVIDIA_EFFECTIVE_MODEL = PASS
NOUS_EFFECTIVE_MODEL = PASS
CUSTOM_EFFECTIVE_MODEL = PASS
LOCAL_EFFECTIVE_MODEL = PASS
COPILOT_ACP_EFFECTIVE_MODEL = PASS

SESSION_EFFECTIVE_MODEL_ISOLATION = PASS
RESUME_EFFECTIVE_MODEL = PASS
NO_SILENT_MODEL_SUBSTITUTION = PASS
EXPLICIT_FALLBACK_OBSERVABLE = PASS
REQUESTED_VS_EFFECTIVE_OBSERVABLE = PASS
```

---

## 5. Campaign Hygiene & Historical Commit Audit

### Classification of `f2d12687` Compression Hunks
- During the Slice F baseline commit `f2d1268766`, non-Slice-F changes in `agent/conversation_loop.py` were bundled:
  - `_compression_deferred_result(..., reason=...)` parameter handling and `"transient_block"` notification wording.
  - `_redecorate_prompt_cache_for_provider` typing overloads.
- **Classification:** `ACCIDENTALLY_BUNDLED`.
- **Status:** Benign, non-breaking, fully functional, and preserved without regression. They do not conflict with Slice F semantics.
- **Auditing Note:**
  ```text
  Slice F functional qualification = CLOSED
  campaign hygiene = compression hunks classified as ACCIDENTALLY_BUNDLED (non-breaking, preserved)
  ```

---

## 6. Continuous Integration (CI) Tracking

- **Latest CI Run Status:** Tracked as `pending` at audit time. Premature "All Green" claims avoided until GitHub Actions workflows report terminal success.

---

## 7. Next Step: Slice G Readiness

- **Status:** Slice F functional status is **CLOSED**.
- **Proceeding to:** Slice G — Fallback / Requested-vs-Effective Observability UX.
- **Scope Contract:** Zero new routing logic; project `ModelRouteObservation` safely into Desktop / CLI / TUI.
  - Normal operation: Quiet (`Claude Sonnet X · Anthropic`, canonicalization alone does not trigger noisy warnings).
  - Explicit divergence (`requested != effective` OR `fallback == true`): Visible indicator displaying requested route, effective route, and reason.
