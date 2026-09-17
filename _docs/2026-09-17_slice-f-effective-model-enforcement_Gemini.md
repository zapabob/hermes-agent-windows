# Implementation Record: Slice F — Effective Model Enforcement

- **Date:** 2026-09-17
- **Author:** Gemini
- **Baseline Commit:** `a9c8a72b4b05920028d216ed4ceb6eedf56b20c2`
- **Scope:** Slice F — Effective Model Enforcement

---

## 1. Overview & Semantic Contract

Slice F guarantees that a model selected by the user does not merely appear selected in the UI/configuration, but is strictly executed by the selected provider adapter subject only to:
1. Documented provider-side canonicalization (e.g. `google/gemini-2.5-pro` -> `gemini-2.5-pro`, `anthropic/claude-3-7-sonnet` -> `claude-3-7-sonnet`).
2. Explicitly configured fallback (with original user intent preserved and fallback observable).
3. Explicit provider rejection.

### Terminology
- **`requested_provider` / `requested_model`**: User/session routing intent after alias resolution.
- **`wire_provider` / `wire_model`**: Identifier sent across the transport/network to the model backend.
- **`effective_provider` / `effective_model`**: Route/model actually used for the completed request.
- **Normal state**: `requested == wire == effective`, with `fallback = False`.

---

## 2. Changes Implemented

1. **`agent/model_route_observation.py`**:
   - Created `ModelRouteObservation` dataclass:
     - `requested_provider`, `requested_model`
     - `wire_provider`, `wire_model`
     - `effective_provider`, `effective_model`
     - `fallback: bool`, `reason: Optional[str]`
     - `effective_model_source: str` (`"request" | "response" | "server"`)
     - `session_id: Optional[str]`
     - Interoperability properties: `requestedProvider`, `requestedModel`, `wireProvider`, `wireModel`, `effectiveProvider`, `effectiveModel`, `effectiveModelSource`, `sessionId`
     - Serialization: `.to_dict()`, `.from_agent(...)`
     - Factory: `build_route_observation(...)`
     - Strictly zero secrets stored (no API keys, OAuth tokens, auth headers).

2. **Transports & Adapters**:
   - `agent/transports/types.py`: Added `model: str | None` and `effective_model_source: str = "request"` to `NormalizedResponse`.
   - `agent/transports/chat_completions.py`:
     - Captured `response.model` from underlying API response.
     - Marked `effective_model_source = "response"` when model is reported by the API.
     - Added bounded mismatch logging if server reports an unexpected model family without falling back.
   - `agent/transports/anthropic.py`:
     - Captured `response.model` on `NormalizedResponse`.
   - `agent/copilot_acp_client.py`:
     - Implemented `_apply_session_model` handling RED 9 contracts:
       - 9.A: Supported model -> sends `session/set_model {"sessionId": session_id, "modelId": target_id}`, effective model matches.
       - 9.B: Unsupported model -> logs warning, visible degradation, no silent claim that X is effective, effective model = server default.
       - 9.C: Virtual slug (`"copilot"`, `"copilot-acp"`, `"default"`, `"auto"`, etc.) -> never forwarded onto wire.
       - 9.D: Server without model switching -> preserves server default explicitly, does not falsely claim requested model ran.
     - Propagated `model` and returned `effective_model` in `_run_prompt` and `_create_chat_completion`.

3. **Fallback Provenance Preservation**:
   - `agent/chat_completion_helpers.py`:
     - Removed destructive mutation of `agent.requested_provider = fb_provider` in `try_activate_fallback`.
     - Stored `agent._fallback_reason` to ensure route observation reflects `fallback=True` with explicit reason while `requested_provider` and `requested_model` reflect the original user selection.

4. **Agent State & Lifecycle**:
   - `agent/agent_init.py` & `run_agent.py`:
     - Added `requested_model` parameter and attribute to `AIAgent`.
     - Added `"requested_model"` to `agent._primary_runtime`.
   - `agent/agent_runtime_helpers.py`:
     - Preserved and restored `agent.requested_model` across `restore_primary_runtime`.
   - `agent/conversation_loop.py` & `agent/turn_finalizer.py`:
     - Auto-constructed and stored `agent.last_route_observation = route_obs` on response arrival.
     - Included `requested_model`, `requested_provider`, `effective_model`, `effective_provider`, and `route_observation` in final turn dictionary.

5. **Test Suite**:
   - `tests/agent/test_effective_model_enforcement.py`: Comprehensive test suite verifying all 14 criteria:
     - RED 1: `test_openai_effective_model`
     - RED 2: `test_anthropic_effective_model`
     - RED 3: `test_gemini_effective_model`
     - RED 4: `test_openrouter_effective_model`
     - RED 5: `test_nvidia_effective_model`
     - RED 6: `test_nous_effective_model`
     - RED 7: `test_custom_effective_model`
     - RED 8: `test_local_effective_model`
     - RED 9: `test_copilot_acp_effective_model_supported`, `test_copilot_acp_effective_model_unsupported`, `test_copilot_acp_effective_model_virtual_slug`, `test_copilot_acp_effective_model_server_without_switching`
     - RED 10: `test_session_effective_model_isolation`
     - RED 11: `test_resume_effective_model`
     - RED 12: `test_no_silent_model_substitution`
     - RED 13: `test_explicit_fallback_observable`
     - RED 14: `test_requested_vs_effective_observable`

---

## 3. Adapter Matrix Classification

| Adapter / Provider | Canonicalization | Wire Transport | Effective Model Source | Fallback Policy |
| :--- | :--- | :--- | :--- | :--- |
| **OpenAI** | None (`model` verbatim) | `chat_completions` REST | `response.model` | Explicit configured fallback only |
| **Anthropic** | `normalize_model_name` (e.g. `anthropic/claude-3-7-sonnet` -> `claude-3-7-sonnet`) | `anthropic` messages REST | `response.model` | Explicit configured fallback only |
| **Gemini** | `bare_gemini_model_id` (e.g. `google/gemini-2.5-pro` -> `gemini-2.5-pro`) | Native REST `models/{model}:generateContent` | `response.model` | Explicit configured fallback only |
| **OpenRouter** | Verbatim vendor/model[:variant] | `chat_completions` REST | `response.model` | Explicit configured fallback only |
| **NVIDIA** | Verbatim vendor/model | `chat_completions` REST | `response.model` | Explicit configured fallback only; fail closed |
| **Nous** | Verbatim model | `chat_completions` REST | `response.model` | Reached only when requested |
| **Custom** | Verbatim custom model | Configured base_url | `response.model` | Explicit configured fallback only |
| **Local (Ollama/Llama)** | Verbatim model | Local port / base_url | `response.model` | Fails visibly if model unavailable |
| **Copilot ACP** | Virtual slug stripped; verified against available models | JSON-RPC `session/set_model` | ACP session / server | Server default if unsupported, warning logged |

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
