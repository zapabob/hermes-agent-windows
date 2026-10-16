"""Follow-up for the cross-turn stream-stale circuit breaker (#58962).

The breaker latches: once ``_consecutive_stale_streams`` reaches the give-up
threshold, ``interruptible_streaming_api_call`` raises BEFORE any stream is
attempted — so the "reset on successful stream" path can never run again on
its own. The breaker's error message tells the user to "switch models …
then retry", and the provider-fallback chain swaps providers on the same
agent object, so BOTH swap paths must clear the streak or a healthy new
provider would keep short-circuiting forever:

- ``switch_model()``   (user-initiated /model swap)
- ``try_activate_fallback()``  (automatic provider fallback)
- ``restore_primary_runtime()``  (turn-start restore back to the primary)

The non-streaming sibling ``interruptible_api_call`` shares the same
breaker (guard at entry, bump on stale_call_kill, reset on success) —
quiet-mode / subagent sessions take that path and had the identical
infinite stale-retry class.
"""

from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest

from run_agent import AIAgent


def _make_agent_openrouter():
    """Minimal openrouter agent (skips __init__), mirroring
    tests/run_agent/test_switch_model_rollback.py."""
    agent = AIAgent.__new__(AIAgent)

    agent.provider = "openrouter"
    agent.model = "x-ai/grok-4"
    agent.base_url = "https://openrouter.ai/api/v1"
    agent.api_key = "or-key-original"
    agent.api_mode = "chat_completions"
    agent.client = MagicMock(name="OriginalClient")
    agent._client_kwargs = {
        "api_key": "or-key-original",
        "base_url": "https://openrouter.ai/api/v1",
    }
    agent.context_compressor = None
    agent._anthropic_api_key = ""
    agent._anthropic_base_url = None
    agent._anthropic_client = None
    agent._is_anthropic_oauth = False
    agent._cached_system_prompt = "cached"
    agent._primary_runtime = {}
    agent._fallback_activated = False
    agent._fallback_index = 0
    agent._fallback_chain = []
    agent._fallback_model = None
    agent._config_context_length = None

    return agent


def _make_fallback_agent(fallback_model):
    """Full-constructor agent for the fallback path, mirroring
    tests/run_agent/test_24996_fallback_exhaustion_cooldown.py."""
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            fallback_model=fallback_model,
        )
        agent.client = MagicMock()
        return agent


def _mock_client(base_url="https://openrouter.ai/api/v1", api_key="fb-key"):
    mock = MagicMock()
    mock.base_url = base_url
    mock.api_key = api_key
    return mock


def test_switch_model_resets_stale_streak():
    """A user-initiated /model swap must clear the latched streak so the new
    provider gets a real stream attempt instead of an instant short-circuit."""
    agent = _make_agent_openrouter()
    agent._consecutive_stale_streams = 7  # past any reasonable threshold

    agent._create_openai_client = MagicMock(return_value=MagicMock(name="NewClient"))

    with patch("hermes_cli.timeouts.get_provider_request_timeout", return_value=None):
        agent.switch_model(
            new_model="openai/gpt-5",
            new_provider="openrouter",
            api_key="or-key-new",
            base_url="https://openrouter.ai/api/v1",
            api_mode="chat_completions",
        )

    assert agent._consecutive_stale_streams == 0


def test_switch_model_failure_does_not_reset_streak():
    """A failed swap rolls back — the agent is still on the wedged provider,
    so the breaker must stay latched (reset happens after the rebuild)."""
    agent = _make_agent_openrouter()
    agent._consecutive_stale_streams = 7

    def boom(*_a, **_kw):
        raise RuntimeError("simulated client build failure")

    agent._create_openai_client = boom

    with patch("hermes_cli.timeouts.get_provider_request_timeout", return_value=None):
        try:
            agent.switch_model(
                new_model="openai/gpt-5",
                new_provider="openrouter",
                api_key="or-key-new",
                base_url="https://openrouter.ai/api/v1",
                api_mode="chat_completions",
            )
        except RuntimeError:
            pass

    assert agent._consecutive_stale_streams == 7


