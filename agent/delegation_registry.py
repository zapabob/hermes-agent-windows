"""Delegation provider registry (T04).

Plugins call :meth:`PluginContext.register_delegation_provider`. Selection is
``delegation.backend`` (default when unset). A configured backend that is not
registered or reports unavailable **fails closed** — never silently falls back
to another route.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import threading
from pathlib import Path
from typing import Any, Mapping, Optional

from agent.delegation_provider import DelegationProvider, DelegationRouteError

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "default"

_BUNDLED_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_lock = threading.RLock()
_providers: dict[str, DelegationProvider] = {}
_first_use: dict[str, DelegationProvider] = {}


def lower_key(name: str) -> str:
    return name.strip().lower()


def register_provider(provider: DelegationProvider) -> None:
    """Register (or replace) a delegation provider by ``provider.name``."""
    if not isinstance(provider, DelegationProvider):
        raise TypeError("provider must be a DelegationProvider")
    key = lower_key(provider.name)
    with _lock:
        previous = _providers.get(key)
        _providers[key] = provider
    if previous is not None and previous is not provider:
        logger.info("Delegation provider %s replaced", key)
    else:
        logger.debug("Delegation provider registered: %s", key)


def list_providers() -> list[DelegationProvider]:
    with _lock:
        return list(_providers.values())


def get_provider(name: str) -> Optional[DelegationProvider]:
    key = lower_key(name)
    with _lock:
        return _providers.get(key)


def configured_backend(config: Mapping[str, Any]) -> str:
    """``delegation.backend`` normalized; blank/non-string means ``default``."""
    raw = config.get("backend") if isinstance(config, Mapping) else None
    return lower_key(raw) if isinstance(raw, str) and raw.strip() else DEFAULT_BACKEND


def _bundled_disabled(name: str) -> bool:
    try:
        from hermes_cli.plugins import _get_disabled_plugins

        disabled = _get_disabled_plugins()
    except Exception:
        return False
    return bool({name, f"delegation/{name}", f"delegation-{name}"} & set(disabled))


def _load_bundled(name: str) -> Optional[DelegationProvider]:
    """Load ``plugins/delegation/<name>/`` on first use without a full plugin sweep."""
    if not _BUNDLED_NAME_RE.match(name) or _bundled_disabled(name):
        return None
    with _lock:
        if name in _first_use:
            return _first_use[name]
    try:
        from hermes_cli.plugins import get_bundled_plugins_dir

        plugin_dir = get_bundled_plugins_dir() / "delegation" / name
    except Exception:
        return None
    init_path = plugin_dir / "__init__.py"
    if not (plugin_dir / "plugin.yaml").is_file() or not init_path.is_file():
        return None

    class _BundledRegistrar:
        def register_delegation_provider(self, provider: DelegationProvider) -> None:
            _first_use[name] = provider

    module_name = f"plugins.delegation.{name.replace('-', '_')}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, init_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        register = getattr(module, "register", None)
        if not callable(register):
            return None
        register(_BundledRegistrar())
    except Exception:
        logger.debug("bundled delegation/%s failed to load", name, exc_info=True)
        return None
    with _lock:
        return _first_use.get(name)


def _available(provider: Optional[DelegationProvider]) -> bool:
    if provider is None:
        return False
    try:
        return bool(provider.is_available())
    except Exception:
        logger.debug(
            "delegation provider %s.is_available() raised",
            getattr(provider, "name", "?"),
            exc_info=True,
        )
        return False


def _usable(name: str) -> Optional[DelegationProvider]:
    registered = get_provider(name)
    if _available(registered):
        return registered
    bundled = _load_bundled(name)
    if _available(bundled):
        return bundled
    if registered is None and bundled is None:
        try:
            from hermes_cli.plugins import discover_plugins

            discover_plugins()
        except Exception:
            logger.debug("discover_plugins for delegation backends failed", exc_info=True)
        registered = get_provider(name)
        if _available(registered):
            return registered
        bundled = _load_bundled(name)
        if _available(bundled):
            return bundled
    return None


def backend_status(name: str) -> tuple[Optional[DelegationProvider], str]:
    """``(provider, "")`` when usable, else ``(provider or None, reason)``."""
    key = lower_key(name) if isinstance(name, str) and name.strip() else DEFAULT_BACKEND
    provider = _usable(key)
    if provider is not None:
        return provider, ""
    registered = get_provider(key)
    if registered is None and key == DEFAULT_BACKEND:
        return None, (
            "No default delegation strategy is available: the bundled plugin "
            "delegation/default is disabled. Remove it from plugins.disabled "
            "in config.yaml."
        )
    if registered is None:
        return None, (
            f"Delegation backend '{key}' is not installed: no enabled plugin provides it. "
            f"Install or enable the plugin that does (`hermes plugins list`), or switch "
            f"back to the default backend (`hermes config set delegation.backend default`)."
        )
    return registered, (
        f"Delegation backend '{key}' is unavailable here (its plugin reports it cannot run). "
        f"Fix its setup, or switch back to the default backend: "
        f"`hermes config set delegation.backend default`."
    )


def get_active_provider(config: Mapping[str, Any]) -> DelegationProvider:
    """Provider selected by ``config``; raises :class:`DelegationRouteError` when unusable."""
    provider, reason = backend_status(configured_backend(config))
    if reason or provider is None:
        raise DelegationRouteError(f"{reason} No subagent was started.")
    return provider


# Compatibility alias used by some upstream-shaped tests / routes.
_registry = type(
    "_RegistryFacade",
    (),
    {
        "get_provider": staticmethod(get_provider),
        "list_providers": staticmethod(list_providers),
        "register": staticmethod(register_provider),
    },
)()
