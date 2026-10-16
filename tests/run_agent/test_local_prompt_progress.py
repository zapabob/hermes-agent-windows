"""Prompt progress must prove forward work without fabricating a first token."""
from __future__ import annotations

import http.server
import json
import threading
import time
from unittest.mock import patch

import pytest


@pytest.mark.parametrize("mode", [
    "advancing", "duplicate", "backward", "heartbeat", "invalid", "zero", "plain-heartbeat",
    "below-high-water", "unsupported", "opt-out", "mixed-output", "duplicate-with-usage", "usage-preserved",
])
def test_native_progress_before_first_token_is_bounded(monkeypatch, record_property, mode):
    """Run the actual SDK/Relay request against an owned finite SSE peer."""
    from run_agent import AIAgent

    wire, aborts, deltas, first, premature = [], [], [], [], []
    finished = threading.Event()
    stop = threading.Event()

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
            base = {"id": "owned-progress", "object": "chat.completion.chunk", "created": 1,
                    "model": "local-fixture", "choices": [{"index": 0, "delta": {}, "finish_reason": None}]}
            try:
                for index in range(1 if mode in {"unsupported", "opt-out", "mixed-output", "usage-preserved"} else 24):
                    progress = {
                        "advancing": {"processed": index + 1, "total": 100, "time_ms": index * 250},
                        "duplicate": {"processed": 10, "total": 100, "time_ms": index * 250},
                        "duplicate-with-usage": {"processed": 10, "total": 100, "time_ms": index * 250},
                        "backward": {"processed": 100 - index, "total": 200},
                        "heartbeat": {"total": 100, "time_ms": index * 250},
                        "invalid": {"processed": True, "total": 100},
                        "zero": {"processed": 0},
                        "below-high-water": {"processed": 100 if index == 0 else index, "total": 200},
                    }.get(mode)
                    frame = {**base, "prompt_progress": progress} if progress is not None else base
                    if mode in {"duplicate-with-usage", "usage-preserved"}:
                        frame = {**frame, "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10}}
                    if mode == "mixed-output":
                        frame = {**base, "prompt_progress": {"processed": 1}, "choices": [
                            {"index": 0, "delta": {"content": "real "}, "finish_reason": None}]}
                    self.wfile.write(("data: " + json.dumps(frame) + "\n\n").encode())
                    self.wfile.flush()
                    if stop.wait(0.25):
                        return
                    if mode != "mixed-output" and first:
                        premature.append("first delta fired before real content")
                final = {**base, "choices": [{"index": 0, "delta": {"content": "owned completion"},
                                               "finish_reason": None}]}
                end = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                self.wfile.write(("data: " + json.dumps(final) + "\n\n"
                                  + "data: " + json.dumps(end) + "\n\n"
                                  + "data: [DONE]\n\n").encode())
                self.wfile.flush()
            except OSError:
                pass  # A stale stream is expected to close this owned connection.
            finally:
                finished.set()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
    worker.start()
    agent = None
    monkeypatch.setenv("HERMES_STREAM_STALE_TIMEOUT", "3")
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "0")
    try:
        with (patch("run_agent.get_tool_definitions", return_value=[]),
              patch("run_agent.check_toolset_requirements", return_value={})):
            agent = AIAgent(api_key="owned-loopback-fixture", model="local-fixture", provider="custom",
                            base_url=f"http://127.0.0.1:{server.server_port}/v1", quiet_mode=True,
                            skip_context_files=True, skip_memory=True, enabled_toolsets=[])
        abort = agent._abort_request_openai_client

        def observe_abort(client, *, reason):
            aborts.append(reason)
            return abort(client, reason=reason)

        agent._abort_request_openai_client = observe_abort
        agent._fire_stream_delta = deltas.append
        agent._current_turn_id = "owned-progress-turn"
        kwargs = {"model": "local-fixture", "messages": [{"role": "user", "content": "fixture"}],
                  "extra_body": {"return_progress": True}}
        if mode == "unsupported":
            kwargs.pop("extra_body")
        elif mode == "opt-out":
            kwargs["extra_body"] = {"return_progress": False, "operator_setting": "kept"}
        error = None
        started = time.monotonic()
        try:
            response = agent._interruptible_streaming_api_call(kwargs, on_first_delta=lambda: first.append(True))
        except Exception as exc:
            error = exc
        elapsed = time.monotonic() - started
        assert len(wire) == 1
        if mode == "unsupported":
            assert "return_progress" not in wire[0]
        else:
            assert wire[0]["return_progress"] is (mode != "opt-out")
        if mode == "opt-out":
            assert wire[0]["operator_setting"] == "kept"
        if mode in {"advancing", "unsupported", "opt-out", "mixed-output", "usage-preserved"}:
            assert error is None, repr(error)
            expected = ["real ", "owned completion"] if mode == "mixed-output" else ["owned completion"]
            assert response.choices[0].message.content == "".join(expected)
            assert deltas == expected and first == [True]
            assert not aborts and agent._consecutive_stale_streams == 0
            if mode == "usage-preserved":
                assert response.usage.prompt_tokens == response.usage.total_tokens == 10
                assert response.usage.completion_tokens == 0
        else:
            assert error is not None, "repeated/non-forward metadata must not buy unlimited waiting"
            assert "stale_stream_kill" in aborts
            assert agent._consecutive_stale_streams >= 1
            assert deltas == first == [], "progress and late content must not fabricate output"
        assert not premature
        assert finished.wait(3), "the finite owned SSE handler must finish"
        record_property("elapsed_seconds", elapsed)
        record_property("wire_request", json.dumps(wire))
        record_property("abort_reasons", json.dumps(aborts))
    finally:
        stop.set()
        if agent is not None:
            agent.client.close()
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert not worker.is_alive()


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 1.5, "1", float("inf"), float("nan")])
def test_untrusted_processed_counts_cannot_advance(value):
    from agent.chat_completion_helpers import _LocalPromptProgress

    progress = _LocalPromptProgress()
    assert not progress.advance({"prompt_progress": {"processed": value}})
    assert progress.processed == 0


