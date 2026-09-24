"""Focused admission and constructor contracts for parent-owned delegation."""

from types import MethodType

import pytest

from agent.subagent_lifecycle import admit_parent_owned_inference
from downstream.delegation.inference_port import InferencePort
from downstream.delegation.inference_port import ParentInferencePort
from run_agent import AIAgent
from tests.tools.test_delegate import _make_mock_parent
from tools.delegate_tool import _build_child_agent


class _CapturedChild:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.valid_tool_names = set()
        self.reasoning_config = kwargs.get("reasoning_config")
        self.client = None
        self._client_kwargs = {}
        self._credential_pool = None
        self._session_init_model_config = None
        self.session_id = "synthetic-child"


def _visible_attribute_graph(root):
    """Walk stored attrs/containers and bound receivers, never function code."""
    pending = [root]
    seen = set()
    while pending and len(seen) < 500:
        value = pending.pop()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        yield value
        if isinstance(value, MethodType):
            pending.append(value.__self__)
        elif isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
        elif hasattr(value, "__dict__") and not isinstance(value, type):
            pending.extend(vars(value).values())


def test_host_admitted_child_constructor_receives_port_without_credentials(
    monkeypatch,
):
    parent = _make_mock_parent()
    parent.api_key = "synthetic-parent-key-A"
    parent._client_kwargs = {"api_key": parent.api_key}
    parent_client = object()
    parent.client = parent_client
    parent.max_tokens = 4096
    parent.reasoning_config = None
    parent.prefill_messages = []
    parent.session_id = "synthetic-parent"
    parent._subagent_id = None
    parent._current_turn_id = ""
    captured = {}

    def capture_constructor(**kwargs):
        captured.update(kwargs)
        return _CapturedChild(**kwargs)

    monkeypatch.setattr("run_agent.AIAgent", capture_constructor)
    monkeypatch.setattr(
        "tools.delegate_tool._resolve_child_credential_pool",
        lambda *_args, **_kwargs: pytest.fail("controlled child resolved a pool"),
    )

    with admit_parent_owned_inference():
        _build_child_agent(
            task_index=0,
            goal="bounded controlled child",
            context=None,
            toolsets=None,
            model=None,
            max_iterations=2,
            task_count=1,
            parent_agent=parent,
        )

    if captured.get("api_key") is not None:
        pytest.fail("host-admitted child constructor received a credential")
    if captured.get("credential_pool") is not None:
        pytest.fail("host-admitted child constructor received a credential pool")
    if not isinstance(captured.get("inference_port"), InferencePort):
        pytest.fail("host-admitted child constructor did not receive the inference port")

    child = captured["inference_port"]._requester_ref()
    assert child is not None
    assert child._delegate_parent_ref is None
    assert child.api_key is None
    assert child.client is None
    assert child._client_kwargs == {}
    assert child._credential_pool is None
    assert all(
        value is not parent
        and value is not parent_client
        and value != parent.api_key
        for value in _visible_attribute_graph(child)
    )
    assert not hasattr(captured["inference_port"], "_parent_ref")


def test_controlled_agent_init_skips_every_provider_client_resolver(monkeypatch):
    parent = _make_mock_parent()
    port = ParentInferencePort.for_parent(parent)
    resolver_calls = []

    def fail_if_resolved(*_args, **_kwargs):
        resolver_calls.append(True)
        raise AssertionError("controlled agent attempted local auth/client resolution")

    monkeypatch.setattr("agent.auxiliary_client.resolve_provider_client", fail_if_resolved)
    monkeypatch.setattr("agent.anthropic_adapter.resolve_anthropic_token", fail_if_resolved)

    child = AIAgent(
        base_url="",
        api_key=None,
        provider=parent.provider,
        api_mode=parent.api_mode,
        model=parent.model,
        inference_port=port,
        credential_pool=None,
        fallback_model=None,
        enabled_toolsets=[],
        quiet_mode=True,
        max_iterations=2,
    )

    assert child._inference_port is port
    assert child.api_key is None
    assert child.client is None
    assert child._client_kwargs == {}
    assert child._credential_pool is None
    assert child._fallback_chain == []
    assert resolver_calls == []


class _WeakrefableChild:
    pass


def _synthetic_controlled_pair(parent, port):
    child = _WeakrefableChild()
    child.provider = parent.provider
    child.model = parent.model
    child.api_mode = parent.api_mode
    child.reasoning_config = None
    child.valid_tool_names = set()
    child._inference_cancel_generation = 0
    child._interrupt_requested = False
    child._active_request_abort = None
    child.platform = "subagent"
    child.session_id = "controlled-child"
    child.quiet_mode = True
    port.bind_child(
        child,
        max_calls=4,
        max_tokens=4096,
        allowed_tool_names=set(),
        reasoning_config=None,
    )
    return child

