"""Keyboard steering through real CLI, agent, SDK, file tools and SQLite.

The owned HTTP peer scripts replies, not steer/cancel/dispatch behavior. Run in
an externally owned fresh process (as for the queue runtime contract); this file
does not inspect implementation source or launch a subprocess of its own.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import socket
from socketserver import ThreadingTCPServer
import sys
import threading
import time
import uuid

import pytest
import yaml
from agent.prompt_builder import STEER_MARKER_OPEN, STEER_MARKER_CLOSE


@pytest.mark.parametrize("mode", ["tool", "cancel-tool", "cancel-model", "late", "late-busy-text"])
def test_keyboard_steer_runtime_effects(tmp_path, monkeypatch, mode):
    from prompt_toolkit.application import Application
    from prompt_toolkit.application.current import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    home = tmp_path / "owned steer CLI 日本語"
    home.mkdir()
    owned_dirs = {
        "HOME": home, "USERPROFILE": home, "HERMES_HOME": home,
        "APPDATA": home / "appdata", "LOCALAPPDATA": home / "localappdata",
        "XDG_CONFIG_HOME": home / "config", "XDG_CACHE_HOME": home / "cache",
        "GH_CONFIG_DIR": home / "gh", "TEMP": home / "tmp", "TMP": home / "tmp",
    }
    for key, directory in owned_dirs.items():
        directory.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(key, str(directory))
    for key in tuple(os.environ):
        upper = key.upper()
        if (upper.endswith(("_API_KEY", "_TOKEN", "_PROXY"))
                or upper in {"HERMES_PROFILE", "HERMES_MANAGED", "HERMES_MANAGED_DIR",
                             "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"}):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("TERMINAL_CWD", str(home))
    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setenv("TERMINAL_HOME_MODE", "profile")
    monkeypatch.setenv("TERMINAL_SCRATCH_DIR", str(home / "scratch"))
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
    monkeypatch.chdir(home)
    nonce = uuid.uuid4().hex
    model = "owned-steer-model"
    anchor, clean_prompt = f"anchor-{nonce}", f"clean-{nonce}"
    steer_token = f"steer-{nonce}"
    steer = f"write the unique payload {steer_token}"
    after_cancel = f"must-discard-after-hard-{nonce}"
    busy_text = f"plain-busy-B-{nonce}"
    cancelled_reply = f"cancelled-model-reply-{nonce}"
    replies = {"anchor": f"Anchor finished {nonce}", "tool": f"Steered {nonce}",
               "late": f"Leftover finished {nonce}", "busy": f"Busy text finished {nonce}",
               "clean": f"Clean finished {nonce}"}
    first_id, second_id = f"first-{nonce}", f"steered-{nonce}"
    entered, release, ready, hard_seen, gate_exited = (threading.Event() for _ in range(5))
    cleanup_entered, release_cleanup = threading.Event(), threading.Event()
    cleanup_observations = []
    commands, wire, effects, errors, violations, threads, wakeups = [], [], [], [], [], [], []
    final_turns, settled_turns, aborted_replies, handler_threads = [], [], [], []
    persisted = []
    guard = {"active": True}
    server = peer_thread = shell = feeder = None

    def audit(event, _args):
        if guard["active"] and (event in {
            "winreg.CreateKey", "winreg.SetValue", "winreg.DeleteKey", "winreg.DeleteValue",
            "winreg.LoadKey", "winreg.SaveKey",
        }):
            violations.append(event)
            raise AssertionError(f"Owned steer test forbids side effect: {event}")

    sys.addaudithook(audit)

    def content(message):
        value = message.get("content", "")
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    def tool_messages(request):
        return [m for m in request["messages"] if m["role"] == "tool"]

    def assert_one_delivery(request):
        results = tool_messages(request)
        first = [m for m in results if m.get("tool_call_id") == first_id]
        assert len(first) == 1, results
        assert content(first[0]).count(f"\n\n{STEER_MARKER_OPEN}\n{steer}\n{STEER_MARKER_CLOSE}") == 1
        assert content(first[0]).count(steer) == 1, first
        assert content(first[0]).count("[OUT-OF-BAND USER MESSAGE") == 1, first
        assert content(first[0]).count("[/OUT-OF-BAND USER MESSAGE]") == 1, first
        assert sum(content(m).count("[OUT-OF-BAND USER MESSAGE") for m in results) == 1
        assert [m["content"] for m in request["messages"] if m["role"] == "user"] in (
            [anchor], [anchor, clean_prompt],
        )
        return first[0]

    class Peer(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def reply(self, status, data, stream=False):
            if stream:
                message = deepcopy(data["choices"][0]["message"])
                for index, call in enumerate(message.get("tool_calls", [])):
                    call["index"] = index
                chunk = {**data, "object": "chat.completion.chunk", "choices": [{
                    "index": 0, "delta": message, "finish_reason": data["choices"][0]["finish_reason"],
                }]}
                body = ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode("utf-8")
            else:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def do_GET(self):
            try:
                self.reply(200, [] if self.path.startswith("/slots") else {"data": []})
            except BaseException as exc:
                errors.append(f"peer GET: {exc!r}")

        def do_POST(self):
            held_model = False
            try:
                assert self.path == "/v1/chat/completions", self.path
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                wire.append(deepcopy(request))
                assert request["model"] == model, request["model"]
                assert self.headers.get("Authorization") == "Bearer owned-placeholder"
                user = next(m["content"] for m in reversed(request["messages"]) if m["role"] == "user")
                finish = "stop"
                if user == clean_prompt or (mode == "cancel-model" and user == anchor + "\n\n" + clean_prompt):
                    final_turns.append("clean")
                    message = {"role": "assistant", "content": replies["clean"]}
                elif user == busy_text and mode == "late-busy-text":
                    final_turns.append("busy")
                    message = {"role": "assistant", "content": replies["busy"]}
                elif user == steer and mode in {"late", "late-busy-text"}:
                    final_turns.append("late")
                    message = {"role": "assistant", "content": replies["late"]}
                else:
                    assert user == anchor, user
                    results = tool_messages(request)
                    first_done = any(m.get("tool_call_id") == first_id for m in results)
                    second_done = any(m.get("tool_call_id") == second_id for m in results)
                    if mode in {"late", "late-busy-text", "cancel-model"}:
                        assert len(wire) == 1, "The first scenario must not be retried"
                        held_model = True
                        entered.set()
                        assert release.wait(30), "Keyboard did not release the held model request"
                        message = {"role": "assistant", "content": (
                            cancelled_reply if mode == "cancel-model" else replies["anchor"])}
                        if mode in {"late", "late-busy-text"}:
                            final_turns.append("anchor")
                    elif not first_done:
                        assert len(wire) == 1, "The first tool call must not be replayed"
                        assert any(t["function"]["name"] == "write_file" for t in request.get("tools", []))
                        call_id, filename, payload = first_id, "first.json", anchor
                        finish = "tool_calls"
                    else:
                        assert mode == "tool", "Hard cancel must not request a model continuation"
                        delivery = assert_one_delivery(request)
                        if not second_done:
                            # The next actual request contains one newly delivered
                            # steer. Later requests legitimately replay its history.
                            assert len(wire) == 2
                            assert json.dumps(request["messages"], ensure_ascii=False).count(steer) == 1
                            delivered = content(delivery).split("[/OUT-OF-BAND USER MESSAGE]", 1)[0].rstrip("\n").rsplit("\n", 1)[-1]
                            assert delivered == steer
                            call_id, filename, payload = second_id, "steered.json", delivered
                            finish = "tool_calls"
                        else:
                            second = [m for m in results if m.get("tool_call_id") == second_id]
                            assert len(second) == 1
                            assert "[OUT-OF-BAND USER MESSAGE" not in content(second[0])
                            final_turns.append("tool")
                            message = {"role": "assistant", "content": replies["tool"]}
                    if finish == "tool_calls":
                        arguments = {"path": str(home / filename), "content": json.dumps({"payload": payload, "nonce": nonce})}
                        message = {"role": "assistant", "content": None, "tool_calls": [{
                            "id": call_id, "type": "function", "function": {
                                "name": "write_file", "arguments": json.dumps(arguments),
                            },
                        }]}
                self.reply(200, {"id": f"owned-{nonce}-{len(wire)}", "object": "chat.completion", "created": 0,
                                 "model": model, "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
                           stream=bool(request.get("stream")))
            except BrokenPipeError as exc:
                if mode == "cancel-model" and held_model and hard_seen.is_set():
                    aborted_replies.append(type(exc).__name__)
                else:
                    errors.append(f"unexpected aborted peer reply: {exc!r}")
            except BaseException as exc:
                errors.append(f"peer POST: {exc!r}")
            finally:
                if held_model:
                    gate_exited.set()
                self.close_connection = True

    class Server(ThreadingTCPServer):
        daemon_threads = True

        def process_request_thread(self, request, client_address):
            handler_threads.append(threading.current_thread())
            try:
                super().process_request_thread(request, client_address)
            except BaseException as exc:
                errors.append(f"peer handler: {exc!r}")

    def assert_outcome():
        assert not errors, errors
        assert not pending()
        assert len(wire) == {"tool": 4, "cancel-tool": 2, "cancel-model": 2, "late": 3, "late-busy-text": 4}[mode]
        assert all(request["messages"][0] == wire[0]["messages"][0] for request in wire)
        assert wire[0]["messages"][0]["role"] == "system"
        expected_users = ([anchor, steer, busy_text, clean_prompt] if mode == "late-busy-text"
                          else [anchor, steer, clean_prompt] if mode == "late" else [anchor, clean_prompt])
        expected_wire_users = [anchor + "\n\n" + clean_prompt] if mode == "cancel-model" else expected_users
        assert [m["content"] for m in wire[-1]["messages"] if m["role"] == "user"] == expected_wire_users
        assert [m["content"] for m in shell.conversation_history if m["role"] == "user"] == expected_wire_users
        assert [m["content"] for m in persisted if m["role"] == "user"] == expected_users
        assistant_text = [m["content"] for m in persisted if m["role"] == "assistant" and m.get("content")]
        assert assistant_text[-1] == replies["clean"]
        assert assistant_text.count(replies["clean"]) == 1
        assert all(not item["result"].get("error") for item in effects), effects
        if mode == "tool":
            assert final_turns == ["tool", "clean"]
            assert assistant_text == [replies["tool"], replies["clean"]]
            assert [Path(item["path"]).name for item in effects] == ["first.json", "steered.json"]
            assert json.loads((home / "steered.json").read_text(encoding="utf-8")) == {"payload": steer, "nonce": nonce}
            for request in wire[1:]:
                assert_one_delivery(request)
            # Count a logical tool history once, not its retransmission on each
            # wire request. The second tool batch must not get another marker.
            logical_tools = [m for m in shell.conversation_history if m["role"] == "tool"]
            assert len(logical_tools) == 2
            assert sum(content(m).count("[OUT-OF-BAND USER MESSAGE") for m in logical_tools) == 1
            assert content(logical_tools[0]).count(steer) == 1
            assert "[OUT-OF-BAND USER MESSAGE" not in content(logical_tools[1])
        elif mode in {"late", "late-busy-text"}:
            expected_stages = ["anchor", "late", "busy", "clean"] if mode == "late-busy-text" else ["anchor", "late", "clean"]
            assert final_turns == expected_stages
            assert assistant_text == [replies[stage] for stage in expected_stages]
            if mode == "late-busy-text":
                assert cleanup_entered.is_set() and release_cleanup.is_set()
                assert len(cleanup_observations) == 2
                assert cleanup_observations[0]["accepting"] is False
                assert cleanup_observations[0]["handoff"]["text"] == steer
            assert effects == []
            assert [m["content"] for m in persisted if m["role"] == "user"].count(steer) == 1
        else:
            assert hard_seen.is_set()
            assert final_turns == ["clean"]
            assert [Path(item["path"]).name for item in effects] == (["first.json"] if mode == "cancel-tool" else [])
            surfaces = [wire[1:], persisted, shell.conversation_history, effects, pending()]
            for surface in surfaces:
                serialized = json.dumps(surface, ensure_ascii=False)
                assert all(token not in serialized for token in (steer_token, after_cancel, cancelled_reply))
        if mode != "tool":
            assert not (home / "steered.json").exists()
        if mode in {"tool", "cancel-tool"}:
            assert json.loads((home / "first.json").read_text(encoding="utf-8")) == {"payload": anchor, "nonce": nonce}
        else:
            assert not (home / "first.json").exists()

    try:
        server = Server(("127.0.0.1", 0), Peer)
        port = server.server_address[1]
        real_connect, real_connect_ex, real_lookup = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        real_pair = socket.socketpair
        real_bind, real_listen = socket.socket.bind, socket.socket.listen
        pair_scope = threading.local()

        def validate(address):
            # Windows asyncio creates its wakeup pipe using stdlib socketpair().
            # Before connecting, match the listener bound/listening inside that
            # synchronous constructor, rather than allowing an arbitrary local port.
            state = getattr(pair_scope, "state", None)
            if state and address == state.get("listening"):
                return
            if not isinstance(address, tuple) or address[:2] != ("127.0.0.1", port):
                violations.append(repr(address))
                raise AssertionError(f"Only the owned HTTP peer is allowed: {address!r}")

        def connect(sock, address):
            validate(address)
            return real_connect(sock, address)

        def connect_ex(sock, address):
            validate(address)
            return real_connect_ex(sock, address)

        def lookup(host, service, *args, **kwargs):
            validate((host, int(service)))
            return real_lookup(host, service, *args, **kwargs)

        def socketpair(*args, **kwargs):
            previous = getattr(pair_scope, "state", None)
            pair_scope.state = {}
            try:
                pair = real_pair(*args, **kwargs)
                try:
                    endpoints = [sock.getsockname() for sock in pair]
                    peers = [sock.getpeername() for sock in pair]
                    assert peers == endpoints[::-1]
                    wakeups.append({"endpoints": endpoints, "peers": peers})
                except BaseException:
                    for sock in pair:
                        sock.close()
                    raise
                return pair
            finally:
                pair_scope.state = previous

        def bind(sock, address):
            result = real_bind(sock, address)
            state = getattr(pair_scope, "state", None)
            if state is not None and isinstance(address, tuple) and address[0] == "127.0.0.1":
                state["bound"] = sock
            return result

        def listen(sock, *args, **kwargs):
            result = real_listen(sock, *args, **kwargs)
            state = getattr(pair_scope, "state", None)
            if state is not None and state.get("bound") is sock:
                state["listening"] = sock.getsockname()
            return result

        monkeypatch.setattr(socket.socket, "connect", connect)
        monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
        monkeypatch.setattr(socket, "getaddrinfo", lookup)
        monkeypatch.setattr(socket, "socketpair", socketpair)
        monkeypatch.setattr(socket.socket, "bind", bind)
        monkeypatch.setattr(socket.socket, "listen", listen)
        peer_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1},
                                       name="owned-steer-peer", daemon=True)
        peer_thread.start()
        base_url = f"http://127.0.0.1:{port}/v1"
        config = {
            "model": {"default": model, "provider": "openai-compat", "base_url": base_url,
                      "context_length": 131072, "max_tokens": 128},
            "display": {"streaming": False, "tool_progress": "off", "bell_on_complete": False},
            "lsp": {"enabled": False}, "compression": {"enabled": False},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "terminal": {"backend": "local", "cwd": str(home), "home_mode": "profile",
                         "shell_init_files": [], "auto_source_bashrc": False},
            "auxiliary": {"title_generation": {"enabled": False},
                          "background_review": {"enabled": False}, "free_only": True},
            "checkpoints": {"enabled": False, "auto_prune": False},
            "fallback_providers": [], "mcp_servers": {},
        }
        if mode == "late-busy-text":
            config["display"]["busy_input_mode"] = "steer"
        (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        # This installer leaf otherwise stages per-machine Windows launchers
        # during import; it is unrelated to the steering behavior under test.
        from hermes_cli import _install_repair as early_install_repair
        monkeypatch.setattr(early_install_repair, "ensure_windows_bin_launchers", lambda *_a, **_k: [])
        from hermes_cli import runtime_provider, model_switch
        from hermes_cli.config import load_config
        import cli
        from tools import file_tools
        from tools.registry import registry

        monkeypatch.setattr(model_switch, "list_authenticated_providers", lambda **_kwargs: [])
        real_available = registry._toolset_has_exposable_tools
        monkeypatch.setattr(registry, "_toolset_has_exposable_tools", lambda toolset, entries: (
            real_available(toolset, entries) if toolset == "file" else False
        ))

        def credentials(**kwargs):
            assert kwargs.get("requested") == "openai-compat", kwargs.get("requested")
            return {"provider": "openai-compat", "api_key": "owned-placeholder", "base_url": base_url,
                    "api_mode": "chat_completions", "source": "owned-steer-peer"}

        monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", credentials)
        monkeypatch.setattr(cli, "CLI_CONFIG", load_config())
        real_write = file_tools.write_file_tool

        def write(path, content, **kwargs):
            assert Path(path).parent == home, path
            assert Path(path).name in {"first.json", "steered.json"}, path
            result = real_write(path, content, **kwargs)
            effects.append({"path": str(path), "content": content, "result": json.loads(result)})
            if Path(path).name == "first.json":
                # The real effect has happened; only its return to the actual
                # dispatcher is held, so /s and Ctrl+C race with a real tool.
                entered.set()
                try:
                    assert release.wait(30), "Keyboard did not release the first real write"
                finally:
                    gate_exited.set()
            return result

        monkeypatch.setattr(file_tools, "write_file_tool", write)
        shell = cli.HermesCLI(model=model, provider="openai-compat", api_key="owned-placeholder",
                              base_url=base_url, reasoning="high", toolsets=["file"], max_turns=6,
                              compact=True, ignore_rules=True)
        shell.streaming_enabled = False
        assert shell._ensure_runtime_credentials()
        assert shell._init_agent()
        shell.agent._memory_nudge_interval = shell.agent._skill_nudge_interval = 0
        if mode == "late-busy-text":
            assert shell.busy_input_mode == "steer"
            steering_agent = shell.agent
            real_clear_interrupt = steering_agent.clear_interrupt

            def clear_interrupt(*args, **kwargs):
                hold_cleanup = False
                # Observe the real finalizer's settled handoff. An early clear
                # or cleanup of a later turn must never enter this gate.
                with steering_agent._pending_steer_lock:
                    handoff = getattr(steering_agent, "_steer_handoff", None)
                    if (entered.is_set() and not cleanup_entered.is_set()
                            and getattr(steering_agent, "_steer_accepting", None) is False
                            and isinstance(handoff, dict) and handoff.get("text") == steer):
                        cleanup_observations.append({"accepting": False, "handoff": deepcopy(handoff)})
                        cleanup_entered.set()
                        hold_cleanup = True
                if hold_cleanup:
                    try:
                        if not release_cleanup.wait(30):
                            errors.append("Timed out holding the first settled finalizer cleanup")
                    finally:
                        release_cleanup.set()
                return real_clear_interrupt(*args, **kwargs)

            monkeypatch.setattr(steering_agent, "clear_interrupt", clear_interrupt)
        real_process = shell.process_command

        def process(command):
            result = real_process(command)
            commands.append(command)
            return result

        monkeypatch.setattr(shell, "process_command", process)
        real_after_turn = shell._tui_after_turn

        def after_turn(*args, **kwargs):
            result = real_after_turn(*args, **kwargs)
            settled_turns.append(deepcopy(shell.conversation_history))
            return result

        monkeypatch.setattr(shell, "_tui_after_turn", after_turn)
        real_threading = threading

        class ThreadingProxy:
            def __getattr__(self, name):
                return getattr(real_threading, name)

            def Thread(self, *args, **kwargs):
                thread = real_threading.Thread(*args, **kwargs)
                threads.append(thread)
                return thread

        monkeypatch.setattr(cli, "threading", ThreadingProxy())
        monkeypatch.setattr(model_switch, "_threading", ThreadingProxy())

        def wait_for(predicate, description):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if errors:
                    raise AssertionError(errors)
                if predicate():
                    return
                time.sleep(0.02)
            raise AssertionError(f"Timed out: {description}; commands={commands}; effects={effects}; wire={len(wire)}")

        def pending():
            with shell._pending_input.mutex:
                return list(shell._pending_input.queue)

        def settled(users, reply=None):
            for history in settled_turns:
                user_rows = [m["content"] for m in history if m["role"] == "user"]
                assistant_rows = [m["content"] for m in history if m["role"] == "assistant" and m.get("content")]
                if user_rows == users and (reply is None or (assistant_rows and assistant_rows[-1] == reply)):
                    return True
            return False

        def settled_members(users, reply=None):
            # The negative baseline may complete B,A. Let it finish so the
            # exact-order final oracle, rather than a timeout, reports the bug.
            for history in settled_turns:
                user_rows = [m["content"] for m in history if m["role"] == "user"]
                assistant_rows = [m["content"] for m in history if m["role"] == "assistant" and m.get("content")]
                if len(user_rows) != len(users) or set(user_rows) != set(users):
                    continue
                expected_reply = reply or {steer: replies["late"], busy_text: replies["busy"]}.get(user_rows[-1])
                if assistant_rows and assistant_rows[-1] == expected_reply:
                    return True
            return False

        def busy_text_submitted():
            # Match the real handoff lock: claiming A and enqueuing B must be
            # observed after the callback releases that lock, not half-way in.
            with steering_agent._pending_steer_lock:
                queued = pending()
                claimed = getattr(steering_agent, "_steer_handoff", None) is None
                return busy_text in queued or claimed

        scenario_users = ([anchor, steer, busy_text] if mode == "late-busy-text"
                          else [anchor, steer] if mode == "late" else [anchor])
        scenario_reply = replies["late"] if mode == "late" else replies["tool"] if mode == "tool" else None
        with ExitStack() as stack:
            pipe = stack.enter_context(create_pipe_input())
            stack.enter_context(create_app_session(input=pipe, output=DummyOutput()))

            def application(**kwargs):
                kwargs.update(input=pipe, output=DummyOutput())
                app = Application(**kwargs)
                app.pre_run_callables.append(ready.set)
                return app

            monkeypatch.setattr(cli, "Application", application)

            def feed():
                try:
                    assert ready.wait(25), "prompt_toolkit did not start"
                    pipe.send_text(anchor + "\r")
                    assert entered.wait(25), "The real tool/model did not reach its gate"
                    assert shell._agent_running
                    assert not release.is_set()

                    def command(text):
                        pipe.send_text(text + "\r")
                        wait_for(lambda: text in commands, text)

                    command("/s " + steer)
                    if mode.startswith("cancel-"):
                        pipe.send_text("\x03")
                        assert shell.agent._hard_interrupt_requested.wait(10), "Keyboard Ctrl+C did not publish hard cancel"
                        hard_seen.set()
                        assert not release.is_set(), "The gate opened before hard cancel"
                        if mode == "cancel-tool":
                            assert not gate_exited.is_set()
                            command("/s " + after_cancel)
                    release.set()
                    if mode == "late-busy-text":
                        assert cleanup_entered.wait(25), "The settled anchor finalizer did not reach cleanup"
                        assert not release_cleanup.is_set()
                        assert shell._agent_running
                        pipe.send_text(busy_text + "\r")
                        wait_for(busy_text_submitted, "plain busy text entered the queue or claimed the handoff")
                        with steering_agent._pending_steer_lock:
                            cleanup_observations.append({
                                "pending_before_release": [str(item) for item in pending()],
                                "handoff_claimed": getattr(steering_agent, "_steer_handoff", None) is None,
                            })
                        release_cleanup.set()
                        wait_for(lambda: gate_exited.is_set() and settled_members(scenario_users)
                                 and not shell._agent_running and not pending(), "both late A and plain B settled")
                    else:
                        wait_for(lambda: gate_exited.is_set() and settled(scenario_users, scenario_reply)
                                 and not shell._agent_running and not pending(), "first scenario settled")
                    pipe.send_text(clean_prompt + "\r")
                    clean_users = [anchor + "\n\n" + clean_prompt] if mode == "cancel-model" else [*scenario_users, clean_prompt]
                    if mode == "late-busy-text":
                        wait_for(lambda: "clean" in final_turns and settled_members(clean_users, replies["clean"])
                                 and not shell._agent_running and not pending(), "clean follow-up settled after both A and B")
                    else:
                        wait_for(lambda: "clean" in final_turns and settled(clean_users, replies["clean"])
                                 and not shell._agent_running and not pending(), "clean follow-up settled")
                    command("/exit")
                except BaseException as exc:
                    errors.append(f"keyboard: {exc!r}")
                    release.set()
                    shell._should_exit = True
                    if shell._app and shell._app.is_running:
                        shell._app.loop.call_soon_threadsafe(shell._app.exit)
                finally:
                    release_cleanup.set()

            feeder = threading.Thread(target=feed, name="owned-steer-keyboard", daemon=True)
            feeder.start()
            try:
                shell.run()
            finally:
                release.set()
                release_cleanup.set()
                shell._should_exit = True
                feeder.join(30)
                assert not feeder.is_alive(), "Keyboard feeder survived cleanup"

    finally:
        active_error = sys.exc_info()[1]
        release.set()
        release_cleanup.set()
        deadline = time.monotonic() + 20

        def clean(label, action):
            try:
                action()
            except BaseException as exc:
                errors.append(f"{label}: {exc!r}")

        def join(thread):
            if thread is not None and thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
                if thread.is_alive():
                    raise AssertionError(f"Owned thread survived cleanup: {thread.name}")

        if shell is not None:
            shell._should_exit = True
            clean("keyboard join", lambda: join(feeder))
            for thread in threads:
                clean(thread.name, lambda thread=thread: join(thread))
            if shell.agent is not None:
                clean("agent.close", shell.agent.close)
            if shell._session_db is not None:
                if shell.agent is not None:
                    def snapshot_persisted():
                        persisted[:] = shell._session_db.get_messages(shell.agent.session_id)
                    clean("database.snapshot", snapshot_persisted)
                clean("database.close", shell._session_db.close)
        if server is not None:
            if peer_thread is not None and peer_thread.ident is not None:
                clean("peer.shutdown", server.shutdown)
            clean("peer.close", server.server_close)
        clean("peer.join", lambda: join(peer_thread))
        for thread in handler_threads:
            clean(thread.name, lambda thread=thread: join(thread))
        guard["active"] = False
        outcome_error = None
        if active_error is None:
            try:
                assert_outcome()
            except BaseException as exc:
                outcome_error = exc
                errors.append(f"outcome: {exc!r}")
        (tmp_path / f"steer-runtime-{mode}-evidence.json").write_text(json.dumps({
            "mode": mode, "nonce": nonce, "commands": commands, "wire": wire, "effects": effects,
            "persisted": persisted, "final_turns": final_turns, "settled_turns": settled_turns,
            "errors": errors, "violations": violations, "owned_socketpairs": wakeups,
            "aborted_replies": aborted_replies, "hard_observed": hard_seen.is_set(),
            "cleanup_entered": cleanup_entered.is_set(), "cleanup_released": release_cleanup.is_set(),
            "cleanup_observations": cleanup_observations, "busy_text": busy_text,
            "body_error": repr(active_error) if active_error else None,
            "outcome_error": repr(outcome_error) if outcome_error else None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if active_error is None:
            if outcome_error is not None:
                raise outcome_error
            assert not errors, errors
            assert not violations, violations
