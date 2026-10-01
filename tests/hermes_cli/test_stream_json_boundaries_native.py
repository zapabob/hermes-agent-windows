"""Independent F11 sink and owned-entrypoint boundaries; no full CLI proof."""
from __future__ import annotations

import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from hermes_cli import stream_json as protocol


def events(output):
    return [json.loads(line) for line in output.splitlines()]


@pytest.mark.parametrize("outcome,code", [("success", 0), ("exit", 7), ("exception", 1), ("interrupt", 130), ("cleanup_failure", 1)])
def test_entrypoint_restores_stdout_context_and_defers_terminal(outcome, code, capsys):
    original = sys.stdout
    outer = object()
    token = protocol._current_sink.set(outer)
    seen = []

    @protocol.stream_json_entrypoint
    def owned(query=None, quiet=False, output_format="text"):
        assert quiet is True
        sink = protocol.current_emitter()
        assert sink is not outer
        assert sys.stdout is sys.stderr
        sink.bind_session("owned-boundary", "owned-model")
        sink.on_text_delta("猫\n ")
        sink.defer_result({"final_response": "canonical", "total_tokens": 9})
        try:
            if outcome == "exit":
                raise SystemExit(7)
            if outcome == "exception":
                raise RuntimeError("owned failure")
            if outcome == "interrupt":
                raise KeyboardInterrupt()
            return "return-value"
        finally:
            seen.append(sink._terminal_code)
            sys.stdout.write("owned cleanup diagnostic\n")
            if outcome == "cleanup_failure":
                raise RuntimeError("owned cleanup failure")

    try:
        if outcome == "success":
            assert owned(query="owned", output_format="stream-json") == "return-value"
        else:
            error_type = SystemExit if outcome in ("exit", "interrupt") else RuntimeError
            with pytest.raises(error_type) as error:
                owned(query="owned", output_format="stream-json")
            if error_type is SystemExit:
                assert error.value.code == code
        assert sys.stdout is original
        assert protocol.current_emitter() is outer
    finally:
        protocol._current_sink.reset(token)
    capture = capsys.readouterr()
    rows = events(capture.out)
    assert seen == [None], "terminal must follow existing cleanup"
    assert [row["type"] for row in rows] == ["system", "text", "result"]
    assert rows[-1]["exit_code"] == code
    if outcome in ("success", "exit"):
        assert rows[-1]["text"] == "canonical"
        assert rows[-1]["tokens"]["total"] == 9
    if outcome == "cleanup_failure":
        assert rows[-1]["error"] == "owned cleanup failure"
    assert "owned cleanup diagnostic" in capture.err
    assert "owned cleanup diagnostic" not in capture.out


def test_terminal_stops_all_callback_events_and_duplicate_result(capsys):
    sink = protocol.StreamJsonEmitter()
    assert sink.emit_result("first", exit_code=7) == 7
    sink.on_text_delta("late")
    sink.on_tool_start("late-id", "same-name", {"path": "late"})
    sink.on_tool_complete("late-id", "same-name", {}, "late")
    sink.bind_session("late-session")
    assert sink.emit_result("second", exit_code=130) == 7
    rows = events(capsys.readouterr().out)
    assert [row["type"] for row in rows] == ["system", "result"]
    assert rows[-1]["text"] == "first"


def test_explicit_zero_duration_consumes_started_identity(monkeypatch, capsys):
    clock = [10.0]
    monkeypatch.setattr(protocol.time, "time", lambda: clock[0])
    sink = protocol.StreamJsonEmitter()
    sink.on_tool_start("zero-id", "same-name", {})
    clock[0] = 20.0
    sink.on_tool_progress("tool.completed", "same-name", tool_call_id="zero-id", result="zero", duration=0)
    assert "zero-id" not in sink._tool_started
    clock[0] = 30.0
    sink.on_tool_progress("tool.completed", "same-name", tool_call_id="zero-id", result="unstarted")
    rows = events(capsys.readouterr().out)
    assert [row["duration_ms"] for row in rows if row["type"] == "tool_result"] == [0, 0]


@pytest.mark.parametrize("value,expected", [(False, "False"), (0, "0")])
def test_falsy_tool_result_is_retained(value, expected, capsys):
    sink = protocol.StreamJsonEmitter()
    sink.on_tool_complete("owned", "same-name", {}, value)
    row = events(capsys.readouterr().out)[-1]
    assert row["output"] == expected
    assert row["is_error"] is False