def _synthetic_turn(child, content):
    from downstream.delegation.inference_port import InferenceTurn

    return InferenceTurn(
        api_kwargs={
            "model": child.model,
            "messages": [{"role": "user", "content": content}],
        },
        requester=child,
    )


class _ConcurrentAbortProbeChild(_WeakrefableChild):
    """Force concurrent callers to snapshot an empty abort slot together."""

    def __init__(self, abort_readers):
        self._abort_readers = abort_readers
        self._abort_callback = None

    def __getattribute__(self, name):
        if name == "_active_request_abort":
            callback = object.__getattribute__(self, "_abort_callback")
            if callback is None:
                from threading import BrokenBarrierError

                try:
                    object.__getattribute__(self, "_abort_readers").wait(
                        timeout=0.5
                    )
                except BrokenBarrierError:
                    pass
            return callback
        return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        if name == "_active_request_abort":
            object.__setattr__(self, "_abort_callback", value)
        else:
            object.__setattr__(self, name, value)


def test_same_child_concurrent_requests_cannot_overlap_abort_ownership(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event, Lock
    from types import SimpleNamespace

    from downstream.delegation.inference_port import InferencePortError

    parent = _make_mock_parent()
    port = ParentInferencePort.for_parent(parent)
    child = _ConcurrentAbortProbeChild(Barrier(2))
    child.provider = parent.provider
    child.model = parent.model
    child.api_mode = parent.api_mode
    child.reasoning_config = None
    child.valid_tool_names = set()
    child._inference_cancel_generation = 0
    child._interrupt_requested = False
    child.platform = "subagent"
    child.session_id = "concurrent-controlled-child"
    child.quiet_mode = True
    port.bind_child(
        child,
        max_calls=4,
        max_tokens=4096,
        allowed_tool_names=set(),
        reasoning_config=None,
    )

    launch = Barrier(3)
    release_transport = Event()
    first_transport_entered = Event()
    second_transport_entered = Event()
    state_lock = Lock()
    active_calls = 0
    max_active_calls = 0
    transport_calls = 0

    def blocked_transport(_requester, _request):
        nonlocal active_calls, max_active_calls, transport_calls
        with state_lock:
            transport_calls += 1
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            if transport_calls == 1:
                first_transport_entered.set()
            elif transport_calls == 2:
                second_transport_entered.set()
        release_transport.wait(timeout=3)
        with state_lock:
            active_calls -= 1
        return SimpleNamespace(choices=[])

    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call", blocked_transport
    )

    def request(label):
        launch.wait(timeout=2)
        try:
            port.complete(
                _synthetic_turn(child, label),
                route_binding=port.route_binding,
                cancel_generation=0,
            )
            return None
        except InferencePortError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(request, "same-child-first"),
            executor.submit(request, "same-child-second"),
        ]
        launch.wait(timeout=2)
        overlapping_transport_observed = second_transport_entered.wait(timeout=0.75)
        release_transport.set()
        outcomes = [future.result(timeout=3) for future in futures]

    assert first_transport_entered.is_set()
    assert not overlapping_transport_observed
    assert max_active_calls == 1
    assert sum(isinstance(outcome, InferencePortError) for outcome in outcomes) == 1
    assert sum(outcome is None for outcome in outcomes) == 1
    assert port._calls_used == 1
    assert child._abort_callback is None


def test_controlled_request_profile_binding_restores_caller_and_reuses_parent_profile(
    monkeypatch, tmp_path
):
    from hermes_constants import (
        get_hermes_home,
        reset_hermes_home_override,
        set_hermes_home_override,
    )

    profile_a = tmp_path / "profile-a"
    profile_b = tmp_path / "profile-b"
    token = set_hermes_home_override(profile_a)
    try:
        parent = _make_mock_parent()
        port = ParentInferencePort.for_parent(parent)
        child = _synthetic_controlled_pair(parent, port)
    finally:
        reset_hermes_home_override(token)

    seen_profiles = []

    def capture_profile(_requester, request):
        seen_profiles.append(get_hermes_home())
        return object()

    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call", capture_profile
    )

    caller_token = set_hermes_home_override(profile_b)
    try:
        port.complete(
            _synthetic_turn(child, "first"),
            route_binding=port.route_binding,
            cancel_generation=0,
        )
        assert get_hermes_home() == profile_b
    finally:
        reset_hermes_home_override(caller_token)

    caller_token = set_hermes_home_override(profile_a)
    try:
        port.complete(
            _synthetic_turn(child, "second"),
            route_binding=port.route_binding,
            cancel_generation=0,
        )
        assert get_hermes_home() == profile_a
    finally:
        reset_hermes_home_override(caller_token)

    assert seen_profiles == [profile_a, profile_a]


