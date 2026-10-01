"""Actual public F08e CLI owners; synthetic credential and HTTP transport leaves."""
from __future__ import annotations

import copy
import _thread
import http.client
import json
from pathlib import Path
import socket
import threading
from types import SimpleNamespace

import pytest
import yaml


@pytest.fixture
def native(tmp_path, monkeypatch):
    home = tmp_path / "所有 home 日本語"
    home.mkdir()
    for key in ("HERMES_HOME", "HOME", "USERPROFILE", "TERMINAL_CWD"):
        monkeypatch.setenv(key, str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(home)
    config = {
        "model": {"default": "f08e-ordinary", "provider": "openai-compat", "context_length": 131072,
                  "base_url": "http://127.0.0.1:9/v1", "max_tokens": 128},
        "display": {"tool_progress": "off", "streaming": False, "bell_on_complete": False},
        "lsp": {"enabled": False}, "compression": {"enabled": False},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "terminal": {"backend": "local", "cwd": str(home)},
        "auxiliary": {"background_review": {"enabled": False}},
        "moa": {"default_preset": "owned", "presets": {"owned": {
            "reference_models": [{"provider": "openai-compat", "model": "f08e-reference"}],
            "aggregator": {"provider": "openai-compat", "model": "f08e-aggregator"}}}},
    }
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    attempts, requests, credentials, threads, agents = [], [], [], [], []
    state = {"mode": "normal", "moa_credentials": 0, "ordinary_key": "owned-placeholder",
             "entered": threading.Event(), "release": threading.Event()}

    def deny(*args, **kwargs):
        attempts.append(str(args[:1]))
        raise AssertionError("F08e forbids network/DNS")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    import httpx
    import requests as metadata_requests
    from hermes_cli import runtime_provider
    from hermes_cli.auth import AuthError

    def resolve(**kwargs):
        requested = kwargs.get("requested")
        credentials.append(dict(kwargs))
        if requested == "moa":
            state["moa_credentials"] += 1
            if state["mode"] == "credential_failure" or (
                state["mode"] == "init_credentials_failure" and state["moa_credentials"] >= 2
            ):
                raise AuthError("Owned synthetic credential refusal", code="invalid_api_key")
            if state["mode"] == "startup_cancel":
                raise KeyboardInterrupt("Owned startup cancellation")
            return {"provider": "moa", "api_key": "moa-virtual-provider", "base_url": "moa://local",
                    "api_mode": "chat_completions", "source": "owned-moa",
                    "command": "owned-moa-command", "args": ["owned-moa-arg"]}
        return {"provider": "openai-compat", "api_key": state["ordinary_key"], "base_url": "http://127.0.0.1:9/v1",
                "api_mode": "chat_completions", "source": "owned"}

    monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", resolve)

    def metadata_send(client, request, **kwargs):
        assert request.method == "GET", request.method
        response = metadata_requests.Response()
        response.status_code = 404
        response._content = b'{"error":"Owned metadata unavailable"}'
        response._content_consumed = True
        response.url = request.url
        response.request = request
        return response

    monkeypatch.setattr(metadata_requests.Session, "send", metadata_send)

    class OwnedProgressConnection:
        def __init__(self, host, port, **kwargs):
            assert host == "127.0.0.1" and port == 9

        def request(self, method, path, **kwargs):
            assert method == "GET" and path.startswith("/slots")

        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda: b"[]")

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", OwnedProgressConnection)

    def send(client, request, **kwargs):
        assert request.url.host == "127.0.0.1" and request.url.port == 9
        if shell.agent is not None and shell.agent not in agents:
            agents.append(shell.agent)
        data = json.loads(request.content)
        requests.append(copy.deepcopy(data))
        if state["mode"] == "worker_exit":
            raise SystemExit(130)
        if state["mode"] in ("late_cancel", "start_cancel") and data["model"] == "f08e-reference":
            state["entered"].set()
            assert state["release"].wait(20), "Owned delayed leaf was not released"
        if state["mode"] == "provider_failure":
            return httpx.Response(400, request=request, json={"error": {"message": "Owned provider failure", "type": "invalid_request_error"}})
        if state["mode"] == "turn_cancel" and shell.agent is not None:
            shell.agent.interrupt("Owned cancellation")
        answer = {"id": "f08e-owned", "object": "chat.completion", "created": 0, "model": data["model"],
                  "choices": [{"index": 0, "message": {"role": "assistant", "content": "所有回答"}, "finish_reason": "stop"}],
                  "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        if data.get("stream"):
            chunk = {"id": "f08e-owned", "object": "chat.completion.chunk", "created": 0, "model": data["model"],
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": "所有回答"}, "finish_reason": "stop"}]}
            return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"},
                                  content=("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode("utf-8"))
        return httpx.Response(200, request=request, json=answer)

    monkeypatch.setattr(httpx.Client, "send", send)
    import cli
    import run_agent
    from hermes_cli.config import load_config
    monkeypatch.setattr(cli, "CLI_CONFIG", load_config())
    real_threading = threading

    class ThreadingProxy:
        def __getattr__(self, name):
            return getattr(real_threading, name)

        def Thread(self, *args, **kwargs):
            thread = real_threading.Thread(*args, **kwargs)
            threads.append(thread)
            if state["mode"] == "start_cancel" and getattr(kwargs.get("target"), "__name__", "") == "run_agent":
                real_start = thread.start

                def observe_actual_start():
                    # Observe a real native Thread.start, with its real child
                    # blocked at the SDK transport, then deliver SIGINT.
                    real_start()
                    assert state["entered"].wait(20)
                    _thread.interrupt_main()

                thread.start = observe_actual_start
            return thread

    monkeypatch.setattr(cli, "threading", ThreadingProxy())
    monkeypatch.setattr(run_agent, "threading", ThreadingProxy())
    shell = cli.HermesCLI(model="f08e-ordinary", provider="openai-compat", api_key="owned-placeholder",
                          base_url="http://127.0.0.1:9/v1", reasoning="high", toolsets=[], max_turns=2,
                          compact=True, ignore_rules=True)
    shell.streaming_enabled = False
    shell._single_query_mode = True
    assert shell._ensure_runtime_credentials()
    assert shell._init_agent()
    agents.append(shell.agent)
    shell.agent._memory_nudge_interval = shell.agent._skill_nudge_interval = 0
    shell.conversation_history = [{"role": "user", "content": "親の会話"}, {"role": "assistant", "content": "親の回答"}]

    def join():
        for thread in threads:
            if thread.ident is not None and not thread.name.startswith("relay-scope-op"):
                thread.join(timeout=30)
                assert not thread.is_alive(), thread.name

    try:
        yield SimpleNamespace(shell=shell, state=state, requests=requests, credentials=credentials,
                              threads=threads, join=join, agents=agents, home=home)
    finally:
        join()
        if shell.agent is not None and shell.agent not in agents:
            agents.append(shell.agent)
        for agent in agents:
            agent.close()
        if shell._session_db is not None:
            shell._session_db.close()
        assert not attempts, attempts


def capture(shell):
    before = shell._snapshot_model_runtime()
    for key in ("acp_command", "acp_args", "_provider_source", "_credential_pool"):
        before[key] = getattr(shell, key)
    return before


def restored(native, before):
    shell = native.shell
    for key in ("model", "provider", "requested_provider", "_explicit_api_key", "_explicit_base_url", "api_key", "base_url", "api_mode",
                "acp_command", "acp_args", "_provider_source", "_credential_pool"):
        assert getattr(shell, key) == before[key], (key, getattr(shell, key), before[key])
    assert not shell._pending_moa_disable_after_turn
    assert shell._pending_moa_restore_model is None


@pytest.mark.parametrize("mode", ["credential_failure", "init_credentials_failure", "startup_cancel"])
def test_public_moa_startup_restores_runtime(native, mode):
    shell = native.shell
    before = capture(shell)
    native.state["mode"] = mode
    assert shell.process_command("/moa 所有プロンプト") is True
    payload = shell._pending_agent_seed
    if mode == "startup_cancel":
        with pytest.raises(KeyboardInterrupt, match="Owned startup"):
            shell.chat(payload)
    else:
        assert shell.chat(payload) is None
    restored(native, before)


@pytest.mark.parametrize("command", ["/refine", "/refine   "])
def test_bare_manual_refine_runs_with_automatic_disabled(native, command):
    shell = native.shell
    before = copy.deepcopy(shell.conversation_history)
    assert shell.process_command(command) is True
    native.join()
    assert any(t.name == "bg-review" for t in native.threads), "Bare manual refine incorrectly followed automatic disabled gate"
    assert native.requests, "Actual bare refine child did not reach transport"
    assert shell.conversation_history == before


@pytest.mark.parametrize("gate", ["automatic", "child", "empty"])
def test_refine_preserves_existing_negative_gates(native, gate):
    shell = native.shell
    if gate == "automatic":
        shell.agent._spawn_background_review(shell.conversation_history, review_memory=True)
    else:
        if gate == "child":
            shell.agent._delegate_depth = 1
        else:
            shell.conversation_history = []
        assert shell.process_command("/refine") is True
    native.join()
    assert not any(t.name == "bg-review" for t in native.threads)
    assert not native.requests


def test_focused_manual_refine_keeps_existing_restricted_worker(native):
    shell = native.shell
    assert shell.chat("所有 seed")
    parent = shell.agent
    prefix = parent._cached_system_prompt
    history = copy.deepcopy(shell.conversation_history)
    native.requests.clear()
    assert shell.process_command("/refine 所有 focus") is True
    native.join()
    assert native.requests, "Actual refine child did not reach transport"
    assert parent._cached_system_prompt == prefix
    assert shell.conversation_history == history
    assert parent._background_review_agent is None and parent._active_children == []


@pytest.mark.parametrize("mode", ["normal", "provider_failure", "turn_cancel", "worker_exit"])
def test_public_moa_real_agent_turn_restores_none_inputs_and_ordinary_primary(native, mode, monkeypatch):
    shell = native.shell
    assert shell.chat("所有 seed")
    parent = shell.agent
    prefix = parent._cached_system_prompt
    reasoning = copy.deepcopy(shell.reasoning_config)
    shell._explicit_api_key = shell._explicit_base_url = None
    shell.api_key = shell.base_url = shell.api_mode = None
    before = capture(shell)
    native.requests.clear()
    native.state["mode"] = mode
    assert shell.process_command("/moa 所有 one turn") is True
    if mode == "worker_exit":
        exits = []
        monkeypatch.setattr(threading, "excepthook", lambda args: exits.append(args.exc_value))
        response = shell.chat(shell._pending_agent_seed)
        assert len(exits) == 1 and isinstance(exits[0], SystemExit) and exits[0].code == 130
    else:
        response = shell.chat(shell._pending_agent_seed)
    native.join()
    assert native.requests, "Actual MoA provider did not reach scripted transport"
    restored(native, before)
    assert shell.agent is parent
    assert parent._primary_runtime == before["agent_primary_runtime"]
    assert parent._cached_system_prompt == prefix
    assert shell.reasoning_config == reasoning
    if mode == "turn_cancel":
        assert shell._last_turn_interrupted
    native.state["mode"] = "normal"
    assert shell.chat("次の通常ターン")
    assert shell.provider == "openai-compat" and shell.model == "f08e-ordinary"
    assert shell.agent is parent and parent._cached_system_prompt == prefix
    if mode == "normal":
        assert response == "所有回答"
        assert shell.process_command("/moa 二度目") is True
        assert shell.chat(shell._pending_agent_seed)
        assert shell.agent is parent and shell.provider == "openai-compat"


def test_public_moa_repeated_staging_restores_original_parent(native):
    shell = native.shell
    parent = shell.agent
    before = capture(shell)
    assert shell.process_command("/moa 最初") is True
    record = shell._pending_moa_restore_model
    assert shell.process_command("/moa 二番目") is True
    assert shell._pending_moa_restore_model is record
    assert shell.chat(shell._pending_agent_seed) == "所有回答"
    restored(native, before)
    assert shell.agent is parent


def test_credentials_preserve_matching_agent_and_rebuild_real_rotation(native):
    shell = native.shell
    parent = shell.agent
    shell.api_key = shell.base_url = shell.api_mode = None
    assert shell._ensure_runtime_credentials()
    assert shell.agent is parent
    native.state["ordinary_key"] = "owned-rotated-key"
    assert shell._ensure_runtime_credentials()
    assert shell.agent is None and shell.api_key == "owned-rotated-key"


def test_public_moa_abandoned_worker_cannot_clear_next_record(native):
    shell = native.shell
    parent = shell.agent
    before = capture(shell)
    native.state["mode"] = "late_cancel"

    def interrupt():
        assert native.state["entered"].wait(20)
        active = shell.agent
        assert shell.process_command("/moa 実行中の予約") is True
        native.state["busy_agent_preserved"] = shell.agent is active
        shell._should_exit = True
        shell._interrupt_queue.put("所有 late cancellation")

    actor = threading.Thread(target=interrupt)
    actor.start()
    try:
        assert shell.process_command("/moa 遅いターン") is True
        shell.chat(shell._pending_agent_seed)
        restored(native, before)
        assert shell.agent is parent
        assert native.state["busy_agent_preserved"], "An in-flight MoA command must not detach its running agent"
        temporary = next(a for a in native.agents if a is not parent)
        assert temporary.client is not None, "Must not retire a running worker"
        assert shell.process_command("/moa 次の予約") is True
        next_record = shell._pending_moa_restore_model
    finally:
        native.state["release"].set()
        actor.join(timeout=25)
        native.join()
        shell._should_exit = False
    assert shell._pending_moa_restore_model is next_record
    assert temporary.client is None, "Late worker must retire its captured temporary agent"
    native.state["mode"] = "normal"
    assert shell.chat(shell._pending_agent_seed) == "所有回答"
    assert shell.agent is parent


def test_public_moa_start_boundary_cancel_keeps_live_worker_client(native):
    shell = native.shell
    parent = shell.agent
    before = capture(shell)
    native.state["mode"] = "start_cancel"
    assert shell.process_command("/moa 開始境界") is True
    try:
        with pytest.raises(KeyboardInterrupt):
            shell.chat(shell._pending_agent_seed)
        restored(native, before)
        assert shell.agent is parent
        temporary = next(a for a in native.agents if a is not parent)
        assert temporary.client is not None, "A started live worker must retain its client until it finishes"
    finally:
        native.state["release"].set()
        native.join()
    assert temporary.client is None
    native.state["mode"] = "normal"
    assert shell.chat("取消後の通常ターン") == "所有回答"
    assert shell.agent is parent
