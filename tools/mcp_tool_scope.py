"""Connection-ledger keys for tools.mcp_tool under a profile multiplexer.

Every ledger in ``tools.mcp_tool`` (``_servers``, connecting/error/cooldown maps,
circuit breaker, lazy configs) is keyed by a *connection key*: the bare server
name outside a multiplexer (single-profile processes are unchanged), and
``(owner_scope, name)`` under one. Two profiles that both configure ``github``
with their own token are two connections; keying by name alone let the first
profile's connection shadow the second forever (#106005, #91654).

A profile may still *adopt* another profile's live connection when the route
and credentials match; ``_server_tool_scopes[key]`` records every scope that
has done so, and ``_resolve_server_key`` finds that shared connection for a
caller whose own scope has none.

COMPOSE from upstream ``ceaf622`` / ``mcp_tool_scope.py`` into the Windows
monolithic ``mcp_tool`` owner — module split is not required.
"""

from __future__ import annotations

from typing import Optional, Tuple, Union

ServerKey = Union[str, Tuple[str, str]]


def _mcp_registry_scope() -> Optional[str]:
    """Registry scope for MCP ledgers: profile overlay under multiplex, else None."""
    try:
        from agent.secret_scope import is_multiplex_active
    except Exception:
        return None
    if not is_multiplex_active():
        return None
    from tools.registry import registry
    return registry.current_scope_key()


def _server_key(name: str, scope: Optional[str] = None, *, current: bool = True) -> ServerKey:
    """Connection key for *name* owned by *scope* (current registry scope when *current*)."""
    if scope is None and current:
        scope = _mcp_registry_scope()
    return name if scope is None else (scope, name)


def _key_name(key: ServerKey) -> str:
    return key[1] if isinstance(key, tuple) else key


def _key_scope(key: ServerKey) -> Optional[str]:
    """Owning registry scope encoded in *key* (None for a bare, unscoped key)."""
    return key[0] if isinstance(key, tuple) else None


def _key_visible_in_scope(key: ServerKey, scope: Optional[str]) -> bool:
    """Whether the connection under *key* serves *scope*: owned by it or adopted."""
    if scope is None:
        return True
    import tools.mcp_tool as core

    return (
        _key_scope(key) == scope
        or core._server_scope_keys.get(key) == scope
        or scope in core._server_tool_scopes.get(key, ())
    )


def _resolve_server_key(
    name: str, scope: Optional[str] = None, *, current: bool = True
) -> ServerKey:
    """Connection key a call to *name* from *scope* must use.

    Prefer the scope's own live/lazy/connecting bookkeeping; else a shared
    connection it adopted; else its own (not yet existing) key.
    """
    if scope is None and current:
        scope = _mcp_registry_scope()
    own = _server_key(name, scope, current=False)
    if scope is None:
        return own
    import tools.mcp_tool as core

    if (
        own in core._servers
        or own in core._lazy_server_configs
        or own in core._server_connecting
    ):
        return own
    for key, scopes in core._server_tool_scopes.items():
        if scope in scopes and _key_name(key) == name and key in core._servers:
            return key
    return own
