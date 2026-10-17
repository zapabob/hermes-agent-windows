"""Classic CLI management of the existing pending-input queue."""

from collections.abc import Callable
from contextlib import nullcontext
from typing import TYPE_CHECKING

from tools.process_registry_notifications import ProcessNotificationBatch, SubagentNotification

if TYPE_CHECKING:
    from cli import HermesCLI


_VERBS = {
    "list": "list", "ls": "list", "show": "list", "clear": "clear",
    "edit": "edit", "set": "edit", "rm": "rm", "remove": "rm",
    "delete": "rm", "del": "rm", "pop": "rm", "move": "move",
}
_INDEXED = {"edit", "rm", "move"}
_USAGE = "  Usage: /queue <prompt> | list | edit N <prompt> | rm N | move A B | clear | add <prompt>"


class _PendingSteerInput(str):
    """A string input retaining its source agent, session and stop generation."""

    def __new__(cls, text, agent, session_id, generation):
        item = super().__new__(cls, text)
        item.agent = agent
        item.session_id = session_id
        item.generation = generation
        return item


def pending_steer_is_current(owner: "HermesCLI", item: object) -> bool:
    if not isinstance(item, _PendingSteerInput):
        return True
    agent = getattr(owner, "agent", None)
    if agent is not item.agent:
        return False
    lock = getattr(agent, "_pending_steer_lock", None)
    with lock if lock is not None else nullcontext():
        stop = getattr(agent, "_hard_interrupt_requested", None)
        return (getattr(agent, "session_id", None) == item.session_id
                and getattr(agent, "_steer_cancel_generation", 0) == item.generation
                and not getattr(agent, "_steer_turn_cancelled", False)
                and (stop is None or not stop.is_set()))


def _claim_steer_handoff(owner: "HermesCLI", agent, ticket=None) -> bool:
    """Claim an authoritative record while the caller holds its steer lock."""
    if getattr(owner, "agent", None) is not agent:
        return False
    stop = getattr(agent, "_hard_interrupt_requested", None)
    if getattr(agent, "_steer_turn_cancelled", False) or (stop is not None and stop.is_set()):
        return False
    handoff = getattr(agent, "_steer_handoff", None)
    generation = getattr(agent, "_steer_cancel_generation", 0)
    session_id = getattr(agent, "session_id", None)
    if (not isinstance(handoff, dict) or (ticket is not None and handoff.get("id") != ticket)
            or handoff.get("generation") != generation or handoff.get("session_id") != session_id):
        return False
    owner._pending_input.put(_PendingSteerInput(handoff["text"], agent, session_id, generation))
    agent._steer_handoff = None
    return True


def enqueue_busy_steer_fallback(owner: "HermesCLI", payload: object, *, source_agent) -> None:
    """Keep a new ordinary input after any earlier settled guidance."""
    lock = getattr(source_agent, "_pending_steer_lock", None)
    with lock if lock is not None else nullcontext():
        _claim_steer_handoff(owner, source_agent)
        # Unlike /s, this is the user's ordinary next input. A stop retires
        # the earlier guidance but does not discard this new request.
        owner._pending_input.put(payload)


def enqueue_pending_steer(owner: "HermesCLI", result: dict, *, source_agent=None) -> bool:
    """Transfer only live leftover guidance, preserving ordinary queued input."""
    text = result.get("pending_steer")
    agent = getattr(owner, "agent", None)
    if not isinstance(text, str) or not text or agent is None:
        return False
    if source_agent is not None and source_agent is not agent:
        return False
    lock = getattr(agent, "_pending_steer_lock", None)
    with lock if lock is not None else nullcontext():
        generation = getattr(agent, "_steer_cancel_generation", 0)
        stop = getattr(agent, "_hard_interrupt_requested", None)
        session_id = getattr(agent, "session_id", None)
        if (result.get("pending_steer_generation", generation) != generation
                or result.get("session_id", session_id) != session_id
                or getattr(agent, "_steer_turn_cancelled", False)
                or (stop is not None and stop.is_set())):
            return False
        ticket = result.get("pending_steer_handoff")
        if ticket is not None:
            return _claim_steer_handoff(owner, agent, ticket)
        # A command arriving during cleanup must not overtake guidance already
        # accepted by that same turn. Claim its retained handoff first; the
        # finalizer's later ticket then cannot enqueue that guidance twice.
        _claim_steer_handoff(owner, agent)
        owner._pending_input.put(_PendingSteerInput(text, agent, session_id, generation))
        return True


