"""Classic CLI queue management through actual dispatch, queue and consumption."""
from collections import deque
from copy import deepcopy
from queue import Empty, Queue
from threading import Lock

import pytest

from cli import HermesCLI, _SeededQueryMessage, _VoiceInputMessage
from tools.process_registry_notifications import ProcessNotificationBatch, SubagentNotification


@pytest.fixture
def surface(monkeypatch):
    owner = object.__new__(HermesCLI)
    owner._agent_running = True
    owner._pending_input = Queue()
    owner._pending_resume_sessions = None
    owner._voice_lock = Lock()
    owner._voice_mode = owner._voice_continuous = False
    owner.conversation_history = [{"role": "system", "content": "Fixed cached prefix"}]
    output = []
    monkeypatch.setattr("cli._cprint", output.append)
    return owner, output


def snapshot(owner):
    with owner._pending_input.mutex:
        return list(owner._pending_input.queue)


@pytest.mark.parametrize("alias", ["/queue", "/q", "/Q"])
def test_management_sequence_changes_actual_queue_and_consumer_payloads(surface, monkeypatch, alias):
    owner, output = surface
    prefix = deepcopy(owner.conversation_history)
    for command in ["add A", "add B", "add C", "list", "edit 2 B2", "move 3 1", "rm 2"]:
        assert owner.process_command(f"{alias} {command}") is True
    assert snapshot(owner) == ["C", "B2"]
    assert output and any("A" in line and "1" in line for line in output)
    delivered = []
    monkeypatch.setattr(owner, "chat", lambda text, **_kwargs: delivered.append(text))
    monkeypatch.setattr(owner, "_print_user_message_preview", lambda _item: None)
    monkeypatch.setattr(owner, "_tui_after_turn", lambda: None)
    while not owner._pending_input.empty():
        owner._tui_process_one_input(owner._pending_input.get_nowait())
    assert delivered == ["C", "B2"]
    assert owner.conversation_history == prefix


@pytest.mark.parametrize("command", ["/queue list", "/q edit 2 B2", "/Q move 2 1", "/queue clear"])
def test_busy_text_queue_control_uses_real_inline_admission(surface, command):
    owner, _ = surface
    assert owner._should_handle_steer_command_inline(command)
    assert not owner._should_handle_steer_command_inline(command, has_images=True)
    owner._agent_running = False
    assert not owner._should_handle_steer_command_inline(command)


@pytest.mark.parametrize("payload", ["clear the logs", "edit the config", "list the errors", "rm -1"])
def test_literal_management_words_still_enqueue_the_original_prompt(surface, payload):
    owner, _ = surface
    assert owner.process_command("/queue " + payload)
    assert snapshot(owner) == [payload]


@pytest.mark.parametrize("payload", ["list", "rm 1", "clear", "MixedCase 日本語"])
def test_add_forces_literal_payload(surface, payload):
    owner, _ = surface
    assert owner.process_command("/queue add " + payload)
    assert snapshot(owner) == [payload]


@pytest.mark.parametrize("command", ["", "list"])
def test_bare_and_list_are_read_only(surface, command):
    owner, output = surface
    owner._pending_input.put("Existing KeepCase 日本語")
    assert owner.process_command("/queue " + command)
    assert snapshot(owner) == ["Existing KeepCase 日本語"]
    assert any("Existing KeepCase 日本語" in line for line in output)


@pytest.mark.parametrize("command", ["rm", "edit", "move", "rm 1 extra", "edit 1", "move 1", "move 1 x",
                                     "rm 0", "rm 3", "move 0 0", "move 9 9", "rm ²", "rm ②",
                                     pytest.param("rm " + "9" * 5000, id="over-limit-integer")])
def test_malformed_or_out_of_bounds_management_never_enqueues_or_changes_pending(surface, command):
    owner, output = surface
    owner._pending_input.put("Existing")
    assert owner.process_command("/queue " + command)
    assert snapshot(owner) == ["Existing"]
    assert output


