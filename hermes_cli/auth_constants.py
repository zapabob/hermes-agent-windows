"""Compatibility shim: the names upstream's ``hermes_cli.auth_constants`` provides to the plugin OAuth broker.

Upstream splits ``AuthError`` and the lazy ``httpx`` proxy out of ``hermes_cli.auth`` into a leaf module. This
fork keeps them in ``hermes_cli.auth``, so the plugin OAuth modules (``plugin_oauth``,
``auth_oauth_pkce_plugin``, ``plugin_provider_requests``) import them from here and stay byte-close to upstream.
Nothing here defines a second ``AuthError``: ``except AuthError`` in either module catches the same class.

Importing this module pulls in ``hermes_cli.auth``; the plugin OAuth modules therefore import it inside the
callables that need it, never at module scope.
"""

from __future__ import annotations

import httpx

from hermes_cli.auth import AuthError

# OAuth ``error`` values that mean the grant itself is gone (revoked, expired, already spent): retrying
# cannot help and the user has to sign in again. Client-configuration errors (``invalid_client``,
# ``invalid_scope``) are deliberately absent: they leave the grant alone so fixing the client fixes the plugin.
OAUTH_GRANT_DEAD_CODES = frozenset({
    "invalid_grant",
    "invalid_token",
    "refresh_token_reused",
    "refresh_token_expired",
    "token_revoked",
})

__all__ = ["AuthError", "OAUTH_GRANT_DEAD_CODES", "httpx"]
