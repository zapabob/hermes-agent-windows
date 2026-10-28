"""``/delegation`` slash: pick or set ``delegation.backend`` (cache-aware).

Default save applies on the **next session** so the current turn keeps its
cached ``delegate_task`` schema. Opt-in ``--now`` rebuilds tools at the next
safe turn boundary (same contract as ``/skills install --now``).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from agent.delegation_backends import list_backends, saved_backend, set_global_backend

logger = logging.getLogger(__name__)

AskChoice = Callable[[str, list], Optional[str]]


def _session_key() -> str:
    try:
        from gateway.session_context import get_session_env

        return str(get_session_env("HERMES_SESSION_KEY", "") or "").strip()
    except Exception:
        logger.debug("delegation slash: session key unavailable", exc_info=True)
        return ""


def _parse_args(raw: str) -> tuple[str, bool]:
    tokens = [t for t in (raw or "").split() if t]
    apply_now = False
    name = ""
    for token in tokens:
        if token == "--now":
            apply_now = True
            continue
        if not name:
            name = token
    return name.strip().lower(), apply_now


def _choice_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for info in list_backends():
        if not info.available:
            continue
        rows.append(
            {
                "value": info.name,
                "label": info.label or info.name,
                "description": info.description or "",
            }
        )
    return rows


def handle_delegation_slash(
    args: str = "",
    *,
    ask_choice: Optional[AskChoice] = None,
) -> str:
    """Sync slash handler body. ``ask_choice`` defaults to ``PluginContext.ask_choice``."""
    from hermes_cli.plugin_choices import ask_choice as default_ask

    chooser = ask_choice or default_ask
    name, apply_now = _parse_args(args)
    current = saved_backend()

    if not name:
        choices = _choice_rows()
        if not choices:
            return (
                "No delegation backends are available. Enable the bundled "
                "`delegation/default` plugin (and optionally `advanced_delegation`)."
            )
        picked = chooser(
            f"Select delegation backend (current: {current})",
            choices,
        )
        if not picked:
            return (
                f"Current delegation backend: {current}. "
                "Usage: /delegation [backend] [--now]"
            )
        name = picked.strip().lower()

    if name == current and not apply_now:
        return (
            f"Delegation backend is already `{name}`. "
            "Pass --now to rebuild tools on this session (invalidates prompt cache)."
        )

    session_key = _session_key() if apply_now else ""
    try:
        set_global_backend(name, session_key=session_key, apply_now=apply_now)
    except PermissionError as exc:
        return str(exc)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        logger.exception("delegation slash failed")
        return f"Could not set delegation backend: {exc}"

    if apply_now:
        return (
            f"Delegation backend set to `{name}` and queued for this session "
            "(tool schema rebuild at the next safe turn — prompt cache invalidates)."
        )
    return (
        f"Delegation backend set to `{name}`. "
        "Takes effect on the next session (prompt cache preserved). "
        "Pass --now to apply sooner."
    )


def register_delegation_slash(ctx: Any) -> None:
    """Register ``/delegation`` on a :class:`PluginContext`."""
    ctx.register_command(
        "delegation",
        handler=lambda args: handle_delegation_slash(args, ask_choice=ctx.ask_choice),
        description="Select the delegation backend (default / model_map / profile_routes).",
        args_hint="[backend] [--now]",
    )