def test_unicode_decimal_and_tab_management_indices(surface):
    owner, _ = surface
    owner._pending_input.put("A")
    owner._pending_input.put("B")
    assert owner.process_command("/queue EDIT\t٢\t日本語 KeepCase")
    assert owner.process_command("/q MOVE\t٢\t١")
    assert snapshot(owner) == ["日本語 KeepCase", "A"]


def test_equivalent_edit_and_same_index_move_are_valid_without_changing_pending(surface):
    owner, output = surface
    owner._pending_input.put("A")
    assert owner.process_command("/queue edit 1 A")
    assert owner.process_command("/queue move 1 1")
    assert snapshot(owner) == ["A"]
    assert not any("not found" in str(line).lower() or "out of range" in str(line).lower() for line in output)


def test_clear_and_remove_preserve_claimed_unfinished_work_and_release_bounded_capacity(surface):
    owner, _ = surface
    owner._pending_input = Queue(maxsize=4)
    for item in ["Claimed", "A", "B"]:
        owner._pending_input.put(item)
    assert owner._pending_input.get_nowait() == "Claimed"
    assert owner.process_command("/queue rm 1")
    assert snapshot(owner) == ["B"]
    assert owner._pending_input.unfinished_tasks == 2
    assert owner.process_command("/queue clear")
    assert owner._pending_input.empty()
    assert owner._pending_input.unfinished_tasks == 1
    owner._pending_input.task_done()
    assert owner._pending_input.unfinished_tasks == 0
    owner._pending_input.put_nowait("New")
    assert owner._pending_input.get_nowait() == "New"


@pytest.mark.parametrize("entry", [_VoiceInputMessage("Voice"), ("Image text", ["owned.png"]),
                                   _SeededQueryMessage("/literal", ["seed.png"]),
                                   ProcessNotificationBatch((({"session_id": "owned"}, "PRIVATE MODEL NOTICE"),)),
                                   SubagentNotification("PRIVATE MODEL NOTICE", {"goal": "Human preview", "status": "completed"})])
def test_move_preserves_structured_entry_identity(surface, entry):
    owner, _ = surface
    owner._pending_input.put("Earlier")
    owner._pending_input.put(entry)
    assert owner.process_command("/queue move 2 1")
    assert snapshot(owner)[0] is entry
    assert snapshot(owner)[1] == "Earlier"


@pytest.mark.parametrize("kind", ["voice", "image", "seeded"])
def test_edit_preserves_voice_and_attachment_literal_semantics(surface, kind):
    owner, _ = surface
    entries = {"voice": _VoiceInputMessage("Before"), "image": ("Before", ["owned.png"]),
               "seeded": _SeededQueryMessage("Before", ["owned.png"])}
    owner._pending_input.put(entries[kind])
    assert owner.process_command("/queue edit 1 /KeepCase 日本語")
    edited = snapshot(owner)[0]
    unwrapped, voice, seeded = owner._tui_unwrap_input(edited)
    assert voice is (kind == "voice")
    assert seeded is (kind == "seeded")
    assert unwrapped == ("/KeepCase 日本語" if kind == "voice" else ("/KeepCase 日本語", ["owned.png"]))


def test_queue_management_preserves_collapsed_paste_expansion(surface, tmp_path):
    owner, _ = surface
    pasted = "first\nMiddleCase 日本語\nlast"
    paste_file = tmp_path / "paste.txt"
    paste_file.write_text(pasted, encoding="utf-8")
    placeholder = f"[Pasted text #1: 3 lines → {paste_file}]"
    assert owner.process_command("/queue add " + placeholder)
    assert snapshot(owner) == [pasted]
    assert owner.process_command("/queue edit 1 " + placeholder)
    assert snapshot(owner) == [pasted]


