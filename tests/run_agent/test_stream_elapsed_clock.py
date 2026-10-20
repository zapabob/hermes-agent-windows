"""Clock corrections must not alter real SDK stream liveness or cancellation."""
from __future__ import annotations

import http.server
import json
import threading
import time
from unittest.mock import patch

import pytest


class ModuleClock:
    """Change only the request owner's wall clock; SDK and host clocks stay real."""

    def __init__(self) -> None:
        self.offset = 0.0

    def time(self) -> float:
        return time.time() + self.offset

    def monotonic(self) -> float:
        return time.monotonic()

    def __getattr__(self, name: str):
        return getattr(time, name)


@pytest.mark.parametrize("mode", [
    "normal-complete", "forward-complete", "normal-stall", "backward-stall",
    "progress-stall", "cancel", "trial-complete", "trial-stall",
])
def test_native_stream_elapsed_clock(monkeypatch, record_property, mode):
    """Exercise the complete forwarder, real SDK/Relay, and finite owned HTTP peer."""
    from agent import chat_completion_helpers as helper
    from run_agent import AIAgent

    clock = ModuleClock()
    host_time = time.time
    monkeypatch.setattr(helper, "time", clock)
    wire, health, aborts, deltas, first = [], [], [], [], []
    peer_errors = []
    stop = threading.Event()
    finished = threading.Event()
    agent = None
    stalled = mode in {"normal-stall", "backward-stall", "progress-stall", "trial-stall"}
    trial = mode.startswith("trial-")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            health.append({"path": self.path, "authorization": self.headers.get("Authorization")})
            self.send_response(200 if self.path == "/health" else 404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            wire.append({"path": self.path, "body": body})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.flush()
            clock.offset = (-7200 if mode in {"backward-stall", "trial-stall"} else
                            7200 if mode in {"forward-complete", "trial-complete", "progress-stall", "cancel"} else 0)
            base = {"id": "owned-clock", "object": "chat.completion.chunk", "created": 1,
                    "model": "clock-fixture", "choices": [{"index": 0, "delta": {}, "finish_reason": None}]}

            def send(frame):
                self.wfile.write(("data: " + json.dumps(frame) + "\n\n").encode())
                self.wfile.flush()

            try:
                if mode == "cancel":
                    if stop.wait(0.15):
                        return
                    agent.interrupt()
                if mode == "progress-stall":
                    # First progress is legitimate; identical later samples buy no idle time.
                    for _ in range(32):
                        send({**base, "prompt_progress": {"processed": 1, "total": 100, "time_ms": 100}})
                        if stop.wait(0.12):
                            return
                elif stop.wait(3.8 if stalled or mode == "cancel" else 0.45):
                    return
                send({**base, "choices": [{"index": 0, "delta": {"content": "owned completion"}, "finish_reason": None}]})
                send({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except OSError:
                pass  # The request owner may close this owned connection on stale/stop.
            except Exception as exc:
                peer_errors.append(repr(exc))
            finally:
                finished.set()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = False
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
    worker.start()
    # Native SDK client setup has its own cost before the request reaches the peer.
    monkeypatch.setenv("HERMES_STREAM_STALE_TIMEOUT", "3")
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "0")
    monkeypatch.setenv("HERMES_STREAM_STALE_GIVEUP", "5")
    try:
        with (patch("run_agent.get_tool_definitions", return_value=[]),
              patch("run_agent.check_toolset_requirements", return_value={})):
            agent = AIAgent(api_key="owned-loopback-fixture", model="clock-fixture", provider="custom",
                            base_url=f"http://127.0.0.1:{server.server_port}/v1", quiet_mode=True,
                            skip_context_files=True, skip_memory=True, enabled_toolsets=[])
        # Initialize real SDK resources before the request liveness budget.
        _ = agent.client.chat.completions
        agent._current_turn_id = "owned-clock-turn"
        agent._consecutive_stale_streams = 0
        original_abort = agent._abort_request_openai_client

        def observe_abort(client, *, reason):
            aborts.append(reason)
            return original_abort(client, reason=reason)

        agent._abort_request_openai_client = observe_abort
        agent._fire_stream_delta = deltas.append
        if trial:
            agent._consecutive_stale_streams = 5
            assert helper._retry_recovered_local_server(agent)
            assert agent._consecutive_stale_streams == 4
        initial_streak = agent._consecutive_stale_streams
        error, response = None, None
        started = time.monotonic()
        try:
            response = agent._interruptible_streaming_api_call({
                "model": "clock-fixture", "messages": [{"role": "user", "content": "owned clock fixture"}],
                "extra_body": {"return_progress": True, "operator_field": "preserved"},
            }, on_first_delta=lambda: first.append(True))
        except Exception as exc:
            error = exc
        elapsed = time.monotonic() - started
        assert time.time is host_time, "The process/SDK wall clock must remain unchanged"
        assert len(wire) == 1
        assert wire[0]["path"] == "/v1/chat/completions"
        assert wire[0]["body"]["model"] == "clock-fixture"
        assert wire[0]["body"]["stream"] is True
        assert wire[0]["body"]["return_progress"] is True
        assert wire[0]["body"]["operator_field"] == "preserved"
        if stalled:
            assert "stale_stream_kill" in aborts, "A backwards clock must not postpone a real stall"
            assert agent._consecutive_stale_streams == initial_streak + 1
            assert deltas == first == [], "Late peer output must not survive a stale attempt"
            assert error is not None
            if trial:
                with pytest.raises(RuntimeError, match="consecutive stale"):
                    agent._interruptible_streaming_api_call({"model": "clock-fixture", "messages": []})
                assert len(wire) == 1, "A failed trial must not issue another model request"
        elif mode == "cancel":
            assert isinstance(error, InterruptedError)
            assert "stream_interrupt_abort" in aborts and "stale_stream_kill" not in aborts
            assert agent._consecutive_stale_streams == initial_streak
            assert deltas == first == []
        else:
            assert error is None, repr(error)
            assert response.choices[0].message.content == "owned completion"
            assert deltas == ["owned completion"] and first == [True]
            assert not aborts and agent._consecutive_stale_streams == 0
        health_probes = [item for item in health if item["path"] == "/health"]
        assert health_probes == ([{"path": "/health", "authorization": None}] if trial else [])
        assert not peer_errors
        record_property("mode", mode)
        record_property("elapsed_seconds", elapsed)
        record_property("wire", json.dumps(wire))
        record_property("health", json.dumps(health))
        record_property("abort_reasons", json.dumps(aborts))
    finally:
        stop.set()
        if agent is not None:
            agent.client.close()
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert finished.is_set() and not worker.is_alive()


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
@pytest.mark.parametrize('partial', [False, True])
def test_native_stream_diagnostic_wall_clock(monkeypatch, caplog, record_property, provider, partial):
    """Real OpenAI SDK / finite Anthropic fixture, each with the real TTFB logger."""
    import logging
    import re

    from agent import chat_completion_helpers as helper
    from agent import stream_diag
    from run_agent import AIAgent

    clock = ModuleClock()
    monkeypatch.setattr(helper, 'time', clock)
    host_time = time.time
    wire, diagnostics, deltas, peer_errors = [], [], [], []
    stop = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            wire.append({'path': self.path,
                         'body': json.loads(self.rfile.read(int(self.headers['Content-Length'])))})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            try:
                if stop.wait(0.25):
                    return

                def send(kind, payload):
                    event = f'event: {kind}\n' if kind else ''
                    self.wfile.write((event + 'data: ' + json.dumps(payload) + '\n\n').encode())
                    self.wfile.flush()

                base = {'id': 'owned-diag', 'object': 'chat.completion.chunk', 'created': 1,
                        'model': 'clock-fixture'}
                send('', {**base, 'choices': [{'index': 0, 'delta': {'content': 'owned diagnostic'},
                                              'finish_reason': None}]})
                if partial:
                    send('', {'error': {'message': 'owned partial failure', 'type': 'server_error'}})
                else:
                    send('', {**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})
                    self.wfile.write(b'data: [DONE]\n\n')
                    self.wfile.flush()
            except OSError:
                pass
            except Exception as exc:
                peer_errors.append(repr(exc))

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
    worker.start()
    agent = None
    monkeypatch.setenv('HERMES_STREAM_RETRIES', '0')
    monkeypatch.setenv('HERMES_STREAM_STALE_TIMEOUT', '5')
    try:
        with (patch('run_agent.get_tool_definitions', return_value=[]),
              patch('run_agent.check_toolset_requirements', return_value={})):
            agent = AIAgent(api_key='owned-loopback-fixture', model='clock-fixture', provider='custom',
                            base_url=f'http://127.0.0.1:{server.server_port}/v1', quiet_mode=True,
                            skip_context_files=True, skip_memory=True, enabled_toolsets=[])
        if provider == 'anthropic':
            from types import SimpleNamespace
            from unittest.mock import MagicMock

            agent.api_mode = 'anthropic_messages'
            final_message = SimpleNamespace(id='owned-diag', content=[SimpleNamespace(
                type='text', text='owned diagnostic')], stop_reason='end_turn',
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))

            def events():
                if stop.wait(0.25):
                    return
                yield SimpleNamespace(type='content_block_start', index=0,
                                      content_block=SimpleNamespace(type='text', text=''))
                yield SimpleNamespace(type='content_block_delta', index=0,
                                      delta=SimpleNamespace(type='text_delta', text='owned diagnostic'))
                if partial:
                    raise RuntimeError('owned partial failure')

            stream = MagicMock()
            stream.__iter__.side_effect = events
            stream.get_final_message.return_value = final_message
            stream.response = SimpleNamespace(status_code=200, headers={})
            manager = MagicMock()
            manager.__enter__.return_value = stream
            client = MagicMock()
            client.messages.stream.return_value = manager
            agent._create_request_anthropic_client = lambda **_kw: client
        agent._current_turn_id = 'owned-diag-turn'
        agent._consecutive_stale_streams = 0
        agent._fire_stream_delta = deltas.append
        original_init = agent._stream_diag_init

        def observe_diag():
            diag = original_init()
            diagnostics.append(diag)
            return diag

        agent._stream_diag_init = observe_diag
        kwargs = {'model': 'clock-fixture', 'messages': [{'role': 'user', 'content': 'owned fixture'}]}
        if provider == 'anthropic':
            kwargs['max_tokens'] = 32
        before = time.time()
        response = agent._interruptible_streaming_api_call(kwargs)
        after = time.time()
        assert time.time is host_time and clock.offset == 0
        assert len(diagnostics) == 1
        if provider == 'openai':
            assert len(wire) == 1 and wire[0]['path'] == '/v1/chat/completions'
            assert wire[0]['body']['stream'] is True
        else:
            assert wire == []
            client.messages.stream.assert_called_once()
            manager.__exit__.assert_called_once()
        assert 'owned diagnostic' in ''.join(deltas)
        assert response is not None
        if partial:
            assert response.id == helper.PARTIAL_STREAM_STUB_ID
        else:
            assert response.id != helper.PARTIAL_STREAM_STUB_ID
        diag = diagnostics[0]
        ttfb = diag['first_chunk_at'] - diag['started_at']
        assert diag['chunks'] > 0 and diag['http_status'] == 200
        # Exercise the actual diagnostic consumer, including the max(0, ...) path.
        with caplog.at_level(logging.WARNING, logger=stream_diag.__name__):
            agent._log_stream_retry(kind='owned-oracle', error=RuntimeError('owned fixture'),
                                    attempt=1, max_attempts=1, mid_tool_call=False, diag=diag)
        message = next(r.getMessage() for r in reversed(caplog.records)
                       if r.name == stream_diag.__name__ and 'owned-oracle' in r.getMessage())
        logged = float(re.search(r'ttfb=([0-9.]+)s', message).group(1))
        assert logged > 0 and abs(logged - ttfb) <= 0.011
        assert before <= diag['started_at'] < diag['first_chunk_at'] <= after
        assert 0.20 <= ttfb <= after - before
        assert not peer_errors
        record_property('wire', json.dumps(wire))
        record_property('diagnostics', json.dumps(diag))
        record_property('diagnostic_log', message)
    finally:
        stop.set()
        if agent is not None:
            agent.client.close()
            cache = getattr(agent, '_request_anthropic_client_cache', None)
            if isinstance(cache, dict) and cache.get('client') is not None:
                cache['client'].close()
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert not worker.is_alive()