def test_controlled_profile_requests_are_context_isolated_concurrently(
    monkeypatch, tmp_path
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from hermes_constants import (
        get_hermes_home,
        reset_hermes_home_override,
        set_hermes_home_override,
    )

    profiles = {name: tmp_path / name for name in ("profile-a", "profile-b")}
    pairs = {}
    for name, profile in profiles.items():
        token = set_hermes_home_override(profile)
        try:
            parent = _make_mock_parent()
            port = ParentInferencePort.for_parent(parent)
            pairs[name] = (parent, port, _synthetic_controlled_pair(parent, port))
        finally:
            reset_hermes_home_override(token)

    rendezvous = Barrier(2)
    seen_profiles = {}

    def capture_profile(_requester, request):
        label = request["messages"][0]["content"]
        rendezvous.wait(timeout=5)
        seen_profiles[label] = get_hermes_home()
        return object()

    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call", capture_profile
    )

    def request_for(name):
        _parent, port, child = pairs[name]
        token = set_hermes_home_override(profiles[name])
        try:
            port.complete(
                _synthetic_turn(child, name),
                route_binding=port.route_binding,
                cancel_generation=0,
            )
            return get_hermes_home()
        finally:
            reset_hermes_home_override(token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            name: executor.submit(request_for, name)
            for name in pairs
        }
        results = {
            name: future.result(timeout=10)
            for name, future in futures.items()
        }

    assert seen_profiles == profiles
    assert results == profiles


def test_controlled_request_rejects_stale_and_late_cancelled_responses(monkeypatch):
    from types import SimpleNamespace

    parent = _make_mock_parent()
    port = ParentInferencePort.for_parent(parent)
    child = _synthetic_controlled_pair(parent, port)
    calls = []

    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call",
        lambda *_args, **_kwargs: calls.append("called"),
    )
    child._inference_cancel_generation = 1
    with pytest.raises(InterruptedError):
        port.complete(
            _synthetic_turn(child, "stale"),
            route_binding=port.route_binding,
            cancel_generation=0,
        )
    assert calls == []

    child._inference_cancel_generation = 0
    abort_reasons = []

    def late_response(requester, _request):
        requester._active_request_abort = lambda reason: abort_reasons.append(reason)
        requester._active_request_abort("interrupt_abort")
        child._inference_cancel_generation += 1
        return SimpleNamespace(choices=[])

    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call", late_response
    )
    with pytest.raises(InterruptedError):
        port.complete(
            _synthetic_turn(child, "cancel during request"),
            route_binding=port.route_binding,
            cancel_generation=0,
        )

    assert abort_reasons == ["interrupt_abort"]
    assert child._active_request_abort is None


def test_admitted_grandchild_has_no_parent_or_credential_reference(monkeypatch):
    parent = _make_mock_parent()
    parent.api_key = "synthetic-root-key-B"
    parent._client_kwargs = {"api_key": parent.api_key}
    parent.client = object()
    parent.max_tokens = 4096
    parent.reasoning_config = None
    parent.prefill_messages = []
    parent.session_id = "synthetic-root"
    parent._subagent_id = None
    parent._current_turn_id = ""
    children = []

    def capture_constructor(**kwargs):
        child = _CapturedChild(**kwargs)
        children.append(child)
        return child

    monkeypatch.setattr("run_agent.AIAgent", capture_constructor)
    monkeypatch.setattr(
        "tools.delegate_tool._resolve_child_credential_pool",
        lambda *_args, **_kwargs: pytest.fail("controlled child resolved a pool"),
    )

    def build(index, owner):
        return _build_child_agent(
            task_index=index,
            goal="bounded controlled child",
            context=None,
            toolsets=None,
            model=None,
            max_iterations=2,
            task_count=1,
            parent_agent=owner,
        )

    with admit_parent_owned_inference():
        child = build(0, parent)
        grandchild = build(1, child)

    assert len(children) == 2
    for controlled in (child, grandchild):
        assert controlled._delegate_parent_ref is None
        assert controlled.api_key is None
        assert controlled.client is None
        assert controlled._client_kwargs == {}
        assert controlled._credential_pool is None
        assert all(
            value is not parent
            and value is not parent.client
            and value != parent.api_key
            for value in _visible_attribute_graph(controlled)
        )

