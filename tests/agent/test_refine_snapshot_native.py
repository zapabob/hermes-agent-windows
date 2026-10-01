"""Owned Windows threads, real /refine dispatch/spawn/worker, scripted child.

The fork-construction boundary is doubled; no provider is instantiated. These
tests prove history handoff/isolation, not provider recovery or persisted DB
corruption. All reachable message shapes here are JSON dict/list containers.
"""
from __future__ import annotations

import copy
import inspect
import json
import socket
import threading
from types import SimpleNamespace

import pytest


def _history():
    return [
        {"role": "user", "content": [
            {"type": "text", "text": "質問 日本語\n\t preserve "},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]},
        {"role": "assistant", "content": "回答 \n", "tool_calls": [
            {"id": "call-owned", "type": "function", "function": {
                "name": "read_file", "arguments": '{"path":"日本語.txt"}'}}
        ], "reasoning_details": [{"type": "reasoning.text", "text": "説明\n",
                                  "metadata": {"tags": ["original"]}}]},
    ]


_PATHS = {
    "content": (0, "content", 0, "text"),
    "tool_calls": (1, "tool_calls", 0, "function", "arguments"),
    "reasoning_details": (1, "reasoning_details", 0, "metadata", "tags", 0),
}


def _change(history, shape):
    node = history
    for key in _PATHS[shape][:-1]:
        node = node[key]
    node[_PATHS[shape][-1]] = "changed 日本語\n"


def _bytes(history):
    return json.dumps(history, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@pytest.fixture
def harness(monkeypatch, tmp_path):
    # Collection is already under the canonical runner's owned HOME/HERMES_HOME.
    # The individual test owns all resources and joins every thread it starts.
    owned = tmp_path / "日本語 refine owned"
    owned.mkdir()
    for key in ("HOME", "USERPROFILE", "HERMES_HOME", "TMP", "TEMP"):
        monkeypatch.setenv(key, str(owned))
    monkeypatch.chdir(owned)
    attempts = []

    def denied(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("F08 owned test forbids network")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)

    import cli
    import run_agent
    import agent.background_review as review
    import model_tools

    state = SimpleNamespace(
        gate=threading.Event(), started=threading.Event(), threads=[], errors=[],
        forks=[], calls=[], snapshot=None, action=lambda history: None,
        network=attempts, notes=[], task_cfg={}, enabled=True,
    )
    parent = object.__new__(run_agent.AIAgent)
    parent.valid_tool_names = {"memory", "skill_manage"}
    parent._delegate_depth = 0
    parent._background_review_run = None
    parent._background_review_agent = None
    parent._background_review_lock = threading.Lock()
    parent._active_children = []
    parent._active_children_lock = threading.Lock()
    parent.client = None
    parent.provider = "scripted-no-provider"
    parent._session_db = None
    parent.session_id = "owned-refine"
    parent._session_messages = _history()
    parent._cached_system_prompt = "owned stable system 日本語\n"
    parent.memory_notifications = "off"
    parent.background_review_callback = None
    parent._safe_print = lambda *args, **kwargs: None
    parent._emit_auxiliary_failure = lambda *args: state.errors.append(args)

    class Child:
        _memory_enabled = False
        _user_profile_enabled = False
        _session_messages = []

        def run_conversation(self, *, user_message, conversation_history):
            state.calls.append((user_message, copy.deepcopy(conversation_history)))
            state.action(conversation_history)
            return {"final_response": "Nothing to save.", "messages": conversation_history}

        def shutdown_memory_provider(self):
            pass

        def close(self):
            pass

    def build(parent_arg, task_cfg, *, max_iterations):
        assert parent_arg is parent
        assert max_iterations == review._REVIEW_MAX_ITERATIONS
        state.forks.append(task_cfg)
        return Child(), {}, False  # same-runtime full replay; no routed digest

    monkeypatch.setattr(review, "build_cache_parity_fork", build)
    # Only discovery at the child boundary is scripted; the actual worker installs
    # and clears its existing whitelist/approval callback and cancellation token.
    monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **kw: [])
    monkeypatch.setattr(review, "load_background_review_settings",
                        lambda: (state.enabled, state.task_cfg))
    monkeypatch.setattr(review, "_background_review_task_config", lambda *args: state.task_cfg)
    monkeypatch.setattr(cli, "_cprint", lambda *args, **kw: state.notes.append(args))

    original_spawn = review.spawn_background_review_thread

    def observe_spawn(*args, **kwargs):
        result = original_spawn(*args, **kwargs)  # tested spawn is executed unchanged
        state.snapshot = inspect.getclosurevars(result[0]).nonlocals["messages_snapshot"]
        return result

    monkeypatch.setattr(review, "spawn_background_review_thread", observe_spawn)
    real_thread = threading.Thread

    def owned_thread(*, target, daemon, name):
        assert name == "bg-review"

        def gated():
            state.started.set()
            if not state.gate.wait(10):
                state.errors.append(("fixture thread gate timeout",))
                return
            try:
                target()  # actual propagated target -> actual review worker
            except BaseException as exc:
                state.errors.append((type(exc).__name__, str(exc)))

        thread = real_thread(target=gated, daemon=daemon, name="F08-owned-bg-review")
        state.threads.append(thread)
        return thread

    # Avoid patching Python's shared threading.Thread, which other owners use.
    monkeypatch.setattr(run_agent, "threading", SimpleNamespace(Thread=owned_thread))
    shell = object.__new__(cli.HermesCLI)
    shell.agent = parent
    shell.conversation_history = parent._session_messages
    shell.session_id = parent.session_id
    state.parent, state.shell, state.review = parent, shell, review

    def dispatch(command="/refine"):
        assert cli.HermesCLI.process_command(shell, command) is True
        if state.threads:
            assert state.started.wait(5), "fixture thread did not start"
        return state.snapshot

    def finish():
        state.gate.set()
        for thread in state.threads:
            thread.join(10)
            assert not thread.is_alive(), "owned worker did not finish"
        assert not state.errors, f"fixture/worker API failure: {state.errors!r}"
        assert not state.network, "unexpected network attempt"
        assert parent._active_children == []
        assert parent._background_review_agent is None

    state.dispatch, state.finish = dispatch, finish
    yield state
    state.gate.set()
    for thread in state.threads:
        thread.join(10)
        assert not thread.is_alive()


