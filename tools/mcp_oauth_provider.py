"""Shared ``OAuthClientProvider`` customizations for Hermes MCP OAuth.

Two code paths build an SDK provider — ``tools.mcp_oauth.build_oauth_auth`` (legacy public
API) and ``tools.mcp_oauth_manager.MCPOAuthManager`` — and both need the same real-world
fixes and config → constructor-kwargs plumbing. This module holds that core once; the origin
modules keep their own subclass (logger name, disk-watch hooks) on top of it.
"""

from __future__ import annotations

import logging
import contextvars
from contextlib import contextmanager, nullcontext
from functools import wraps
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.mcp_oauth import HermesTokenStorage
logger = logging.getLogger(__name__)
_active_commit = contextvars.ContextVar("mcp_oauth_commit", default=None)
_token_publication = contextvars.ContextVar("mcp_oauth_publication", default=None)


@contextmanager
def oauth_commit_scope(storage):
    capture = getattr(storage, "capture_commit", None)
    marker = _active_commit.set(capture() if callable(capture) else None)
    try:
        yield
    finally:
        _active_commit.reset(marker)


def oauth_response_guard(method):
    """Capture immutable ownership before parsing or awaiting a response."""
    @wraps(method)
    async def guarded(self, *args, **kwargs):
        storage = self.context.storage
        existing = _active_commit.get()
        if existing is not None and existing[0] is storage:
            return await method(self, *args, **kwargs)
        capture = getattr(storage, "capture_commit", None)
        token = _active_commit.set(capture() if callable(capture) else None)
        try:
            return await method(self, *args, **kwargs)
        finally:
            _active_commit.reset(token)
    return guarded


def oauth_flow_guard(method):
    """Carry one lease across SDK generator yields without leaking ContextVars."""
    @wraps(method)
    async def guarded(self, *args, **kwargs):
        storage = self.context.storage
        capture = getattr(storage, "capture_commit", None)
        operation = capture() if callable(capture) else None
        inner = method(self, *args, **kwargs)

        async def advance(action, *values):
            marker = _active_commit.set(operation)
            try:
                if operation is not None:
                    with storage._mutation_guard(check_token=False):
                        pass
                result = await action(*values)
                if operation is not None:
                    with storage._mutation_guard():
                        pass
                return result
            finally:
                _active_commit.reset(marker)

        try:
            outgoing = await advance(inner.__anext__)
            while True:
                incoming = yield outgoing
                outgoing = await advance(inner.asend, incoming)
        except StopAsyncIteration:
            return
        finally:
            # Always release the SDK context lock, including revoked/cancelled
            # operations; no ContextVar token remains installed across yield.
            await inner.aclose()
    return guarded


def publication_guard(storage):
    guard = getattr(storage, "_mutation_guard", None)
    return guard() if callable(guard) else nullcontext()


async def persist_provider_tokens(context: Any, token_response: Any) -> None:
    """Publish credentials only after storage has accepted and persisted them.

    Storage may reject a revoked configuration or fail an atomic replacement.
    Neither outcome authorizes publishing the candidate in the SDK context.
    """
    expires_in = getattr(token_response, "expires_in", None)
    # Preserve the response's expiry reference time even when storage is slow;
    # publishing later must not grant an additional storage-duration TTL.
    deadline = None if expires_in is None else time.time() + int(expires_in)
    published = False

    def publish():
        nonlocal published
        context.current_tokens = token_response
        context.update_token_expiry(token_response)
        context.token_expiry_time = deadline
        published = True

    marker = _token_publication.set((context.storage, publish))
    try:
        await context.storage.set_tokens(token_response)
        if not published:
            with publication_guard(context.storage):
                publish()
    finally:
        _token_publication.reset(marker)


