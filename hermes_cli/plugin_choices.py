"""``PluginContext.ask_choice``: a plugin slash command asks its user to pick one option.

The surface that dispatches the command binds an asker around the handler call (:func:`bind_asker`).
Each asker is that surface's existing clarify prompt, so no surface grows a new kind of card:

* a messaging chat: ``adapter.send_clarify`` (buttons on Telegram, Discord and Slack, the numbered
  list answered by a typed reply elsewhere): ``gateway/plugin_command_choice.py``;
* a local session on the TUI gateway (Ink TUI, Desktop): the ``clarify.request`` prompt to the
  session's attached viewers (``gateway/plugin_command_choice.py``);
* the in-process classic CLI: its own clarify picker (``cli.py``).

An asker takes ``(question, labels)`` and returns the label the user picked, or None; values are
mapped back here, so a surface never sees them. With no asker bound (a hook, a cron job, a handler
on an event loop, where blocking would stall the loop that must deliver the answer) the call
returns None and the handler falls back to its own text usage.

This is a *selection* helper only. It is not a permission or approval API: a plugin that needs to
authorise a dangerous action must go through the approval flow, never through ``ask_choice``.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, Optional, Union

logger = logging.getLogger(__name__)

Asker = Callable[[str, list], Optional[str]]
Choice = Union[str, dict]

_ASKER: ContextVar[Optional[Asker]] = ContextVar("plugin_choice_asker", default=None)


@contextmanager
def bind_asker(asker: Asker) -> Iterator[None]:
    """Make *asker* answer ``ask_choice`` for the calls in this context (and the executor thread a
    sync handler runs on: callers carry the context over).

    The token is always reset, including when the handler raises, so one command's asker can never
    leak into the next command that runs in the same context."""
    token = _ASKER.set(asker)
    try:
        yield
    finally:
        _ASKER.reset(token)


def asker_bound() -> bool:
    return _ASKER.get() is not None


def clarify_asker(callback: Callable[[str, list], object]) -> Asker:
    """An asker over a single-question clarify callback (``(question, choices) -> str``): the
    classic CLI's clarify panel. Anything but a string (a cancel sentinel object, None) is no
    answer; a timeout sentence is a string too, but never equals a choice, so it maps to None."""
    def ask(question: str, labels: list) -> Optional[str]:
        answer = callback(question, labels)
        return answer if isinstance(answer, str) else None
    return ask


def _options(choices: list[Choice]) -> list[tuple[str, str, str]]:
    """``[(value, plain label, label shown)]``: a string is all three; a dict's description rides on the shown
    label only, so a typed plain label still picks it. Malformed entries are dropped, never guessed at."""
    options = []
    for choice in choices or []:
        if isinstance(choice, str):
            if choice.strip():
                options.append((choice, choice, choice))
            continue
        if not isinstance(choice, dict) or choice.get("value") is None:
            logger.warning("ask_choice: ignoring malformed choice %r (need a string or a dict with 'value')", choice)
            continue
        value = str(choice["value"])
        label = str(choice.get("label") or value)
        description = str(choice.get("description") or "").strip()
        options.append((value, label, f"{label} — {description}" if description else label))
    return options


def _running_on_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _match(typed: str, options: list[tuple[str, str, str]]) -> Optional[str]:
    """Map the asker's reply onto exactly one option, trying the shown label, then the plain label,
    then the value (any case). A reply that matches several options at one tier is ambiguous and
    maps to None: guessing the first would act on a choice the user did not make."""
    if not typed:
        return None
    for index in (2, 1, 0):
        hits = [option[0] for option in options if option[index].casefold() == typed]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return None
    return None


def ask_choice(question: str, choices: list[Choice]) -> Optional[str]:
    """Ask the user who ran the current slash command to pick one of *choices*; the picked choice's
    value, or None when nothing can ask here, the user cancels or types something else, or the
    clarify timeout passes. A typed value or label (any case) also counts as that choice."""
    asker = _ASKER.get()
    options = _options(choices)
    if asker is None or not options:
        return None
    if _running_on_loop():
        logger.warning("ask_choice needs a sync slash-command handler: an async one would block the "
                       "event loop that delivers the answer; returning None")
        return None
    try:
        picked = asker(str(question), [shown for _value, _label, shown in options])
    except Exception:
        logger.warning("ask_choice: the surface's prompt failed; returning None", exc_info=True)
        return None
    return _match((picked or "").strip().casefold() if isinstance(picked, str) else "", options)