def test_fallback_activation_resets_stale_streak():
    """Automatic provider fallback swaps to a different backend; the streak
    measured the OLD provider and must not wedge the new one."""
    fbs = [{"provider": "openai", "model": "gpt-4o"}]
    agent = _make_fallback_agent(fallback_model=fbs)
    agent._consecutive_stale_streams = 7

    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        return_value=(_mock_client(), "resolved"),
    ):
        assert agent._try_activate_fallback() is True

    assert agent._consecutive_stale_streams == 0


def test_fallback_exhaustion_keeps_stale_streak():
    """When the chain is exhausted (no swap happened), the streak stays
    latched — the session is still wedged on the same provider."""
    agent = _make_fallback_agent(fallback_model=[])
    agent._consecutive_stale_streams = 7

    assert agent._try_activate_fallback() is False
    assert agent._consecutive_stale_streams == 7






class TestNonStreamingSibling:
    """interruptible_api_call carries the same breaker (#58962)."""

    def test_non_streaming_short_circuits_at_threshold(self, monkeypatch):
        monkeypatch.setenv("HERMES_STREAM_STALE_GIVEUP", "3")
        agent = _make_fallback_agent(fallback_model=[])
        agent._consecutive_stale_streams = 3

        with pytest.raises(RuntimeError, match="unresponsive"):
            agent._interruptible_api_call({})

        # The client is never touched on the short-circuit path.
        agent.client.chat.completions.create.assert_not_called()
        assert agent._consecutive_stale_streams == 3

    def test_non_streaming_success_resets_streak(self, monkeypatch):
        monkeypatch.setenv("HERMES_STREAM_STALE_GIVEUP", "3")
        agent = _make_fallback_agent(fallback_model=[])
        agent._consecutive_stale_streams = 2  # below threshold
        agent.client.chat.completions.create.return_value = MagicMock(
            name="resp", choices=[MagicMock()]
        )

        resp = agent._interruptible_api_call({"model": "m", "messages": []})
        assert resp is not None
        assert agent._consecutive_stale_streams == 0


@pytest.fixture
def local_health_probe(monkeypatch):
    import http.client

    factory = MagicMock()
    factory.return_value.getresponse.return_value.status = 200
    class Connection:
        def __init__(self, host, port, *, timeout):
            self.sock = None
            factory(host, port, timeout=timeout)

        def request(self, *args, **kwargs):
            return factory.return_value.request(*args, **kwargs)

        def getresponse(self):
            return factory.return_value.getresponse()

        def close(self):
            return factory.return_value.close()

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    monkeypatch.setenv("HERMES_STREAM_STALE_GIVEUP", "5")
    return factory


def _local_stale_agent(**overrides):
    fields = dict(provider="custom", model="local-fixture", api_mode="chat_completions",
                  base_url="http://127.0.0.1:8080/v1", _current_turn_id="turn-1",
                  _consecutive_stale_streams=5, _interrupt_requested=False)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_local_health_grants_one_trial_then_another_stall_recloses(local_health_probe):
    from agent.chat_completion_helpers import (
        _retry_recovered_local_server, _check_stale_giveup, _bump_stale_streak,
    )

    agent = _local_stale_agent(_consecutive_stale_streams=19)
    assert _retry_recovered_local_server(agent)
    assert agent._consecutive_stale_streams == 4
    _check_stale_giveup(agent)
    _bump_stale_streak(agent)
    with pytest.raises(RuntimeError, match="5 consecutive stale attempts"):
        _check_stale_giveup(agent)
    assert not _retry_recovered_local_server(agent)
    assert local_health_probe.call_count == 1
    agent._current_turn_id = "turn-2"
    assert _retry_recovered_local_server(agent)
    assert local_health_probe.call_count == 2
    local_health_probe.return_value.request.assert_called_with(
        "GET", "/health", headers={"Connection": "close"},
    )
    assert (agent.provider, agent.model, agent.base_url) == (
        "custom", "local-fixture", "http://127.0.0.1:8080/v1",
    )


