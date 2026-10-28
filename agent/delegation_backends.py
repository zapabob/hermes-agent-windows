"""Public API for selecting a delegation backend (``/delegation`` / config).

``delegation.backend`` is the saved choice. A session routes on the backend its
``delegate_task`` schema was built from (``agent._delegation_backend``), because
that schema is cached prompt — a save applies from the next session unless
``apply_now`` rebuilds tools at a safe turn boundary.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from typing import Any

from agent.delegation_registry import (
    DEFAULT_BACKEND,
    backend_status,
    configured_backend,
    list_providers,
    lower_key,
)

logger = logging.getLogger(__name__)

_rebuild_requests: set[str] = set()
_lock = threading.Lock()


@dataclass(frozen=True)
class BackendInfo:
    """One selectable delegation backend."""

    name: str
    label: str
    description: str
    available: bool
    reason: str = ""


def _info(name: str) -> BackendInfo:
    provider, reason = backend_status(name)
    if provider is None:
        return BackendInfo(name, name, "", False, reason)
    return BackendInfo(
        name,
        provider.display_name,
        provider.summary,
        not reason,
        reason,
    )


def list_backends() -> list[BackendInfo]:
    """``default`` first, then every registered backend."""
    names = [
        DEFAULT_BACKEND,
        *sorted({p.name for p in list_providers()} - {DEFAULT_BACKEND}),
    ]
    return [_info(name) for name in names]


def saved_backend() -> str:
    """``delegation.backend`` as config.yaml has it now."""
    from tools.delegate_tool import _load_config

    return configured_backend(_load_config())


def _delegate_def(tools: Any) -> Any:
    return next(
        (
            t
            for t in tools or ()
            if isinstance(t, dict)
            and (t.get("function") or {}).get("name") == "delegate_task"
        ),
        None,
    )


def adopt_built_backend(agent: Any, defs: Any, backend: str) -> None:
    """Pin ``backend`` on the agent when its ``delegate_task`` matches ``defs``."""
    if _delegate_def(getattr(agent, "tools", None)) == _delegate_def(defs):
        agent._delegation_backend = backend


def pinned_backend(agent: Any) -> str:
    """Backend the agent's ``delegate_task`` was built from; ``""`` when unknown."""
    pinned = getattr(agent, "_delegation_backend", None)
    return pinned if isinstance(pinned, str) else ""


def set_global_backend(name: str, *, session_key: str = "", apply_now: bool = False) -> None:
    """Persist ``delegation.backend``. Raises on managed installs / unavailable backends."""
    from hermes_cli.config import (
        atomic_config_write,
        format_managed_message,
        get_config_path,
        is_managed,
        read_user_config_raw,
    )

    if is_managed():
        raise PermissionError(format_managed_message("set delegation.backend"))
    if apply_now and not session_key:
        raise ValueError("No session to apply the switch to: apply_now needs the command's session_key.")
    key = lower_key(name)
    info = _info(key)
    if not info.available:
        raise ValueError(info.reason)
    path = get_config_path()
    user_config = read_user_config_raw(path)
    section = user_config.get("delegation")
    if not isinstance(section, dict):
        section = user_config["delegation"] = {}
    section["backend"] = key
    atomic_config_write(path, user_config)
    if apply_now:
        with _lock:
            _rebuild_requests.add(session_key)


def apply_requested_tool_rebuild(agent: Any) -> bool:
    """Rebuild tools at turn start when ``apply_now`` was requested for this session."""
    if getattr(agent, "_turn_origin", None) or getattr(agent, "_delegate_depth", 0):
        return False
    try:
        from gateway.session_context import get_session_env

        key = get_session_env("HERMES_SESSION_KEY", "") or str(
            getattr(agent, "session_id", "") or ""
        )
    except Exception:
        key = str(getattr(agent, "session_id", "") or "")
    with _lock:
        if key not in _rebuild_requests:
            return False
        _rebuild_requests.discard(key)
    # Prefer the existing MCP/tool refresh path when present; otherwise rebuild
    # definitions via model_tools so the pinned backend updates.
    before = getattr(agent, "tools", None)
    try:
        from model_tools import get_tool_definitions

        defs = get_tool_definitions(
            enabled_toolsets=getattr(agent, "enabled_toolsets", None),
            disabled_toolsets=getattr(agent, "disabled_toolsets", None),
        )
        agent.tools = defs
        adopt_built_backend(agent, defs, saved_backend())
    except Exception:
        logger.debug("delegation tool rebuild failed", exc_info=True)
        return False
    return agent.tools is not before


class DelegationBackends:
    """``ctx.delegation_backends`` host facade for plugins."""

    def list_backends(self) -> list[dict[str, Any]]:
        return [asdict(info) for info in list_backends()]

    def set_global_backend(self, name: str, *, session_key: str = "", apply_now: bool = False) -> None:
        set_global_backend(name, session_key=session_key, apply_now=apply_now)