def test_notification_preview_and_edit_do_not_render_or_replace_model_notice(surface, monkeypatch):
    owner, output = surface
    batch = ProcessNotificationBatch((({"session_id": "owned"}, "PRIVATE MODEL NOTICE"),))
    delegated = SubagentNotification("PRIVATE MODEL NOTICE", {"goal": "Human preview", "status": "completed"})
    rendered = []
    def render_notice(*_args):
        rendered.append(True)
        return "PRIVATE MODEL NOTICE"

    monkeypatch.setattr(ProcessNotificationBatch, "render", render_notice)
    owner._pending_input.put(batch)
    owner._pending_input.put(delegated)
    assert owner.process_command("/queue list")
    assert any("Human preview" in str(line) for line in output)
    assert not any("PRIVATE MODEL NOTICE" in str(line) for line in output)
    assert owner.process_command("/queue edit 1 New")
    assert owner.process_command("/queue edit 2 New")
    assert snapshot(owner) == [batch, delegated]
    assert snapshot(owner)[0] is batch and snapshot(owner)[1] is delegated
    assert rendered == []


def test_snapshot_and_complete_mutation_hold_the_existing_queue_mutex(surface):
    owner, _ = surface
    observed = []

    class ObservedDeque(deque):
        def __iter__(self):
            observed.append(owner._pending_input.mutex.locked())
            return super().__iter__()

        def clear(self):
            observed.append(owner._pending_input.mutex.locked())
            return super().clear()

        def extend(self, values):
            observed.append(owner._pending_input.mutex.locked())
            return super().extend(values)

    owner._pending_input.queue = ObservedDeque(["A", "B"])
    owner._pending_input.unfinished_tasks = 2
    assert owner.process_command("/queue move 2 1")
    assert observed and all(observed)
    assert snapshot(owner) == ["B", "A"]


def test_remove_wakes_a_real_blocked_bounded_producer(surface):
    import threading
    import time

    owner, _ = surface
    owner._pending_input = Queue(maxsize=2)
    pending = owner._pending_input
    pending.put("A")
    pending.put("B")
    attempted, produced, command_done = (threading.Event() for _ in range(3))
    errors = []

    def producer():
        attempted.set()
        try:
            pending.put("Later", timeout=3)
            produced.set()
        except BaseException as exc:
            errors.append(exc)

    def remove():
        try:
            owner.process_command("/queue rm 1")
        except BaseException as exc:
            errors.append(exc)
        finally:
            command_done.set()

    producer_thread = threading.Thread(target=producer, daemon=True)
    command_thread = threading.Thread(target=remove, daemon=True)
    producer_thread.start()
    try:
        assert attempted.wait(1)
        assert not produced.wait(0.1), "Full bounded queue did not block producer"
        command_thread.start()
        assert command_done.wait(1), "Removal blocked instead of freeing queue capacity"
        assert produced.wait(1), "Removal did not notify the blocked producer"
        assert not errors
        assert snapshot(owner) == ["B", "Later"]
        assert pending.unfinished_tasks == 2
    finally:
        deadline = time.monotonic() + 4
        while (producer_thread.is_alive() or command_thread.is_alive()) and time.monotonic() < deadline:
            try:
                pending.get(timeout=0.05)
                pending.task_done()
            except Empty:
                pass
        producer_thread.join(timeout=1)
        if command_thread.ident is not None:
            command_thread.join(timeout=1)


def test_clear_wakes_a_real_join_waiter_without_completing_claimed_work(surface):
    import threading

    owner, _ = surface
    pending = owner._pending_input
    pending.put("A")
    waiting, joined = threading.Event(), threading.Event()

    def waiter():
        waiting.set()
        pending.join()
        joined.set()

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    try:
        assert waiting.wait(1)
        assert not joined.wait(0.1)
        assert owner.process_command("/queue clear")
        assert joined.wait(1), "Clear did not wake the existing join waiter"
        assert pending.unfinished_tasks == 0
    finally:
        while not pending.empty():
            pending.get_nowait()
            pending.task_done()
        thread.join(timeout=1)