@pytest.mark.parametrize("status", [301, 302, 401, 404, 503])
def test_health_denial_keeps_breaker_latched_without_following_redirects(local_health_probe, status):
    from agent.chat_completion_helpers import _retry_recovered_local_server

    local_health_probe.return_value.getresponse.return_value.status = status
    agent = _local_stale_agent()
    assert not _retry_recovered_local_server(agent)
    assert agent._consecutive_stale_streams == 5
    local_health_probe.return_value.close.assert_called_once()
    assert not _retry_recovered_local_server(agent)
    assert local_health_probe.call_count == 1


@pytest.mark.parametrize("changes", [
    {"base_url": "https://api.openai.com/v1"},
    {"base_url": "http://127.0.0.1:8080@api.openai.com/v1"},
    {"base_url": "http://secret@127.0.0.1:8080/v1"},
    {"base_url": "http://127.0.0.1:8080/v1?token=fixture"},
    {"base_url": "http://127.0.0.1:bad/v1"},
    {"base_url": "ftp://127.0.0.1/v1"},
    {"base_url": ""}, {"api_mode": "anthropic_messages"},
    {"_current_turn_id": None}, {"_interrupt_requested": True},
    {"_consecutive_stale_streams": 4},
])
def test_ineligible_recovery_never_opens_health_connection(local_health_probe, changes):
    from agent.chat_completion_helpers import _retry_recovered_local_server

    agent = _local_stale_agent(**changes)
    before = agent._consecutive_stale_streams
    assert not _retry_recovered_local_server(agent)
    assert agent._consecutive_stale_streams == before
    local_health_probe.assert_not_called()


def test_disabled_breaker_never_probes(local_health_probe, monkeypatch):
    from agent.chat_completion_helpers import _retry_recovered_local_server

    monkeypatch.setenv("HERMES_STREAM_STALE_GIVEUP", "0")
    assert not _retry_recovered_local_server(_local_stale_agent())
    local_health_probe.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"base_url": "http://127.0.0.1:9000/v1"}, {"provider": "other"},
    {"model": "replacement"}, {"_current_turn_id": "turn-2"},
    {"_consecutive_stale_streams": 6}, {"_interrupt_requested": True},
])
def test_health_result_cannot_change_replaced_runtime_or_new_turn(local_health_probe, changes):
    from agent.chat_completion_helpers import _retry_recovered_local_server

    agent = _local_stale_agent()
    def replace_during_probe():
        for key, value in changes.items():
            setattr(agent, key, value)
        return SimpleNamespace(status=200)
    local_health_probe.return_value.getresponse.side_effect = replace_during_probe
    assert not _retry_recovered_local_server(agent)
    assert agent._consecutive_stale_streams == changes.get("_consecutive_stale_streams", 5)


def test_health_transport_failure_keeps_breaker_latched(local_health_probe):
    from agent.chat_completion_helpers import _retry_recovered_local_server

    local_health_probe.return_value.getresponse.side_effect = OSError("fixture offline")
    agent = _local_stale_agent()
    assert not _retry_recovered_local_server(agent)
    assert agent._consecutive_stale_streams == 5
    local_health_probe.return_value.close.assert_called_once()


def test_health_cleanup_failure_does_not_abort_new_turn(local_health_probe):
    from agent.chat_completion_helpers import _retry_recovered_local_server

    local_health_probe.return_value.close.side_effect = OSError("fixture close failure")
    agent = _local_stale_agent()
    assert not _retry_recovered_local_server(agent)
    assert agent._consecutive_stale_streams == 5


@pytest.mark.parametrize("half_open", [False, True])
@pytest.mark.parametrize("response_kind", ["complete", "partial", "failure"])
def test_only_an_actual_completion_settles_the_local_trial(local_health_probe, half_open, response_kind):
    from agent.chat_completion_helpers import _retry_recovered_local_server, _settle_stream_stale_trial
    from hermes_constants import PARTIAL_STREAM_STUB_ID

    agent = _local_stale_agent()
    if half_open:
        assert _retry_recovered_local_server(agent)
    response = None if response_kind == "failure" else SimpleNamespace(
        id=PARTIAL_STREAM_STUB_ID if response_kind == "partial" else "actual-completion",
    )
    failed_trial = _settle_stream_stale_trial(agent, response)
    expected_closed = half_open and response_kind != "complete"
    assert failed_trial is expected_closed
    assert agent._consecutive_stale_streams == (5 if expected_closed or response is None else 0)


