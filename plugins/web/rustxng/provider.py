"""RustXNG search — plugin form.

Subclasses :class:`agent.web_search_provider.WebSearchProvider`. Same JSON
API call (``/search?format=json``), same result normalization as SearXNG.
RustXNG is a SearXNG-compatible metasearch engine written in Rust with
the same API surface.

Search-only — RustXNG aggregates results from upstream engines but does not
fetch/extract arbitrary URLs. ``supports_extract()`` returns False.

Config keys this provider responds to::

    web:
      search_backend: "rustxng"     # explicit per-capability
      backend: "rustxng"            # shared fallback

Env var::

    RUSTXNG_URL=http://localhost:8888
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


def _rustxng_url() -> str:
    """Return RUSTXNG_URL from Hermes config-aware env, falling back to process env."""
    try:
        from hermes_cli.config import get_env_value

        val = get_env_value("RUSTXNG_URL")
    except Exception:
        val = None
    if val is None:
        val = os.getenv("RUSTXNG_URL", "")
    return (val or "").strip()


class RustXNGWebSearchProvider(WebSearchProvider):
    """Search via a user-hosted RustXNG instance."""

    @property
    def name(self) -> str:
        return "rustxng"

    @property
    def display_name(self) -> str:
        return "RustXNG"

    def is_available(self) -> bool:
        """Return True when ``RUSTXNG_URL`` is set."""
        return bool(_rustxng_url())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Execute a search against the configured RustXNG instance."""
        import httpx

        base_url = _rustxng_url().rstrip("/")
        if not base_url:
            return {"success": False, "error": "RUSTXNG_URL is not set"}

        params: Dict[str, Any] = {
            "q": query,
            "format": "json",
            "pageno": 1,
        }

        try:
            resp = httpx.get(
                f"{base_url}/search",
                params=params,
                timeout=15,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("RustXNG HTTP error: %s", exc)
            status_code = getattr(exc.response, "status_code", "unknown")
            return {
                "success": False,
                "error": f"RustXNG returned HTTP {status_code}",
            }
        except httpx.RequestError as exc:
            logger.warning("RustXNG request error: %s", exc)
            return {
                "success": False,
                "error": f"Could not reach RustXNG at {base_url}: {exc}",
            }

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("RustXNG response parse error: %s", exc)
            return {
                "success": False,
                "error": "Could not parse RustXNG response as JSON",
            }

        raw_results = data.get("results", [])

        # RustXNG may return a score field; sort descending and cap to limit.
        sorted_results = sorted(
            raw_results,
            key=lambda r: float(r.get("score", 0)),
            reverse=True,
        )[:limit]

        web_results = [
            {
                "title": str(r.get("title", "")),
                "url": str(r.get("url", "")),
                "description": str(r.get("content", "")),
                "position": i + 1,
            }
            for i, r in enumerate(sorted_results)
        ]

        logger.info(
            "RustXNG search '%s': %d results (from %d raw, limit %d)",
            query,
            len(web_results),
            len(raw_results),
            limit,
        )

        return {"success": True, "data": {"web": web_results}}

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "RustXNG",
            "badge": "free · self-hosted",
            "tag": "SearXNG-compatible metasearch in Rust. Point RUSTXNG_URL at your instance.",
            "env_vars": [
                {
                    "key": "RUSTXNG_URL",
                    "prompt": "RustXNG instance URL (e.g. http://localhost:8888)",
                    "url": "https://github.com/zapabob/RustXNG",
                },
            ],
        }