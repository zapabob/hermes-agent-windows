"""Native SDK requests prove the actual route, wire flag and reading budget."""
from __future__ import annotations

import asyncio
import copy
import http.server
import json
import threading
from unittest.mock import patch

import pytest


@pytest.fixture
def owned_progress_peer():
    wire = []
    completed = threading.Event()
    release = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            wire.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {"id": "native-aux-progress", "object": "chat.completion.chunk",
                     "created": 1, "model": "fixture", "choices": [
                         {"index": 0, "delta": {}, "finish_reason": None}]}
            try:
                if body.get("return_progress"):
                    for i in range(1, 13):
                        if release.wait(0.12):
                            return
                        progress = {**chunk, "prompt_progress": {"processed": 1 if body.get("fixture_duplicate_progress") else i, "total": 100, "time_ms": i * 120}}
                        self.wfile.write(("data: " + json.dumps(progress) + "\n\n").encode())
                        self.wfile.flush()
                output = {**chunk, "choices": [{"index": 0, "delta": {"content": "native summary"}, "finish_reason": None}]}
                end = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                self.wfile.write(("data: " + json.dumps(output) + "\n\n"
                                  + "data: " + json.dumps(end) + "\n\n"
                                  + "data: [DONE]\n\n").encode())
                self.wfile.flush()
            except OSError:
                pass
            finally:
                completed.set()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", wire, completed
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert not worker.is_alive()


@pytest.mark.parametrize("dispatch", ["main", "sync", "async"])
@pytest.mark.parametrize("policy", ["capable", "unknown", "explicit-off"])
def test_native_capability_controls_real_wire_and_response(monkeypatch, record_property, owned_progress_peer, dispatch, policy):
    from openai import AsyncOpenAI, OpenAI
    from agent import auxiliary_client as aux

    base, wire, completed = owned_progress_peer
    config = {"custom_providers": [{"name": "fixture", "base_url": base,
                                    "models": {"fixture": {"prompt_progress": policy != "unknown"}}}]}
    original = copy.deepcopy(config)
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda: config)
    # Deliberately shorter than the peer's measured prompt reading. Only
    # reading may be discounted; a long model/generation stall stays bounded.
    monkeypatch.setattr(aux, "_aux_stream_total_ceiling", lambda _timeout: 1.0)
    kwargs = {"model": "fixture", "messages": [{"role": "user", "content": "owned fixture"}],
              "extra_body": {"operator_field": "kept"}, "timeout": 1.0}
    if policy == "explicit-off":
        kwargs["extra_body"]["return_progress"] = False
    before = copy.deepcopy(kwargs)
    ticks = []
    if dispatch == "main":
        from run_agent import AIAgent

        with (patch("run_agent.get_tool_definitions", return_value=[]),
              patch("run_agent.check_toolset_requirements", return_value={}),
              patch("agent.context_compressor.get_model_context_length", return_value=128000)):
            agent = AIAgent(api_key="owned-peer-key", provider="custom", model="fixture", base_url=base,
                            quiet_mode=True, skip_memory=True, skip_context_files=True, enabled_toolsets=[])
        try:
            response = agent._interruptible_streaming_api_call(kwargs, on_first_delta=lambda: ticks.append(True))
        finally:
            agent.client.close()
        assert ticks == [True], "metadata must not emit a first output token"
    elif dispatch == "sync":
        with OpenAI(api_key="owned-peer-key", base_url=base, max_retries=0) as client:
            with aux.aux_progress_hook(lambda: ticks.append(True)):
                response = aux._create_with_progress(client, kwargs)
    else:
        async def request():
            async with AsyncOpenAI(api_key="owned-peer-key", base_url=base, max_retries=0) as client:
                return await aux._acreate_with_progress(client, kwargs)
        with aux.aux_progress_hook(lambda: ticks.append(True)):
            response = asyncio.run(request())
    assert response.choices[0].message.content == "native summary"
    assert completed.wait(3) and len(wire) == 1
    assert wire[0].get("return_progress") is (None if policy == "unknown" else policy == "capable")
    assert wire[0]["operator_field"] == "kept" and wire[0]["model"] == "fixture"
    assert config == original and kwargs == before
    record_property("native_wire", json.dumps(wire))


@pytest.mark.parametrize("stalled", [False, True])
def test_native_protected_provider_extends_only_original_host_budget(monkeypatch, owned_progress_peer, stalled):
    import time
    from openai import OpenAI
    from agent import auxiliary_client as aux
    from agent.conversation_compression import CompressionCommitFence, run_compress_context_with_progress_timeout
    from agent.local_prompt_progress import prompt_reading_budget

    base, wire, completed = owned_progress_peer
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda: {
        "custom_providers": [{"name": "fixture", "base_url": base,
                              "models": {"fixture": {"prompt_progress": True}}}],
    })
    monkeypatch.setattr(aux, "_aux_stream_total_ceiling", lambda _timeout: 1.0)
    messages = [{"role": "user", "content": "preserve original"}]
    fence = CompressionCommitFence()
    entered, exited = threading.Event(), threading.Event()
    kwargs = {"model": "fixture", "messages": messages, "timeout": 1.0,
              "extra_body": {"fixture_duplicate_progress": stalled}}
    commits = []
    def worker(original):
        try:
            entered.set()
            with OpenAI(api_key="owned-key", base_url=base, max_retries=0) as client:
                with (aux.aux_progress_hook(original.touch_progress),
                      aux.aux_interrupt_protection(cancel_check=lambda: original.is_cancelled),
                      prompt_reading_budget(original.extend_deadline, lambda: original.deadline_monotonic)):
                    response = aux._run_protected_sync_provider_call(lambda args: aux._create_with_progress(client, args), kwargs)
            original.close_progress()
            if not original.begin_commit():
                return messages, "fallback"
            try:
                commits.append(response.choices[0].message.content)
                return [{"role": "assistant", "content": commits[-1]}], "done"
            finally:
                original.finish_commit()
        finally:
            original.close_progress()
            exited.set()
    started = time.monotonic()
    result = run_compress_context_with_progress_timeout(
        worker=worker, messages=messages, system_prompt_fallback="fallback",
        idle_timeout_seconds=0.7, total_ceiling_seconds=1.0, fence=fence, stall_fallback=False,
    )
    elapsed = time.monotonic() - started
    assert entered.is_set()
    assert exited.wait(4) and completed.wait(4) and len(wire) == 1
    if stalled:
        assert result == (messages, "fallback") and commits == [] and fence.is_cancelled
    else:
        assert result == ([{"role": "assistant", "content": "native summary"}], "done")
        assert commits == ["native summary"] and elapsed > 1.0
    previous = fence.deadline_monotonic
    assert not fence.extend_deadline(100) and fence.deadline_monotonic == previous