def test_timed_out_health_connect_cannot_write_late_or_accumulate(monkeypatch):
    import http.client
    import threading
    from agent.chat_completion_helpers import _retry_recovered_local_server

    entered, release = threading.Event(), threading.Event()
    requests = []
    connections = []
    class DelayedConnection:
        def __init__(self, *_args, **_kwargs):
            self.sock = None
            connections.append(self)

        def connect(self):
            entered.set()
            assert release.wait(6)

        def request(self, *_args, **_kwargs):
            self.connect()
            requests.append("late GET")

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", DelayedConnection)
    monkeypatch.setenv("HERMES_STREAM_STALE_GIVEUP", "5")
    agent = _local_stale_agent()
    try:
        assert not _retry_recovered_local_server(agent)
        assert entered.is_set() and not agent._local_stale_probe_done.is_set()
        agent._current_turn_id = "next-turn"
        assert not _retry_recovered_local_server(agent)
        assert len(connections) == 1
        assert agent._consecutive_stale_streams == 5
    finally:
        release.set()
    assert agent._local_stale_probe_done.wait(3)
    assert requests == [], "an expired DNS/connect result must not issue a health request"


def test_concurrent_probe_for_same_turn_has_one_owner(local_health_probe):
    import threading
    from agent.chat_completion_helpers import _retry_recovered_local_server

    entered, release = threading.Event(), threading.Event()
    results = []
    agent = _local_stale_agent()
    def hold_response():
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(status=200)
    local_health_probe.return_value.getresponse.side_effect = hold_response
    worker = threading.Thread(target=lambda: results.append(_retry_recovered_local_server(agent)))
    worker.start()
    try:
        assert entered.wait(3)
        assert not _retry_recovered_local_server(agent)
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive() and results == [True]
    assert local_health_probe.call_count == 1


