"""Account-scoped speed and Daybreak capabilities for official Codex requests."""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)
_CATALOG_TTL = 3600
_MAX_CATALOGS = 128
# Publish tiers, timestamp and programs together: a refresh must not pair a
# fresh timestamp with an older account entitlement. No raw tokens are retained.
_catalogs: dict[str, tuple[dict[str, frozenset[str]], float, dict[str, frozenset[str]]]] = {}
DAYBREAK_PROGRAM = "daybreak_blue"


def _advertised_tiers(entry: dict[str, Any]) -> frozenset[str] | None:
    tiers = entry.get("service_tiers")
    if isinstance(tiers, list):
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in tiers):
            return None
        if tiers:
            return frozenset(item["id"] for item in tiers)
    speeds = entry.get("additional_speed_tiers")
    if isinstance(speeds, list) and all(isinstance(item, str) for item in speeds):
        return frozenset({"fast": "priority"}.get(item, item) for item in speeds)
    return frozenset() if tiers == [] else None


def remember_catalog(cache_key: str, entries: list[Any]) -> None:
    """Keep advertised tiers and access programs, not tokens or whole catalog rows."""
    if not cache_key or not isinstance(entries, list):
        return
    models: dict[str, frozenset[str]] = {}
    programs: dict[str, frozenset[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            continue
        tiers = _advertised_tiers(entry)
        if tiers is not None:
            models[slug.strip().lower()] = tiers
        advertised = entry.get("available_access_programs")
        cyber = advertised.get("cyber") if isinstance(advertised, dict) else None
        if isinstance(cyber, list) and all(isinstance(item, str) for item in cyber):
            programs[slug.strip().lower()] = frozenset(cyber)
    if cache_key not in _catalogs and len(_catalogs) >= _MAX_CATALOGS:
        oldest = min(_catalogs, key=lambda key: _catalogs[key][1])
        del _catalogs[oldest]
    _catalogs[cache_key] = (models, time.time(), programs)


def _fresh_catalog(access_token: str, *, allow_network: bool = True) -> tuple | None:
    from agent import model_metadata

    cache_key = model_metadata._codex_oauth_token_fingerprint(access_token)
    cached = _catalogs.get(cache_key)
    now = time.time()
    if cached is None or now - cached[1] >= _CATALOG_TTL:
        if not allow_network:
            return None
        # Reuse the existing authenticated /models probe. Its successful fetch
        # records tier ids through remember_catalog; failures remain unknown.
        try:
            model_metadata._fetch_codex_oauth_context_lengths_with_source(
                access_token,
                refresh_catalog=True,
            )
        except Exception:
            logger.debug("Codex capability catalog is unavailable", exc_info=True)
            return None
        cached = _catalogs.get(cache_key)
        now = time.time()
    if cached is None or now - cached[1] >= _CATALOG_TTL:
        return None
    return cached


def _catalog_slug(model: str) -> str:
    from agent import model_metadata

    return model_metadata._bare_codex_slug(
        model_metadata.strip_codex_context_variant_suffix(model)
    ).lower()


def _tiers_for_model(access_token: str, model: str) -> frozenset[str] | None:
    cached = _fresh_catalog(access_token)
    return None if cached is None else cached[0].get(_catalog_slug(model))


def _cyber_programs_for_model(
    access_token: str, model: str, *, allow_network: bool = True,
) -> frozenset[str] | None:
    cached = _fresh_catalog(access_token, allow_network=allow_network)
    return None if cached is None else cached[2].get(_catalog_slug(model))


def _account_catalog_token(access_token: Any = None) -> str | None:
    """Read this profile's stored account credential without refresh or CLI import."""
    from agent import model_metadata
    from hermes_cli.auth import _codex_access_token_is_expiring

    token = access_token
    if token is None:
        from hermes_cli.auth import _load_auth_store, _pool_codex_access_token

        try:
            # Read the active profile's own store. The normal runtime resolver
            # may inherit a global-root login; that fallback is not proof that
            # this profile's picker is using the same entitled account.
            store = _load_auth_store()
            providers = store.get("providers")
            state = providers.get("openai-codex") if isinstance(providers, dict) else None
            tokens = state.get("tokens") if isinstance(state, dict) else None
            token = tokens.get("access_token") if isinstance(tokens, dict) else None
            if not token:
                token = _pool_codex_access_token()
        except Exception:
            return None
    if (not isinstance(token, str) or not token
            or not model_metadata._extract_chatgpt_account_id(token)
            or _codex_access_token_is_expiring(token, 0)):
        return None
    return token


def daybreak_offered(
    model: Any, *, provider: Any = None, base_url: Any = None,
    access_token: Any = None, allow_network: bool = True,
) -> bool:
    """Offer Daybreak only for an explicit account-catalog listing on Codex.

    Cold model pickers pass ``allow_network=False`` and remain bounded. Missing,
    expired or unreadable metadata hides the switch; no synthetic slug grants it.
    """
    from agent.auxiliary_client import _CODEX_AUX_BASE_URL, _is_official_codex_base_url
    from hermes_cli.model_switch import _scoped_key_env
    from hermes_cli.models import normalize_provider

    if not provider or normalize_provider(provider) != "openai-codex":
        return False
    base = str(base_url or "").strip() or _scoped_key_env("HERMES_CODEX_BASE_URL") or _CODEX_AUX_BASE_URL
    if not _is_official_codex_base_url(base):
        return False
    token = _account_catalog_token(access_token)
    if token is None:
        return False
    programs = _cyber_programs_for_model(token, str(model or ""), allow_network=allow_network)
    return programs is not None and DAYBREAK_PROGRAM in programs


def apply_daybreak(agent: Any, overrides: dict[str, Any]) -> None:
    """Add Daybreak to this request, preserving the user's saved override mapping."""
    if (getattr(agent, "daybreak", False) is not True
            or getattr(agent, "api_mode", None) != "codex_responses"
            or getattr(agent, "provider", None) != "openai-codex"):
        return
    token = getattr(agent, "api_key", None)
    base = getattr(agent, "base_url", None)
    # A request must use its selected credential and route, never fall back to a
    # different account from the profile when either is absent.
    if not isinstance(token, str) or not token or not base:
        return
    if not daybreak_offered(
        overrides.get("model", getattr(agent, "model", "")),
        provider=agent.provider, base_url=base, access_token=token,
    ):
        return
    extra_body = dict(overrides.get("extra_body") or {})
    extra_body["access_programs"] = {
        **dict(extra_body.get("access_programs") or {}), "cyber": DAYBREAK_PROGRAM,
    }
    overrides["extra_body"] = extra_body


def negotiate_request_tier(agent: Any, overrides: dict[str, Any]) -> None:
    """Clamp a requested tier only when the selected OAuth account proves its cap."""
    requested = overrides.get("service_tier")
    if requested not in {"priority", "ultrafast"}:
        return
    if (
        getattr(agent, "api_mode", None) != "codex_responses"
        or getattr(agent, "provider", None) != "openai-codex"
    ):
        return

    base_url = getattr(agent, "base_url", "")
    try:
        from agent.auxiliary_client import _is_official_codex_base_url
        if not _is_official_codex_base_url(base_url):
            return
    except Exception:
        # An unavailable route guard must not make a request or block a turn.
        return

    access_token = getattr(agent, "api_key", None)
    if not isinstance(access_token, str) or not access_token:
        return
    from agent import model_metadata
    if not model_metadata._extract_chatgpt_account_id(access_token):
        return

    model = overrides.get("model", getattr(agent, "model", ""))
    supported = _tiers_for_model(access_token, str(model or ""))
    if supported is None:
        return

    candidates = ("ultrafast", "priority") if requested == "ultrafast" else ("priority",)
    effective = next((tier for tier in candidates if tier in supported), None)
    if effective is None:
        overrides.pop("service_tier", None)
    else:
        overrides["service_tier"] = effective
    if effective != requested:
        logger.debug(
            "Codex service tier %s -> %s: not advertised for selected credential",
            requested,
            effective or "default",
        )
