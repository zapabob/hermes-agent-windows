"""``ask_choice`` from a plugin slash command run through the TUI gateway's ``slash.exec``.

The real ``_block`` bridge is used end to end: ``clarify.request`` goes out to the session's viewer
and the viewer's ``clarify.respond`` settles it while ``slash.exec`` is still waiting for the handler.
Only the plugin lookup (and the config/skill scans the dispatcher consults) is substituted.
"""
import importlib
import queue
import threading
import types
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.plugin_choices import asker_bound, ask_choice

CHOICES = [{"value": "default", "label": "Default", "description": "parent model"},
           {"value": "model_map", "label": "Model routes"}, "profile_routes"]
LABELS = ["Default — parent model", "Model routes", "profile_routes"]


@pytest.fixture
def server(monkeypatch):
    with patch.dict("sys.modules", {"hermes_cli.env_loader": MagicMock(), "hermes_cli.banner": MagicMock()}):
        mod = importlib.import_module("tui_gateway.server")
    monkeypatch.setattr(mod, "_load_cfg", lambda: {})
    monkeypatch.setattr("agent.skill_commands.scan_skill_commands", lambda: {})
    monkeypatch.setattr("hermes_cli.plugins.get_plugin_commands", lambda: {})
    monkeypatch.setattr("tools.clarify_gateway.get_clarify_timeout", lambda: 15)
    return mod


class _Viewer:
    """A transport that records every frame, like one attached renderer."""

    def __init__(self):
        self.frames = queue.Queue()

    def write(self, frame):
        self.frames.put(frame)
        return True

    def wait_for(self, predicate, timeout=20.0):
        while True:
            frame = self.frames.get(timeout=timeout)
            if predicate(frame):
                return frame


def _session():
    return {
        "agent": types.SimpleNamespace(), "session_key": "session-key", "history": [],
        "history_lock": threading.Lock(), "history_version": 0, "running": False,
        "attached_images": [], "image_counter": 0, "cols": 80, "slash_worker": None,
        "show_reasoning": False, "tool_progress_mode": "all",
    }


def _slash_exec(server, viewer, sid, command, rid):
    assert server.dispatch(
        {"jsonrpc": "2.0", "id": rid, "method": "slash.exec", "params": {"session_id": sid, "command": command}},
        viewer,
    ) is None, "slash.exec must run on the RPC pool so clarify.respond can be read meanwhile"


def _respond(server, viewer, request_id, answer, rid="respond"):
    reply = server.dispatch(
        {"jsonrpc": "2.0", "id": rid, "method": "clarify.respond",
         "params": {"request_id": request_id, "answer": answer}},
        viewer,
    )
    assert reply is not None and "error" not in reply, reply


def _is_clarify(frame):
    return frame.get("method") == "event" and frame["params"].get("type") == "clarify.request"


def _install(server, monkeypatch, sid, handler):
    server._sessions[sid] = _session()
    monkeypatch.setattr("hermes_cli.plugins.get_plugin_command_handler",
                        lambda name: handler if name == "delegation" else None)


def _cleanup(server, *sids):
    for sid in sids:
        server._sessions.pop(sid, None)


def test_a_viewer_answers_the_choice_while_its_slash_exec_waits(server, monkeypatch):
    _install(server, monkeypatch, "sid-a", lambda arg: f"MODE={ask_choice('Delegation mode', CHOICES)}")
    viewer = _Viewer()
    try:
        _slash_exec(server, viewer, "sid-a", "/delegation", "exec")
        asked = viewer.wait_for(_is_clarify)["params"]
        assert asked["session_id"] == "sid-a"
        assert asked["payload"]["question"] == "Delegation mode"
        assert asked["payload"]["choices"] == LABELS
        _respond(server, viewer, asked["payload"]["request_id"], LABELS[2])
        done = viewer.wait_for(lambda frame: frame.get("id") == "exec")
    finally:
        _cleanup(server, "sid-a")
    assert done["result"]["output"] == "MODE=profile_routes", done


