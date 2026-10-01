"""JSONL presentation for the existing single-query CLI execution path.

Adapted from NousResearch Hermes Agent's stream-json protocol at
1a269fcd3b61971bd05e841f80154279dd0a7e65. Execution, admission and
session finalization remain owned by the downstream CLI and agent.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from contextvars import ContextVar
from functools import wraps
import inspect
import json
import sys
from threading import RLock
import time
from typing import Any

_TOOL_OUTPUT_CAP = 5000
_current_sink: ContextVar[StreamJsonEmitter | None] = ContextVar("stream_json_sink", default=None)


def stream_json_requested(args) -> bool:
    """Validate the public flag before interactive routing or runtime setup."""
    if getattr(args, "output_format", "text") != "stream-json":
        return False
    if not (getattr(args, "query", None) or getattr(args, "query_file", None)):
        sys.stderr.write("Error: --format stream-json requires -q/--query or --query-file.\n")
        raise SystemExit(2)
    if getattr(args, "tui", False):
        sys.stderr.write("Error: --format stream-json cannot be used with --tui.\n")
        raise SystemExit(2)
    args.quiet = True
    return True


def current_emitter() -> StreamJsonEmitter | None:
    """Return the sink for this invocation without changing configuration."""
    return _current_sink.get()


class StreamJsonEmitter:
    """Serialize callbacks atomically to the captured protocol output stream."""

    def __init__(self, model: str = "", session_id: str = "", *, initialize: bool = True):
        self._output = sys.stdout
        self._lock = RLock()
        self._session_id = session_id
        self._start = time.time()
        self._tool_started: dict[str, float] = {}
        self._initialized = False
        self._terminal_code: int | None = None
        self._pending: Any = None
        if initialize:
            self.bind_session(session_id, model)

    def bind_session(self, session_id: str, model: str = "") -> None:
        with self._lock:
            self._session_id = session_id or self._session_id
            if not self._initialized:
                self._initialized = True
                self._emit({"type": "system", "subtype": "init", "model": model,
                            "session_id": self._session_id})

    def attach(self, agent) -> StreamJsonEmitter:
        agent.stream_delta_callback = self.on_text_delta
        # The downstream executor's dedicated callbacks carry the actual ID
        # and filtered display payload. Its legacy progress callback does not.
        if hasattr(agent, "tool_start_callback") and hasattr(agent, "tool_complete_callback"):
            agent.tool_progress_callback = None
            agent.tool_start_callback = self.on_tool_start
            agent.tool_complete_callback = self.on_tool_complete
        else:
            agent.tool_progress_callback = self.on_tool_progress
        return self

    def on_text_delta(self, text: str | None) -> None:
        if text is not None and text != "":
            self._emit({"type": "text", "text": str(text)})

    def on_tool_start(self, tool_call_id: str, name: str, args: dict) -> None:
        self.on_tool_progress("tool.started", name, args=args, tool_call_id=tool_call_id)

    def on_tool_complete(self, tool_call_id: str, name: str, args: dict, result: Any) -> None:
        data = result
        if isinstance(result, str):
            try:
                data = json.loads(result)
            except (ValueError, TypeError):
                data = None
        is_error = isinstance(data, dict) and bool(data.get("error") or data.get("success") is False)
        self.on_tool_progress("tool.completed", name, result=result,
                              tool_call_id=tool_call_id, is_error=is_error)

    def on_tool_progress(self, event_type: str, tool_name: str | None = None,
                         preview: Any = None, args: Any = None, **kwargs: Any) -> None:
        name = tool_name or "unknown"
        key = kwargs.get("tool_call_id") or name
        with self._lock:
            if event_type == "tool.started":
                self._tool_started[key] = time.time()
                payload: dict[str, Any] = {"type": "tool_use", "name": name}
                if kwargs.get("tool_call_id"):
                    payload["tool_call_id"] = kwargs["tool_call_id"]
                if isinstance(args, dict):
                    payload["input"] = args
                self._emit(payload)
            elif event_type == "tool.completed":
                now = time.time()
                started = self._tool_started.pop(key, now)
                duration = kwargs.get("duration")
                if duration is None:
                    duration = now - started
                value = kwargs.get("result")
                output = "" if value is None else str(value)
                self._emit({"type": "tool_result", "name": name,
                            **({"tool_call_id": kwargs["tool_call_id"]} if kwargs.get("tool_call_id") else {}),
                            "output": output if len(output) <= _TOOL_OUTPUT_CAP else output[:_TOOL_OUTPUT_CAP] + "...",
                            "duration_ms": max(0, int(float(duration) * 1000)),
                            "is_error": bool(kwargs.get("is_error", False))})

    def defer_result(self, result: Any, session_id: str = "") -> None:
        """Keep the canonical result until existing finalization has unwound."""
        self._pending = result
        self._session_id = session_id or self._session_id

    def emit_result(self, result: Any, session_id: str = "", exit_code: int = 0) -> int:
        with self._lock:
            if self._terminal_code is not None:
                return self._terminal_code
            self.bind_session(session_id)
            data = result if isinstance(result, dict) else {"final_response": "" if result is None else str(result)}
            exit_code = exit_code or (1 if data.get("failed") else 0)
            payload = {"type": "result", "session_id": session_id or self._session_id,
                       "exit_code": exit_code, "text": data.get("final_response") or "",
                       "tokens": {"input": data.get("input_tokens") or 0, "output": data.get("output_tokens") or 0,
                                  "total": data.get("total_tokens") or 0, "cache_read": data.get("cache_read_tokens") or 0,
                                  "cache_write": data.get("cache_write_tokens") or 0},
                       "duration_ms": max(0, int((time.time() - self._start) * 1000))}
            if data.get("error"):
                payload["error"] = str(data["error"])
            self._terminal_code = exit_code
            self._emit(payload)
            sys.stderr.write(f"\nsession_id: {payload['session_id']}\n")
            return exit_code

    def _emit(self, obj: dict) -> None:
        with self._lock:
            if self._terminal_code is not None and obj.get("type") != "result":
                return
            try:
                self._output.write(json.dumps({**obj, "timestamp": int(time.time() * 1000)}, ensure_ascii=False) + "\n")
                self._output.flush()
            except (BrokenPipeError, OSError):
                pass


def stream_json_entrypoint(function):
    """Scope presentation around the existing CLI, preserving its lifecycle."""
    signature = inspect.signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        if bound.arguments.get("output_format", "text") != "stream-json":
            return function(*args, **kwargs)
        if not (bound.arguments.get("query") or bound.arguments.get("q")):
            raise ValueError("stream-json requires a single query")
        bound.arguments["quiet"] = True
        if isinstance(current_emitter(), StreamJsonEmitter):
            return function(*bound.args, **bound.kwargs)
        return _run_with_sink(function, bound.args, bound.kwargs)

    return wrapped


def stream_json_chat_entrypoint(function):
    """Include pre-agent chat diagnostics without changing session resolution."""
    @wraps(function)
    def wrapped(args):
        if not stream_json_requested(args):
            return function(args)
        return _run_with_sink(function, (args,), {})
    return wrapped


def _run_with_sink(function, args, kwargs):
    emitter = StreamJsonEmitter(initialize=False)
    token = _current_sink.set(emitter)
    try:
        with redirect_stdout(sys.stderr):
            try:
                value = function(*args, **kwargs)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
                result = emitter._pending
                if result is None:
                    result = {"failed": bool(code), "error": "Interrupted" if code == 130 else "single-query startup failed" if code else ""}
                emitter.emit_result(result, exit_code=code)
                raise
            except KeyboardInterrupt:
                emitter.emit_result({"failed": True, "error": "Interrupted"}, exit_code=130)
                raise SystemExit(130)
            except Exception as exc:
                emitter.emit_result({"failed": True, "error": str(exc)}, exit_code=1)
                raise
            else:
                emitter.emit_result(emitter._pending if emitter._pending is not None else value)
                return value
    finally:
        _current_sink.reset(token)
