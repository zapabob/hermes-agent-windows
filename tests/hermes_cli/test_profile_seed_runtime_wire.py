"""Public profile creation -> fresh CLI turn -> fresh CLI resume over actual HTTP."""
from __future__ import annotations

import argparse
import asyncio
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import socket
from socketserver import ThreadingTCPServer
import subprocess
import sys
import threading
import uuid

import pytest
import yaml


@pytest.mark.parametrize("entry", ["cli", "rest", "rpc"])
def test_new_profile_first_turn_and_fresh_resume_use_the_inherited_route(tmp_path, monkeypatch, entry):
    home = tmp_path / "profile-route-owned"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for key, value in {"HERMES_HOME": home, "HOME": tmp_path, "USERPROFILE": tmp_path}.items():
        monkeypatch.setenv(key, str(value))
    token = "owned-profile-token-" + uuid.uuid4().hex
    monkeypatch.setenv("OWNED_PROFILE_TOKEN", token)
    nonce = uuid.uuid4().hex
    requests, errors, violations = [], [], []

    class Peer(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def reply(self, body, content_type="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def do_GET(self):
            self.reply(b"[]" if self.path.startswith("/slots") else b'{"data":[]}')

        def do_POST(self):
            try:
                assert self.path == "/v1/chat/completions"
                assert self.headers.get("Authorization") == "Bearer " + token
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert data["model"] == "owned-profile-model", data["model"]
                users = [m["content"] for m in data["messages"] if m["role"] == "user"]
                requests.append({"model": data["model"], "users": users, "auth_matches": True})
                message = {"role": "assistant", "content": "Owned answer: " + users[-1]}
                answer = {"id": "owned-" + nonce, "model": data["model"], "created": 0,
                          "object": "chat.completion", "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
                if data.get("stream"):
                    answer["object"] = "chat.completion.chunk"
                    answer["choices"] = [{"index": 0, "delta": message, "finish_reason": "stop"}]
                    body = ("data: " + json.dumps(answer) + "\n\ndata: [DONE]\n\n").encode("utf-8")
                    self.reply(body, "text/event-stream")
                else:
                    self.reply(json.dumps(answer).encode("utf-8"))
            except BaseException as exc:
                errors.append(repr(exc))
                self.reply(b'{"error":{"message":"Owned peer rejected request"}}')

    class Server(ThreadingTCPServer):
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Peer)
    port = server.server_address[1]
    peer = threading.Thread(target=server.serve_forever, daemon=True)
    peer.start()
    # Establish the ASGI runner's own Windows wakeup sockets before restricting
    # connections. Its loop and the owned peer remain fixture-owned resources.
    runner = asyncio.Runner()
    runner.get_loop()
    real_connect, real_connect_ex, real_lookup = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def validate(address):
        if address[:2] != ("127.0.0.1", port):
            violations.append(str(address))
            raise AssertionError(f"Only the owned model peer is allowed: {address!r}")

    def connect(sock, address):
        validate(address)
        return real_connect(sock, address)

    def connect_ex(sock, address):
        validate(address)
        return real_connect_ex(sock, address)

    def lookup(host, service, *args, **kwargs):
        validate((host, int(service)))
        return real_lookup(host, service, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    from hermes_cli import profiles
    from hermes_cli.config import DEFAULT_CONFIG, read_user_config_raw
    monkeypatch.setattr(profiles, "seed_profile_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(profiles, "check_alias_collision", lambda _name: True)
    source = {"model": {"provider": "lab", "default": "owned-profile-model", "context_length": 131072},
              "providers": {"lab": {"api": f"http://127.0.0.1:{port}/v1", "api_key": "${OWNED_PROFILE_TOKEN}"}},
              "_config_version": DEFAULT_CONFIG["_config_version"]}
    source_path = home / "config.yaml"
    source_path.write_text(yaml.safe_dump(source), encoding="utf-8")
    source_bytes = source_path.read_bytes()
    reports = []
    try:
        if entry == "cli":
            from hermes_cli.main import cmd_profile
            from hermes_cli.subcommands.profile import build_profile_parser
            parser = argparse.ArgumentParser()
            build_profile_parser(parser.add_subparsers(), cmd_profile=cmd_profile)
            args = parser.parse_args(["profile", "create", "child", "--no-alias", "--no-skills"])
            args.func(args)
            target = profiles.get_profile_dir("child")
        elif entry == "rpc":
            # tui_gateway.server import-time prefetch hits api.github.com via
            # hermes_cli.banner.prefetch_update_check (daemon thread). Keep this
            # network-isolation fixture offline by stubbing before first import.
            import hermes_cli.banner as banner

            monkeypatch.setattr(banner, "prefetch_update_check", lambda: None)
            import tui_gateway.server as gateway
            response = gateway._methods["profiles.create"]("owned", {"name": "child", "no_skills": True, "share_auth": True})
            assert "error" not in response, response
            target = Path(response["result"]["path"])
        else:
            import httpx
            from fastapi import FastAPI
            from hermes_cli.web_routers.profiles import router
            app = FastAPI()
            app.include_router(router)

            async def create():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://owned-api") as client:
                    response = await client.post("/api/profiles", json={"name": "child", "no_skills": True})
                    assert response.status_code == 200, response.text
                    return Path(response.json()["path"])

            target = runner.run(create())
        raw = read_user_config_raw(target / "config.yaml")
        assert raw["model"] == source["model"]
        assert raw["providers"] == source["providers"]
        assert token not in (target / "config.yaml").read_text(encoding="utf-8")
        assert source_path.read_bytes() == source_bytes
        # Auxiliary title generation deliberately makes an additional model
        # request. Use its supported per-profile opt-out for this two-turn
        # primary-inference proof; routing and SDK transports remain real.
        from hermes_cli.config import set_config_value
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override
        scope = set_hermes_home_override(str(target))
        try:
            set_config_value("auxiliary.title_generation.enabled", "false")
        finally:
            reset_hermes_home_override(scope)
        for index in range(2):
            manifest = {"profile_home": str(target), "port": port, "prompt": f"{nonce}-{index}",
                        "resume": reports[-1]["session_id"] if reports else None,
                        "report_path": str(tmp_path / f"worker-{index}-report.json")}
            manifest_path = tmp_path / f"worker-{index}.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            env = {**os.environ, "HERMES_HOME": str(target), "HERMES_TEST_ISOLATION": str(target),
                   "TERMINAL_CWD": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
            with (tmp_path / f"worker-{index}.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([sys.executable, "-B", "-m", "tests.hermes_cli.profile_seed_runtime_worker", str(manifest_path)],
                                        env=env, cwd=Path(__file__).resolve().parents[2], stdout=log, stderr=subprocess.STDOUT,
                                        timeout=45, check=False)
            assert result.returncode == 0, (
                f"Fresh worker {index} exited {result.returncode}; "
                f"log: {tmp_path / f'worker-{index}.log'}\n"
                "Worker log tail (owned token redacted):\n"
                + (tmp_path / f"worker-{index}.log").read_text(
                    encoding="utf-8", errors="replace"
                ).replace(token, "<owned-profile-token>")[-16000:]
            )
            reports.append(json.loads(Path(manifest["report_path"]).read_text(encoding="utf-8")))
        assert len(requests) == 2 and not errors, errors
        assert requests[0]["users"] == [f"{nonce}-0"]
        assert requests[1]["users"] == [f"{nonce}-0", f"{nonce}-1"]
        assert reports[0]["session_id"] == reports[1]["session_id"]
        assert reports[0]["pid"] != reports[1]["pid"]
        assert reports[1]["users"] == [f"{nonce}-0", f"{nonce}-1"]
        assert all(not report["violations"] for report in reports)
        assert source_path.read_bytes() == source_bytes
    finally:
        active_error = sys.exc_info()[1]
        for close in (runner.close, server.shutdown, server.server_close):
            try:
                close()
            except BaseException as exc:
                errors.append(repr(exc))
        peer.join(5)
        if peer.is_alive():
            errors.append("Owned peer survived cleanup")
        (tmp_path / "profile-wire-evidence.json").write_text(json.dumps({"entry": entry, "reports": reports,
            "requests": requests, "errors": errors, "violations": violations}, ensure_ascii=False, indent=2), encoding="utf-8")
        if active_error is None:
            assert not errors, errors
            assert not violations, violations
