# Slice E: Session/Profile Persistence Semantics

**Date:** 2026-09-17  
**Author:** Gemini (Antigravity)  
**Status:** COMPLETE / GREEN  
**Baseline:** `321da834f6cbf39dc2a9a7202e07faf5de59f852`

---

## 1. Executive Summary

Slice E establishes explicit, deterministic, and predictable persistence semantics across all Hermes client surfaces (Desktop, CLI, TUI, Gateway, Settings).

### Sacred Invariant
- **Desktop/session picker:** Strictly session-only (`--session`). Never mutates the profile default.
- **Explicit `--session`:** Strictly session-only.
- **Explicit `--once`:** Transient next-turn model routing only; restores to previous state afterwards.
- **Explicit `--global`:** Profile default persistence in `config.yaml`.
- **Settings -> Model:** Profile default persistence in `config.yaml`.
- **Fresh profile (no configured provider/model):** First intentional selection seeds the initial profile default. A second selection on that profile is session-only and does NOT rewrite the profile default.
- **Stale ambient credentials:** API keys in the environment (`OPENROUTER_API_KEY`, `NOUS_API_KEY`, `OPENAI_API_KEY`) must never decide persistence scope or override explicit provider selections.
- **Atomic persistence:** `model.default`, `model.provider`, `model.base_url`, and `model.api_mode` persist atomically in a single multi-key YAML update.
- **Profile isolation:** Modifying Profile A's default never touches Profile B's configuration.

---

## 2. Precedence Hierarchy

`resolve_persist_behavior` in `hermes_cli/model_switch.py` acts as the single authority across all surfaces with the following 6-tier precedence:

1. `--once` -> transient (`False`)
2. `--session` -> session-only (`False`)
3. `--global` -> profile default (`True`)
4. Fresh profile initial intentional selection -> profile seed (`True`)
5. Explicit provider on already-configured profile without `--global` -> session-only (`False`)
6. Otherwise -> `model.persist_switch_by_default` compatibility policy

---

## 3. Implementation Details

1. **`utils.py`**:
   - Implemented `atomic_roundtrip_yaml_update_multi(path, updates: dict[str, Any]) -> None` to update multiple dotted keys in-memory on `CommentedMap`, preserving user comments, ordering, quoting, and Unicode, before writing to a single temp file and atomically replacing it via `os.replace`.
   - Updated `atomic_roundtrip_yaml_update` to delegate to `atomic_roundtrip_yaml_update_multi`.

2. **`cli.py`**:
   - Added `save_config_values(updates: dict[str, Any]) -> bool` leveraging `atomic_roundtrip_yaml_update_multi`.
   - Updated `save_config_value` to maintain backward-compatibility with tests mocking `atomic_roundtrip_yaml_update` or `save_config_value`.

3. **`tui_gateway/server.py`**:
   - Updated `_persist_model_switch(result)` to call `save_config_values` with `model.default`, `model.provider`, `model.base_url`, and `model.api_mode` in one atomic operation.

4. **`hermes_cli/model_switch.py`**:
   - Implemented `is_fresh_profile(cfg: dict | None = None) -> bool`:
     Evaluates profile configuration state directly: `model.default` unset/empty AND `model.provider` unset/empty. Never inspects ambient credentials or environment variables.
   - Updated `resolve_persist_behavior(..., profile_has_default: bool | None = None)` to implement the 6-tier precedence hierarchy.

---

## 4. Acceptance Receipt

| Check | Status | Evidence |
|---|---|---|
| `DESKTOP_PICKER_SESSION_ONLY` | **PASS** | `TestRed1DesktopPickerSessionOnly` |
| `EXPLICIT_SESSION_NON_PERSIST` | **PASS** | `TestRed4ExplicitSession` |
| `EXPLICIT_ONCE_NON_PERSIST` | **PASS** | `TestRed5ExplicitOnce` |
| `EXPLICIT_GLOBAL_PROFILE_PERSIST` | **PASS** | `TestRed3ExplicitGlobal` |
| `SETTINGS_PROFILE_DEFAULT` | **PASS** | `TestRed6SettingsModelPersistence` |
| `FRESH_PROFILE_FIRST_PICK_SEEDS_DEFAULT` | **PASS** | `TestRed7FreshProfileFirstSelection` |
| `SECOND_PICK_DOES_NOT_REWRITE_DEFAULT` | **PASS** | `TestRed7FreshProfileFirstSelection` |
| `EXPLICIT_PROVIDER_EXPLORATORY_IS_SESSION_ONLY` | **PASS** | `TestRed9ExploratoryProviderSwitch` |
| `AMBIENT_CREDENTIAL_PROVIDER_OVERRIDE` | **ABSENT** | `TestRed8StaleAmbientCredential` |
| `PROFILE_PERSISTENCE_ISOLATION` | **PASS** | `TestProfileIsolation` |
| `PROVIDER_MODEL_ATOMIC_PERSISTENCE` | **PASS** | `TestAtomicPersistence` |
| `PERSIST_SWITCH_BY_DEFAULT_COMPAT` | **PASS** | `TestRed10PersistSwitchByDefault` |

---

## 6. Slice E.1 Qualification Closure

Slice E.1 verified and closed all production-path qualification contracts:
1. **CLI Atomic Profile Persistence**: Replaced the 4-call `save_config_value` cluster in both `HermesCLI._apply_model_switch_result` and `HermesCLI._handle_model_switch` with a single atomic call to `save_config_values({...})`.
2. **Atomic Multi-Key Meaning**: Strictly commits `model.default`, `model.provider`, `model.base_url`, and `model.api_mode` together in a single atomic file replacement pass (`os.replace` via `atomic_roundtrip_yaml_update_multi`).
3. **Explicit Scope Precedence over Fresh Seeding**:
   - Fresh profile + `--session` -> does NOT seed default (session-only).
   - Fresh profile + `--once` -> does NOT seed default (transient next-turn).
   - Fresh profile + `--global` -> seeds/persists default.
   - Desktop live-session picker always emits `--session` -> strictly session-only, never seeds default.

### Final Receipt

| Receipt Item | Status | Verification Reference |
|---|---|---|
| `CLI_ATOMIC_PROFILE_PERSISTENCE` | **PASS** | `TestCliAtomicProfilePersistenceProductionPath` |
| `FRESH_PROFILE_PRODUCTION_SEED` | **PASS** | `TestFreshProfileProductionQualification` |
| `SECOND_PICK_SESSION_ONLY` | **PASS** | `TestFreshProfileProductionQualification` |
| `FRESH_PROFILE_SESSION_SCOPE_NON_PERSIST` | **PASS** | `TestFreshProfileScopePrecedence` |
| `FRESH_PROFILE_ONCE_SCOPE_NON_PERSIST` | **PASS** | `TestFreshProfileScopePrecedence` |
| `EXPLICIT_GLOBAL_PROFILE_PERSIST` | **PASS** | `TestFreshProfileScopePrecedence` |

**SLICE E STATUS = CLOSED**
