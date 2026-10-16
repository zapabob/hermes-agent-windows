"""Classic CLI management of the existing pending-input queue."""

from collections.abc import Callable
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
