"""Classic CLI keyboard -> queue -> real agent/file tool, with an owned HTTP peer.

The model peer is deterministic; this proves dispatch and consumption, not model
quality. The prompt_toolkit input/output seam is replaced, not the queue worker,
chat(), SDK transport, tool dispatcher, or filesystem backend.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socket
from socketserver import ThreadingTCPServer
import sys
import threading
import time
import uuid

import yaml


def test_keyboard_queue_edits_reach_file_tool_once_in_order(tmp_path, monkeypatch):
    from prompt_toolkit.application import Application
    from prompt_toolkit.application.current import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    home = tmp_path / "owned CLI 日本語"
    home.mkdir()
    (home / "home").mkdir()
    for key in ("HOME", "USERPROFILE", "HERMES_HOME", "TERMINAL_CWD"):
        monkeypatch.setenv(key, str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setenv("TERMINAL_HOME_MODE", "profile")
    monkeypatch.setenv("TERMINAL_SCRATCH_DIR", str(home / "scratch"))
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
    monkeypatch.chdir(home)
    nonce = uuid.uuid4().hex
    anchor = f"hold-{nonce}"
    payloads = {key: f"{key}-{nonce}" for key in ("A", "B", "B2", "C", "cleared")}
    entered, release, ready = (threading.Event() for _ in range(3))
    commands, wire, effects, errors, violations, threads, wakeups = [], [], [], [], [], [], []
    final_turns = []
    registry_guard = {"active": True}

    def registry_audit(event, args):
        if registry_guard["active"] and event in {
            "winreg.CreateKey", "winreg.SetValue", "winreg.DeleteKey", "winreg.DeleteValue",
            "winreg.LoadKey", "winreg.SaveKey",
        }:
            violations.append(event)
            raise AssertionError(f"Owned CLI test forbids registry writes: {event}")

    sys.addaudithook(registry_audit)

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
            self.close_connection = True

        def do_GET(self):
            self.reply(200, [] if self.path.startswith("/slots") else {"data": []})

        def do_POST(self):
            try:
                assert self.path == "/v1/chat/completions", self.path
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                wire.append(deepcopy(data))
                assert data["model"] == "fxa01-owned", data["model"]
                last_user = next(m["content"] for m in reversed(data["messages"]) if m["role"] == "user")
                if last_user == anchor:
                    entered.set()
                    assert release.wait(30), "Queue controls did not release the anchor turn"
                    message, finish = {"role": "assistant", "content": "Anchor finished"}, "stop"
                else:
                    key = next((k for k, value in payloads.items() if value == last_user), None)
                    assert key is not None, last_user
                    call_id = f"write-{key}-{nonce}"
                    completed = any(m.get("tool_call_id") == call_id for m in data["messages"] if m["role"] == "tool")
                    if completed:
                        final_turns.append(key)
                        message, finish = {"role": "assistant", "content": f"Recorded {key}-{nonce}"}, "stop"
                    else:
                        assert any(t["function"]["name"] == "write_file" for t in data.get("tools", []))
                        arguments = {"path": str(home / f"{key}.json"), "content": json.dumps({"payload": key, "nonce": nonce})}
                        message = {"role": "assistant", "content": None, "tool_calls": [{
                            "id": call_id, "type": "function", "function": {
                                "name": "write_file", "arguments": json.dumps(arguments),
                            },
                        }]}
                        finish = "tool_calls"
                self.reply(200, {"id": f"owned-{nonce}-{len(wire)}", "object": "chat.completion", "created": 0,
                                 "model": "fxa01-owned", "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}, stream=bool(data.get("stream")))
            except BaseException as exc:
                errors.append(repr(exc))
                self.reply(400, {"error": {"message": "Owned peer rejected the request", "type": "invalid_request_error"}})

    class Server(ThreadingTCPServer):
        daemon_threads = True

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
    peer_thread = threading.Thread(target=server.serve_forever, name="owned-queue-peer", daemon=True)
    peer_thread.start()
    base_url = f"http://127.0.0.1:{port}/v1"
    config = {
        "model": {"default": "fxa01-owned", "provider": "openai-compat", "base_url": base_url,
                  "context_length": 131072, "max_tokens": 128},
        "display": {"streaming": False, "tool_progress": "off", "bell_on_complete": False},
        "lsp": {"enabled": False}, "compression": {"enabled": False},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "terminal": {"backend": "local", "cwd": str(home), "home_mode": "profile",
                     "shell_init_files": [], "auto_source_bashrc": False},
        "auxiliary": {"background_review": {"enabled": False}, "free_only": True},
        "checkpoints": {"enabled": False, "auto_prune": False},
        "fallback_providers": [], "mcp_servers": {},
    }
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    shell = None
    feeder = None
    try:
        from hermes_cli import runtime_provider
        from hermes_cli import model_switch
        from hermes_cli.config import load_config
        import cli
        from tools import file_tools
        from tools.registry import registry

        # Provider catalog discovery is unrelated to queue consumption. Keep
        # its worker real, resolving discovery to an owned offline inventory.
        monkeypatch.setattr(model_switch, "list_authenticated_providers", lambda **_kwargs: [])
        real_available = registry._toolset_has_exposable_tools
        monkeypatch.setattr(registry, "_toolset_has_exposable_tools", lambda toolset, entries: (
            real_available(toolset, entries) if toolset == "file" else False
        ))

        # Credentials are synthetic. The SDK still performs a real HTTP request.
        def credentials(**kwargs):
            assert kwargs.get("requested") == "openai-compat", kwargs.get("requested")
            return {"provider": "openai-compat", "api_key": "owned-placeholder", "base_url": base_url,
                    "api_mode": "chat_completions", "source": "owned-queue-peer"}

        monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", credentials)
        monkeypatch.setattr(cli, "CLI_CONFIG", load_config())
        real_write = file_tools.write_file_tool

        def write(path, content, **kwargs):
            assert Path(path).parent == home
            result = real_write(path, content, **kwargs)
            effects.append({"path": str(path), "content": content, "result": json.loads(result)})
            return result

        monkeypatch.setattr(file_tools, "write_file_tool", write)
        shell = cli.HermesCLI(model="fxa01-owned", provider="openai-compat", api_key="owned-placeholder",
                              base_url=base_url, reasoning="high", toolsets=["file"], max_turns=6,
                              compact=True, ignore_rules=True)
        shell.streaming_enabled = False
        assert shell._ensure_runtime_credentials()
        assert shell._init_agent()
        shell.agent._memory_nudge_interval = shell.agent._skill_nudge_interval = 0
        real_process = shell.process_command

        def process(command):
            result = real_process(command)
            commands.append(command)
            return result

        monkeypatch.setattr(shell, "process_command", process)
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
                    assert entered.wait(25), "Real anchor request did not reach the HTTP peer"
                    prefix = deepcopy(shell.conversation_history)

                    def command(text):
                        pipe.send_text(text + "\r")
                        wait_for(lambda: text in commands, text)

                    command("/queue add " + payloads["cleared"])
                    command("/queue clear")
                    assert pending() == []
                    for key in ("A", "B", "C"):
                        command("/queue add " + payloads[key])
                    command("/queue list")
                    command("/q edit 2 " + payloads["B2"])
                    command("/queue move 3 1")
                    command("/queue rm 2")
                    assert pending() == [payloads["C"], payloads["B2"]]
                    command("/queue rm 99")
                    command("/queue move 1 nope")
                    assert pending() == [payloads["C"], payloads["B2"]]
                    command("/queue add list")
                    assert pending() == [payloads["C"], payloads["B2"], "list"]
                    command("/queue rm 3")
                    assert shell.conversation_history == prefix
                    release.set()
                    wait_for(lambda: final_turns == ["C", "B2"] and not shell._agent_running and not pending(), "both real queued turns complete")
                    command("/exit")
                except BaseException as exc:
                    errors.append(repr(exc))
                    release.set()
                    shell._should_exit = True
                    if shell._app and shell._app.is_running:
                        shell._app.loop.call_soon_threadsafe(shell._app.exit)

            feeder = threading.Thread(target=feed, name="owned-queue-keyboard", daemon=True)
            feeder.start()
            try:
                shell.run()
            finally:
                release.set()
                shell._should_exit = True
                feeder.join(30)
                assert not feeder.is_alive(), "Keyboard feeder survived cleanup"
        assert not errors, errors
        assert [Path(item["path"]).stem for item in effects] == ["C", "B2"]
        assert all(not item["result"].get("error") for item in effects), effects
        for key in ("C", "B2"):
            assert json.loads((home / f"{key}.json").read_text(encoding="utf-8")) == {"payload": key, "nonce": nonce}
        assert not (home / "A.json").exists()
        assert not (home / "cleared.json").exists()
        assert final_turns == ["C", "B2"]
        assert len(wire) == 5, "One anchor plus two tool/final pairs must reach the real SDK transport"
        assert all(request["messages"][0] == wire[0]["messages"][0] for request in wire)
        persisted = shell._session_db.get_messages(shell.agent.session_id)
        assert [message["content"] for message in persisted if message["role"] == "user"] == [
            anchor, payloads["C"], payloads["B2"],
        ]
        assert [message["content"] for message in persisted if message["role"] == "assistant" and message.get("content")] == [
            "Anchor finished", f"Recorded C-{nonce}", f"Recorded B2-{nonce}",
        ]
    finally:
        active_error = sys.exc_info()[1]
        release.set()
        deadline = time.monotonic() + 20

        def clean(label, action):
            try:
                action()
            except BaseException as exc:
                errors.append(f"{label}: {exc!r}")

        def join(thread):
            if thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
                if thread.is_alive():
                    raise AssertionError(f"Owned thread survived cleanup: {thread.name}")

        if shell is not None:
            shell._should_exit = True
            if feeder is not None:
                clean("keyboard join", lambda: join(feeder))
            for thread in threads:
                clean(thread.name, lambda thread=thread: join(thread))
            if shell.agent is not None:
                clean("agent.close", shell.agent.close)
            if shell._session_db is not None:
                clean("database.close", shell._session_db.close)
        clean("peer.shutdown", server.shutdown)
        clean("peer.close", server.server_close)
        clean("peer.join", lambda: join(peer_thread))
        registry_guard["active"] = False
        (tmp_path / "queue-runtime-evidence.json").write_text(json.dumps({
            "nonce": nonce, "commands": commands, "wire": wire, "effects": effects,
            "final_turns": final_turns, "errors": errors, "violations": violations,
            "owned_socketpairs": wakeups, "body_error": repr(active_error) if active_error else None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if active_error is None:
            assert not errors, errors
            assert not violations, violations
