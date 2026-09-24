from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent import chat_completion_helpers as cch
from downstream.delegation.network_budget import (
    RequestBudget,
    RequestBudgetError,
    RequestTimeouts,
    bind_request_lease,
)


def _wait(event: threading.Event, timeout: float = 3.0) -> None:
    assert event.wait(timeout), "controlled request did not reach expected state"


def test_cancelled_call_keeps_lease_until_provider_worker_exits() -> None:
    agent = MagicMock()
    agent.api_mode = "anthropic_messages"
    agent.provider = "anthropic"
    agent.platform = "subagent"
    agent._interrupt_requested = True
    agent._compute_non_stream_stale_timeout.return_value = 5.0
    agent._codex_silent_hang_hint = MagicMock(return_value=None)
    request_client = MagicMock()
    agent._create_request_anthropic_client.return_value = request_client
    agent._abort_request_anthropic_client = MagicMock()
    agent._close_request_anthropic_client = MagicMock()
    provider_entered = threading.Event()
    allow_provider_exit = threading.Event()

    def blocked_provider(*_args, **_kwargs):
        provider_entered.set()
        allow_provider_exit.wait(15.0)
        raise RuntimeError("controlled transport exit")

    agent._anthropic_messages_create.side_effect = blocked_provider
    budget = RequestBudget(per_account_limit=2, reserved_interactive_slots=1)
    lease = budget.reserve("admission-account", "inference")
    try:
        with pytest.raises(InterruptedError):
            with lease, bind_request_lease(lease):
                cch.interruptible_api_call(agent, {"model": "test-model", "messages": []})
        _wait(provider_entered)

        with pytest.raises(RequestBudgetError) as caught:
            budget.reserve("admission-account", "inference")
        assert caught.value.code == "request_outcome_unknown"
        assert budget.status()["requests"][0]["active_workers"] == 1
    finally:
        allow_provider_exit.set()

    deadline = time.monotonic() + 3.0
    while budget.status()["active"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert budget.status()["active"] == 0
    retry = budget.reserve("admission-account", "inference")
    retry.finish()


def test_request_proxy_fences_transient_interrupt_generation() -> None:
    from downstream.delegation.inference_port import _ParentRequestAgent

    requester = SimpleNamespace(
        _interrupt_requested=False,
        _inference_cancel_generation=0,
    )
    request_agent = _ParentRequestAgent(
        "unused-owner-token",
        requester,
        "request-id",
        cancel_generation=0,
    )
    assert request_agent._interrupt_requested is False

    requester._inference_cancel_generation = 1
    requester._interrupt_requested = True
    requester._interrupt_requested = False

    assert request_agent._interrupt_requested is True


def test_slow_local_provider_does_not_block_status_or_cancel() -> None:
    entered = threading.Event()
    release_response = threading.Event()
    cancelled = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            entered.set()
            release_response.wait(3.0)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()
    budget = RequestBudget()
    lease = budget.reserve("slow-provider-account", "inference")
    lease.set_abort_callback(lambda _reason: cancelled.set())

    def request() -> None:
        from urllib.request import urlopen

        lease.worker_started()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/slow", timeout=2.0) as response:
                response.read()
                lease.mark_progress()
        finally:
            lease.worker_finished()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(request)
            _wait(entered)
            started = time.monotonic()
            assert budget.status()["active"] == 1
            assert budget.cancel(lease.request_id, reason="user_cancel")
            _wait(cancelled)
            assert time.monotonic() - started < 0.5
            lease.finish(outcome="unknown")
            with pytest.raises(RequestBudgetError) as caught:
                budget.reserve("slow-provider-account", "inference")
            assert caught.value.code == "request_outcome_unknown"
            release_response.set()
            future.result(timeout=3.0)
            lease.finish(outcome="cancelled")
    finally:
        release_response.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3.0)

    assert not server_thread.is_alive()
    assert budget.status()["active"] == 0


def test_direct_delegated_trickle_is_aborted_within_lease_deadline() -> None:
    import socket
    from urllib.request import urlopen

    entered = threading.Event()
    aborted = threading.Event()
    response_holder = {}

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            entered.set()
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            for _ in range(100):
                try:
                    self.wfile.write(b"x")
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.02)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()

    def _create(**_kwargs):
        response = urlopen(
            f"http://127.0.0.1:{server.server_port}/trickle", timeout=1.0
        )
        response_holder["response"] = response
        return response.read()

    def _abort(_client, *, reason: str) -> None:
        assert reason == "stale_call_kill"
        aborted.set()
        response = response_holder.get("response")
        raw = getattr(getattr(response, "fp", None), "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=_create),
        ),
    )
    agent = MagicMock()
    agent.api_mode = "chat_completions"
    agent.provider = "openai"
    agent.platform = "subagent"
    agent.base_url = None
    agent._interrupt_requested = False
    agent._consecutive_stale_streams = 0
    agent._compute_non_stream_stale_timeout.return_value = 2.0
    agent._create_request_openai_client.return_value = client
    agent._abort_request_openai_client.side_effect = _abort
    agent._close_request_openai_client.return_value = None
    agent._touch_activity.return_value = None

    budget = RequestBudget(
        timeouts={"inference": RequestTimeouts(0.05, 0.08, 0.25)}
    )
    lease = budget.reserve("direct-path-account", "inference")
    started = time.monotonic()
    try:
        with lease, bind_request_lease(lease):
            with pytest.raises(TimeoutError):
                cch.direct_api_call(agent, {"model": "controlled-test"})
        elapsed = time.monotonic() - started
        assert entered.is_set()
        assert aborted.is_set()
        assert elapsed < 1.0
    finally:
        response = response_holder.get("response")
        if response is not None:
            response.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3.0)

    assert not server_thread.is_alive()
