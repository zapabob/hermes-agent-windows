"""Delegation Provider ABC (T04 advanced delegation seam).

A provider decides HOW one ``delegate_task`` task becomes a child run: which
model/provider/endpoint it uses, or which Hermes profile it runs as. It may
add per-task schema parameters. ``delegation.backend`` selects the active one
(unset = ``default``). Core keeps the lifecycle; providers only answer routes.

Everything crossing this interface is plain JSON (no live agent objects).
"""

from __future__ import annotations

import abc
from typing import Any, Mapping

#: Core-owned per-task property names. Provider parameters must not redefine these.
RESERVED_TASK_PARAMETERS = frozenset({
    "goal",
    "context",
    "index",
    "output_schema",
    "images",
    "group",
    "role",
    "toolsets",
    "acp_command",
    "acp_args",
    "provider",
    "model",
    "base_url",
    "api_key",
    "api_mode",
})

#: Keys a route may carry; anything else in a provider answer is ignored.
ROUTE_KEYS = frozenset({
    "model",
    "provider",
    "base_url",
    "api_key",
    "api_mode",
    "request_overrides",
    "reasoning_effort",
    "service_tier",
    "fallback_providers",
    "profile",
    "label",
})


class DelegationRouteError(ValueError):
    """Raised by :meth:`DelegationProvider.route_task` to refuse a task."""


class DelegationProvider(abc.ABC):
    """Abstract base class for a pluggable delegation strategy.

    ``name`` is the ``delegation.backend`` value. ``config`` is the
    ``delegation`` section (read-only). Backend-specific settings live under
    ``delegation.backends.<name>`` via :meth:`settings`.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable backend id (lowercase, matched by ``delegation.backend``)."""

    @property
    def display_name(self) -> str:
        """Human-readable picker label."""
        return self.name

    @property
    def summary(self) -> str:
        """One user-facing line for backend pickers; never shown to the model."""
        return ""

    def settings(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        """This backend's settings: ``delegation.backends.<name>``."""
        backends = config.get("backends") if isinstance(config, Mapping) else None
        own = backends.get(self.name) if isinstance(backends, Mapping) else None
        return own if isinstance(own, Mapping) else {}

    def is_available(self) -> bool:
        """Whether this provider can run here. MUST NOT make network calls."""
        return True

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Extra per-task JSON-schema properties merged into ``tasks.items``.

        Called when tool definitions are built for a session (never mid-turn).
        Must be deterministic for a given ``config`` (prompt-cache safe).
        """
        return {}

    def description(self, config: Mapping[str, Any]) -> str:
        """Optional guidance appended to the ``delegate_task`` description."""
        return ""

    @abc.abstractmethod
    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        """Return the route for one task. Raise :class:`DelegationRouteError` to refuse."""