@pytest.mark.parametrize(
    ("api_mode", "provider", "model"),
    [
        ("chat_completions", "openrouter", "test-chat-model"),
        ("anthropic_messages", "anthropic", "claude-3-7-sonnet"),
    ],
)
def test_controlled_normal_loop_roundtrips_tools_for_response_families(
    monkeypatch, api_mode, provider, model
):
    from types import SimpleNamespace

    tool_schema = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
    monkeypatch.setattr("run_agent.get_tool_definitions", lambda *_a, **_k: [tool_schema])

    parent = _make_mock_parent()
    parent.provider = provider
    parent.api_mode = api_mode
    parent.model = model
    parent.base_url = "https://provider.invalid/v1"
    parent.api_key = "synthetic-parent-key-roundtrip"
    parent._client_kwargs = {"api_key": parent.api_key}
    parent.client = object()
    port = ParentInferencePort.for_parent(parent)

    child = AIAgent(
        base_url="",
        api_key=None,
        provider=provider,
        api_mode=api_mode,
        model=model,
        inference_port=port,
        credential_pool=None,
        enabled_toolsets=[],
        max_iterations=3,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    child.tools = [tool_schema]
    child.valid_tool_names = {"read_file"}
    port.bind_child(
        child,
        max_calls=3,
        max_tokens=child.max_tokens,
        allowed_tool_names=child.valid_tool_names,
        reasoning_config=child.reasoning_config,
    )

    if api_mode == "chat_completions":
        tool_response = SimpleNamespace(
            id="chat-tool-response",
            model=model,
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        role="assistant",
                        content=None,
                        refusal=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_read_file",
                                type="function",
                                function=SimpleNamespace(
                                    name="read_file",
                                    arguments='{"path":"safe.txt"}',
                                ),
                            )
                        ],
                    ),
                )
            ],
            usage=None,
        )
        final_response = SimpleNamespace(
            id="chat-final-response",
            model=model,
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        role="assistant", content="finished", refusal=None, tool_calls=[]
                    ),
                )
            ],
            usage=None,
        )
    else:
        tool_response = SimpleNamespace(
            id="anthropic-tool-response",
            type="message",
            role="assistant",
            model=model,
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="toolu_read_file",
                    name="read_file",
                    input={"path": "safe.txt"},
                )
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=2, output_tokens=2),
        )
        final_response = SimpleNamespace(
            id="anthropic-final-response",
            type="message",
            role="assistant",
            model=model,
            content=[SimpleNamespace(type="text", text="finished")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )

    responses = [tool_response, final_response]
    requests = []

    def controlled_api_call(requester, request):
        assert requester._active_request_abort is None
        for attr in ("api_key", "client", "_client_kwargs", "_credential_pool"):
            assert not hasattr(requester, attr)
        requests.append(request)
        assert responses
        return responses.pop(0)

    monkeypatch.setattr(
        "agent.chat_completion_helpers.interruptible_api_call", controlled_api_call
    )

    result = child.run_conversation(
        "read safe.txt and report",
        conversation_history=[],
        task_id="controlled-roundtrip",
    )

    assert result["final_response"] == "finished"
    assert len(requests) == 2
    assert requests[0]["model"] == model
    assert any(message.get("tool_calls") for message in result["messages"] if message.get("role") == "assistant")
    assert any(message.get("role") == "tool" and message.get("content") for message in result["messages"])
    assert not responses
    assert "File not found: safe.txt" in repr(requests[1].get("messages", []))
    assert child.api_key is None
    assert child.client is None
    assert child._client_kwargs == {}
    assert child._credential_pool is None


def test_auxiliary_inference_is_blocked_before_secret_resolution(monkeypatch):
    from agent.auxiliary_client import _call_llm_impl
    from downstream.delegation.inference_port import bind_inference_port

    parent = _make_mock_parent()
    port = ParentInferencePort.for_parent(parent)
    _synthetic_controlled_pair(parent, port)
    resolver_calls = []

    def fail_if_resolved(*_args, **_kwargs):
        resolver_calls.append(True)
        raise AssertionError("controlled auxiliary call attempted route resolution")

    monkeypatch.setattr(
        "agent.auxiliary_client._resolve_task_provider_model", fail_if_resolved
    )
    with bind_inference_port(port):
        with pytest.raises(RuntimeError, match="Auxiliary model calls are disabled"):
            _call_llm_impl(task="compression", messages=[])

    assert resolver_calls == []
