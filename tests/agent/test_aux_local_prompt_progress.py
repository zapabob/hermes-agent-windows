"""Local auxiliary prefill must advance deadlines only for observed new work."""
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from agent import auxiliary_client as aux
from agent.conversation_compression import CompressionCommitFence


def _chunk(processed=None, *, text=None, finish=None, usage=None, server_ms=None):
    progress = {} if processed is None else {"processed": processed, "total": 100}
    if server_ms is not None:
        progress["time_ms"] = server_ms
    return SimpleNamespace(
        id="owned-aux", model="fixture", usage=usage, model_extra={"prompt_progress": progress},
        choices=[SimpleNamespace(finish_reason=finish, delta=SimpleNamespace(
            content=text, tool_calls=None, reasoning=None, reasoning_content=None, refusal=None,
        ))],
    )


class _Client:
    def __init__(self, samples, clock, asynchronous=False):
        self.base_url = "http://127.0.0.1:9821/v1"
        self.calls = []
        self.closed = False
        self.samples = samples
        self.clock = clock
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=self.acreate if asynchronous else self.create,
        ))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not kwargs.get("stream"):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="plain"))])
        def stream():
            try:
                for at, chunk in self.samples:
                    self.clock[0] = at
                    yield chunk
            finally:
                self.closed = True
        return stream()

    async def acreate(self, **kwargs):
        self.calls.append(kwargs)
        async def stream():
            try:
                for at, chunk in self.samples:
                    self.clock[0] = at
                    yield chunk
            finally:
                self.closed = True
        return stream()


def _run(client, kwargs, asynchronous):
    return (asyncio.run(aux._acreate_with_progress(client, kwargs)) if asynchronous
            else aux._create_with_progress(client, kwargs))


@pytest.mark.parametrize("asynchronous", [False, True])
def test_only_advancing_progress_and_real_output_tick_hook(monkeypatch, asynchronous):
    clock, ticks = [0.0], []
    monkeypatch.setattr(aux, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=1, total_tokens=12)
    samples = [(0.5, _chunk(10)), (1, _chunk(10)), (1.5, _chunk(9)), (2, _chunk(11)),
               (2.5, _chunk()), (3, _chunk(11, usage=usage)),
               (3.5, _chunk(text="summary")), (4, _chunk(finish="stop"))]
    client = _Client(samples, clock, asynchronous)
    with aux.aux_progress_hook(lambda: ticks.append(clock[0])):
        result = _run(client, {"model": "fixture", "messages": [], "timeout": 2.5}, asynchronous)
    assert ticks == [0, 0.5, 2, 3.5, 4]
    assert result.choices[0].message.content == "summary"
    assert result.usage is usage and client.closed


