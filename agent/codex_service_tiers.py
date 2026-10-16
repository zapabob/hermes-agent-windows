"""Account-scoped service-tier negotiation for official Codex requests."""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)
_CATALOG_TTL = 3600
_MAX_CATALOGS = 128
# Cache only model tier ids under the existing non-secret token fingerprint.
_catalogs: dict[str, tuple[dict[str, frozenset[str]], float]] = {}


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
    """Keep only advertised tier ids; never retain tokens or whole catalog rows."""
    if not cache_key or not isinstance(entries, list):
        return
    models: dict[str, frozenset[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            continue
        tiers = _advertised_tiers(entry)
        if tiers is not None:
            models[slug.strip().lower()] = tiers
    if cache_key not in _catalogs and len(_catalogs) >= _MAX_CATALOGS:
        oldest = min(_catalogs, key=lambda key: _catalogs[key][1])
        del _catalogs[oldest]
    _catalogs[cache_key] = (models, time.time())


def _tiers_for_model(access_token: str, model: str) -> frozenset[str] | None:
    from agent import model_metadata

    cache_key = model_metadata._codex_oauth_token_fingerprint(access_token)
    cached = _catalogs.get(cache_key)
    now = time.time()
    if cached is None or now - cached[1] >= _CATALOG_TTL:
        # Reuse the existing authenticated /models probe. Its successful fetch
        # records tier ids through remember_catalog; failures remain unknown.
        model_metadata._fetch_codex_oauth_context_lengths_with_source(
            access_token,
            refresh_catalog=True,
        )
        cached = _catalogs.get(cache_key)
        now = time.time()
    if cached is None or now - cached[1] >= _CATALOG_TTL:
        return None

    slug = model_metadata._bare_codex_slug(
        model_metadata.strip_codex_context_variant_suffix(model)
    ).lower()
    return cached[0].get(slug)


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
