"""Validate and atomically merge the ``delegation`` config block.

Used by the Desktop subagent settings Apply path. Validation runs *before*
any disk write so a bad draft never partially lands. Secrets are not accepted
from the GUI draft — existing ``api_key`` on disk is preserved untouched.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Mapping, MutableMapping, Optional

logger = logging.getLogger(__name__)

# Keys the dedicated subagent UI may set. Unknown keys are rejected so a
# typo cannot silently widen the surface.
_EDITABLE_KEYS = frozenset({
    "backend",
    "backends",
    "model",
    "provider",
    "base_url",
    "api_mode",
    "inherit_mcp_toolsets",
    "max_iterations",
    "max_summary_chars",
    "child_timeout_seconds",
    "reasoning_effort",
    "max_concurrent_children",
    "max_spawn_depth",
    "orchestrator_enabled",
    "subagent_auto_approve",
    "surface_child_process_notifications",
    "fallback_providers",
})

# Schema / tool-capability affecting — take effect on the next session.
SCHEMA_AFFECTING_KEYS = frozenset({
    "backend",
    "backends",
    "max_concurrent_children",
    "max_spawn_depth",
    "orchestrator_enabled",
})

_REASONING_EFFORTS = frozenset({"", "xhigh", "high", "medium", "low", "minimal"})

# Sentinel: omit key → inherit parent chain; explicit [] → disable fallback.
_FALLBACK_OMIT = object()


class DelegationConfigError(ValueError):
    """Raised when a delegation draft fails validation."""


def _as_nonneg_number(value: Any, *, field: str, allow_float: bool = True) -> float | int:
    if isinstance(value, bool):
        raise DelegationConfigError(f"{field} must be a number")
    if isinstance(value, int):
        if value < 0:
            raise DelegationConfigError(f"{field} must be >= 0")
        return value
    if allow_float and isinstance(value, float):
        if value != value or value < 0:  # NaN check
            raise DelegationConfigError(f"{field} must be a finite number >= 0")
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = float(value) if allow_float else int(value)
        except ValueError as exc:
            raise DelegationConfigError(f"{field} must be a number") from exc
        if parsed < 0:
            raise DelegationConfigError(f"{field} must be >= 0")
        return int(parsed) if not allow_float or parsed == int(parsed) else parsed
    raise DelegationConfigError(f"{field} must be a number")


def _as_positive_int(value: Any, *, field: str, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise DelegationConfigError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DelegationConfigError(f"{field} must be an integer") from exc
    if parsed < minimum:
        raise DelegationConfigError(f"{field} must be >= {minimum}")
    return parsed


def _normalize_fallback_providers(value: Any) -> Any:
    """Return None (omit/inherit), [] (disabled), or a cleaned list."""
    if value is None:
        return None
    if value == []:
        return []
    if not isinstance(value, list):
        raise DelegationConfigError("fallback_providers must be a list, null, or omitted")
    cleaned: list[dict[str, str]] = []
    for index, entry in enumerate(value):
        if isinstance(entry, str):
            slash = entry.find("/")
            if slash <= 0:
                raise DelegationConfigError(
                    f"fallback_providers[{index}] string must be 'provider/model'"
                )
            provider, model = entry[:slash].strip(), entry[slash + 1 :].strip()
        elif isinstance(entry, Mapping):
            provider = str(entry.get("provider") or "").strip()
            model = str(entry.get("model") or "").strip()
        else:
            raise DelegationConfigError(
                f"fallback_providers[{index}] must be an object or 'provider/model' string"
            )
        if not provider or not model:
            raise DelegationConfigError(
                f"fallback_providers[{index}] requires non-empty provider and model"
            )
        cleaned.append({"provider": provider, "model": model})
    return cleaned


def validate_delegation_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a full subagent draft. Returns a cleaned patch (no secrets)."""
    if not isinstance(draft, Mapping):
        raise DelegationConfigError("delegation draft must be an object")

    unknown = sorted(set(draft.keys()) - _EDITABLE_KEYS - {"api_key"})
    if unknown:
        raise DelegationConfigError(f"unknown delegation fields: {', '.join(unknown)}")

    if "api_key" in draft and draft.get("api_key") not in (None, ""):
        # GUI must not submit secrets; reject rather than persist a pasted key.
        raise DelegationConfigError("delegation.api_key cannot be set from this endpoint")

    out: dict[str, Any] = {}

    for key in ("model", "provider", "base_url", "api_mode"):
        if key not in draft:
            continue
        value = draft[key]
        if value is None:
            out[key] = ""
            continue
        if not isinstance(value, str):
            raise DelegationConfigError(f"{key} must be a string")
        out[key] = value.strip()

    if "reasoning_effort" in draft:
        effort = draft["reasoning_effort"]
        if effort is None:
            effort = ""
        if not isinstance(effort, str):
            raise DelegationConfigError("reasoning_effort must be a string")
        effort = effort.strip().lower()
        if effort not in _REASONING_EFFORTS:
            raise DelegationConfigError(
                "reasoning_effort must be one of: "
                + ", ".join(sorted(e for e in _REASONING_EFFORTS if e))
                + " (or empty)"
            )
        out["reasoning_effort"] = effort

    for key in (
        "inherit_mcp_toolsets",
        "orchestrator_enabled",
        "subagent_auto_approve",
        "surface_child_process_notifications",
    ):
        if key not in draft:
            continue
        value = draft[key]
        if not isinstance(value, bool):
            raise DelegationConfigError(f"{key} must be a boolean")
        out[key] = value

    if "max_iterations" in draft:
        out["max_iterations"] = _as_positive_int(draft["max_iterations"], field="max_iterations")
    if "max_summary_chars" in draft:
        out["max_summary_chars"] = _as_positive_int(
            draft["max_summary_chars"], field="max_summary_chars", minimum=0
        )
    if "max_concurrent_children" in draft:
        out["max_concurrent_children"] = _as_positive_int(
            draft["max_concurrent_children"], field="max_concurrent_children"
        )
    if "max_spawn_depth" in draft:
        out["max_spawn_depth"] = _as_positive_int(
            draft["max_spawn_depth"], field="max_spawn_depth", minimum=1
        )
    if "child_timeout_seconds" in draft:
        out["child_timeout_seconds"] = _as_nonneg_number(
            draft["child_timeout_seconds"], field="child_timeout_seconds"
        )

    if "fallback_providers" in draft:
        out["fallback_providers"] = _normalize_fallback_providers(draft["fallback_providers"])

    if "backend" in draft:
        backend = draft["backend"]
        if backend is None:
            backend = "default"
        if not isinstance(backend, str) or not backend.strip():
            raise DelegationConfigError("backend must be a non-empty string")
        out["backend"] = backend.strip().lower()
        # Fail closed at save time (same class as route-time refusal).
        try:
            from agent.delegation_registry import backend_status

            _provider, reason = backend_status(out["backend"])
        except Exception as exc:
            raise DelegationConfigError(
                f"could not validate delegation.backend: {exc}"
            ) from exc
        if reason:
            raise DelegationConfigError(reason)

    if "backends" in draft:
        backends = draft["backends"]
        if backends is None:
            out["backends"] = {}
        elif not isinstance(backends, Mapping):
            raise DelegationConfigError("backends must be an object")
        else:
            cleaned_backends: dict[str, Any] = {}
            for name, block in backends.items():
                if not isinstance(name, str) or not name.strip():
                    raise DelegationConfigError("backends keys must be non-empty strings")
                if block is None:
                    cleaned_backends[name.strip().lower()] = {}
                elif not isinstance(block, Mapping):
                    raise DelegationConfigError(
                        f"backends.{name} must be an object"
                    )
                else:
                    cleaned_backends[name.strip().lower()] = dict(block)
            out["backends"] = cleaned_backends

    return out