def test_progress_high_water_survives_regression_and_new_attempt_starts_clean():
    from agent.chat_completion_helpers import _LocalPromptProgress

    progress = _LocalPromptProgress()
    assert progress.advance({"prompt_progress": {"processed": 100}})
    for count in (99, 3, 50, 100):
        assert not progress.advance({"prompt_progress": {"processed": count}})
    assert progress.advance({"prompt_progress": {"processed": 101}})
    assert _LocalPromptProgress().advance({"prompt_progress": {"processed": 1}})


@pytest.mark.parametrize("total", [True, False, -1, 1, "10", 10.5])
def test_invalid_totals_cannot_advance(total):
    from agent.chat_completion_helpers import _LocalPromptProgress

    assert not _LocalPromptProgress().advance({"prompt_progress": {"processed": 2, "total": total}})


@pytest.mark.parametrize("field", ["content", "tool_calls", "reasoning", "reasoning_content", "refusal"])
def test_mixed_real_output_preserves_its_original_path(field):
    from agent.chat_completion_helpers import _LocalPromptProgress

    chunk = {"prompt_progress": {"processed": 1}, "choices": [{"delta": {field: "real"}}]}
    assert not _LocalPromptProgress.metadata_only(chunk)


@pytest.mark.parametrize("fields", [
    {"error_type": "invalid_request"},
    {"error_message": "fixture error"}, {"choices": [{"finish_reason": "stop", "delta": {}}]},
])
def test_usage_finish_and_provider_error_keep_existing_processing(fields):
    from agent.chat_completion_helpers import _LocalPromptProgress

    assert not _LocalPromptProgress.metadata_only({"prompt_progress": {"processed": 1}, **fields})
