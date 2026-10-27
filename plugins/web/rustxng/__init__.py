"""RustXNG search plugin — bundled, auto-loaded.

Backed by a user-hosted RustXNG instance (URL configured via ``RUSTXNG_URL``).
Search-only — pair with an extract provider (firecrawl/tavily/exa) for
``web_extract`` calls.

RustXNG is a SearXNG-compatible metasearch engine written in Rust.
API-compatible with SearXNG: same /search?format=json endpoint and response shape.
"""

from __future__ import annotations

from plugins.web.rustxng.provider import RustXNGWebSearchProvider


def register(ctx) -> None:
    """Register the RustXNG provider with the plugin context."""
    ctx.register_web_search_provider(RustXNGWebSearchProvider())