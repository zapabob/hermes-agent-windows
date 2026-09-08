"""Subagent → parent background-process handoff (process_manage action='handoff').

Ownership is the process's ``owner_task_id``: completion notices are stamped from it at exit and the parent's
``drain_notifications`` suppresses ``sa-`` owners, so a child's watcher never reaches the parent and is killed at child
teardown. A validated handoff flips the owner so the completion lands in the parent's chat; anything not handed off is
named on the child's result as orphaned before teardown kills it.
"""

import json
import time
import weakref

import pytest

from tools.delegate_tool import _register_subagent, _unregister_subagent
from tools.process_registry import ProcessRegistry, process_registry, _handle_process
from tools.process_registry_notifications import format_process_notification


class _Parent:
    def __init__(self):
        self.session_id = "sess-handoff"
        self._current_task_id = "parent-turn-1"


class _Child:
    def __init__(self, parent):
        self._delegate_parent_ref = weakref.ref(parent)


def _register(sid, child):
    _register_subagent({"subagent_id": sid, "parent_id": None, "depth": 0, "goal": "g", "model": "m",
                        "started_at": time.time(), "status": "running", "tool_count": 0, "agent": child})


@pytest.fixture(autouse=True)
def _plain_spawn(monkeypatch):
    """Spawn plain children: the systemd-run --user --scope wrapper is irrelevant here and stalls under pytest."""
    import tools.process_registry as _pr
    monkeypatch.setattr(_pr, "_SYSTEMD_SCOPE_AVAILABLE", False)


@pytest.fixture
def clean_queue():
    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()
    yield
    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()


def test_handed_off_process_completion_reaches_parent_and_leftover_is_reported(clean_queue):
    """A real child-owned process handed off carries the parent's owner id (so the parent's drain accepts it, with the
    handoff purpose), while a sibling the child did not hand off is still owned by the child and is listed as orphaned
    on the child's result."""
    sid = "sa-0-handoff01"
    parent = _Parent()
    child = _Child(parent)
    _register(sid, child)
    try:
        handed = process_registry.spawn_local("sleep 0.4; echo ci-green", task_id=sid, owner_task_id=sid)
        handed.notify_on_complete = True
        leftover = process_registry.spawn_local("sleep 30", task_id=sid, owner_task_id=sid)

        out = json.loads(_handle_process(
            {"action": "handoff", "session_id": handed.id, "data": "CI watcher for PR 1"}, task_id=sid))
        assert out["status"] == "handed_off"
        assert handed.owner_task_id == "parent-turn-1" and handed.session_key == "sess-handoff"
        assert child._handed_off_processes[0]["session_id"] == handed.id

        # Only the un-handed sibling is left in the child's name — this is what the result entry reports as orphaned.
        assert [s.id for s in process_registry.running_owned_by(sid)] == [leftover.id]

        # Let it exit on its own — a registry wait() would mark the completion consumed (that is the parent-observed path).
        deadline = time.time() + 10
        while process_registry.completion_queue.empty() and time.time() < deadline:
            time.sleep(0.05)
        assert handed.exited
        # The parent drains with the default suppression of sa- owners: the handed-off completion passes it.
        events = process_registry.drain_notifications(owns_event=lambda e: True)
        mine = [(e, text) for e, text in events if e.get("session_id") == handed.id]
        assert len(mine) == 1
        evt, text = mine[0]
        assert evt["owner_task_id"] == "parent-turn-1"
        assert "Handed off to you by a subagent" in text and "CI watcher for PR 1" in text
    finally:
        process_registry.kill_all(source="test")
        _unregister_subagent(sid)


def test_handoff_refuses_exited_foreign_or_non_child_callers(clean_queue):
    """A PID in prose is not a transfer: handoff is an error for a process that already exited, one the caller does
    not own, or a caller that is not a registered subagent — never a silent no-op."""
    sid, other = "sa-0-handoff02", "sa-1-handoff03"
    parent = _Parent()
    _register(sid, _Child(parent))
    try:
        done = process_registry.spawn_local("true", task_id=sid, owner_task_id=sid)
        process_registry.wait(done.id, timeout=10)
        assert "error" in json.loads(_handle_process(
            {"action": "handoff", "session_id": done.id, "data": "x"}, task_id=sid))

        foreign = process_registry.spawn_local("sleep 30", task_id=other, owner_task_id=other)
        assert "error" in json.loads(_handle_process(
            {"action": "handoff", "session_id": foreign.id, "data": "x"}, task_id=sid))
        assert foreign.owner_task_id == other

        assert "error" in json.loads(_handle_process(
            {"action": "handoff", "session_id": foreign.id, "data": "x"}, task_id="not-a-subagent"))

        # A completion for an un-handed child process is still suppressed in the parent.
        reg = ProcessRegistry()
        reg.completion_queue.put({"type": "completion", "session_id": "proc_x", "task_id": other,
                                  "owner_task_id": other, "command": "sleep", "exit_code": 0, "output": ""})
        assert reg.drain_notifications() == []
        assert format_process_notification({"type": "completion", "session_id": "p", "command": "c", "exit_code": 0,
                                            "output": "", "handoff_note": "why"}).count("Handed off to you") == 1
    finally:
        process_registry.kill_all(source="test")
        _unregister_subagent(sid)