@pytest.mark.parametrize("answer", ["", "something unrelated"])
def test_a_cancelled_or_unknown_viewer_answer_is_none(server, monkeypatch, answer):
    _install(server, monkeypatch, "sid-b", lambda arg: f"MODE={ask_choice('Delegation mode', CHOICES)}")
    viewer = _Viewer()
    try:
        _slash_exec(server, viewer, "sid-b", "/delegation", "exec")
        asked = viewer.wait_for(_is_clarify)["params"]
        _respond(server, viewer, asked["payload"]["request_id"], answer)
        done = viewer.wait_for(lambda frame: frame.get("id") == "exec")
    finally:
        _cleanup(server, "sid-b")
    assert done["result"]["output"] == "MODE=None", done


def test_two_sessions_prompting_at_once_never_cross_replies(server, monkeypatch):
    seen_by = {}

    def handler(arg):
        seen_by[arg] = ask_choice(f"question for {arg}", [f"{arg}-one", f"{arg}-two"])
        return f"{arg}:{seen_by[arg]}"

    server._sessions["sid-1"], server._sessions["sid-2"] = _session(), _session()
    monkeypatch.setattr("hermes_cli.plugins.get_plugin_command_handler",
                        lambda name: handler if name == "delegation" else None)
    one, two = _Viewer(), _Viewer()
    try:
        _slash_exec(server, one, "sid-1", "/delegation s1", "exec-1")
        _slash_exec(server, two, "sid-2", "/delegation s2", "exec-2")
        ask_one = one.wait_for(_is_clarify)["params"]
        ask_two = two.wait_for(_is_clarify)["params"]
        assert ask_one["payload"]["question"] == "question for s1"
        assert ask_two["payload"]["question"] == "question for s2"
        # answer in the opposite order of asking: each reply settles only its own command
        _respond(server, two, ask_two["payload"]["request_id"], "s2-two", rid="r2")
        _respond(server, one, ask_one["payload"]["request_id"], "s1-one", rid="r1")
        done_one = one.wait_for(lambda frame: frame.get("id") == "exec-1")
        done_two = two.wait_for(lambda frame: frame.get("id") == "exec-2")
    finally:
        _cleanup(server, "sid-1", "sid-2")
    assert done_one["result"]["output"] == "s1:s1-one"
    assert done_two["result"]["output"] == "s2:s2-two"
    assert not asker_bound()


def test_the_asker_does_not_outlive_a_failing_handler(server, monkeypatch):
    def handler(arg):
        assert asker_bound()
        raise RuntimeError("handler failed")

    _install(server, monkeypatch, "sid-c", handler)
    viewer = _Viewer()
    try:
        _slash_exec(server, viewer, "sid-c", "/delegation", "exec")
        done = viewer.wait_for(lambda frame: frame.get("id") == "exec")
    finally:
        _cleanup(server, "sid-c")
    assert "handler failed" in done["result"]["output"]
    # a later command in the same pool thread must find no stale asker
    follow = []
    thread = threading.Thread(target=lambda: follow.append(ask_choice("q?", ["x"])))
    thread.start()
    thread.join()
    assert follow == [None]


def test_command_dispatch_never_blocks_on_a_prompt_it_cannot_hear_answered(server, monkeypatch):
    """command.dispatch runs on the reader thread that must read clarify.respond: it binds no asker."""
    monkeypatch.setattr("hermes_cli.plugins.get_plugin_command_handler",
                        lambda name: (lambda arg: f"MODE={ask_choice('Delegation mode', CHOICES)}"))
    server._sessions["sid-d"] = _session()
    viewer = _Viewer()
    try:
        reply = server.dispatch(
            {"jsonrpc": "2.0", "id": "d", "method": "command.dispatch",
             "params": {"name": "delegation", "arg": "", "session_id": "sid-d"}},
            viewer,
        )
    finally:
        _cleanup(server, "sid-d")
    assert reply["result"] == {"type": "plugin", "output": "MODE=None"}
    assert viewer.frames.empty(), "no clarify.request may be emitted from the reader thread"
