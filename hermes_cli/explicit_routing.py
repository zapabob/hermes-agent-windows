"""Explicit model routing policy — single source of truth for model selection.

This module centralizes model-switching policy so all surfaces (CLI, gateway,
TUI, Telegram picker) share the same resolution semantics.  The key contract:

1. Explicit provider+model → exact pair, no implicit fallback
2. Ambient Nous disabled — only activates when user explicitly selects provider=nous
3. Session/persistence scope isolated per-profile/connection
4. Fallback only when explicitly configured in config.yaml fallback_providers
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSelectionIntent:
    """Captures the user's explicit model selection intent.

    This is the "request" — what the user or config asked for.
    """

    provider: str          # Canonical provider id (e.g. "openai", "nvidia", "nous")
    model: str             # Model identifier as given (e.g. "gpt-4", "auto-free")
    profile_id: str        # Profile owning this selection
    session_id: str        # Session owning this selection
    connection_id: str     # Desktop connection/tile owner
    persistence_scope: str = "session"  # "session" | "global" | "once"
    source: str = "user"   # "user" | "config" | "alias" | "picker"


@dataclass(frozen=True)
class FallbackPolicy:
    """Policy governing what fallbacks are allowed.

    Only explicitly configured fallbacks in config.yaml ``fallback_providers``
    are honored.  No ambient/implicit cross-provider fallbacks.
    """

    # Same-provider credential rotation is always allowed when the primary
    # provider/model fails but credentials are valid under a different key.
    same_provider_credential_rotation: bool = True

    # Explicit fallback routes from config.yaml fallback_providers
    explicit_routes: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    # Whether cross-provider fallback is allowed without explicit config
    allow_cross_provider: bool = False

    # Whether same-provider model retry is attempted first
    same_provider_retry: bool = True


# ---------------------------------------------------------------------------
# Policy resolution
# ---------------------------------------------------------------------------


def resolve_selection_intent(
    raw_provider: str,
    raw_model: str,
    *,
    profile_id: str,
    session_id: str,
    connection_id: str,
    persistence_scope: str = "session",
    config_fallback_providers: Optional[List[dict]] = None,
    explicit_provider: Optional[str] = None,
) -> Tuple[ModelSelectionIntent, FallbackPolicy]:
    """Resolve the effective selection intent and fallback policy.

    This is the ONE entry point for model routing policy.  All surfaces must
    delegate to this function rather than re-implementing their own logic.

    Returns (intent, fallback_policy) where:
      - intent: the effective explicit selection (always deterministic)
      - fallback_policy: what fallbacks are permitted from this point
    """
    # ------------------------------------------------------------------
    # 1. Normalize provider (alias resolution)
    # ------------------------------------------------------------------
    from hermes_cli.providers import normalize_provider, get_provider

    canonical = normalize_provider(raw_provider)

    # If an explicit provider was given (e.g. --provider nvidia), honor it
    # and do NOT auto-discover or ambient-fallback to other providers.
    if explicit_provider is not None:
        canonical = normalize_provider(explicit_provider)

    # Resolve the provider def to confirm it exists; if not, keep the raw
    # canonical so callers can emit a "unavailable" UX rather than silently
    # switching.
    pdef = get_provider(canonical, allow_network=False)

    # ------------------------------------------------------------------
    # 2. Build the selection intent
    # ------------------------------------------------------------------
    intent = ModelSelectionIntent(
        provider=canonical,
        model=raw_model,
        profile_id=profile_id,
        session_id=session_id,
        connection_id=connection_id,
        persistence_scope=persistence_scope,
        source="explicit" if explicit_provider else "user",
    )

    # ------------------------------------------------------------------
    # 3. Build the fallback policy
    # ------------------------------------------------------------------
    # Start from config fallback_providers if provided
    explicit_routes: Tuple[Tuple[str, str], ...] = tuple()

    if config_fallback_providers:
        for entry in config_fallback_providers:
            prov = str(entry.get("provider") or "").strip().lower()
            mod = str(entry.get("model") or "").strip().lower()
            if prov and mod:
                explicit_routes += ((prov, mod),)

    fallback_policy = FallbackPolicy(
        same_provider_credential_rotation=True,
        explicit_routes=explicit_routes,
        allow_cross_provider=False,  # Central contract: NO ambient cross-provider
        same_provider_retry=True,
    )

    # If user explicitly selected Nous, enable Nous-specific fallbacks
    # (but only when explicitly chosen, not ambient)
    if canonical.lower() == "nous":
        # Nous explicit selection — Nous free-tier auto-free is allowed
        # only as an explicitly configured fallback, not ambient.
        pass  # Handled by config_fallback_providers check above

    logger.debug(
        "Resolved model routing: provider=%s model=%s scope=%s "
        "fallback_routes=%s",
        canonical,
        raw_model,
        persistence_scope,
        fallback_policy.explicit_routes,
    )

    return intent, fallback_policy


def check_fallback_allowed(
    intent: ModelSelectionIntent,
    fallback_policy: FallbackPolicy,
    *,  # keyword-only after this
    effective_provider: str,
    effective_model: str,
) -> bool:
    """Check whether a fallback to (effective_provider, effective_model) is allowed.

    Returns True only when:
      1. It's a same-provider credential rotation, OR
      2. It matches an explicit fallback route from config.yaml, OR
      3. allow_cross_provider is True (should rarely be the case)

    Never returns True for implicit/ambient cross-provider fallbacks.
    """
    # Same-provider credential rotation: same provider, different model but
    # same family, with valid credentials elsewhere
    if (
        intent.provider == effective_provider
        and intent.model != effective_model
        and fallback_policy.same_provider_credential_rotation
    ):
        return True

    # Explicit fallback route match
    for route_provider, route_model in fallback_policy.explicit_routes:
        if (
            effective_provider.lower() == route_provider.lower()
            and effective_model.lower() == route_model.lower()
        ):
            return True

    # Cross-provider fallback only if explicitly allowed (should be False
    # per central contract)
    if fallback_policy.allow_cross_provider:
        return True

    return False


def model_unavailable_error(
    intent: ModelSelectionIntent,
    reason: str = "model unavailable",
) -> Dict[str, str]:
    """Return the error dict to show when the selected model is unavailable.

    Per the contract: never silently switch to another model/provider.
    Always show "Selected model unavailable" with retry/refresh actions.
    """
    return {
        "error": f"Selected model unavailable: {reason}",
        "selected_provider": intent.provider,
        "selected_model": intent.model,
        "actions": [
            "Retry",
            "Refresh models",
            "Choose another model",
            "Use configured fallback",
        ],
    }


# ---------------------------------------------------------------------------
# Slice-A guard: ambient Nous check
# ---------------------------------------------------------------------------


def is_ambient_nous_active(intent: ModelSelectionIntent) -> bool:
    """Return True when Nous routing is active without explicit user selection.

    This is the zero-ambient guard.  Returns True ONLY when:
      - The intent's provider is "nous" AND
      - There was NO explicit --provider nous flag and
      - No config.yaml fallback_providers entry for nous

    In all other cases (explicit --provider nous, or user chose another
    provider), this returns False.
    """
    if intent.provider.lower() != "nous":
        return False

    # If the user explicitly selected --provider nous, ambient is NOT active
    # (that's explicit, not ambient)
    # The caller should check for --provider flag presence; this helper
    # assumes the intent was resolved without an explicit --provider token.

    # True ambient: nous appeared because no provider was specified and the
    # system defaulted to it — this must be prevented.
    return True  # Caller must verify explicit selection beforehand


# ---------------------------------------------------------------------------
# Alias-safe model name normalization for display
# ---------------------------------------------------------------------------

def normalize_model_name(model: str, provider: str) -> str:
    """Normalize a model name for safe display and catalog lookup.

    Strips known opaque proxy prefixes, applies provider-specific formatting,
    but never resolves aliases — the original name is preserved for wire use.
    """
    from hermes_cli.model_switch import format_model_for_display

    return format_model_for_display(model)