def test_claimed_work_keeps_join_waiter_blocked_until_real_completion(surface):
    import threading

    owner, _ = surface
    pending = owner._pending_input
    pending.put("Claimed")
    pending.put("Pending")
    assert pending.get_nowait() == "Claimed"
    waiting, joined = threading.Event(), threading.Event()

    def waiter():
        waiting.set()
        pending.join()
        joined.set()

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    try:
        assert waiting.wait(1)
        assert owner.process_command("/queue clear")
        assert pending.unfinished_tasks == 1
        assert not joined.wait(0.1), "Pending clear completed already claimed work"
        pending.task_done()
        assert joined.wait(1)
    finally:
        with pending.mutex:
            remaining = pending.unfinished_tasks
        for _ in range(remaining):
            pending.task_done()
        thread.join(timeout=1)


def test_atomic_move_serializes_real_concurrent_consumer_and_producer(surface):
    import threading

    owner, _ = surface
    pending = owner._pending_input
    snapshot_started, allow_commit = threading.Event(), threading.Event()
    attempted_get, attempted_put = threading.Event(), threading.Event()
    consumed, produced, command_done = (threading.Event() for _ in range(3))
    delivered, errors = [], []
    intercept = [True]

    class BarrierDeque(deque):
        def __iter__(self):
            if intercept[0]:
                intercept[0] = False
                snapshot_started.set()
                if not allow_commit.wait(3):
                    raise AssertionError("Snapshot barrier not released")
            return super().__iter__()

    pending.queue = BarrierDeque(["A", "B"])
    pending.unfinished_tasks = 2

    def move():
        try:
            owner.process_command("/queue move 2 1")
        except BaseException as exc:
            errors.append(exc)
        finally:
            command_done.set()

    def consume():
        attempted_get.set()
        try:
            delivered.append(pending.get(timeout=2))
            pending.task_done()
            consumed.set()
        except BaseException as exc:
            errors.append(exc)

    def produce():
        attempted_put.set()
        try:
            pending.put("C", timeout=2)
            produced.set()
        except BaseException as exc:
            errors.append(exc)

    command_thread = threading.Thread(target=move, daemon=True)
    consumer_thread = threading.Thread(target=consume, daemon=True)
    producer_thread = threading.Thread(target=produce, daemon=True)
    command_thread.start()
    try:
        assert snapshot_started.wait(1), "Management never reached the real queue snapshot"
        consumer_thread.start()
        producer_thread.start()
        assert attempted_get.wait(1) and attempted_put.wait(1)
        assert not consumed.wait(0.1), "Consumer escaped between snapshot and mutation"
        assert not produced.is_set(), "Producer escaped between snapshot and mutation"
        allow_commit.set()
        assert command_done.wait(1) and consumed.wait(1) and produced.wait(1)
        assert not errors
        assert delivered == ["B"]
        assert snapshot(owner) == ["A", "C"]
        assert pending.unfinished_tasks == 2
    finally:
        allow_commit.set()
        for thread in [command_thread, consumer_thread, producer_thread]:
            if thread.ident is not None:
                thread.join(timeout=3)


def test_queue_management_does_not_change_another_real_cli_owner(surface):
    owner, _ = surface
    other = object.__new__(HermesCLI)
    other._agent_running = True
    other._pending_input = Queue()
    other.conversation_history = [{"role": "system", "content": "Other cached prefix"}]
    other._pending_input.put("Other A")
    other._pending_input.put("Other B")
    history = deepcopy(other.conversation_history)
    owner._pending_input.put("Own A")
    owner._pending_input.put("Own B")
    assert owner.process_command("/queue rm 1")
    assert snapshot(owner) == ["Own B"]
    assert snapshot(other) == ["Other A", "Other B"]
    assert other._pending_input.unfinished_tasks == 2
    assert other.conversation_history == history


def test_canonical_queue_metadata_exposes_management_without_new_dispatch_owner():
    from hermes_cli.commands import resolve_command

    command = resolve_command("q")
    assert command.name == "queue"
    assert set(command.subcommands) == {"list", "edit", "rm", "move", "clear", "add"}
    assert command.busy_policy == "dispatch"
    assert command.busy_handler == "queue"