@pytest.mark.parametrize("shape", _PATHS)
def test_parent_mutation_after_public_spawn_cannot_rewrite_worker_history(harness, shape):
    before = copy.deepcopy(harness.parent._session_messages)
    prompt = harness.parent._cached_system_prompt.encode("utf-8")
    harness.dispatch("/refine Keep Case 日本語")
    _change(harness.parent._session_messages, shape)
    harness.finish()
    assert len(harness.calls) == 1, "worker handoff not reached"
    assert harness.calls[0][1] == before, "parent mutation leaked into worker snapshot"
    assert harness.parent._cached_system_prompt.encode("utf-8") == prompt


@pytest.mark.parametrize("shape", _PATHS)
def test_child_snapshot_mutation_before_execution_cannot_rewrite_parent(harness, shape):
    before = _bytes(harness.parent._session_messages)
    snapshot = harness.dispatch()
    _change(snapshot, shape)
    harness.finish()
    assert len(harness.calls) == 1
    assert _bytes(harness.parent._session_messages) == before, "child snapshot aliased parent canonical messages"


@pytest.mark.parametrize("shape", _PATHS)
def test_actual_worker_child_boundary_mutation_cannot_rewrite_parent(harness, shape):
    before = _bytes(harness.parent._session_messages)
    harness.action = lambda history: _change(history, shape)
    harness.dispatch()
    harness.finish()
    assert len(harness.calls) == 1
    assert _bytes(harness.parent._session_messages) == before, "worker mutation leaked into canonical history"


def test_unmodified_handoff_preserves_supported_json_leaves_and_focus(harness):
    before = copy.deepcopy(harness.parent._session_messages)
    harness.dispatch("/refine Keep Case 日本語")
    harness.finish()
    assert harness.calls[0][1] == before
    assert "Keep Case 日本語" in harness.calls[0][0]
    assert "Other tools will be denied" in harness.calls[0][0]


@pytest.mark.parametrize("command", ["/refine", "/refine   ", "/refine \t"])
def test_blank_focus_keeps_existing_automatic_prompt_bytes(harness, command):
    harness.dispatch(command)
    harness.finish()
    expected = harness.review._COMBINED_REVIEW_PROMPT + (
        "\n\nYou can only call memory and skill management tools. Other tools will be denied "
        "at runtime — do not attempt them.")
    assert harness.calls[0][0] == expected


@pytest.mark.parametrize("gate", ["disabled", "delegate"])
def test_blank_focus_retains_existing_spawn_gates(harness, gate):
    if gate == "disabled":
        harness.enabled = False
    else:
        harness.parent._delegate_depth = 1
    assert harness.dispatch() is None
    harness.finish()
    assert not harness.threads and not harness.forks and not harness.calls


@pytest.mark.parametrize("gate", ["disabled", "delegate"])
def test_nonblank_focus_retains_existing_explicit_request_contract(harness, gate):
    if gate == "disabled":
        harness.enabled = False
    else:
        harness.parent._delegate_depth = 1
    harness.dispatch("/refine Keep Case 日本語")
    harness.finish()
    assert len(harness.calls) == 1


def test_cancel_before_owned_worker_execution_fences_child_construction(harness):
    before = _bytes(harness.parent._session_messages)
    harness.dispatch()
    token = harness.parent._background_review_run
    assert token is not None
    token.cancel()
    harness.finish()
    assert token.request_done.is_set()
    assert harness.parent._background_review_run is None
    assert not harness.forks and not harness.calls
    assert _bytes(harness.parent._session_messages) == before