class HermesProviderMixin:
    """Token-endpoint fixes layered over the SDK's ``OAuthClientProvider`` (must precede it in
    the MRO; subclasses set ``_hermes_logger`` to keep their own logger name).

    - Supabase-style dynamic registration returns a ``client_secret`` but omits
      ``token_endpoint_auth_method``; the SDK then treats the client as public and the token
      endpoint rejects the exchange (looping the browser page) — coerce ``client_secret_post``.
    - ``token_user_agent`` (``oauth.user_agent``) is stamped onto token-endpoint requests only
      (some authorization servers/WAFs reject httpx's default).
    - Any 2xx token/refresh response is accepted; token bodies never leak into errors/logs."""

    _hermes_logger: logging.Logger = logger

    @oauth_flow_guard
    def async_auth_flow(self, request):
        return super().async_auth_flow(request)

    def __init__(self, *args: Any, token_user_agent: str | None = None, oauth_flow: str = "browser", **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._hermes_oauth_flow = oauth_flow
        # oauth.user_agent — stamped onto token-endpoint requests only; some authorization servers/WAFs
        # reject httpx's default (#75576).
        self._hermes_token_user_agent = token_user_agent

    async def _perform_authorization(self):
        info = self.context.client_info
        grants = getattr(info, "grant_types", None) or []
        if (getattr(self, "_hermes_oauth_flow", "browser") == "device"
                or ("urn:ietf:params:oauth:grant-type:device_code" in grants and "authorization_code" not in grants)):
            from tools.mcp_oauth import OAuthNonInteractiveError
            raise OAuthNonInteractiveError(
                "MCP device authorization requires `hermes mcp login <server> --flow device`; "
                "background reconnects cannot start a device login")
        return await super()._perform_authorization()

    def _prepare_token_request(self, request):
        """Stamp the configured User-Agent onto a token/refresh request."""
        ua = getattr(self, "_hermes_token_user_agent", None)  # tests build via __new__
        if ua:
            request.headers["User-Agent"] = ua
        return request

    def _coerce_client_secret_post(self) -> None:
        """Same rule as ``HermesTokenStorage._coerce_secret_auth_method``, applied to the
        in-memory client info BEFORE the SDK builds a token-endpoint request from it."""
        info = self.context.client_info
        if not info:
            return
        from mcp.shared.auth import OAuthClientInformationFull
        from tools.mcp_oauth import HermesTokenStorage
        data = info.model_dump(mode="json", exclude_none=True)
        if hasattr(HermesTokenStorage, "_coerce_secret_auth_method") and HermesTokenStorage._coerce_secret_auth_method(data):
            self.context.client_info = OAuthClientInformationFull.model_validate(data)

    async def _exchange_token_authorization_code(self, *args: Any, **kwargs: Any):
        self._coerce_client_secret_post()
        return self._prepare_token_request(await super()._exchange_token_authorization_code(*args, **kwargs))

    async def _refresh_token(self):
        self._coerce_client_secret_post()
        return self._prepare_token_request(await super()._refresh_token())

    async def _initialize(self) -> None:
        """Load stored state, restore persisted server metadata, enforce issuer binding."""
        await super()._initialize()
        storage = self.context.storage
        from tools.mcp_oauth import HermesTokenStorage
        if isinstance(storage, HermesTokenStorage) and self.context.oauth_metadata is None:
            meta = storage.load_oauth_metadata()
            if meta is not None:
                self.context.oauth_metadata = meta
        enforce_refresh_token_issuer(self.context)

    async def _store_tokens(self, token_response) -> None:
        bind_issuer_from_context(self.context)
        await persist_provider_tokens(self.context, token_response)

    @oauth_response_guard
    async def _handle_token_response(self, response):
        """Accept any 2xx token response; never echo the body into errors."""
        from mcp.client.auth.oauth2 import OAuthTokenError
        if not (200 <= response.status_code < 300):
            raise OAuthTokenError(f"Token exchange failed ({response.status_code})")
        from httpx import HTTPError
        from mcp.client.auth.utils import handle_token_response_scopes
        try:
            token_response = await handle_token_response_scopes(response)
        except (HTTPError, OAuthTokenError):
            raise OAuthTokenError("Invalid token response") from None
        await self._store_tokens(token_response)

    @oauth_response_guard
    async def _handle_refresh_response(self, response) -> bool:
        """Accept any 2xx refresh response; never log the body."""
        if not (200 <= response.status_code < 300):
            self._hermes_logger.warning("Token refresh failed: %s", response.status_code)
            with publication_guard(self.context.storage):
                self.context.clear_tokens()
            return False
        from httpx import HTTPError
        from mcp.shared.auth import OAuthToken
        from pydantic import ValidationError
        try:
            token_response = OAuthToken.model_validate_json(await response.aread())
        except (HTTPError, ValidationError):
            self._hermes_logger.warning("Invalid refresh response: %s", response.status_code)
            with publication_guard(self.context.storage):
                self.context.clear_tokens()
            return False
        # RFC 6749 §6: a refresh response may omit refresh_token / scope.
        prior = self.context.current_tokens
        if prior is not None:
            if token_response.refresh_token is None:
                token_response.refresh_token = prior.refresh_token
            if token_response.scope is None:
                token_response.scope = prior.scope
        await self._store_tokens(token_response)
        return True


def _metadata_issuer(context: Any) -> str | None:
    """Discovered authorization-server issuer, without trailing slash."""
    meta = getattr(context, "oauth_metadata", None)
    issuer = getattr(meta, "issuer", None) if meta is not None else None
    return (str(issuer).rstrip("/") or None) if issuer else None


def bind_issuer_from_context(context: Any) -> None:
    """Record the discovered issuer so the next ``storage.set_tokens`` carries it."""
    from tools.mcp_oauth import HermesTokenStorage
    storage = getattr(context, "storage", None)
    issuer = _metadata_issuer(context)
    if isinstance(storage, HermesTokenStorage) and issuer:
        storage.bind_issuer(issuer)


def enforce_refresh_token_issuer(context: Any) -> None:
    """Refuse to reuse a refresh token minted by a different issuer.

    On mismatch the refresh token is stripped (memory + disk) while an
    unexpired access token stays usable. Legacy token files without an issuer
    adopt the current issuer once rather than forcing a re-login.
    """
    from tools.mcp_oauth import HermesTokenStorage
    storage = getattr(context, "storage", None)
    tokens = getattr(context, "current_tokens", None)
    if (
        not isinstance(storage, HermesTokenStorage)
        or tokens is None
        or not getattr(tokens, "refresh_token", None)
    ):
        return
    current = _metadata_issuer(context)
    if current is None:
        return
    stored = (storage.loaded_issuer or "").rstrip("/") or None
    if stored is None:
        storage.stamp_issuer(current)
        return
    if stored != current:
        logger.warning(
            "MCP OAuth: authorization server issuer changed (%s -> %s); "
            "dropping the stored refresh token rather than sending it to a "
            "different issuer",
            stored,
            current,
        )
        storage.strip_refresh_token()
        tokens.refresh_token = None


def prepare_oauth_config(server_name: str, server_url: str, oauth_config: dict | None) -> tuple[dict, "HermesTokenStorage"]:
    """Copy the ``oauth:`` block, apply provider defaults, open its token storage. The copy
    matters: later steps record ``_resolved_port`` / ``_cimd_url`` in the dict, which must
    never leak back into the caller's config."""
    from tools import mcp_oauth as mo
    cfg = dict(oauth_config or {})
    mo.apply_oauth_provider_defaults(cfg, server_name=server_name, server_url=server_url)
    return cfg, mo.HermesTokenStorage(server_name)


def build_provider_kwargs(cfg: dict, storage: "HermesTokenStorage", *, ssh_proxy_hint: bool) -> dict[str, Any]:
    """Resolve the callback port and return the shared provider constructor kwargs. Order
    matters: metadata needs the resolved port, pre-registration needs the metadata.
    ``ssh_proxy_hint`` lets the redirect handler tailor its remote-session hint to a configured
    proxy ``redirect_uri``. Helpers are looked up on ``tools.mcp_oauth`` so tests can patch them."""
    from tools import mcp_oauth as mo
    port = mo._configure_callback_port(cfg, storage)
    client_metadata = mo._build_client_metadata(cfg)
    mo._maybe_preregister_client(storage, cfg, client_metadata)
    redirect_uri = (cfg.get("redirect_uri") or None) if ssh_proxy_hint else None
    return {
        "client_metadata": client_metadata,
        "storage": storage,
        "redirect_handler": mo._make_redirect_handler(port, redirect_uri=redirect_uri),
        # mcp 2.0 dropped OAuthClientProvider's own `timeout`; the configured
        # `oauth.timeout` bounds the callback waiter's poll loop instead.
        "callback_handler": mo._make_callback_waiter(port, cfg.get("_cimd_url"), timeout=float(cfg.get("timeout", 300))),
        "token_user_agent": mo.token_request_user_agent(cfg),
        "oauth_flow": cfg.get("flow", "browser"),
        **mo.cimd_provider_kwargs(cfg)}
