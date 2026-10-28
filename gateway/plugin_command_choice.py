"""The gateway's askers for ``PluginContext.ask_choice`` (``hermes_cli/plugin_choices.py``).

Both reuse the clarify tool's own prompt, so every surface renders a plugin command's choice the
way it renders the agent's questions:

* a messaging chat gets ``adapter.send_clarify``: buttons where the adapter has them (Telegram,
  Discord, Slack), the base numbered list elsewhere. A tap resolves it through
  ``resolve_gateway_clarify``; a typed reply reaches the clarify text-intercept even though the
  command still holds the chat (the adapter's clarify bypass);
* a local TUI-gateway session (Ink TUI, Desktop) gets the ``clarify.request`` prompt on its
  viewers' sockets, answered by their clarify panel (``clarify.respond``).

A sync handler runs on an executor thread (:func:`run_plugin_handler`), so blocking here never
stalls the event loop that delivers the reply; the wait follows the clarify timeout.

``ask_choice`` selects between options only. It is not an approval API and never grants permission.
"""
from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
import uuid
from contextlib import nullcontext
from typing import Any, Callable, Optional

from gateway.config import Platform
from hermes_cli.plugin_choices import asker_bound, bind_asker, clarify_asker

logger = logging.getLogger(__name__)


def chat_choices(runner, source, session_key: str, loop: Optional[asyncio.AbstractEventLoop] = None):
    """Bind the messaging asker for a command *source* sent, unless the caller bound one already (a
    local viewer's ``slash.exec``) or the source is a local session (it has no chat to post in).

    *loop* is the gateway event loop the adapter lives on; it defaults to the running loop, so
    call from the loop (or pass it explicitly from a worker thread)."""
    if asker_bound() or source.platform == Platform.LOCAL:
        return nullcontext()
    loop = loop or asyncio.get_running_loop()
    return bind_asker(lambda question, labels: _ask_chat(runner, source, session_key, loop, question, labels))


def _ask_chat(runner, source, session_key: str, loop, question: str, labels: list) -> Optional[str]:
    # gateway.run imports this module, so its clarify send/wait seam is imported lazily (it is
    # already loaded by the time a command runs).
    from gateway.run import _clarify_send_then_wait
    from tools import clarify_gateway

    adapter = runner._adapter_for_source(source)
    if adapter is None:
        return None
    clarify_id = uuid.uuid4().hex[:10]
    entry = clarify_gateway.register(clarify_id, session_key, question, labels)
    try:
        card = asyncio.run_coroutine_threadsafe(
            adapter.send_clarify(
                chat_id=source.chat_id, question=question, choices=labels, clarify_id=clarify_id,
                session_key=session_key, metadata=runner._thread_metadata_for_source(source),
            ),
            loop,
        )
        response = _clarify_send_then_wait(
            card, clarify_id=clarify_id, session_key=session_key, clarify_mod=clarify_gateway, entry=entry,
        )
    except Exception:
        # The registration must not outlive a failed send (a later typed reply would resolve a
        # question nobody can see); cancel_request is a no-op once the entry is gone.
        clarify_gateway.cancel_request(clarify_id, entry=entry)
        raise
    # Timeout / undeliverable sentinels are plain strings that never equal a choice label.
    return response if isinstance(response, str) else None


def viewer_choices(clarify_block: Callable[..., str], session_id: str):
    """Bind the local-session asker: *clarify_block* is the TUI gateway's blocking clarify bridge
    (``tui_gateway.server._clarify_block``), which emits ``clarify.request`` to *session_id*'s
    viewers and blocks until ``clarify.respond`` (or the clarify timeout, which answers ``""``)."""
    return bind_asker(clarify_asker(lambda question, labels: clarify_block(session_id, question, labels)))


async def run_plugin_handler(runner, source, session_key: str, handler: Callable[[str], Any], arg: str):
    """Run a plugin slash-command *handler* with ``ask_choice`` wired to the chat that sent it.

    A sync handler runs on an executor thread under a copy of the current context (so profile and
    secret scopes carry over, and the asker binding dies with the copy even if the handler raises);
    blocking in ``ask_choice`` therefore cannot stall the loop. An async handler stays on the
    loop, where ``ask_choice`` deliberately returns None."""
    loop = asyncio.get_running_loop()
    if inspect.iscoroutinefunction(handler):
        result = handler(arg)
    else:
        context = contextvars.copy_context()

        def call():
            with chat_choices(runner, source, session_key, loop):
                return handler(arg)

        result = await loop.run_in_executor(None, context.run, call)
    if inspect.isawaitable(result):
        result = await result
    return result