@pytest.mark.parametrize(("outcome", "dispatch"), [
    ("complete", "stream"), ("stall", "stream"), ("partial", "stream"),
    ("trickle", "stream"), ("server-error", "stream"),
    ("complete", "nonstream"), ("server-error", "nonstream"),
    ("complete", "inline"), ("server-error", "inline"),
])
def test_native_health_recovery_then_real_sdk_stream_completion(monkeypatch, record_property, outcome, dispatch):
    """Use the product request path and real SDK against only an owned peer."""
    import http.server
    import json
    import threading
    import time
    from agent.chat_completion_helpers import _retry_recovered_local_server

    wire = []
    release_stall = threading.Event()
    entered_stall = threading.Event()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            wire.append({"method": "GET", "path": self.path,
                         "authorization_present": bool(self.headers.get("Authorization"))})
            if outcome == "trickle" and self.path == "/health":
                try:
                    self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                    self.wfile.flush()
                    for _ in range(5):
                        if release_stall.wait(0.85):
                            return
                        self.wfile.write(b"X-Fixture: alive\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"Content-Length: 0\r\n\r\n")
                    self.wfile.flush()
                except OSError:
                    pass  # The deadline is expected to shut down this owned peer.
                return
            self.send_response(200 if self.path == "/health" else 404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            wire.append({"method": "POST", "path": self.path, "body": body})
            if outcome == "server-error":
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if dispatch != "stream":
                raw = json.dumps({"id": "native-complete", "object": "chat.completion", "created": 1,
                                  "model": "local-fixture", "choices": [{"index": 0,
                                  "message": {"role": "assistant", "content": "native recovery"},
                                  "finish_reason": "stop"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            chunk = {"id": "owned-native-response", "object": "chat.completion.chunk",
                     "created": 1, "model": "local-fixture", "choices": [
                         {"index": 0, "delta": {"role": "assistant", "content": "native recovery"}, "finish_reason": None}]}
            end = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            raw = ("data: " + json.dumps(chunk) + "\n\n"
                   + ("data: " + json.dumps(end) + "\n\n" if outcome != "partial" else "")
                   + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if outcome == "stall":
                self.wfile.flush()
                entered_stall.set()
                release_stall.wait(12)
                return
            self.wfile.write(raw)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
    worker.start()
    agent = None
    monkeypatch.setenv("HERMES_STREAM_STALE_GIVEUP", "5")
    # SDK client construction can take a second on native Windows. The
    # positive control must not time out before it reaches the owned peer.
    monkeypatch.setenv("HERMES_STREAM_STALE_TIMEOUT", "30" if outcome == "complete" else "3")
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "2" if outcome == "server-error" else "0")
    try:
        with (patch("run_agent.get_tool_definitions", return_value=[]),
              patch("run_agent.check_toolset_requirements", return_value={})):
            agent = AIAgent(api_key="owned-loopback-fixture", model="local-fixture", provider="custom",
                            base_url=f"http://127.0.0.1:{server.server_port}/v1",
                            quiet_mode=True, skip_context_files=True, skip_memory=True,
                            enabled_toolsets=[])
        agent._current_turn_id = "native-turn-1"
        agent._consecutive_stale_streams = 5
        from agent.chat_completion_helpers import direct_api_call
        request = {
            "stream": agent._interruptible_streaming_api_call,
            "nonstream": agent._interruptible_api_call,
            "inline": lambda kwargs: direct_api_call(agent, kwargs),
        }[dispatch]
        started = time.monotonic()
        if outcome == "trickle":
            assert not _retry_recovered_local_server(agent)
            elapsed = time.monotonic() - started
            assert elapsed < 3.6
            assert agent._local_stale_probe_done.wait(1), "expired header reads must release their owned worker"
            assert agent._consecutive_stale_streams == 5
            assert len([r for r in wire if r["path"] == "/health"]) == 1
            assert not any(r["method"] == "POST" for r in wire)
            record_property("owned_local_peer_wire", json.dumps(wire))
            record_property("health_total_elapsed", elapsed)
            return
        assert _retry_recovered_local_server(agent)
        assert agent._consecutive_stale_streams == 4
        kwargs = {
            "model": "local-fixture", "messages": [{"role": "user", "content": "fixture"}],
        }
        if outcome == "complete":
            response = request(kwargs)
            assert response.choices[0].message.content == "native recovery"
            assert agent._consecutive_stale_streams == 0
        elif outcome == "partial":
            from hermes_constants import PARTIAL_STREAM_STUB_ID
            response = request(kwargs)
            assert response.id == PARTIAL_STREAM_STUB_ID
            assert response.choices[0].message.content == "native recovery"
            assert response.choices[0].finish_reason == "length"
            assert agent._consecutive_stale_streams >= 5, "an unfinished trial cannot settle as success"
            with pytest.raises(RuntimeError, match="consecutive stale attempts"):
                request(kwargs)
        else:
            with pytest.raises(Exception):
                request(kwargs)
            if outcome == "stall":
                assert entered_stall.is_set(), "the actual peer must have accepted the stalled stream"
            assert agent._consecutive_stale_streams >= 5
            assert not _retry_recovered_local_server(agent)
            with pytest.raises(RuntimeError, match="consecutive stale attempts"):
                request(kwargs)
        health = [row for row in wire if row["path"] == "/health"]
        posts = [row for row in wire if row["method"] == "POST"]
        assert len(health) == len(posts) == 1
        assert not health[0]["authorization_present"]
        assert posts[0]["path"] == "/v1/chat/completions"
        assert posts[0]["body"]["model"] == "local-fixture"
        assert posts[0]["body"].get("stream", False) is (dispatch == "stream")
        record_property("owned_local_peer_wire", json.dumps(wire))
    finally:
        release_stall.set()
        if agent is not None:
            agent.client.close()
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert not worker.is_alive()
