"""Remote model catalog fetcher.

The Hermes docs site hosts a JSON manifest of curated models for providers
we want to update without shipping a release (currently OpenRouter and
Nous Portal). This module fetches, validates, and caches that manifest,
falling back to the in-repo hardcoded lists when the network is unavailable.

Pipeline
--------
1. ``get_catalog()`` — returns a parsed manifest dict.
   - Checks in-process cache (invalidated by TTL).
   - Reads disk cache at ``~/.hermes/cache/model_catalog.json``.
   - Fetches the master URL if disk cache is stale or missing.
   - On any fetch failure, keeps using the stale cache (or empty dict).

2. ``get_curated_openrouter_models()`` / ``get_curated_nous_models()`` —
   thin accessors returning the shapes existing callers expect. Each
   falls back to the in-repo hardcoded list on any lookup failure.

Schema (version 1)
------------------
::

    {
      "version": 1,
      "updated_at": "2026-04-25T22:00:00Z",
      "metadata": {...},                # free-form
      "providers": {
        "openrouter": {
          "metadata": {...},            # free-form
          "models": [
            {"id": "vendor/model", "description": "recommended",
             "metadata": {...}}          # free-form, model-level
          ]
        },
        "nous": {...}
      }
    }

Unknown fields are ignored — extra metadata can be added at either level
without bumping ``version``. ``version`` bumps are reserved for
breaking changes (renaming ``providers``, changing ``models`` shape).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_cli import __version__ as _HERMES_VERSION
from utils import atomic_replace

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical Normalized Catalog Data Models
# ---------------------------------------------------------------------------

@dataclass
class NormalizedModel:
    """Canonical model entry in a normalized catalog."""

    id: str
    name: str = ""
    description: str = ""
    default: bool = False
    reasoning: bool = False
    tool_call: bool = False
    attachment: bool = False
    modalities: dict[str, list[str]] = field(default_factory=dict)
    context: int = 0
    max_output: int = 0
    release_date: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "default": self.default,
            "reasoning": self.reasoning,
            "tool_call": self.tool_call,
            "attachment": self.attachment,
            "modalities": self.modalities,
            "context": self.context,
            "max_output": self.max_output,
            "release_date": self.release_date,
            "metadata": self.metadata,
            "capabilities": self.capabilities,
        }


@dataclass
class NormalizedProvider:
    """Canonical provider entry in a normalized catalog."""

    id: str
    name: str = ""
    models: list[NormalizedModel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "metadata": self.metadata,
            "models": [m.to_dict() for m in self.models],
        }


@dataclass
class NormalizedCatalog:
    """Canonical normalized model catalog."""

    providers: dict[str, NormalizedProvider] = field(default_factory=dict)
    version: int = 1
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    source_format: str = "models_dev"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "providers": {k: v.to_dict() for k, v in self.providers.items()},
        }


# ---------------------------------------------------------------------------
# Source Adapters
# ---------------------------------------------------------------------------

def parse_models_dev(raw_data: Any) -> NormalizedCatalog | None:
    """Source adapter for models.dev (https://models.dev/api.json).

    Expects a mapping of provider IDs to provider objects containing model
    mappings or lists. Fails closed (returns None) on malformed or empty payloads.
    """
    if not isinstance(raw_data, dict) or not raw_data:
        return None

    # If it's a legacy schema mistakenly passed here, don't parse as models.dev
    if "version" in raw_data and "providers" in raw_data and isinstance(raw_data.get("providers"), dict):
        return None

    providers: dict[str, NormalizedProvider] = {}

    for pkey, pval in raw_data.items():
        if not isinstance(pkey, str) or not isinstance(pval, dict):
            return None
        pid = str(pval.get("id") or pkey).strip()
        pname = str(pval.get("name") or pid).strip()
        models_raw = pval.get("models")
        if not isinstance(models_raw, (dict, list)):
            return None

        norm_models: list[NormalizedModel] = []
        if isinstance(models_raw, dict):
            model_items = list(models_raw.items())
        else:
            model_items = [(m.get("id", ""), m) for m in models_raw if isinstance(m, dict)]

        for mkey, mval in model_items:
            if not isinstance(mval, dict):
                return None
            mid = mval.get("id") or mkey
            if not isinstance(mid, str) or not mid.strip():
                return None

            limit = mval.get("limit") if isinstance(mval.get("limit"), dict) else {}
            ctx = int(limit.get("context") or mval.get("context") or 0)
            max_out = int(limit.get("output") or mval.get("max_output") or 0)

            mods = mval.get("modalities")
            if not isinstance(mods, dict):
                mods = {"input": list(mods)} if isinstance(mods, (list, tuple)) else {}

            norm_models.append(
                NormalizedModel(
                    id=mid.strip(),
                    name=str(mval.get("name") or mid),
                    description=str(mval.get("description") or ""),
                    default=bool(mval.get("default", False)),
                    reasoning=bool(mval.get("reasoning", False)),
                    tool_call=bool(mval.get("tool_call", False) or mval.get("tools", False)),
                    attachment=bool(mval.get("attachment", False) or mval.get("vision", False)),
                    modalities=mods,
                    context=ctx,
                    max_output=max_out,
                    release_date=str(mval.get("release_date") or ""),
                    metadata=mval.get("metadata") if isinstance(mval.get("metadata"), dict) else {},
                    capabilities=mval.get("capabilities") if isinstance(mval.get("capabilities"), dict) else {},
                )
            )

        if norm_models:
            providers[pid] = NormalizedProvider(
                id=pid,
                name=pname,
                models=norm_models,
                metadata=pval.get("metadata") if isinstance(pval.get("metadata"), dict) else {},
            )

    if not providers:
        return None

    return NormalizedCatalog(providers=providers, source_format="models_dev")


def parse_legacy_hermes_catalog(raw_data: Any) -> NormalizedCatalog | None:
    """Source adapter for legacy Hermes manifest format (version 1)."""
    if not isinstance(raw_data, dict) or not raw_data:
        return None

    version = raw_data.get("version")
    if not isinstance(version, int) or version > SUPPORTED_SCHEMA_VERSION:
        return None

    providers_raw = raw_data.get("providers")
    if not isinstance(providers_raw, dict) or not providers_raw:
        return None

    providers: dict[str, NormalizedProvider] = {}

    for pid, pval in providers_raw.items():
        if not isinstance(pid, str) or not isinstance(pval, dict):
            return None
        models_raw = pval.get("models")
        if not isinstance(models_raw, list):
            return None

        norm_models: list[NormalizedModel] = []
        for m in models_raw:
            if not isinstance(m, dict):
                return None
            mid = m.get("id")
            if not isinstance(mid, str) or not mid.strip():
                return None

            limit = m.get("limit") if isinstance(m.get("limit"), dict) else {}
            ctx = int(limit.get("context") or m.get("context") or 0)
            max_out = int(limit.get("output") or m.get("max_output") or 0)
            mods = m.get("modalities")
            if not isinstance(mods, dict):
                mods = {"input": list(mods)} if isinstance(mods, (list, tuple)) else {}

            norm_models.append(
                NormalizedModel(
                    id=mid.strip(),
                    name=str(m.get("name") or mid),
                    description=str(m.get("description") or ""),
                    default=bool(m.get("default", False)),
                    reasoning=bool(m.get("reasoning", False)),
                    tool_call=bool(m.get("tool_call", False) or m.get("tools", False)),
                    attachment=bool(m.get("attachment", False) or m.get("vision", False)),
                    modalities=mods,
                    context=ctx,
                    max_output=max_out,
                    release_date=str(m.get("release_date") or ""),
                    metadata=m.get("metadata") if isinstance(m.get("metadata"), dict) else {},
                    capabilities=m.get("capabilities") if isinstance(m.get("capabilities"), dict) else {},
                )
            )

        if norm_models:
            meta = pval.get("metadata") if isinstance(pval.get("metadata"), dict) else {}
            pname = str(pval.get("name") or meta.get("display_name") or pid)
            providers[pid] = NormalizedProvider(id=pid, name=pname, models=norm_models, metadata=meta)

    if not providers:
        return None

    return NormalizedCatalog(
        providers=providers,
        version=int(raw_data.get("version", 1)),
        updated_at=str(raw_data.get("updated_at", "")),
        metadata=raw_data.get("metadata") if isinstance(raw_data.get("metadata"), dict) else {},
        source_format="legacy",
    )


def detect_and_parse_catalog(raw_data: Any) -> NormalizedCatalog | None:
    """Detect schema type (models.dev or legacy) and return NormalizedCatalog."""
    if not isinstance(raw_data, dict) or not raw_data:
        return None
    if "version" in raw_data and "providers" in raw_data and isinstance(raw_data.get("providers"), dict):
        return parse_legacy_hermes_catalog(raw_data)
    return parse_models_dev(raw_data)


def get_static_fallback_catalog() -> dict[str, Any]:
    """In-repo minimal static catalog fallback when both network and cache are unavailable."""
    return {
        "version": 1,
        "updated_at": "static-fallback",
        "metadata": {"source": "in-repo static fallback"},
        "providers": {
            "openrouter": {
                "id": "openrouter",
                "name": "OpenRouter",
                "metadata": {"display_name": "OpenRouter"},
                "models": [
                    {
                        "id": "anthropic/claude-sonnet-4-6",
                        "name": "Claude Sonnet 4.6",
                        "description": "curated default",
                        "default": True,
                        "tool_call": True,
                        "reasoning": True,
                    },
                    {
                        "id": "openai/gpt-5",
                        "name": "GPT-5",
                        "description": "curated flagship",
                        "default": False,
                        "tool_call": True,
                        "reasoning": True,
                    },
                ],
            },
            "anthropic": {
                "id": "anthropic",
                "name": "Anthropic",
                "metadata": {"display_name": "Anthropic"},
                "models": [
                    {
                        "id": "claude-sonnet-4-6",
                        "name": "Claude Sonnet 4.6",
                        "description": "default",
                        "default": True,
                        "tool_call": True,
                        "reasoning": True,
                    },
                ],
            },
        },
    }


def _get_static_fallback_catalog() -> dict[str, Any]:
    return get_static_fallback_catalog()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CATALOG_URL = "https://models.dev/api.json"
DEFAULT_CATALOG_FALLBACK_URLS: tuple[str, ...] = (
    "https://raw.githubusercontent.com/models-dev/models/main/api.json",
)
NOUS_CATALOG_URL = (
    "https://hermes-agent.nousresearch.com/docs/api/model-catalog.json"
)
NOUS_CATALOG_FALLBACK_URLS: tuple[str, ...] = (
    "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/static/api/model-catalog.json",
)
DEFAULT_TTL_HOURS = 4
DEFAULT_FETCH_TIMEOUT = 8.0
SUPPORTED_SCHEMA_VERSION = 1

_HERMES_USER_AGENT = f"hermes-cli/{_HERMES_VERSION}"

# In-process cache to avoid repeated disk + parse work across multiple
# calls within the same session. Invalidated by TTL against the disk file's
# mtime, so calling code never has to think about this.
_catalog_cache: dict[str, Any] | None = None
_catalog_cache_source_mtime: float = 0.0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_catalog_config() -> dict[str, Any]:
    """Load the ``model_catalog`` config block with defaults filled in."""
    try:
        from hermes_cli.config import load_config
        cfg = load_config() or {}
    except Exception:
        cfg = {}

    raw = cfg.get("model_catalog")
    if not isinstance(raw, dict):
        raw = {}

    return {
        "enabled": bool(raw.get("enabled", True)),
        "url": str(raw.get("url") or DEFAULT_CATALOG_URL),
        "ttl_hours": float(raw.get("ttl_hours") or DEFAULT_TTL_HOURS),
        "providers": raw.get("providers") if isinstance(raw.get("providers"), dict) else {},
    }


def openrouter_free_route_refresh_enabled(hermes_home: Path | None = None) -> bool:
    """Return true only for an explicit OpenRouter metadata-refresh opt-in.

    The general model picker catalogue is enabled by default, so it is not an
    adequate approval signal for a new background provider request. A profile
    must set ``model_catalog.providers.openrouter.free_route_catalogue_enabled``
    to the boolean ``true`` before a host may refresh this public metadata. A
    host supplies its captured profile home so later checks do not follow an
    unrelated active profile in the same process.
    """
    if hermes_home is None:
        config = _load_catalog_config()
    else:
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        home_token = set_hermes_home_override(hermes_home)
        try:
            config = _load_catalog_config()
        finally:
            reset_hermes_home_override(home_token)
    providers = config.get("providers")
    provider = providers.get("openrouter") if isinstance(providers, dict) else None
    return (
        config.get("enabled") is True
        and isinstance(provider, dict)
        and provider.get("free_route_catalogue_enabled") is True
    )


def _cache_path() -> Path:
    """Return the disk cache path. Import lazily so tests can monkeypatch home."""
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "cache" / "model_catalog.json"


def free_route_cache_path() -> Path:
    """Return the profile-scoped last-good free-route catalogue cache path.

    The route projection is derived from the provider's canonical model
    catalogue, but its price evidence has a different twelve-hour freshness
    contract and must not be folded into the curated manifest or refreshed on
    that manifest's four-hour picker cadence.
    """
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "cache" / "model_catalog_free_routes.json"


def get_cached_curated_openrouter_model_ids() -> frozenset[str]:
    """Return the approved OpenRouter ids without starting a catalogue fetch.

    The free-route refresher is a host lifecycle task and must not turn a
    pricing read into a second request to the four-hour curated-manifest
    service. It uses the in-process/disk manifest when present and Hermes'
    existing static picker list otherwise. A disabled model catalogue yields
    no ids, which keeps the provider fetch disabled as well.
    """
    if not _load_catalog_config()["enabled"]:
        return frozenset()

    # Always resolve against the active profile's path. `_catalog_cache` is a
    # process-global picker cache and may have been populated while another
    # profile was active in the same Desktop/Gateway process.
    catalog, _mtime = _read_disk_cache()
    if isinstance(catalog, dict):
        providers = catalog.get("providers")
        block = providers.get("openrouter") if isinstance(providers, dict) else None
        if isinstance(block, dict):
            models = block.get("models")
            if isinstance(models, list):
                ids = {
                    entry.get("id", "").strip()
                    for entry in models
                    if isinstance(entry, dict)
                    and isinstance(entry.get("id"), str)
                    and entry["id"].strip()
                    and len(entry["id"].strip()) <= 512
                }
                if ids:
                    return frozenset(ids)

    # This is the same compiled-in fallback used by the existing picker. The
    # import is intentionally local to avoid a module-level cycle.
    try:
        from hermes_cli.models import OPENROUTER_MODELS

        return frozenset(
            model_id
            for model_id, _description in OPENROUTER_MODELS
            if isinstance(model_id, str) and model_id.strip() == model_id and len(model_id) <= 512
        )
    except Exception:
        return frozenset()


# ---------------------------------------------------------------------------
# Fetch + validate + cache
# ---------------------------------------------------------------------------


def _fetch_manifest(url: str, timeout: float) -> dict[str, Any] | None:
    """HTTP GET the manifest URL and return a normalized dict, or None on failure."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": _HERMES_USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.info("model catalog fetch failed (%s): %s", url, exc)
        return None
    except Exception as exc:  # pragma: no cover — defensive
        logger.info("model catalog fetch errored (%s): %s", url, exc)
        return None

    norm = detect_and_parse_catalog(data)
    if norm is None:
        logger.info("model catalog at %s failed schema validation", url)
        return None

    return norm.to_dict()


def _fetch_manifest_with_fallback(
    primary_url: str,
    timeout: float,
    fallback_urls: tuple[str, ...] = DEFAULT_CATALOG_FALLBACK_URLS,
) -> dict[str, Any] | None:
    """Try ``primary_url`` first, then walk ``fallback_urls``.

    Returns the first manifest that fetches and validates, or None when
    every URL fails. Skips fallback URLs identical to the primary so an
    operator who configured the catalog URL to point at the raw GitHub
    copy doesn't double-fetch.
    """
    data = _fetch_manifest(primary_url, timeout)
    if data is not None:
        return data
    for url in fallback_urls:
        if not url or url == primary_url:
            continue
        data = _fetch_manifest(url, timeout)
        if data is not None:
            logger.info("model catalog primary URL failed; using fallback %s", url)
            return data
    return None


def _validate_manifest(data: Any) -> bool:
    """Return True when ``data`` can be parsed into a NormalizedCatalog."""
    if not isinstance(data, dict):
        return False
    norm = detect_and_parse_catalog(data)
    return norm is not None


def _read_disk_cache() -> tuple[dict[str, Any] | None, float]:
    """Return ``(data_or_none, mtime)``. mtime is 0 if file is missing.

    Always returns a canonicalized NormalizedCatalog dict shape. If the file
    on disk was in an unnormalized legacy format, automatically migrates the
    cache on read.
    """
    path = _cache_path()
    try:
        mtime = path.stat().st_mtime
    except (OSError, FileNotFoundError):
        return (None, 0.0)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return (None, 0.0)

    norm = detect_and_parse_catalog(data)
    if norm is None:
        return (None, 0.0)

    canonical_dict = norm.to_dict()
    # Migration: if disk content differed from canonical form, migrate on read
    if data != canonical_dict:
        _write_disk_cache(canonical_dict)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            pass

    return (canonical_dict, mtime)


def _write_disk_cache(data: dict[str, Any] | NormalizedCatalog) -> None:
    """Write catalog to disk cache atomically in canonical NormalizedCatalog shape.

    Fails closed: refuses to persist any unparseable or non-canonical payload.
    """
    if isinstance(data, NormalizedCatalog):
        canonical_dict = data.to_dict()
    elif isinstance(data, dict):
        norm = detect_and_parse_catalog(data)
        if norm is None:
            logger.warning("refusing to write non-canonical or unparseable catalog payload to disk")
            return
        canonical_dict = norm.to_dict()
    else:
        logger.warning("refusing to write invalid non-dict payload to disk")
        return

    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}_{threading.get_ident()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(canonical_dict, fh, indent=2)
            fh.write("\n")
        atomic_replace(tmp, path)
    except OSError as exc:
        logger.info("model catalog cache write failed: %s", exc)


# Stale-while-revalidate machinery: at most one background manifest refresh
# in flight per process. The refreshed manifest lands on disk; the NEXT
# get_catalog() call picks it up via the mtime check.
_catalog_swr_lock = threading.Lock()
_catalog_swr_inflight = False


def _spawn_catalog_swr_refresh(url: str) -> None:
    """Refresh the catalog manifest off-thread (fire-and-forget, deduped)."""
    global _catalog_swr_inflight
    with _catalog_swr_lock:
        if _catalog_swr_inflight:
            return
        _catalog_swr_inflight = True

    def _refresh() -> None:
        global _catalog_swr_inflight
        try:
            fetched = _fetch_manifest_with_fallback(url, DEFAULT_FETCH_TIMEOUT)
            if fetched is not None:
                _write_disk_cache(fetched)
        except Exception:
            logger.debug("catalog SWR refresh failed", exc_info=True)
        finally:
            with _catalog_swr_lock:
                _catalog_swr_inflight = False

    threading.Thread(target=_refresh, daemon=True, name="model-catalog-swr").start()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_catalog(*, force_refresh: bool = False, fallback_to_static: bool = False) -> dict[str, Any]:
    """Return the parsed model catalog manifest, or an empty dict on failure.

    Callers should treat a missing provider/model as "use the in-repo fallback"
    — never raise from this function so the CLI keeps working offline.
    If ``fallback_to_static=True``, returns the in-repo static fallback catalog
    when both network and disk cache are unavailable.
    """
    global _catalog_cache, _catalog_cache_source_mtime

    cfg = _load_catalog_config()
    if not cfg["enabled"]:
        return {}

    ttl_seconds = max(0.0, cfg["ttl_hours"] * 3600.0)

    disk_data, disk_mtime = _read_disk_cache()
    now = time.time()
    disk_fresh = disk_data is not None and (now - disk_mtime) < ttl_seconds

    # In-process cache hit: disk hasn't changed since we loaded it and still fresh.
    if (
        not force_refresh
        and _catalog_cache is not None
        and disk_data is not None
        and disk_mtime == _catalog_cache_source_mtime
        and disk_fresh
    ):
        return _catalog_cache

    # Disk is fresh enough — use it without a network hit.
    if not force_refresh and disk_fresh and disk_data is not None:
        _catalog_cache = disk_data
        _catalog_cache_source_mtime = disk_mtime
        return disk_data

    # Stale-while-revalidate: an expired disk copy is served immediately and
    # refreshed off-thread, so interactive surfaces (the /model picker calls
    # this via get_curated_nous_model_ids on every open) never block on the
    # manifest fetch. Only a cold cache (no disk copy at all) still blocks.
    if not force_refresh and disk_data is not None:
        _catalog_cache = disk_data
        _catalog_cache_source_mtime = disk_mtime
        _spawn_catalog_swr_refresh(cfg["url"])
        return disk_data

    # Need to (re)fetch. If it fails, fall back to any stale disk copy.
    fetched = _fetch_manifest_with_fallback(cfg["url"], DEFAULT_FETCH_TIMEOUT)
    if fetched is not None:
        _write_disk_cache(fetched)
        new_disk_data, new_mtime = _read_disk_cache()
        if new_disk_data is not None:
            _catalog_cache = new_disk_data
            _catalog_cache_source_mtime = new_mtime
            return new_disk_data
        _catalog_cache = fetched
        _catalog_cache_source_mtime = now
        return fetched

    if disk_data is not None:
        _catalog_cache = disk_data
        _catalog_cache_source_mtime = disk_mtime
        return disk_data

    if fallback_to_static:
        fallback = _get_static_fallback_catalog()
        _catalog_cache = fallback
        _catalog_cache_source_mtime = now
        return fallback

    return {}


def _fetch_provider_override(provider: str) -> dict[str, Any] | None:
    """If ``model_catalog.providers.<name>.url`` is set, fetch that instead."""
    cfg = _load_catalog_config()
    if not cfg["enabled"]:
        return None
    provider_cfg = cfg["providers"].get(provider)
    if not isinstance(provider_cfg, dict):
        return None
    override_url = provider_cfg.get("url")
    if not isinstance(override_url, str) or not override_url.strip():
        return None
    # Override fetches skip the disk cache because they're usually
    # third-party self-hosted. Re-request on every call but with a short
    # timeout so they don't block the picker.
    return _fetch_manifest(override_url.strip(), DEFAULT_FETCH_TIMEOUT)


def _get_provider_block(provider: str) -> dict[str, Any] | None:
    """Return the provider's manifest block, respecting per-provider overrides."""
    override = _fetch_provider_override(provider)
    if override is not None:
        block = override.get("providers", {}).get(provider)
        if isinstance(block, dict):
            return block

    catalog = get_catalog()
    if not catalog:
        return None
    block = catalog.get("providers", {}).get(provider)
    return block if isinstance(block, dict) else None


def get_curated_openrouter_models() -> list[tuple[str, str]] | None:
    """Return OpenRouter's curated ``[(id, description), ...]`` from the manifest.

    Returns ``None`` when the manifest is unavailable, so callers can fall
    back to their hardcoded list.
    """
    block = _get_provider_block("openrouter")
    if not block:
        return None
    out: list[tuple[str, str]] = []
    for m in block.get("models", []):
        mid = str(m.get("id") or "").strip()
        if not mid:
            continue
        desc = str(m.get("description") or "")
        out.append((mid, desc))
    return out or None


def get_curated_nous_models() -> list[str] | None:
    """Return Nous Portal's curated list of model ids from the manifest.

    Returns ``None`` when the manifest is unavailable.
    """
    block = _get_provider_block("nous")
    if not block:
        return None
    out: list[str] = []
    for m in block.get("models", []):
        mid = str(m.get("id") or "").strip()
        if mid:
            out.append(mid)
    return out or None


def _default_model_from_block(block: dict[str, Any] | None) -> str | None:
    """Return the id of the model entry labeled ``"default": true``, or None."""
    if not isinstance(block, dict):
        return None
    for m in block.get("models", []):
        if isinstance(m, dict) and m.get("default"):
            mid = str(m.get("id") or "").strip()
            if mid:
                return mid
    return None


def get_default_model_from_cache(provider: str) -> str | None:
    """Return the catalog's labeled default model for ``provider`` — cache only.

    The manifest marks exactly one model entry per provider with
    ``"default": true``; that entry is the model Hermes silently lands on when
    the user never picked one. This accessor reads ONLY the in-process copy or
    the disk cache — it NEVER triggers a network fetch, so it is safe on hot
    resolution paths (agent build, gateway session setup) that must stay
    network-free. The cache is kept fresh by the picker/`hermes update` paths;
    when no cached manifest exists (fresh install, offline), returns None and
    the caller falls back to the in-repo constant.
    """
    if _catalog_cache is not None:
        block = _catalog_cache.get("providers", {}).get(provider)
        found = _default_model_from_block(block)
        if found:
            return found
    disk_data, _mtime = _read_disk_cache()
    if disk_data is not None:
        block = disk_data.get("providers", {}).get(provider)
        return _default_model_from_block(block)
    return None


def seed_cache_from_checkout(project_root: "Path | str") -> bool:
    """Overwrite the disk cache with the catalog shipped in a local checkout.

    ``hermes update`` pulls the latest repo, so the freshly-pulled
    ``website/static/api/model-catalog.json`` IS the newest catalog — no
    network round-trip needed. Copying it straight over the disk cache keeps
    the model picker current even when the remote manifest fetch is bot-gated
    or the Portal hiccups.

    Reads the shipped manifest, validates it against the schema, and writes it
    to ``~/.hermes/cache/model_catalog.json`` via the same atomic writer the
    network path uses. Returns ``True`` on success, ``False`` if the file is
    missing, malformed, or fails validation (caller should treat a ``False``
    as non-fatal — the network fetch path still applies on the next picker
    open).
    """
    src = Path(project_root) / "website" / "static" / "api" / "model-catalog.json"
    try:
        with open(src, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("model catalog seed from checkout skipped (%s): %s", src, exc)
        return False
    norm = detect_and_parse_catalog(data)
    if norm is None:
        logger.debug("model catalog seed from checkout skipped: invalid manifest at %s", src)
        return False
    _write_disk_cache(norm.to_dict())
    reset_cache()  # drop the in-process copy so the next read picks up the seed
    return True


def reset_cache() -> None:
    """Clear the in-process cache. Used by tests and ``hermes model --refresh``."""
    global _catalog_cache, _catalog_cache_source_mtime
    _catalog_cache = None
    _catalog_cache_source_mtime = 0.0