@pytest.mark.parametrize("value,is_error", [({"success": False}, True), ('{"success": false}', True), ({"error": "denied"}, True), ('{"error": "denied"}', True), ({"success": True}, False), ('{"success": true}', False)])
def test_existing_display_result_error_classification(value, is_error, capsys):
    sink = protocol.StreamJsonEmitter()
    sink.on_tool_complete("owned", "write_file", {}, value)
    assert events(capsys.readouterr().out)[-1]["is_error"] is is_error


def test_dedicated_callbacks_keep_identity_and_filtered_payload(capsys):
    legacy_calls = []
    agent = SimpleNamespace(stream_delta_callback=None,
                            tool_progress_callback=lambda *args, **kwargs: legacy_calls.append(args),
                            tool_start_callback=None, tool_complete_callback=None)
    sink = protocol.StreamJsonEmitter().attach(agent)
    assert agent.tool_progress_callback is None
    assert agent.tool_start_callback.__self__ is sink
    assert agent.tool_complete_callback.__self__ is sink
    filtered = {"token": "[REDACTED]", "path": "owned"}
    agent.tool_start_callback("actual-id", "same-name", filtered)
    agent.tool_complete_callback("actual-id", "same-name", filtered, '{"success": false, "error": "denied"}')
    captured = capsys.readouterr()
    rows = events(captured.out)
    assert [row["type"] for row in rows] == ["system", "tool_use", "tool_result"]
    assert rows[1]["input"] == filtered
    assert rows[1]["tool_call_id"] == rows[2]["tool_call_id"] == "actual-id"
    assert rows[2]["is_error"] is True
    assert legacy_calls == []


def test_real_concurrent_same_name_callbacks_write_atomic_jsonl(monkeypatch):
    class YieldingOutput(io.StringIO):
        def write(self, value):
            # Character writes make line-level locking observable under contention.
            from time import sleep
            for character in value:
                super().write(character)
                sleep(0)
            return len(value)

    output = YieldingOutput()
    monkeypatch.setattr(sys, "stdout", output)
    sink = protocol.StreamJsonEmitter()
    barrier = Barrier(4)

    def callback(index):
        identifier = f"owned-{index}"
        barrier.wait(timeout=10)
        sink.on_tool_start(identifier, "same-name", {"index": index, "text": "猫\n "})
        barrier.wait(timeout=10)
        sink.on_text_delta(f"delta-{index}\n猫")
        sink.on_tool_complete(identifier, "same-name", {}, f"result-{index}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(callback, index) for index in range(4)]
        for future in futures:
            future.result(timeout=20)
    sink.emit_result("done")
    rows = events(output.getvalue())
    assert len(rows) == 14
    assert rows[-1]["type"] == "result"
    for index in range(4):
        paired = [row for row in rows if row.get("tool_call_id") == f"owned-{index}"]
        assert [row["type"] for row in paired] == ["tool_use", "tool_result"]
        assert paired[0]["input"]["index"] == index
        assert paired[1]["output"] == f"result-{index}"
        assert paired[1]["duration_ms"] >= 0
    assert sink._tool_started == {}


def test_query_required_before_owned_function_and_context_change(capsys):
    called = []
    original = sys.stdout
    context = protocol.current_emitter()

    @protocol.stream_json_entrypoint
    def owned(query=None, quiet=False, output_format="text"):
        called.append(query)

    with pytest.raises(ValueError, match="single query"):
        owned(output_format="stream-json")
    assert called == []
    assert sys.stdout is original and protocol.current_emitter() is context
    assert capsys.readouterr().out == ""


def test_default_text_callthrough_preserves_return_arguments_stdout_context(capsys):
    original = sys.stdout
    context = protocol.current_emitter()
    value = object()

    @protocol.stream_json_entrypoint
    def owned(query=None, quiet=False, output_format="text"):
        assert (query, quiet, output_format) == ("owned", False, "text")
        assert sys.stdout is original and protocol.current_emitter() is context
        sys.stdout.write("plain owned\n")
        return value

    assert owned("owned") is value
    assert capsys.readouterr().out == "plain owned\n"
