"""Saved unlisted models survive a new runtime and reach only their endpoint.

This exercises the REST config owner, shared picker inventory and runtime
resolver. The HTTP server is an owned protocol fixture, not a model engine.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


MODEL = "local/unlisted-test-Q4_K_M.gguf"

# A fresh process must derive routing from the saved profile, without an
# explicit model/provider/base_url override or any parent-process config cache.
FRESH_RUNTIME = r'''
import json
import sys

attempts = []
blocked_dns = []
port = int(sys.argv[1])

def audit(event, args):
    if event == "subprocess.Popen":
        raise AssertionError("External credential/helper processes denied")
    elif event == "socket.connect":
        address = args[1]
        attempts.append([event, list(address)])
        if address[0] != "127.0.0.1" or address[1] != port:
            raise AssertionError("Foreign socket connection denied")
    elif event == "socket.getaddrinfo":
        host, requested_port = args[:2]
        if host != "127.0.0.1" or requested_port != port:
            # Deny before DNS resolution. Shared metadata readers may attempt
            # a refresh; none can send traffic from this test process.
            blocked_dns.append([str(host), requested_port])
            raise AssertionError("Foreign DNS resolution denied")
        attempts.append([event, [str(host), requested_port]])

sys.addaudithook(audit)
from hermes_cli.inventory import load_picker_context, build_model_options_payload
from hermes_cli.runtime_provider import resolve_runtime_provider
from openai import OpenAI

context = load_picker_context()
catalogue = build_model_options_payload(context, explicit_only=True)
runtime = resolve_runtime_provider()
with OpenAI(
    base_url=runtime["base_url"], api_key=runtime["api_key"],
    max_retries=0, timeout=5,
) as client:
    reply = client.chat.completions.create(
        model=context.current_model, messages=[{"role": "user", "content": "route probe"}],
    )
print(json.dumps({
    "context_provider": context.current_provider,
    "context_model": context.current_model,
    "providers": [{"slug": row["slug"], "models": row["models"]}
                  for row in catalogue["providers"]
                  if row["slug"] == context.current_provider],
    "runtime": {key: runtime[key] for key in
                ("provider", "requested_provider", "base_url", "api_mode")},
    "reply": reply.choices[0].message.content,
    "attempts": attempts,
    "blocked_dns": blocked_dns,
}))
'''


@pytest.mark.parametrize("with_key", [False, True], ids=["no-key", "profile-key"])
def test_unlisted_profile_model_resolves_after_fresh_process(
    tmp_path, monkeypatch, with_key
):
    # Provider inventory can consult external CLI credential stores. Give both
    # parent and child an owned user/config home, and forbid helper subprocesses
    # in the child rather than inheriting the operator's gh/keychain context.
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "GH_CONFIG_DIR"):
        monkeypatch.setenv(name, str(user_home))
    from starlette.testclient import TestClient

    from hermes_cli import profiles
    from hermes_cli.config import get_config_path, load_config, save_config
    from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app
    from hermes_constants import get_hermes_home

    default_home = get_hermes_home()
    save_config({"model": {"provider": "openrouter", "default": "keep-default"}})
    default_before = get_config_path().read_bytes()
    worker_home = profiles.get_profile_dir("route-worker")
    worker_home.mkdir(parents=True)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization"), None))
            # The manually selected model is deliberately absent from discovery.
            self.respond({"data": [{"id": "discovered-only-model"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), body))
            self.respond({
                "id": "owned-loopback-response", "object": "chat.completion",
                "created": 0, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "route confirmed"}}],
            })

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    key = "sk-synthetic-profile-route" if with_key else None
    try:
        with TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN}) as client:
            payload = {
                "id": "owned-local", "name": "Owned Local", "base_url": base_url,
                "model": MODEL, "models": ["discovered-only-model"],
                "make_default": True, "discover_models": True,
            }
            if key:
                payload["api_key"] = key
            saved = client.post(
                "/api/providers/custom-endpoints?profile=route-worker", json=payload,
            )
            assert saved.status_code == 200, saved.text
            endpoint = next(e for e in saved.json()["endpoints"] if e["id"] == "owned-local")
            assert endpoint["model"] == MODEL
            assert MODEL in endpoint["models"]

        # Check the on-disk owner and profile boundary before starting a reader.
        assert get_config_path().read_bytes() == default_before
        assert load_config()["model"]["default"] == "keep-default"
        worker_config = (worker_home / "config.yaml").read_text(encoding="utf-8")
        assert MODEL in worker_config
        assert not key or key not in worker_config
        assert not (default_home / ".env").exists()
        assert not key or key in (worker_home / ".env").read_text(encoding="utf-8")

        # Supply owned public metadata to normal catalogue reads. Other missing
        # metadata refreshes are denied by the child audit hook before DNS.
        (worker_home / "models_dev_cache.json").write_text(
            json.dumps({"owned-catalog-fixture": {"models": {}}}), encoding="utf-8",
        )

        env = os.environ.copy()
        env.update({
            "HERMES_HOME": str(worker_home), "HERMES_TEST_ISOLATION": str(worker_home),
            "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
            # Synthetic ambient credentials must neither win nor reach the local server.
            "OPENAI_API_KEY": "sk-synthetic-wrong-openai",
            "OPENROUTER_API_KEY": "sk-synthetic-wrong-openrouter",
            "HERMES_INFERENCE_PROVIDER": "openrouter",
            "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1",
            "PATH": str(user_home),
        })
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(name, None)
        fresh = subprocess.run(
            [sys.executable, "-B", "-c", FRESH_RUNTIME, str(server.server_port)],
            cwd=Path(__file__).resolve().parents[2], env=env,
            text=True, encoding="utf-8", capture_output=True, timeout=60, check=False,
        )
        assert fresh.returncode == 0, fresh.stderr
        result = json.loads(fresh.stdout.strip().splitlines()[-1])
        assert result["context_provider"] == "owned-local"
        assert result["context_model"] == MODEL
        row = next(r for r in result["providers"] if r["slug"] == "owned-local")
        assert MODEL in row["models"]
        assert result["runtime"] == {
            "provider": "custom", "requested_provider": "owned-local",
            "base_url": base_url, "api_mode": "chat_completions",
        }
        assert result["reply"] == "route confirmed"
        assert result["attempts"]
        for event, address in result["attempts"]:
            assert address == ["127.0.0.1", server.server_port], event
        posts = [request for request in requests if request[2] is not None]
        assert len(posts) == 1
        path, authorization, body = posts[0]
        assert path == "/v1/chat/completions"
        assert authorization == f"Bearer {key or 'no-key-required'}"
        assert body["model"] == MODEL
        assert get_config_path().read_bytes() == default_before
        result["observed_requests"] = [
            {"path": path, "model": body.get("model") if body else None,
             "expected_authorization": auth == f"Bearer {key or 'no-key-required'}"}
            for path, auth, body in requests
        ]
        (tmp_path / "route-proof.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
