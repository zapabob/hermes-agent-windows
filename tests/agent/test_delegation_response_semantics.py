"""Behavioral contracts for parent-owned provider response semantics."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent.codex_runtime import _consume_codex_event_stream
from downstream.delegation.inference_port import (
    InferencePortError,
    InferenceTurn,
    ParentInferencePort,
)
from run_agent import AIAgent


def _field(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(**values)


class _ChildOwner:
    def __init__(self, parent: Any):
        self.provider = parent.provider
        self.model = parent.model
        self.api_mode = parent.api_mode
        self.requested_model = f"configured:{parent.model}"
        self.reasoning_config = {"effort": "high"}
        self.valid_tool_names = {"controlled_test_tool"}
        self._inference_cancel_generation = 0
        self._interrupt_requested = False
        self._active_request_abort = None
        self.platform = "subagent"
        self.session_id = "response-semantics-child"
        self.quiet_mode = True


class _RecordedParent:
    def __init__(self, *, api_mode: str, model: str, streams=None):
        self.provider = "openai"
        self.model = model
        self.requested_model = f"configured:{model}"
        self.api_mode = api_mode
        self.base_url = "https://provider.invalid/v1"
        self.streams = list(streams or [])

    def _create_request_openai_client(self, *, reason, api_kwargs):
        return object()

    def _abort_request_openai_client(self, _client, *, reason):
        return None

    def _close_request_openai_client(self, _client, *, reason):
        return None

    def _run_codex_stream(self, _api_kwargs, *, client, on_first_delta=None):
        assert client is not None
        events = self.streams.pop(0)
        return _consume_codex_event_stream(events, model=self.model)


def _tool_schema() -> dict[str, Any]:
    function = {
        "name": "controlled_test_tool",
        "description": "Records one controlled test invocation.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    }
    return {"type": "function", "function": function}


def _tool_response(*, finish_reason="tool_calls", ids=("call-1",)):
    return _field(
        id="synthetic-chat-response",
        model="reported-model",
        choices=[
            _field(
                finish_reason=finish_reason,
                message=_field(
                    role="assistant",
                    content=None,
                    refusal=None,
                    tool_calls=[
                        _field(
                            id=call_id,
                            type="function",
                            function=_field(
                                name="controlled_test_tool",
                                arguments='{"value":"ok"}',
                            ),
                        )
                        for call_id in ids
                    ],
                ),
            )
        ],
    )


def _final_chat_response():
    return _field(
        id="synthetic-chat-final",
        model="reported-model",
        choices=[
            _field(
                finish_reason="stop",
                message=_field(
                    role="assistant", content="done", refusal=None, tool_calls=[]
                ),
            )
        ],
    )


def _response_events(*, status="completed", tool_calls=(), commentary="working", final="done"):
    events = []
    output_index = 0
    if commentary is not None:
        events.extend(
            [
                _field(
                    type="response.output_item.added",
                    output_index=output_index,
                    item=_field(type="message", id="msg-commentary", phase="commentary"),
                ),
                _field(
                    type="response.output_item.done",
                    output_index=output_index,
                    item=_field(
                        type="message",
                        id="msg-commentary",
                        role="assistant",
                        phase="commentary",
                        status="completed",
                        content=[_field(type="output_text", text=commentary)],
                    ),
                ),
            ]
        )
        output_index += 1
    for call_id, name, arguments in tool_calls:
        events.extend(
            [
                _field(
                    type="response.output_item.added",
                    output_index=output_index,
                    item=_field(
                        type="function_call",
                        id=f"fc_{call_id}",
                        call_id=call_id,
                        name=name,
                        arguments=arguments,
                    ),
                ),
                _field(
                    type="response.output_item.done",
                    output_index=output_index,
                    item=_field(
                        type="function_call",
                        id=f"fc_{call_id}",
                        call_id=call_id,
                        name=name,
                        arguments=arguments,
                        status="completed",
                    ),
                ),
            ]
        )
        output_index += 1
    if final is not None:
        events.append(
            _field(
                type="response.output_item.done",
                output_index=output_index,
                item=_field(
                    type="message",
                    id="msg-final",
                    role="assistant",
                    phase="final_answer",
                    status="completed",
                    content=[_field(type="output_text", text=final)],
                ),
            )
        )
    terminal_type = {
        "completed": "response.completed",
        "incomplete": "response.incomplete",
        "failed": "response.failed",
    }.get(status, "response.completed")
    events.append(
        _field(
            type=terminal_type,
            response=_field(
                id="synthetic-responses",
                model="reported-model",
                status=status,
                output=None,
            ),
        )
    )
    return events


def _bind_parent_port(parent, child):
    port = ParentInferencePort.for_parent(parent)
    port.bind_child(
        child,
        max_calls=4,
        max_tokens=4096,
        allowed_tool_names=child.valid_tool_names,
        reasoning_config=child.reasoning_config,
    )
    return port


def _request_turn(child, tool_schema):
    request = {
        "model": child.model,
        "tools": [tool_schema],
        "messages": [{"role": "user", "content": "run the test tool"}],
        "reasoning": {"effort": "medium"},
    }
    turn = InferenceTurn(
        api_kwargs=request,
        original_api_kwargs=request,
        requester=child,
    )
    return turn


def test_normalized_turn_preserves_terminal_text_commentary_and_provenance(monkeypatch):
    parent = _RecordedParent(api_mode="codex_responses", model="selected-model")
    child = _ChildOwner(parent)
    port = _bind_parent_port(parent, child)
    tool_schema = _tool_schema()
    response = _consume_codex_event_stream(
        _response_events(commentary="working", final="done"),
        model="reported-model",
    )
    response.reasoning_effort = "low"
    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call",
        lambda _request_agent, _request: response,
    )

    turn = port.complete(
        _request_turn(child, tool_schema),
        route_binding=port.route_binding,
        cancel_generation=0,
    )

    assert turn.terminal_status == "completed"
    assert turn.final_text == "done"
    assert turn.commentary_count == 1
    assert turn.configured_model == "configured:selected-model"
    assert turn.requested_model == "selected-model"
    assert turn.reported_model == "reported-model"
    assert turn.configured_effort == "high"
    assert turn.wire_effort == "medium"
    assert turn.reported_effort == "low"
    assert turn.failure_code is None


@pytest.mark.parametrize(
    ("finish_reason", "ids"),
    [
        ("length", ("call-1",)),
        ("tool_calls", ("call-1", "call-1")),
        ("provider_pending", ("call-1",)),
    ],
    ids=["incomplete-terminal", "duplicate-call-id", "unknown-terminal"],
)
def test_controlled_chat_loop_does_not_dispatch_untrusted_tool_calls(
    monkeypatch, finish_reason, ids
):
    model = "selected-chat-model"
    parent = _RecordedParent(api_mode="chat_completions", model=model)
    port = ParentInferencePort.for_parent(parent)
    child = AIAgent(
        base_url="",
        api_key=None,
        provider=parent.provider,
        api_mode=parent.api_mode,
        model=model,
        inference_port=port,
        credential_pool=None,
        enabled_toolsets=[],
        max_iterations=3,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    schema = _tool_schema()
    child.tools = [schema]
    child.valid_tool_names = {"controlled_test_tool"}
    child.requested_model = f"configured:{model}"
    port.bind_child(
        child,
        max_calls=4,
        max_tokens=child.max_tokens,
        allowed_tool_names=child.valid_tool_names,
        reasoning_config=child.reasoning_config,
    )
    monkeypatch.setattr("run_agent.get_tool_definitions", lambda *_a, **_k: [schema])
    dispatched = []

    def record_dispatch(name, arguments, *_args, **_kwargs):
        dispatched.append((name, arguments))
        return json.dumps({"ok": True})

    monkeypatch.setattr("run_agent.handle_function_call", record_dispatch)
    responses = [_tool_response(finish_reason=finish_reason, ids=ids), _final_chat_response()]
    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call",
        lambda _request_agent, _request: responses.pop(0),
    )

    child.run_conversation(
        "run the controlled test tool",
        conversation_history=[],
        task_id="response-semantics-chat",
    )

    assert dispatched == []


@pytest.mark.parametrize("model", ["selected-responses-a", "selected-responses-b"])
def test_recorded_responses_sse_success_uses_parent_port_and_normal_tool_loop(
    monkeypatch, model
):
    parent = _RecordedParent(
        api_mode="codex_responses",
        model=model,
        streams=[
            _response_events(
                status="completed",
                tool_calls=(("call-1", "controlled_test_tool", '{"value":"ok"}'),),
                commentary="working",
                final=None,
            ),
            _response_events(
                status="completed",
                commentary="working",
                final="done",
            ),
        ],
    )
    port = ParentInferencePort.for_parent(parent)
    child = AIAgent(
        base_url="",
        api_key=None,
        provider=parent.provider,
        api_mode=parent.api_mode,
        model=model,
        inference_port=port,
        credential_pool=None,
        enabled_toolsets=[],
        max_iterations=3,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    schema = _tool_schema()
    child.tools = [schema]
    child.valid_tool_names = {"controlled_test_tool"}
    child.requested_model = f"configured:{model}"
    port.bind_child(
        child,
        max_calls=4,
        max_tokens=child.max_tokens,
        allowed_tool_names=child.valid_tool_names,
        reasoning_config=child.reasoning_config,
    )
    monkeypatch.setattr("run_agent.get_tool_definitions", lambda *_a, **_k: [schema])
    dispatched = []

    def record_dispatch(name, arguments, *_args, **_kwargs):
        dispatched.append((name, arguments))
        return json.dumps({"ok": True})

    monkeypatch.setattr("run_agent.handle_function_call", record_dispatch)
    monkeypatch.setattr(
        "agent.chat_completion_helpers._resolve_direct_stale_timeout",
        lambda *_args, **_kwargs: 1.0,
    )

    result = child.run_conversation(
        "run the controlled test tool",
        conversation_history=[],
        task_id="response-semantics-codex",
    )

    assert result["final_response"] == "done"
    assert len(dispatched) == 1
    assert dispatched[0][0] == "controlled_test_tool"
    assert dispatched[0][1] == {"value": "ok"}
    assert not parent.streams

@pytest.mark.parametrize(
    ("failure_case", "failure_code"),
    [
        ("unknown_status", "UNKNOWN_TERMINAL_STATUS"),
        ("duplicate_id", "DUPLICATE_TOOL_CALL_ID"),
        ("partial_arguments", "INCOMPLETE_TOOL_ARGUMENTS"),
    ],
)
def test_parent_port_returns_fixed_safe_codes_for_invalid_turns(
    monkeypatch, failure_case, failure_code
):
    parent = _RecordedParent(api_mode="chat_completions", model="selected-chat-model")
    child = _ChildOwner(parent)
    port = _bind_parent_port(parent, child)
    tool_schema = _tool_schema()
    finish_reason = "tool_calls"
    ids = ("call-1",)
    response = None

    if failure_case == "unknown_status":
        finish_reason = "provider_pending"
        response = _tool_response(finish_reason=finish_reason, ids=ids)
    elif failure_case == "duplicate_id":
        response = _tool_response(finish_reason=finish_reason, ids=("call-1", "call-1"))
    else:
        response = _tool_response(finish_reason=finish_reason, ids=ids)
        response.choices[0].message.tool_calls[0].function.arguments = (
            '{"value":"private-provider-detail"'
        )

    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call",
        lambda _request_agent, _request: response,
    )
    turn = _request_turn(child, tool_schema)

    with pytest.raises(InferencePortError) as caught:
        port.complete(
            turn,
            route_binding=port.route_binding,
            cancel_generation=0,
        )

    assert caught.value.failure_code == failure_code
    assert "private-provider-detail" not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "tool_calls"),
    [
        (
            "incomplete",
            (("call-1", "controlled_test_tool", '{"value":"ok"}'),),
        ),
        (
            "completed",
            (
                ("call-1", "controlled_test_tool", '{"value":"first"}'),
                ("call-1", "controlled_test_tool", '{"value":"second"}'),
            ),
        ),
        (
            "provider_pending",
            (("call-1", "controlled_test_tool", '{"value":"ok"}'),),
        ),
    ],
    ids=["incomplete-response", "duplicate-response-call", "unknown-response-status"],
)
def test_recorded_responses_sse_refuses_invalid_calls_before_tool_dispatch(
    monkeypatch, status, tool_calls
):
    model = "selected-responses-invalid"
    parent = _RecordedParent(
        api_mode="codex_responses",
        model=model,
        streams=[
            _response_events(
                status=status,
                tool_calls=tool_calls,
                commentary="working",
                final=None,
            ),
            _response_events(
                status="completed",
                commentary=None,
                final="done",
            ),
        ],
    )
    port = ParentInferencePort.for_parent(parent)
    child = AIAgent(
        base_url="",
        api_key=None,
        provider=parent.provider,
        api_mode=parent.api_mode,
        model=model,
        inference_port=port,
        credential_pool=None,
        enabled_toolsets=[],
        max_iterations=3,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    schema = _tool_schema()
    child.tools = [schema]
    child.valid_tool_names = {"controlled_test_tool"}
    child.requested_model = f"configured:{model}"
    port.bind_child(
        child,
        max_calls=4,
        max_tokens=child.max_tokens,
        allowed_tool_names=child.valid_tool_names,
        reasoning_config=child.reasoning_config,
    )
    monkeypatch.setattr("run_agent.get_tool_definitions", lambda *_a, **_k: [schema])
    dispatched = []

    def record_dispatch(name, arguments, *_args, **_kwargs):
        dispatched.append((name, arguments))
        return json.dumps({"ok": True})

    monkeypatch.setattr("run_agent.handle_function_call", record_dispatch)

    try:
        child.run_conversation(
            "run the controlled test tool",
            conversation_history=[],
            task_id="response-semantics-codex-invalid",
        )
    except InferencePortError:
        # A safe refusal may be surfaced to the caller after the standard
        # bounded retry path; it must never reach the tool dispatcher.
        pass

    assert dispatched == []