def _index(token: str) -> int | None:
    if not token.isdigit():
        return None
    try:
        return int(token) - 1
    except ValueError:
        # Some digit-like Unicode characters and excessively long integers
        # cannot be converted; these are malformed control inputs, not prompts.
        return None


def _preview(item: object) -> str:
    if isinstance(item, ProcessNotificationBatch):
        text = f"Process notifications ({len(item.notifications)})"
    elif isinstance(item, SubagentNotification):
        text = item.display_text
    elif isinstance(item, tuple):
        text = str(item[0])
    else:
        text = str(item)
    text = " ".join(text.split())
    return text[:80] + ("..." if len(text) > 80 else "")


def _edit(item: object, text: str) -> object | None:
    from cli import _SeededQueryMessage, _VoiceInputMessage

    # Notifications own their model payload and can only be moved or removed.
    # Check before str: SubagentNotification is itself a string subclass.
    if isinstance(item, (ProcessNotificationBatch, SubagentNotification)):
        return None
    if isinstance(item, _VoiceInputMessage):
        return _VoiceInputMessage(text)
    if isinstance(item, _SeededQueryMessage):
        edited = _SeededQueryMessage(text)
        edited.images = item.images
        return edited
    if isinstance(item, tuple):
        return (text, item[1])
    if isinstance(item, str):
        return text
    return None


def process_queue_command(owner: "HermesCLI", command: str, emit: Callable[[str], None]) -> None:
    """Dispatch queue controls without entering or interrupting the model turn."""
    parts = command.split(None, 1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    tokens = payload.split(None, 1)
    verb = _VERBS.get(tokens[0].lower()) if tokens else "list"
    rest = tokens[1] if len(tokens) > 1 else ""
    management = verb is not None and (
        not rest or (verb in _INDEXED and rest.split(None, 1)[0].isdigit())
    )
    pending = owner._pending_input

    if not management:
        if tokens and tokens[0].lower() == "add":
            payload = rest
        payload = owner._expand_paste_references(payload)
        if not payload:
            emit(_USAGE)
            return
        pending.put(payload)
        label = "Queued for the next turn" if owner._agent_running else "Queued"
        emit(f"  {label}: {_preview(payload)}")
        return

    if verb == "list":
        with pending.mutex:
            items = list(pending.queue)
        emit("  Queued prompts:" if items else "  No queued prompts.")
        for position, item in enumerate(items, 1):
            emit(f"    {position}. {_preview(item)}")
        return

    args = rest.split(None, 1)
    first = _index(args[0]) if args else None
    second = _index(args[1]) if verb == "move" and len(args) == 2 else None
    replacement = owner._expand_paste_references(args[1]) if verb == "edit" and len(args) == 2 else ""
    if verb != "clear" and (
        first is None or first < 0
        or (verb == "rm" and len(args) != 1)
        or (verb == "edit" and not replacement)
        or (verb == "move" and (second is None or second < 0))
    ):
        emit(_USAGE)
        return

    # Clear has no index; every indexed operation was validated above.
    first = first if first is not None else -1
    second = second if second is not None else -1

    # Snapshot, validate and commit under the Queue's own mutex. Retain task
    # accounting for inputs already claimed by a consumer, and wake existing
    # join/put waiters when pending removal completes tasks or frees capacity.
    with pending.mutex:
        items = list(pending.queue)
        before = len(items)
        if verb != "clear" and (
            first >= before or (verb == "move" and second >= before)
        ):
            message = "  Queue index out of range."
        elif verb == "edit" and (edited := _edit(items[first], replacement)) is None:
            message = "  This queued notification cannot be edited."
        else:
            if verb == "clear":
                items.clear()
                message = f"  Cleared {before} queued prompt(s)."
            elif verb == "rm":
                items.pop(first)
                message = f"  Removed queued prompt {first + 1}."
            elif verb == "edit":
                items[first] = edited
                message = f"  Updated queued prompt {first + 1}."
            else:
                items.insert(second, items.pop(first))
                message = f"  Moved queued prompt {first + 1} to {second + 1}."
            pending.queue.clear()
            pending.queue.extend(items)
            removed = before - len(items)
            if removed:
                pending.unfinished_tasks -= removed
                if pending.unfinished_tasks == 0:
                    pending.all_tasks_done.notify_all()
                pending.not_full.notify_all()
    emit(message)
