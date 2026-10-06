from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.routing import Mount, Route
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response

from . import oauth_auth


def build_oauth_http_app(mcp_app: Any, state: oauth_auth.OAuthState) -> Any:
    """Expose OAuth discovery/authorization routes around the MCP ASGI app."""

    async def resource_metadata(request: Request) -> JSONResponse:
        return oauth_auth.protected_resource_metadata(request, state)

    async def authorization_metadata(request: Request) -> JSONResponse:
        return oauth_auth.authorization_metadata(request, state)

    async def authorize(request: Request) -> Response:
        return oauth_auth.authorize(request, state)

    async def token(request: Request) -> JSONResponse:
        return await oauth_auth.token(request, state)

    routes = [
        Route("/.well-known/oauth-protected-resource", resource_metadata, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource/mcp", resource_metadata, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", authorization_metadata, methods=["GET"]),
        Route("/oauth/authorize", authorize, methods=["GET"]),
        Route("/oauth/token", token, methods=["POST"]),
        Mount("/", app=oauth_auth.DefaultMcpAcceptMiddleware(mcp_app)),
    ]
    lifespan = getattr(getattr(mcp_app, "router", None), "lifespan_context", None)
    app = Starlette(routes=routes, lifespan=lifespan)
    issuer = urlparse(state.config.issuer)
    origins = ["https://chatgpt.com"]
    if issuer.scheme and issuer.netloc:
        origins.append(f"{issuer.scheme}://{issuer.netloc}")
    return CORSMiddleware(
        oauth_auth.BearerAuthMiddleware(app, state),
        allow_origins=list(dict.fromkeys(origins)),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        max_age=86400,
    )