def merge_delegation_config(
    existing_config: MutableMapping[str, Any],
    draft: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deep-copied config with a validated delegation merge applied.

    Preserves unrelated top-level keys and any existing ``delegation.api_key``.
    ``fallback_providers: null`` removes the key (inherit). Explicit ``[]``
    stores an empty list (disable).
    """
    cleaned = validate_delegation_draft(draft)
    merged = copy.deepcopy(dict(existing_config))
    current = merged.get("delegation")
    if not isinstance(current, dict):
        current = {}
    else:
        current = copy.deepcopy(current)

    preserved_api_key = current.get("api_key")

    for key, value in cleaned.items():
        if key == "fallback_providers":
            if value is None:
                current.pop("fallback_providers", None)
            else:
                current["fallback_providers"] = value
            continue
        current[key] = value

    if preserved_api_key not in (None, ""):
        current["api_key"] = preserved_api_key
    else:
        current.pop("api_key", None)

    merged["delegation"] = current
    return merged


def schema_affecting_changes(
    before: Optional[Mapping[str, Any]],
    after: Mapping[str, Any],
) -> list[str]:
    """Return schema-affecting keys that changed between two delegation blocks."""
    before_block = before if isinstance(before, Mapping) else {}
    after_block = after if isinstance(after, Mapping) else {}
    changed: list[str] = []
    for key in sorted(SCHEMA_AFFECTING_KEYS):
        if before_block.get(key) != after_block.get(key):
            changed.append(key)
    return changed