@pytest.mark.parametrize("asynchronous", [False, True])
def test_constant_usage_and_heartbeat_cannot_mask_logical_idle(monkeypatch, asynchronous):
    clock, ticks = [0.0], []
    monkeypatch.setattr(aux, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    samples = [(i / 4, _chunk(10, usage=SimpleNamespace(prompt_tokens=10))) for i in range(1, 9)]
    samples.append((2.5, _chunk(text="too late", finish="stop")))
    client = _Client(samples, clock, asynchronous)
    with aux.aux_progress_hook(lambda: ticks.append(clock[0])):
        with pytest.raises(TimeoutError, match="timed out"):
            _run(client, {"model": "fixture", "messages": [], "timeout": 1}, asynchronous)
    assert ticks == [0, 0.25] and client.closed


@pytest.mark.parametrize("asynchronous", [False, True])
def test_prompt_reading_is_excluded_from_aux_total_but_generation_is_not(monkeypatch, asynchronous):
    clock = [0.0]
    monkeypatch.setattr(aux, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(aux, "_aux_stream_total_ceiling", lambda _timeout: 3.0)
    samples = [(1, _chunk(10, server_ms=1000)), (2, _chunk(20, server_ms=2000)),
               (3, _chunk(30, server_ms=3000)), (4, _chunk(text="summary")),
               (4.5, _chunk(finish="stop"))]
    client = _Client(samples, clock, asynchronous)
    with aux.aux_progress_hook(lambda: None):
        result = _run(client, {"model": "fixture", "messages": [], "timeout": 2}, asynchronous)
    assert result.choices[0].message.content == "summary" and client.closed


@pytest.mark.parametrize("closed_by", ["cancel", "revoke", "deadline"])
def test_closed_compression_fence_rejects_late_progress(monkeypatch, closed_by):
    from agent import conversation_compression as compression

    clock = [0.0]
    monkeypatch.setattr(compression, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    fence = CompressionCommitFence(total_ceiling_seconds=5)
    clock[0] = 1
    fence.touch_progress()
    if closed_by == "cancel":
        assert fence.cancel_before_commit()
    elif closed_by == "revoke":
        fence.revoke_commit_admission()
    else:
        clock[0] = 6
    clock[0] += 1
    fence.touch_progress()
    assert fence.seconds_since_progress() == clock[0] - 1
    assert not fence.begin_commit()


@pytest.mark.parametrize(("capability", "model", "route", "explicit", "expected"), [
    (True, "fixture", "http://127.0.0.1:9821/v1/", None, True),
    (False, "fixture", "http://127.0.0.1:9821/v1", None, None),
    ("true", "fixture", "http://127.0.0.1:9821/v1", None, None),
    (1, "fixture", "http://127.0.0.1:9821/v1", None, None),
    (True, "other", "http://127.0.0.1:9821/v1", None, None),
    (True, "fixture", "http://127.0.0.1:9821/other/v1", None, None),
    (True, "fixture", "http://127.0.0.1:9821/v1", False, False),
])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_progress_request_matches_actual_client_route_and_exact_model(
    monkeypatch, capability, model, route, explicit, expected, asynchronous,
):
    config = {"custom_providers": [{"name": "fixture", "base_url": route,
                                    "models": {model: {"prompt_progress": capability}}}]}
    original_config = copy.deepcopy(config)
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda: config)
    client = _Client([(0.1, _chunk(text="ok", finish="stop"))], [0.0], asynchronous)
    kwargs = {"model": "fixture", "messages": [], "extra_body": {"operator_field": "kept"}}
    if explicit is not None:
        kwargs["extra_body"]["return_progress"] = explicit
    original_kwargs = copy.deepcopy(kwargs)
    with aux.aux_progress_hook(lambda: None):
        result = _run(client, kwargs, asynchronous)
    assert client.calls[0]["extra_body"].get("return_progress") is expected
    assert client.calls[0]["extra_body"]["operator_field"] == "kept"
    assert result.choices[0].message.content == "ok"
    assert kwargs == original_kwargs and config == original_config


def test_reading_credit_uses_measured_monotone_time_and_ignores_queue():
    from agent.local_prompt_progress import PromptReadingClock

    clock = PromptReadingClock(0)
    assert clock.tick(_chunk(10, server_ms=1000), 5)
    assert clock.seconds == 1, "four queued seconds are not measured reading"
    assert not clock.tick(_chunk(10, server_ms=999999), 6)
    assert clock.tick(_chunk(20, server_ms=2000), 7)
    assert not clock.tick(_chunk(15, server_ms=3000), 8)
    assert clock.tick(_chunk(30, server_ms=1500), 9)
    assert clock.seconds == 2, "server clock regression cannot lower its high-water mark"
    assert clock.tick(_chunk(40, server_ms=2100), 10)
    assert clock.seconds == pytest.approx(2.1)


@pytest.mark.parametrize("server_ms", [None, True, "1000", -1, float("nan"), float("inf")])
def test_forward_counts_without_measured_duration_grant_idle_only(server_ms):
    from agent.local_prompt_progress import PromptReadingClock

    clock = PromptReadingClock(0)
    assert clock.tick(_chunk(10, server_ms=server_ms), 10)
    assert clock.seconds == 0


@pytest.mark.parametrize("closed_by", ["cancel", "revoke", "deadline", "scope", "commit"])
def test_reading_cannot_revive_or_extend_closed_compression(monkeypatch, closed_by):
    from agent import conversation_compression as compression

    clock = [0.0]
    monkeypatch.setattr(compression, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    fence = CompressionCommitFence(5)
    clock[0] = 1
    fence.touch_progress()
    if closed_by == "cancel":
        fence.cancel_before_commit()
    elif closed_by == "revoke":
        fence.revoke_commit_admission()
    elif closed_by == "deadline":
        clock[0] = 6
    elif closed_by == "scope":
        fence.close_progress()
    else:
        assert fence.begin_commit()
        fence.finish_commit()
    previous_deadline = fence.deadline_monotonic
    assert not fence.extend_deadline(100)
    fence.touch_progress()
    assert fence.deadline_monotonic == previous_deadline
    assert fence.seconds_since_progress() == clock[0] - 1


def test_progress_and_reading_never_wait_for_busy_commit_lock():
    fence = CompressionCommitFence(5)
    assert fence.begin_commit()
    try:
        fence.touch_progress()
        assert not fence.extend_deadline(100)
        assert not fence.progress_observed
    finally:
        fence.finish_commit()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_known_capable_model_streams_without_display_hook(monkeypatch, asynchronous):
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda: {
        "custom_providers": [{"name": "fixture", "base_url": "http://127.0.0.1:9821/v1",
                              "models": {"fixture": {"prompt_progress": True}}}],
    })
    client = _Client([(0.1, _chunk(text="ok", finish="stop"))], [0.0], asynchronous)
    result = _run(client, {"model": "fixture", "messages": []}, asynchronous)
    assert client.calls[0]["stream"] is True
    assert client.calls[0]["extra_body"]["return_progress"] is True
    assert result.choices[0].message.content == "ok"


def test_shared_fence_deadline_controls_worker_after_measured_reading(monkeypatch):
    from agent import conversation_compression as compression
    from agent.local_prompt_progress import prompt_reading_budget

    clock = [0.0]
    timer = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(aux, "time", timer)
    monkeypatch.setattr(compression, "time", timer)
    fence = CompressionCommitFence(3)
    with prompt_reading_budget(fence.extend_deadline, lambda: fence.deadline_monotonic), aux.aux_progress_hook(fence.touch_progress):
        acc = aux._ChatStreamAccumulator(prompt_progress=True, idle_timeout=2)
        for stamp in (1, 2, 3):
            clock[0] = stamp
            acc.feed(_chunk(stamp * 10, server_ms=stamp * 1000))
        assert fence.deadline_monotonic == 6
        clock[0] = 4
        acc.feed(_chunk(text="summary"))
        clock[0] = 6
        with pytest.raises(TimeoutError, match="timed out"):
            acc.feed(_chunk(40, server_ms=4000))
    assert fence.deadline_monotonic == 6 and fence.is_cancelled


def test_old_accumulator_cannot_report_into_next_attempt_scope(monkeypatch):
    from agent import conversation_compression as compression
    from agent.local_prompt_progress import prompt_reading_budget

    clock = [0.0]
    timer = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(aux, "time", timer)
    monkeypatch.setattr(compression, "time", timer)
    first, second = CompressionCommitFence(5), CompressionCommitFence(5)
    with prompt_reading_budget(first.extend_deadline, lambda: first.deadline_monotonic), aux.aux_progress_hook(first.touch_progress):
        old = aux._ChatStreamAccumulator(prompt_progress=True)
    first.close_progress()
    with prompt_reading_budget(second.extend_deadline, lambda: second.deadline_monotonic), aux.aux_progress_hook(second.touch_progress):
        clock[0] = 1
        old.feed(_chunk(10, server_ms=1000))
    assert first.deadline_monotonic == second.deadline_monotonic == 5
    assert not first.progress_observed and not second.progress_observed


def test_captured_cancel_remains_latched_when_host_event_is_cleared():
    import threading

    event = threading.Event()
    with aux.aux_interrupt_protection(cancel_event=event):
        acc = aux._ChatStreamAccumulator(prompt_progress=True)
    event.set()
    with pytest.raises(aux.AuxiliaryExplicitCancellation):
        acc.feed(_chunk(10))
    event.clear()
    with pytest.raises(aux.AuxiliaryExplicitCancellation):
        acc.feed(_chunk(text="late"))
    assert acc.content_parts == []


@pytest.mark.parametrize("closed_by", ["cancel", "stop"])
def test_retired_heartbeat_start_has_no_activity(monkeypatch, closed_by):
    from agent.conversation_compression import _CompressionActivityHeartbeat

    touches = []
    agent = SimpleNamespace(_touch_activity=lambda *a, **kw: touches.append((a, kw)))
    fence = CompressionCommitFence(5)
    heartbeat = _CompressionActivityHeartbeat(agent, commit_fence=fence)
    if closed_by == "cancel":
        fence.cancel_before_commit()
    else:
        heartbeat._stop.set()
    assert heartbeat.start() is heartbeat
    assert not heartbeat._thread.is_alive() and touches == []


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(("shared", "individual"), [(10, 3), (3, 10)])
def test_shared_and_individual_generation_ceilings_are_both_enforced(monkeypatch, asynchronous, shared, individual):
    from agent import conversation_compression as compression
    from agent.local_prompt_progress import prompt_reading_budget

    clock = [0.0]
    timer = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(aux, "time", timer)
    monkeypatch.setattr(compression, "time", timer)
    monkeypatch.setattr(aux, "_aux_stream_total_ceiling", lambda _timeout: individual)
    fence = CompressionCommitFence(shared)
    samples = [(i / 2, _chunk(text="output")) for i in range(1, 9)]
    client = _Client(samples, clock, asynchronous)
    with prompt_reading_budget(fence.extend_deadline, lambda: fence.deadline_monotonic), aux.aux_progress_hook(fence.touch_progress):
        with pytest.raises(TimeoutError, match="timed out"):
            _run(client, {"model": "fixture", "messages": [], "timeout": 1}, asynchronous)
    assert clock[0] == 3 and client.closed


def test_completed_worker_timeout_does_not_busy_wait(monkeypatch):
    import concurrent.futures
    from agent import conversation_compression as compression

    clock = [0.0]
    monkeypatch.setattr(compression, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    class CountedFuture(concurrent.futures.Future):
        polls = 0
        def result(self, timeout=None):
            self.polls += 1
            clock[0] += 0.01
            return super().result(timeout)

    future = CountedFuture()
    future.set_exception(TimeoutError("provider finished with timeout"))
    fence = CompressionCommitFence()
    def submit(_callback, worker_fence):
        worker_fence.touch_progress()
        return future
    monkeypatch.setattr(compression, "_get_compress_timeout_executor", lambda: SimpleNamespace(submit=submit))
    messages = [{"role": "user", "content": "preserve"}]
    result = compression.run_compress_context_with_progress_timeout(
        worker=lambda _f: None, messages=messages, system_prompt_fallback="fallback",
        idle_timeout_seconds=0.1, total_ceiling_seconds=0.3, fence=fence, stall_fallback=False,
    )
    assert result == (messages, "fallback") and fence.is_cancelled
    assert future.polls == 1, "a settled worker exception must not be mistaken for another wait expiry"


@pytest.mark.parametrize("operation", ["extend", "touch"])
def test_close_serializes_with_callback_already_past_guard(operation):
    import inspect
    import sys
    import threading

    fence = CompressionCommitFence(20)
    method = fence.extend_deadline if operation == "extend" else fence.touch_progress
    source, first = inspect.getsourcelines(method)
    assignment = "self._deadline += seconds" if operation == "extend" else "self._last_progress = now"
    line = first + next(i for i, text in enumerate(source) if assignment in text)
    paused, release, closing, closed = (threading.Event() for _ in range(4))
    outcomes = []
    def trace(frame, event, _arg):
        if frame.f_code is method.__func__.__code__ and event == "line" and frame.f_lineno == line:
            paused.set()
            assert release.wait(3)
        return trace
    def callback():
        sys.settrace(trace)
        try:
            outcomes.append(method(1) if operation == "extend" else method())
        finally:
            sys.settrace(None)
    snapshots = []
    def close():
        closing.set()
        fence.close_progress()
        snapshots.append((fence.deadline_monotonic, fence._last_progress))
        closed.set()
    writer = threading.Thread(target=callback)
    closer = threading.Thread(target=close)
    writer.start()
    try:
        assert paused.wait(3)
        closer.start()
        assert closing.wait(3)
        returned_while_callback_paused = closed.wait(0.1)
    finally:
        release.set()
        writer.join(3)
        if closer.ident is not None:
            closer.join(3)
    assert not writer.is_alive() and not closer.is_alive() and closed.is_set()
    assert not returned_while_callback_paused, "close must settle admitted callbacks before returning"
    assert snapshots == [(fence.deadline_monotonic, fence._last_progress)]
    assert not fence.extend_deadline(1)
    fence.touch_progress()
    assert snapshots == [(fence.deadline_monotonic, fence._last_progress)]