def test_handoff_survives_child_teardown_and_delivers_to_parent(tmp_path, clean_queue):
    """Deterministic sync test verifying process lifetime across child agent teardown:
    1. Spawn handed-off candidate that signals READY and waits for EXIT_PERMIT.
    2. Spawn an un-handed sibling (sleep 60).
    3. Wait until handed candidate signals READY.
    4. Handoff to parent.
    5. Execute real child cleanup: process_registry.kill_all(task_id=sid).
    6. Assert handed-off candidate is STILL RUNNING, while un-handed sibling is TERMINATED.
    7. Grant EXIT_PERMIT.
    8. Wait for handed-off process completion.
    9. Assert parent drain_notifications receives completion event with handoff note and exit_code 0.
    """
    import sys
    sid = "sa-0-handoff-sync"
    parent = _Parent()
    child = _Child(parent)
    _register(sid, child)

    ready_file = tmp_path / "ready.txt"
    permit_file = tmp_path / "permit.txt"
    worker_script = tmp_path / "worker.py"
    sibling_script = tmp_path / "sibling.py"

    worker_script.write_text(
        f"import time, pathlib\n"
        f"pathlib.Path({str(ready_file.as_posix())!r}).write_text('READY', encoding='utf-8')\n"
        f"permit = pathlib.Path({str(permit_file.as_posix())!r})\n"
        f"deadline = time.time() + 20\n"
        f"while not permit.exists() and time.time() < deadline:\n"
        f"    time.sleep(0.05)\n"
        f"print('WORKER_COMPLETED_SUCCESSFULLY')\n",
        encoding="utf-8",
    )
    sibling_script.write_text(
        "import time\ntime.sleep(60)\n",
        encoding="utf-8",
    )

    cmd_worker = f'"{sys.executable}" "{worker_script.as_posix()}"'
    cmd_sibling = f'"{sys.executable}" "{sibling_script.as_posix()}"'

    try:
        handed = process_registry.spawn_local(cmd_worker, task_id=sid, owner_task_id=sid)
        handed.notify_on_complete = True
        sibling = process_registry.spawn_local(cmd_sibling, task_id=sid, owner_task_id=sid)

        # Wait until target process is actively running and signaled READY
        deadline = time.time() + 10
        while not ready_file.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert ready_file.exists(), f"Target process did not start and signal READY. Output: {handed.output}"
        assert not handed.exited, "Target process exited prematurely"
        assert not sibling.exited, "Sibling process exited prematurely"

        # Perform handoff
        out = json.loads(_handle_process(
            {"action": "handoff", "session_id": handed.id, "data": "Durable task for parent"},
            task_id=sid,
        ))
        assert out["status"] == "handed_off"
        assert handed.owner_task_id == "parent-turn-1"
        assert handed.task_id == 'default'

        # Execute real child teardown/cleanup for `sid`
        killed_count = process_registry.kill_all(task_id=sid, source="subagent_cleanup")
        assert killed_count == 1, f"Expected exactly 1 sibling killed, got {killed_count}"

        # Verify: sibling is dead, handed process is STILL ALIVE
        assert sibling.exited, "Un-handed sibling was not killed by child cleanup"
        assert not handed.exited, "Handed-off process was killed by child cleanup!"

        # Grant exit permission to let handed process finish normally
        permit_file.write_text("PERMIT", encoding="utf-8")

        # Wait for handed-off process to complete
        deadline = time.time() + 10
        while not handed.exited and time.time() < deadline:
            time.sleep(0.05)
        assert handed.exited, "Handed-off process failed to finish after permission granted"
        # OS exit precedes durable result persistence and notification publication.
        assert handed._completion_event.wait(10), "Completion was not published after child exit"
        assert handed.exit_code == 0
        assert "WORKER_COMPLETED_SUCCESSFULLY" in handed.output_buffer

        # Parent drains notifications
        events = process_registry.drain_notifications(owns_event=lambda e: True)
        mine = [(e, text) for e, text in events if e.get("session_id") == handed.id]
        assert len(mine) == 1
        evt, text = mine[0]
        assert evt["owner_task_id"] == "parent-turn-1"
        assert "Handed off to you by a subagent" in text
        assert "Durable task for parent" in text
    finally:
        process_registry.kill_all(source="test_cleanup")
        _unregister_subagent(sid)
